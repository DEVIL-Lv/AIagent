from fastapi import APIRouter, Depends, HTTPException, Form, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Optional
from . import database, models, schemas
from .knowledge_service import KnowledgeService

router = APIRouter(prefix="/knowledge", tags=["Knowledge Base"])

def get_knowledge_service(db: Session = Depends(database.get_db)):
    return KnowledgeService(db)

@router.get("/", response_model=List[schemas.KnowledgeDocument])
def list_documents(service: KnowledgeService = Depends(get_knowledge_service)):
    return service.list_documents()

@router.post("/", response_model=schemas.KnowledgeDocument)
async def add_document(
    title: str = Form(...),
    content: str = Form(None),
    file: UploadFile = File(None),
    category: str = Form("general"),
    service: KnowledgeService = Depends(get_knowledge_service)
):
    final_content = content or ""
    source = "manual"
    
    if file:
        try:
            file_bytes = await file.read()
            # Simple text decoding for now
            text = file_bytes.decode("utf-8")
            final_content = text
            source = file.filename
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")
    
    if not final_content:
        raise HTTPException(status_code=400, detail="Content or File is required")

    return service.add_document(title=title, content=final_content, source=source, category=category)

@router.get("/{doc_id}", response_model=schemas.KnowledgeDocument)
def get_document(doc_id: int, service: KnowledgeService = Depends(get_knowledge_service)):
    doc = service.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc

@router.put("/{doc_id}", response_model=schemas.KnowledgeDocument)
def update_document(
    doc_id: int,
    title: str = Form(None),
    content: str = Form(None),
    category: str = Form(None),
    service: KnowledgeService = Depends(get_knowledge_service)
):
    doc = service.update_document(doc_id, title=title, content=content, category=category)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc

@router.delete("/{doc_id}")
def delete_document(doc_id: int, service: KnowledgeService = Depends(get_knowledge_service)):
    success = service.delete_document(doc_id)
    if not success:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"status": "success"}

@router.post("/search")
def search_knowledge(
    query: str = Form(...), 
    k: int = 3,
    service: KnowledgeService = Depends(get_knowledge_service)
):
    return service.search(query, k)
