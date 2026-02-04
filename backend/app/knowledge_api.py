from fastapi import APIRouter, Depends, HTTPException, Form, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Optional
from . import database, models, schemas
from .knowledge_service import KnowledgeService
from .document_service import parse_file_content, UPLOAD_DIR as DOCUMENT_UPLOAD_DIR
import os
import re
import time
import shutil

router = APIRouter(prefix="/knowledge", tags=["Knowledge Base"])

def get_knowledge_service(db: Session = Depends(database.get_db)):
    return KnowledgeService(db)

def _safe_filename(name: str) -> str:
    base_name = os.path.basename(name or "")
    if not base_name:
        return "file"
    last_dot = base_name.rfind(".")
    base = base_name[:last_dot] if last_dot >= 0 else base_name
    ext = base_name[last_dot:] if last_dot >= 0 else ""
    safe_base = re.sub(r"[^\w.-]+", "_", base).strip("_") or "file"
    safe_ext = re.sub(r"[^\w.]+", "", ext)
    return f"{safe_base}{safe_ext}"

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
        safe_name = _safe_filename(file.filename)
        temp_path = os.path.join(DOCUMENT_UPLOAD_DIR, f"knowledge_{int(time.time() * 1000)}_{safe_name}")
        try:
            max_mb = int(os.getenv("MAX_UPLOAD_MB", "500"))
            max_bytes = max_mb * 1024 * 1024
            size = None
            try:
                file.file.seek(0, os.SEEK_END)
                size = file.file.tell()
                file.file.seek(0)
            except Exception:
                size = None
            if size is not None:
                if size == 0:
                    raise HTTPException(status_code=400, detail="Uploaded file is empty")
                if size > max_bytes:
                    raise HTTPException(status_code=413, detail=f"Uploaded file is too large (>{max_mb}MB)")
            with open(temp_path, "wb") as f:
                shutil.copyfileobj(file.file, f)
            if size is None:
                try:
                    size = os.path.getsize(temp_path)
                except Exception:
                    size = None
            if size is not None:
                if size == 0:
                    raise HTTPException(status_code=400, detail="Uploaded file is empty")
                if size > max_bytes:
                    raise HTTPException(status_code=413, detail=f"Uploaded file is too large (>{max_mb}MB)")
            final_content = parse_file_content(temp_path, safe_name)
            source = safe_name
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
    
    if not final_content or str(final_content).strip() == "":
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
