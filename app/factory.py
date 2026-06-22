from __future__ import annotations

from app.agent.graph import EduRagAgent
from app.agent.tools import build_tool_registry
from app.core.config import settings
from app.core.db import AppStore
from app.core.logging import JsonlInteractionLogger
from app.rag.retriever import KnowledgeBaseRetriever


def build_agent(store: AppStore | None = None) -> EduRagAgent:
    retriever = KnowledgeBaseRetriever(settings.vectorstore_path)
    tools = build_tool_registry(retriever, store=store)
    logger = JsonlInteractionLogger(settings.log_path)
    return EduRagAgent(
        tools=tools,
        logger=logger,
        llm_provider=settings.llm_provider,
        llm_api_key=settings.llm_api_key,
        llm_base_url=settings.llm_base_url,
        llm_model=settings.llm_model,
    )
