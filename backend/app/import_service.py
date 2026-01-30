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

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/admin/import-feishu")
def import_customers_from_feishu(request: FeishuImportRequest, db: Session = Depends(get_db)):
    """
    从飞书多维表格/电子表格导入客户数据
    """
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
            # Feishu rich text cell: {'text': '...', 'segmentStyle': {...}, 'type': 'text'}
            if 'text' in cell:
                return str(cell['text'])
            # Nested dict, fallback to string
            return str(cell)
        if isinstance(cell, list):
            # List of segments or values
            parts = []
            for seg in cell:
                if isinstance(seg, dict) and 'text' in seg:
                    parts.append(str(seg['text']))
                else:
                    parts.append(str(seg))
            return "".join(parts)
        return str(cell)
    
    # Normalize headers and data rows (extract pure text)
    raw_headers = rows[0]
    headers = [extract_text(h) for h in raw_headers]
    data_rows = [[extract_text(c) for c in row] for row in rows[1:]]
    
    imported_count = 0
    
    # Simple mapping logic (Index based or Name based)
    try:
        name_idx = -1
        contact_idx = -1
        stage_idx = -1
        risk_idx = -1
        
        # Identify standard columns
        for i, h in enumerate(headers):
            h_str = str(h).strip()
            if "姓名" in h_str or "Name" in h_str: name_idx = i
            elif "联系" in h_str or "Contact" in h_str or "电话" in h_str: contact_idx = i
            elif "阶段" in h_str or "Stage" in h_str: stage_idx = i
            elif "风险" in h_str or "Risk" in h_str: risk_idx = i
            
        if name_idx == -1:
            # Fallback to column 0 if no explicit name column found
            name_idx = 0
            
        for row in data_rows:
            if not row or len(row) <= name_idx: continue
            
            name = row[name_idx]
            if not name: continue
            
            contact = row[contact_idx] if contact_idx != -1 and len(row) > contact_idx else None
            stage = row[stage_idx] if stage_idx != -1 and len(row) > stage_idx else None
            risk = row[risk_idx] if risk_idx != -1 and len(row) > risk_idx else None
            
            # Extract custom fields (all other columns)
            custom_data = {}
            for i, val in enumerate(row):
                if i not in [name_idx, contact_idx, stage_idx, risk_idx] and i < len(headers):
                    key = headers[i]
                    if key and val: # Only store if key and value exist
                        custom_data[key] = val
            
            # Check if exists (Update if exists, Create if new)
            existing_customer = db.query(models.Customer).filter(models.Customer.name == str(name)).first()
            
            if existing_customer:
                # Update fields if provided and not empty
                if contact: existing_customer.contact_info = str(contact)
                # Only update stage/risk if provided (don't overwrite with empty)
                if stage and stage != "contact_before": existing_customer.stage = str(stage)
                if risk: existing_customer.risk_profile = str(risk)
                
                # Merge custom fields
                if custom_data:
                    current_custom = existing_customer.custom_fields or {}
                    current_custom.update(custom_data)
                    existing_customer.custom_fields = current_custom
                    # Flag modified for ORM to pick up JSON change if needed (usually auto-detected)
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

@router.post("/admin/import-excel")
def import_customers_from_excel(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    管理员批量导入客户数据 (Excel)
    """
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Only Excel files are supported")
    
    try:
        contents = file.file.read()
        df = pd.read_excel(io.BytesIO(contents))
        
        # Expected columns: Name, Contact, Stage, Risk Profile
        # Map them loosely
        imported_count = 0
        
        # Identify standard columns to skip in custom_fields
        standard_cols = ['姓名', 'Name', '联系方式', 'Contact', 'Phone', '阶段', 'Stage', '风险偏好', 'Risk']

        for _, row in df.iterrows():
            # Basic validation
            name = row.get('姓名') or row.get('Name')
            if not name or pd.isna(name):
                continue
                
            contact = row.get('联系方式') or row.get('Contact') or row.get('Phone')
            if pd.isna(contact): contact = None
            
            stage = row.get('阶段') or row.get('Stage')
            if pd.isna(stage): stage = None
            
            risk = row.get('风险偏好') or row.get('Risk')
            if pd.isna(risk): risk = None
            
            # Extract custom fields
            custom_data = {}
            for col in df.columns:
                if col not in standard_cols:
                    val = row.get(col)
                    if not pd.isna(val):
                        custom_data[str(col)] = str(val)

            # Check if exists (Update if exists, Create if new)
            existing_customer = db.query(models.Customer).filter(models.Customer.name == str(name)).first()
            
            if existing_customer:
                if contact: existing_customer.contact_info = str(contact)
                if stage: existing_customer.stage = str(stage)
                if risk: existing_customer.risk_profile = str(risk)
                
                # Merge custom fields
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
