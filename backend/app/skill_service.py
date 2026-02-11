from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from .llm_service import LLMService
import re

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

    def _sanitize_output(self, text: str) -> str:
        if not text:
            return text
        cleaned = self.llm_service.to_plain_text(text)
        cleaned = re.sub(r"[\x00-\x08\x0B-\x1F\x7F]", "", cleaned)
        cleaned = re.sub(r"[<>]{2,}", "", cleaned)
        cleaned = re.sub(r"[\\/|~`^_+=]{3,}", "", cleaned)
        return cleaned.strip()

    def _invoke_with_fallback(self, system_prompt: str, skill_name: str, input_text: str) -> str:
        format_guard = (
            "\n\n输出格式要求：\n"
            "1、仅输出纯文本，不要使用 Markdown，不要输出 ###、```、| 表格、** 加粗等格式\n"
            "2、不要使用项目符号（-、*、+），如需分点请使用中文序号（1、2、3）\n"
            "3、不要输出无意义符号，内容清晰直接\n"
        )
        system_prompt = (system_prompt or "") + format_guard
        chain = self._get_chain(system_prompt, skill_name=skill_name)
        try:
            result = chain.invoke({"input": input_text})
            return self._sanitize_output(result)
        except Exception as e:
            msg = str(e)
            if ("Error code: 403" in msg) and ("Request not allowed" in msg):
                fallback_chain = self._get_chain(system_prompt, skill_name="chat")
                result = fallback_chain.invoke({"input": input_text})
                return self._sanitize_output(result)
            raise

    def analyze_risk(self, context: str) -> str:
        """
        Skill: 风险偏好深度分析
        """
        prompt = """
        你是转化运营团队的风险偏好分析专家。请基于客户数据输出风险偏好报告，帮助转化同学快速理解客户的真实风险承受能力。
        
        客户背景信息：
        {input}
        
        输出要求：
        1. 风险承受能力评估（优先看行为而非口头表达）
        2. 回撤容忍度分析
        3. 客户真实投资目标与需求
        4. 风险提示（客户口头表达与行为不一致的地方）
        
        【重要】这是给转化同学看的内部分析，不是给客户看的。
        输出为中文，直接给结论与建议，不要输出推理过程。
        """
        # Pass skill_name
        return self._invoke_with_fallback(prompt, skill_name="risk_analysis", input_text=context)

    def generate_reply(self, context: str, question: str) -> str:
        """
        Skill: 金牌销售话术生成
        """
        prompt = """
        你是转化运营团队的金牌销售教练。请根据客户背景与当前对话场景，生成一段可直接发送的专业回复。
        
        客户背景：
        {context}
        
        用户问题/当前场景：
        {question}
        
        输出要求：
        - 语气不卑不亢，亲切但专业，建立平等关系
        - 可适度提出一个确认式问题以推动对话继续
        - 不承诺收益、不保证结果、不夸大或虚构
        - 不要终结对话，保持对话流动
        
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
        你是转化运营团队的推进研判专家。请评估当前客户是否适合推进成交。
        
        客户信息：
        {input}
        
        输出要求：
        1. 推进建议（建议推进 / 建议放缓 / 不建议推进）
        2. 核心理由（必须有数据支撑）
        3. 关键阻碍或未化解的顾虑（列点）
        4. 下一步具体动作（必须可执行、可落地）
        
        【重要】宁可放缓也不要误判推进，错推一次可能永久失去客户。
        输出为中文，直接给结论与建议，不要输出推理过程。
        """
        return self._invoke_with_fallback(prompt, skill_name="deal_evaluation", input_text=context)

    def analyze_call(self, call_content: str) -> str:
        """
        Skill: 通话深度分析
        """
        prompt = """
        你是转化运营团队的通话分析专家。请仔细阅读通话录音/对话内容，输出面向转化同学的深度分析。
        
        通话内容：
        {input}
        
        输出要求：
        1. 核心摘要：简要概括通话主要内容
        2. 关键信息提取：金额、时间、产品名称、客户需求、异议点
        3. 客户情绪/态度：积极/消极/犹豫/担忧 及具体依据
        4. 核心顾虑：客户反复提及或回避的问题
        5. 机会与风险：可以抓住的机会和需要注意的雷区
        6. 下一步建议：转化同学可执行的具体跟进策略
        
        输出为中文，直接给结论与建议，不要输出推理过程。
        """
        return self._invoke_with_fallback(prompt, skill_name="call_analysis", input_text=call_content)

    def analyze_file(self, content: str) -> str:
        """
        Skill: 通用文件深度分析
        """
        prompt = """
        你是转化运营团队的文档分析专家。请仔细阅读文档内容，输出面向转化同学的结构化分析。

        文档内容：
        {input}

        输出要求：
        1. 核心摘要：简要概括文档的主要内容
        2. 关键信息提取：关键数据、结论或条款
        3. 业务价值：对转化工作有什么用（产品特点、竞争优势、合规要求等）
        4. 行动建议：转化同学可以怎么用这份材料
        
        输出为中文，直接给结论与建议，不要输出推理过程。
        """
        return self._invoke_with_fallback(prompt, skill_name="file_analysis", input_text=content)

    def core_assistant(self, context: str, query: str, rag_context: str = "") -> str:
        system_prompt = """
        你是转化运营团队的 AI 辅助决策与话术系统。请基于输入内容输出最合适的结果。
        
        你的三个核心能力：
        1. 客户理解：画像速览（阶段、风险偏好、核心顾虑、关键机会与风险）
        2. 话术辅助：回应方向 + 金牌回复 + 风险提示
        3. 推进建议：明确结论 + 理由 + 下一步动作
        
        【底线】不承诺收益，不保证结果，不夸大，涉及产品请提示“以正式材料为准”。
        输出为中文，直接给结论与建议，不要输出推理过程。
        """
        input_text = query.strip() if query else "请生成一份客户速览，包含画像、阶段、风险偏好、关键机会与风险、下一步建议。"
        payload = f"【客户上下文】\n{context}\n\n【参考知识库】\n{rag_context or '（未匹配到相关知识库文档）'}\n\n【问题】\n{input_text}"
        return self._invoke_with_fallback(system_prompt, skill_name="core", input_text=payload)

    def analyze_content(self, content: str) -> str:
        prompt = """
        你是转化运营团队的内容分析专家。请分析以下内容并输出面向转化同学的结构化结果。
        
        先判断内容更像“通话记录/对话文本”或“文档/资料”，再按对应维度输出：
        - 通话/对话：核心摘要、关键信息、客户情绪与核心顾虑、机会/风险点、下一步建议
        - 文档/资料：核心摘要、关键信息、业务价值、风险点、行动建议
        
        内容：
        {input}
        
        输出为中文，直接给结论与建议，不要输出推理过程。
        """
        return self._invoke_with_fallback(prompt, skill_name="content_analysis", input_text=content)
