from __future__ import annotations

import hashlib
from pathlib import Path

from app.rag.document import SourceDocument


SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf"}


def load_documents(input_path: Path) -> list[SourceDocument]:
    if input_path.is_file():
        files = [input_path]
    else:
        files = sorted(
            path for path in input_path.rglob("*") if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        )

    documents: list[SourceDocument] = []
    for file_path in files:
        text = _read_file(file_path)
        if not text.strip():
            continue
        source_id = hashlib.sha1(str(file_path).encode("utf-8")).hexdigest()[:12]
        documents.append(
            SourceDocument(
                source_id=source_id,
                title=file_path.stem,
                text=text,
                metadata={"path": str(file_path), "extension": file_path.suffix.lower()},
            )
        )
    return documents


def _read_file(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return file_path.read_text(encoding="utf-8")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF loading requires pypdf. Run: pip install pypdf") from exc
        reader = PdfReader(str(file_path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    raise ValueError(f"Unsupported file type: {file_path.suffix}")

