from fastapi import APIRouter, Depends, HTTPException, Body
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
    print(f"DEBUG: run_skill called for customer {customer_id} with skill {request.skill_name}")
    customer = crud.get_customer(db, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    context = crud.get_customer_context(db, customer_id)
    service = SkillService(db, config_name=request.model)
    
    try:
        if request.skill_name == "risk_analysis":
            content = service.analyze_risk(context)
        elif request.skill_name == "deal_evaluation":
            content = service.evaluate_deal(context)
        elif request.skill_name == "reply_suggestion":
            query = request.question or "请根据上下文生成合适的回复"
            content = service.generate_reply(context, query)
        elif request.skill_name == "call_analysis":
            # Use specific question/content if provided (from the button click on the file)
            # otherwise fall back to context (though this skill is best used with specific content)
            target_content = request.question or context
            content = service.analyze_call(target_content)
        elif request.skill_name == "file_analysis":
            target_content = request.question or context
            content = service.analyze_file(target_content)
        elif request.skill_name == "summary":
            # Map 'summary' skill to generate_customer_summary logic
            # Since generate_customer_summary is in LLMService and takes customer_id,
            # we can invoke it here. Note: This updates the customer summary field too.
            service.llm_service.generate_customer_summary(customer_id)
            # Fetch the updated summary
            updated_customer = crud.get_customer(db, customer_id)
            content = updated_customer.summary or "摘要生成完成"
        else:
            raise HTTPException(status_code=400, detail=f"Unknown skill: {request.skill_name}")
    except HTTPException:
        raise
    except Exception as e:
        print(f"ERROR in run_skill: {e}")
        content = f"Skill execution failed: {str(e)}"
        crud.create_customer_data(db, schemas.CustomerDataCreate(
            source_type=f"ai_skill_{request.skill_name}_error",
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
        source_type=f"ai_skill_{request.skill_name}",
        content=content,
        meta_info={"triggered_by": "manual_skill_button", "skill": request.skill_name}
    ), customer_id)
    return {"result": content}

