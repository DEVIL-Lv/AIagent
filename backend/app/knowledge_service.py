from sqlalchemy.orm import Session
from app import models, schemas
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document
import os
import threading
import logging

_VECTOR_STORE: FAISS | None = None
_VECTOR_STORE_SIGNATURE: tuple[int, int] | None = None
_VECTOR_STORE_LOCK = threading.Lock()
logger = logging.getLogger(__name__)


from langchain_core.embeddings import Embeddings
import requests

class DoubaoEmbeddings(Embeddings):
    def __init__(self, api_key: str, model: str, api_base: str):
        self.api_key = api_key
        self.model = model
        self.api_base = api_base.rstrip("/")
        # Ensure we target the multimodal endpoint if it's the multimodal model
        # User provided curl uses /api/v3/embeddings/multimodal
        # Standard base might be https://ark.cn-beijing.volces.com/api/v3
        if "multimodal" not in self.api_base and "doubao-embedding-vision" in model:
             self.api_base = f"{self.api_base}/embeddings/multimodal"
        elif "embeddings" not in self.api_base:
             # Fallback for standard embedding endpoint if not specified
             # But for this specific vision model, we prioritize the multimodal path
             self.api_base = f"{self.api_base}/embeddings/multimodal"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # Map list of strings to list of dicts as required by Doubao Multimodal API
        input_payload = [{"type": "text", "text": text} for text in texts]
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        payload = {
            "model": self.model,
            "input": input_payload
        }
        
        try:
            response = requests.post(self.api_base, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            # Extract embeddings in order
            # Response format: { "data": [ { "embedding": [...], "index": 0 }, ... ] }
            results = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
            return [item["embedding"] for item in results]
        except Exception as e:
            logger.error(f"Doubao embedding failed: {str(e)}")
            raise

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

def _chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    chunks = []
    start = 0
    length = len(cleaned)
    while start < length:
        end = min(length, start + chunk_size)
        chunks.append(cleaned[start:end])
        if end >= length:
            break
        start = max(0, end - overlap)
    return chunks


def _signature_from_docs(docs: list[models.KnowledgeDocument]) -> tuple[int, int]:
    max_id = 0
    for d in docs:
        if d.id and d.id > max_id:
            max_id = d.id
    return (len(docs), max_id)


class KnowledgeService:
    def __init__(self, db: Session):
        self.db = db

    @classmethod
    def invalidate_cache(cls):
        global _VECTOR_STORE, _VECTOR_STORE_SIGNATURE
        with _VECTOR_STORE_LOCK:
            _VECTOR_STORE = None
            _VECTOR_STORE_SIGNATURE = None

    def _get_embedding_config(self):
        # Priority 1: Config with explicit embedding_model_name
        config = self.db.query(models.LLMConfig).filter(
            models.LLMConfig.is_active == True,
            models.LLMConfig.embedding_model_name != None,
            models.LLMConfig.embedding_model_name != ""
        ).first()

        if not config:
            # Priority 2: Config where model_name contains "embedding" (e.g. doubao-embedding-vision)
            # This handles the case where the user put the embedding model in the main model_name field
            config = self.db.query(models.LLMConfig).filter(
                models.LLMConfig.is_active == True,
                models.LLMConfig.model_name.ilike("%embedding%")
            ).first()

        if not config:
            # Priority 3: OpenAI config (legacy behavior)
            config = self.db.query(models.LLMConfig).filter(
                models.LLMConfig.is_active == True,
                models.LLMConfig.provider == 'openai'
            ).first()

        if not config:
            # Priority 4: Any active config
            config = self.db.query(models.LLMConfig).filter(models.LLMConfig.is_active == True).first()

        if config:
            api_key = config.api_key
            if api_key:
                api_key = api_key.strip()
                if api_key.startswith("Bearer "):
                    api_key = api_key[7:]
            # If embedding_model_name is set, use it. Otherwise use model_name (e.g. gpt-4) which might fail for embeddings
            model = config.embedding_model_name if config.embedding_model_name else config.model_name
            return api_key, config.api_base, model

        return os.getenv("OPENAI_API_KEY"), os.getenv("OPENAI_API_BASE"), None

    def _get_or_build_vector_store(self) -> FAISS | None:
        global _VECTOR_STORE, _VECTOR_STORE_SIGNATURE

        docs = self.db.query(models.KnowledgeDocument).all()
        if not docs:
            return None

        sig = _signature_from_docs(docs)

        with _VECTOR_STORE_LOCK:
            if _VECTOR_STORE is not None and _VECTOR_STORE_SIGNATURE == sig:
                return _VECTOR_STORE

            api_key, api_base, model_name = self._get_embedding_config()
            if not api_key:
                logger.warning("Knowledge embeddings unavailable: missing api_key")
                return None

            texts: list[str] = []
            metadatas: list[dict] = []
            for doc in docs:
                text = doc.content or ""
                if not text.strip():
                    continue
                for chunk in _chunk_text(text):
                    texts.append(str(chunk))
                    metadatas.append({"source": doc.source, "id": doc.id, "title": doc.title})
            if not texts:
                return None

            kwargs = {"api_key": api_key}
            if api_base:
                kwargs["base_url"] = api_base
            
            # Fix: Do NOT use the LLM model name (e.g. gpt-4) for embeddings unless it is explicitly compatible.
            # Use embedding_model_name from config if available, otherwise default to text-embedding-ada-002
            # or rely on provider default if not specified.
            if model_name and "gpt" not in model_name.lower() and "claude" not in model_name.lower():
               kwargs["model"] = model_name
            elif model_name and ("embedding" in model_name.lower() or "bge" in model_name.lower()):
               kwargs["model"] = model_name

            try:
                # Use custom DoubaoEmbeddings if configured
            if model_name and ("doubao" in model_name.lower() or "volcengine" in str(api_base).lower() or "volces" in str(api_base).lower()):
                if not api_base:
                    # Default to Volcengine public endpoint if not set but model name implies Doubao
                    api_base = "https://ark.cn-beijing.volces.com/api/v3"
                elif ("volcengine" in str(api_base).lower() or "volces" in str(api_base).lower()) and "/api/v3" not in str(api_base).lower():
                    # Auto-fix common mistake where user omits /api/v3
                    api_base = str(api_base).rstrip("/") + "/api/v3"
                
                embeddings = DoubaoEmbeddings(api_key=api_key, model=model_name, api_base=api_base)
            else:
                embeddings = OpenAIEmbeddings(**kwargs)
                
                _VECTOR_STORE = FAISS.from_texts(texts, embeddings, metadatas=metadatas)
                _VECTOR_STORE_SIGNATURE = sig
                return _VECTOR_STORE
            except Exception:
                logger.exception("Knowledge vector build failed")
                _VECTOR_STORE = None
                _VECTOR_STORE_SIGNATURE = None
                return None

    def add_document(self, title: str, content: str, source: str, category: str = "general"):
        doc = models.KnowledgeDocument(
            title=title,
            content=content,
            source=source,
            category=category
        )
        self.db.add(doc)
        self.db.commit()
        self.db.refresh(doc)
        self.invalidate_cache()
        return doc

    def search(self, query: str, k: int = 3):
        try:
            vector_store = self._get_or_build_vector_store()
            if not vector_store:
                return []
            results = vector_store.similarity_search(query, k=k)
            return [{"content": res.page_content, "metadata": res.metadata} for res in results]
        except Exception:
            logger.exception("Knowledge search failed")
            return []

    def list_documents(self):
        return self.db.query(models.KnowledgeDocument).all()

    def get_document(self, doc_id: int):
        return self.db.query(models.KnowledgeDocument).filter(models.KnowledgeDocument.id == doc_id).first()

    def update_document(self, doc_id: int, title: str = None, content: str = None, category: str = None):
        doc = self.db.query(models.KnowledgeDocument).filter(models.KnowledgeDocument.id == doc_id).first()
        if not doc:
            return None

        if title:
            doc.title = title
        if content:
            doc.content = content
        if category:
            doc.category = category

        self.db.commit()
        self.db.refresh(doc)
        self.invalidate_cache()
        return doc

    def delete_document(self, doc_id: int):
        doc = self.db.query(models.KnowledgeDocument).filter(models.KnowledgeDocument.id == doc_id).first()
        if doc:
            self.db.delete(doc)
            self.db.commit()
            self.invalidate_cache()
            return True
        return False
