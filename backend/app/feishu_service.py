import requests
import os
import json
import logging
from fastapi import HTTPException
from sqlalchemy.orm import Session
from . import models

class FeishuService:
    def __init__(self, db: Session, config_id: int | None = None):
        self.db = db
        self.app_id = None
        self.app_secret = None
        
        # Load config from DB
        config = None
        if config_id:
            config = db.query(models.DataSourceConfig).filter(
                models.DataSourceConfig.id == config_id,
                models.DataSourceConfig.source_type == 'feishu',
                models.DataSourceConfig.is_active == True
            ).first()
        if not config:
            config = db.query(models.DataSourceConfig).filter(
                models.DataSourceConfig.source_type == 'feishu',
                models.DataSourceConfig.is_active == True
            ).first()
        
        if config and config.config_json:
            self.app_id = config.config_json.get('app_id')
            self.app_secret = config.config_json.get('app_secret')
            
        # Fallback to env vars if DB config missing (optional, for backward compatibility)
        if not self.app_id:
            self.app_id = os.getenv("FEISHU_APP_ID", "")
        if not self.app_secret:
            self.app_secret = os.getenv("FEISHU_APP_SECRET", "")
            
        self.base_url = "https://open.feishu.cn/open-apis"
        self.logger = logging.getLogger(__name__)

    def get_tenant_access_token(self):
        if not self.app_id or not self.app_secret:
            self.logger.warning("Feishu config missing")
            raise HTTPException(status_code=400, detail="Feishu App ID or Secret not configured. Please add a Data Source in Settings.")

        url = f"{self.base_url}/auth/v3/tenant_access_token/internal"
        headers = {"Content-Type": "application/json; charset=utf-8"}
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }
        try:
            response = requests.post(url, headers=headers, json=payload)
            data = response.json()
            if data.get("code") != 0:
                error_msg = f"Feishu Auth Failed: {data.get('msg')} (Code: {data.get('code')})"
                self.logger.error("Feishu auth failed", extra={"code": data.get("code")})
                raise Exception(error_msg)
            return data.get("tenant_access_token")
        except Exception as e:
            self.logger.exception("Feishu auth exception")
            raise HTTPException(status_code=500, detail=f"Feishu Auth Error: {str(e)}")

    def read_bitable(self, app_token: str, table_id: str):
        """
        Read records from Feishu Bitable (Multidimensional Sheet).
        """
        token = self.get_tenant_access_token()
        
        # 1. List records
        # GET /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records
        url = f"{self.base_url}/bitable/v1/apps/{app_token}/tables/{table_id}/records"
        headers = {
            "Authorization": f"Bearer {token}",
        }
        params = {
            "page_size": 100 # Adjust as needed
        }
        
        try:
            response = requests.get(url, headers=headers, params=params)
            data = response.json()
            
            if data.get("code") != 0:
                code = data.get("code")
                msg = data.get("msg")
                self.logger.error("Feishu bitable read failed", extra={"code": code})
                if code in [99991672]:
                    suggestion = (
                        "飞书返回无权限。请在目标多维表格中将企业应用添加为协作者或允许企业应用访问，"
                        "并在飞书开放平台为该应用开通 Bitable 读取权限。使用 app_token + table_id。"
                    )
                    raise HTTPException(status_code=403, detail=f"Feishu Bitable Read Failed: {msg} (Code: {code}). {suggestion}")
                raise HTTPException(status_code=400, detail=f"Feishu Bitable Read Failed: {msg} (Code: {code})")
                
            items = data.get("data", {}).get("items", [])
            
            # Convert to list of lists (header + rows) to match read_spreadsheet output format
            if not items:
                return []
                
            # Extract fields
            # items = [{ "fields": { "Name": "...", "Phone": "..." }, "record_id": "..." }]
            
            # Collect all unique keys from all records to form headers
            keys = set()
            for item in items:
                keys.update(item.get("fields", {}).keys())
            
            headers = list(keys)
            rows = [headers]
            
            for item in items:
                fields = item.get("fields", {})
                row = [fields.get(k, "") for k in headers]
                rows.append(row)
                
            return rows
            
        except HTTPException:
             raise
        except Exception as e:
             self.logger.exception("Feishu bitable error")
             raise HTTPException(status_code=500, detail=f"Feishu Bitable Error: {str(e)}")

    def read_spreadsheet(self, spreadsheet_token: str, range_name: str = ""):
        token = self.get_tenant_access_token()
        
        # Get Sheet Meta to find first sheet id if range is not specific
        if not range_name or "!" not in range_name:
             meta_url = f"{self.base_url}/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/query"
             headers = {"Authorization": f"Bearer {token}"}
             try:
                 meta_res = requests.get(meta_url, headers=headers)
                 meta_data = meta_res.json()
                 if meta_data.get("code") == 0 and meta_data.get("data", {}).get("sheets"):
                     first_sheet_id = meta_data["data"]["sheets"][0]["sheet_id"]
                     range_name = f"{first_sheet_id}" # Read whole sheet? V2 API needs range like sheetId!range
                     # Actually V2 values endpoint needs range. 
                     # Let's default to A1:Z200 for MVP
                     range_name = f"{first_sheet_id}!A1:Z200"
                 else:
                     # Fallback if meta fails
                     range_name = "0!A1:Z200" 
             except:
                 range_name = "0!A1:Z200"

        url = f"{self.base_url}/sheets/v2/spreadsheets/{spreadsheet_token}/values/{range_name}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8"
        }
        
        response = requests.get(url, headers=headers)
        data = response.json()
        
        if data.get("code") != 0:
             code = data.get("code")
             msg = data.get("msg")
             self.logger.error("Feishu read failed", extra={"code": code})
             # Permission related codes: 99991672 (No permission)
             if code in [99991672]:
                 suggestion = (
                     "飞书返回无权限。请在目标文档/多维表格中将企业应用添加为协作者或允许企业应用访问，"
                     "并在飞书开放平台为该应用开通 Sheets/Bitable 读取权限。"
                     "多维表格请使用 app_token + table_id；电子表格使用 spreadsheet_token。"
                 )
                 raise HTTPException(status_code=403, detail=f"Feishu Read Failed: {msg} (Code: {code}). {suggestion}")
             error_msg = f"Feishu Read Failed: {msg} (Code: {code})"
             raise HTTPException(status_code=400, detail=error_msg)
             
        return data.get("data", {}).get("valueRange", {}).get("values", [])
