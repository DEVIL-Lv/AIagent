from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlalchemy.orm import Session
from . import database, models, crud
from .feishu_service import FeishuService
import pandas as pd
import io
from pydantic import BaseModel

router = APIRouter()

class FeishuImportRequest(BaseModel):
    spreadsheet_token: str # Can be spreadsheet token OR app_token (if bitable)
    range_name: str = ""
    import_type: str = "sheet" # "sheet" or "bitable"
    table_id: str = "" # Required for bitable
    data_source_id: int | None = None

class FeishuHeaderResponse(BaseModel):
    headers: list[str]

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/admin/import-feishu")
def import_customers_from_feishu(request: FeishuImportRequest, db: Session = Depends(get_db)):
    service = FeishuService(db, request.data_source_id)
    
    if request.import_type == "bitable":
        if not request.table_id:
             raise HTTPException(status_code=400, detail="Table ID is required for Bitable import")
        rows = service.read_bitable(request.spreadsheet_token, request.table_id)
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
        def find_idx(patterns: list[str]) -> int:
            for i, h in enumerate(norm_headers):
                for p in patterns:
                    if p in h:
                        return i
            return -1
        name_idx = find_idx(["客户姓名", "姓名", "客户名称", "名称", "name"])
        contact_idx = find_idx(["联系方式", "联系电话", "联系", "电话", "手机", "contact", "phone", "mobile"])
        stage_idx = find_idx(["销售阶段", "阶段", "stage"])
        risk_idx = find_idx(["风险偏好", "风险", "risk"])
        if name_idx == -1:
            name_idx = 0
            
        for row in data_rows:
            if not row or len(row) <= name_idx: continue
            
            name = row[name_idx]
            if not name:
                for j, val in enumerate(row):
                    v = str(val).strip()
                    if v:
                        if j not in (contact_idx, stage_idx, risk_idx):
                            name = v
                            break
            if not name:
                continue
            
            contact = row[contact_idx] if contact_idx != -1 and len(row) > contact_idx else None
            stage = row[stage_idx] if stage_idx != -1 and len(row) > stage_idx else None
            risk = row[risk_idx] if risk_idx != -1 and len(row) > risk_idx else None
            
            custom_data = {}
            for i, val in enumerate(row):
                if i < len(headers):
                    key = headers[i]
                    value_str = str(val).strip() if val is not None else ""
                    if key and value_str:
                        if i not in (name_idx, contact_idx, stage_idx, risk_idx):
                            custom_data[key] = value_str
            
            existing_customer = db.query(models.Customer).filter(models.Customer.name == str(name)).first()
            
            if existing_customer:
                if contact: existing_customer.contact_info = str(contact)
                if stage and stage != "contact_before": existing_customer.stage = str(stage)
                if risk: existing_customer.risk_profile = str(risk)
                if custom_data:
                    current_custom = existing_customer.custom_fields or {}
                    current_custom.update(custom_data)
                    existing_customer.custom_fields = current_custom
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(existing_customer, "custom_fields")
                imported_count += 1
            else:
                customer_data = models.Customer(
                    name=str(name),
                    contact_info=str(contact) if contact else None,
                    stage=str(stage) if stage else "contact_before",
                    risk_profile=str(risk) if risk else None,
                    custom_fields=custom_data
                )
                db.add(customer_data)
                imported_count += 1
            
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
        rows = service.read_bitable(request.spreadsheet_token, request.table_id)
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
def import_customers_from_excel(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Only Excel files are supported")
    
    try:
        contents = file.file.read()
        df = pd.read_excel(io.BytesIO(contents))
        
        imported_count = 0
        
        norm_cols = [str(c).strip().lower() for c in df.columns]
        def find_col(patterns: list[str]) -> int:
            for i, c in enumerate(norm_cols):
                for p in patterns:
                    if p in c:
                        return i
            return -1
        name_i = find_col(["客户姓名", "姓名", "客户名称", "名称", "name"])
        contact_i = find_col(["联系方式", "联系电话", "联系", "电话", "手机", "contact", "phone", "mobile"])
        stage_i = find_col(["销售阶段", "阶段", "stage"])
        risk_i = find_col(["风险偏好", "风险", "risk"])
        if name_i == -1:
            name_i = 0
        
        for _, row in df.iterrows():
            name = None
            if name_i >= 0 and name_i < len(df.columns):
                nval = row.iloc[name_i]
                if pd.notna(nval):
                    name = str(nval).strip()
            if not name:
                for j in range(len(df.columns)):
                    v = row.iloc[j]
                    if pd.notna(v):
                        sv = str(v).strip()
                        if sv and j not in (contact_i, stage_i, risk_i):
                            name = sv
                            break
            if not name:
                continue
            
            contact = None
            if contact_i != -1:
                v = row.iloc[contact_i]
                if pd.notna(v): contact = str(v).strip()
            stage = None
            if stage_i != -1:
                v = row.iloc[stage_i]
                if pd.notna(v): stage = str(v).strip()
            risk = None
            if risk_i != -1:
                v = row.iloc[risk_i]
                if pd.notna(v): risk = str(v).strip()
            
            custom_data = {}
            for idx, col in enumerate(df.columns):
                v = row.iloc[idx]
                if pd.notna(v):
                    val = str(v).strip()
                    if val and idx not in (name_i, contact_i, stage_i, risk_i):
                        custom_data[str(col).strip()] = val

            existing_customer = db.query(models.Customer).filter(models.Customer.name == str(name)).first()
            
            if existing_customer:
                if contact: existing_customer.contact_info = str(contact)
                if stage: existing_customer.stage = str(stage)
                if risk: existing_customer.risk_profile = str(risk)
                if custom_data:
                    current_custom = existing_customer.custom_fields or {}
                    current_custom.update(custom_data)
                    existing_customer.custom_fields = current_custom
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(existing_customer, "custom_fields")
                imported_count += 1
            else:
                customer_data = models.Customer(
                    name=str(name),
                    contact_info=str(contact) if contact else None,
                    stage=str(stage) if stage else "contact_before",
                    risk_profile=str(risk) if risk else None,
                    custom_fields=custom_data
                )
                db.add(customer_data)
                imported_count += 1
            
        db.commit()
        return {"message": f"Successfully imported {imported_count} customers"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse Excel: {str(e)}")

@router.post("/admin/import-excel/headers")
def get_excel_headers(file: UploadFile = File(...)):
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Only Excel files are supported")
    try:
        contents = file.file.read()
        df = pd.read_excel(io.BytesIO(contents))
        headers = [str(col).strip() for col in df.columns if str(col).strip()]
        return {"headers": headers}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse Excel: {str(e)}")
