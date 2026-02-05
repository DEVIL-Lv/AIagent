from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Any, Dict
from datetime import datetime, timezone

# --- Customer Schemas ---
class CustomerBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str
    contact_info: Optional[str] = None
    stage: Optional[str] = Field(default="contact_before", alias="阶段")
    risk_profile: Optional[str] = Field(default=None, alias="风险偏好")
    summary: Optional[str] = Field(default=None, alias="画像摘要")
    custom_fields: Optional[Dict[str, Any]] = None

class CustomerCreate(CustomerBase):
    pass

class CustomerUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: Optional[str] = None
    contact_info: Optional[str] = None
    stage: Optional[str] = Field(default=None, alias="阶段")
    risk_profile: Optional[str] = Field(default=None, alias="风险偏好")
    summary: Optional[str] = Field(default=None, alias="画像摘要")
    custom_fields: Optional[Dict[str, Any]] = None

class Customer(CustomerBase):
    id: int
    created_at: datetime
    class Config:
        from_attributes = True

# --- Customer Data Schemas ---
class CustomerDataBase(BaseModel):
    source_type: str
    content: str
    meta_info: Optional[dict] = None

class CustomerDataCreate(CustomerDataBase):
    file_binary: Optional[bytes] = None

class CustomerData(CustomerDataBase):
    id: int
    customer_id: int
    created_at: datetime
    class Config:
        from_attributes = True

class CustomerDetail(Customer):
    data_entries: List[CustomerData] = []

# --- LLM Schemas ---
class LLMConfigBase(BaseModel):
    name: str
    provider: str
    api_base: Optional[str] = None
    api_key: str
    model_name: str
    temperature: float = 0.7
    cost_input_1k: float = 0.0
    cost_output_1k: float = 0.0
    is_active: bool = True

class LLMConfigCreate(LLMConfigBase):
    pass

class LLMConfig(LLMConfigBase):
    id: int
    total_tokens: int = 0
    total_cost: float = 0.0
    class Config:
        from_attributes = True

class LLMConfigUpdate(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    model_name: Optional[str] = None
    temperature: Optional[float] = None
    cost_input_1k: Optional[float] = None
    cost_output_1k: Optional[float] = None
    is_active: Optional[bool] = None

# --- Skill Route Schemas ---
class SkillRouteBase(BaseModel):
    skill_name: str
    llm_config_id: int

class SkillRouteCreate(SkillRouteBase):
    pass

class SkillRoute(SkillRouteBase):
    id: int
    llm_config: Optional[LLMConfig] = None
    class Config:
        from_attributes = True

# --- Data Source Schemas ---
class DataSourceConfigBase(BaseModel):
    name: str
    source_type: str
    config_json: Dict[str, Any]
    is_active: bool = True

class DataSourceConfigCreate(DataSourceConfigBase):
    pass

class DataSourceConfig(DataSourceConfigBase):
    id: int
    class Config:
        from_attributes = True

class DataSourceConfigUpdate(BaseModel):
    name: Optional[str] = None
    source_type: Optional[str] = None
    config_json: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None

# --- Routing Rule Schemas ---
class RoutingRuleBase(BaseModel):
    keyword: str
    target_skill: str
    description: Optional[str] = None
    is_active: bool = True

class RoutingRuleCreate(RoutingRuleBase):
    pass

class RoutingRule(RoutingRuleBase):
    id: int
    class Config:
        from_attributes = True

class KnowledgeDocumentBase(BaseModel):
    title: str
    content: str
    source: str
    category: str = "general"

class KnowledgeDocumentCreate(KnowledgeDocumentBase):
    pass

class KnowledgeDocument(KnowledgeDocumentBase):
    id: int
    created_at: datetime
    raw_content: Optional[str] = None
    class Config:
        from_attributes = True
        json_encoders = {datetime: lambda v: (v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)).isoformat()}

class SalesTalkBase(BaseModel):
    title: str
    category: str = "general"
    filename: str
    file_path: str
    content: str
    raw_content: Optional[str] = None

class SalesTalkCreate(SalesTalkBase):
    pass

class SalesTalk(SalesTalkBase):
    id: int
    created_at: datetime
    updated_at: datetime
    raw_content: Optional[str] = None
    class Config:
        from_attributes = True
        json_encoders = {datetime: lambda v: (v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)).isoformat()}

# --- Analysis Schemas ---

class ReplySuggestionRequest(BaseModel):
    customer_id: int
    intent: Optional[str] = None # 用户可以手动输入意图，例如“我想催单”
    chat_context: Optional[str] = None # 最近的对话内容，如果为空则自动从数据库取

class ReplySuggestionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    suggested_reply: str = Field(alias="建议回复")
    rationale: str = Field(alias="回复理由")
    risk_alert: Optional[str] = Field(default=None, alias="风险提示")

class ProgressionAnalysisRequest(BaseModel):
    customer_id: int

class ProgressionAnalysisResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    recommendation: str = Field(alias="推进建议")
    reason: str = Field(alias="核心理由")
    key_blockers: List[str] = Field(default_factory=list, alias="关键阻碍")
    next_step_suggestion: str = Field(alias="下一步建议")

class AgentChatRequest(BaseModel):
    query: str
    model: Optional[str] = None
    history: List[Dict[str, str]] = [] # [{'role': 'user', 'content': '...'}, ...]

class AgentChatResponse(BaseModel):
    response: str

class RunSkillRequest(BaseModel):
    skill_name: str
    question: Optional[str] = None
    model: Optional[str] = None
