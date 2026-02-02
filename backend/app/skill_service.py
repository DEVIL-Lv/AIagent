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
        你是一个资深的财富管理风控专家。请分析以下客户数据，输出一份风险偏好报告。
        
        客户背景信息：
        {input}
        
        请包含以下部分：
        1. 风险承受能力评估
        2. 投资目标分析
        3. 建议的资产配置比例
        """
        # Pass skill_name
        return self._invoke_with_fallback(prompt, skill_name="risk_analysis", input_text=context)

    def generate_reply(self, context: str, question: str) -> str:
        print("DEBUG: generate_reply entered")
        """
        Skill: 金牌销售话术生成
        """
        prompt = """
        你是一个金牌销售顾问。请根据以下客户背景和当前对话场景，生成一段专业的回复。
        
        客户背景：
        {context}
        
        用户问题/当前场景：
        {question}
        
        请直接给出回复建议，语气专业且亲切。
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
        你是一个销售策略专家。请评估当前客户的成交可能性。
        
        客户信息：
        {input}
        
        请分析：
        1. 客户意向等级 (高/中/低)
        2. 主要痛点
        3. 建议的下一步行动
        """
        return self._invoke_with_fallback(prompt, skill_name="deal_evaluation", input_text=context)

    def analyze_call(self, call_content: str) -> str:
        """
        Skill: 通话深度分析
        """
        prompt = """
        你是一个专业的对话分析专家。请仔细阅读以下通话录音/对话内容，进行深度分析。
        
        通话内容：
        {input}
        
        请输出以下分析结果：
        1. **核心摘要**：简要概括通话的主要内容。
        2. **关键信息提取**：提取对话中涉及的关键要素（如金额、时间、需求、异议等）。
        3. **客户情绪分析**：判断客户在对话中的情绪变化（积极/消极/中性）。
        4. **潜在机会/风险**：识别对话中暴露出的销售机会或潜在风险点。
        5. **下一步建议**：基于此次通话，建议后续的跟进策略。
        """
        return self._invoke_with_fallback(prompt, skill_name="call_analysis", input_text=call_content)

    def analyze_file(self, content: str) -> str:
        """
        Skill: 通用文件深度分析
        """
        prompt = """
        你是一个专业的商业文档分析专家。请仔细阅读以下文档内容，进行深度分析。

        文档内容：
        {input}

        请输出以下分析结果：
        1. **核心摘要**：简要概括文档的主要内容。
        2. **关键信息提取**：提取文档中的关键数据、结论或条款。
        3. **意图/价值分析**：分析该文档的核心意图或商业价值。
        4. **行动建议**：基于文档内容，建议后续的行动或注意事项。
        """
        return self._invoke_with_fallback(prompt, skill_name="file_analysis", input_text=content)
