from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from . import database, schemas, crud
from .skill_service import SkillService
import re

router = APIRouter()

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/customers/{customer_id}/run-skill", response_model=dict)
def run_skill(customer_id: int, request: schemas.RunSkillRequest, db: Session = Depends(get_db)):
    customer = crud.get_customer(db, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    context = crud.get_customer_context(db, customer_id)
    service = SkillService(db, config_name=request.model)
    
    try:
        requested_skill = (request.skill_name or "").strip()
        if not requested_skill:
            raise HTTPException(status_code=400, detail="skill_name is required")

        core_aliases = {"core", "agent_chat", "customer_summary", "summary", "risk_analysis", "deal_evaluation", "reply_suggestion"}
        content_aliases = {"content_analysis", "call_analysis", "file_analysis"}

        if requested_skill in core_aliases:
            resolved_skill = "core"
            query = request.question or ""
            content = service.core_assistant(context, query)
        elif requested_skill in content_aliases:
            resolved_skill = "content_analysis"
            target_content = request.question or context
            content = service.analyze_content(target_content)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown skill: {requested_skill}")
    except HTTPException:
        raise
    except Exception as e:
        print(f"ERROR in run_skill: {e}")
        content = f"Skill execution failed: {str(e)}"
        crud.create_customer_data(db, schemas.CustomerDataCreate(
            source_type=f"ai_skill_{requested_skill}_error",
            content=content,
            meta_info={"error": str(e)}
        ), customer_id)
        msg = str(e)
        match = re.search(r"Error code:\s*(\d{3})", msg)
        upstream_code = int(match.group(1)) if match else None
        status_code = 500
        if upstream_code == 429:
            status_code = 503
        elif upstream_code in (401, 403):
            status_code = 502
        elif upstream_code and 400 <= upstream_code < 600:
            status_code = 502
        detail = f"LLM request failed{f' (upstream {upstream_code})' if upstream_code else ''}: {msg}"
        raise HTTPException(status_code=status_code, detail=detail)

    crud.create_customer_data(db, schemas.CustomerDataCreate(
        source_type=f"ai_skill_{resolved_skill}",
        content=content,
        meta_info={"triggered_by": "manual_skill_button", "requested_skill": requested_skill, "skill": resolved_skill}
    ), customer_id)
    return {"result": content}

