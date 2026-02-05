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
        config = self.db.query(models.LLMConfig).filter(
            models.LLMConfig.is_active == True,
            models.LLMConfig.provider == 'openai'
        ).first()

        if not config:
            config = self.db.query(models.LLMConfig).filter(models.LLMConfig.is_active == True).first()

        if config:
            api_key = config.api_key
            if api_key:
                api_key = api_key.strip()
                if api_key.startswith("Bearer "):
                    api_key = api_key[7:]
            return api_key, config.api_base, config.model_name

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
            if model_name:
                kwargs["model"] = model_name

            try:
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
