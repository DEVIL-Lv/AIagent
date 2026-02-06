from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from . import database, models, schemas, crud

router = APIRouter()

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/sessions/", response_model=schemas.ChatSession)
def create_session(session: schemas.ChatSessionCreate, db: Session = Depends(get_db)):
    return crud.create_chat_session(db, session)

@router.get("/sessions/", response_model=List[schemas.ChatSession])
def get_sessions(customer_id: Optional[int] = None, db: Session = Depends(get_db)):
    return crud.get_chat_sessions(db, customer_id=customer_id)

@router.delete("/sessions/{session_id}")
def delete_session(session_id: int, db: Session = Depends(get_db)):
    session = crud.delete_chat_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "success"}

@router.get("/sessions/{session_id}/messages", response_model=List[schemas.ChatMessage])
def get_session_messages(session_id: int, db: Session = Depends(get_db)):
    return crud.get_chat_session_messages(db, session_id)
