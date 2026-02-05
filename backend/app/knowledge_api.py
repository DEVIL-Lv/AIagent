from fastapi import APIRouter, Depends, HTTPException, Form, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from . import database, models, schemas
from .knowledge_service import KnowledgeService
from .document_service import parse_file_content, UPLOAD_DIR as DOCUMENT_UPLOAD_DIR
from .feishu_service import FeishuService
from langchain_core.messages import SystemMessage, HumanMessage
import base64
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

def _is_image_file(filename: str, content_type: str | None) -> bool:
    if content_type and content_type.startswith("image/"):
        return True
    ext = filename.split(".")[-1].lower() if "." in filename else ""
    return ext in {"png", "jpg", "jpeg", "gif", "webp", "bmp", "tiff"}

class KnowledgeFeishuImportRequest(BaseModel):
    spreadsheet_token: str
    range_name: str = ""
    import_type: str = "sheet"
    table_id: str = ""
    data_source_id: int | None = None
    category: str = "general"
    title_field: str | None = None
    content_fields: list[str] | None = None
    use_ai_processing: bool = False

def _normalize_header(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()

def _pick_header(headers: list[str], candidates: list[str]) -> str | None:
    normalized = {_normalize_header(h): h for h in headers}
    for cand in candidates:
        hit = normalized.get(_normalize_header(cand))
        if hit:
            return hit
    return None

@router.get("/", response_model=List[schemas.KnowledgeDocument])
def list_documents(service: KnowledgeService = Depends(get_knowledge_service)):
    return service.list_documents()

@router.post("/", response_model=schemas.KnowledgeDocument)
async def add_document(
    title: str = Form(...),
    content: str = Form(None),
    file: UploadFile = File(None),
    category: str = Form("general"),
    use_ai_processing: bool = Form(True),
    service: KnowledgeService = Depends(get_knowledge_service),
    db: Session = Depends(database.get_db)
):
    final_content = content or ""
    source = "manual"
    raw_content = ""
    
    image_processed = False
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
            if _is_image_file(safe_name, file.content_type):
                try:
                    with open(temp_path, "rb") as f:
                        image_bytes = f.read()
                    if not image_bytes:
                        raise HTTPException(status_code=400, detail="Uploaded image file is empty")
                    b64 = base64.b64encode(image_bytes).decode("utf-8")
                    from .llm_service import LLMService
                    llm_service = LLMService(db)
                    llm = llm_service.get_llm(skill_name="chat")
                    system_prompt = """
你是专业的知识库整理助手。请基于图片内容生成结构化的 Markdown 记录，便于知识库检索。

要求：
1. 先给出【核心摘要】2-4 句
2. 提取图片中的关键事实、数据、术语和结论
3. 使用清晰的标题与列表
4. 输出为中文，不要输出推理过程
"""
                    resp = llm.invoke([
                        SystemMessage(content=system_prompt.strip()),
                        HumanMessage(content=[
                            {"type": "text", "text": "请解析这张图片并输出结构化 Markdown。"},
                            {"type": "image_url", "image_url": {"url": f"data:{file.content_type or 'image/png'};base64,{b64}"}}
                        ])
                    ])
                    final_content = getattr(resp, "content", "") or ""
                    if not final_content.strip():
                        raise HTTPException(status_code=400, detail="Image analysis returned empty content")
                    raw_content = final_content
                    if use_ai_processing:
                        final_content = llm_service.process_knowledge_content(raw_content)
                        image_processed = True
                except HTTPException:
                    raise
                except Exception:
                    raise HTTPException(status_code=400, detail="当前模型暂不支持图片内容分析，请在设置中选择支持多模态的模型")
            else:
                final_content = parse_file_content(temp_path, safe_name)
                raw_content = final_content
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
    else:
        raw_content = final_content
    
    if not final_content or str(final_content).strip() == "":
        raise HTTPException(status_code=400, detail="Content or File is required")

    # AI Processing
    if use_ai_processing and not image_processed:
        from .llm_service import LLMService
        llm_service = LLMService(db)
        final_content = llm_service.process_knowledge_content(raw_content)

    doc = service.add_document(title=title, content=final_content, source=source, category=category)
    
    if use_ai_processing:
        doc.raw_content = raw_content
        db.commit()

    return doc

@router.post("/import-feishu")
def import_from_feishu(
    request: KnowledgeFeishuImportRequest,
    db: Session = Depends(database.get_db),
    service: KnowledgeService = Depends(get_knowledge_service)
):
    if not request.spreadsheet_token:
        raise HTTPException(status_code=400, detail="spreadsheet_token is required")
    feishu = FeishuService(db, request.data_source_id)
    
    # Handle Docx Import
    if request.import_type == "docx":
        content = feishu.read_docx(request.spreadsheet_token)
        if not content:
            raise HTTPException(status_code=400, detail="Document content is empty")
        
        raw_content = content
        
        # AI Processing
        if request.use_ai_processing:
            from .llm_service import LLMService
            llm_service = LLMService(db)
            content = llm_service.process_knowledge_content(raw_content)
        
        title = "Feishu Doc"
        source = f"feishu:docx:{request.spreadsheet_token}"
        
        doc = service.add_document(title=title, content=content, source=source, category=request.category or "general")
        
        if request.use_ai_processing:
            doc.raw_content = raw_content
            db.commit()
            
        return {"imported": 1, "skipped": 0}

    if request.import_type == "bitable":
        if not request.table_id:
            raise HTTPException(status_code=400, detail="table_id is required for bitable import")
        rows = feishu.read_bitable(request.spreadsheet_token, request.table_id)
    else:
        rows = feishu.read_spreadsheet(request.spreadsheet_token, request.range_name)
    if not rows:
        return {"imported": 0, "skipped": 0}

    headers = [str(h).strip() for h in rows[0] if str(h).strip() != ""]
    if not headers:
        raise HTTPException(status_code=400, detail="No headers found in sheet")

    title_field = request.title_field
    if not title_field:
        title_field = _pick_header(headers, ["title", "标题", "name", "名称"]) or headers[0]

    content_fields = request.content_fields or []
    if not content_fields:
        content_fields = [h for h in headers if h != title_field]
    content_fields = [h for h in content_fields if h in headers]

    imported = 0
    skipped = 0
    
    from .llm_service import LLMService
    llm_service = LLMService(db) if request.use_ai_processing else None

    for idx, row in enumerate(rows[1:], start=1):
        row_map = {headers[i]: (row[i] if i < len(row) else "") for i in range(len(headers))}
        title_val = str(row_map.get(title_field, "")).strip()
        
        content_parts = []
        for field in content_fields:
            val = str(row_map.get(field, "")).strip()
            if val:
                content_parts.append(f"{field}: {val}")
        
        raw_content = "\n".join(content_parts).strip()
        if not raw_content:
            skipped += 1
            continue
            
        final_content = raw_content
        
        title = title_val or f"Feishu 文档 {idx}"
        source = f"feishu:{request.spreadsheet_token}"
        if request.import_type == "bitable" and request.table_id:
            source = f"{source}:{request.table_id}"
            
        doc = service.add_document(title=title, content=final_content, source=source, category=request.category or "general")
        imported += 1

    return {"imported": imported, "skipped": skipped}

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
