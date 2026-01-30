from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form
from sqlalchemy.orm import Session
from . import database, models
import os
import shutil
from datetime import datetime

router = APIRouter()

UPLOAD_DIR = "knowledge_base"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/scripts/upload")
async def upload_script(
    file: UploadFile = File(...), 
    title: str = Form(...),
    category: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    Upload a script document (PDF/TXT/MD) to the knowledge base
    """
    file_path = os.path.join(UPLOAD_DIR, f"{datetime.now().timestamp()}_{file.filename}")
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # In a real app, we would also trigger RAG embedding here
        # For now, just save the metadata
        
        # We'll use a simple dictionary return since we don't have a dedicated Scripts table yet
        # Or we can reuse CustomerData with a special customer_id=0 for "Global Knowledge"
        
        return {
            "filename": file.filename,
            "title": title,
            "category": category,
            "path": file_path,
            "status": "uploaded",
            "rag_status": "pending_embedding"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

@router.get("/scripts/")
def get_scripts():
    # Mock data for now, in real app query DB
    return [
        {"id": 1, "title": "高净值客户破冰话术", "category": "开场白", "filename": "ice_breaking.pdf", "updated_at": "2024-03-20"},
        {"id": 2, "title": "异议处理：价格太贵", "category": "异议处理", "filename": "price_objection.docx", "updated_at": "2024-03-18"},
        {"id": 3, "title": "产品价值塑造-尊享版", "category": "产品介绍", "filename": "value_prop.txt", "updated_at": "2024-03-15"},
    ]

@router.post("/scripts/simulate")
def simulate_script(query: str = Form(...), script_id: int = Form(...)):
    """
    Simulate AI response based on a specific script
    """
    # Mock LLM response based on script context
    return {
        "response": f"（基于话术库 #{script_id} 的模拟回答）\n针对您提出的 '{query}'，建议采用“价值锚定法”。您可以这样说：\n“王总，我完全理解您对价格的顾虑。不过与其看单价，不如看这款产品为您带来的长期溢价...”"
    }
