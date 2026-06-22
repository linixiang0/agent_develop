from pathlib import Path

from app.agent.graph import EduRagAgent
from app.agent.tools import build_tool_registry
from app.core.db import AppStore
from app.core.logging import JsonlInteractionLogger


class DummyRetriever:
    def retrieve(self, query: str, top_k: int = 4) -> list:
        return []


class FakeToolPlanner:
    def plan_system_action(self, question: str, history: list[dict[str, str]] | None = None) -> dict:
        return {
            "tool": "create_service_request",
            "arguments": {
                "title": "后天期末考试",
                "category": "课程项目",
                "details": question,
                "priority": "high",
                "due_date": None,
            },
        }

    def generate(self, question: str, evidence: list, history: list[dict[str, str]] | None = None):
        raise AssertionError("system action should not call answer generation")


def test_agent_can_create_list_and_complete_service_request(tmp_path: Path) -> None:
    store = AppStore(tmp_path / "app.sqlite")
    user = store.register("alice", "password123")
    tools = build_tool_registry(DummyRetriever(), store=store)
    agent = EduRagAgent(tools=tools, logger=JsonlInteractionLogger(tmp_path / "logs.jsonl"))

    created = agent.run("帮我创建一条待办：明天提交开题报告，紧急", user_id=user.id)

    assert created.provider == "system-tool"
    assert "已创建办事记录" in created.answer
    assert "开题报告" in created.answer
    rows = store.list_service_requests(user.id)
    assert len(rows) == 1
    assert rows[0]["status"] == "open"
    assert rows[0]["priority"] == "high"

    listed = agent.run("查看我的待办", user_id=user.id)

    assert "#1" in listed.answer
    assert "开题报告" in listed.answer

    completed = agent.run("完成待办 1", user_id=user.id)

    assert "已更新办事记录" in completed.answer
    assert store.list_service_requests(user.id, status="done")[0]["status"] == "done"


def test_agent_local_fallback_accepts_daiban_typo(tmp_path: Path) -> None:
    store = AppStore(tmp_path / "app.sqlite")
    user = store.register("alice", "password123")
    tools = build_tool_registry(DummyRetriever(), store=store)
    agent = EduRagAgent(tools=tools, logger=JsonlInteractionLogger(tmp_path / "logs.jsonl"))

    state = agent.run("帮我创建一条代办：后天期末考试，非常紧急", user_id=user.id)

    rows = store.list_service_requests(user.id)
    assert state.provider == "system-tool"
    assert rows[0]["title"] == "后天期末考试，非常紧急"
    assert rows[0]["priority"] == "high"


def test_agent_uses_llm_tool_plan_before_keyword_rules(tmp_path: Path) -> None:
    store = AppStore(tmp_path / "app.sqlite")
    user = store.register("bob", "password123")
    tools = build_tool_registry(DummyRetriever(), store=store)
    agent = EduRagAgent(tools=tools, logger=JsonlInteractionLogger(tmp_path / "logs.jsonl"))
    agent.generator = FakeToolPlanner()

    state = agent.run("后天期末考试，非常紧急", user_id=user.id)

    rows = store.list_service_requests(user.id)
    assert state.provider == "system-tool"
    assert state.tool_plan_provider == "llm-router"
    assert rows[0]["title"] == "后天期末考试"
