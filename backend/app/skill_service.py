from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from .llm_service import LLMService

class SkillService:
    def __init__(self, db_session, config_name: str | None = None):
        self.db = db_session
        self.llm_service = LLMService(db_session)
        self.config_name = config_name

    def _get_chain(self, system_prompt: str, skill_name: str):
        # Pass skill_name to get_llm for routing
        llm = self.llm_service.get_llm(config_name=self.config_name, skill_name=skill_name)
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{input}")
        ])
        return prompt | llm | StrOutputParser()

    def _invoke_with_fallback(self, system_prompt: str, skill_name: str, input_text: str) -> str:
        chain = self._get_chain(system_prompt, skill_name=skill_name)
        try:
            return chain.invoke({"input": input_text})
        except Exception as e:
            msg = str(e)
            if ("Error code: 403" in msg) and ("Request not allowed" in msg):
                fallback_chain = self._get_chain(system_prompt, skill_name="chat")
                return fallback_chain.invoke({"input": input_text})
            raise

    def analyze_risk(self, context: str) -> str:
        """
        Skill: 风险偏好深度分析
        """
        prompt = """
        你是资深的财富管理风控专家。请基于客户数据输出风险偏好报告。
        
        客户背景信息：
        {input}
        
        输出要求：
        1. 风险承受能力评估
        2. 投资目标分析
        3. 建议的资产配置比例
        4. 重点风险提示（如有）
        
        输出为中文，直接给结论与建议，不要输出推理过程。
        """
        # Pass skill_name
        return self._invoke_with_fallback(prompt, skill_name="risk_analysis", input_text=context)

    def generate_reply(self, context: str, question: str) -> str:
        """
        Skill: 金牌销售话术生成
        """
        prompt = """
        你是金牌销售顾问。请根据客户背景与当前对话场景，生成一段可直接发送的专业回复。
        
        客户背景：
        {context}
        
        用户问题/当前场景：
        {question}
        
        输出要求：
        - 语气专业且亲切
        - 可适度提出一个确认式问题以推动对话
        - 不承诺收益、不保证结果、不夸大或虚构
        
        输出为中文，直接给回复内容。
        """
        # Inject context and question into the system prompt
        filled_prompt = prompt.replace("{context}", context).replace("{question}", question)
        
        chain = self._get_chain(filled_prompt, skill_name="reply_suggestion")
        
        # Pass the question as human input as well
        return self._invoke_with_fallback(filled_prompt, skill_name="reply_suggestion", input_text=question)

    def evaluate_deal(self, context: str) -> str:
        """
        Skill: 推进可行性研判
        """
        prompt = """
        你是销售策略专家。请评估当前客户的成交可能性。
        
        客户信息：
        {input}
        
        输出要求：
        1. 客户意向等级（高/中/低）
        2. 主要痛点（列点）
        3. 建议的下一步行动（可执行）
        
        输出为中文，直接给结论与建议，不要输出推理过程。
        """
        return self._invoke_with_fallback(prompt, skill_name="deal_evaluation", input_text=context)

    def analyze_call(self, call_content: str) -> str:
        """
        Skill: 通话深度分析
        """
        prompt = """
        你是专业的对话分析专家。请仔细阅读通话录音/对话内容，进行深度分析。
        
        通话内容：
        {input}
        
        输出要求：
        1. 核心摘要：简要概括通话主要内容
        2. 关键信息提取：金额、时间、需求、异议等
        3. 客户情绪分析：积极/消极/中性及依据
        4. 潜在机会/风险：列点说明
        5. 下一步建议：可执行的跟进策略
        
        输出为中文，直接给结论与建议，不要输出推理过程。
        """
        return self._invoke_with_fallback(prompt, skill_name="call_analysis", input_text=call_content)

    def analyze_file(self, content: str) -> str:
        """
        Skill: 通用文件深度分析
        """
        prompt = """
        你是专业的商业文档分析专家。请仔细阅读文档内容，进行深度分析。

        文档内容：
        {input}

        输出要求：
        1. 核心摘要：简要概括文档的主要内容
        2. 关键信息提取：关键数据、结论或条款
        3. 意图/价值分析：文档核心意图或商业价值
        4. 行动建议：后续行动或注意事项
        
        输出为中文，直接给结论与建议，不要输出推理过程。
        """
        return self._invoke_with_fallback(prompt, skill_name="file_analysis", input_text=content)

    def core_assistant(self, context: str, query: str, rag_context: str = "") -> str:
        prompt = f"""
        你是专业的财富管理“转化助手”。请根据客户上下文与运营需求，输出最合适的结果。
        
        可能任务包括（但不限于）：
        1. 客户画像速览（阶段、风险偏好、关键机会与风险、下一步建议）
        2. 风险偏好分析与资产配置建议
        3. 推进研判（意向等级、主要痛点、下一步行动）
        4. 回复建议（可直接发送的回复，并简要说明理由与风险提示）
        
        客户上下文：
        {context}
        
        参考知识库：
        {rag_context or "（未匹配到相关知识库文档）"}
        
        输出为中文，直接给结论与建议，不要输出推理过程。
        """
        input_text = query.strip() if query else "请生成一份客户速览，包含画像、阶段、风险偏好、关键机会与风险、下一步建议。"
        return self._invoke_with_fallback(prompt, skill_name="core", input_text=input_text)

    def analyze_content(self, content: str) -> str:
        prompt = """
        你是资深内容分析专家。请分析以下内容并输出结构化结果。
        
        先判断内容更像“通话记录/对话文本”或“文档/资料”，再按对应维度输出：
        - 通话/对话：核心摘要、关键信息、客户情绪、机会/风险点、下一步建议
        - 文档/资料：核心摘要、关键信息、意图/价值、风险点、行动建议
        
        内容：
        {input}
        
        输出为中文，直接给结论与建议，不要输出推理过程。
        """
        return self._invoke_with_fallback(prompt, skill_name="content_analysis", input_text=content)
