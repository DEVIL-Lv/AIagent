from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from . import models, schemas, database, crud
import shutil
import os
import pandas as pd
from pypdf import PdfReader
from docx import Document
from .llm_service import LLMService
import logging
import re

UPLOAD_DIR = "uploads/documents"
logger = logging.getLogger(__name__)
os.makedirs(UPLOAD_DIR, exist_ok=True)

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

def parse_file_content(file_path: str, filename: str) -> str:
    ext = filename.split('.')[-1].lower()
    content = ""
    
    try:
        if ext == 'pdf':
            reader = PdfReader(file_path)
            for page in reader.pages:
                content += page.extract_text() + "\n"
                
        elif ext in ['xlsx', 'xls', 'csv']:
            if ext == 'csv':
                df = pd.read_csv(file_path)
            else:
                df = pd.read_excel(file_path)
            # Convert dataframe to string representation
            content = df.to_string()
            
        elif ext in ['docx', 'doc']:
            doc = Document(file_path)
            for para in doc.paragraphs:
                content += para.text + "\n"
                
        elif ext in ['txt', 'md']:
            encodings = ['utf-8-sig', 'utf-8', 'gb18030', 'gbk', 'latin-1']
            for enc in encodings:
                try:
                    with open(file_path, 'r', encoding=enc) as f:
                        content = f.read()
                    break # Success
                except UnicodeDecodeError:
                    continue
            else:
                return f"Error parsing file: Could not decode text file with supported encodings ({', '.join(encodings)})"
        
        else:
            return f"Unsupported file format: {ext}"
            
    except Exception as e:
        logger.exception("File parse error", extra={"ext": ext})
        return f"Error parsing file: {str(e)}"
        
    return content

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

router = APIRouter()

@router.post("/customers/{customer_id}/upload-document", response_model=schemas.CustomerData)
async def upload_document(customer_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
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
    
    safe_name = _safe_filename(file.filename)
    file_path = os.path.join(UPLOAD_DIR, f"{customer_id}_{safe_name}")
    try:
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
    if size is None:
        try:
            size = os.path.getsize(file_path)
        except Exception:
            size = None
    if size is not None:
        if size == 0:
            try:
                os.remove(file_path)
            except Exception:
                pass
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        if size > max_bytes:
            try:
                os.remove(file_path)
            except Exception:
                pass
            raise HTTPException(status_code=413, detail=f"Uploaded file is too large (>{max_mb}MB)")
        
    # 2. Parse content
    parsed_text = parse_file_content(file_path, safe_name)
    
    if not parsed_text.strip():
        parsed_text = "[File content is empty or unreadable]"

    # 3. Save to DB (including binary)
    store_upload_binary = os.getenv("STORE_UPLOAD_BINARY") == "1"
    content = None
    if store_upload_binary:
        with open(file_path, "rb") as f:
            content = f.read()
        if size is None:
            if not content:
                raise HTTPException(status_code=400, detail="Uploaded file is empty")
            if len(content) > max_bytes:
                raise HTTPException(status_code=413, detail=f"Uploaded file is too large (>{max_mb}MB)")
    ext = safe_name.split(".")[-1] if "." in safe_name else "file"
    data_entry = schemas.CustomerDataCreate(
        source_type=f"document_{ext}",
        content=f"【文件内容: {safe_name}】\n{parsed_text[:5000]}",
        meta_info={"filename": safe_name, "original_filename": file.filename, "file_path": file_path},
        file_binary=content if store_upload_binary else None
    )
    return crud.create_customer_data(db=db, data=data_entry, customer_id=customer_id)

@router.post("/chat/global/upload-document", response_model=dict)
async def chat_global_upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
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

    safe_name = _safe_filename(file.filename)
    file_path = os.path.join(UPLOAD_DIR, f"global_{safe_name}")
    try:
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
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
        
        parsed_text = parse_file_content(file_path, safe_name)
        if parsed_text.startswith("Error parsing file:") or parsed_text.startswith("Unsupported file format:"):
            raise HTTPException(status_code=400, detail=parsed_text)
        if not parsed_text.strip():
            parsed_text = "[File content is empty or unreadable]"
        
        llm_service = LLMService(db)
        llm = llm_service.get_llm(skill_name="chat")
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import StrOutputParser
        prompt = ChatPromptTemplate.from_messages([
            ("system", "你是专业的财富管理系统全局助手。请基于用户上传的文档内容进行解读与分析，给出清晰、结构化的回答。输出尽量使用中文，避免无必要英文。"),
            ("human", "以下是文件内容，请提炼要点并给出结论/建议（如有问题请回答）：\n{content}")
        ])
        chain = prompt | llm | StrOutputParser()
        response = chain.invoke({"content": parsed_text[:8000]})
        return {"response": response}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
