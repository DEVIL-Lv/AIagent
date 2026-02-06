from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Float, JSON, Boolean, LargeBinary
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(255), unique=True, index=True)
    hashed_password = Column(String(255))
    role = Column(String(50), default="admin") # admin, sales
    created_at = Column(DateTime, default=datetime.utcnow)

class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), index=True)
    contact_info = Column(String(255), nullable=True)
    # Stage: contact_before, trust_building, product_matching, closing
    stage = Column(String(50), default="contact_before")
    # Risk Profile
    risk_profile = Column(Text, nullable=True)
    # AI Summary
    summary = Column(Text, nullable=True)
    # Dynamic fields from import
    custom_fields = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    data_entries = relationship("CustomerData", back_populates="customer")

class CustomerData(Base):
    __tablename__ = "customer_data"
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    # Source: chat_history, audio_transcript, asset_table, manual_note, file_upload
    source_type = Column(String(100))
    content = Column(Text)
    # Meta info like token_count, upload_time, file_path
    meta_info = Column(JSON, nullable=True)
    # Binary file content (for direct DB storage)
    file_binary = Column(LargeBinary, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer", back_populates="data_entries")
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=True)
    session = relationship("ChatSession", back_populates="customer_data_entries")

class ChatSession(Base):
    """支持多会话管理 (New Chat / History List)"""
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    title = Column(String(255)) 
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True) # Soft delete

    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")
    customer_data_entries = relationship("CustomerData", back_populates="session")

class ChatMessage(Base):
    """通用聊天消息记录 (Global Chat)"""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"))
    role = Column(String(50)) # "user", "ai", "system"
    content = Column(Text)
    meta_info = Column(JSON, nullable=True) 
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("ChatSession", back_populates="messages")

class LLMConfig(Base):
    __tablename__ = "llm_configs"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True) # e.g. "GPT-4-Turbo"
    provider = Column(String(50)) # "openai", "azure_openai", "anthropic"
    api_base = Column(String(512), nullable=True)
    api_key = Column(Text)
    model_name = Column(String(255)) # e.g. "gpt-4-0125-preview"
    embedding_model_name = Column(String(255), nullable=True) # e.g. "text-embedding-ada-002"
    temperature = Column(Float, default=0.7)
    # Cost tracking (Cost per 1k tokens)
    cost_input_1k = Column(Float, default=0.0) 
    cost_output_1k = Column(Float, default=0.0)
    
    # Stats
    total_tokens = Column(Integer, default=0)
    total_cost = Column(Float, default=0.0)
    
    is_active = Column(Boolean, default=True)

class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), index=True)
    content = Column(Text)
    raw_content = Column(Text, nullable=True)
    source = Column(String(255))  # e.g., filename or "manual_entry"
    category = Column(String(100), default="general") # e.g., "product", "sales_technique"
    created_at = Column(DateTime, default=datetime.utcnow)

class SalesTalk(Base):
    __tablename__ = "scripts"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), index=True)
    category = Column(String(100), default="general")
    filename = Column(String(255))
    file_path = Column(String(512))
    content = Column(Text)
    raw_content = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SkillRoute(Base):
    """Configuration for which LLM executes which Skill"""
    __tablename__ = "skill_routes"
    id = Column(Integer, primary_key=True, index=True)
    skill_name = Column(String(255), unique=True) # e.g. "risk_analysis"
    llm_config_id = Column(Integer, ForeignKey("llm_configs.id"))
    
    llm_config = relationship("LLMConfig")

class DataSourceConfig(Base):
    """Configuration for external data sources (Feishu, DB)"""
    __tablename__ = "data_source_configs"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255)) # e.g. "Company Feishu"
    source_type = Column(String(50)) # "feishu", "mysql", "file_server"
    config_json = Column(JSON) # { "app_id": "...", "app_secret": "..." }
    is_active = Column(Boolean, default=True)

class RoutingRule(Base):
    """Rules for routing chat messages to specific skills based on keywords"""
    __tablename__ = "routing_rules"
    id = Column(Integer, primary_key=True, index=True)
    keyword = Column(String(255), index=True) # e.g. "风险"
    target_skill = Column(String(255)) # e.g. "risk_analysis"
    description = Column(String(512), nullable=True)
    is_active = Column(Boolean, default=True)
