from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from . import models, schemas, crud, database

router = APIRouter()

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/admin/data-sources/", response_model=schemas.DataSourceConfig)
def create_data_source(config: schemas.DataSourceConfigCreate, db: Session = Depends(get_db)):
    return crud.create_data_source_config(db=db, config=config)

@router.get("/admin/data-sources/", response_model=List[schemas.DataSourceConfig])
def read_data_sources(db: Session = Depends(get_db)):
    return crud.get_data_source_configs(db)

@router.delete("/admin/data-sources/{config_id}")
def delete_data_source(config_id: int, db: Session = Depends(get_db)):
    config = db.query(models.DataSourceConfig).filter(models.DataSourceConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Data source not found")
    deleted_customers = crud.delete_customers_by_data_source(db, config_id)
    result = crud.delete_data_source_config(db, config_id)
    return {"message": "Deleted successfully", "deleted_customers": deleted_customers}

@router.delete("/admin/data-sources/{config_id}/feishu-sheet")
def delete_feishu_sheet(config_id: int, token: str, db: Session = Depends(get_db)):
    # 1. Clean the token to match meta_info storage
    clean_token = token
    if '/base/' in token:
        parts = token.split('/base/')
        if len(parts) > 1:
            clean_token = parts[1].split('?')[0]
    elif '/sheets/' in token:
        parts = token.split('/sheets/')
        if len(parts) > 1:
            clean_token = parts[1].split('?')[0]
    elif '/docx/' in token:
        parts = token.split('/docx/')
        if len(parts) > 1:
            clean_token = parts[1].split('?')[0]
    elif '/docs/' in token:
        parts = token.split('/docs/')
        if len(parts) > 1:
            clean_token = parts[1].split('?')[0]
    
    # Also handle simple query param stripping if it wasn't a full URL
    clean_token = clean_token.split('?')[0]

    # 2. Delete customers associated with this token
    deleted_customers = crud.delete_customers_by_token(db, config_id, clean_token)
    
    # 3. Update config to remove token from saved_sheets and display_fields_by_token
    config = db.query(models.DataSourceConfig).filter(models.DataSourceConfig.id == config_id).first()
    if config and config.config_json:
        current_json = dict(config.config_json)
        changed = False
        
        # Remove from saved_sheets (match against raw token)
        if "saved_sheets" in current_json:
            original_len = len(current_json["saved_sheets"])
            current_json["saved_sheets"] = [
                s for s in current_json["saved_sheets"] 
                if s.get("token") != token
            ]
            if len(current_json["saved_sheets"]) != original_len:
                changed = True
        
        # Remove from display_fields_by_token (match against raw token)
        if "display_fields_by_token" in current_json:
            if token in current_json["display_fields_by_token"]:
                del current_json["display_fields_by_token"][token]
                changed = True
        
        if changed:
            config.config_json = current_json
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(config, "config_json")
            db.commit()
            
    return {"message": "Sheet deleted successfully", "deleted_customers": deleted_customers}

@router.put("/admin/data-sources/{config_id}", response_model=schemas.DataSourceConfig)
def update_data_source(config_id: int, update: schemas.DataSourceConfigUpdate, db: Session = Depends(get_db)):
    result = crud.update_data_source_config(db, config_id, update)
    if not result:
        raise HTTPException(status_code=404, detail="Data source not found")
    return result
