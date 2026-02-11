import requests
import os
import json
import logging
import datetime
import urllib.parse
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

    def _coerce_cell_value(self, v):
        if v is None:
            return ""
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float, str)):
            return str(v)
        return json.dumps(v, ensure_ascii=False)

    def _format_unix_ts(self, ts, fmt):
        try:
            if ts is None:
                return None
            if isinstance(ts, bool):
                return None
            if isinstance(ts, float):
                ts = int(ts)
            if not isinstance(ts, int):
                return None

            if ts > 10**12:
                dt = datetime.datetime.fromtimestamp(ts / 1000.0)
            elif ts > 10**9:
                dt = datetime.datetime.fromtimestamp(ts)
            else:
                return None
            return dt.strftime(fmt)
        except Exception:
            return None

    def _feishu_date_format_to_strftime(self, date_formatter):
        s = date_formatter or ""
        s = s.replace("yyyy", "%Y").replace("MM", "%m").replace("dd", "%d")
        s = s.replace("HH", "%H").replace("mm", "%M").replace("ss", "%S")
        if "%" not in s:
            return "%Y-%m-%d"
        return s

    def _normalize_value(self, field_meta, v):
        if v is None:
            return ""

        field_type = None if not field_meta else field_meta.get("type")
        ui_type = None if not field_meta else field_meta.get("ui_type")
        prop = None if not field_meta else (field_meta.get("property") or {})

        if field_type in (5, 1001, 1002) or ui_type in ("DateTime", "CreatedTime", "ModifiedTime"):
            fmt = "%Y-%m-%d"
            if isinstance(prop, dict):
                df = prop.get("date_formatter") or prop.get("format") or prop.get("date_format")
                if isinstance(df, str) and df.strip():
                    fmt = self._feishu_date_format_to_strftime(df.strip())
            s = self._format_unix_ts(v, fmt)
            if s is not None:
                return s

        if field_type == 7 and isinstance(v, bool):
            return "是" if v else "否"

        if isinstance(v, dict):
            if "value" in v:
                return self._normalize_value(field_meta, v.get("value"))
            if "text" in v and isinstance(v.get("text"), str):
                return v.get("text") or ""
            if "name" in v and isinstance(v.get("name"), str):
                return v.get("name") or ""
            if "url" in v and isinstance(v.get("url"), str):
                return v.get("url") or ""
            return json.dumps(v, ensure_ascii=False)

        if isinstance(v, list):
            if all(isinstance(x, dict) and isinstance(x.get("text"), str) for x in v):
                return "".join((x.get("text") or "") for x in v)
            if all(isinstance(x, dict) and isinstance(x.get("name"), str) for x in v):
                return ",".join((x.get("name") or "") for x in v if (x.get("name") or "").strip())
            if all(isinstance(x, str) for x in v):
                return ",".join([x for x in v if x.strip()])
            return ",".join([self._coerce_cell_value(self._normalize_value(field_meta, x)) for x in v if self._coerce_cell_value(self._normalize_value(field_meta, x))])

        return v

    def read_bitable(self, app_token: str, table_id: str, view_id: str = None):
        """
        Read records from Feishu Bitable (Multidimensional Sheet).
        """
        self.logger.info(f"Starting read_bitable [v20240523]: app_token={app_token}, table_id={table_id}, view_id={view_id}")
        
        token = self.get_tenant_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8"
        }
        
        # 1. Get Fields (Schema)
        fields_url = f"{self.base_url}/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
        
        field_items = []
        page_token = None
        has_more = True
        
        try:
            while has_more:
                fields_params = {"page_size": 100}
                if view_id:
                    fields_params["view_id"] = view_id
                if page_token:
                    fields_params["page_token"] = page_token
                
                self.logger.debug(f"Fetching fields: {fields_url}, params={fields_params}")
                fields_res = requests.get(fields_url, headers=headers, params=fields_params)
                fields_data = fields_res.json()
                
                if fields_data.get("code") == 0:
                    items = fields_data.get("data", {}).get("items", [])
                    field_items.extend(items)
                    has_more = fields_data.get("data", {}).get("has_more", False)
                    page_token = fields_data.get("data", {}).get("page_token")
                else:
                    self.logger.warning(f"Feishu bitable fields read failed: {fields_data}")
                    has_more = False
        except Exception as e:
            self.logger.exception(f"Feishu bitable fields error: {str(e)}")

        # Create a map for field metadata
        field_map = {f.get("field_name"): f for f in field_items}
        table_headers = [f.get("field_name") for f in field_items if f.get("field_name")]
        self.logger.info(f"Found {len(table_headers)} fields: {table_headers}")

        # 2. List records
        # Use Search endpoint for better filtering and view support
        url = f"{self.base_url}/bitable/v1/apps/{app_token}/tables/{table_id}/records/search"
        
        all_items = []
        has_more = True
        page_token = None
        
        try:
            while has_more:
                params = {"page_size": 500}
                if page_token:
                    params["page_token"] = page_token
                
                qs = urllib.parse.urlencode(params)
                full_url = f"{url}?{qs}"
                
                body = {}
                if view_id:
                    body["view_id"] = view_id
                if table_headers:
                    body["field_names"] = table_headers
                
                self.logger.debug(f"Searching records: {full_url}, body={body}")
                response = requests.post(full_url, headers=headers, json=body)
                data = response.json()
                
                if data.get("code") != 0:
                    code = data.get("code")
                    msg = data.get("msg")
                    self.logger.error(f"Feishu bitable read failed. URL: {full_url} Body: {body} Response: {data}")
                    
                    if code in [99991672, 1254302] or msg == "RolePermNotAllow":
                        suggestion = (
                            "Reason: The current app (tenant_access_token) does not have permission for this Bitable.\n"
                            "Fix: 1) Enable Bitable permissions in Feishu Open Platform.\n"
                            "2) Add this app as a collaborator in the Bitable with Editor/Manager access.\n"
                            "3) Ensure the app has access to all fields if Advanced Permissions are on.\n"
                            "4) Ensure the Bitable is in the same tenant."
                        )
                        raise HTTPException(status_code=403, detail=f"Feishu Bitable Read Failed: {msg} (Code: {code}). {suggestion}")
                    
                    raise HTTPException(status_code=400, detail=f"Feishu Bitable Read Failed: {msg} (Code: {code})")
                    
                items = data.get("data", {}).get("items", [])
                all_items.extend(items)
                
                has_more = data.get("data", {}).get("has_more", False)
                page_token = data.get("data", {}).get("page_token")
                
            
            # 3. Process records with normalization
            rows = [table_headers]
            
            for item in all_items:
                fields = item.get("fields", {})
                row = []
                for header in table_headers:
                    # Get raw value
                    raw_val = fields.get(header)
                    # Get field meta
                    field_meta = field_map.get(header)
                    # Normalize
                    norm_val = self._normalize_value(field_meta, raw_val)
                    # Coerce to string
                    str_val = self._coerce_cell_value(norm_val)
                    row.append(str_val)
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
                     # V2 values endpoint needs a specific range; use a generous default
                     range_name = f"{first_sheet_id}!A1:ZZ10000"
                 else:
                     # Fallback if meta fails
                     range_name = "0!A1:ZZ10000" 
             except:
                 range_name = "0!A1:ZZ10000"

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

    def _list_bitable_tables(self, app_token: str) -> list[dict]:
        token = self.get_tenant_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8"
        }
        url = f"{self.base_url}/bitable/v1/apps/{app_token}/tables"
        items: list[dict] = []
        page_token = None
        has_more = True
        while has_more:
            params = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            res = requests.get(url, headers=headers, params=params)
            data = res.json()
            if data.get("code") != 0:
                break
            data_block = data.get("data", {}) or {}
            items.extend(data_block.get("items", []) or [])
            has_more = data_block.get("has_more", False)
            page_token = data_block.get("page_token")
        return items

    def get_bitable_table_name(self, app_token: str, table_id: str) -> str | None:
        if not app_token or not table_id:
            return None
        try:
            items = self._list_bitable_tables(app_token)
            for item in items:
                if str(item.get("table_id")) == str(table_id):
                    return item.get("table_name") or item.get("name")
            token = self.get_tenant_access_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8"
            }
            url = f"{self.base_url}/bitable/v1/apps/{app_token}/tables/{table_id}"
            res = requests.get(url, headers=headers)
            data = res.json()
            if data.get("code") == 0:
                info = data.get("data", {}) or {}
                return info.get("table_name") or info.get("name")
        except Exception:
            return None
        return None

    def get_sheet_title(self, spreadsheet_token: str, range_name: str = "") -> str | None:
        if not spreadsheet_token:
            return None
        token = self.get_tenant_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        meta_url = f"{self.base_url}/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/query"
        try:
            meta_res = requests.get(meta_url, headers=headers)
            meta_data = meta_res.json()
            sheets = meta_data.get("data", {}).get("sheets", []) if meta_data.get("code") == 0 else []
            if not sheets:
                return None
            target_sheet_id = ""
            if range_name and "!" in range_name:
                target_sheet_id = range_name.split("!", 1)[0]
            if target_sheet_id:
                for sheet in sheets:
                    if str(sheet.get("sheet_id")) == str(target_sheet_id):
                        return sheet.get("title") or sheet.get("sheet_name")
            first = sheets[0]
            return first.get("title") or first.get("sheet_name")
        except Exception:
            return None

    def read_docx(self, document_id: str):
        """
        Read content from Feishu Docx (New Docs).
        Uses raw_content API to get plain text.
        """
        token = self.get_tenant_access_token()
        url = f"{self.base_url}/docx/v1/documents/{document_id}/raw_content"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8"
        }
        
        try:
            response = requests.get(url, headers=headers)
            data = response.json()
            
            if data.get("code") != 0:
                code = data.get("code")
                msg = data.get("msg")
                self.logger.error("Feishu docx read failed", extra={"code": code})
                if code in [99991672]:
                     raise HTTPException(status_code=403, detail=f"无权限访问该文档，请确保应用已添加为协作者。Code: {code}")
                raise HTTPException(status_code=400, detail=f"Feishu Docx Error: {msg}")
            
            return data.get("data", {}).get("content", "")

        except HTTPException:
            raise
        except Exception as e:
            self.logger.exception("Feishu docx exception")
            raise HTTPException(status_code=500, detail=f"Feishu Docx Error: {str(e)}")
