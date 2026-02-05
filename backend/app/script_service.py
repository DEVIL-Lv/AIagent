from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form
from sqlalchemy.orm import Session
from . import database, models, crud, schemas
from .document_service import parse_file_content, _safe_filename
from .llm_service import LLMService
from .feishu_service import FeishuService
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import os
import shutil
import threading
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
import re
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

UPLOAD_DIR = os.path.join("uploads", "sales_talks")
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

_TALK_VECTOR_STORE: FAISS | None = None
_TALK_VECTOR_SIGNATURE: tuple[int, int, str] | None = None
_TALK_VECTOR_LOCK = threading.Lock()

class SalesTalkFeishuImportRequest(BaseModel):
    spreadsheet_token: str
    range_name: str = ""
    import_type: str = "sheet"
    table_id: str = ""
    view_id: str | None = None
    data_source_id: int | None = None
    category: str = "sales_script"
    title_field: str | None = None
    content_fields: list[str] | None = None

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _signature_from_talks(talks: list[models.SalesTalk]) -> tuple[int, int, str]:
    max_id = 0
    max_updated = ""
    for s in talks:
        if s.id and s.id > max_id:
            max_id = s.id
        if s.updated_at:
            ts = s.updated_at.isoformat()
            if ts > max_updated:
                max_updated = ts
    return (len(talks), max_id, max_updated)

def _get_embedding_config(db: Session):
    config = db.query(models.LLMConfig).filter(
        models.LLMConfig.is_active == True,
        models.LLMConfig.provider == 'openai'
    ).first()

    if not config:
        config = db.query(models.LLMConfig).filter(models.LLMConfig.is_active == True).first()

    if config:
        api_key = config.api_key
        if api_key:
            api_key = api_key.strip()
            if api_key.startswith("Bearer "):
                api_key = api_key[7:]
        return api_key, config.api_base

    return os.getenv("OPENAI_API_KEY"), os.getenv("OPENAI_API_BASE")

def _chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    chunks = []
    start = 0
    length = len(cleaned)
    while start < length:
        end = min(length, start + chunk_size)
        chunks.append(cleaned[start:end])
        if end >= length:
            break
        start = max(0, end - overlap)
    return chunks

def _normalize_header(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()

def _pick_header(headers: list[str], candidates: list[str]) -> str | None:
    normalized = {_normalize_header(h): h for h in headers}
    for cand in candidates:
        hit = normalized.get(_normalize_header(cand))
        if hit:
            return hit
    return None

def _invalidate_vector_store():
    global _TALK_VECTOR_STORE, _TALK_VECTOR_SIGNATURE
    with _TALK_VECTOR_LOCK:
        _TALK_VECTOR_STORE = None
        _TALK_VECTOR_SIGNATURE = None

def _get_or_build_vector_store(db: Session) -> FAISS | None:
    global _TALK_VECTOR_STORE, _TALK_VECTOR_SIGNATURE

    talks = db.query(models.SalesTalk).all()
    if not talks:
        return None

    sig = _signature_from_talks(talks)

    with _TALK_VECTOR_LOCK:
        if _TALK_VECTOR_STORE is not None and _TALK_VECTOR_SIGNATURE == sig:
            return _TALK_VECTOR_STORE

        api_key, api_base = _get_embedding_config(db)
        if not api_key:
            return None

        documents: list[Document] = []
        for talk in talks:
            content = talk.content or ""
            if not content.strip():
                continue
            for chunk in _chunk_text(content):
                documents.append(Document(page_content=chunk, metadata={"talk_id": talk.id, "title": talk.title}))

        if not documents:
            return None

        kwargs = {"api_key": api_key}
        if api_base:
            kwargs["base_url"] = api_base

        embeddings = OpenAIEmbeddings(**kwargs)
        _TALK_VECTOR_STORE = FAISS.from_documents(documents, embeddings)
        _TALK_VECTOR_SIGNATURE = sig
        return _TALK_VECTOR_STORE

@router.post("/scripts/upload", response_model=schemas.SalesTalk)
async def upload_talk(
    file: UploadFile = File(...), 
    title: str = Form(...),
    category: str = Form(...),
    use_ai_processing: bool = Form(True),
    db: Session = Depends(get_db)
):
    max_mb = int(os.getenv("MAX_UPLOAD_MB", "500"))
    max_bytes = max_mb * 1024 * 1024
    size = None
    try:
        file.file.seek(0, os.SEEK_END)
        size = file.file.tell()
        file.file.seek(0)
    except Exception:
        pass
    if size is not None:
        if size == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        if size > max_bytes:
            raise HTTPException(status_code=413, detail=f"Uploaded file is too large (>{max_mb}MB)")
    safe_name = _safe_filename(file.filename)
    file_path = os.path.join(UPLOAD_DIR, f"{datetime.now().timestamp()}_{safe_name}")
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        if size is None:
            try:
                size = os.path.getsize(file_path)
            except Exception:
                size = None
        if size is not None:
            if size == 0:
                raise HTTPException(status_code=400, detail="Uploaded file is empty")
            if size > max_bytes:
                raise HTTPException(status_code=413, detail=f"Uploaded file is too large (>{max_mb}MB)")

        content = parse_file_content(file_path, safe_name)
        if content.startswith("Error parsing file:") or content.startswith("Unsupported file format:"):
            raise HTTPException(status_code=400, detail=content)
        if not content.strip():
            raise HTTPException(status_code=400, detail="话术内容为空")

        raw_content = content

        if use_ai_processing:
            llm_service = LLMService(db)
            content = llm_service.process_sales_script(raw_content)

        talk_data = schemas.SalesTalkCreate(
            title=title,
            category=category,
            filename=safe_name,
            file_path=file_path,
            content=content,
            raw_content=raw_content
        )
        talk = crud.create_sales_talk(db, talk_data)
        _invalidate_vector_store()
        return talk
    except HTTPException:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        raise
    except Exception as e:
        logger.exception("Script upload failed")
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

@router.get("/scripts/", response_model=list[schemas.SalesTalk])
def get_talks(db: Session = Depends(get_db)):
    return crud.get_sales_talks(db)

@router.get("/scripts/{script_id}", response_model=schemas.SalesTalk)
def get_talk(script_id: int, db: Session = Depends(get_db)):
    talk = crud.get_sales_talk(db, script_id)
    if not talk:
        raise HTTPException(status_code=404, detail="话术不存在")
    return talk

@router.post("/scripts/import-feishu")
def import_scripts_from_feishu(
    request: SalesTalkFeishuImportRequest,
    db: Session = Depends(get_db)
):
    if not request.spreadsheet_token:
        raise HTTPException(status_code=400, detail="spreadsheet_token is required")
    feishu = FeishuService(db, request.data_source_id)

    # Handle Docx Import
    if request.import_type == "docx":
        content = feishu.read_docx(request.spreadsheet_token)
        if not content:
            raise HTTPException(status_code=400, detail="Document content is empty")
        
        # Create a single SalesTalk from the document
        # We use a default title if not provided, or maybe we can try to extract it from content?
        # For now, use a generic title + token suffix
        title = f"Feishu Doc {request.spreadsheet_token[-6:]}"
        
        talk_data = schemas.SalesTalkCreate(
            title=title,
            category=request.category or "sales_script",
            filename=f"feishu_docx_{request.spreadsheet_token}",
            file_path="",
            content=content,
            raw_content=content
        )
        crud.create_sales_talk(db, talk_data)
        _invalidate_vector_store()
        return {"imported": 1, "skipped": 0}

    if request.import_type == "bitable":
        if not request.table_id:
            raise HTTPException(status_code=400, detail="table_id is required for bitable import")
        rows = feishu.read_bitable(request.spreadsheet_token, request.table_id, request.view_id)
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
    for idx, row in enumerate(rows[1:], start=1):
        row_map = {headers[i]: (row[i] if i < len(row) else "") for i in range(len(headers))}
        title_val = str(row_map.get(title_field, "")).strip()
        content_parts = []
        for field in content_fields:
            value = row_map.get(field, "")
            if value is None:
                continue
            text = str(value).strip()
            if text:
                content_parts.append(f"{field}: {text}")
        content = "\n".join(content_parts).strip()
        if not content:
            skipped += 1
            continue
        title = title_val or f"Feishu 话术 {idx}"
        talk_data = schemas.SalesTalkCreate(
            title=title,
            category=request.category or "sales_script",
            filename=f"feishu_{request.import_type}",
            file_path="",
            content=content,
            raw_content=content
        )
        crud.create_sales_talk(db, talk_data)
        imported += 1

    if imported:
        _invalidate_vector_store()

    return {"imported": imported, "skipped": skipped}

@router.put("/scripts/{script_id}", response_model=schemas.SalesTalk)
async def update_talk(
    script_id: int,
    title: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    content: Optional[str] = Form(None),
    file: UploadFile | None = File(None),
    use_ai_processing: bool = Form(True),
    db: Session = Depends(get_db)
):
    talk = crud.get_sales_talk(db, script_id)
    if not talk:
        raise HTTPException(status_code=404, detail="话术不存在")

    updates: dict = {}
    if title is not None and title.strip():
        updates["title"] = title.strip()
    if category is not None and category.strip():
        updates["category"] = category.strip()

    new_file_path = None
    old_file_path = talk.file_path

    if file is not None:
        max_mb = int(os.getenv("MAX_UPLOAD_MB", "500"))
        max_bytes = max_mb * 1024 * 1024
        size = None
        try:
            file.file.seek(0, os.SEEK_END)
            size = file.file.tell()
            file.file.seek(0)
        except Exception:
            pass
        if size is not None:
            if size == 0:
                raise HTTPException(status_code=400, detail="Uploaded file is empty")
            if size > max_bytes:
                raise HTTPException(status_code=413, detail=f"Uploaded file is too large (>{max_mb}MB)")

        safe_name = _safe_filename(file.filename)
        new_file_path = os.path.join(UPLOAD_DIR, f"{datetime.now().timestamp()}_{safe_name}")

        try:
            with open(new_file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

            if size is None:
                try:
                    size = os.path.getsize(new_file_path)
                except Exception:
                    size = None
            if size is not None:
                if size == 0:
                    raise HTTPException(status_code=400, detail="Uploaded file is empty")
                if size > max_bytes:
                    raise HTTPException(status_code=413, detail=f"Uploaded file is too large (>{max_mb}MB)")

            parsed = parse_file_content(new_file_path, safe_name)
            if parsed.startswith("Error parsing file:") or parsed.startswith("Unsupported file format:"):
                raise HTTPException(status_code=400, detail=parsed)
            if not parsed.strip():
                raise HTTPException(status_code=400, detail="话术内容为空")

            raw_content = parsed
            final_content = raw_content
            if use_ai_processing:
                llm_service = LLMService(db)
                final_content = llm_service.process_sales_script(raw_content)

            updates["filename"] = safe_name
            updates["file_path"] = new_file_path
            updates["content"] = final_content
            updates["raw_content"] = raw_content
        except HTTPException:
            if new_file_path and os.path.exists(new_file_path):
                try:
                    os.remove(new_file_path)
                except Exception:
                    pass
            raise
        except Exception as e:
            logger.exception("Script update failed")
            if new_file_path and os.path.exists(new_file_path):
                try:
                    os.remove(new_file_path)
                except Exception:
                    pass
            raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")
    elif content is not None:
        if not content.strip():
            raise HTTPException(status_code=400, detail="话术内容为空")
        raw_content = content
        final_content = raw_content
        if use_ai_processing:
            llm_service = LLMService(db)
            final_content = llm_service.process_sales_script(raw_content)
        updates["content"] = final_content
        updates["raw_content"] = raw_content

    if not updates:
        raise HTTPException(status_code=400, detail="无可更新内容")

    updated = crud.update_sales_talk(db, script_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="话术不存在")

    if new_file_path and old_file_path and os.path.exists(old_file_path):
        try:
            os.remove(old_file_path)
        except Exception:
            pass

    _invalidate_vector_store()
    return updated

@router.delete("/scripts/{script_id}", response_model=schemas.SalesTalk)
def delete_talk(script_id: int, db: Session = Depends(get_db)):
    talk = crud.get_sales_talk(db, script_id)
    if not talk:
        raise HTTPException(status_code=404, detail="话术不存在")
    file_path = talk.file_path
    deleted = crud.delete_sales_talk(db, script_id)
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception:
            pass
    _invalidate_vector_store()
    return deleted

@router.post("/scripts/simulate")
def simulate_talk(query: str = Form(...), script_id: int = Form(...), db: Session = Depends(get_db)):
    talk = crud.get_sales_talk(db, script_id)
    if not talk:
        raise HTTPException(status_code=404, detail="话术不存在")

    rag_context = ""
    vector_store = _get_or_build_vector_store(db)
    if vector_store:
        try:
            candidates = vector_store.similarity_search(query, k=6)
            matched = [d.page_content for d in candidates if d.metadata.get("talk_id") == talk.id]
            if matched:
                rag_context = "\n".join(matched[:3])
        except Exception:
            rag_context = ""

    system_prompt = f"""你是资深销售顾问。请基于以下话术库内容，为用户问题生成可直接发送的专业回复。

话术库内容：
{talk.content or ""}

相关片段：
{rag_context}

要求：
1. 回复简洁、有策略、贴近客户语境
2. 语气专业且亲切，可加入一个确认式问题推动对话
3. 不承诺收益、不保证结果、不夸大或虚构
4. 输出尽量使用中文，避免无必要英文
"""
    llm_service = LLMService(db)
    llm = llm_service.get_llm(skill_name="reply_suggestion")
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{question}")
    ])
    chain = prompt | llm | StrOutputParser()
    response = chain.invoke({"question": query})
    return {"response": response}
