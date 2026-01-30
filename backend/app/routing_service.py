from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from . import models, schemas, crud, database

router = APIRouter()

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/admin/routing-rules/", response_model=schemas.RoutingRule)
def create_rule(rule: schemas.RoutingRuleCreate, db: Session = Depends(get_db)):
    return crud.create_routing_rule(db=db, rule=rule)

@router.get("/admin/routing-rules/", response_model=List[schemas.RoutingRule])
def read_rules(db: Session = Depends(get_db)):
    return crud.get_routing_rules(db)

@router.delete("/admin/routing-rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    result = crud.delete_routing_rule(db, rule_id)
    if not result:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"message": "Deleted successfully"}

@router.get("/admin/skill-routes/", response_model=List[schemas.SkillRoute])
def get_skill_mappings(db: Session = Depends(get_db)):
    return crud.get_skill_routes(db)

@router.post("/admin/skill-routes/")
def update_skill_mapping(data: schemas.SkillRouteCreate, db: Session = Depends(get_db)):
    return crud.update_skill_route(db, data.skill_name, data.llm_config_id)
