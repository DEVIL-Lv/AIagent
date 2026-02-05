from sqlalchemy.orm import Session
from typing import List
from . import models, schemas

def _normalize_stage(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip().lower()
    mapping = {
        "contact_before": "contact_before",
        "trust_building": "trust_building",
        "product_matching": "product_matching",
        "closing": "closing",
        "接触前": "contact_before",
        "待开发": "contact_before",
        "建立信任": "trust_building",
        "需求分析": "product_matching",
        "产品匹配": "product_matching",
        "商务谈判": "closing",
        "成交关闭": "closing",
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
        if k.lower() in text:
            return v
    return value

# Customer CRUD
def get_customer(db: Session, customer_id: int):
    return db.query(models.Customer).filter(models.Customer.id == customer_id).first()

def get_customers(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Customer).offset(skip).limit(limit).all()

def create_customer(db: Session, customer: schemas.CustomerCreate):
    db_customer = models.Customer(**customer.model_dump())
    db.add(db_customer)
    db.commit()
    db.refresh(db_customer)
    return db_customer

def update_customer(db: Session, customer_id: int, customer_update: schemas.CustomerUpdate):
    db_customer = get_customer(db, customer_id)
    if not db_customer:
        return None
    
    update_data = customer_update.model_dump(exclude_unset=True)
    if "stage" in update_data:
        update_data["stage"] = _normalize_stage(update_data.get("stage"))
    for key, value in update_data.items():
        setattr(db_customer, key, value)
    
    db.commit()
    db.refresh(db_customer)
    return db_customer

def delete_customer(db: Session, customer_id: int):
    db_customer = get_customer(db, customer_id)
    if db_customer:
        db.delete(db_customer)
        db.commit()
    return db_customer

def delete_customers(db: Session, customer_ids: List[int]) -> int:
    # Delete associated data first (manual cascade)
    db.query(models.CustomerData).filter(models.CustomerData.customer_id.in_(customer_ids)).delete(synchronize_session=False)
    # Delete customers
    result = db.query(models.Customer).filter(models.Customer.id.in_(customer_ids)).delete(synchronize_session=False)
    db.commit()
    return result

def delete_customer_data(db: Session, data_id: int):
    db_data = db.query(models.CustomerData).filter(models.CustomerData.id == data_id).first()
    if db_data:
        db.delete(db_data)
        db.commit()
    return db_data

# Customer Data CRUD
def create_customer_data(db: Session, data: schemas.CustomerDataCreate, customer_id: int):
    db_data = models.CustomerData(**data.model_dump(), customer_id=customer_id)
    db.add(db_data)
    db.commit()
    db.refresh(db_data)
    return db_data

def get_customer_context(db: Session, customer_id: int, limit: int = 20) -> str:
    customer = get_customer(db, customer_id)
    if not customer:
        return ""
    recent_entries = (
        db.query(models.CustomerData)
        .filter(models.CustomerData.customer_id == customer_id)
        .order_by(models.CustomerData.created_at.desc())
        .limit(limit)
        .all()
    )
    recent_entries.reverse()
    context = ""
    for entry in recent_entries:
        role = "Human" if "user" in entry.source_type else "AI"
        # Optional: Add skill info if present in source_type
        if "skill" in entry.source_type:
            role = "AI (Skill)"
            
        context += f"{role}: {entry.content}\n"
        
    return context

# LLM Config CRUD
def get_llm_configs(db: Session):
    return db.query(models.LLMConfig).filter(models.LLMConfig.is_active == True).all()

def create_llm_config(db: Session, config: schemas.LLMConfigCreate):
    db_config = models.LLMConfig(**config.model_dump())
    db.add(db_config)
    db.commit()
    db.refresh(db_config)
    return db_config
 
def update_llm_config(db: Session, config_id: int, update: schemas.LLMConfigUpdate):
    db_config = db.query(models.LLMConfig).filter(models.LLMConfig.id == config_id).first()
    if not db_config:
        return None
    data = update.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(db_config, k, v)
    db.commit()
    db.refresh(db_config)
    return db_config
 
def delete_llm_config(db: Session, config_id: int):
    db_config = db.query(models.LLMConfig).filter(models.LLMConfig.id == config_id).first()
    if db_config:
        db.delete(db_config)
        db.commit()
    return db_config

# Data Source Config CRUD
def get_data_source_configs(db: Session):
    return db.query(models.DataSourceConfig).filter(models.DataSourceConfig.is_active == True).all()

def create_data_source_config(db: Session, config: schemas.DataSourceConfigCreate):
    db_config = models.DataSourceConfig(**config.model_dump())
    db.add(db_config)
    db.commit()
    db.refresh(db_config)
    return db_config

def delete_data_source_config(db: Session, config_id: int):
    db_config = db.query(models.DataSourceConfig).filter(models.DataSourceConfig.id == config_id).first()
    if db_config:
        db.delete(db_config)
        db.commit()
    return db_config

def update_data_source_config(db: Session, config_id: int, update: schemas.DataSourceConfigUpdate):
    db_config = db.query(models.DataSourceConfig).filter(models.DataSourceConfig.id == config_id).first()
    if not db_config:
        return None
    update_data = update.model_dump(exclude_unset=True)
    if "config_json" in update_data:
        current_config = db_config.config_json or {}
        new_config = update_data["config_json"] or {}
        merged_config = {**current_config, **new_config}
        update_data["config_json"] = merged_config
    for key, value in update_data.items():
        setattr(db_config, key, value)
    db.commit()
    db.refresh(db_config)
    return db_config

# Routing Rule CRUD
def get_routing_rules(db: Session):
    return db.query(models.RoutingRule).filter(models.RoutingRule.is_active == True).all()

def create_routing_rule(db: Session, rule: schemas.RoutingRuleCreate):
    db_rule = models.RoutingRule(**rule.model_dump())
    db.add(db_rule)
    db.commit()
    db.refresh(db_rule)
    return db_rule

def delete_routing_rule(db: Session, rule_id: int):
    db_rule = db.query(models.RoutingRule).filter(models.RoutingRule.id == rule_id).first()
    if db_rule:
        db.delete(db_rule)
        db.commit()
    return db_rule

# Skill Route (Function -> LLM) CRUD
def get_skill_routes(db: Session):
    return db.query(models.SkillRoute).all()

def update_skill_route(db: Session, skill_name: str, llm_config_id: int):
    route = db.query(models.SkillRoute).filter(models.SkillRoute.skill_name == skill_name).first()
    if route:
        route.llm_config_id = llm_config_id
    else:
        route = models.SkillRoute(skill_name=skill_name, llm_config_id=llm_config_id)
        db.add(route)
    db.commit()
    db.refresh(route)
    return route

def create_sales_talk(db: Session, talk: schemas.SalesTalkCreate):
    db_talk = models.SalesTalk(**talk.model_dump())
    db.add(db_talk)
    db.commit()
    db.refresh(db_talk)
    return db_talk

def get_sales_talk(db: Session, talk_id: int):
    return db.query(models.SalesTalk).filter(models.SalesTalk.id == talk_id).first()

def get_sales_talks(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.SalesTalk).order_by(models.SalesTalk.updated_at.desc()).offset(skip).limit(limit).all()

def update_sales_talk(db: Session, talk_id: int, updates: dict):
    talk = get_sales_talk(db, talk_id)
    if not talk:
        return None
    for key, value in updates.items():
        setattr(talk, key, value)
    db.commit()
    db.refresh(talk)
    return talk

def delete_sales_talk(db: Session, talk_id: int):
    talk = get_sales_talk(db, talk_id)
    if talk:
        db.delete(talk)
        db.commit()
    return talk
