from sqlalchemy.orm import Session
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from . import models, schemas, crud
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class LLMService:
    # Common mappings for user-friendly names to API strings
    MODEL_MAPPING = {
        # Anthropic
        "Claude Haiku 4.5": "claude-haiku-4-5",
        "Haiku 4.5": "claude-haiku-4-5",
        "haiku4.5": "claude-haiku-4-5",
        "haiku-4.5": "claude-haiku-4-5",
        "Claude Haiku 3.5": "claude-3-5-haiku-latest",
        "Claude 3.5 Haiku": "claude-3-5-haiku-latest",
        "Claude 3 Haiku": "claude-3-haiku-20240307",
        "Claude 3.5 Sonnet": "claude-3-5-sonnet-20240620",
        "Claude 3 Opus": "claude-3-opus-20240229",
        "Claude 3 Sonnet": "claude-3-sonnet-20240229",
        # OpenAI
        "GPT-4 Turbo": "gpt-4-turbo",
        "GPT-3.5 Turbo": "gpt-3.5-turbo",
        "GPT-4o": "gpt-4o",
    }
    
    SKILL_NAME_ALIASES = {
        # Core Assistant Group
        "summary": "core",
        "customer_summary": "core",
        "suggest_reply": "core",
        "reply_suggestion": "core",
        "evaluate_progression": "core",
        "agent_chat": "core",
        
        # Independent Skills
        "data_selector": "data_selector",
        "knowledge_processing": "knowledge_processing",
        "chat": "chat"
    }

    def __init__(self, db: Session):
        self.db = db

    def get_llm(self, config_name: str = None, skill_name: str = None, streaming: bool = False):
        """
        根据配置获取 LLM 实例。
        支持根据 skill_name 自动路由。
        """
        config = None
        resolved_skill = None
        if skill_name:
            resolved_skill = self.SKILL_NAME_ALIASES.get(skill_name, skill_name)
        
        # 1. 如果指定了 config_name (用户手动选择)，优先级最高
        if config_name:
            config = self.db.query(models.LLMConfig).filter(models.LLMConfig.name == config_name).first()

        # 2. 如果没有指定 config_name，但指定了 Skill Name，查路由表
        if not config and resolved_skill:
            candidate_names = {resolved_skill, skill_name}
            for k, v in self.SKILL_NAME_ALIASES.items():
                if v == resolved_skill:
                    candidate_names.add(k)
            candidate_names = {n for n in candidate_names if n}
            route = self.db.query(models.SkillRoute).filter(models.SkillRoute.skill_name.in_(list(candidate_names))).first()
            if route and route.llm_config:
                config = route.llm_config
            
        # 3. 还没找到，取默认第一个
        if not config:
            config = self.db.query(models.LLMConfig).filter(models.LLMConfig.is_active == True).first()

        if config:
            logger.info("LLM config selected", extra={"provider": config.provider})
        else:
            logger.warning("No LLM config found")

        if not config:
            # 兜底逻辑
            if os.getenv("ANTHROPIC_API_KEY"):
                 logger.info("Using Anthropic from env")
                 return ChatAnthropic(model="claude-haiku-4-5", temperature=0.7, streaming=streaming)
            if os.getenv("OPENAI_API_KEY"):
                logger.info("Using OpenAI from env")
                return ChatOpenAI(model="gpt-3.5-turbo", temperature=0.7, streaming=streaming)
            
            logger.warning("Using mock LLM due to missing config")
            from langchain_core.language_models.chat_models import BaseChatModel
            from langchain_core.messages import BaseMessage, AIMessage
            from langchain_core.outputs import ChatResult, ChatGeneration
            from typing import Any, List, Optional

            class SimpleMockChatModel(BaseChatModel):
                response: str = "【模拟回复】未配置有效的 LLM 密钥，返回模拟内容。"
                
                def _generate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
                    return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.response))])
                
                @property
                def _llm_type(self) -> str:
                    return "mock"

            return SimpleMockChatModel()
            # raise ValueError("未在数据库或环境变量中找到可用的 LLM 配置。")

        # 构造 LLM 实例
        # Auto-correct model name
        actual_model_name = self.MODEL_MAPPING.get(config.model_name, config.model_name)

        api_base = config.api_base.strip().strip("`") if config.api_base else None
        api_key = config.api_key.strip().strip("`") if config.api_key else None
        
        if config.provider == "anthropic":
            # Handle empty base_url
            kwargs = {
                "model": actual_model_name,
                "temperature": config.temperature,
                "anthropic_api_key": api_key,
                "streaming": streaming,
            }
            if api_base:
                 kwargs["base_url"] = api_base
                 
            return ChatAnthropic(**kwargs)
        elif config.provider in ["openai", "doubao", "volcengine", "azure", "azure_openai", "openai_compatible"]:
            # Default to OpenAI compatible
            
            # Sanitize API Key (remove "Bearer " prefix and whitespace)
            if api_key and api_key.startswith("Bearer "):
                api_key = api_key[7:]

            llm_params = {
                "model": actual_model_name,
                "temperature": config.temperature,
                "openai_api_key": api_key,
                "streaming": streaming,
            }
            
            # Special handling for Doubao/Volcengine
            if config.provider in ["doubao", "volcengine"] and not config.api_base:
                # Force Volcengine Base URL if not set
                llm_params["base_url"] = "https://ark.cn-beijing.volces.com/api/v3"
                logger.info("Using default Volcengine base_url")
            
            if config.api_base:
                llm_params["base_url"] = api_base or config.api_base
                
            return ChatOpenAI(**llm_params)
        else:
            llm_params = {
                "model": actual_model_name,
                "temperature": config.temperature,
                "openai_api_key": api_key,
                "streaming": streaming,
            }
            if api_base:
                llm_params["base_url"] = api_base
            return ChatOpenAI(**llm_params)

    def _save_agent_user_query(self, customer_id: int, query: str) -> None:
        try:
            logger.info("Saving user query", extra={"customer_id": customer_id})
            crud.create_customer_data(self.db, schemas.CustomerDataCreate(
                source_type="agent_chat_user",
                content=query,
                meta_info={"role": "user", "timestamp": datetime.utcnow().isoformat()}
            ), customer_id)
        except Exception:
            logger.exception("Failed to save user chat history", extra={"customer_id": customer_id})

    def _save_agent_ai_response(self, customer_id: int, response_content: str) -> None:
        try:
            logger.info("Saving AI response", extra={"customer_id": customer_id})
            crud.create_customer_data(self.db, schemas.CustomerDataCreate(
                source_type="agent_chat_ai",
                content=response_content,
                meta_info={"role": "ai", "timestamp": datetime.utcnow().isoformat()}
            ), customer_id)
        except Exception:
            logger.exception("Failed to save AI chat history", extra={"customer_id": customer_id})

    def _build_agent_messages(self, customer_id: int, query: str, history: list = None, rag_context: str = "", model: str = None):
        customer = self.db.query(models.Customer).filter(models.Customer.id == customer_id).first()
        if not customer:
            raise ValueError(f"Customer {customer_id} not found")

        customer_logs = ""
        entries = sorted(customer.data_entries, key=lambda x: x.created_at, reverse=True)[:10]
        entries.reverse()
        for entry in entries:
            if entry.source_type in ['chat_history_user', 'chat_history_ai']:
                customer_logs += f"[{'客户' if entry.source_type == 'chat_history_user' else '销售'}]: {entry.content}\n"

        if not customer_logs:
            customer_logs = "（暂无最近聊天记录）"

        matched_context = ""
        try:
            candidate_entries = [e for e in customer.data_entries if e.source_type not in ['chat_history_user', 'chat_history_ai']]
            candidate_entries.sort(key=lambda x: x.created_at, reverse=True)
            selected_entries = []
            query_lower = query.lower()
            keyword_hits = []
            for e in candidate_entries:
                meta = e.meta_info or {}
                filename = (meta.get("filename") or "").lower()
                orig_filename = (meta.get("original_audio_filename") or "").lower()
                if filename and filename in query_lower:
                    keyword_hits.append(e)
                    continue
                if orig_filename and orig_filename in query_lower:
                    keyword_hits.append(e)
                    continue
                if filename:
                    stem = filename.rsplit('.', 1)[0]
                    if len(stem) > 5 and stem in query_lower:
                        keyword_hits.append(e)
                        continue
                if orig_filename:
                    stem_orig = orig_filename.rsplit('.', 1)[0]
                    if len(stem_orig) > 5 and stem_orig in query_lower:
                        keyword_hits.append(e)
                        continue
            selected_entries.extend(keyword_hits)
            llm_selected = self._select_relevant_data_entries(query, candidate_entries[:30], model=model)
            for e in llm_selected:
                if e not in selected_entries:
                    selected_entries.append(e)
            unique_entries = []
            seen_ids = set()
            for e in selected_entries:
                if e.id not in seen_ids:
                    unique_entries.append(e)
                    seen_ids.add(e.id)
            print(f"检索记录：问题 '{query}'，共命中 {len(unique_entries)} 条（关键词 {len(keyword_hits)}，模型 {len(llm_selected)}）")
            if not unique_entries:
                fallback_entries = []
                for e in candidate_entries:
                    meta = e.meta_info or {}
                    if meta.get("filename") or meta.get("original_audio_filename"):
                        fallback_entries.append(e)
                        continue
                    st = e.source_type or ""
                    if st.startswith("document_") or st.startswith("audio_") or st.startswith("audio_transcription"):
                        fallback_entries.append(e)
                        continue
                unique_entries = fallback_entries[:3]
                if unique_entries:
                    logger.info("Retrieval fallback applied", extra={"count": len(unique_entries)})
            for e in unique_entries:
                meta = e.meta_info or {}
                filename = meta.get("filename") or meta.get("original_audio_filename") or "No Name"
                content_preview = e.content
                if len(content_preview) > 15000:
                    content_preview = content_preview[:15000] + "\n（内容过长已截断）"
                matched_context += f"【已检索数据：{filename}（类型：{e.source_type}）】\n{content_preview}\n----------------\n"
        except Exception:
            logger.exception("Data selection error")
            matched_context = ""

        system_prompt = f"""
        你是转化运营专家的专属 AI 助手，负责协助运营人员分析客户、制定策略和撰写回复。
        
        【当前分析的客户信息】
        - 姓名：{customer.name}
        - 阶段：{customer.stage}
        - 风险偏好：{customer.risk_profile or '未知'}
        - 画像摘要：{customer.summary or '暂无'}

        【客户最近的聊天记录】
        {customer_logs}

        【参考知识库】
        {rag_context or "（未匹配到相关知识库文档）"}

        【用户指定的数据条目】
        {matched_context or "（未指定具体数据条目或未匹配到）"}

        【你的职责】
        1. 回答运营人员关于该客户的问题。
        2. 如果运营人员询问“怎么回”，结合知识库与客户上下文给出建议话术。
        3. 保持客观、专业、有洞察力。
        4. 直接输出结论与建议，不要输出推理过程，不要使用【call_analysis】或【file_analysis】等标签。
        5. 输出尽量使用中文，避免无必要英文。
        """

        messages = [SystemMessage(content=system_prompt)]
        if history:
            for msg in history:
                if msg['role'] == 'user':
                    messages.append(HumanMessage(content=msg['content']))
                elif msg['role'] == 'ai':
                    messages.append(AIMessage(content=msg['content']))
        messages.append(HumanMessage(content=query))
        return messages

    def generate_customer_summary(self, customer_id: int) -> str:
        customer = self.db.query(models.Customer).filter(models.Customer.id == customer_id).first()
        if not customer:
            raise ValueError(f"Customer {customer_id} not found")

        context_text = f"【基本信息】\n姓名：{customer.name}\n创建时间：{customer.created_at}\n"
        if customer.contact_info:
            context_text += f"联系方式：{customer.contact_info}\n"
        
        # Add custom fields if available
        if customer.custom_fields:
            try:
                fields = customer.custom_fields if isinstance(customer.custom_fields, dict) else json.loads(customer.custom_fields)
                for k, v in fields.items():
                    context_text += f"{k}：{v}\n"
            except:
                pass
        
        context_text += "----------------\n"

        if customer.data_entries:
            for entry in customer.data_entries:
                context_text += f"【来源: {entry.source_type}】\n{entry.content}\n----------------\n"
        else:
            context_text += "（暂无更多交互数据）\n"
        
        system_prompt = """
        请根据客户多源数据生成结构化分析，严格输出 JSON 对象，仅输出 JSON 不要代码块：
        {
          "阶段": "接触前 | 建立信任 | 需求分析 | 商务谈判",
          "风险偏好": "中文短语，如 稳健型/中风险/高风险/未知 等",
          "画像摘要": "简洁画像摘要，面向销售人员阅读"
        }
        阶段必须为上述四个枚举之一，画像摘要与风险偏好用中文表述。
        如果数据稀疏（仅有基本信息），请基于现有信息生成简要说明（例如“新客户，待开发”），不要编造不存在的特征。
        """

        llm = self.get_llm(skill_name="customer_summary")
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"客户原始数据：\n{context_text}")
        ])

        import json, re
        content = response.content.strip()
        content = re.sub(r'^```json\s*', '', content)
        content = re.sub(r'^```\s*', '', content)
        content = re.sub(r'\s*```$', '', content)
        parsed = None
        try:
            parsed = json.loads(content)
        except:
            parsed = None
        
        def normalize_stage(s: str) -> str:
            if not s:
                return "contact_before"
            t = s.strip().lower()
            mapping = {
                "contact_before": "contact_before",
                "trust_building": "trust_building",
                "product_matching": "product_matching",
                "closing": "closing",
                "接触前": "contact_before",
                "建立信任": "trust_building",
                "需求分析": "product_matching",
                "商务谈判": "closing",
                "成交": "closing",
                "认知": "contact_before",
                "观望": "trust_building",
                "决策": "product_matching",
                "犹豫": "trust_building",
                "初次": "contact_before",
                "匹配": "product_matching",
                "谈判": "closing"
            }
            for k, v in mapping.items():
                if k in t:
                    return v
            return "contact_before"

        if parsed and isinstance(parsed, dict):
            summary = parsed.get("画像摘要") or parsed.get("summary")
            stage_value = parsed.get("阶段") or parsed.get("stage")
            risk_profile = parsed.get("风险偏好") or parsed.get("risk_profile")

            customer.summary = summary or response.content
            customer.stage = normalize_stage(stage_value)
            rp = risk_profile
            if rp:
                customer.risk_profile = rp
        else:
            customer.summary = response.content
        self.db.commit()
        
        return customer.summary

    def generate_reply_suggestion(self, customer_id: int, intent: str = None, chat_context: str = None) -> dict:
        """
        核心功能：话术辅助
        """
        # 1. 获取客户上下文
        customer = self.db.query(models.Customer).filter(models.Customer.id == customer_id).first()
        if not customer:
            raise ValueError(f"Customer {customer_id} not found")

        # 如果没有提供特定的 chat_context，则聚合历史数据（优先取最近的聊天记录）
        full_context = ""
        if chat_context:
            full_context = chat_context
        else:
             # 简单的取最近 5 条聊天记录或所有笔记
            entries = sorted(customer.data_entries, key=lambda x: x.created_at, reverse=True)[:10]
            entries.reverse() # 恢复时间顺序
            for entry in entries:
                full_context += f"[{entry.source_type}]: {entry.content}\n"

        # 2. System Prompt
        system_prompt = """
        你是一位拥有 10 年经验的“金牌销售教练”。你的任务是辅助新手销售回复客户，帮助推进对话并保持合规与专业。
        
        请基于客户画像与最近对话，输出一个可直接发送的【最佳回复建议】。
        
        输出必须是严格 JSON 对象，且只包含以下字段：
        - 建议回复: 具体话术，口语化、亲切但专业，可直接复制发送。允许包含一个确认式问题以推动对话。
        - 回复理由: 一句话说明为什么这样回复，聚焦客户心理/顾虑。
        - 风险提示: 可能的风险或雷区，若无则输出空字符串。
        
        质量要求：
        - 语气不卑不亢，建立平等专业关系。
        - 推动对话继续，不把对话终结。
        - 不承诺收益、不保证结果、不夸大或虚构。
        
        输出格式示例（仅示意，不要照抄内容）：
        {"建议回复":"...","回复理由":"...","风险提示":"..."}
        """
        
        user_input = f"客户上下文：\n{customer.summary}\n\n最近对话：\n{full_context}"
        if intent:
            user_input += f"\n\n销售当前的意图是：{intent}"

        # 3. Call LLM
        # 强制使用 JSON 模式（如果模型支持）或者在 Prompt 里强调
        llm = self.get_llm(skill_name="reply_suggestion")
        
        # 简易处理：直接让它输出 JSON string，然后解析
        response = llm.invoke([
            SystemMessage(content=system_prompt + "\n请务必只输出标准的 JSON 格式，不要包含 Markdown 代码块。"),
            HumanMessage(content=user_input)
        ])
        
        import json
        import re
        
        content = response.content.strip()
        # 尝试清理 Markdown 代码块
        content = re.sub(r'^```json\s*', '', content)
        content = re.sub(r'^```\s*', '', content)
        content = re.sub(r'\s*```$', '', content)
        
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            result = None

        if isinstance(result, dict):
            suggested_reply = result.get("建议回复") or result.get("suggested_reply") or content
            rationale = result.get("回复理由") or result.get("rationale") or result.get("理由") or "解析失败，直接显示原文"
            risk_alert = result.get("风险提示") or result.get("risk_alert") or ""
        else:
            suggested_reply = content
            rationale = "解析失败，直接显示原文"
            risk_alert = "请人工审核回复内容"

        return {
            "suggested_reply": suggested_reply,
            "rationale": rationale,
            "risk_alert": risk_alert
        }

    def _select_relevant_data_entries(self, query: str, entries: list, model: str | None = None) -> list:
        """
        Smart Selector: Use LLM to decide which data entries are relevant to the query.
        """
        if not entries:
            return []
            
        # 1. Build File List for LLM
        file_list_str = ""
        entry_map = {}
        for e in entries:
            meta = e.meta_info or {}
            filename = meta.get("filename") or meta.get("original_audio_filename") or "No Name"
            snippet = e.content[:50].replace("\n", " ")
            file_list_str += f"编号: {e.id} | 类型: {e.source_type} | 名称: {filename} | 内容摘要: {snippet}...\n"
            entry_map[e.id] = e
            
        # 2. Selector Prompt
        system_prompt = """
        你是数据检索助手。你的任务是判断用户问题与哪些数据条目相关，并输出匹配的条目 ID。
        
        - 用户明确点名文件（例如“分析 voice_123”），请优先选择该文件。
        - 用户模糊提到文件（例如“那份合同”“我刚上传的音频”“最后一个文件”），根据类型、名称、时间选择最合理的匹配。
        - 用户提出泛化问题且未指向具体数据（例如“怎么回复”），返回空列表。
        
        仅输出严格 JSON：{"relevant_ids":[id1,id2]}
        """
        
        user_input = f"用户问题：{query}\n\n可用数据条目：\n{file_list_str}"
        
        # 3. Call LLM (Use a fast model if possible, or the default)
        try:
            llm = self.get_llm(config_name=model, skill_name="data_selector")
            response = llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_input)
            ])
            
            import json, re
            content = response.content.strip()
            content = re.sub(r'^```json\s*', '', content)
            content = re.sub(r'^```\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
            
            result = json.loads(content)
            ids = result.get("relevant_ids", [])
            
            selected_entries = []
            for i in ids:
                if i in entry_map:
                    selected_entries.append(entry_map[i])
            return selected_entries
            
        except Exception as e:
            print(f"数据筛选失败: {e}")
            return []

    def chat_with_agent(self, customer_id: int, query: str, history: list = None, rag_context: str = "", model: str = None) -> str:
        messages = self._build_agent_messages(customer_id, query, history, rag_context, model)
        self._save_agent_user_query(customer_id, query)
        response_content = ""
        try:
            if model:
                llm = self.get_llm(config_name=model)
            else:
                llm = self.get_llm(skill_name="agent_chat")
            response = llm.invoke(messages)
            response_content = response.content
        except Exception as e:
            logger.exception("LLM invoke failed")
            response_content = f"（系统错误）AI 响应失败: {str(e)}"
        self._save_agent_ai_response(customer_id, response_content)
        return response_content

    async def chat_with_agent_stream(self, customer_id: int, query: str, history: list = None, rag_context: str = "", model: str = None):
        messages = self._build_agent_messages(customer_id, query, history, rag_context, model)
        self._save_agent_user_query(customer_id, query)
        response_content = ""
        try:
            if model:
                llm = self.get_llm(config_name=model, streaming=True)
            else:
                llm = self.get_llm(skill_name="agent_chat", streaming=True)
            async for chunk in llm.astream(messages):
                token = getattr(chunk, "content", None)
                if token:
                    response_content += token
                    yield token
        except Exception as e:
            logger.exception("LLM stream failed")
            error_msg = f"（系统错误）AI 响应失败: {str(e)}"
            response_content = response_content or error_msg
            yield error_msg
        self._save_agent_ai_response(customer_id, response_content)

    def evaluate_sales_progression(self, customer_id: int) -> dict:
        """
        核心功能：推进建议
        """
        customer = self.db.query(models.Customer).filter(models.Customer.id == customer_id).first()
        if not customer:
            raise ValueError(f"Customer {customer_id} not found")

        context_text = ""
        for entry in customer.data_entries:
            context_text += f"【{entry.source_type}】\n{entry.content}\n----------------\n"

        system_prompt = """
        你是一位严格的销售总监。请根据客户的全量历史数据，判断【现在适不适合推进成交】并给出清晰可执行的下一步建议。
        
        输出必须是严格 JSON 对象，且只包含以下字段：
        - 推进建议: 只能是 "建议推进" | "建议观望" | "建议停止"
        - 核心理由: 一句话核心理由，必须可被历史数据支撑
        - 关键阻碍: 列表，写出具体阻碍点或疑虑，没有则空列表
        - 下一步建议: 下一步具体动作建议，需可执行
        
        判断标准：
        - 客户还在问基础概念 -> 建议观望
        - 客户对资金安全极度担忧且未被化解 -> 建议观望 或 建议停止
        - 客户询问费率、流程、合同细节 -> 建议推进
        - 信息不足或信号矛盾 -> 建议观望
        
        输出格式示例（仅示意，不要照抄内容）：
        {"推进建议":"建议观望","核心理由":"...","关键阻碍":["..."],"下一步建议":"..."}
        """

        llm = self.get_llm(skill_name="evaluate_progression")
        response = llm.invoke([
            SystemMessage(content=system_prompt + "\n请务必只输出标准的 JSON 格式。"),
            HumanMessage(content=f"客户全量数据：\n{context_text}")
        ])

        import json
        import re
        content = response.content.strip()
        content = re.sub(r'^```json\s*', '', content)
        content = re.sub(r'^```\s*', '', content)
        content = re.sub(r'\s*```$', '', content)

        try:
            result = json.loads(content)
        except:
            result = None

        def normalize_recommendation(value: str) -> str:
            if not value:
                return "建议观望"
            text = str(value).strip().lower()
            mapping = {
                "recommend": "建议推进",
                "hold": "建议观望",
                "stop": "建议停止",
                "建议推进": "建议推进",
                "建议观望": "建议观望",
                "建议停止": "建议停止",
                "推进": "建议推进",
                "观望": "建议观望",
                "停止": "建议停止"
            }
            for k, v in mapping.items():
                if k in text:
                    return v
            return "建议观望"

        if isinstance(result, dict):
            recommendation = result.get("推进建议") or result.get("recommendation")
            reason = result.get("核心理由") or result.get("reason") or "AI 解析响应失败，建议人工判断"
            key_blockers = result.get("关键阻碍") or result.get("key_blockers") or []
            next_step = result.get("下一步建议") or result.get("next_step_suggestion") or "检查日志"
        else:
            recommendation = "建议观望"
            reason = "AI 解析响应失败，建议人工判断"
            key_blockers = ["系统错误"]
            next_step = "检查日志"

        return {
            "recommendation": normalize_recommendation(recommendation),
            "reason": reason,
            "key_blockers": key_blockers,
            "next_step_suggestion": next_step
        }

    def process_knowledge_content(self, raw_content: str, source_type: str = "text") -> str:
        """
        Knowledge Preprocessing: Structure and summarize raw content into clean Markdown.
        """
        if not raw_content or len(raw_content) < 50:
            return raw_content

        system_prompt = """
        你是一名专业的知识库整理专家。你的任务是将输入的原始文本（可能包含噪音、格式混乱或口语化内容）整理成结构清晰、易于阅读和检索的 Markdown 文档。
        
        【处理原则】
        1. **结构化**：使用合理的 Markdown 标题（# ## ###）分层级组织内容。
        2. **摘要**：在文档开头生成一段【核心摘要】，概括文档主要内容。
        3. **清洗**：去除无意义的字符、乱码或无关的元数据。
        4. **保留**：保留所有关键事实、数据、专有名词和逻辑关系，不要过度删减。
        5. **格式**：关键术语可用 **加粗** 强调，列表内容使用 - 或 1. 列表。
        
        请直接输出整理后的 Markdown 内容，不要包含 "好的"、"如下是整理后的内容" 等废话。
        """

        # Truncate if too long to avoid token limits (simple safety check)
        # Assuming 100k chars is a safe upper bound for now, but really depends on model context window
        input_text = raw_content[:100000] 
        
        try:
            # Use a smart model for structuring (e.g. gpt-4o or claude-3.5-sonnet if available)
            # fallback to default
            llm = self.get_llm(skill_name="knowledge_processing") 
            
            response = llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"【原始文本】：\n{input_text}")
            ])
            
            return response.content.strip()
        except Exception as e:
            logger.error(f"Knowledge processing failed: {e}")
            # Fallback to raw content if AI fails
            return raw_content

    def process_sales_script(self, raw_content: str) -> str:
        """
        Sales Script Preprocessing: Extract Q&A pairs and key selling points.
        """
        if not raw_content or len(raw_content) < 20:
            return raw_content

        system_prompt = """
        你是一名金牌销售话术整理专家。你的任务是将输入的原始话术文档（可能是对话记录、培训手册或散乱的笔记）整理成结构化、易于检索和实战使用的 Markdown 格式。
        
        【处理原则】
        1. **问答提取**：重点识别“客户异议/问题”与“推荐回复”，整理为 `### Q: [问题]` 和 `**A:** [回复]` 的形式。
        2. **卖点提炼**：在文档开头总结【核心卖点】与【适用场景】。
        3. **结构化**：使用清晰的层级（# ## ###），将话术按阶段（如开场、挖掘、异议处理、成交）分类。
        4. **清洗优化**：去除口语废话，保留高情商、有说服力的表达；适当润色不通顺的句子。
        
        请直接输出整理后的 Markdown 内容，不要包含 "好的" 等废话。
        """

        input_text = raw_content[:100000] 
        
        try:
            llm = self.get_llm(skill_name="knowledge_processing") # Reuse same skill config for now
            
            response = llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"【原始话术】：\n{input_text}")
            ])
            
            return response.content.strip()
        except Exception as e:
            logger.error(f"Sales script processing failed: {e}")
            return raw_content
