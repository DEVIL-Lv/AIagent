from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form
from sqlalchemy.orm import Session
from . import database, models, crud
from .feishu_service import FeishuService
import pandas as pd
import io
import os
from pydantic import BaseModel
import re
from typing import Any

router = APIRouter()

class FeishuImportRequest(BaseModel):
    spreadsheet_token: str # Can be spreadsheet token OR app_token (if bitable)
    range_name: str = ""
    import_type: str = "sheet" # "sheet" or "bitable"
    table_id: str = "" # Required for bitable
    view_id: str | None = None
    data_source_id: int | None = None

class FeishuHeaderResponse(BaseModel):
    headers: list[str]

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    s = str(value).strip()
    if not s:
        return ""
    return " ".join(s.split())

def _normalize_customer_name(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if pd.isna(value):
            return ""
        if value.is_integer():
            return str(int(value))
        return _normalize_text(value)
    if isinstance(value, int):
        return str(value).strip()
    s = _normalize_text(value)
    if not s:
        return ""
    m = re.fullmatch(r"(\d+)\.0+", s)
    if m:
        return m.group(1)
    return s

def _normalize_stage(value: Any) -> str:
    s = _normalize_text(value)
    if not s:
        return ""
    text = s.strip().lower()
    mapping = {
        "contact_before": "contact_before",
        "trust_building": "trust_building",
        "product_matching": "product_matching",
        "closing": "closing",
        "接触前": "contact_before",
        "待开发": "contact_before",
        "建立信任": "trust_building",
        "需求分析": "product_matching",
        "产品匹配": "product_matching",
        "商务谈判": "closing",
        "成交关闭": "closing",
        "成交": "closing",
        "认知": "contact_before",
        "观望": "trust_building",
        "决策": "product_matching",
        "犹豫": "trust_building",
        "初次": "contact_before",
        "匹配": "product_matching",
        "谈判": "closing"
    }
    for k, v in mapping.items():
        if k.lower() in text:
            return v
    return s

def _process_single_row(
    db: Session,
    name: str,
    contact: str,
    stage: str,
    risk: str,
    custom_data: dict,
    source_type: str,  # 'excel', 'feishu_sheet', 'feishu_bitable'
    source_desc: str,   # filename or sheet name
    data_source_id: int | None = None,
    cleanup_old_data: bool = False # If True, remove old entries from same source for this customer
) -> int:
    """
    Process a single row of imported data.
    Returns 1 if a new customer was created, 0 otherwise.
    """
    existing_customer = db.query(models.Customer).filter(models.Customer.name == name).first()
    
    created_new = 0
    customer_id = None

    if existing_customer:
        if contact: existing_customer.contact_info = contact
        if stage: existing_customer.stage = stage
        if risk: existing_customer.risk_profile = risk
        # Note: We do NOT update custom_fields anymore to keep Basic Info clean.
        # We explicitly CLEAR it to remove legacy data that might be there.
        existing_customer.custom_fields = None
        # All detailed data goes into CustomerData (import_record).
        customer_id = existing_customer.id
        
        # Cleanup old data if requested (Overwrite Logic)
        if cleanup_old_data:
            # Find and delete existing import_records for this source
            db.query(models.CustomerData).filter(
                models.CustomerData.customer_id == customer_id,
                models.CustomerData.source_type == "import_record",
                # We use JSON_EXTRACT or simple text matching depending on DB. 
                # For safety/portability, we'll iterate or use a simpler source_desc check if stored elsewhere.
                # But here source_desc is inside meta_info. 
                # Ideally, we should filter by meta_info->>'source_name' == source_desc.
                # Since we don't have a strict JSON query helper here, let's rely on Python side or a specialized delete.
                # Optimization: We can do a bulk delete if we trust the inputs.
            ).filter(
                models.CustomerData.content.like(f"Imported from {source_type}: {source_desc}%")
            ).delete(synchronize_session=False)

    else:
        new_customer = models.Customer(
            name=name,
            contact_info=contact if contact else None,
            stage=stage if stage else "contact_before",
            risk_profile=risk if risk else None,
            # custom_fields=custom_data # Do NOT save to custom_fields to avoid redundancy in Basic Info
        )
        db.add(new_customer)
        db.flush() # CRITICAL: Ensure subsequent rows in same transaction find this customer
        customer_id = new_customer.id
        created_new = 1
    
    # Create Detailed Import Record (CustomerData)
    # We store the row data in meta_info for the "Detailed Records" table
    if customer_id:
        meta_info = {
            "source_type": source_type,
            "source_name": source_desc,
            **custom_data
        }
        if data_source_id is not None:
            meta_info["data_source_id"] = data_source_id
        import_record = models.CustomerData(
            customer_id=customer_id,
            source_type="import_record",
            content=f"Imported from {source_type}: {source_desc}",
            meta_info=meta_info
        )
        db.add(import_record)

    return created_new

def _ensure_upload_within_limit(file: UploadFile) -> int:
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
    return max_mb

@router.post("/admin/import-feishu")
def import_customers_from_feishu(request: FeishuImportRequest, db: Session = Depends(get_db)):
    service = FeishuService(db, request.data_source_id)
    
    if request.import_type == "bitable":
        if not request.table_id:
             raise HTTPException(status_code=400, detail="Table ID is required for Bitable import")
        rows = service.read_bitable(request.spreadsheet_token, request.table_id, request.view_id)
    else:
        rows = service.read_spreadsheet(request.spreadsheet_token, request.range_name)
    
    if not rows:
        return {"message": "No data found in Feishu sheet"}
    
    def extract_text(cell):
        if cell is None:
            return ""
        if isinstance(cell, str):
            return cell
        if isinstance(cell, (int, float)):
            return str(cell)
        if isinstance(cell, dict):
            if 'text' in cell:
                return str(cell['text'])
            return str(cell)
        if isinstance(cell, list):
            parts = []
            for seg in cell:
                if isinstance(seg, dict) and 'text' in seg:
                    parts.append(str(seg['text']))
                else:
                    parts.append(str(seg))
            return "".join(parts)
        return str(cell)
    
    raw_headers = rows[0]
    headers = [extract_text(h).strip() for h in raw_headers]
    data_rows = [[extract_text(c) for c in row] for row in rows[1:]]
    
    imported_count = 0
    
    try:
        norm_headers = [str(h).lower() for h in headers]
        def find_idx_exact(header_name: str) -> int:
            target = (header_name or "").strip().lower()
            if not target:
                return -1
            for i, h in enumerate(norm_headers):
                if h.strip() == target:
                    return i
            return -1
        
        name_idx = find_idx_exact("名义购买人")
        if name_idx == -1:
            name_idx = find_idx_exact("姓名")
        if name_idx == -1:
            name_idx = find_idx_exact("姓名(自动更新)")
        if name_idx == -1:
            name_idx = find_idx_exact("姓名（自动更新）")

        def find_idx_contains(patterns: list[str]) -> int:
            for p in patterns:
                p_norm = (p or "").strip().lower()
                if not p_norm:
                    continue
                for i, h in enumerate(norm_headers):
                    if p_norm in h:
                        return i
            return -1

        contact_idx = find_idx_contains(["联系方式", "联系电话", "手机号", "手机", "电话", "contact", "phone", "mobile", "联系"])
        stage_idx = find_idx_contains(["销售阶段", "阶段", "stage"])
        risk_idx = find_idx_contains(["风险偏好", "风险", "risk"])
        
        if name_idx == -1:
            name_idx = find_idx_contains(["姓名"])

        if name_idx == -1:
            raise HTTPException(status_code=400, detail="Could not find key column. Please ensure the sheet has a column named exactly: 名义购买人, 姓名, 姓名(自动更新).")

            
        # Track which customers we have seen in this batch to handle "Overwrite once, then append"
        processed_customers = set()

        for row in data_rows:
            if not row or len(row) <= name_idx: continue
            
            raw_name = row[name_idx]
            name = _normalize_customer_name(raw_name)
            if not name:
                continue
            
            contact = _normalize_text(row[contact_idx]) if contact_idx != -1 and len(row) > contact_idx else ""
            stage = _normalize_stage(row[stage_idx]) if stage_idx != -1 and len(row) > stage_idx else ""
            risk = _normalize_text(row[risk_idx]) if risk_idx != -1 and len(row) > risk_idx else ""
            
            custom_data = {}
            for i, val in enumerate(row):
                if i < len(headers):
                    key = headers[i]
                    value_str = _normalize_text(val)
                    if key and value_str:
                        if i not in (name_idx, contact_idx, stage_idx, risk_idx):
                            custom_data[key] = value_str
            
            source_desc = request.range_name or f"Feishu Sheet {request.spreadsheet_token}"
            if request.import_type == "bitable":
                source_desc = f"Bitable {request.table_id}"
            
            # Add token/table info to custom_data temporarily so it gets into meta_info
            # But _process_single_row puts custom_data into meta_info directly.
            # Better to pass it explicitly or modify _process_single_row.
            # Actually, _process_single_row takes custom_data and spreads it into meta_info.
            # So if we add it to custom_data, it will be in meta_info.
            # However, custom_data is also used for something else?
            # custom_data keys are field names. We should use a reserved key.
            # But let's look at _process_single_row again.
            
            # _process_single_row:
            # meta_info = { "source_type": ..., "source_name": ..., **custom_data }
            
            # So if we add "feishu_token": request.spreadsheet_token to custom_data, it works.
            custom_data["_feishu_token"] = request.spreadsheet_token
            if request.table_id:
                custom_data["_feishu_table_id"] = request.table_id

            # If this is the first time we see this customer in THIS upload batch, 
            # we should clean up their old data from this source.
            cleanup = (name not in processed_customers)
            if cleanup:
                processed_customers.add(name)

            imported_count += _process_single_row(
                db, name, contact, stage, risk, custom_data,
                "feishu_bitable" if request.import_type == "bitable" else "feishu_sheet",
                source_desc,
                request.data_source_id,
                cleanup_old_data=cleanup
            )
            
        db.commit()
        return {"message": f"Successfully imported {imported_count} customers from Feishu"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")

@router.post("/admin/feishu/headers", response_model=FeishuHeaderResponse)
def get_feishu_headers(request: FeishuImportRequest, db: Session = Depends(get_db)):
    service = FeishuService(db, request.data_source_id)
    if request.import_type == "bitable":
        if not request.table_id:
            raise HTTPException(status_code=400, detail="Table ID is required for Bitable import")
        rows = service.read_bitable(request.spreadsheet_token, request.table_id, request.view_id)
    else:
        rows = service.read_spreadsheet(request.spreadsheet_token, request.range_name)
    if not rows:
        return {"headers": []}

    def extract_text(cell):
        if cell is None:
            return ""
        if isinstance(cell, str):
            return cell
        if isinstance(cell, (int, float)):
            return str(cell)
        if isinstance(cell, dict):
            if 'text' in cell:
                return str(cell['text'])
            return str(cell)
        if isinstance(cell, list):
            parts = []
            for seg in cell:
                if isinstance(seg, dict) and 'text' in seg:
                    parts.append(str(seg['text']))
                else:
                    parts.append(str(seg))
            return "".join(parts)
        return str(cell)

    raw_headers = rows[0]
    headers = []
    seen = set()
    for h in raw_headers:
        value = extract_text(h).strip()
        if value and value not in seen:
            seen.add(value)
            headers.append(value)
    return {"headers": headers}

@router.post("/admin/import-excel")
def import_customers_from_excel(
    file: UploadFile = File(...),
    data_source_id: int | None = Form(None),
    db: Session = Depends(get_db)
):
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Only Excel files are supported")
    
    try:
        _ensure_upload_within_limit(file)
        contents = file.file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        df = pd.read_excel(io.BytesIO(contents))
        
        imported_count = 0
        
        norm_cols = [str(c).strip().lower() for c in df.columns]
        def find_col(patterns: list[str]) -> int:
            for i, c in enumerate(norm_cols):
                for p in patterns:
                    if p in c:
                        return i
            return -1
        def find_col_exact(col_name: str) -> int:
            target = (col_name or "").strip().lower()
            if not target:
                return -1
            for i, c in enumerate(norm_cols):
                if c.strip() == target:
                    return i
            return -1

        name_i = find_col_exact("名义购买人")
        if name_i == -1:
            name_i = find_col_exact("姓名")
        if name_i == -1:
            name_i = find_col_exact("姓名(自动更新)")
        if name_i == -1:
            name_i = find_col_exact("姓名（自动更新）")
        contact_i = find_col(["联系方式", "联系电话", "联系", "电话", "手机", "contact", "phone", "mobile"])
        stage_i = find_col(["销售阶段", "阶段", "stage"])
        risk_i = find_col(["风险偏好", "风险", "risk"])
        
        if name_i == -1:
             name_i = find_col(["姓名"])

        if name_i == -1:
             raise HTTPException(status_code=400, detail="Could not find key column. Please ensure the Excel file has a column named exactly: 名义购买人, 姓名, 姓名(自动更新).")

        processed_customers = set()

        for _, row in df.iterrows():
            name = ""
            if name_i >= 0 and name_i < len(df.columns):
                nval = row.iloc[name_i]
                if pd.notna(nval):
                    name = _normalize_customer_name(nval)
            if not name:
                continue
            
            contact = ""
            if contact_i != -1:
                v = row.iloc[contact_i]
                if pd.notna(v): contact = _normalize_text(v)
            stage = ""
            if stage_i != -1:
                v = row.iloc[stage_i]
                if pd.notna(v): stage = _normalize_stage(v)
            risk = ""
            if risk_i != -1:
                v = row.iloc[risk_i]
                if pd.notna(v): risk = _normalize_text(v)
            
            custom_data = {}
            for idx, col in enumerate(df.columns):
                v = row.iloc[idx]
                if pd.notna(v):
                    val = _normalize_text(v)
                    if val and idx not in (name_i, contact_i, stage_i, risk_i):
                        custom_data[str(col).strip()] = val

            cleanup = (name not in processed_customers)
            if cleanup:
                processed_customers.add(name)

            imported_count += _process_single_row(
                db, name, contact, stage, risk, custom_data,
                "excel",
                file.filename or "unknown_file",
                data_source_id,
                cleanup_old_data=cleanup
            )
            
        db.commit()
        return {"message": f"Successfully imported {imported_count} customers"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse Excel: {str(e)}")

@router.post("/admin/import-excel/headers")
def get_excel_headers(file: UploadFile = File(...)):
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Only Excel files are supported")
    try:
        _ensure_upload_within_limit(file)
        contents = file.file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        df = pd.read_excel(io.BytesIO(contents))
        headers = [str(col).strip() for col in df.columns if str(col).strip()]
        return {"headers": headers}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse Excel: {str(e)}")
