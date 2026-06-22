from __future__ import annotations

import re

from app.rag.document import DocumentChunk, SourceDocument


def split_documents(
    documents: list[SourceDocument],
    chunk_size: int = 520,
    chunk_overlap: int = 80,
) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    for document in documents:
        parts = _split_markdown_sections(document.text)
        if not parts:
            parts = [(None, part) for part in _split_text(document.text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)]
        expanded_parts: list[tuple[str | None, str]] = []
        for heading, part in parts:
            if len(part) <= chunk_size:
                expanded_parts.append((heading, part))
            else:
                expanded_parts.extend((heading, piece) for piece in _split_text(part, chunk_size, chunk_overlap))
        for index, (heading, part) in enumerate(expanded_parts):
            chunks.append(
                DocumentChunk(
                    chunk_id=f"{document.source_id}-{index:04d}",
                    source_id=document.source_id,
                    title=document.title if not heading else f"{document.title} / {heading}",
                    text=part,
                    metadata={**document.metadata, "chunk_index": index, "heading": heading},
                )
            )
    return chunks


def _split_markdown_sections(text: str) -> list[tuple[str | None, str]]:
    lines = text.strip().splitlines()
    sections: list[tuple[str | None, list[str]]] = []
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in lines:
        if line.startswith("## "):
            if current_lines:
                sections.append((current_heading, current_lines))
            current_heading = line[3:].strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_heading, current_lines))

    usable = [
        (heading, "\n".join(section_lines).strip())
        for heading, section_lines in sections
        if heading and "\n".join(section_lines).strip()
    ]
    return usable if len(usable) >= 2 else []


def _split_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    normalized = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(normalized) <= chunk_size:
        return [normalized] if normalized else []

    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        window = normalized[start:end]
        boundary = max(window.rfind("\n\n"), window.rfind("。"), window.rfind("."), window.rfind("\n"))
        if boundary > chunk_size * 0.45 and end < len(normalized):
            end = start + boundary + 1
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start = max(0, end - chunk_overlap)
    return chunks
