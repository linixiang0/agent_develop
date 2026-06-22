from pathlib import Path

from app import mcp_server
from app.agent.graph import EduRagAgent
from app.agent.tools import build_tool_registry
from app.core.logging import JsonlInteractionLogger
from app.rag.loader import load_documents
from app.rag.retriever import KnowledgeBaseRetriever
from app.rag.splitter import split_documents
from app.rag.vectorstore import LocalVectorStore


def test_mcp_lists_search_tool() -> None:
    response = mcp_server._handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert response is not None
    assert response["result"]["tools"][0]["name"] == "search_knowledge_base"


def test_mcp_tool_call_returns_answer(monkeypatch, tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "course.md").write_text("VPN 用于校外访问学校授权资源，不应共享账号。", encoding="utf-8")
    chunks = split_documents(load_documents(raw_dir))
    store = LocalVectorStore(tmp_path / "vectorstore.json")
    store.build(chunks)
    store.save()

    retriever = KnowledgeBaseRetriever(tmp_path / "vectorstore.json")
    tools = build_tool_registry(retriever)
    agent = EduRagAgent(tools=tools, logger=JsonlInteractionLogger(tmp_path / "logs.jsonl"))
    monkeypatch.setattr(mcp_server, "build_agent", lambda: agent)

    response = mcp_server._handle_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "search_knowledge_base",
                "arguments": {"query": "校外访问资源可以共享 VPN 账号吗？", "top_k": 2},
            },
        }
    )

    assert response is not None
    text = response["result"]["content"][0]["text"]
    assert "VPN" in text
    assert "共享账号" in text
