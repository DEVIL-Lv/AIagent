from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session
from typing import List
import asyncio
import time
import logging
from sqlalchemy import text
import json
import re
from . import models, schemas, crud, database
from .llm_service import LLMService
from . import audio_service
from . import document_service
from . import api_skills
from . import chat_service
from . import import_service
from . import analysis_service
from . import script_service
from . import datasource_service
from . import routing_service
from . import knowledge_api
from . import chat_session_service

logger = logging.getLogger(__name__)

async def _wait_for_database(max_wait_seconds: int = 90, interval_seconds: int = 2) -> None:
    deadline = time.monotonic() + max_wait_seconds
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with database.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as e:
            last_exc = e
            await asyncio.sleep(interval_seconds)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Database not ready")

app = FastAPI(title="Conversion Agent API")

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error(f"Validation error: {exc.errors()}")
    return JSONResponse(
        status_code=400,
        content={"detail": exc.errors()},
    )

@app.on_event("startup")
async def startup_event():
    logger.info("Starting up")
    await _wait_for_database()
    models.Base.metadata.create_all(bind=database.engine)
    database.ensure_schema()

# Register Routers
app.include_router(chat_service.router) 
app.include_router(audio_service.router)
app.include_router(document_service.router)
app.include_router(api_skills.router)
app.include_router(import_service.router) 
app.include_router(analysis_service.router) 
app.include_router(script_service.router) 
app.include_router(datasource_service.router)
app.include_router(routing_service.router)
app.include_router(knowledge_api.router)
app.include_router(chat_session_service.router, prefix="/chat", tags=["chat-sessions"])


def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _sse_message(data: dict, event: str | None = None) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    if event:
        return f"event: {event}\ndata: {payload}\n\n"
    return f"data: {payload}\n\n"

@app.get("/")
def read_root():
    return {"status": "System Operational", "message": "Welcome to AI Conversion Agent"}

@app.get("/health")
def health_check():
    return {"status": "ok"}

# --- Customer APIs ---
@app.post("/customers/", response_model=schemas.Customer)
def create_customer(
    name: str = Form(...),
    bio: str = Form(None),
    file: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    # 1. Create Customer
    # summary 字段暂时留给 AI，bio 存为第一条笔记
    customer_in = schemas.CustomerCreate(name=name)
    db_customer = crud.create_customer(db=db, customer=customer_in)
    
    # 2. Add Bio if exists
    if bio:
        crud.create_customer_data(db, schemas.CustomerDataCreate(
            source_type="manual_note",
            content=bio,
            meta_info={"type": "initial_bio"}
        ), db_customer.id)
        
    # 3. Handle File if exists (Simple Text Parsing for MVP)
    if file:
        try:
            content = file.file.read()
            # 尝试作为文本解码，如果是二进制文件(PDF/Word)暂时略过或需要引入 parser
            # 这里简单处理 txt/csv
            text_content = content.decode("utf-8")
            crud.create_customer_data(db, schemas.CustomerDataCreate(
                source_type="file_upload",
                content=text_content,
                meta_info={"filename": file.filename}
            ), db_customer.id)
        except Exception as e:
            # 如果解码失败，说明是二进制文件，暂时只记录文件名
            crud.create_customer_data(db, schemas.CustomerDataCreate(
                source_type="file_upload",
                content=f"[Binary File Uploaded: {file.filename}]",
                meta_info={"filename": file.filename, "error": str(e)}
            ), db_customer.id)
            
    return db_customer

@app.get("/customers/", response_model=List[schemas.Customer])
def read_customers(skip: int = 0, limit: int = 10000, db: Session = Depends(get_db)):
    try:
        return crud.get_customers(db, skip=skip, limit=limit)
    except Exception as e:
        logger.exception("Read customers failed")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/customers/{customer_id}", response_model=schemas.CustomerDetail)
def read_customer(customer_id: int, db: Session = Depends(get_db)):
    db_customer = crud.get_customer(db, customer_id=customer_id)
    if db_customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return db_customer

@app.put("/customers/{customer_id}", response_model=schemas.Customer)
def update_customer(customer_id: int, customer: schemas.CustomerUpdate, db: Session = Depends(get_db)):
    db_customer = crud.update_customer(db, customer_id=customer_id, customer_update=customer)
    if db_customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return db_customer

@app.delete("/customers/{customer_id}", response_model=schemas.Customer)
def delete_customer(customer_id: int, db: Session = Depends(get_db)):
    db_customer = crud.delete_customer(db, customer_id=customer_id)
    if db_customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return db_customer

@app.post("/customers/batch_delete")
def batch_delete_customers(request: schemas.BatchDeleteRequest, db: Session = Depends(get_db)):
    deleted_count = crud.delete_customers(db, request.customer_ids)
    return {"deleted_count": deleted_count}

@app.post("/customers/{customer_id}/data/", response_model=schemas.CustomerData)
def add_customer_data(customer_id: int, data: schemas.CustomerDataCreate, db: Session = Depends(get_db)):
    return crud.create_customer_data(db=db, data=data, customer_id=customer_id)

@app.delete("/customers/{customer_id}/data/{data_id}", response_model=dict)
def delete_customer_data(customer_id: int, data_id: int, db: Session = Depends(get_db)):
    """
    删除客户档案中的特定数据条目 (如上传的文件记录)
    """
    import os
    # 1. Verify customer exists
    customer = crud.get_customer(db, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    # 2. Find the data entry
    data_entry = db.query(models.CustomerData).filter(
        models.CustomerData.id == data_id,
        models.CustomerData.customer_id == customer_id
    ).first()

    if not data_entry:
        raise HTTPException(status_code=404, detail="Data entry not found")

    # 3. Optional: Delete file from disk if it exists
    # Check meta_info for file_path
    if data_entry.meta_info and "file_path" in data_entry.meta_info:
        file_path = data_entry.meta_info["file_path"]
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info("Deleted file", extra={"file_path": file_path})
            except Exception as e:
                logger.exception("Delete file failed", extra={"file_path": file_path})

    # 4. Delete record
    db.delete(data_entry)
    db.commit()
    
    return {"status": "success", "message": "Data entry deleted"}

from .knowledge_service import KnowledgeService

def _search_sales_talks(db: Session, query: str, k: int = 3) -> list[dict]:
    q = (query or "").strip()
    if not q:
        return []
    talks = db.query(models.SalesTalk).all()
    if not talks:
        return []
    ql = q.lower()
    tokens = [t for t in re.split(r"\s+", ql) if t]
    scored: list[tuple[float, models.SalesTalk]] = []
    for t in talks:
        title = (t.title or "").strip()
        base = (t.content or t.raw_content or "").strip()
        tl = title.lower()
        bl = base.lower()
        score = 0.0
        if ql in tl:
            score += 5.0
        if ql in bl:
            score += 2.5
        for tok in tokens:
            if tok in tl:
                score += 2.0
            if tok in bl:
                score += 1.0
        if tl == ql:
            score += 6.0
        if score > 0:
            scored.append((score, t))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [t for _, t in scored[:k]]
    results = []
    for t in top:
        base = t.content or t.raw_content or ""
        bl = base.lower()
        pos = bl.find(ql) if ql else -1
        if pos < 0 and tokens:
            for tok in tokens:
                if tok:
                    pos = bl.find(tok)
                    if pos >= 0:
                        break
        start = max(0, pos - 120) if pos >= 0 else 0
        end = min(len(base), start + 240)
        snippet = base[start:end]
        results.append({
            "content": f"Title: {t.title}\n\n{snippet}",
            "metadata": {"source": f"sales_talk:{t.category}", "id": t.id, "title": t.title}
        })
    return results

@app.post("/customers/{customer_id}/agent-chat", response_model=schemas.AgentChatResponse)
def chat_with_agent_endpoint(
    customer_id: int, 
    request: schemas.AgentChatRequest, 
    db: Session = Depends(get_db)
):
    llm_service = LLMService(db)
    knowledge_service = KnowledgeService(db)
    
    # 1. RAG Search
    rag_docs = []
    try:
        rag_docs = knowledge_service.search(request.query, k=3)
    except Exception as e:
        logger.exception("Agent chat RAG search failed")
        
    # Handle list of dicts returned by search
    rag_context = ""
    if rag_docs:
        rag_context = "\n\n".join([f"【相关文档: {doc.get('metadata', {}).get('title', 'Untitled')}】\n{doc.get('content', '')}" for doc in rag_docs])
    talk_docs = _search_sales_talks(db, request.query, k=3)
    if talk_docs:
        talk_context = "\n\n".join([f"【相关话术: {doc.get('metadata', {}).get('title', 'Untitled')}】\n{doc.get('content', '')}" for doc in talk_docs])
        rag_context = f"{rag_context}\n\n{talk_context}".strip()
    
    # 2. Chat
    try:
        response_text = llm_service.chat_with_agent(
            customer_id=customer_id,
            query=request.query,
            history=request.history,
            rag_context=rag_context,
            model=request.model
        )
        return schemas.AgentChatResponse(response=response_text)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Agent chat failed")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/customers/{customer_id}/agent-chat/stream")
async def chat_with_agent_stream_endpoint(
    customer_id: int,
    request: schemas.AgentChatRequest,
    db: Session = Depends(get_db)
):
    llm_service = LLMService(db)
    knowledge_service = KnowledgeService(db)

    rag_docs = []
    try:
        rag_docs = knowledge_service.search(request.query, k=3)
    except Exception:
        logger.exception("Agent chat RAG search failed")

    rag_context = ""
    if rag_docs:
        rag_context = "\n\n".join([f"【相关文档: {doc.get('metadata', {}).get('title', 'Untitled')}】\n{doc.get('content', '')}" for doc in rag_docs])
    talk_docs = _search_sales_talks(db, request.query, k=3)
    if talk_docs:
        talk_context = "\n\n".join([f"【相关话术: {doc.get('metadata', {}).get('title', 'Untitled')}】\n{doc.get('content', '')}" for doc in talk_docs])
        rag_context = f"{rag_context}\n\n{talk_context}".strip()

    async def event_generator():
        try:
            async for token in llm_service.chat_with_agent_stream(
                customer_id=customer_id,
                query=request.query,
                history=request.history,
                rag_context=rag_context,
                model=request.model
            ):
                yield _sse_message({"token": token})
        except Exception as e:
            yield _sse_message({"message": f"（系统错误）AI 响应失败: {str(e)}"}, event="error")
        yield "event: done\ndata: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/customers/{customer_id}/generate-summary", response_model=schemas.Customer)
def generate_customer_summary(customer_id: int, db: Session = Depends(get_db)):
    """
    触发 AI 分析，生成客户画像摘要。
    会读取该客户下所有的 data entries，调用 LLM 生成摘要，并更新到 Customer.summary 字段。
    """
    service = LLMService(db)
    try:
        service.generate_customer_summary(customer_id)
        # 重新获取最新的 customer 信息返回
        db_customer = crud.get_customer(db, customer_id=customer_id)
        return db_customer
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Generate summary failed")
        raise HTTPException(status_code=500, detail=f"AI 分析失败: {str(e)}")

# --- LLM Config APIs ---
@app.post("/admin/llm-configs/", response_model=schemas.LLMConfig)
def create_llm_config(config: schemas.LLMConfigCreate, db: Session = Depends(get_db)):
    return crud.create_llm_config(db=db, config=config)

@app.get("/admin/llm-configs/", response_model=List[schemas.LLMConfig])
def read_llm_configs(db: Session = Depends(get_db)):
    return crud.get_llm_configs(db)
 
@app.put("/admin/llm-configs/{config_id}", response_model=schemas.LLMConfig)
def update_llm_config(config_id: int, update: schemas.LLMConfigUpdate, db: Session = Depends(get_db)):
    cfg = crud.update_llm_config(db, config_id, update)
    if not cfg:
        raise HTTPException(status_code=404, detail="LLM Config not found")
    return cfg
 
@app.delete("/admin/llm-configs/{config_id}", response_model=schemas.LLMConfig)
def delete_llm_config(config_id: int, db: Session = Depends(get_db)):
    cfg = crud.delete_llm_config(db, config_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="LLM Config not found")
    return cfg
