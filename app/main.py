from __future__ import annotations

import re
from collections import Counter
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.db import AppStore, User
from app.factory import build_agent
from app.rag.retriever import KnowledgeBaseRetriever

try:
    from fastapi import Cookie, FastAPI, HTTPException, Response
    from fastapi.responses import HTMLResponse
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("FastAPI is required. Run: pip install -r requirements.txt") from exc


app = FastAPI(title=settings.app_name, version="0.3.1")
store = AppStore()


class AuthRequest(BaseModel):
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)


class UserResponse(BaseModel):
    id: int
    username: str


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: int = Field(default=4, ge=1, le=8)
    conversation_id: int | None = None


class SourceResponse(BaseModel):
    ref: str
    chunk_id: str
    category: str
    source_type: str
    display_title: str
    title: str
    score: float
    path: str | None = None
    text: str


class AskResponse(BaseModel):
    conversation_id: int
    question: str
    answer: str
    provider: str
    elapsed_ms: int
    history_messages: int
    sources: list[SourceResponse]
    action_results: list[dict[str, Any]] = Field(default_factory=list)


class StatsResponse(BaseModel):
    app: str
    llm_provider: str
    llm_model: str
    api_mode: str
    chunk_count: int
    source_count: int
    categories: list[dict[str, int | str]]


class KnowledgeItem(BaseModel):
    id: str
    ref: str
    category: str
    source_type: str
    title: str
    text: str


class KnowledgeDetail(BaseModel):
    id: str
    category: str
    source_type: str
    title: str
    source_title: str
    path: str | None
    text: str


class KnowledgeListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[KnowledgeItem]


class ServiceRequestCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    category: str = Field(default="综合办事", max_length=40)
    details: str = Field(default="", max_length=2000)
    priority: str = Field(default="normal")
    due_date: str | None = None


class ServiceRequestUpdate(BaseModel):
    status: str = Field(..., pattern="^(open|done|cancelled)$")


class ServiceRequestResponse(BaseModel):
    id: int
    user_id: int
    category: str
    title: str
    details: str
    status: str
    priority: str
    due_date: str | None
    created_at: str
    updated_at: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


@app.post("/api/register", response_model=UserResponse)
def register(request: AuthRequest, response: Response) -> UserResponse:
    try:
        user = store.register(request.username, request.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_session_cookie(response, user)
    return UserResponse(id=user.id, username=user.username)


@app.post("/api/login", response_model=UserResponse)
def login(request: AuthRequest, response: Response) -> UserResponse:
    user = store.authenticate(request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    _set_session_cookie(response, user)
    return UserResponse(id=user.id, username=user.username)


@app.post("/api/logout")
def logout(response: Response, session_id: str | None = Cookie(default=None)) -> dict[str, str]:
    if session_id:
        store.delete_session(session_id)
    response.delete_cookie("session_id")
    return {"status": "ok"}


@app.get("/api/me", response_model=UserResponse)
def me(session_id: str | None = Cookie(default=None)) -> UserResponse:
    user = _require_user(session_id)
    return UserResponse(id=user.id, username=user.username)


@app.get("/api/stats", response_model=StatsResponse)
def stats() -> StatsResponse:
    chunks = _chunks()
    titles = sorted({chunk.title for chunk in chunks})
    categories = Counter(_source_category(chunk.title) for chunk in chunks)
    api_mode = "DeepSeek API" if settings.llm_provider == "deepseek" and bool(settings.llm_api_key) else "Local Extractive"
    return StatsResponse(
        app=settings.app_name,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        api_mode=api_mode,
        chunk_count=len(chunks),
        source_count=len(titles),
        categories=[{"name": name, "count": categories[name]} for name in _ordered_categories(categories)],
    )


@app.get("/api/knowledge", response_model=KnowledgeListResponse)
def knowledge(category: str = "", q: str = "", page: int = 1, page_size: int = 12) -> KnowledgeListResponse:
    keyword = q.strip().lower()
    filtered = []
    for chunk in _chunks():
        item_category = _source_category(chunk.title)
        item_title = _display_title(chunk.title)
        item_text = _clean_source_text(chunk.text)
        if category and item_category != category:
            continue
        if keyword and keyword not in (item_title + item_text).lower():
            continue
        filtered.append((chunk, item_category, item_title, item_text))
    page = max(page, 1)
    page_size = min(max(page_size, 1), 50)
    start = (page - 1) * page_size
    selected = filtered[start : start + page_size]
    return KnowledgeListResponse(
        total=len(filtered),
        page=page,
        page_size=page_size,
        items=[
            KnowledgeItem(
                id=chunk.chunk_id,
                ref=f"资料{start + index}",
                category=item_category,
                source_type=_source_type(chunk),
                title=item_title,
                text=item_text,
            )
            for index, (chunk, item_category, item_title, item_text) in enumerate(selected, start=1)
        ],
    )


@app.get("/api/knowledge/{chunk_id}", response_model=KnowledgeDetail)
def knowledge_detail(chunk_id: str) -> KnowledgeDetail:
    for chunk in _chunks():
        if chunk.chunk_id == chunk_id:
            return KnowledgeDetail(
                id=chunk.chunk_id,
                category=_source_category(chunk.title),
                source_type=_source_type(chunk),
                title=_display_title(chunk.title),
                source_title=chunk.title,
                path=chunk.metadata.get("path"),
                text=_clean_source_text(chunk.text),
            )
    raise HTTPException(status_code=404, detail="Knowledge item not found")


@app.get("/api/conversations")
def conversations(session_id: str | None = Cookie(default=None)) -> list[dict[str, Any]]:
    user = _require_user(session_id)
    return store.list_conversations(user.id)


@app.post("/api/conversations")
def create_conversation(session_id: str | None = Cookie(default=None)) -> dict[str, int]:
    user = _require_user(session_id)
    conversation_id = store.create_conversation(user.id, "\u65b0\u7684\u95ee\u7b54")
    return {"conversation_id": conversation_id}


@app.get("/api/conversations/{conversation_id}/messages")
def messages(conversation_id: int, session_id: str | None = Cookie(default=None)) -> list[dict[str, Any]]:
    user = _require_user(session_id)
    if not store.get_conversation(user.id, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return store.messages(user.id, conversation_id)


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, session_id: str | None = Cookie(default=None)) -> dict[str, str]:
    user = _require_user(session_id)
    if not store.delete_conversation(user.id, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "ok"}


@app.delete("/api/conversations/{conversation_id}/messages")
def clear_conversation_messages(conversation_id: int, session_id: str | None = Cookie(default=None)) -> dict[str, str]:
    user = _require_user(session_id)
    if not store.clear_conversation_messages(user.id, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "ok"}


@app.get("/api/service-requests", response_model=list[ServiceRequestResponse])
def service_requests(status: str = "open", session_id: str | None = Cookie(default=None)) -> list[ServiceRequestResponse]:
    user = _require_user(session_id)
    return [ServiceRequestResponse(**item) for item in store.list_service_requests(user.id, status=status)]


@app.post("/api/service-requests", response_model=ServiceRequestResponse)
def create_service_request(
    request: ServiceRequestCreate,
    session_id: str | None = Cookie(default=None),
) -> ServiceRequestResponse:
    user = _require_user(session_id)
    if request.priority not in {"low", "normal", "high"}:
        raise HTTPException(status_code=400, detail="priority must be low, normal, or high")
    item = store.create_service_request(
        user_id=user.id,
        title=request.title,
        category=request.category,
        details=request.details,
        priority=request.priority,
        due_date=request.due_date,
    )
    return ServiceRequestResponse(**item)


@app.patch("/api/service-requests/{request_id}", response_model=ServiceRequestResponse)
def update_service_request(
    request_id: int,
    request: ServiceRequestUpdate,
    session_id: str | None = Cookie(default=None),
) -> ServiceRequestResponse:
    user = _require_user(session_id)
    item = store.update_service_request_status(user.id, request_id, request.status)
    if not item:
        raise HTTPException(status_code=404, detail="Service request not found")
    return ServiceRequestResponse(**item)


@app.post("/api/ask", response_model=AskResponse)
def ask(request: AskRequest, session_id: str | None = Cookie(default=None)) -> AskResponse:
    user = _require_user(session_id)
    conversation_id = request.conversation_id
    if conversation_id is None:
        conversation_id = store.create_conversation(user.id, request.question[:40])
    elif not store.get_conversation(user.id, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    history = store.context_messages(user.id, conversation_id)
    state = build_agent(store=store).run(request.question, top_k=request.top_k, history=history, user_id=user.id)
    sources = [
        SourceResponse(
            ref=f"资料{index}",
            chunk_id=item.chunk.chunk_id,
            category=_source_category(item.chunk.title),
            source_type=_source_type(item.chunk),
            display_title=_display_title(item.chunk.title),
            title=item.chunk.title,
            score=item.score,
            path=item.chunk.metadata.get("path"),
            text=_clean_source_text(item.chunk.text),
        )
        for index, item in enumerate(state.evidence, start=1)
    ]
    source_dicts = [source.model_dump() for source in sources]
    store.add_message(conversation_id, "user", request.question)
    store.add_message(conversation_id, "assistant", state.answer, provider=state.provider, sources=source_dicts)
    for action in state.tool_results:
        result = action.get("result")
        store.log_agent_action(
            user_id=user.id,
            conversation_id=conversation_id,
            tool_name=str(action.get("tool", "")),
            arguments=dict(action.get("arguments") or {}),
            result=result if isinstance(result, dict) else {"value": result},
        )
    return AskResponse(
        conversation_id=conversation_id,
        question=state.question,
        answer=state.answer,
        provider=state.provider,
        elapsed_ms=state.elapsed_ms,
        history_messages=len(history),
        sources=sources,
        action_results=state.tool_results,
    )


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTML


def _chunks():
    retriever = KnowledgeBaseRetriever(settings.vectorstore_path)
    return retriever.vectorstore.chunks


def _ordered_categories(categories: Counter[str]) -> list[str]:
    preferred = ["课程项目", "学籍与培养", "论文与学位", "奖助与就业", "校园服务", "科研与规范", "综合办事"]
    ordered = [name for name in preferred if name in categories]
    ordered.extend(name for name, _ in categories.most_common() if name not in ordered)
    return ordered


def _set_session_cookie(response: Response, user: User) -> None:
    token = store.create_session(user.id)
    response.set_cookie("session_id", token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7)


def _require_user(session_id: str | None) -> User:
    user = store.user_by_session(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Login required")
    return user


def _source_category(title: str) -> str:
    heading = title.split(" / ", 1)[1] if " / " in title else title
    cleaned = re.sub(r"^(KB|REAL)-\d{4}\s*", "", heading).strip()
    if cleaned == "公开来源链接":
        return "综合办事"
    return _major_category(cleaned)


def _major_category(cleaned: str) -> str:
    rules = [
        ("课程项目", ["CS599", "项目方向", "核心技术要素", "仓库", "报告", "评分", "时间节点", "课程项目", "真实资料", "合成资料"]),
        ("学籍与培养", ["学籍", "注册报到", "培养计划", "课程管理", "课程考试", "开题", "中期考核", "专业培养方案"]),
        ("论文与学位", ["学位论文", "学位申请", "论文", "预答辩", "盲审", "答辩", "归档"]),
        ("奖助与就业", ["奖助管理", "奖学金", "助教", "困难补助", "就业服务"]),
        ("校园服务", ["服务窗口", "信息化服务", "信息服务", "图书馆服务", "档案户口", "证明档案", "财务宿舍", "国际交流", "教学日历"]),
        ("科研与规范", ["学术规范", "实验室安全", "科研训练", "伦理审查", "数据管理", "成果署名"]),
        ("综合办事", ["综合办事", "教务咨询"]),
    ]
    for category, keywords in rules:
        if any(keyword in cleaned for keyword in keywords):
            return category
    if "\uff1a" in cleaned:
        prefix = cleaned.split("\uff1a", 1)[0]
        return prefix if len(prefix) <= 8 else "综合办事"
    return "综合办事"


def _display_title(title: str) -> str:
    heading = title.split(" / ", 1)[1] if " / " in title else title
    return re.sub(r"^(KB|REAL)-\d{4}\s*", "", heading).strip()


def _clean_source_text(text: str) -> str:
    lines = [line for line in text.splitlines() if not line.startswith("## ")]
    return "\n".join(lines).strip()


def _source_type(chunk) -> str:
    path = str(chunk.metadata.get("path", ""))
    title = chunk.title
    if "cs599_course_requirements" in path or "cs599_course_requirements" in title:
        return "课程要求"
    if "real_public_grad_service_knowledge" in path or "real_public_grad_service_knowledge" in title:
        return "公开资料"
    if "synthetic_campus_knowledge" in path or "synthetic_campus_knowledge" in title:
        return "演示数据"
    return "知识片段"


HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>EduRAG-Agent</title>
  <style>
    :root { --bg:#eef2f7; --panel:#fff; --line:#d9e1ec; --text:#172033; --muted:#64748b; --blue:#2563eb; --soft:#f8fafc; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:Arial,"Microsoft YaHei",sans-serif; background:var(--bg); color:var(--text); }
    .auth { min-height:100vh; display:grid; place-items:center; padding:24px; }
    .auth-card { width:min(420px,100%); background:#fff; border:1px solid var(--line); border-radius:10px; padding:28px; box-shadow:0 20px 50px rgba(15,23,42,.12); }
    .auth-card h1 { margin:0 0 8px; font-size:26px; }
    .auth-card p,.hint { color:var(--muted); font-size:13px; }
    .field { display:grid; gap:7px; margin-bottom:14px; font-size:14px; }
    input,textarea,select,button { font-family:inherit; }
    .input,textarea,select { width:100%; border:1px solid #cbd5e1; border-radius:8px; padding:11px 12px; background:#fff; color:var(--text); font-size:15px; }
    .primary { border:0; border-radius:8px; background:var(--blue); color:#fff; padding:10px 16px; cursor:pointer; font-size:14px; }
    .ghost { border:1px solid var(--line); border-radius:8px; background:#fff; color:#24324a; padding:9px 14px; cursor:pointer; font-size:14px; }
    .error { margin-top:12px; color:#b91c1c; font-size:13px; min-height:18px; }
    .app { display:none; }
    .topbar { background:#12213a; color:#fff; border-bottom:1px solid #0c1729; }
    .topbar-inner { max-width:1280px; margin:0 auto; padding:18px 22px; display:flex; align-items:center; justify-content:space-between; gap:18px; }
    .brand { display:flex; align-items:center; gap:12px; }
    .mark { width:38px; height:38px; border-radius:8px; background:#e9f0ff; color:#1d4ed8; display:grid; place-items:center; font-weight:800; }
    h1 { margin:0; font-size:24px; }
    .subtitle { margin:4px 0 0; color:#cbd5e1; font-size:14px; }
    .userbar { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
    .status-pill { display:inline-flex; align-items:center; gap:8px; padding:8px 12px; border:1px solid rgba(255,255,255,.24); border-radius:999px; color:#dbeafe; font-size:13px; }
    .dot { width:8px; height:8px; border-radius:50%; background:#22c55e; }
    .nav-tabs { max-width:1280px; margin:0 auto; padding:0 22px 16px; display:flex; gap:10px; }
    .tab-btn { border:1px solid rgba(255,255,255,.24); background:rgba(255,255,255,.08); color:#e5eefc; border-radius:8px; padding:9px 14px; cursor:pointer; font-size:14px; }
    .tab-btn.active { background:#fff; color:#17325d; border-color:#fff; }
    main { max-width:1280px; margin:0 auto; padding:24px 22px 36px; display:none; gap:18px; }
    main.active { display:grid; }
    #qaView.active { grid-template-columns:330px minmax(0,1fr); }
    #kbView.active { grid-template-columns:280px minmax(0,1fr); }
    #todoView.active { grid-template-columns:320px minmax(0,1fr); }
    #detailView.active { grid-template-columns:1fr; }
    .panel { background:var(--panel); border:1px solid var(--line); border-radius:8px; box-shadow:0 8px 24px rgba(15,23,42,.06); }
    .panel-head { padding:15px 16px; border-bottom:1px solid var(--line); display:flex; align-items:center; justify-content:space-between; gap:10px; }
    .panel-title { margin:0; font-size:16px; }
    .panel-body { padding:16px; }
    .category-list,.conversation-list { margin:12px 0 0; padding:0; list-style:none; display:grid; gap:8px; font-size:13px; }
    .category-list li,.conversation-list li { border:1px solid #e5eaf2; background:var(--soft); border-radius:8px; padding:9px 10px; cursor:pointer; }
    .category-list li { display:grid; grid-template-columns:minmax(0,1fr) auto; align-items:center; gap:10px; min-height:58px; padding:10px 12px; }
    .category-list li:hover { border-color:#93b4f6; background:#eef5ff; }
    .category-list li.active { border-color:#2563eb; background:#eff6ff; box-shadow:inset 3px 0 0 #2563eb; }
    .category-name { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#172033; font-weight:600; }
    .category-desc { grid-column:1 / 2; margin-top:2px; color:#64748b; font-size:12px; line-height:1.35; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .category-count { flex:0 0 auto; min-width:32px; text-align:center; border-radius:999px; padding:3px 8px; background:#e2e8f0; color:#334155; font-size:12px; font-weight:700; }
    .category-list li.active .category-count { background:#2563eb; color:#fff; }
    .conversation-list li.active { border-color:#2563eb; background:#eef5ff; }
    .conversation-list li { display:grid; grid-template-columns:minmax(0,1fr) auto; align-items:center; gap:8px; }
    .conversation-title { font-weight:700; color:#26364d; margin-bottom:4px; }
    .conversation-meta { color:var(--muted); font-size:12px; }
    .icon-danger { width:34px; height:34px; border:1px solid #fecaca; border-radius:8px; background:#fff; color:#b91c1c; cursor:pointer; display:grid; place-items:center; font-size:18px; line-height:1; }
    .icon-danger:hover { background:#fef2f2; border-color:#fca5a5; }
    .example-group { border-top:1px solid #edf1f6; padding-top:10px; margin-top:10px; }
    .example-group:first-child { border-top:0; padding-top:0; margin-top:0; }
    .example-group h3 { margin:0 0 8px; font-size:13px; color:#42526b; }
    .sample-grid { display:grid; gap:8px; }
    .sample { width:100%; text-align:left; border:1px solid var(--line); background:var(--soft); color:#24324a; border-radius:8px; padding:10px 12px; cursor:pointer; font-size:14px; line-height:1.35; }
    .sample:hover,.source:hover,.kb-card:hover { border-color:#93b4f6; background:#eef5ff; }
    .chat { display:grid; gap:12px; max-height:520px; overflow:auto; padding-right:4px; }
    .bubble { border:1px solid #e1e8f2; border-radius:8px; padding:12px 14px; line-height:1.7; white-space:pre-wrap; }
    .bubble.user { background:#eef5ff; border-color:#c7d9ff; }
    .bubble.assistant { background:#fff; }
    .bubble-role { font-size:12px; color:var(--muted); margin-bottom:6px; }
    textarea { min-height:96px; resize:vertical; line-height:1.55; }
    .actions { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-top:12px; }
    .trace { display:flex; gap:8px; flex-wrap:wrap; color:var(--muted); font-size:13px; }
    .tag { border:1px solid var(--line); border-radius:999px; padding:5px 9px; background:var(--soft); }
    .sources { display:grid; gap:10px; }
    .source { border:1px solid #e1e8f2; border-radius:8px; padding:12px 14px; background:#fbfdff; cursor:pointer; }
    .meta { color:#243b63; font-size:14px; margin-bottom:8px; display:flex; justify-content:space-between; gap:10px; flex-wrap:wrap; }
    .ref-badge { display:inline-flex; min-width:54px; justify-content:center; padding:4px 8px; border-radius:999px; background:#eaf2ff; color:#1d4ed8; font-size:13px; margin-right:8px; }
    .category-badge { display:inline-flex; padding:4px 8px; border-radius:999px; background:#eefbf5; color:#047857; font-size:12px; margin-right:8px; }
    .type-badge { display:inline-flex; padding:4px 8px; border-radius:999px; background:#f1f5f9; color:#475569; font-size:12px; margin-right:8px; }
    .source-text { color:#26364d; line-height:1.6; font-size:14px; max-height:120px; overflow:auto; }
    .stats { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
    .metric { border:1px solid #e5eaf2; border-radius:8px; padding:12px; background:#f9fbfd; }
    .metric strong { display:block; font-size:22px; margin-bottom:3px; }
    .mode { margin-top:12px; padding:10px 12px; border-radius:8px; font-size:13px; line-height:1.55; }
    .mode.deepseek { background:#ecfdf5; color:#066343; border:1px solid #bbf7d0; }
    .mode.local { background:#fff7ed; color:#9a3412; border:1px solid #fed7aa; }
    .kb-layout { margin-top:16px; }
    .kb-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
    .kb-card { border:1px solid #e1e8f2; border-radius:8px; background:#fff; padding:14px; min-height:170px; cursor:pointer; }
    .kb-title { margin:8px 0; font-weight:700; color:#1f3558; line-height:1.4; }
    .kb-text { color:#334155; font-size:14px; line-height:1.65; max-height:110px; overflow:auto; }
    .detail-panel { border:1px solid #cfd9e8; border-radius:8px; background:#fff; padding:24px; }
    .detail-actions { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:16px; }
    .detail-title { margin:10px 0; font-size:24px; color:#172033; }
    .detail-text { white-space:pre-wrap; line-height:1.9; color:#26364d; font-size:17px; }
    .pager { display:flex; align-items:center; justify-content:flex-end; gap:10px; margin-top:14px; color:var(--muted); font-size:14px; }
    .search-input { min-width:280px; flex:1; }
    .kb-toolbar { display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
    .todo-help { display:grid; gap:10px; }
    .todo-help-item { border:1px solid #e5eaf2; border-radius:8px; background:#f9fbfd; padding:12px; }
    .todo-help-item strong { display:block; margin-bottom:5px; color:#1f3558; font-size:14px; }
    .todo-help-item code { color:#1d4ed8; white-space:normal; line-height:1.6; }
    .todo-toolbar { display:flex; gap:10px; flex-wrap:wrap; align-items:center; justify-content:space-between; margin-bottom:14px; }
    .todo-grid { display:grid; gap:12px; }
    .todo-card { border:1px solid #e1e8f2; border-radius:8px; background:#fff; padding:14px; display:grid; gap:10px; }
    .todo-card.done { background:#f8fafc; }
    .todo-card.cancelled { background:#fff7f7; border-color:#fecaca; }
    .todo-title { font-weight:700; color:#1f3558; line-height:1.4; }
    .todo-meta { display:flex; gap:8px; flex-wrap:wrap; color:#64748b; font-size:13px; }
    .todo-details { color:#334155; font-size:14px; line-height:1.65; white-space:pre-wrap; }
    .todo-actions { display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end; }
    .status-badge { display:inline-flex; padding:4px 8px; border-radius:999px; font-size:12px; font-weight:700; background:#eaf2ff; color:#1d4ed8; }
    .status-badge.done { background:#ecfdf5; color:#047857; }
    .status-badge.cancelled { background:#fef2f2; color:#b91c1c; }
    @media (max-width:980px) { #qaView.active,#kbView.active,#todoView.active,#detailView.active { grid-template-columns:1fr; } main { padding:18px 14px 28px; } .kb-grid { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <section class="auth" id="authView"><div class="auth-card"><h1>EduRAG-Agent</h1><p>&#30331;&#24405;&#21518;&#36827;&#20837;&#30740;&#31350;&#29983;&#25945;&#21153;&#26234;&#33021;&#38382;&#31572;&#24037;&#20316;&#21488;&#12290;&#19981;&#21516;&#29992;&#25143;&#30340;&#38382;&#31572;&#35760;&#24405;&#20114;&#30456;&#38548;&#31163;&#12290;</p><label class="field">&#29992;&#25143;&#21517;<input class="input" id="authUsername" value="student001"></label><label class="field">&#23494;&#30721;<input class="input" id="authPassword" type="password" value="123456"></label><div class="actions"><button class="primary" onclick="login()">&#30331;&#24405;</button><button class="ghost" onclick="register()">&#27880;&#20876;</button></div><div class="error" id="authError"></div></div></section>
  <section class="app" id="appView"><header class="topbar"><div class="topbar-inner"><div class="brand"><div class="mark">ER</div><div><h1>EduRAG-Agent</h1><p class="subtitle">&#30740;&#31350;&#29983;&#25945;&#21153;&#19982;&#35838;&#31243;&#36164;&#26009;&#26234;&#33021;&#38382;&#31572;&#24037;&#20316;&#21488;</p></div></div><div class="userbar"><div class="status-pill"><span class="dot"></span><span id="apiStatus">&#36830;&#25509;&#20013;</span></div><div class="status-pill">&#29992;&#25143;&#65306;<span id="currentUser">-</span></div><button class="ghost" onclick="logout()">&#36864;&#20986;</button></div></div><nav class="nav-tabs"><button class="tab-btn active" id="qaTab" onclick="switchView('qa')">&#26234;&#33021;&#38382;&#31572;</button><button class="tab-btn" id="todoTab" onclick="switchView('todo')">&#25105;&#30340;&#24453;&#21150;</button><button class="tab-btn" id="kbTab" onclick="switchView('kb')">&#30693;&#35782;&#24211;&#27983;&#35272;</button><button class="tab-btn" id="detailTab" onclick="switchView('detail')" style="display:none;">&#30693;&#35782;&#35814;&#24773;</button></nav></header>
    <main id="qaView" class="active"><aside><section class="panel"><div class="panel-head"><h2 class="panel-title">&#20250;&#35805;&#35760;&#24405;</h2><button class="ghost" onclick="newConversation()">&#26032;&#24314;</button></div><div class="panel-body"><ul class="conversation-list" id="conversationList"></ul></div></section><section class="panel" style="margin-top:18px;"><div class="panel-head"><h2 class="panel-title">&#31034;&#20363;&#38382;&#39064;</h2></div><div class="panel-body"><div class="example-group"><h3>&#22521;&#20859;&#19982;&#23398;&#31821;</h3><div class="sample-grid"><button class="sample" onclick="fillQuestion('\\u5982\\u4f55\\u529e\\u7406\\u7814\\u7a76\\u751f\\u4f11\\u5b66\\uff1f\\u9700\\u8981\\u5bfc\\u5e08\\u5ba1\\u6279\\u5417\\uff1f')">&#22914;&#20309;&#21150;&#29702;&#30740;&#31350;&#29983;&#20241;&#23398;&#65311;&#38656;&#35201;&#23548;&#24072;&#23457;&#25209;&#21527;&#65311;</button><button class="sample" onclick="fillQuestion('\\u57f9\\u517b\\u8ba1\\u5212\\u53d8\\u66f4\\u9700\\u8981\\u8d70\\u4ec0\\u4e48\\u6d41\\u7a0b\\uff1f')">&#22521;&#20859;&#35745;&#21010;&#21464;&#26356;&#38656;&#35201;&#36208;&#20160;&#20040;&#27969;&#31243;&#65311;</button></div></div><div class="example-group"><h3>&#23398;&#20301;&#35770;&#25991;</h3><div class="sample-grid"><button class="sample" onclick="fillQuestion('\\u7855\\u58eb\\u8bba\\u6587\\u9884\\u7b54\\u8fa9\\u9700\\u8981\\u63d0\\u4ea4\\u54ea\\u4e9b\\u6750\\u6599\\uff1f')">&#30805;&#22763;&#35770;&#25991;&#39044;&#31572;&#36777;&#38656;&#35201;&#25552;&#20132;&#21738;&#20123;&#26448;&#26009;&#65311;</button><button class="sample" onclick="fillQuestion('\\u5982\\u679c\\u9884\\u7b54\\u8fa9\\u6ca1\\u6709\\u901a\\u8fc7\\uff0c\\u540e\\u7eed\\u600e\\u4e48\\u5904\\u7406\\uff1f')">&#22914;&#26524;&#39044;&#31572;&#36777;&#27809;&#26377;&#36890;&#36807;&#65292;&#21518;&#32493;&#24590;&#20040;&#22788;&#29702;&#65311;</button></div></div><div class="example-group"><h3>&#22870;&#21161;&#19982;&#26381;&#21153;</h3><div class="sample-grid"><button class="sample" onclick="fillQuestion('\\u56fd\\u5bb6\\u5956\\u5b66\\u91d1\\u8bc4\\u5ba1\\u91cd\\u70b9\\u770b\\u4ec0\\u4e48\\uff1f')">&#22269;&#23478;&#22870;&#23398;&#37329;&#35780;&#23457;&#37325;&#28857;&#30475;&#20160;&#20040;&#65311;</button><button class="sample" onclick="fillQuestion('\\u5fd8\\u8bb0\\u7edf\\u4e00\\u8eab\\u4efd\\u8ba4\\u8bc1\\u5bc6\\u7801\\u600e\\u4e48\\u529e\\uff1f')">&#24536;&#35760;&#32479;&#19968;&#36523;&#20221;&#35748;&#35777;&#23494;&#30721;&#24590;&#20040;&#21150;&#65311;</button></div></div><div class="example-group"><h3>&#35838;&#31243;&#39033;&#30446;</h3><div class="sample-grid"><button class="sample" onclick="fillQuestion('CS599 \\u671f\\u672b\\u5927\\u4f5c\\u4e1a\\u6700\\u7ec8\\u63d0\\u4ea4\\u622a\\u6b62\\u65f6\\u95f4\\u662f\\u4ec0\\u4e48\\uff1f')">CS599 &#26399;&#26411;&#22823;&#20316;&#19994;&#26368;&#32456;&#25552;&#20132;&#25130;&#27490;&#26102;&#38388;&#26159;&#20160;&#20040;&#65311;</button><button class="sample" onclick="fillQuestion('\\u62a5\\u544a PDF \\u5fc5\\u987b\\u5305\\u542b\\u54ea\\u4e9b\\u7ae0\\u8282\\uff1f')">&#25253;&#21578; PDF &#24517;&#39035;&#21253;&#21547;&#21738;&#20123;&#31456;&#33410;&#65311;</button></div></div></div></section></aside><div><section class="panel"><div class="panel-head"><h2 class="panel-title">&#32842;&#22825;&#35760;&#24405;</h2><div class="trace" id="trace"></div><button class="ghost" onclick="clearCurrentConversation()">&#28165;&#31354;</button></div><div class="panel-body"><div class="chat" id="chatLog"></div></div></section><section class="panel" style="margin-top:18px;"><div class="panel-head"><h2 class="panel-title">&#25552;&#38382;</h2><span class="hint">&#20445;&#30041;&#26368;&#36817; 6 &#36718;&#19978;&#19979;&#25991;&#65292;&#26368;&#38271;&#32422; 4000 &#23383;</span></div><div class="panel-body"><textarea id="question" placeholder="&#36755;&#20837;&#38382;&#39064;&#65292;&#20063;&#21487;&#20197;&#22522;&#20110;&#19978;&#19968;&#36718;&#32487;&#32493;&#36861;&#38382;"></textarea><div class="actions"><button class="primary" id="askBtn" onclick="ask()">&#21457;&#36865;</button><span class="hint">RAG &#26816;&#32034; + DeepSeek &#29983;&#25104; + &#29992;&#25143;&#21382;&#21490;&#35760;&#24405;</span></div></div></section><section class="panel" style="margin-top:18px;"><div class="panel-head"><h2 class="panel-title">&#26412;&#36718;&#26816;&#32034;&#26469;&#28304;</h2><span class="hint">&#28857;&#20987;&#26469;&#28304;&#21487;&#25171;&#24320;&#21333;&#29420;&#35814;&#24773;&#39029;</span></div><div class="panel-body sources" id="sources"></div></section></div></main>
    <main id="todoView"><aside><section class="panel"><div class="panel-head"><h2 class="panel-title">聊天可完成的操作</h2></div><div class="panel-body"><div class="todo-help"><div class="todo-help-item"><strong>创建待办</strong><code>帮我创建一条待办：明天提交开题报告，紧急</code></div><div class="todo-help-item"><strong>查看待办</strong><code>查看我的待办</code><br><code>查看全部办事记录</code></div><div class="todo-help-item"><strong>更新状态</strong><code>完成待办 1</code><br><code>取消工单 #2</code></div><div class="todo-help-item"><strong>自动分类</strong><span class="hint">聊天创建时会根据关键词归类到学籍与培养、论文与学位、奖助与就业、校园服务、课程项目或综合办事。</span></div></div></div></section><section class="panel" style="margin-top:18px;"><div class="panel-head"><h2 class="panel-title">快速提问</h2></div><div class="panel-body"><div class="sample-grid"><button class="sample" onclick="askTodo('查看我的待办')">查看我的待办</button><button class="sample" onclick="askTodo('帮我创建一条待办：明天提交开题报告，紧急')">创建开题报告待办</button></div></div></section></aside><div><section class="panel"><div class="panel-head"><h2 class="panel-title">我的办事待办</h2><span class="hint" id="todoTotal">加载中</span></div><div class="panel-body"><div class="todo-toolbar"><select id="todoStatus" onchange="loadServiceRequests()"><option value="open">未完成</option><option value="done">已完成</option><option value="cancelled">已取消</option><option value="all">全部</option></select><button class="ghost" onclick="loadServiceRequests()">刷新</button></div><div class="todo-grid" id="todoList"></div></div></section></div></main>
    <main id="kbView"><aside><section class="panel"><div class="panel-head"><h2 class="panel-title">&#30693;&#35782;&#24211;&#29366;&#24577;</h2></div><div class="panel-body"><div class="stats"><div class="metric"><strong id="kbChunkCount">-</strong><span>&#30693;&#35782;&#29255;&#27573;</span></div><div class="metric"><strong id="kbCategoryCount">-</strong><span>&#20998;&#31867;&#25968;&#37327;</span></div></div><div class="mode" id="apiMode">&#27169;&#22411;&#27169;&#24335;&#21152;&#36733;&#20013;</div><p class="hint" style="line-height:1.7;">&#30693;&#35782;&#24211;&#19981;&#26159;&#38382;&#31572;&#23545;&#65292;&#32780;&#26159;&#32467;&#26500;&#21270;&#19994;&#21153;&#25991;&#26723;&#29255;&#27573;&#12290;&#28857;&#20987;&#20219;&#24847;&#21345;&#29255;&#36827;&#20837;&#21333;&#29420;&#35814;&#24773;&#39029;&#38754;&#12290;</p></div></section><section class="panel" style="margin-top:18px;"><div class="panel-head"><h2 class="panel-title">&#20998;&#31867;&#31579;&#36873;</h2></div><div class="panel-body"><ul class="category-list" id="kbCategoryList"></ul></div></section></aside><div><section class="panel"><div class="panel-head"><h2 class="panel-title">&#30693;&#35782;&#24211;&#27983;&#35272;</h2><span class="hint" id="kbTotal">&#21152;&#36733;&#20013;</span></div><div class="panel-body"><div class="kb-toolbar"><select id="kbCategory" onchange="loadKnowledge(1)"></select><input class="input search-input" id="kbSearch" placeholder="&#25628;&#32034;&#65306;&#23398;&#31821;&#12289;&#22521;&#20859;&#35745;&#21010;&#12289;&#22870;&#23398;&#37329;&#12289;VPN&#12289;&#39044;&#31572;&#36777;"><button class="primary" onclick="loadKnowledge(1)">&#25628;&#32034;</button></div><div class="kb-layout"><div class="kb-grid" id="kbGrid"></div><div class="pager"><button class="ghost" id="prevPage" onclick="loadKnowledge(kbPage - 1)">&#19978;&#19968;&#39029;</button><span id="pageInfo">&#31532; 1 &#39029;</span><button class="ghost" id="nextPage" onclick="loadKnowledge(kbPage + 1)">&#19979;&#19968;&#39029;</button></div></div></div></section></div></main>
    <main id="detailView"><section class="panel"><div class="panel-head"><h2 class="panel-title">&#30693;&#35782;&#35814;&#24773;</h2><button class="ghost" onclick="switchView('kb')">&#36820;&#22238;&#30693;&#35782;&#24211;</button></div><div class="panel-body"><article class="detail-panel" id="kbDetail"><span class="hint">&#20174;&#30693;&#35782;&#24211;&#21015;&#34920;&#25110;&#38382;&#31572;&#26469;&#28304;&#20013;&#36873;&#25321;&#19968;&#26465;&#36164;&#26009;&#12290;</span></article></div></section></main>
  </section>
  <script>
    let currentConversationId = null; let kbPage = 1; let selectedKbCategory = ''; let currentApiMode = 'Local Extractive'; const pageSize = 12;
    async function api(url, options = {}) { const res = await fetch(url, {headers:{'Content-Type':'application/json'}, ...options}); if (!res.ok) { let msg='Request failed'; try { msg=(await res.json()).detail || msg; } catch (_) {} throw new Error(msg); } return res.json(); }
    async function register(){ await auth('/api/register'); } async function login(){ await auth('/api/login'); }
    async function auth(url){ try { const user=await api(url,{method:'POST',body:JSON.stringify({username:authUsername.value,password:authPassword.value})}); showApp(user); } catch(err){ authError.textContent=err.message; } }
    async function logout(){ await fetch('/api/logout',{method:'POST'}); location.reload(); }
    async function boot(){ try { showApp(await api('/api/me')); } catch(_){ authView.style.display='grid'; appView.style.display='none'; } }
    async function showApp(user){ authView.style.display='none'; appView.style.display='block'; currentUser.textContent=user.username; await loadStats(); await loadConversations(); await loadKnowledge(1); await loadServiceRequests(); }
    function switchView(view){ qaView.classList.toggle('active',view==='qa'); todoView.classList.toggle('active',view==='todo'); kbView.classList.toggle('active',view==='kb'); detailView.classList.toggle('active',view==='detail'); qaTab.classList.toggle('active',view==='qa'); todoTab.classList.toggle('active',view==='todo'); kbTab.classList.toggle('active',view==='kb'); detailTab.classList.toggle('active',view==='detail'); if(view==='detail') detailTab.style.display='inline-flex'; if(view==='kb') loadKnowledge(kbPage); if(view==='todo') loadServiceRequests(); }
    function fillQuestion(text){ question.value=text; switchView('qa'); question.focus(); }
    async function loadStats(){ const data=await api('/api/stats'); currentApiMode=data.api_mode; const usingDeepSeek=data.api_mode==='DeepSeek API'; apiStatus.textContent=usingDeepSeek?'DeepSeek API \\u5df2\\u542f\\u7528':'\\u672c\\u5730\\u62bd\\u53d6\\u6a21\\u5f0f'; kbChunkCount.textContent=data.chunk_count; kbCategoryCount.textContent=data.categories.length; apiMode.className='mode '+(usingDeepSeek?'deepseek':'local'); apiMode.textContent=usingDeepSeek?`\\u5f53\\u524d\\u6a21\\u578b\\uff1aDeepSeek / ${data.llm_model}`:`\\u5f53\\u524d\\u6a21\\u578b\\uff1a\\u672c\\u5730\\u62bd\\u53d6\\u3002\\u672a\\u68c0\\u6d4b\\u5230 DeepSeek API Key\\uff0c\\u56e0\\u6b64\\u4e0d\\u4f1a\\u8c03\\u7528\\u5916\\u90e8\\u5927\\u6a21\\u578b\\u3002`; refreshModelHints(usingDeepSeek); renderCategoryList(data.categories); kbCategory.innerHTML='<option value="">\\u5168\\u90e8\\u5206\\u7c7b</option>'+data.categories.map(item=>`<option value="${escapeAttr(item.name)}">${item.name}</option>`).join(''); kbCategory.value=selectedKbCategory; }
    function refreshModelHints(usingDeepSeek){ document.querySelectorAll('.hint').forEach(el=>{ if(el.textContent.includes('DeepSeek')) el.textContent=usingDeepSeek?'RAG 检索 + DeepSeek 生成 + 用户历史记录':'RAG 检索 + 本地抽取回答 + 用户历史记录'; }); }
    function renderCategoryList(categories){ const total=categories.reduce((sum,item)=>sum+Number(item.count||0),0); const rows=[{name:'',label:'\\u5168\\u90e8\\u77e5\\u8bc6',count:total},...categories]; kbCategoryList.innerHTML=rows.map(item=>`<li class="${item.name===selectedKbCategory?'active':''}" onclick="setKbCategory('${escapeAttr(item.name)}')" title="${escapeAttr(item.label||item.name)}"><div><span class="category-name">${escapeHtml(item.label||item.name)}</span><div class="category-desc">${escapeHtml(categoryDesc(item.name))}</div></div><span class="category-count">${item.count}</span></li>`).join(''); }
    function categoryDesc(name){ return ({'':'课程要求、真实资料与演示资料','课程项目':'CS599 评分、提交、报告与加分项','学籍与培养':'注册、培养计划、课程与培养流程','论文与学位':'开题、预答辩、盲审、答辩与归档','奖助与就业':'奖学金、助教、困难补助与就业','校园服务':'信息化、图书馆、档案、财务和交流','科研与规范':'学术诚信、实验安全、伦理和数据','综合办事':'教务咨询、材料提交和通用流程'}[name]||'相关业务资料'); }
    function setKbCategory(name){ selectedKbCategory=name; kbCategory.value=name; [...kbCategoryList.children].forEach(item=>item.classList.toggle('active', item.querySelector('.category-name')?.textContent===name)); loadKnowledge(1); switchView('kb'); }
    async function loadServiceRequests(){ const status=todoStatus.value || 'open'; const rows=await api(`/api/service-requests?status=${encodeURIComponent(status)}`); todoTotal.textContent=`共 ${rows.length} 条`; renderServiceRequests(rows); }
    function renderServiceRequests(rows){ if(!rows.length){ todoList.innerHTML='<div class="hint">当前没有匹配的办事待办。你可以在聊天中输入“帮我创建一条待办：明天提交开题报告，紧急”。</div>'; return; } todoList.innerHTML=rows.map(item=>`<article class="todo-card ${escapeAttr(item.status)}"><div class="todo-title">#${item.id} ${escapeHtml(item.title)}</div><div class="todo-meta"><span class="status-badge ${escapeAttr(item.status)}">${statusLabel(item.status)}</span><span>${escapeHtml(item.category)}</span><span>优先级：${priorityLabel(item.priority)}</span><span>截止：${escapeHtml(item.due_date || '未设置')}</span></div><div class="todo-details">${escapeHtml(item.details || '无补充说明')}</div><div class="todo-actions">${item.status==='open'?`<button class="ghost" onclick="updateServiceRequest(${item.id}, 'done')">完成</button><button class="ghost" onclick="updateServiceRequest(${item.id}, 'cancelled')">取消</button>`:`<button class="ghost" onclick="updateServiceRequest(${item.id}, 'open')">重新打开</button>`}<button class="ghost" onclick="fillQuestion('查看我的待办')">去聊天查看</button></div></article>`).join(''); }
    async function updateServiceRequest(id,status){ await api(`/api/service-requests/${id}`,{method:'PATCH',body:JSON.stringify({status})}); await loadServiceRequests(); }
    function askTodo(text){ fillQuestion(text); ask(); }
    function statusLabel(status){ return ({open:'未完成',done:'已完成',cancelled:'已取消'}[status]||status); }
    function priorityLabel(priority){ return ({low:'低',normal:'普通',high:'紧急'}[priority]||priority); }
    async function loadConversations(){ const rows=await api('/api/conversations'); conversationList.innerHTML=rows.map(row=>`<li onclick="openConversation(${row.id})" class="${row.id===currentConversationId?'active':''}"><div><div class="conversation-title">${escapeHtml(row.title)}</div><div class="conversation-meta">${row.message_count} \\u6761\\u6d88\\u606f</div></div><button class="icon-danger" title="\\u5220\\u9664\\u4f1a\\u8bdd" onclick="deleteConversation(event, ${row.id})">×</button></li>`).join(''); if(!currentConversationId && rows.length) await openConversation(rows[0].id); if(!rows.length){ currentConversationId=null; chatLog.innerHTML='<div class="hint">\\u8fd8\\u6ca1\\u6709\\u4f1a\\u8bdd\\u3002\\u53ef\\u4ee5\\u76f4\\u63a5\\u8f93\\u5165\\u95ee\\u9898\\u5f00\\u59cb\\u3002</div>'; sources.innerHTML='<div class="hint">\\u53d1\\u9001\\u95ee\\u9898\\u540e\\uff0c\\u8fd9\\u91cc\\u4f1a\\u5c55\\u793a\\u68c0\\u7d22\\u6765\\u6e90\\u3002</div>'; trace.innerHTML=''; } }
    async function newConversation(){ const data=await api('/api/conversations',{method:'POST'}); currentConversationId=data.conversation_id; chatLog.innerHTML=''; renderSources([]); trace.innerHTML=''; await loadConversations(); }
    async function deleteConversation(event,id){ event.stopPropagation(); if(!confirm('\\u786e\\u5b9a\\u5220\\u9664\\u8fd9\\u4e2a\\u4f1a\\u8bdd\\u53ca\\u5176\\u5168\\u90e8\\u6d88\\u606f\\u5417\\uff1f')) return; await api(`/api/conversations/${id}`,{method:'DELETE'}); if(currentConversationId===id){ currentConversationId=null; chatLog.innerHTML=''; renderSources([]); trace.innerHTML=''; } await loadConversations(); }
    async function clearCurrentConversation(){ if(!currentConversationId){ chatLog.innerHTML=''; renderSources([]); trace.innerHTML=''; return; } if(!confirm('\\u786e\\u5b9a\\u6e05\\u7a7a\\u5f53\\u524d\\u4f1a\\u8bdd\\u7684\\u804a\\u5929\\u8bb0\\u5f55\\u5417\\uff1f')) return; await api(`/api/conversations/${currentConversationId}/messages`,{method:'DELETE'}); chatLog.innerHTML='<div class="hint">\\u5f53\\u524d\\u4f1a\\u8bdd\\u5df2\\u6e05\\u7a7a\\u3002</div>'; renderSources([]); trace.innerHTML=''; await loadConversations(); }
    async function openConversation(id){ currentConversationId=id; trace.innerHTML=''; const rows=await api(`/api/conversations/${id}/messages`); renderMessages(rows); const lastAssistant=[...rows].reverse().find(m=>m.role==='assistant' && m.sources && m.sources.length); renderSources(lastAssistant?lastAssistant.sources:[]); await loadConversations(); }
    function renderMessages(rows){ chatLog.innerHTML=rows.map(m=>`<div class="bubble ${m.role}"><div class="bubble-role">${m.role==='user'?'\\u6211':'EduRAG-Agent'}</div>${escapeHtml(m.content)}</div>`).join('') || '<div class="hint">\\u8fd9\\u4e2a\\u4f1a\\u8bdd\\u8fd8\\u6ca1\\u6709\\u6d88\\u606f\\u3002</div>'; chatLog.scrollTop=chatLog.scrollHeight; }
    async function ask(){ const text=question.value.trim(); if(!text) return; askBtn.disabled=true; appendBubble('user',text); appendBubble('assistant','\\u68c0\\u7d22\\u548c\\u751f\\u6210\\u4e2d...'); try { const data=await api('/api/ask',{method:'POST',body:JSON.stringify({question:text,conversation_id:currentConversationId,top_k:4})}); currentConversationId=data.conversation_id; question.value=''; await openConversation(currentConversationId); trace.innerHTML=`<span class="tag">Model: ${providerLabel(data.provider)}</span><span class="tag">\\u8017\\u65f6: ${data.elapsed_ms}ms</span><span class="tag">\\u4e0a\\u4e0b\\u6587: ${data.history_messages} \\u6761</span>`; renderSources(data.sources); if(data.provider==='system-tool') await loadServiceRequests(); } catch(err){ appendBubble('assistant','\\u8bf7\\u6c42\\u5931\\u8d25\\uff1a'+err.message); } finally { askBtn.disabled=false; } }
    function appendBubble(role,content){ if(chatLog.querySelector('.hint')) chatLog.innerHTML=''; chatLog.insertAdjacentHTML('beforeend',`<div class="bubble ${role}"><div class="bubble-role">${role==='user'?'\\u6211':'EduRAG-Agent'}</div>${escapeHtml(content)}</div>`); chatLog.scrollTop=chatLog.scrollHeight; }
    function renderSources(items){ if(!items || !items.length){ sources.innerHTML='<div class="hint">\\u6682\\u65e0\\u53ef\\u5c55\\u793a\\u6765\\u6e90\\u3002\\u53d1\\u9001\\u65b0\\u95ee\\u9898\\u540e\\u4f1a\\u5728\\u8fd9\\u91cc\\u5c55\\u793a\\u672c\\u8f6e\\u68c0\\u7d22\\u8bc1\\u636e\\u3002</div>'; return; } sources.innerHTML=items.map(item=>`<div class="source" onclick="openKnowledgeDetail('${item.chunk_id}')"><div class="meta"><span><span class="ref-badge">${item.ref}</span><span class="category-badge">${item.category}</span><span class="type-badge">${item.source_type}</span>${escapeHtml(item.display_title)}</span><span>\\u76f8\\u5173\\u5ea6 ${Number(item.score||0).toFixed(4)}</span></div><div class="source-text">${escapeHtml(item.text)}</div></div>`).join(''); }
    async function loadKnowledge(page){ selectedKbCategory=kbCategory.value; kbPage=Math.max(page,1); const data=await api(`/api/knowledge?page=${kbPage}&page_size=${pageSize}&category=${encodeURIComponent(selectedKbCategory)}&q=${encodeURIComponent(kbSearch.value.trim())}`); [...kbCategoryList.children].forEach(item=>item.classList.toggle('active', item.querySelector('.category-name')?.textContent===(selectedKbCategory||'\\u5168\\u90e8\\u77e5\\u8bc6'))); kbTotal.textContent=`\\u5171 ${data.total} \\u6761`; kbGrid.innerHTML=data.items.map(item=>`<article class="kb-card" onclick="openKnowledgeDetail('${item.id}')"><span class="ref-badge">${item.ref}</span><span class="category-badge">${item.category}</span><span class="type-badge">${item.source_type}</span><div class="kb-title">${escapeHtml(item.title)}</div><div class="kb-text">${escapeHtml(item.text)}</div></article>`).join('') || '<div class="hint">\\u6ca1\\u6709\\u627e\\u5230\\u5339\\u914d\\u7684\\u77e5\\u8bc6\\u7247\\u6bb5\\u3002</div>'; const maxPage=Math.max(1,Math.ceil(data.total/pageSize)); pageInfo.textContent=`\\u7b2c ${kbPage} / ${maxPage} \\u9875`; prevPage.disabled=kbPage<=1; nextPage.disabled=kbPage>=maxPage; }
    async function openKnowledgeDetail(id){ const item=await api(`/api/knowledge/${encodeURIComponent(id)}`); kbDetail.dataset.loaded='1'; kbDetail.innerHTML=`<div class="detail-actions"><div><span class="category-badge">${item.category}</span><span class="type-badge">${item.source_type}</span><h3 class="detail-title">${escapeHtml(item.title)}</h3></div><button class="ghost" onclick="fillQuestion('\\u8bf7\\u89e3\\u91ca\\uff1a${escapeAttr(item.title)}')">\\u57fa\\u4e8e\\u6b64\\u8d44\\u6599\\u63d0\\u95ee</button></div><hr style="border:0;border-top:1px solid #e1e8f2;margin:14px 0;"><div class="detail-text">${escapeHtml(item.text)}</div>`; switchView('detail'); window.scrollTo({top:0,behavior:'smooth'}); }
    function providerLabel(provider){ if(provider==='system-tool') return '\\u7cfb\\u7edf\\u5de5\\u5177'; if(provider==='openai-compatible') return currentApiMode==='DeepSeek API'?'DeepSeek API':'OpenAI Compatible'; if(provider==='local-extractive') return '\\u672c\\u5730\\u62bd\\u53d6'; return provider; }
    function escapeHtml(text){ return String(text ?? '').replace(/[&<>"']/g,s=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s])); }
    function escapeAttr(text){ return String(text ?? '').replace(/'/g,"\\\\'").replace(/"/g,'&quot;'); }
    boot();
  </script>
</body>
</html>
"""

