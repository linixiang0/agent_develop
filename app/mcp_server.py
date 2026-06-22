from __future__ import annotations

import json
import sys
from typing import Any

from app.factory import build_agent


PROTOCOL_VERSION = "2024-11-05"


def main() -> None:
    while True:
        message = _read_message()
        if message is None:
            break
        response = _handle_message(message)
        if response is not None:
            _write_message(response)


def _handle_message(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    message_id = message.get("id")
    if method == "notifications/initialized":
        return None
    try:
        if method == "initialize":
            result = {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "edurag-agent-mcp", "version": "0.1.0"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "search_knowledge_base",
                        "description": "Search EduRAG-Agent course, graduate affairs, and campus service knowledge base.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "Natural-language search query."},
                                "top_k": {"type": "integer", "minimum": 1, "maximum": 8, "default": 4},
                            },
                            "required": ["query"],
                        },
                    }
                ]
            }
        elif method == "tools/call":
            params = message.get("params") or {}
            result = _call_tool(params.get("name", ""), params.get("arguments") or {})
        else:
            return _error(message_id, -32601, f"Unsupported method: {method}")
        return {"jsonrpc": "2.0", "id": message_id, "result": result}
    except Exception as exc:  # pragma: no cover - MCP host integration path
        return _error(message_id, -32000, str(exc))


def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name != "search_knowledge_base":
        raise ValueError(f"Unknown tool: {name}")
    query = str(arguments.get("query", "")).strip()
    top_k = int(arguments.get("top_k", 4))
    if not query:
        raise ValueError("query is required")
    state = build_agent().run(query, top_k=max(1, min(top_k, 8)))
    payload = {
        "answer": state.answer,
        "provider": state.provider,
        "elapsed_ms": state.elapsed_ms,
        "sources": [
            {
                "chunk_id": item.chunk.chunk_id,
                "title": item.chunk.title,
                "score": round(item.score, 4),
                "path": item.chunk.metadata.get("path"),
                "text": item.chunk.text[:800],
            }
            for item in state.evidence
        ],
    }
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False, indent=2),
            }
        ],
        "isError": False,
    }


def _error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def _read_message() -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in {b"\r\n", b"\n"}:
            break
        key, _, value = line.decode("ascii").partition(":")
        headers[key.lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    body = sys.stdin.buffer.read(length)
    return json.loads(body.decode("utf-8"))


def _write_message(message: dict[str, Any]) -> None:
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
