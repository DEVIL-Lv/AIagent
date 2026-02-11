from sqlalchemy import create_engine, text, inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
import socket
from urllib.parse import quote_plus
import logging
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
logger = logging.getLogger(__name__)

def _is_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except Exception:
        return False

def _build_mysql_uri(host: str, port: str, database: str, user: str, password: str) -> str:
    safe_user = quote_plus(user or "")
    safe_password = quote_plus(password or "")
    return f"mysql+pymysql://{safe_user}:{safe_password}@{host}:{port}/{database}?charset=utf8mb4"

DB_URI = os.getenv("SQLALCHEMY_DATABASE_URL")
if not DB_URI:
    mysql_host = os.getenv("MYSQL_HOST")
    mysql_port = os.getenv("MYSQL_PORT") or "3306"
    mysql_database = os.getenv("MYSQL_DATABASE")
    mysql_user = os.getenv("MYSQL_USER")
    mysql_password = os.getenv("MYSQL_PASSWORD")
    mysql_explicit = any([mysql_host, mysql_database, mysql_user, mysql_password])
    if not mysql_explicit:
        # Default to SQLite to avoid conflict with other local MySQL instances
        DB_FILE = os.path.normpath(os.path.join(BASE_DIR, "..", "..", "sql_app.db"))
        DB_URI = f"sqlite:///{Path(DB_FILE).as_posix()}"
    else:
        DB_URI = _build_mysql_uri(mysql_host or "127.0.0.1", mysql_port, mysql_database or "ai_agent", mysql_user or "ai_agent", mysql_password or "ai_agent_pass")
else:
    if DB_URI.startswith("sqlite:///./"):
        relative_path = DB_URI.replace("sqlite:///./", "")
        DB_FILE = os.path.normpath(os.path.join(BASE_DIR, "..", "..", relative_path))
        DB_URI = f"sqlite:///{Path(DB_FILE).as_posix()}"
    else:
        DB_FILE = DB_URI
db_engine = "sqlite" if DB_URI.startswith("sqlite") else "mysql"
logger.info("Database configured", extra={"engine": db_engine})

engine_args = {}
if DB_URI.startswith("sqlite"):
    engine_args["connect_args"] = {"check_same_thread": False}

engine = create_engine(DB_URI, **engine_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def ensure_schema():
    inspector = inspect(engine)

    def has_table(table: str) -> bool:
        try:
            return inspector.has_table(table)
        except Exception:
            return False

    def has_column(table: str, column: str) -> bool:
        try:
            cols = inspector.get_columns(table)
        except Exception:
            return False
        return any(c["name"] == column for c in cols)

    def add_column(table: str, column: str, col_type: str, default_sql: str | None = None):
        if not has_table(table):
            return
        if has_column(table, column):
            return
        ddl = f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
        if default_sql is not None:
            ddl += f" DEFAULT {default_sql}"
        with engine.begin() as conn:
            conn.execute(text(ddl))

    add_column("customers", "custom_fields", "JSON")
    add_column("customers", "summary", "TEXT")
    add_column("customer_data", "meta_info", "JSON")
    add_column("llm_configs", "embedding_model_name", "VARCHAR(255)")
    add_column("customer_data", "file_binary", "BLOB")
    add_column("llm_configs", "cost_input_1k", "FLOAT", "0.0")
    add_column("llm_configs", "cost_output_1k", "FLOAT", "0.0")
    add_column("llm_configs", "total_tokens", "INTEGER", "0")
    add_column("llm_configs", "total_cost", "FLOAT", "0.0")
    add_column("llm_configs", "is_active", "BOOLEAN", "1")
    add_column("data_source_configs", "is_active", "BOOLEAN", "1")
    add_column("routing_rules", "is_active", "BOOLEAN", "1")
    add_column("users", "role", "TEXT", "'admin'")
    add_column("customer_data", "session_id", "INTEGER")
    
    # Knowledge Preprocessing Support
    add_column("scripts", "raw_content", "TEXT")
    add_column("knowledge_documents", "raw_content", "TEXT")
