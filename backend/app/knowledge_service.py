from sqlalchemy.orm import Session
from app import models, schemas
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document
import os

class KnowledgeService:
    def __init__(self, db: Session):
        self.db = db
        self.vector_store = None
        self._init_vector_store()

    def _get_embedding_config(self):
        # MVP: Try to find an OpenAI config first for embeddings
        config = self.db.query(models.LLMConfig).filter(
            models.LLMConfig.is_active == True, 
            models.LLMConfig.provider == 'openai'
        ).first()
        
        if config:
            return config.api_key, config.api_base
            
        # If no OpenAI config, try any active config
        config = self.db.query(models.LLMConfig).filter(models.LLMConfig.is_active == True).first()
        if config:
             # Sanitize key
             api_key = config.api_key
             if api_key and api_key.startswith("Bearer "):
                 api_key = api_key[7:]
             return api_key, config.api_base
                 
        return os.getenv("OPENAI_API_KEY"), os.getenv("OPENAI_API_BASE")

    def _init_vector_store(self):
        # Load all documents from DB and build index
        docs = self.db.query(models.KnowledgeDocument).all()
        if not docs:
            self.vector_store = None
            return

        api_key, api_base = self._get_embedding_config()
        if not api_key:
            print("Warning: No API key found for KnowledgeService (Embeddings)")
            return

        documents = [
            Document(page_content=doc.content, metadata={"source": doc.source, "id": doc.id, "title": doc.title})
            for doc in docs
        ]
        
        try:
            # Handle different providers or base_urls if needed
            kwargs = {"api_key": api_key}
            if api_base:
                kwargs["base_url"] = api_base
                # Some compatible APIs need a specific model
                # kwargs["model"] = "text-embedding-3-small" 
                
            embeddings = OpenAIEmbeddings(**kwargs)
            self.vector_store = FAISS.from_documents(documents, embeddings)
            print(f"Vector Store Initialized with {len(documents)} documents.")
        except Exception as e:
            print(f"Error initializing vector store: {e}")
            self.vector_store = None

    def add_document(self, title: str, content: str, source: str, category: str = "general"):
        # Add to DB
        doc = models.KnowledgeDocument(
            title=title,
            content=content,
            source=source,
            category=category
        )
        self.db.add(doc)
        self.db.commit()
        self.db.refresh(doc)

        # Update Vector Store (MVP: Rebuild or add)
        api_key = self._get_openai_api_key()
        if api_key:
            embeddings = OpenAIEmbeddings(api_key=api_key)
            new_doc = Document(page_content=content, metadata={"source": source, "id": doc.id, "title": title})
            if self.vector_store:
                self.vector_store.add_documents([new_doc])
            else:
                self.vector_store = FAISS.from_documents([new_doc], embeddings)
        
        return doc

    def search(self, query: str, k: int = 3):
        if not self.vector_store:
            return []
        
        results = self.vector_store.similarity_search(query, k=k)
        return [{"content": res.page_content, "metadata": res.metadata} for res in results]

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
        
        # MVP: Rebuild index (inefficient but safe)
        self._init_vector_store()
        return doc

    def delete_document(self, doc_id: int):
        doc = self.db.query(models.KnowledgeDocument).filter(models.KnowledgeDocument.id == doc_id).first()
        if doc:
            self.db.delete(doc)
            self.db.commit()
            # MVP: Rebuild index (inefficient but safe)
            self._init_vector_store()
            return True
        return False
