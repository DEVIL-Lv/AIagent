from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from . import models, schemas, crud, database
from .llm_service import LLMService
from .skill_service import SkillService
from .knowledge_service import KnowledgeService
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import SystemMessage, HumanMessage
import base64
import logging
import re
import os
import json
from datetime import datetime

router = APIRouter()
logger = logging.getLogger(__name__)

class ChatRequest(BaseModel):
    message: str
    model: str | None = None
    session_id: int | None = None

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _resolve_customer_from_message(db: Session, message: str) -> tuple[models.Customer | None, str]:
    text = (message or "").strip()
    if not text:
        return None, text

    customers = db.query(models.Customer).order_by(models.Customer.id.asc()).limit(300).all()

    def clean_query_after_prefix(prefix_pattern: str) -> str:
        cleaned = re.sub(prefix_pattern, "", text, count=1, flags=re.IGNORECASE).strip()
        cleaned = cleaned.lstrip("，。,:：;；-—").strip()
        return cleaned

    m_num = re.search(r"(?:客户|customer)\s*[【\[\(#（(]?\s*(\d{1,8})\s*[】\]\)#）)]?", text, flags=re.IGNORECASE)
    if m_num:
        num_str = m_num.group(1)
        # Prioritize Name lookup as per user request (e.g. customer named "11")
        customer = db.query(models.Customer).filter(models.Customer.name == num_str).first()
        if not customer:
             # Fallback to ID lookup
             try:
                 customer = db.query(models.Customer).filter(models.Customer.id == int(num_str)).first()
             except ValueError:
                 pass
        
        if customer:
            prefix_pattern = rf"^\s*(?:请\s*)?(?:帮我\s*)?(?:分析|看看|总结|评估|生成|帮我分析|帮我看看)?\s*(?:客户|customer)\s*[【\[\(#（(]?\s*{re.escape(num_str)}\s*[】\]\)#）)]?\s*(?:号)?"
            return customer, clean_query_after_prefix(prefix_pattern)

    m_name = re.search(r"(?:客户|customer)\s*[【\[\(#（(]?\s*([^\s，。,.!?！？:：;；\n]{1,32})", text, flags=re.IGNORECASE)
    if m_name:
        raw_name = m_name.group(1).strip().strip("】]#）)】")
        candidate_name = raw_name
        candidate_name = re.sub(r"(的|进行|一下|一份|一下子)$", "", candidate_name)
        if candidate_name:
            customer = db.query(models.Customer).filter(models.Customer.name == candidate_name).first()
            if not customer and customers:
                for c in sorted(customers, key=lambda x: len((x.name or "")), reverse=True):
                    n = (c.name or "").strip()
                    if n and n in text:
                        customer = c
                        candidate_name = n
                        break
            if customer:
                prefix_pattern = rf"^\s*(?:请\s*)?(?:帮我\s*)?(?:分析|看看|总结|评估|生成|帮我分析|帮我看看)?\s*(?:客户|customer)\s*[【\[\(#（(]?\s*{re.escape(candidate_name)}\s*[】\]\)#）)]?\s*"
                return customer, clean_query_after_prefix(prefix_pattern)

    return None, text

def _search_sales_talks(db: Session, query: str, k: int = 3) -> list[dict]:
    q = (query or "").strip()
    if not q:
        return []
    talks = db.query(models.SalesTalk).all()
    if not talks:
        return []
    ql = q.lower()
    tokens = [t for t in re.split(r"\s+", ql) if t]
    scored: list[tuple[float, models.SalesTalk]] = []
    for t in talks:
        title = (t.title or "").strip()
        base = (t.content or t.raw_content or "").strip()
        tl = title.lower()
        bl = base.lower()
        score = 0.0
        if ql in tl:
            score += 5.0
        if ql in bl:
            score += 2.5
        for tok in tokens:
            if tok in tl:
                score += 2.0
            if tok in bl:
                score += 1.0
        if tl == ql:
            score += 6.0
        if score > 0:
            scored.append((score, t))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [t for _, t in scored[:k]]
    results = []
    for t in top:
        base = t.content or t.raw_content or ""
        bl = base.lower()
        pos = bl.find(ql) if ql else -1
        if pos < 0 and tokens:
            for tok in tokens:
                if tok:
                    pos = bl.find(tok)
                    if pos >= 0:
                        break
        start = max(0, pos - 120) if pos >= 0 else 0
        end = min(len(base), start + 240)
        snippet = base[start:end]
        results.append({
            "content": f"Title: {t.title}\n\n{snippet}",
            "metadata": {"source": f"sales_talk:{t.category}", "id": t.id, "title": t.title}
        })
    return results

def _sse_message(data: dict, event: str | None = None) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    if event:
        return f"event: {event}\ndata: {payload}\n\n"
    return f"data: {payload}\n\n"

@router.post("/chat/global", response_model=dict)
def chat_global(request: ChatRequest, db: Session = Depends(get_db)):
    """
    全局 AI 助手对话 (无特定客户上下文)
    """
    llm_service = LLMService(db)

    # 1. Handle Session
    session_id = request.session_id
    if not session_id:
        # Create new session if not provided
        session = crud.create_chat_session(db, schemas.ChatSessionCreate(first_message=request.message))
        session_id = session.id
    
    # Save User Message
    crud.create_chat_message(db, schemas.ChatMessageCreate(
        role="user", 
        content=request.message
    ), session_id=session_id)

    # ... Existing logic ...
    customer, cleaned = _resolve_customer_from_message(db, request.message)
    if customer:
        analysis_query = cleaned
        if not analysis_query:
            analysis_query = "请生成一份客户速览，包含画像、阶段、风险偏好、关键机会与风险、下一步建议。"
        analysis_query = analysis_query.replace(customer.name or "", "该客户")

        try:
            response = llm_service.chat_with_agent(
                customer_id=customer.id,
                query=analysis_query,
                history=None,
                rag_context="",
                model=request.model,
            )
            response_text = f"已定位客户【{customer.name}】(ID: {customer.id})。\n\n{response}"
            # Save AI Response
            crud.create_chat_message(db, schemas.ChatMessageCreate(
                role="ai", 
                content=response_text
            ), session_id=session_id)
            return {"response": response_text, "session_id": session_id}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # Prefer explicit config_name if provided
    llm = llm_service.get_llm(config_name=request.model, skill_name="chat")
    
    # Load History from Session
    history_msgs = crud.get_chat_session_messages(db, session_id)
    # Exclude the current user message we just saved (to avoid duplication if we append it manually later, 
    # but here we build prompt from history)
    # Actually, simpler to just take the last N messages
    
    # 0. RAG: Search Knowledge Base
    knowledge_service = KnowledgeService(db)
    docs = knowledge_service.search(request.message, k=3)
    knowledge_context = ""
    if docs:
        knowledge_context = "\n\n【参考知识库信息】\n" + "\n".join([f"- {d['content']}" for d in docs])
        logger.debug("Global chat RAG hit", extra={"doc_count": len(docs)})
    talk_docs = _search_sales_talks(db, request.message, k=3)
    talk_context = ""
    if talk_docs:
        talk_context = "\n\n【参考话术库信息】\n" + "\n".join([f"- {d['content']}" for d in talk_docs])

    system_instruction = """你是转化运营团队的 AI 辅助决策与话术系统。
    
    【定位】站在转化同学身边，帮助看得更全、想得更清楚、说得更稳。
    【能力】客户分析、话术辅助、推进建议。如果用户提到具体客户，会自动调取该客户上下文。
    【底线】不承诺收益，不保证结果，不夸大，涉及产品请提示“以正式材料为准”。
    【输出】中文，结构清晰，直接给结论和建议。"""
    messages = [SystemMessage(content=system_instruction)]
    if talk_context:
        messages.append(HumanMessage(content=f"【参考话术库】\n{talk_context}"))
    if knowledge_context:
        messages.append(HumanMessage(content=f"【参考知识库】\n{knowledge_context}"))
    
    # Add recent history (excluding the very last one which is current user message, 
    # because we will append it as HumanMessage at the end?)
    # Wait, create_chat_message saves it. get_chat_session_messages returns it.
    # Let's filter it out or just use the list.
    # Common pattern: System + History (User/AI) + Current User
    
    # Let's just use the history up to before this request
    # But we already saved it. So history_msgs includes it.
    # We should use history_msgs[:-1] as history, and request.message as current.
    
    for msg in history_msgs[:-1]: # Exclude current
        if msg.role == "user":
            messages.append(HumanMessage(content=msg.content))
        elif msg.role == "ai":
            from langchain_core.messages import AIMessage
            messages.append(AIMessage(content=msg.content))
            
    messages.append(HumanMessage(content=request.message))

    try:
        chain = llm | StrOutputParser()
        response = chain.invoke(messages)
        
        # Save AI Response
        crud.create_chat_message(db, schemas.ChatMessageCreate(
            role="ai", 
            content=response
        ), session_id=session_id)
        
        return {"response": response, "session_id": session_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/chat/global/stream")
async def chat_global_stream(request: ChatRequest, db: Session = Depends(get_db)):
    llm_service = LLMService(db)
    customer, cleaned = _resolve_customer_from_message(db, request.message)

    # 1. Handle Session
    session_id = request.session_id
    if not session_id:
        session = crud.create_chat_session(db, schemas.ChatSessionCreate(first_message=request.message))
        session_id = session.id
        
    # Save User Message
    crud.create_chat_message(db, schemas.ChatMessageCreate(
        role="user", 
        content=request.message
    ), session_id=session_id)

    async def event_generator():
        yield _sse_message({"session_id": session_id}, event="session_info")
        
        if customer:
            analysis_query = cleaned
            if not analysis_query:
                analysis_query = "请生成一份客户速览，包含画像、阶段、风险偏好、关键机会与风险、下一步建议。"
            analysis_query = analysis_query.replace(customer.name or "", "该客户")
            prefix = f"已定位客户【{customer.name}】(ID: {customer.id})。\n\n"
            yield _sse_message({"token": prefix})
            
            full_response = prefix
            try:
                async for token in llm_service.chat_with_agent_stream(
                    customer_id=customer.id,
                    query=analysis_query,
                    history=None,
                    rag_context="",
                    model=request.model,
                ):
                    full_response += token
                    yield _sse_message({"token": token})
                
                # Save AI Response
                crud.create_chat_message(db, schemas.ChatMessageCreate(
                    role="ai", 
                    content=full_response
                ), session_id=session_id)
                    
            except Exception as e:
                yield _sse_message({"message": f"（系统错误）AI 响应失败: {str(e)}"}, event="error")
            yield "event: done\ndata: [DONE]\n\n"
            return

        llm = llm_service.get_llm(config_name=request.model, skill_name="chat", streaming=True)
        knowledge_service = KnowledgeService(db)
        try:
            docs = knowledge_service.search(request.message, k=3)
        except Exception:
            logger.exception("Global chat RAG search failed")
            docs = []
        knowledge_context = ""
        if docs:
            knowledge_context = "\n\n【参考知识库信息】\n" + "\n".join([f"- {d['content']}" for d in docs])
            logger.debug("Global chat RAG hit", extra={"doc_count": len(docs)})
        talk_docs = _search_sales_talks(db, request.message, k=3)
        talk_context = ""
        if talk_docs:
            talk_context = "\n\n【参考话术库信息】\n" + "\n".join([f"- {d['content']}" for d in talk_docs])

        system_instruction = """你是转化运营团队的 AI 辅助决策与话术系统。
        
        【定位】站在转化同学身边，帮助看得更全、想得更清楚、说得更稳。
        【能力】客户分析、话术辅助、推进建议。如果用户提到具体客户，会自动调取该客户上下文。
        【底线】不承诺收益，不保证结果，不夸大，涉及产品请提示“以正式材料为准”。
        【输出】中文，结构清晰，直接给结论和建议。"""
        history_msgs = crud.get_chat_session_messages(db, session_id)
        messages = [SystemMessage(content=system_instruction)]
        if talk_context:
            messages.append(HumanMessage(content=f"【参考话术库】\n{talk_context}"))
        if knowledge_context:
            messages.append(HumanMessage(content=f"【参考知识库】\n{knowledge_context}"))
        
        for msg in history_msgs[:-1]: # Exclude current
            if msg.role == "user":
                messages.append(HumanMessage(content=msg.content))
            elif msg.role == "ai":
                from langchain_core.messages import AIMessage
                messages.append(AIMessage(content=msg.content))
        messages.append(HumanMessage(content=request.message))

        response_content = ""
        try:
            async for chunk in llm.astream(messages):
                token = getattr(chunk, "content", None)
                if token:
                    response_content += token
                    yield _sse_message({"token": token})
            
            # Save AI Response
            crud.create_chat_message(db, schemas.ChatMessageCreate(
                role="ai", 
                content=response_content
            ), session_id=session_id)
            
        except Exception as e:
            yield _sse_message({"message": f"（系统错误）AI 响应失败: {str(e)}"}, event="error")
        yield "event: done\ndata: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.post("/chat/global/upload-image", response_model=dict)
async def chat_global_upload_image(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    全局图片分析（尽量使用具备多模态能力的模型；否则返回不支持）
    """
    llm_service = LLMService(db)
    llm = llm_service.get_llm(skill_name="chat")
    # 仅当底层模型支持 image_url 的多模态输入时才可用；否则返回提示
    try:
        max_mb = int(os.getenv("MAX_UPLOAD_MB", "500"))
        max_bytes = max_mb * 1024 * 1024
        size = None
        try:
            file.file.seek(0, os.SEEK_END)
            size = file.file.tell()
            file.file.seek(0)
        except Exception:
            size = None
        if size is not None:
            if size == 0:
                raise HTTPException(status_code=400, detail="Uploaded image file is empty")
            if size > max_bytes:
                raise HTTPException(status_code=413, detail=f"Uploaded file is too large (>{max_mb}MB)")
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded image file is empty")
        if len(content) > max_mb * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"Uploaded file is too large (>{max_mb}MB)")
        b64 = base64.b64encode(content).decode("utf-8")
        from langchain_core.messages import HumanMessage
        # 通过 OpenAI 兼容接口的多模态消息结构
        resp = llm.invoke([
            HumanMessage(content=[
                {"type": "text", "text": "请分析图片要点并给出结论/建议，输出尽量使用中文，避免无必要英文。"},
                {"type": "image_url", "image_url": {"url": f"data:{file.content_type};base64,{b64}"}}
            ])
        ])
        return {"response": getattr(resp, "content", str(resp))}
    except HTTPException:
        raise
    except Exception:
        return {"response": "当前模型暂不支持图片内容分析，如需启用请在设置中选择支持多模态的模型（如 GPT-4o）。"}
@router.post("/customers/{customer_id}/chat", response_model=schemas.CustomerData)
def chat_with_customer_context(customer_id: int, request: ChatRequest, db: Session = Depends(get_db)):
    """
    与 AI 对话，AI 拥有该客户的所有上下文信息。
    包含简单的意图识别路由 (Skill Routing)。
    """
    customer = crud.get_customer(db, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    # Handle Session
    session_id = request.session_id
    if not session_id:
         session = crud.create_chat_session(db, schemas.ChatSessionCreate(
             customer_id=customer_id, 
             first_message=request.message
         ))
         session_id = session.id
        
    # 1. 保存用户消息
    user_entry = schemas.CustomerDataCreate(
        source_type="chat_history_user",
        content=request.message,
        meta_info={"triggered_by": "user", "session_id": session_id}
    )
    user_data = crud.create_customer_data(db=db, data=user_entry, customer_id=customer_id)
    
    # Update Session ID if it's missing (should be handled by crud but we need to ensure)
    # Actually CustomerData doesn't have session_id field in schema create?
    # We added it to model. We need to manually update it if schema doesn't support it yet or if crud.create doesn't map it.
    # We updated CustomerData model, let's update crud.create_customer_data to handle extra kwargs or update directly.
    # Let's do a direct update for now or ensure schemas.CustomerDataCreate has it? 
    # Schemas doesn't have it. Let's add it to meta_info and rely on a backend migration or just use meta_info for now?
    # Wait, I added session_id to CustomerData MODEL. I should set it.
    
    user_data.session_id = session_id
    db.commit()
    
    # 2. 构建上下文 (Filter by Session? Or keep global context?)
    # User likely wants "Fresh Chat" to mean "Fresh Context". 
    # So if session_id is provided, we should probably ONLY use context from that session?
    # But RAG and Customer Profile should persist. Only "Chat History" should reset.
    
    # For now, let's keep get_customer_context as is (recent 20). 
    # BUT if we want "New Chat" behavior, we should filter by session_id IF the user wants isolated sessions.
    # The requirement "Forget previous context" implies we should ONLY fetch history from THIS session.
    
    # Custom Context Builder for Session
    context = ""
    # Fetch recent messages from THIS session
    session_msgs = crud.get_chat_session_messages(db, session_id)
    # Convert to string context
    # Exclude the current message? session_msgs includes it because we just saved it.
    for msg in session_msgs[:-1]: 
        role_label = "客户" if msg.role == "user" else "销售"
        context += f"[{role_label}]: {msg.content}\n"

    # ... RAG ...

    # 2. 预判意图 (Intent Detection) - 提前判断是否需要检索上下文
    info_keywords = ["基本信息", "客户信息", "档案", "资料", "表格", "字段", "记录", "查看", "列出", "展示", "有哪些", "查询"]
    analysis_keywords = ["总结", "分析", "判断", "建议", "画像", "风险", "推进", "成交", "评估", "研判"]
    is_info_query = any(k in request.message for k in info_keywords) and not any(k in request.message for k in analysis_keywords)
    
    skill_service = SkillService(db)
    triggered_skill = None
    
    # Dynamic Routing from DB
    routing_rules = crud.get_routing_rules(db)
    for rule in routing_rules:
        if rule.keyword in request.message:
            triggered_skill = rule.target_skill
            break
            
    if not triggered_skill:
        # Fallback to hardcoded defaults
        if "风险" in request.message and "分析" in request.message:
            triggered_skill = "risk_analysis"
        elif "赢单" in request.message or "成功率" in request.message:
            triggered_skill = "deal_evaluation"

    # Optimization: Skip expensive retrieval for simple info queries
    need_context = True
    if not triggered_skill and is_info_query:
        need_context = False

    knowledge_context = ""
    talk_context = ""
    retrieved_context = ""

    if need_context:
        # 2.1 RAG: Search Knowledge Base for Customer Chat
        knowledge_service = KnowledgeService(db)
        docs = knowledge_service.search(request.message, k=2)
        if docs:
            knowledge_context = "\n【相关知识库参考】\n" + "\n".join([f"- {d['content']}" for d in docs])
        talk_docs = _search_sales_talks(db, request.message, k=2)
        if talk_docs:
            talk_context = "\n【相关话术库参考】\n" + "\n".join([f"- {d['content']}" for d in talk_docs])

        llm_service = LLMService(db)
        retrieved_context = llm_service.retrieve_customer_data_context(
            customer_id=customer_id,
            query=request.message,
            model=request.model,
        )

    response = ""
    
    # 3. 技能执行 (Skill Execution)
    if triggered_skill:
        # Map skill names to methods
        if triggered_skill == "risk_analysis":
             context_for_skill = context
             if retrieved_context:
                 context_for_skill += "\n" + retrieved_context
             if knowledge_context:
                 context_for_skill += "\n" + knowledge_context
             if talk_context:
                 context_for_skill += "\n" + talk_context
             response = "【自动触发：风险分析】\n" + skill_service.analyze_risk(context_for_skill)
        elif triggered_skill == "deal_evaluation":
             context_for_skill = context
             if retrieved_context:
                 context_for_skill += "\n" + retrieved_context
             if knowledge_context:
                 context_for_skill += "\n" + knowledge_context
             if talk_context:
                 context_for_skill += "\n" + talk_context
             response = "【自动触发：赢单评估】\n" + skill_service.evaluate_deal(context_for_skill)
    elif is_info_query:
        # Fast Path: Structured Info
        llm_service = LLMService(db)
        triggered_skill = "info_query"
        response = llm_service.build_structured_info_response(customer_id)
    else:
        # 4. 普通对话 (Normal Chat)
        llm_service = LLMService(db)
        llm = llm_service.get_llm(config_name=request.model, skill_name="chat")
        system_instruction = """你是转化运营团队的 AI 辅助决策与话术系统。
        
        【定位】站在转化同学身边，帮助看得更全、想得更清楚、说得更稳。
        【能力】客户分析、话术辅助、推进建议。如果用户提到具体客户，会自动调取该客户上下文。
        【底线】不承诺收益，不保证结果，不夸大，涉及产品请提示“以正式材料为准”。
        【输出】中文，结构清晰，直接给结论和建议。"""
        messages = [SystemMessage(content=system_instruction)]
        if talk_context:
            messages.append(HumanMessage(content=f"【参考话术库】\n{talk_context}"))
        if knowledge_context:
            messages.append(HumanMessage(content=f"【参考知识库】\n{knowledge_context}"))
        if retrieved_context:
            messages.append(HumanMessage(content=f"【已检索客户档案】\n{retrieved_context}"))
        messages.append(HumanMessage(content=f"【客户历史上下文】\n{context}"))
        messages.append(HumanMessage(content=request.message))
        chain = llm | StrOutputParser()
        response = chain.invoke(messages)
    
    # 5. 保存 AI 回复
    ai_entry = schemas.CustomerDataCreate(
        source_type=f"chat_history_ai_{triggered_skill}" if triggered_skill else "chat_history_ai",
        content=response,
        meta_info={"triggered_by": triggered_skill or "chat", "session_id": session_id}
    )
    ai_data = crud.create_customer_data(db=db, data=ai_entry, customer_id=customer_id)
    ai_data.session_id = session_id
    db.query(models.ChatSession).filter(models.ChatSession.id == session_id).update(
        {models.ChatSession.updated_at: datetime.utcnow()}
    )
    db.commit()
    
    # Return data with session_id injected into meta if needed, or just return as is
    return ai_data

@router.post("/customers/{customer_id}/chat/stream")
async def chat_with_customer_context_stream(customer_id: int, request: ChatRequest, db: Session = Depends(get_db)):
    customer = crud.get_customer(db, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    session_id = request.session_id
    if not session_id:
        session = crud.create_chat_session(db, schemas.ChatSessionCreate(
            customer_id=customer_id,
            first_message=request.message
        ))
        session_id = session.id

    user_entry = schemas.CustomerDataCreate(
        source_type="chat_history_user",
        content=request.message,
        meta_info={"triggered_by": "user", "session_id": session_id}
    )
    user_data = crud.create_customer_data(db=db, data=user_entry, customer_id=customer_id)
    user_data.session_id = session_id
    db.query(models.ChatSession).filter(models.ChatSession.id == session_id).update(
        {models.ChatSession.updated_at: datetime.utcnow()}
    )
    db.commit()

    session_msgs = crud.get_chat_session_messages(db, session_id)
    context = ""
    for msg in session_msgs[:-1]:
        role_label = "客户" if msg.role == "user" else "销售"
        context += f"{role_label}: {msg.content}\n"
    knowledge_service = KnowledgeService(db)
    docs = knowledge_service.search(request.message, k=2)
    knowledge_context = ""
    if docs:
        knowledge_context = "\n【相关知识库参考】\n" + "\n".join([f"- {d['content']}" for d in docs])
    talk_docs = _search_sales_talks(db, request.message, k=2)
    talk_context = ""
    if talk_docs:
        talk_context = "\n【相关话术库参考】\n" + "\n".join([f"- {d['content']}" for d in talk_docs])

    llm_service = LLMService(db)
    retrieved_context = llm_service.retrieve_customer_data_context(
        customer_id=customer_id,
        query=request.message,
        model=request.model,
    )

    info_keywords = ["基本信息", "客户信息", "档案", "资料", "表格", "字段", "记录", "查看", "列出", "展示", "有哪些", "查询"]
    analysis_keywords = ["总结", "分析", "判断", "建议", "画像", "风险", "推进", "成交", "评估", "研判"]
    is_info_query = any(k in request.message for k in info_keywords) and not any(k in request.message for k in analysis_keywords)

    skill_service = SkillService(db)
    response = ""
    triggered_skill = None
    routing_rules = crud.get_routing_rules(db)
    for rule in routing_rules:
        if rule.keyword in request.message:
            triggered_skill = rule.target_skill
            if triggered_skill == "risk_analysis":
                context_for_skill = context
                if retrieved_context:
                    context_for_skill += "\n" + retrieved_context
                if knowledge_context:
                    context_for_skill += "\n" + knowledge_context
                if talk_context:
                    context_for_skill += "\n" + talk_context
                response = "【自动触发：风险分析】\n" + skill_service.analyze_risk(context_for_skill)
            elif triggered_skill == "deal_evaluation":
                context_for_skill = context
                if retrieved_context:
                    context_for_skill += "\n" + retrieved_context
                if knowledge_context:
                    context_for_skill += "\n" + knowledge_context
                if talk_context:
                    context_for_skill += "\n" + talk_context
                response = "【自动触发：赢单评估】\n" + skill_service.evaluate_deal(context_for_skill)
            break

    if not triggered_skill:
        if "风险" in request.message and "分析" in request.message:
            triggered_skill = "risk_analysis"
            context_for_skill = context
            if retrieved_context:
                context_for_skill += "\n" + retrieved_context
            if knowledge_context:
                context_for_skill += "\n" + knowledge_context
            if talk_context:
                context_for_skill += "\n" + talk_context
            response = "【自动触发：风险分析】\n" + skill_service.analyze_risk(context_for_skill)
        elif "赢单" in request.message or "成功率" in request.message:
            triggered_skill = "deal_evaluation"
            context_for_skill = context
            if retrieved_context:
                context_for_skill += "\n" + retrieved_context
            if knowledge_context:
                context_for_skill += "\n" + knowledge_context
            if talk_context:
                context_for_skill += "\n" + talk_context
            response = "【自动触发：赢单评估】\n" + skill_service.evaluate_deal(context_for_skill)
    if not triggered_skill and is_info_query:
        triggered_skill = "info_query"
        response = llm_service.build_structured_info_response(customer_id)

    async def event_generator():
        yield _sse_message({"session_id": session_id}, event="session_info")
        response_content = ""
        if triggered_skill:
            response_content = response
            if response_content:
                yield _sse_message({"token": response_content})
        else:
            llm = llm_service.get_llm(config_name=request.model, skill_name="chat", streaming=True)
            system_instruction = """你是转化运营团队的 AI 辅助决策与话术系统。
            
            【定位】站在转化同学身边，帮助看得更全、想得更清楚、说得更稳。
            【能力】客户分析、话术辅助、推进建议。如果用户提到具体客户，会自动调取该客户上下文。
            【底线】不承诺收益，不保证结果，不夸大，涉及产品请提示“以正式材料为准”。
            【输出】中文，结构清晰，直接给结论和建议。"""
            messages = [SystemMessage(content=system_instruction)]
            if talk_context:
                messages.append(HumanMessage(content=f"【参考话术库】\n{talk_context}"))
            if knowledge_context:
                messages.append(HumanMessage(content=f"【参考知识库】\n{knowledge_context}"))
            if retrieved_context:
                messages.append(HumanMessage(content=f"【已检索客户档案】\n{retrieved_context}"))
            messages.append(HumanMessage(content=f"【客户历史上下文】\n{context}"))
            messages.append(HumanMessage(content=request.message))
            try:
                async for chunk in llm.astream(messages):
                    token = getattr(chunk, "content", None)
                    if token:
                        response_content += token
                        yield _sse_message({"token": token})
            except Exception as e:
                error_msg = f"（系统错误）AI 响应失败: {str(e)}"
                if not response_content:
                    response_content = error_msg
                yield _sse_message({"message": error_msg}, event="error")

        if response_content:
            ai_entry = schemas.CustomerDataCreate(
                source_type=f"chat_history_ai_{triggered_skill}" if triggered_skill else "chat_history_ai",
                content=response_content,
                meta_info={"triggered_by": triggered_skill or "chat", "session_id": session_id}
            )
            ai_data = crud.create_customer_data(db=db, data=ai_entry, customer_id=customer_id)
            ai_data.session_id = session_id
            db.query(models.ChatSession).filter(models.ChatSession.id == session_id).update(
                {models.ChatSession.updated_at: datetime.utcnow()}
            )
            db.commit()
        yield "event: done\ndata: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
