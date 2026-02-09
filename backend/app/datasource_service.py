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

@router.put("/admin/data-sources/{config_id}", response_model=schemas.DataSourceConfig)
def update_data_source(config_id: int, update: schemas.DataSourceConfigUpdate, db: Session = Depends(get_db)):
    result = crud.update_data_source_config(db, config_id, update)
    if not result:
        raise HTTPException(status_code=404, detail="Data source not found")
    return result
