from pathlib import Path

from app.agent.graph import EduRagAgent
from app.agent.tools import build_tool_registry
from app.core.logging import JsonlInteractionLogger
from app.rag.loader import load_documents
from app.rag.retriever import KnowledgeBaseRetriever
from app.rag.splitter import split_documents
from app.rag.vectorstore import LocalVectorStore


def test_local_rag_pipeline_answers_from_knowledge_base(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "course.md").write_text(
        "CS599 期末大作业最终提交截止时间是 2026 年 6 月 22 日 23:00。"
        "如果是 Private Repository，必须添加 qxr777 为 Collaborator。",
        encoding="utf-8",
    )

    documents = load_documents(raw_dir)
    chunks = split_documents(documents)
    store_path = tmp_path / "vectorstore.json"
    store = LocalVectorStore(store_path)
    store.build(chunks)
    store.save()

    retriever = KnowledgeBaseRetriever(store_path)
    tools = build_tool_registry(retriever)
    logger = JsonlInteractionLogger(tmp_path / "logs.jsonl")
    agent = EduRagAgent(tools=tools, logger=logger)

    state = agent.run("Private 仓库需要添加谁？")

    assert "qxr777" in state.answer
    assert state.evidence
    assert state.provider == "local-extractive"


def test_vectorstore_returns_relevant_chunk(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "a.md").write_text("报告 PDF 必须包含可用的导航窗格。", encoding="utf-8")
    (raw_dir / "b.md").write_text("系统需要使用环境变量管理 API Key。", encoding="utf-8")

    chunks = split_documents(load_documents(raw_dir))
    store = LocalVectorStore(tmp_path / "store.json")
    store.build(chunks)

    results = store.search("PDF 导航窗格", top_k=1)

    assert results
    assert "导航窗格" in results[0].chunk.text

