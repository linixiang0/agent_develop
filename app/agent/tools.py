from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.core.db import AppStore
from app.rag.document import RetrievalResult
from app.rag.retriever import KnowledgeBaseRetriever


ToolFunction = Callable[..., Any]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    function: ToolFunction


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def call(self, name: str, **kwargs: Any) -> Any:
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        return self._tools[name].function(**kwargs)

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in self._tools.values()
        ]


def build_tool_registry(retriever: KnowledgeBaseRetriever, store: AppStore | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    app_store = store or AppStore()

    def search_knowledge_base(query: str, top_k: int = 4) -> list[RetrievalResult]:
        return retriever.retrieve(query, top_k=top_k)

    def create_service_request(
        user_id: int | None,
        title: str,
        category: str = "综合办事",
        details: str = "",
        priority: str = "normal",
        due_date: str | None = None,
    ) -> dict[str, Any]:
        if user_id is None:
            return {"ok": False, "error": "Login is required for database actions."}
        item = app_store.create_service_request(
            user_id=user_id,
            title=title,
            category=category,
            details=details,
            priority=priority,
            due_date=due_date,
        )
        return {"ok": True, "action": "created", "item": item}

    def list_service_requests(user_id: int | None, status: str = "open", limit: int = 20) -> dict[str, Any]:
        if user_id is None:
            return {"ok": False, "error": "Login is required for database actions."}
        items = app_store.list_service_requests(user_id=user_id, status=status, limit=limit)
        return {"ok": True, "action": "listed", "status": status, "items": items}

    def update_service_request(user_id: int | None, request_id: int, status: str) -> dict[str, Any]:
        if user_id is None:
            return {"ok": False, "error": "Login is required for database actions."}
        item = app_store.update_service_request_status(user_id=user_id, request_id=request_id, status=status)
        if not item:
            return {"ok": False, "error": f"Service request #{request_id} was not found."}
        return {"ok": True, "action": "updated", "item": item}

    registry.register(
        Tool(
            name="search_knowledge_base",
            description="Search course, academic affairs, and CS599 project documents.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "User question or rewritten search query."},
                    "top_k": {"type": "integer", "description": "Maximum number of evidence chunks."},
                },
                "required": ["query"],
            },
            function=search_knowledge_base,
        )
    )
    registry.register(
        Tool(
            name="create_service_request",
            description="Create a user-owned campus service request or todo item in the system database.",
            parameters={
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer"},
                    "title": {"type": "string"},
                    "category": {"type": "string"},
                    "details": {"type": "string"},
                    "priority": {"type": "string", "enum": ["low", "normal", "high"]},
                    "due_date": {"type": "string", "description": "Optional ISO date, yyyy-mm-dd."},
                },
                "required": ["user_id", "title"],
            },
            function=create_service_request,
        )
    )
    registry.register(
        Tool(
            name="list_service_requests",
            description="List the current user's service requests or todo items from the system database.",
            parameters={
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer"},
                    "status": {"type": "string", "enum": ["open", "done", "cancelled", "all"]},
                    "limit": {"type": "integer"},
                },
                "required": ["user_id"],
            },
            function=list_service_requests,
        )
    )
    registry.register(
        Tool(
            name="update_service_request",
            description="Update a user-owned service request status in the system database.",
            parameters={
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer"},
                    "request_id": {"type": "integer"},
                    "status": {"type": "string", "enum": ["open", "done", "cancelled"]},
                },
                "required": ["user_id", "request_id", "status"],
            },
            function=update_service_request,
        )
    )
    return registry
