from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from . import database, models, schemas

router = APIRouter()

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/analysis/stats")
def get_analysis_stats(db: Session = Depends(get_db)):
    """
    Get aggregated statistics for dashboard
    """
    # 1. Stage Distribution (Funnel)
    stage_counts = db.query(
        models.Customer.stage, 
        func.count(models.Customer.id)
    ).group_by(models.Customer.stage).all()
    
    stage_map = {
        'contact_before': '待开发',
        'trust_building': '建立信任',
        'product_matching': '需求分析',
        'closing': '商务谈判'
    }
    
    # Ensure all stages are present even if count is 0
    funnel_data = []
    current_counts = {s: 0 for s in stage_map.keys()}
    for stage, count in stage_counts:
        if stage in current_counts:
            current_counts[stage] = count
            
    for stage_key, label in stage_map.items():
        funnel_data.append({
            "stage": label,
            "count": current_counts[stage_key],
            "fill": "#8884d8" # Placeholder color
        })

    # 2. Risk Distribution (Pie)
    risk_counts = db.query(
        models.Customer.risk_profile, 
        func.count(models.Customer.id)
    ).group_by(models.Customer.risk_profile).all()
    
    risk_data = []
    for risk, count in risk_counts:
        if not risk: risk = "未评估"
        risk_data.append({"name": risk, "value": count})

    # 3. Key Metrics
    total_customers = db.query(func.count(models.Customer.id)).scalar()
    high_intent = db.query(func.count(models.Customer.id)).filter(models.Customer.stage == 'product_matching').scalar()
    closed_deals = db.query(func.count(models.Customer.id)).filter(models.Customer.stage == 'closing').scalar()

    cutoff = datetime.utcnow() - timedelta(days=7)
    active_weekly = db.query(func.count(func.distinct(models.CustomerData.customer_id))).filter(
        models.CustomerData.created_at >= cutoff
    ).scalar()

    return {
        "funnel": funnel_data,
        "risk": risk_data,
        "metrics": {
            "total": total_customers,
            "high_intent": high_intent,
            "closed": closed_deals,
            "active_weekly": active_weekly or 0
        }
    }

@router.post("/analysis/suggest-reply", response_model=schemas.ReplySuggestionResponse)
def suggest_reply(request: schemas.ReplySuggestionRequest, db: Session = Depends(get_db)):
    """
    话术辅助：给我一个金牌回答
    """
    from .llm_service import LLMService
    llm_service = LLMService(db)
    
    try:
        result = llm_service.generate_reply_suggestion(
            customer_id=request.customer_id,
            intent=request.intent,
            chat_context=request.chat_context
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/analysis/evaluate-progression", response_model=schemas.ProgressionAnalysisResponse)
def evaluate_progression(request: schemas.ProgressionAnalysisRequest, db: Session = Depends(get_db)):
    """
    推进建议：现在该不该推？
    """
    from .llm_service import LLMService
    llm_service = LLMService(db)
    
    try:
        result = llm_service.evaluate_sales_progression(customer_id=request.customer_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
