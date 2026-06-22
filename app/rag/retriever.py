from __future__ import annotations

from pathlib import Path

from app.rag.document import RetrievalResult
from app.rag.vectorstore import LocalVectorStore


class KnowledgeBaseRetriever:
    def __init__(self, vectorstore_path: Path) -> None:
        self.vectorstore = LocalVectorStore(vectorstore_path)
        self.vectorstore.load()

    def retrieve(self, question: str, top_k: int = 4) -> list[RetrievalResult]:
        return self.vectorstore.search(question, top_k=top_k)

