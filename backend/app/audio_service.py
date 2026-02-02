from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from . import models, schemas, database, crud
import shutil
import os
from funasr import AutoModel
import threading
from fastapi.concurrency import run_in_threadpool

# 简单的音频处理服务
# 注意：生产环境应该把文件传到对象存储 (S3)，这里为了 MVP 直接存本地

UPLOAD_DIR = "uploads/audio"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# --- Local FunASR Model Management ---
LOCAL_FUNASR_MODEL = None

def get_local_funasr_model():
    global LOCAL_FUNASR_MODEL
    if LOCAL_FUNASR_MODEL is None:
        print(f"Loading Local FunASR Model (Paraformer-ZH + Speaker Diarization)... This might take a while first time.")
        try:
            LOCAL_FUNASR_MODEL = AutoModel(
                model="paraformer-zh",
                model_revision="v2.0.4",
                vad_model="fsmn-vad",
                vad_model_revision="v2.0.4",
                punc_model="ct-punc-c",
                punc_model_revision="v2.0.4",
                spk_model="cam++",
                spk_model_revision="v2.0.2",
                disable_update=True,
                device="cpu",
                trust_remote_code=True
            )
            print("Local FunASR Model Loaded.")
        except Exception as e:
            print(f"Failed to load FunASR model: {e}")
            raise e
    return LOCAL_FUNASR_MODEL

def preload_model_background():
    """Start loading the model in a background thread."""
    def _load():
        try:
            get_local_funasr_model()
        except Exception as e:
            print(f"Failed to preload FunASR model: {e}")
    
    thread = threading.Thread(target=_load, daemon=True)
    thread.start()

def format_time(ms):
    """Convert milliseconds to MM:SS format"""
    seconds = ms / 1000
    m, s = divmod(seconds, 60)
    return f"{int(m):02d}:{int(s):02d}"

def run_local_funasr_transcription(file_path: str):
    """
    Blocking function to run local FunASR transcription with speaker separation.
    Should be run in a threadpool.
    """
    model = get_local_funasr_model()
    # Run generation
    # batch_size_s=300 means up to 300 seconds of audio per batch
    res = model.generate(
        input=file_path, 
        batch_size_s=300, 
        hotword='魔搭'
    )
    
    # Process result
    # res is a list of results (one per input file)
    if not res:
        return ""
    
    result_data = res[0]
    full_text = []
    
    # Check if we have sentence_info for detailed speaker segments
    if 'sentence_info' in result_data:
        for sent in result_data['sentence_info']:
            text = sent.get('text', '')
            spk = sent.get('spk', 'Unknown')
            start = sent.get('start', 0)
            end = sent.get('end', 0)
            
            # Format: [Speaker X] MM:SS - MM:SS: Text
            time_str = f"{format_time(start)} - {format_time(end)}"
            full_text.append(f"[说话人 {spk}] {time_str}: {text}")
    elif 'text' in result_data:
        # Fallback if no speaker info
        full_text.append(result_data['text'])
        
    return "\n".join(full_text)

async def process_audio_background(file_path: str, data_id: int, filename: str):
    db = database.SessionLocal()
    try:
        text_content = await transcribe_audio_file(file_path, db)
        data_entry = db.query(models.CustomerData).filter(models.CustomerData.id == data_id).first()
        if data_entry:
            data_entry.content = f"【录音转写: {filename}】\n{text_content}"
            data_entry.source_type = "audio_transcription"
            try:
                stem = os.path.splitext(filename)[0]
                new_filename = f"{stem}转写文字.txt"
            except Exception:
                new_filename = f"{filename}转写文字.txt"
            meta = data_entry.meta_info or {}
            meta.update({
                "filename": new_filename,
                "original_audio_filename": filename,
                "file_path": file_path
            })
            data_entry.meta_info = meta
            db.commit()
    except Exception as e:
        data_entry = db.query(models.CustomerData).filter(models.CustomerData.id == data_id).first()
        if data_entry:
            data_entry.content = f"【转写失败】\n{str(e)}"
            db.commit()
    finally:
        db.close()

async def transcribe_audio_file(file_path: str, db: Session):
    """
    Unified transcription function.
    Uses Local FunASR ONLY (as requested).
    """
    try:
        print("Attempting Local FunASR Transcription...")
        # Use run_in_threadpool to avoid blocking the event loop
        text = await run_in_threadpool(run_local_funasr_transcription, file_path)
        return text
    except Exception as e:
        print(f"Local FunASR Failed: {e}")
        raise HTTPException(status_code=500, detail=f"Transcription failed (Local FunASR): {str(e)}")

# 依赖注入
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

router = APIRouter()


@router.post("/customers/{customer_id}/upload-audio", response_model=schemas.CustomerData)
async def upload_audio(
    customer_id: int, 
    file: UploadFile = File(...), 
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None
):
    # 1. Save file
    # Use await file.read() to ensure non-blocking read and handle async file pointer correctly
    await file.seek(0)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded audio file is empty")

    file_path = os.path.join(UPLOAD_DIR, f"{customer_id}_{file.filename}")
    with open(file_path, "wb") as f:
        f.write(content)
        
    # 2. Create DB Entry with Pending Status (including binary)
    store_upload_binary = os.getenv("STORE_UPLOAD_BINARY") == "1"
    data_entry = schemas.CustomerDataCreate(
        source_type="audio_transcription_pending",
        content="【音频正在转写中...】\n请稍候，转写完成后会自动更新。",
        meta_info={"filename": file.filename, "file_path": file_path},
        file_binary=content if store_upload_binary else None
    )
    db_data = crud.create_customer_data(db=db, data=data_entry, customer_id=customer_id)

    # 3. Trigger Background Task
    if background_tasks:
        background_tasks.add_task(process_audio_background, file_path, db_data.id, file.filename)

    return db_data

@router.post("/chat/global/upload-audio", response_model=dict)
async def chat_global_upload_audio(file: UploadFile = File(...), db: Session = Depends(get_db)):
    # 1. Save file到本地（临时）
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded audio file is empty")
        
    file_path = os.path.join(UPLOAD_DIR, f"global_{file.filename}")
    with open(file_path, "wb") as f:
        f.write(content)
    # 2. Transcribe
    try:
        transcript = await transcribe_audio_file(file_path, db)
        return {"response": f"【本地转写完成】\n{transcript}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"语音分析失败: {str(e)}")
