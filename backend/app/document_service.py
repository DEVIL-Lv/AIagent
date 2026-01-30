from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from . import models, schemas, database, crud
import shutil
import os
import pandas as pd
from pypdf import PdfReader
from docx import Document
from .llm_service import LLMService

UPLOAD_DIR = "uploads/documents"
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
                
        elif ext == 'txt':
            # Debug: Check file size
            try:
                size = os.path.getsize(file_path)
                print(f"Parsing TXT file: {file_path}, Size: {size} bytes")
            except Exception as e:
                print(f"Error checking file size: {e}")

            # Try multiple encodings
            encodings = ['utf-8-sig', 'utf-8', 'gb18030', 'gbk', 'latin-1']
            for enc in encodings:
                try:
                    print(f"Attempting decoding with {enc}...")
                    with open(file_path, 'r', encoding=enc) as f:
                        content = f.read()
                    print(f"Success with {enc}. Content length: {len(content)}")
                    break # Success
                except UnicodeDecodeError:
                    print(f"Failed with {enc}")
                    continue
            else:
                return f"Error parsing file: Could not decode text file with supported encodings ({', '.join(encodings)})"
        
        else:
            return f"Unsupported file format: {ext}"
            
    except Exception as e:
        return f"Error parsing file: {str(e)}"
        
    return content

router = APIRouter()

@router.post("/customers/{customer_id}/upload-document", response_model=schemas.CustomerData)
async def upload_document(customer_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    # 1. Save file
    await file.seek(0)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    
    file_path = os.path.join(UPLOAD_DIR, f"{customer_id}_{file.filename}")
    with open(file_path, "wb") as f:
        f.write(content)
        
    # 2. Parse content
    parsed_text = parse_file_content(file_path, file.filename)
    
    if not parsed_text.strip():
        parsed_text = "[File content is empty or unreadable]"

    # 3. Save to DB (including binary)
    data_entry = schemas.CustomerDataCreate(
        source_type=f"document_{file.filename.split('.')[-1]}",
        content=f"【文件内容: {file.filename}】\n{parsed_text[:5000]}", # Limit length for now
        meta_info={"filename": file.filename, "file_path": file_path},
        file_binary=content # Store binary content
    )
    return crud.create_customer_data(db=db, data=data_entry, customer_id=customer_id)

@router.post("/chat/global/upload-document", response_model=dict)
async def chat_global_upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    # 1. Save file temporarily
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    file_path = os.path.join(UPLOAD_DIR, f"global_{file.filename}")
    with open(file_path, "wb") as f:
        f.write(content)
    
    # 2. Parse content
    parsed_text = parse_file_content(file_path, file.filename)
    if not parsed_text.strip():
        parsed_text = "[File content is empty or unreadable]"
    
    # 3. Ask LLM to analyze without persisting
    llm_service = LLMService(db)
    llm = llm_service.get_llm(skill_name="chat")
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是一个专业的财富管理系统全局助手。你将根据用户上传的文档内容进行解读与分析，给出清晰、结构化的回答。"),
        ("human", "以下是文件内容，请分析要点并回答问题（如果有）：\n{content}")
    ])
    chain = prompt | llm | StrOutputParser()
    try:
        response = chain.invoke({"content": parsed_text[:8000]})
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
