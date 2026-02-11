import json
from sqlalchemy.orm import Session
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage
from . import models, schemas, crud
from urllib.parse import parse_qs
import re
import os
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

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
        "history_summarizer": "core",
        
        # Independent Skills
        "data_selector": "data_selector",
        "knowledge_processing": "knowledge_processing",
        "chat": "chat"
    }

    def __init__(self, db: Session):
        self.db = db

    def _normalize_match_text(self, s: str) -> str:
        if s is None:
            return ""
        text = str(s).strip().lower()
        if not text:
            return ""
        return re.sub(r"[\s\r\n\t\-_/,:，。；;、】【\[\]（）(){}<>\"'`]+", "", text)

    def to_plain_text(self, text: str) -> str:
        if not text:
            return text
        s = str(text)
        s = re.sub(r"```[\s\S]*?```", "", s)
        s = re.sub(r"^\s*#{1,6}\s*", "", s, flags=re.M)
        s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
        s = re.sub(r"\*\*(.*?)\*\*", r"\1", s)
        s = re.sub(r"__(.*?)__", r"\1", s)
        s = re.sub(r"`([^`]*)`", r"\1", s)
        s = re.sub(r"^\s*>\s?", "", s, flags=re.M)
        s = re.sub(r"^\s*[-*+]\s+", "", s, flags=re.M)
        s = re.sub(r"^\s*\d+\.\s+", "", s, flags=re.M)
        s = re.sub(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$", "", s, flags=re.M)
        s = re.sub(r"\|", " ", s)
        s = s.replace("**", "").replace("__", "")
        s = re.sub(r"\n{3,}", "\n\n", s)
        return s.strip()

    def _parse_feishu_token(self, raw_token: str) -> tuple[str, str]:
        if not raw_token:
            return "", ""
        token = str(raw_token).strip()
        clean_token = token
        table_id = ""
        if "/base/" in token or token.startswith("bas"):
            after = token.split("/base/")[1] if "/base/" in token else token
            clean_token = after.split("?", 1)[0]
            if "?" in after:
                query = after.split("?", 1)[1]
                params = parse_qs(query)
                table_id = (params.get("table") or [""])[0]
        elif "/sheets/" in token or token.startswith("sht"):
            after = token.split("/sheets/")[1] if "/sheets/" in token else token
            clean_token = after.split("?", 1)[0]
        else:
            clean_token = token.split("?", 1)[0]
        return clean_token, table_id

    def _get_feishu_alias_map(self, config_id: int | None, cache: dict[str, dict[str, str]]) -> dict[str, str]:
        key = str(config_id) if config_id is not None else "default"
        if key in cache:
            return cache[key]
        mapping: dict[str, str] = {}
        if config_id is None:
            cache[key] = mapping
            return mapping
        config = self.db.query(models.DataSourceConfig).filter(models.DataSourceConfig.id == config_id).first()
        config_json = config.config_json if config and config.config_json else {}
        saved_sheets = config_json.get("saved_sheets") or []
        for sheet in saved_sheets:
            token = sheet.get("token")
            alias = sheet.get("alias")
            if not token or not alias:
                continue
            clean_token, table_id = self._parse_feishu_token(str(token))
            if not clean_token:
                continue
            if table_id:
                mapping[f"{clean_token}:{table_id}"] = str(alias)
            mapping[clean_token] = str(alias)
        cache[key] = mapping
        return mapping

    def _looks_like_internal_table_name(self, name: str) -> bool:
        n = str(name or "").strip()
        if not n:
            return False
        if n.startswith("Bitable ") and "tbl" in n:
            return True
        if n.startswith("tbl") or n.startswith("sht"):
            return True
        return False

    def _resolve_import_table_name(self, meta: dict, alias_cache: dict[str, dict[str, str]]) -> str:
        source_name = meta.get("source_name")
        if source_name and not self._looks_like_internal_table_name(source_name):
            return str(source_name)
        base_name = source_name or meta.get("_feishu_table_id") or meta.get("_feishu_token") or "导入记录"
        token = meta.get("_feishu_token")
        table_id = meta.get("_feishu_table_id")
        config_id = meta.get("data_source_id")
        if token:
            alias_map = self._get_feishu_alias_map(config_id, alias_cache)
            if table_id:
                alias = alias_map.get(f"{token}:{table_id}")
                if alias:
                    return alias
            alias = alias_map.get(str(token))
            if alias:
                return alias
        return str(base_name)

    def build_customer_import_schema(self, customer_id: int) -> dict[str, Any]:
        customer = self.db.query(models.Customer).filter(models.Customer.id == customer_id).first()
        if not customer:
            return {"tables": {}, "table_names": [], "field_to_tables": {}}
        entries = sorted(customer.data_entries or [], key=lambda x: x.created_at)
        alias_cache: dict[str, dict[str, str]] = {}
        reserved = {"source_type", "source_name", "data_source_id", "_feishu_token", "_feishu_table_id"}
        tables: dict[str, dict[str, Any]] = {}
        field_to_tables: dict[str, set[str]] = {}
        for entry in entries:
            if (entry.source_type or "").strip() != "import_record":
                continue
            meta = entry.meta_info or {}
            table_name = self._resolve_import_table_name(meta, alias_cache)
            row_keys = [k for k in meta.keys() if k and k not in reserved and not str(k).startswith("_")]
            t = tables.setdefault(table_name, {"fields": set()})
            for k in row_keys:
                ks = str(k).strip()
                if not ks:
                    continue
                t["fields"].add(ks)
                field_to_tables.setdefault(ks, set()).add(table_name)
        table_names = list(tables.keys())
        return {"tables": tables, "table_names": table_names, "field_to_tables": field_to_tables}

    def match_customer_schema(self, customer_id: int, query: str) -> dict[str, Any]:
        q = query or ""
        norm_query = self._normalize_match_text(q)
        stripped = re.sub(r"(请|帮我|给我|我要|我想|查一下|查下|看看|看下|查看|查询|列出|展示|一下|他的|她的|这个|这位|该客户)", "", q)
        norm_core = self._normalize_match_text(stripped)
        schema = self.build_customer_import_schema(customer_id)
        table_names: list[str] = schema.get("table_names") or []
        field_to_tables: dict[str, set[str]] = schema.get("field_to_tables") or {}

        explicit_tables: set[str] = set()
        fuzzy_tables: set[str] = set()
        for t in table_names:
            nt = self._normalize_match_text(t)
            if not nt:
                continue
            if nt in norm_query:
                explicit_tables.add(t)
                continue
            if norm_core and len(norm_core) >= 2 and norm_core in nt:
                fuzzy_tables.add(t)

        matched_fields: set[str] = set()
        field_tables: set[str] = set()
        for f, tables in field_to_tables.items():
            nf = self._normalize_match_text(f)
            if not nf:
                continue
            if nf in norm_query:
                matched_fields.add(f)
                for t in tables:
                    field_tables.add(t)
                continue
            if norm_core and len(norm_core) >= 2 and norm_core in nf:
                matched_fields.add(f)
                for t in tables:
                    field_tables.add(t)

        return {
            "explicit_tables": sorted(explicit_tables),
            "fuzzy_tables": sorted(fuzzy_tables),
            "field_tables": sorted(field_tables),
            "matched_fields": sorted(matched_fields),
            "schema": schema,
        }

    def is_schema_info_query(self, customer_id: int, query: str) -> bool:
        if not query:
            return False
        basic_keywords = ["基本信息", "基础信息"]
        norm_query = self._normalize_match_text(query)
        basic_field_names = ["姓名", "沟通阶段", "风险偏好", "联系方式"]
        if any(k in query for k in basic_keywords) or any(self._normalize_match_text(f) in norm_query for f in basic_field_names):
            return True
        m = self.match_customer_schema(customer_id, query)
        return bool(m.get("explicit_tables") or m.get("fuzzy_tables") or m.get("matched_fields"))

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

    def _history_dict_to_message(self, msg: Dict[str, Any]) -> Optional[BaseMessage]:
        role = (msg.get("role") or "").lower()
        content = msg.get("content")
        if content is None:
            return None
        content = str(content)
        if len(content) > 12000:
            content = content[:12000] + "\n（单条消息过长已截断）"
        if role == "user":
            return HumanMessage(content=content)
        if role in ("ai", "assistant"):
            return AIMessage(content=content)
        return None

    def _summarize_history(self, history: List[Dict[str, Any]], model: str = None) -> str:
        if not history:
            return ""

        lines: List[str] = []
        for msg in history:
            role = (msg.get("role") or "").lower()
            label = "用户" if role == "user" else "助手" if role in ("ai", "assistant") else ""
            content = msg.get("content")
            if not label or content is None:
                continue
            text = str(content).strip()
            if not text:
                continue
            if len(text) > 4000:
                text = text[:4000] + "…"
            lines.append(f"{label}: {text}")

        raw = "\n".join(lines)
        if not raw:
            return ""

        try:
            llm = self.get_llm(config_name=model) if model else self.get_llm(skill_name="history_summarizer")
            resp = llm.invoke([
                SystemMessage(content=(
                    "你是转化运营团队的对话摘要助手。请将历史对话压缩为可供后续决策参考的摘要。\n"
                    "要求：\n"
                    "1) 使用中文；\n"
                    "2) 重点保留：客户的核心顾虑、风险偏好表达、异议点、已达成共识、待办事项、推进状态；\n"
                    "3) 如出现数字、日期、金额、产品名称、人名要尽量保留；\n"
                    "4) 不要编造对话中未提及的信息；\n"
                    "5) 300~800 字，结构清晰。"
                )),
                HumanMessage(content=f"请总结以下更早的对话内容：\n\n{raw}"),
            ])
            summary = (getattr(resp, "content", None) or "").strip()
        except Exception:
            logger.exception("History summarization failed")
            summary = ""

        if not summary:
            summary = f"（已省略更早的 {len(history)} 条对话消息）"

        if len(summary) > 4000:
            summary = summary[:4000] + "…"
        return summary

    def _compress_history_messages(self, history: List[Dict[str, Any]], model: str = None, keep_last: int = 30) -> List[BaseMessage]:
        if not history:
            return []

        normalized: List[Dict[str, Any]] = []
        for msg in history:
            if not isinstance(msg, dict):
                continue
            role = (msg.get("role") or "").lower()
            if role not in ("user", "ai", "assistant"):
                continue
            if msg.get("content") is None:
                continue
            normalized.append({"role": "user" if role == "user" else "ai", "content": msg.get("content")})

        if not normalized:
            return []

        if len(normalized) <= keep_last:
            out: List[BaseMessage] = []
            for m in normalized:
                bm = self._history_dict_to_message(m)
                if bm:
                    out.append(bm)
            return out

        older = normalized[:-keep_last]
        recent = normalized[-keep_last:]

        summary = self._summarize_history(older, model=model)
        out = [SystemMessage(content=f"以下是更早对话的摘要（用于补充上下文，不必逐字引用）：\n{summary}")]
        for m in recent:
            bm = self._history_dict_to_message(m)
            if bm:
                out.append(bm)
        return out

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

        matched_context = self.retrieve_customer_data_context(customer_id=customer_id, query=query, model=model)

        system_role = """你是转化运营团队的专属 AI 辅助决策与话术系统。

【你的定位】
你"站在转化同学身边"，帮助他们看得更全、想得更清楚、说得更稳。
- 你不是自动卖产品的机器人
- 你不是替代转化同学的客服
- 你不是万能问答 GPT
判断仍然是人做，推进节奏仍然是人掌控。你的价值在于辅助决策。

【你的三个核心能力】
1. 客户理解：基于多源数据（聊天记录、录音转写、资产信息、购买历史），给出客户当前沟通阶段、真实风险偏好、核心顾虑的判断摘要——这是给转化同学看的，不是给客户看的。
2. 话术辅助：当转化同学不知道怎么回复时，提供"推荐回应方向 + 金牌销售示例回答 + 风险提示（哪些话不要说）"。目标是把最成熟的销售认知复制给所有转化同学。
3. 推进建议：判断"现在适不适合推进成交"，给出明确结论（建议推进/放缓/不建议）+ 理由 + 下一步动作。减少硬推、错推、情绪化推进。

【合规底线】
- 不承诺收益、不保证结果、不夸大或虚构
- 不替代合规审核流程
- 涉及具体产品推荐时必须提示"请以正式材料为准"

【输出要求】
- 直接输出结论与建议，不要输出推理过程
- 使用中文，结构清晰，重点突出
- 不要使用 Markdown，不要输出 ###、```、| 表格、** 加粗等格式
- 不要使用项目符号（-、*、+），如需分点请使用中文序号（1、2、3）
- 不要使用【call_analysis】或【file_analysis】等标签"""

        messages = [SystemMessage(content=system_role)]
        basic_info = (
            f"【当前客户信息】\n"
            f"姓名：{customer.name}\n"
            f"沟通阶段：{customer.stage}\n"
            f"风险偏好：{customer.risk_profile or '未评估'}\n"
            f"画像摘要：{customer.summary or '暂无'}"
        )
        messages.append(HumanMessage(content=basic_info))
        if customer_logs:
            messages.append(HumanMessage(content=f"【客户最近的聊天记录】\n{customer_logs}"))
        if rag_context:
            messages.append(HumanMessage(content=f"【参考知识库】\n{rag_context}"))
        if matched_context:
            messages.append(HumanMessage(content=f"【用户指定的数据条目】\n{matched_context}"))
        if history:
            try:
                history_msgs = self._compress_history_messages(history, model=model, keep_last=30)
            except Exception:
                logger.exception("History compression failed")
                history_msgs = []
            messages.extend(history_msgs)
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
                if entry.source_type == "import_record":
                    # Add detailed table data
                    try:
                        meta = entry.meta_info or {}
                        # Exclude source_type/name from AI context to reduce noise, keep actual data
                        content_dict = {k: v for k, v in meta.items() if k not in ("source_type", "source_name")}
                        # Format as a concise line
                        line = " | ".join([f"{k}:{v}" for k, v in content_dict.items()])
                        context_text += f"【详细数据】{line}\n"
                    except:
                        context_text += f"【详细数据】{entry.content}\n"
                else:
                    context_text += f"【来源: {entry.source_type}】\n{entry.content}\n----------------\n"
        else:
            context_text += "（暂无更多交互数据）\n"
        
        system_prompt = """你是资深转化运营分析师。请基于客户的多源数据（聊天记录、电话录音转写、资产信息、购买历史等），生成面向转化同学阅读的客户判断摘要。

【重要】你输出的不是"标签"，而是"判断"——帮助转化同学在接触客户前快速理解这个人。

请严格输出 JSON 对象，仅输出 JSON 不要代码块：
{
  "阶段": "接触前 | 建立信任 | 需求分析 | 商务谈判",
  "阶段判断依据": "一句话说明为什么判断为该阶段",
  "风险偏好": "稳健型 / 中风险 / 高风险 / 未知",
  "风险偏好分析": "用客户的实际行为反推真实风险偏好，而非仅看口头表达。例如：口头说稳健但买过高波动产品",
  "回撤容忍度": "对亏损、回撤、极端行情的真实态度描述",
  "核心顾虑": ["当前最核心的1-2个顾虑点，不要多"],
  "画像摘要": "3-5句面向转化同学的判断摘要，包含：客户是谁、当前状态、关键机会与风险"
}

【判断标准】
- 阶段判断：
  · 接触前：新线索或长期未联系，信息稀疏
  · 建立信任：有初步沟通但客户仍在观望、了解阶段
  · 需求分析：客户开始主动询问产品细节、费率、结构
  · 商务谈判：客户询问合同、流程、时间节点，接近成交
- 风险偏好：优先看行为（买过什么、持有多久、对回撤的实际反应），其次看表达
- 核心顾虑：从聊天记录中提炼客户反复提及或回避的问题

如果数据稀疏（仅有基本信息），请如实说明"数据不足，待补充"，不要编造不存在的特征。"""

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
            summary_parts = []

            raw_summary = parsed.get("画像摘要") or parsed.get("summary") or ""
            stage_reason = parsed.get("阶段判断依据") or ""
            risk_analysis = parsed.get("风险偏好分析") or ""
            tolerance = parsed.get("回撤容忍度") or ""
            concerns = parsed.get("核心顾虑") or []

            if raw_summary:
                summary_parts.append(raw_summary)
            if tolerance:
                summary_parts.append(f"回撤容忍度：{tolerance}")
            if concerns:
                concerns_str = "、".join(concerns) if isinstance(concerns, list) else str(concerns)
                summary_parts.append(f"核心顾虑：{concerns_str}")

            final_summary = "\n".join(summary_parts) if summary_parts else response.content

            stage_value = parsed.get("阶段") or parsed.get("stage")
            risk_profile = parsed.get("风险偏好") or parsed.get("risk_profile")

            customer.summary = final_summary
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
        system_prompt = """你是拥有10年经验的金牌销售教练。你的任务不是替转化同学发消息，而是帮他们"想清楚该怎么回"。

【你需要提供三样东西】

1. 推荐回应方向（四选一）：
   - 安抚：客户有情绪或顾虑，先稳住关系
   - 澄清：客户存在误解或信息偏差，需要纠正认知
   - 推进：客户信号积极，可以往成交方向引导
   - 暂停：时机不对或信息不足，建议暂时不回复或轻触达

2. 金牌销售示例回答：
   - 口语化、亲切但专业，可直接复制发送
   - 允许包含一个确认式问题以推动对话继续
   - 语气不卑不亢，建立平等专业关系

3. 风险提示：
   - 这个场景下哪些话不要说
   - 哪些点此时不宜强调
   - 可能踩的雷区

输出必须是严格 JSON 对象，且只包含以下字段：
{
  "回应方向": "安抚 | 澄清 | 推进 | 暂停",
  "方向说明": "一句话说明为什么选择这个方向",
  "建议回复": "具体话术，可直接复制发送",
  "风险提示": "哪些话不要说、哪些点不宜强调，若无则输出空字符串"
}

【质量底线】
- 不承诺收益、不保证结果、不夸大或虚构
- 推动对话继续，不把对话终结
- 不要出现"我们保证""绝对安全""稳赚不赔"等违规表述"""
        
        user_input = f"【客户画像】\n{customer.summary or '暂无'}\n\n【最近对话】\n{full_context}"
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
            rationale = result.get("方向说明") or result.get("回应方向") or result.get("回复理由") or result.get("rationale") or result.get("理由") or "解析失败，直接显示原文"
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
        system_prompt = """你是转化运营系统的数据检索助手。你的任务是判断转化同学的问题与哪些客户数据条目相关，并输出匹配的条目 ID。

【判断规则】
- 用户明确点名文件（例如"分析 voice_123"）：优先选择该文件
- 用户模糊提到文件（例如"那份合同""我刚上传的音频""最后一个文件"）：根据类型、名称、时间选择最合理的匹配
- 用户提出与客户数据相关的问题（例如"客户的风险偏好""上次通话说了什么"）：选择相关数据
- 用户提出泛化问题且未指向具体数据（例如"怎么回复"）：返回空列表

仅输出严格 JSON：{"relevant_ids":[id1,id2]}"""
        
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
            logger.exception("Data selector failed")
            return []

    def retrieve_customer_data_context(
        self,
        customer_id: int,
        query: str,
        model: str | None = None,
        max_candidates: int = 30,
        max_results: int = 3,
    ) -> str:
        customer = self.db.query(models.Customer).filter(models.Customer.id == customer_id).first()
        if not customer:
            return ""

        q = (query or "").strip()
        if not q:
            return ""

        matched_context = ""
        try:
            candidate_entries = []
            for e in customer.data_entries or []:
                st = (e.source_type or "").strip()
                if st.startswith("chat_history_") or st.startswith("agent_chat_"):
                    continue
                candidate_entries.append(e)

            candidate_entries.sort(key=lambda x: x.created_at, reverse=True)
            limited_candidates = candidate_entries[:max_candidates]

            profile_keywords = [
                "速览",
                "画像",
                "风险",
                "风险偏好",
                "推进",
                "成交",
                "时机",
                "阻碍",
                "建议",
                "下一步",
                "分析",
                "客户分析",
                "客户情况",
                "阶段判断",
                "评估",
            ]
            include_all = any(k in q for k in profile_keywords)
            ql = q.lower()
            selected_entries: list = []
            keyword_hits: list = []
            for e in limited_candidates:
                meta = e.meta_info or {}
                filename = (meta.get("filename") or "").lower()
                orig_filename = (meta.get("original_audio_filename") or "").lower()
                if filename and filename in ql:
                    keyword_hits.append(e)
                    continue
                if orig_filename and orig_filename in ql:
                    keyword_hits.append(e)
                    continue
                if filename:
                    stem = filename.rsplit(".", 1)[0]
                    if len(stem) > 5 and stem in ql:
                        keyword_hits.append(e)
                        continue
                if orig_filename:
                    stem_orig = orig_filename.rsplit(".", 1)[0]
                    if len(stem_orig) > 5 and stem_orig in ql:
                        keyword_hits.append(e)
                        continue

            selected_entries.extend(keyword_hits)
            llm_selected = self._select_relevant_data_entries(q, limited_candidates, model=model)
            for e in llm_selected:
                if e not in selected_entries:
                    selected_entries.append(e)

            unique_entries: list = []
            seen_ids = set()
            for e in selected_entries:
                if e.id not in seen_ids:
                    unique_entries.append(e)
                    seen_ids.add(e.id)

            if include_all:
                grouped_imports: dict[str, list[str]] = {}
                other_entries: list = []
                for e in reversed(candidate_entries):
                    meta = e.meta_info or {}
                    st = (e.source_type or "").strip()
                    if st == "import_record":
                        source_name = meta.get("source_name") or meta.get("_feishu_table_id") or meta.get("_feishu_token") or "导入记录"
                        content_dict = {
                            k: v
                            for k, v in meta.items()
                            if k
                            not in (
                                "source_type",
                                "source_name",
                                "data_source_id",
                                "_feishu_token",
                                "_feishu_table_id",
                            )
                        }
                        line = ""
                        if content_dict:
                            line = " | ".join([f"{k}:{v}" for k, v in content_dict.items()])
                        elif e.content:
                            line = e.content
                        if line:
                            grouped_imports.setdefault(str(source_name), []).append(line)
                    else:
                        other_entries.append(e)

                for source_name, lines in grouped_imports.items():
                    joined = "\n".join(lines)
                    if len(joined) > 50000:
                        joined = joined[:50000] + "\n（内容过长已截断）"
                    matched_context += f"【已检索数据：{source_name}（类型：import_record）】\n{joined}\n----------------\n"

                for e in other_entries:
                    meta = e.meta_info or {}
                    filename = meta.get("filename") or meta.get("original_audio_filename") or meta.get("source_name") or "No Name"
                    content_preview = e.content or ""
                    if len(content_preview) > 50000:
                        content_preview = content_preview[:50000] + "\n（内容过长已截断）"
                    matched_context += f"【已检索数据：{filename}（类型：{e.source_type}）】\n{content_preview}\n----------------\n"
                return matched_context

            if not unique_entries:
                should_include_import = any(k in q for k in profile_keywords)
                fallback_entries = []
                for e in limited_candidates:
                    meta = e.meta_info or {}
                    if meta.get("filename") or meta.get("original_audio_filename"):
                        fallback_entries.append(e)
                        continue
                    st = (e.source_type or "").strip()
                    if st.startswith("document_") or st.startswith("audio_") or st.startswith("audio_transcription"):
                        fallback_entries.append(e)
                        continue
                    if should_include_import and st == "import_record":
                        fallback_entries.append(e)
                        continue
                unique_entries = fallback_entries[:max_results]
                if unique_entries:
                    logger.info("Customer data retrieval fallback applied", extra={"count": len(unique_entries)})
            else:
                unique_entries = unique_entries[:max_results]

            for e in unique_entries:
                meta = e.meta_info or {}
                filename = meta.get("filename") or meta.get("original_audio_filename") or meta.get("source_name") or "导入记录"
                if e.source_type == "import_record":
                    content_dict = {
                        k: v
                        for k, v in meta.items()
                        if k
                        not in (
                            "source_type",
                            "source_name",
                            "data_source_id",
                            "_feishu_token",
                            "_feishu_table_id",
                        )
                    }
                    if content_dict:
                        content_preview = " | ".join([f"{k}:{v}" for k, v in content_dict.items()])
                    else:
                        content_preview = e.content or ""
                else:
                    content_preview = e.content or ""
                if len(content_preview) > 50000:
                    content_preview = content_preview[:50000] + "\n（内容过长已截断）"
                matched_context += f"【已检索数据：{filename}（类型：{e.source_type}）】\n{content_preview}\n----------------\n"
        except Exception:
            logger.exception("Customer data retrieval failed")
            matched_context = ""

        return matched_context

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
            response_content = self.to_plain_text(response.content)
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
        response_content = self.to_plain_text(response_content)
        self._save_agent_ai_response(customer_id, response_content)

    def build_full_customer_context(self, customer_id: int, include_chat: bool = True) -> str:
        customer = self.db.query(models.Customer).filter(models.Customer.id == customer_id).first()
        if not customer:
            return ""
        entries = sorted(customer.data_entries or [], key=lambda x: x.created_at)
        context_text = ""
        for entry in entries:
            st = (entry.source_type or "").strip()
            if not include_chat and (st.startswith("chat_history_") or st.startswith("agent_chat_")):
                continue
            meta = entry.meta_info or {}
            label_name = meta.get("filename") or meta.get("original_audio_filename") or meta.get("source_name")
            label = f"{st}:{label_name}" if label_name else st
            if st == "import_record":
                source_name = meta.get("source_name") or meta.get("_feishu_table_id") or meta.get("_feishu_token") or "导入记录"
                content_dict = {
                    k: v
                    for k, v in meta.items()
                    if k
                    not in (
                        "source_type",
                        "source_name",
                        "data_source_id",
                        "_feishu_token",
                        "_feishu_table_id",
                    )
                }
                line = ""
                if content_dict:
                    line = " | ".join([f"{k}:{v}" for k, v in content_dict.items()])
                elif entry.content:
                    line = entry.content
                if line:
                    context_text += f"【import_record:{source_name}】\n{line}\n----------------\n"
                continue
            if entry.content:
                context_text += f"【{label}】\n{entry.content}\n----------------\n"
        return context_text

    def identify_relevant_tables(self, query: str, table_names: list[str]) -> list[str]:
        """
        Identify relevant tables from a list based on user query using LLM.
        """
        if not query or not table_names:
            return table_names
        
        # If query explicitly asks for "all" or "everything", return all
        if any(keyword in query for keyword in ["全部", "所有", "一切", "all", "everything"]):
            return table_names

        llm = self.get_llm(skill_name="data_selector")
        
        prompt = f"""
User Query: "{query}"
Available Data Tables: {json.dumps(table_names, ensure_ascii=False)}

Analyze the user's query and identify which tables from the list are relevant.
Return a JSON list of strings containing ONLY the relevant table names.
- If the user asks for specific information (e.g., "assets", "transactions"), select tables that likely contain that data based on their names.
- If the user asks for "basic info" or "profile", select tables related to basic information if available.
- If the query implies looking up specific records, select tables that might contain them.
- If no tables seem relevant or the query is too broad/unrelated to specific tables, return an empty list.
- Fuzzy matching is encouraged (e.g. "transaction" -> "TransTable").

Output Example: ["Table A", "Table B"]
Return ONLY the JSON list.
"""
        messages = [
            SystemMessage(content="You are a data selection assistant. You select relevant data tables based on user queries."),
            HumanMessage(content=prompt)
        ]
        
        try:
            response = llm.invoke(messages)
            content = response.content.strip()
            # Try to parse JSON
            # Clean up potential markdown code blocks
            if content.startswith("```"):
                parts = content.split("```")
                if len(parts) >= 2:
                    content = parts[1]
                    if content.startswith("json"):
                        content = content[4:]
            
            selected = json.loads(content.strip())
            if isinstance(selected, list):
                # Verify names exist
                valid_names = [n for n in selected if n in table_names]
                # If LLM returns empty list (no match), we return empty list to show no tables.
                return valid_names
        except Exception as e:
            logger.error(f"Error identifying relevant tables: {e}")
            return table_names # Fallback to all on error

        return table_names

    def build_structured_info_response(self, customer_id: int, query: str | None = None) -> str:
        customer = self.db.query(models.Customer).filter(models.Customer.id == customer_id).first()
        if not customer:
            return "未找到客户信息"
        entries = sorted(customer.data_entries or [], key=lambda x: x.created_at)
        matched = self.match_customer_schema(customer_id, query or "")
        schema = matched.get("schema") or {}
        all_table_names: list[str] = schema.get("table_names") or []
        explicit_tables: list[str] = matched.get("explicit_tables") or []
        fuzzy_tables: list[str] = matched.get("fuzzy_tables") or []
        field_tables: list[str] = matched.get("field_tables") or []
        matched_fields: list[str] = matched.get("matched_fields") or []
        table_name_norms = {self._normalize_match_text(t) for t in all_table_names if self._normalize_match_text(t)}
        field_tables_map: dict[str, set[str]] = schema.get("field_to_tables") or {}
        norm_field_to_tables: dict[str, set[str]] = {}
        for f, tables in field_tables_map.items():
            nf = self._normalize_match_text(f)
            if not nf:
                continue
            norm_field_to_tables.setdefault(nf, set()).update(tables)
        effective_fields = [
            f
            for f in matched_fields
            if self._normalize_match_text(f)
            and self._normalize_match_text(f) not in table_name_norms
            and f not in explicit_tables
        ]

        if query:
            if explicit_tables:
                target_tables = explicit_tables
            elif field_tables:
                target_tables = field_tables
            elif fuzzy_tables:
                target_tables = fuzzy_tables
            elif all_table_names:
                target_tables = self.identify_relevant_tables(query, list(all_table_names))
            else:
                target_tables = []
        else:
            target_tables = list(all_table_names)

        lines: list[str] = []
        norm_query = self._normalize_match_text(query or "")
        basic_field_names = ["姓名", "沟通阶段", "风险偏好", "联系方式"]
        show_basic = (not query) or ("基本信息" in (query or "")) or ("基础信息" in (query or "")) or any(self._normalize_match_text(f) in norm_query for f in basic_field_names)

        if show_basic:
            basic_pairs = [
                ("姓名", customer.name),
                ("沟通阶段", customer.stage),
                ("风险偏好", customer.risk_profile or "未评估"),
            ]
            if customer.contact_info:
                basic_pairs.append(("联系方式", customer.contact_info))

            if effective_fields:
                keep_norms = {self._normalize_match_text(x) for x in effective_fields if self._normalize_match_text(x)}
                basic_pairs = [(k, v) for (k, v) in basic_pairs if self._normalize_match_text(k) in keep_norms]

            if basic_pairs:
                lines.append("【客户基本信息】")
                for k, v in basic_pairs:
                    lines.append(f"{k}：{v}")
                lines.append("----------------")

        table_rows: dict[str, list[dict]] = {}
        archives: list[str] = []
        alias_cache: dict[str, dict[str, str]] = {}
        reserved = {"source_type", "source_name", "data_source_id", "_feishu_token", "_feishu_table_id"}
        
        for entry in entries:
            st = (entry.source_type or "").strip()
            meta = entry.meta_info or {}
            
            if st == "import_record":
                source_name = self._resolve_import_table_name(meta, alias_cache)
                
                # Filter: source_name must be in target_tables
                if query and source_name not in target_tables:
                     continue
                    
                row = {
                    k: v
                    for k, v in meta.items()
                    if k and k not in reserved and not str(k).startswith("_")
                }
                updated_at = getattr(entry, "created_at", None)
                row_with_time = {"更新时间": str(updated_at) if updated_at is not None else "", **row}
                if row_with_time:
                    table_rows.setdefault(source_name, []).append(row_with_time)
                continue
                
            # Archives
            # Show archives if:
            # - No query (default)
            # - Query asks for "archives", "documents", "files"
            show_archives = not query or any(k in query for k in ["档案", "资料", "文件", "archive", "document", "file"])
            
            if show_archives and (st.startswith("document_") or st.startswith("audio_") or st.startswith("audio_transcription")):
                label = meta.get("filename") or meta.get("original_audio_filename") or meta.get("source_name") or st
                preview = entry.content or ""
                if len(preview) > 500:
                    preview = preview[:500] + "…"
                archives.append(f"{label}：{preview}")

        if query and target_tables and not any(t in table_rows for t in target_tables) and not archives and not lines:
            lines.append("未找到与问题相关的数据")

        ordered_tables = target_tables if query and target_tables else list(table_rows.keys())
        for table_name in ordered_tables:
            rows = table_rows.get(table_name, [])
            rows_sorted = sorted(rows, key=lambda r: str(r.get("更新时间") or ""), reverse=True)
            lines.append(f"【{table_name}】")
            if not rows_sorted:
                lines.append("（暂无数据）")
                lines.append("----------------")
                continue
            for row in rows_sorted:
                updated_at = str(row.get("更新时间") or "").strip()
                lines.append("【数据详情】")
                if updated_at:
                    lines.append(f"更新时间：{updated_at}")
                keys = [x for x in row.keys() if x and x != "更新时间"]
                if effective_fields:
                    keep_norms = {self._normalize_match_text(x) for x in effective_fields if self._normalize_match_text(x)}
                    keep_norms = {n for n in keep_norms if norm_field_to_tables.get(n, set()) & set(target_tables)}
                    keys = [k for k in keys if self._normalize_match_text(k) in keep_norms]
                for k in sorted(keys):
                    v = row.get(k, "")
                    s = str(v) if v is not None else ""
                    s = s.replace("\r\n", "\n").replace("\n", " ").strip()
                    lines.append(f"{k}：{s}")
                lines.append("----------------")

        if archives:
            lines.append("【档案资料】")
            lines.extend([f"- {item}" for item in archives])

        return "\n".join(lines)

    def build_structured_info_analysis_response(self, customer_id: int, query: str, model: str | None = None) -> str:
        structured = self.build_structured_info_response(customer_id, query=query)
        if not structured:
            return "未找到客户信息"
        if "未找到与问题相关的数据" in structured:
            return structured + "\n分析结论：未找到可分析的数据"
        llm = self.get_llm(config_name=model, skill_name="chat")
        system_instruction = """你是转化运营团队的客户数据分析助手。
要求：仅输出纯文本，不要使用 Markdown，不要使用表格、列表符号或特殊格式。
基于给定结构化数据，给出简洁的分析结论和推进建议。"""
        messages = [
            SystemMessage(content=system_instruction),
            HumanMessage(content=f"用户问题：{query}\n结构化数据：\n{structured}\n请给出分析结论和建议。")
        ]
        chain = llm | StrOutputParser()
        analysis = chain.invoke(messages)
        analysis = self.to_plain_text(analysis)
        if not analysis:
            analysis = "暂无法生成有效分析"
        return f"{structured}\n分析结论：\n{analysis}"

    def evaluate_sales_progression(self, customer_id: int) -> dict:
        """
        核心功能：推进建议
        """
        customer = self.db.query(models.Customer).filter(models.Customer.id == customer_id).first()
        if not customer:
            raise ValueError(f"Customer {customer_id} not found")

        context_text = self.build_full_customer_context(customer_id, include_chat=True)

        system_prompt = """你是一位严谨的销售总监。你只回答一个问题：
"现在适不适合推进成交？"

请基于客户的全量历史数据（聊天记录、录音转写、资产信息、购买记录），给出明确结论。
这个判断能极大减少硬推、错推和情绪化推进。

输出必须是严格 JSON 对象，且只包含以下字段：
{
  "推进建议": "建议推进 | 建议放缓 | 不建议推进",
  "核心理由": "一句话核心理由，必须可被历史数据支撑",
  "支撑证据": ["从数据中提取的2-3条具体证据"],
  "关键阻碍": ["具体阻碍点或未化解的顾虑，没有则空列表"],
  "下一步建议": "下一步具体动作建议，必须可执行、可落地"
}

【判断框架】
建议推进的信号：
- 客户主动询问费率、合同细节、流程时间
- 客户对产品表现出明确兴趣且核心顾虑已化解
- 客户在比较竞品，说明已进入决策阶段

建议放缓的信号：
- 客户还在问基础概念，尚未建立产品认知
- 客户对资金安全极度担忧且未被化解
- 信息不足或信号矛盾，无法判断真实意向
- 客户明确表示"再想想""不急"

不建议推进的信号：
- 客户多次明确拒绝或回避
- 客户的真实风险承受能力与产品不匹配
- 存在合规风险（如客户明显不适合该产品）

【重要】
- 宁可放缓也不要误判推进——错推一次可能永久失去客户
- 结论必须明确，不要模棱两可
- "下一步建议"必须是转化同学明天就能做的事"""

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
                return "建议放缓"
            text = str(value).strip().lower()
            mapping = {
                "recommend": "建议推进",
                "hold": "建议放缓",
                "stop": "不建议推进",
                "建议推进": "建议推进",
                "建议放缓": "建议放缓",
                "不建议推进": "不建议推进",
                "建议观望": "建议放缓",
                "建议停止": "不建议推进",
                "推进": "建议推进",
                "放缓": "建议放缓",
                "观望": "建议放缓",
                "停止": "不建议推进",
                "不建议": "不建议推进"
            }
            for k, v in mapping.items():
                if k in text:
                    return v
            return "建议放缓"

        if isinstance(result, dict):
            recommendation = result.get("推进建议") or result.get("recommendation")
            reason = result.get("核心理由") or result.get("reason") or "AI 解析响应失败，建议人工判断"
            key_blockers = result.get("关键阻碍") or result.get("key_blockers") or []
            next_step = result.get("下一步建议") or result.get("next_step_suggestion") or "检查日志"
        else:
            recommendation = "建议放缓"
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

        system_prompt = """你是转化运营团队的知识库整理专家。你的任务是将原始文本（可能包含噪音、格式混乱或口语化内容）整理成结构清晰、便于转化同学查阅和系统检索的 Markdown 文档。

【处理原则】
1. **结构化**：使用合理的 Markdown 标题（# ## ###）分层级组织内容
2. **核心摘要**：在文档开头生成一段【核心摘要】，概4句话概括文档主要内容
3. **清洗**：去除无意义的字符、乱码或无关的元数据
4. **保留**：保留所有关键事实、数据、专有名词和逻辑关系，不要过度删减
5. **格式**：关键术语用 **加粗** 强调，列表内容使用 - 或 1. 列表
6. **业务导向**：如果内容涉及产品、策略或合规，请标注清楚，方便后续检索命中

请直接输出整理后的 Markdown 内容，不要包含“好的”“如下是整理后的内容”等废话。"""

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

        system_prompt = """你是转化运营团队的金牌话术整理专家。你的任务是将原始话术文档（可能是对话记录、培训手册或散乱的笔记）整理成转化同学可直接实战使用的结构化 Markdown 格式。

【处理原则】
1. **问答提取**：重点识别“客户异议/问题”与“推荐回复”，整理为 `### Q: [问题]` 和 `**A:** [回复]` 的形式
2. **核心提炼**：在文档开头总结【核心卖点】与【适用场景】
3. **阶段分类**：使用清晰的层级（# ## ###），将话术按使用场景分类（如开场、异议处理、信任建立、推进成交、风险提示等）
4. **清洗优化**：去除口语废话，保留高情商、有说服力的表达；适当润色不通顺的句子
5. **合规标注**：如发现话术中有承诺收益、夸大表述等合规风险，请标注 ⚠️风险 并建议修改

请直接输出整理后的 Markdown 内容，不要包含“好的”等废话。"""

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
