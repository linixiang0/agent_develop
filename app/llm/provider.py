from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.rag.document import RetrievalResult
from app.rag.embeddings import tokenize


@dataclass(frozen=True)
class GeneratedAnswer:
    text: str
    provider: str


class LocalExtractiveGenerator:
    provider = "local-extractive"

    def plan_system_action(self, question: str, history: list[dict[str, str]] | None = None) -> dict[str, Any] | None:
        return None

    def generate(
        self,
        question: str,
        evidence: list[RetrievalResult],
        history: list[dict[str, str]] | None = None,
    ) -> GeneratedAnswer:
        if not evidence:
            return GeneratedAnswer(
                text="知识库中没有检索到足够相关的资料。请补充课程通知、培养方案或教务服务文件后重新构建知识库。",
                provider=self.provider,
            )

        direct_answer = _direct_extract(question, evidence)
        if direct_answer:
            return GeneratedAnswer(
                text=f"根据当前知识库，结论如下：\n{direct_answer}\n\n来源：资料1",
                provider=self.provider,
            )

        top_score = evidence[0].score
        selected = [item for item in evidence if item.score >= max(0.18, top_score * 0.92)][:2]
        if not selected:
            selected = evidence[:1]

        lines = ["根据当前知识库，结论如下："]
        for index, item in enumerate(selected, start=1):
            lines.append(f"{index}. {_best_snippet(question, item.chunk.text, limit=260)}")
        lines.append("")
        lines.append("来源：" + "、".join(f"资料{index}" for index, _ in enumerate(selected, start=1)))
        return GeneratedAnswer(text="\n".join(lines), provider=self.provider)


class OpenAICompatibleGenerator:
    provider = "openai-compatible"

    def __init__(self, api_key: str, base_url: str, model: str, timeout: int = 30) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def generate(
        self,
        question: str,
        evidence: list[RetrievalResult],
        history: list[dict[str, str]] | None = None,
    ) -> GeneratedAnswer:
        if not self.api_key:
            return LocalExtractiveGenerator().generate(question, evidence, history=history)

        context = "\n\n".join(
            f"资料{index}\n标题：{item.chunk.title}\n内容：{item.chunk.text}"
            for index, item in enumerate(evidence, start=1)
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "你是研究生教务与课程资料问答 Agent。"
                    "你可以利用历史对话理解代词和追问，但事实依据必须来自本轮给定证据。"
                    "若证据不足，明确说明缺少哪些资料。"
                    "答案末尾用“来源：资料1、资料2”的格式列出依据。"
                    "不要输出内部 chunk_id，不要使用 [1] 这种裸编号。"
                ),
            }
        ]
        for item in history or []:
            if item.get("role") in {"user", "assistant"}:
                messages.append({"role": item["role"], "content": item.get("content", "")})
        messages.append({"role": "user", "content": f"问题：{question}\n\n本轮检索证据：\n{context}"})

        payload = {"model": self.model, "messages": messages, "temperature": 0.2}
        request = urllib.request.Request(
            url=f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
            fallback = LocalExtractiveGenerator().generate(question, evidence, history=history)
            return GeneratedAnswer(text=f"{fallback.text}\n\nLLM 调用失败，已使用本地模式：{exc}", provider=f"{self.provider}-fallback")

        return GeneratedAnswer(text=body["choices"][0]["message"]["content"], provider=self.provider)

    def plan_system_action(self, question: str, history: list[dict[str, str]] | None = None) -> dict[str, Any] | None:
        if not self.api_key:
            return None
        messages = [
            {
                "role": "system",
                "content": (
                    "你是系统工具路由器，只判断用户是否要操作系统数据库。"
                    "只能返回 JSON，不要输出解释。"
                    "可用工具："
                    "1. create_service_request：创建用户待办、代办、提醒、办事记录、任务、事项。"
                    "2. list_service_requests：查看、查询、列出用户待办、代办、办事记录。"
                    "3. update_service_request：完成、取消、撤销、重新打开指定编号的记录。"
                    "4. search_knowledge_base：普通知识库问答。"
                    "如果用户只是问政策、流程、课程资料，返回 search_knowledge_base。"
                    "字段要求：tool 必填；arguments 是对象。"
                    "create_service_request.arguments 包含 title, category, details, priority, due_date。"
                    "priority 只能是 low、normal、high；due_date 用 yyyy-mm-dd，不确定则 null。"
                    "category 从 课程项目、学籍与培养、论文与学位、奖助与就业、校园服务、综合办事 中选。"
                    "list_service_requests.arguments 包含 status: open/done/cancelled/all, limit。"
                    "update_service_request.arguments 包含 request_id 和 status: open/done/cancelled。"
                    f"今天日期是 {date.today().isoformat()}。"
                ),
            }
        ]
        for item in (history or [])[-6:]:
            if item.get("role") in {"user", "assistant"}:
                messages.append({"role": item["role"], "content": item.get("content", "")[:500]})
        messages.append(
            {
                "role": "user",
                "content": (
                    "请判断这句话是否需要调用系统工具，并返回 JSON："
                    f"{question}\n"
                    "返回示例："
                    '{"tool":"create_service_request","arguments":{"title":"后天期末考试","category":"课程项目",'
                    '"details":"后天期末考试，非常紧急","priority":"high","due_date":"2026-06-21"}}'
                ),
            }
        )
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            url=f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=min(self.timeout, 10)) as response:
                body = json.loads(response.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            parsed = json.loads(_extract_json_object(content))
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError, TypeError, ValueError):
            return None
        return _normalize_tool_plan(parsed)


def _compact(text: str, limit: int) -> str:
    normalized = " ".join(_clean_evidence_text(text).split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _extract_json_object(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    match = re.search(r"\{.*\}", stripped, flags=re.S)
    if not match:
        raise ValueError("No JSON object found")
    return match.group(0)


def _normalize_tool_plan(parsed: dict[str, Any]) -> dict[str, Any] | None:
    tool = str(parsed.get("tool", "")).strip()
    if tool == "search_knowledge_base":
        return None
    if tool not in {"create_service_request", "list_service_requests", "update_service_request"}:
        return None
    arguments = parsed.get("arguments")
    if not isinstance(arguments, dict):
        arguments = {}
    if tool == "create_service_request":
        title = str(arguments.get("title") or "").strip()
        if not title:
            return None
        return {
            "tool": tool,
            "arguments": {
                "title": title[:120],
                "category": _normalize_category(arguments.get("category")),
                "details": str(arguments.get("details") or title).strip()[:2000],
                "priority": _normalize_priority(arguments.get("priority")),
                "due_date": _normalize_optional_text(arguments.get("due_date")),
            },
        }
    if tool == "list_service_requests":
        return {
            "tool": tool,
            "arguments": {
                "status": _normalize_status(arguments.get("status"), default="open", allow_open=True),
                "limit": _normalize_limit(arguments.get("limit")),
            },
        }
    request_id = _normalize_int(arguments.get("request_id"))
    if request_id is None:
        return None
    return {
        "tool": tool,
        "arguments": {
            "request_id": request_id,
            "status": _normalize_status(arguments.get("status"), default="done", allow_open=True),
        },
    }


def _normalize_category(value: object) -> str:
    category = str(value or "").strip()
    allowed = {"课程项目", "学籍与培养", "论文与学位", "奖助与就业", "校园服务", "综合办事"}
    return category if category in allowed else "综合办事"


def _normalize_priority(value: object) -> str:
    priority = str(value or "").strip()
    return priority if priority in {"low", "normal", "high"} else "normal"


def _normalize_status(value: object, default: str, allow_open: bool = False) -> str:
    status = str(value or "").strip()
    allowed = {"done", "cancelled", "all"}
    if allow_open:
        allowed.add("open")
    return status if status in allowed else default


def _normalize_limit(value: object) -> int:
    parsed = _normalize_int(value)
    if parsed is None:
        return 20
    return max(1, min(parsed, 50))


def _normalize_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "null":
        return None
    return text


def _best_snippet(question: str, text: str, limit: int) -> str:
    query_tokens = set(tokenize(question))
    cleaned = _clean_evidence_text(text)
    sentences = [part.strip() for part in re.split(r"(?<=[。！？.!?])\s+|\n+", cleaned) if part.strip()]
    if not sentences:
        return _compact(text, limit=limit)

    def score(sentence: str) -> int:
        sentence_tokens = set(tokenize(sentence))
        return len(query_tokens.intersection(sentence_tokens))

    ranked = sorted(sentences, key=score, reverse=True)
    chosen: list[str] = []
    total = 0
    for sentence in ranked:
        if score(sentence) == 0 and chosen:
            continue
        if len(chosen) >= 2:
            break
        if total + len(sentence) > limit and chosen:
            break
        chosen.append(sentence)
        total += len(sentence)
        if total >= limit * 0.7:
            break
    return _compact(" ".join(chosen or sentences[:1]), limit=limit)


def _clean_evidence_text(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("## KB-") or stripped.startswith("## REAL-"):
            continue
        if stripped == "## 公开来源链接":
            break
        lines.append(stripped)
    cleaned = " ".join(lines)
    cleaned = re.sub(r"\s*##\s*(KB|REAL)-\d+[^。！？.!?]*", "", cleaned)
    cleaned = cleaned.replace("## ", "")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _direct_extract(question: str, evidence: list[RetrievalResult]) -> str:
    text = evidence[0].chunk.text
    lines = [line.strip() for line in text.splitlines()]
    if "CS599" in question and "截止" in question:
        for line in lines:
            if line.startswith("最终提交截止"):
                return line
    if "CS599" in question and "加分" in question:
        answer_lines: list[str] = []
        collecting = False
        for line in lines:
            if line == "加分项包括：":
                collecting = True
                answer_lines.append(line)
                continue
            if collecting:
                if not line:
                    continue
                if not line.startswith("- "):
                    break
                answer_lines.append(line)
        if len(answer_lines) > 1:
            return "\n".join(answer_lines)
    return ""
