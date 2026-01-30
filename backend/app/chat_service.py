from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import BaseModel
from . import models, schemas, crud, database
from .llm_service import LLMService
from .skill_service import SkillService
from .knowledge_service import KnowledgeService
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import base64

router = APIRouter()

class ChatRequest(BaseModel):
    message: str
    model: str | None = None

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/chat/global", response_model=dict)
def chat_global(request: ChatRequest, db: Session = Depends(get_db)):
    """
    全局 AI 助手对话 (无特定客户上下文)
    """
    llm_service = LLMService(db)
    # Prefer explicit config_name if provided
    llm = llm_service.get_llm(config_name=request.model, skill_name="chat")
    
    # 0. RAG: Search Knowledge Base
    knowledge_service = KnowledgeService(db)
    docs = knowledge_service.search(request.message, k=3)
    knowledge_context = ""
    if docs:
        knowledge_context = "\n\n【参考知识库信息】\n" + "\n".join([f"- {d['content']}" for d in docs])
        print(f"Global Chat RAG Hit: {len(docs)} documents")

    system_instruction = "你是一个专业的财富管理系统全局助手。你可以回答关于销售技巧、话术建议、或者系统使用的一般性问题。"
    if knowledge_context:
        system_instruction += f"\n请结合以下知识库内容进行回答：{knowledge_context}"

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_instruction),
        ("human", "{input}")
    ])
    
    try:
        chain = prompt | llm | StrOutputParser()
        response = chain.invoke({"input": request.message})
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/chat/global/upload-image", response_model=dict)
async def chat_global_upload_image(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    全局图片分析（尽量使用具备多模态能力的模型；否则返回不支持）
    """
    llm_service = LLMService(db)
    llm = llm_service.get_llm(skill_name="chat")
    # 仅当底层模型支持 image_url 的多模态输入时才可用；否则返回提示
    try:
        content = await file.read()
        b64 = base64.b64encode(content).decode("utf-8")
        from langchain_core.messages import HumanMessage
        # 通过 OpenAI 兼容接口的多模态消息结构
        resp = llm.invoke([
            HumanMessage(content=[
                {"type": "text", "text": "请分析这张图片的要点，并给出结论/建议。"},
                {"type": "image_url", "image_url": {"url": f"data:{file.content_type};base64,{b64}"}}
            ])
        ])
        return {"response": getattr(resp, "content", str(resp))}
    except Exception:
        # 模型不支持或调用失败
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
        
    # 1. 保存用户消息
    user_entry = schemas.CustomerDataCreate(
        source_type="chat_history_user",
        content=request.message,
        meta_info={"triggered_by": "user"}
    )
    crud.create_customer_data(db=db, data=user_entry, customer_id=customer_id)
    
    # 2. 构建上下文
    context = crud.get_customer_context(db, customer_id, limit=20)

    # 2.1 RAG: Search Knowledge Base for Customer Chat
    knowledge_service = KnowledgeService(db)
    docs = knowledge_service.search(request.message, k=2)
    knowledge_context = ""
    if docs:
        knowledge_context = "\n【相关知识库参考】\n" + "\n".join([f"- {d['content']}" for d in docs])
        
    # 3. 意图识别 (Skill Routing)
    skill_service = SkillService(db)
    response = ""
    triggered_skill = None
    
    # Dynamic Routing from DB
    routing_rules = crud.get_routing_rules(db)
    for rule in routing_rules:
        if rule.keyword in request.message:
            triggered_skill = rule.target_skill
            # Map skill names to methods
            if triggered_skill == "risk_analysis":
                 response = "【自动触发：风险分析】\n" + skill_service.analyze_risk(context)
            elif triggered_skill == "deal_evaluation":
                 response = "【自动触发：赢单评估】\n" + skill_service.evaluate_deal(context)
            # Add more skills here
            break
            
    if not triggered_skill:
        # Fallback to hardcoded defaults if DB is empty (Optional, for safety)
        if "风险" in request.message and "分析" in request.message:
            triggered_skill = "risk_analysis"
            response = "【自动触发：风险分析】\n" + skill_service.analyze_risk(context)
        elif "赢单" in request.message or "成功率" in request.message:
            triggered_skill = "deal_evaluation"
            response = "【自动触发：赢单评估】\n" + skill_service.evaluate_deal(context)
    
    if triggered_skill:
        # Already handled above
        pass
    else:
        # 4. 普通对话 (Normal Chat)
        llm_service = LLMService(db)
        llm = llm_service.get_llm(config_name=request.model, skill_name="chat")
        
        system_instruction = "你是一个专业的财富管理助手。你正在查看一位客户的详细资料。请根据上下文回答用户的问题，或者对用户输入的客户对话进行分析。保持专业、客观。"
        if knowledge_context:
            system_instruction += f"\n{knowledge_context}\n如果知识库内容与问题相关，请优先参考。"

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_instruction),
            ("system", "以下是客户的历史记录上下文：\n{context}"),
            ("human", "{input}")
        ])
        
        chain = prompt | llm | StrOutputParser()
        response = chain.invoke({"context": context, "input": request.message})
    
    # 5. 保存 AI 回复
    ai_entry = schemas.CustomerDataCreate(
        source_type=f"chat_history_ai_{triggered_skill}" if triggered_skill else "chat_history_ai",
        content=response,
        meta_info={"triggered_by": triggered_skill or "chat"}
    )
    return crud.create_customer_data(db=db, data=ai_entry, customer_id=customer_id)
