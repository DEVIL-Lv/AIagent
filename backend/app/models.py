from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Float, JSON, Boolean, LargeBinary
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(String, default="admin") # admin, sales
    created_at = Column(DateTime, default=datetime.utcnow)

class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    contact_info = Column(String, nullable=True)
    # Stage: contact_before, trust_building, product_matching, closing
    stage = Column(String, default="contact_before")
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
    source_type = Column(String)
    content = Column(Text)
    # Meta info like token_count, upload_time, file_path
    meta_info = Column(JSON, nullable=True)
    # Binary file content (for direct DB storage)
    file_binary = Column(LargeBinary, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer", back_populates="data_entries")

class LLMConfig(Base):
    __tablename__ = "llm_configs"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True) # e.g. "GPT-4-Turbo"
    provider = Column(String) # "openai", "azure_openai", "anthropic"
    api_base = Column(String, nullable=True)
    api_key = Column(String)
    model_name = Column(String) # e.g. "gpt-4-0125-preview"
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
    title = Column(String, index=True)
    content = Column(String)
    source = Column(String)  # e.g., filename or "manual_entry"
    category = Column(String, default="general") # e.g., "product", "sales_technique"
    created_at = Column(DateTime, default=datetime.utcnow)


class SkillRoute(Base):
    """Configuration for which LLM executes which Skill"""
    __tablename__ = "skill_routes"
    id = Column(Integer, primary_key=True, index=True)
    skill_name = Column(String, unique=True) # e.g. "risk_analysis"
    llm_config_id = Column(Integer, ForeignKey("llm_configs.id"))
    
    llm_config = relationship("LLMConfig")

class DataSourceConfig(Base):
    """Configuration for external data sources (Feishu, DB)"""
    __tablename__ = "data_source_configs"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String) # e.g. "Company Feishu"
    source_type = Column(String) # "feishu", "mysql", "file_server"
    config_json = Column(JSON) # { "app_id": "...", "app_secret": "..." }
    is_active = Column(Boolean, default=True)

class RoutingRule(Base):
    """Rules for routing chat messages to specific skills based on keywords"""
    __tablename__ = "routing_rules"
    id = Column(Integer, primary_key=True, index=True)
    keyword = Column(String, index=True) # e.g. "风险"
    target_skill = Column(String) # e.g. "risk_analysis"
    description = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
