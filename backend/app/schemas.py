from pydantic import BaseModel
from typing import List, Optional, Any, Dict
from datetime import datetime

# --- Customer Schemas ---
class CustomerBase(BaseModel):
    name: str
    contact_info: Optional[str] = None
    stage: Optional[str] = "contact_before"
    risk_profile: Optional[str] = None
    summary: Optional[str] = None
    custom_fields: Optional[Dict[str, Any]] = None

class CustomerCreate(CustomerBase):
    pass

class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    contact_info: Optional[str] = None
    stage: Optional[str] = None
    risk_profile: Optional[str] = None
    summary: Optional[str] = None
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
    class Config:
        from_attributes = True

# --- Analysis Schemas ---

class ReplySuggestionRequest(BaseModel):
    customer_id: int
    intent: Optional[str] = None # 用户可以手动输入意图，例如“我想催单”
    chat_context: Optional[str] = None # 最近的对话内容，如果为空则自动从数据库取

class ReplySuggestionResponse(BaseModel):
    suggested_reply: str
    rationale: str # 为什么要这样回
    risk_alert: Optional[str] = None # 风险提示

class ProgressionAnalysisRequest(BaseModel):
    customer_id: int

class ProgressionAnalysisResponse(BaseModel):
    recommendation: str # "recommend" | "hold" | "stop"
    reason: str
    key_blockers: List[str] = []
    next_step_suggestion: str

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
