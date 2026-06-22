from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

from app.agent.tools import ToolRegistry
from app.core.logging import JsonlInteractionLogger
from app.llm.provider import GeneratedAnswer, LocalExtractiveGenerator, OpenAICompatibleGenerator
from app.rag.document import RetrievalResult


AgentStep = Literal["plan", "retrieve", "act", "answer", "observe", "done"]


@dataclass
class AgentState:
    question: str
    top_k: int = 4
    history: list[dict[str, str]] = field(default_factory=list)
    retrieval_query: str = ""
    step: AgentStep = "plan"
    selected_tool: str | None = None
    evidence: list[RetrievalResult] = field(default_factory=list)
    answer: str = ""
    provider: str = ""
    elapsed_ms: int = 0
    user_id: int | None = None
    tool_arguments: dict[str, object] = field(default_factory=dict)
    tool_results: list[dict[str, object]] = field(default_factory=list)
    tool_plan_provider: str = "local-rules"


class EduRagAgent:
    def __init__(
        self,
        tools: ToolRegistry,
        logger: JsonlInteractionLogger,
        llm_provider: str = "local",
        llm_api_key: str = "",
        llm_base_url: str = "",
        llm_model: str = "",
    ) -> None:
        self.tools = tools
        self.logger = logger
        if llm_provider in {"deepseek", "openai", "openai-compatible"} and llm_api_key:
            self.generator = OpenAICompatibleGenerator(llm_api_key, llm_base_url, llm_model)
        else:
            self.generator = LocalExtractiveGenerator()

    def run(
        self,
        question: str,
        top_k: int = 4,
        history: list[dict[str, str]] | None = None,
        user_id: int | None = None,
    ) -> AgentState:
        started = time.perf_counter()
        state = AgentState(question=question, top_k=top_k, history=history or [], user_id=user_id)

        state = self._plan(state)
        if state.selected_tool == "search_knowledge_base":
            state = self._retrieve(state)
        else:
            state = self._act(state)
        state = self._answer(state)
        state.elapsed_ms = int((time.perf_counter() - started) * 1000)
        self._observe(state)
        state.step = "done"
        return state

    def _plan(self, state: AgentState) -> AgentState:
        intent = self.generator.plan_system_action(state.question, history=state.history)
        if intent:
            state.tool_plan_provider = "llm-router"
        else:
            intent = _parse_service_intent(state.question)
            state.tool_plan_provider = "local-rules" if intent else "rag"
        if intent:
            state.selected_tool = intent["tool"]
            state.tool_arguments = intent["arguments"]
            state.step = "act"
            return state
        state.selected_tool = "search_knowledge_base"
        state.step = "retrieve"
        return state

    def _retrieve(self, state: AgentState) -> AgentState:
        state.retrieval_query = _build_retrieval_query(state.question, state.history)
        state.evidence = self.tools.call(
            state.selected_tool or "search_knowledge_base",
            query=state.retrieval_query,
            top_k=state.top_k,
        )
        state.step = "answer"
        return state

    def _act(self, state: AgentState) -> AgentState:
        arguments = {"user_id": state.user_id, **state.tool_arguments}
        result = self.tools.call(state.selected_tool or "", **arguments)
        state.tool_results.append(
            {
                "tool": state.selected_tool or "",
                "arguments": arguments,
                "result": result,
            }
        )
        state.step = "answer"
        return state

    def _answer(self, state: AgentState) -> AgentState:
        if state.tool_results:
            state.answer = _format_tool_answer(state.tool_results)
            state.provider = "system-tool"
            state.step = "observe"
            return state
        generated: GeneratedAnswer = self.generator.generate(state.question, state.evidence, history=state.history)
        state.answer = generated.text
        state.provider = generated.provider
        state.step = "observe"
        return state

    def _observe(self, state: AgentState) -> None:
        self.logger.write(
            {
                "question": state.question,
                "answer": state.answer,
                "provider": state.provider,
                "elapsed_ms": state.elapsed_ms,
                "history_messages": len(state.history),
                "retrieval_query": state.retrieval_query,
                "sources": [
                    {
                        "chunk_id": item.chunk.chunk_id,
                        "title": item.chunk.title,
                        "score": round(item.score, 4),
                        "path": item.chunk.metadata.get("path"),
                    }
                    for item in state.evidence
                ],
                "tool_results": state.tool_results,
                "tool_plan_provider": state.tool_plan_provider,
            }
        )


def _build_retrieval_query(question: str, history: list[dict[str, str]]) -> str:
    if not history:
        return question
    if _looks_standalone(question):
        return question
    recent = [item for item in history[-6:] if item.get("role") == "user"]
    context = "\n".join(item.get("content", "")[:240] for item in recent)
    return f"{context}\n当前追问：{question}"


def _looks_standalone(question: str) -> bool:
    explicit_topics = [
        "CS599",
        "期末大作业",
        "报告",
        "GitHub",
        "Private",
        "休学",
        "复学",
        "培养计划",
        "预答辩",
        "盲审",
        "国家奖学金",
        "VPN",
        "WebVPN",
        "图书馆",
    ]
    pronouns = ["这个", "那个", "它", "上面", "刚才", "继续", "还有", "这些", "前面"]
    return any(topic in question for topic in explicit_topics) and not any(word in question for word in pronouns)


def _parse_service_intent(question: str) -> dict[str, object] | None:
    text = question.strip()
    if not _mentions_service_request(text):
        return None
    request_id = _extract_request_id(text)
    if request_id and any(word in text for word in ["完成", "办完", "已办", "关闭"]):
        return {"tool": "update_service_request", "arguments": {"request_id": request_id, "status": "done"}}
    if request_id and any(word in text for word in ["取消", "作废", "撤销", "删除"]):
        return {"tool": "update_service_request", "arguments": {"request_id": request_id, "status": "cancelled"}}
    if any(word in text for word in ["查看", "列出", "查询", "有哪些", "我的", "全部"]):
        status = "all" if "全部" in text else "open"
        if any(word in text for word in ["已完成", "完成的", "办完"]):
            status = "done"
        if any(word in text for word in ["已取消", "取消的", "作废"]):
            status = "cancelled"
        return {"tool": "list_service_requests", "arguments": {"status": status, "limit": 20}}
    if any(word in text for word in ["创建", "新增", "添加", "记录", "提醒", "帮我办", "帮我创建", "帮我记录"]):
        title = _extract_title(text)
        return {
            "tool": "create_service_request",
            "arguments": {
                "title": title,
                "category": _infer_category(text),
                "details": text,
                "priority": _infer_priority(text),
                "due_date": _infer_due_date(text),
            },
        }
    return None


def _mentions_service_request(text: str) -> bool:
    return any(word in text for word in ["待办", "代办", "办事", "工单", "申请", "提醒", "任务", "记录", "事项"])


def _extract_request_id(text: str) -> int | None:
    match = re.search(r"(?:#|编号|ID|id)?\s*(\d+)", text)
    if not match:
        return None
    return int(match.group(1))


def _extract_title(text: str) -> str:
    for marker in ["：", ":", "为", "是"]:
        if marker in text:
            candidate = text.split(marker, 1)[1].strip()
            if candidate:
                return _strip_action_words(candidate)
    return _strip_action_words(text)


def _strip_action_words(text: str) -> str:
    cleaned = text
    for word in ["帮我", "创建", "新增", "添加", "记录", "提醒", "一个", "一条", "待办", "代办", "办事", "工单", "任务", "申请", "事项"]:
        cleaned = cleaned.replace(word, "")
    return cleaned.strip(" ，。；;")[:120] or "未命名办事记录"


def _infer_category(text: str) -> str:
    rules = [
        ("学籍与培养", ["休学", "复学", "学籍", "培养计划", "选课", "考试"]),
        ("论文与学位", ["论文", "开题", "中期", "预答辩", "盲审", "答辩", "学位"]),
        ("奖助与就业", ["奖学金", "助学金", "助教", "就业", "困难补助"]),
        ("校园服务", ["VPN", "WebVPN", "图书馆", "宿舍", "财务", "档案", "邮箱", "一卡通"]),
        ("课程项目", ["CS599", "作业", "报告", "GitHub", "项目"]),
    ]
    for category, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return category
    return "综合办事"


def _infer_priority(text: str) -> str:
    if any(word in text for word in ["紧急", "非常紧急", "高优先级", "尽快", "今天"]):
        return "high"
    if any(word in text for word in ["不急", "低优先级", "有空"]):
        return "low"
    return "normal"


def _infer_due_date(text: str) -> str | None:
    match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return date(year, month, day).isoformat()
    today = date.today()
    if "今天" in text:
        return today.isoformat()
    if "明天" in text:
        return (today + timedelta(days=1)).isoformat()
    if "后天" in text:
        return (today + timedelta(days=2)).isoformat()
    return None


def _format_tool_answer(tool_results: list[dict[str, object]]) -> str:
    result = tool_results[-1].get("result")
    if not isinstance(result, dict):
        return "系统工具已执行，但返回结果格式无法展示。"
    if not result.get("ok"):
        return f"系统工具调用失败：{result.get('error', 'unknown error')}"
    action = result.get("action")
    if action == "created":
        return _format_request_item("已创建办事记录", result.get("item"))
    if action == "updated":
        return _format_request_item("已更新办事记录", result.get("item"))
    if action == "listed":
        items = result.get("items") or []
        if not items:
            return "当前没有匹配的办事记录。"
        lines = ["你的办事记录："]
        for item in items:
            if isinstance(item, dict):
                lines.append(_format_request_line(item))
        return "\n".join(lines)
    return "系统工具已执行。"


def _format_request_item(prefix: str, item: object) -> str:
    if not isinstance(item, dict):
        return prefix
    return f"{prefix}：\n{_format_request_line(item)}"


def _format_request_line(item: dict[str, object]) -> str:
    due_date = item.get("due_date") or "未设置截止日期"
    return (
        f"#{item.get('id')} [{item.get('status')}] {item.get('title')} "
        f"| 分类：{item.get('category')} | 优先级：{item.get('priority')} | 截止：{due_date}"
    )
