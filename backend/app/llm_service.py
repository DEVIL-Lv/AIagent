from sqlalchemy.orm import Session
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from . import models, schemas, crud
import os
from datetime import datetime

class LLMService:
    # Common mappings for user-friendly names to API strings
    MODEL_MAPPING = {
        # Anthropic
        "Claude Haiku 3.5": "claude-3-haiku-20240307", # Guess user intent
        "Claude 3 Haiku": "claude-3-haiku-20240307",
        "Claude 3.5 Sonnet": "claude-3-5-sonnet-20240620",
        "Claude 3 Opus": "claude-3-opus-20240229",
        "Claude 3 Sonnet": "claude-3-sonnet-20240229",
        # OpenAI
        "GPT-4 Turbo": "gpt-4-turbo",
        "GPT-3.5 Turbo": "gpt-3.5-turbo",
        "GPT-4o": "gpt-4o",
    }

    def __init__(self, db: Session):
        self.db = db

    def get_llm(self, config_name: str = None, skill_name: str = None):
        """
        根据配置获取 LLM 实例。
        支持根据 skill_name 自动路由。
        """
        config = None
        
        # 1. 如果指定了 config_name (用户手动选择)，优先级最高
        if config_name:
            config = self.db.query(models.LLMConfig).filter(models.LLMConfig.name == config_name).first()

        # 2. 如果没有指定 config_name，但指定了 Skill Name，查路由表
        if not config and skill_name:
            route = self.db.query(models.SkillRoute).filter(models.SkillRoute.skill_name == skill_name).first()
            if route and route.llm_config:
                config = route.llm_config
            
        # 3. 还没找到，取默认第一个
        if not config:
            config = self.db.query(models.LLMConfig).filter(models.LLMConfig.is_active == True).first()

        if config:
            safe_api_base = config.api_base.strip().strip("`") if config.api_base else None
            print(f"Using DB Config: {config.name}, Provider: {config.provider}, BaseURL: {safe_api_base}")
        else:
            print("No DB Config found.")

        if not config:
            # 兜底逻辑
            if os.getenv("ANTHROPIC_API_KEY"):
                 print("Using Anthropic from env")
                 return ChatAnthropic(model="claude-3-haiku-20240307", temperature=0.7)
            if os.getenv("OPENAI_API_KEY"):
                print("Using OpenAI from env")
                return ChatOpenAI(model="gpt-3.5-turbo", temperature=0.7)
            
            print("No LLM config found, using Fake/Mock LLM for testing")
            from langchain_core.language_models.chat_models import BaseChatModel
            from langchain_core.messages import BaseMessage, AIMessage
            from langchain_core.outputs import ChatResult, ChatGeneration
            from typing import Any, List, Optional

            class SimpleMockChatModel(BaseChatModel):
                response: str = "[Mock LLM Response] 这是一个模拟的回复，因为没有配置有效的 LLM API Key。"
                
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
            }
            if api_base:
                 kwargs["base_url"] = api_base
                 
            return ChatAnthropic(**kwargs)
        elif config.provider in ["openai", "doubao", "volcengine", "azure_openai", "openai_compatible"]:
            # Default to OpenAI compatible
            
            # Sanitize API Key (remove "Bearer " prefix and whitespace)
            if api_key and api_key.startswith("Bearer "):
                api_key = api_key[7:]

            llm_params = {
                "model": actual_model_name,
                "temperature": config.temperature,
                "openai_api_key": api_key,
            }
            
            # Special handling for Doubao/Volcengine
            if config.provider in ["doubao", "volcengine"] and not api_base:
                # Force Volcengine Base URL if not set
                llm_params["base_url"] = "https://ark.cn-beijing.volces.com/api/v3"
                print(f"Forcing Volcengine Base URL: {llm_params['base_url']}")
            
            if api_base:
                llm_params["base_url"] = api_base
                
            return ChatOpenAI(**llm_params)
        else:
            llm_params = {
                "model": actual_model_name,
                "temperature": config.temperature,
                "openai_api_key": api_key,
            }
            if api_base:
                llm_params["base_url"] = api_base
            return ChatOpenAI(**llm_params)

    def track_cost(self, llm_instance, usage_info: dict):
        """
        更新 LLM 的 Token 消耗和成本。
        usage_info: {'input_tokens': 100, 'output_tokens': 50}
        """
        # 我们需要反查 llm_instance 对应的 config
        # 这有点难，因为 instance 是新建的。
        # 更好的方式是 get_llm 返回 (llm, config_id)
        # 或者在 get_llm 时记录当前使用的 config_id
        pass

    def generate_customer_summary(self, customer_id: int) -> str:
        customer = self.db.query(models.Customer).filter(models.Customer.id == customer_id).first()
        if not customer:
            raise ValueError(f"Customer {customer_id} not found")

        context_text = ""
        for entry in customer.data_entries:
            context_text += f"【来源: {entry.source_type}】\n{entry.content}\n----------------\n"
        
        if not context_text:
            return "暂无数据，无法生成画像。"

        system_prompt = """
        请根据客户多源数据生成结构化分析，严格输出 JSON：
        {
          "stage": "contact_before | trust_building | product_matching | closing",
          "risk_profile": "中文短语，如 稳健型/中风险/高风险 等",
          "summary": "简洁画像摘要，面向销售人员阅读"
        }
        仅输出 JSON。stage 必须为四个枚举之一。
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
            customer.summary = parsed.get("summary") or response.content
            customer.stage = normalize_stage(parsed.get("stage"))
            rp = parsed.get("risk_profile")
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
        你是一位拥有 10 年经验的“金牌销售教练”。你的任务是辅助新手销售回复客户。
        
        请基于客户的历史上下文和当前对话，提供一个【最佳回复建议】。
        
        你的输出必须包含三部分（请用 JSON 格式输出，包含 suggested_reply, rationale, risk_alert 字段）：
        1. suggested_reply: 具体的话术，口语化，亲切但专业。可以直接复制发送。
        2. rationale: 为什么要这么回？解析客户背后的心理或顾虑。
        3. risk_alert: 有什么雷区？（例如：不要过度承诺收益，不要忽视客户的风险厌恶等）。
        
        请确保：
        - 语气不卑不亢，建立平等专业的关系。
        - 能够推动对话继续，而不是把天聊死。
        """
        
        user_input = f"客户上下文：\n{customer.summary}\n\n最近对话：\n{full_context}"
        if intent:
            user_input += f"\n\n销售当前的意图是：{intent}"

        # 3. Call LLM
        # 强制使用 JSON 模式（如果模型支持）或者在 Prompt 里强调
        llm = self.get_llm(skill_name="suggest_reply")
        
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
            # Fallback
            result = {
                "suggested_reply": content,
                "rationale": "解析失败，直接显示原文",
                "risk_alert": "请人工审核回复内容"
            }
            
        return result

    def _select_relevant_data_entries(self, query: str, entries: list, config_name: str | None = None) -> list:
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
            file_list_str += f"ID: {e.id} | Type: {e.source_type} | Name: {filename} | Content Snippet: {snippet}...\n"
            entry_map[e.id] = e
            
        # 2. Selector Prompt
        system_prompt = """
        You are a Data Retrieval Assistant. Your task is to identify which data entries from the provided list are relevant to the User's Query.
        
        - If the user explicitly names a file (e.g., "analyze voice_123"), select it.
        - If the user refers to a file implicitly (e.g., "the contract", "the audio I just uploaded", "the last file"), select the most logical match based on Type, Name, and Date.
        - If the user asks a general question without referencing specific data (e.g., "how to reply?"), return an empty list.
        
        Output strictly valid JSON: {"relevant_ids": [id1, id2]}
        """
        
        user_input = f"User Query: {query}\n\nAvailable Data Entries:\n{file_list_str}"
        
        # 3. Call LLM (Use a fast model if possible, or the default)
        try:
            llm = self.get_llm(config_name=config_name, skill_name="data_selector") # Optional: define a specific skill for this
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
            print(f"Smart Selector Failed: {e}")
            return []

    def chat_with_agent(self, customer_id: int, query: str, history: list = None, rag_context: str = "", model: str = None) -> str:
        """
        User <-> Agent 对话接口
        """
        # 1. 获取客户上下文
        customer = self.db.query(models.Customer).filter(models.Customer.id == customer_id).first()
        if not customer:
            raise ValueError(f"Customer {customer_id} not found")

        # 2. 聚合客户最近动态（聊天记录）作为背景信息
        customer_logs = ""
        entries = sorted(customer.data_entries, key=lambda x: x.created_at, reverse=True)[:10]
        entries.reverse()
        for entry in entries:
            # 过滤掉 AI 技能的中间产物，只保留对话
            if entry.source_type in ['chat_history_user', 'chat_history_ai']:
                customer_logs += f"[{'客户' if entry.source_type == 'chat_history_user' else '销售'}]: {entry.content}\n"
        
        if not customer_logs:
            customer_logs = "（暂无最近聊天记录）"

        # 2.1 Smart Data Selection (Combined Strategy)
        matched_context = ""
        try:
            # Prepare candidates: all non-chat entries
            candidate_entries = [e for e in customer.data_entries if e.source_type not in ['chat_history_user', 'chat_history_ai']]
            candidate_entries.sort(key=lambda x: x.created_at, reverse=True)
            
            selected_entries = []
            
            # Strategy A: Deterministic Keyword Matching (Fast & Reliable for exact names)
            # This is crucial if Smart Selector fails or if the user is very specific
            query_lower = query.lower()
            keyword_hits = []
            for e in candidate_entries:
                meta = e.meta_info or {}
                filename = (meta.get("filename") or "").lower()
                orig_filename = (meta.get("original_audio_filename") or "").lower()
                
                # Check 1: Exact filename match (ignoring case)
                if filename and filename in query_lower:
                    keyword_hits.append(e)
                    continue
                    
                # Check 2: Original filename match
                if orig_filename and orig_filename in query_lower:
                    keyword_hits.append(e)
                    continue
                    
                # Check 3: Filename stem match (e.g. "voice_123" matches "voice_123.wav")
                if filename:
                    stem = filename.rsplit('.', 1)[0]
                    if len(stem) > 5 and stem in query_lower:
                        keyword_hits.append(e)
                        continue
                        
                # Check 4: Original filename stem match (for renamed files)
                if orig_filename:
                    stem_orig = orig_filename.rsplit('.', 1)[0]
                    if len(stem_orig) > 5 and stem_orig in query_lower:
                        keyword_hits.append(e)
                        continue
            
            # Add keyword hits first
            selected_entries.extend(keyword_hits)
            
            # Strategy B: Smart Selector (LLM-based)
            # Only run if we need more context or if keyword match found nothing
            # To be safe, we always run it but dedup results
            llm_selected = self._select_relevant_data_entries(query, candidate_entries[:30], config_name=model)
            
            for e in llm_selected:
                if e not in selected_entries:
                    selected_entries.append(e)
            
            # Deduplicate just in case
            unique_entries = []
            seen_ids = set()
            for e in selected_entries:
                if e.id not in seen_ids:
                    unique_entries.append(e)
                    seen_ids.add(e.id)
            
            # Log for debugging
            print(f"Retrieval for query '{query}': Found {len(unique_entries)} entries. (Keyword: {len(keyword_hits)}, LLM: {len(llm_selected)})")
            
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
                    print(f"Retrieval fallback: Using {len(unique_entries)} recent file entries.")
            
            for e in unique_entries:
                meta = e.meta_info or {}
                filename = meta.get("filename") or meta.get("original_audio_filename") or "No Name"
                
                # Safety truncation to avoid token overflow
                content_preview = e.content
                if len(content_preview) > 15000:
                    content_preview = content_preview[:15000] + "\n...(content truncated due to length)..."
                    
                matched_context += f"【已检索数据: {filename} (Type: {e.source_type})】\n{content_preview}\n----------------\n"
                
        except Exception as e:
            print(f"Data selection error: {e}")
            matched_context = ""

        # 3. 构建 System Prompt
        system_prompt = f"""
        你是一个转化运营专家的专属 AI 助手。你的工作是协助运营人员分析客户、制定策略和撰写回复。
        
        【当前分析的客户信息】
        - 姓名：{customer.name}
        - 阶段：{customer.stage}
        - 风险偏好：{customer.risk_profile or '未知'}
        - 画像摘要：{customer.summary or '暂无'}

        【客户最近的聊天记录 (Context)】
        {customer_logs}

        【参考知识库 (RAG)】
        {rag_context or "（未匹配到相关知识库文档）"}

        【用户指定的数据条目】
        {matched_context or "（未指定具体数据条目或未匹配到）"}

        【你的职责】
        1. 回答运营人员关于该客户的问题。
        2. 如果运营人员询问“怎么回”，请根据知识库和客户上下文给出建议。
        3. 保持客观、专业、有洞察力。
        4. 直接输出内容，不要使用【call_analysis】或【file_analysis】等标签作为开头。
        """

        messages = [SystemMessage(content=system_prompt)]
        
        # 4. 注入历史对话 (User <-> Agent)
        if history:
            for msg in history:
                if msg['role'] == 'user':
                    messages.append(HumanMessage(content=msg['content']))
                elif msg['role'] == 'ai':
                    messages.append(AIMessage(content=msg['content']))
        
        messages.append(HumanMessage(content=query))

        # 5. 先保存用户提问，防止后续 LLM 失败导致记录丢失
        try:
            print(f"Saving user query for customer {customer_id}: {query}")
            crud.create_customer_data(self.db, schemas.CustomerDataCreate(
                source_type="agent_chat_user",
                content=query,
                meta_info={"role": "user", "timestamp": datetime.utcnow().isoformat()}
            ), customer_id)
        except Exception as e:
            print(f"Error saving user chat history: {e}")

        # 6. 调用 LLM
        response_content = ""
        try:
            if model:
                llm = self.get_llm(config_name=model)
            else:
                llm = self.get_llm(skill_name="agent_chat") # 可以专门配置一个 skill
            
            response = llm.invoke(messages)
            response_content = response.content
        except Exception as e:
            print(f"LLM invoke failed: {e}")
            response_content = f"（系统错误）AI 响应失败: {str(e)}"

        # 7. 保存 AI 回复
        try:
            print(f"Saving AI response for customer {customer_id}: {response_content[:50]}...")
            crud.create_customer_data(self.db, schemas.CustomerDataCreate(
                source_type="agent_chat_ai",
                content=response_content,
                meta_info={"role": "ai", "timestamp": datetime.utcnow().isoformat()}
            ), customer_id)
        except Exception as e:
            print(f"Error saving ai chat history: {e}")

        return response_content

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
        你是一位严格的销售总监。请根据客户的全量历史数据，判断【现在适不适合推进成交？】。
        
        请输出 JSON 格式，包含以下字段：
        1. recommendation: 只能是 "recommend" (建议推进), "hold" (建议放缓/观望), "stop" (不建议/放弃) 中的一个。
        2. reason: 核心理由（一句话总结）。
        3. key_blockers: 一个列表，列出具体的阻碍点或疑虑（如果没有则为空）。
        4. next_step_suggestion: 下一步具体的动作建议（例如：发送产品对比表，预约电话，发送行业报告等）。
        
        判断标准：
        - 如果客户还在问基础概念，不要推成交 -> hold
        - 如果客户明确表达了对资金安全的极度担忧且未被化解，不要推 -> hold/stop
        - 如果客户询问了具体的费率、流程、合同细节 -> recommend
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
             result = {
                "recommendation": "hold",
                "reason": "AI 解析响应失败，建议人工判断",
                "key_blockers": ["系统错误"],
                "next_step_suggestion": "检查日志"
            }
        
        return result
