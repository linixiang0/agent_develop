from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from app.rag.document import DocumentChunk, RetrievalResult
from app.rag.embeddings import cosine_similarity, term_frequency


class LocalVectorStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._chunks: list[DocumentChunk] = []
        self._vectors: dict[str, dict[str, float]] = {}

    @property
    def chunks(self) -> list[DocumentChunk]:
        return list(self._chunks)

    def build(self, chunks: list[DocumentChunk]) -> None:
        self._chunks = chunks
        self._vectors = {
            chunk.chunk_id: term_frequency(f"{chunk.title}\n{chunk.metadata.get('path', '')}\n{chunk.text}")
            for chunk in chunks
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "chunks": [asdict(chunk) for chunk in self._chunks],
            "vectors": self._vectors,
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self) -> None:
        if not self.path.exists():
            self._chunks = []
            self._vectors = {}
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self._chunks = [DocumentChunk(**chunk) for chunk in payload.get("chunks", [])]
        self._vectors = payload.get("vectors", {})

    def search(self, query: str, top_k: int = 4) -> list[RetrievalResult]:
        query_vector = term_frequency(query)
        scored = [
            RetrievalResult(
                chunk=chunk,
                score=cosine_similarity(query_vector, self._vectors.get(chunk.chunk_id, {})) * _source_boost(query, chunk),
            )
            for chunk in self._chunks
        ]
        return [result for result in sorted(scored, key=lambda item: item.score, reverse=True)[:top_k] if result.score > 0]


def _source_boost(query: str, chunk: DocumentChunk) -> float:
    path = str(chunk.metadata.get("path", ""))
    title = chunk.title
    if any(keyword in query for keyword in ["CS599", "期末大作业", "评分", "加分", "GitHub", "报告 PDF"]):
        if "cs599_course_requirements" in path or "cs599_course_requirements" in title:
            return 3.0
        if "synthetic_campus_knowledge" in path:
            return 0.55
    if "真实公开资料" in query or "合成资料" in query:
        if "real_public_grad_service_knowledge" in path or "real_public_grad_service_knowledge" in title:
            return 1.4
    return 1.0
