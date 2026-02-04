from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form
from sqlalchemy.orm import Session
from . import database, models, crud, schemas
from .document_service import parse_file_content
from .llm_service import LLMService
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import os
import shutil
import threading
from datetime import datetime

router = APIRouter()

UPLOAD_DIR = os.path.join("uploads", "sales_talks")
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

_TALK_VECTOR_STORE: FAISS | None = None
_TALK_VECTOR_SIGNATURE: tuple[int, int, str] | None = None
_TALK_VECTOR_LOCK = threading.Lock()

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
    db: Session = Depends(get_db)
):
    file_path = os.path.join(UPLOAD_DIR, f"{datetime.now().timestamp()}_{file.filename}")
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        content = parse_file_content(file_path, file.filename)
        if content.startswith("Error parsing file:") or content.startswith("Unsupported file format:"):
            raise HTTPException(status_code=400, detail=content)
        if not content.strip():
            raise HTTPException(status_code=400, detail="话术内容为空")

        talk_data = schemas.SalesTalkCreate(
            title=title,
            category=category,
            filename=file.filename,
            file_path=file_path,
            content=content
        )
        talk = crud.create_sales_talk(db, talk_data)
        _invalidate_vector_store()
        return talk
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

@router.get("/scripts/", response_model=list[schemas.SalesTalk])
def get_talks(db: Session = Depends(get_db)):
    return crud.get_sales_talks(db)

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
