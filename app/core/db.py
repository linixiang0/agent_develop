from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings


DB_PATH = settings.data_dir / "app.sqlite"
CONTEXT_TURNS = 6
CONTEXT_MAX_CHARS = 4000


@dataclass(frozen=True)
class User:
    id: int
    username: str


class AppStore:
    def __init__(self, path: Path = DB_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists users (
                    id integer primary key autoincrement,
                    username text not null unique,
                    password_hash text not null,
                    salt text not null,
                    created_at text not null
                );
                create table if not exists sessions (
                    token text primary key,
                    user_id integer not null,
                    created_at text not null,
                    foreign key(user_id) references users(id)
                );
                create table if not exists conversations (
                    id integer primary key autoincrement,
                    user_id integer not null,
                    title text not null,
                    created_at text not null,
                    updated_at text not null,
                    foreign key(user_id) references users(id)
                );
                create table if not exists messages (
                    id integer primary key autoincrement,
                    conversation_id integer not null,
                    role text not null,
                    content text not null,
                    provider text,
                    sources_json text,
                    created_at text not null,
                    foreign key(conversation_id) references conversations(id)
                );
                create table if not exists service_requests (
                    id integer primary key autoincrement,
                    user_id integer not null,
                    category text not null,
                    title text not null,
                    details text not null default '',
                    status text not null default 'open',
                    priority text not null default 'normal',
                    due_date text,
                    created_at text not null,
                    updated_at text not null,
                    foreign key(user_id) references users(id)
                );
                create table if not exists agent_action_logs (
                    id integer primary key autoincrement,
                    user_id integer,
                    conversation_id integer,
                    tool_name text not null,
                    arguments_json text not null,
                    result_json text not null,
                    created_at text not null,
                    foreign key(user_id) references users(id),
                    foreign key(conversation_id) references conversations(id)
                );
                """
            )

    def register(self, username: str, password: str) -> User:
        username = username.strip()
        if len(username) < 3:
            raise ValueError("用户名至少 3 个字符")
        if len(password) < 6:
            raise ValueError("密码至少 6 个字符")
        salt = secrets.token_hex(16)
        password_hash = _hash_password(password, salt)
        now = _now()
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    "insert into users(username, password_hash, salt, created_at) values (?, ?, ?, ?)",
                    (username, password_hash, salt, now),
                )
                return User(id=int(cursor.lastrowid), username=username)
        except sqlite3.IntegrityError as exc:
            raise ValueError("用户名已存在") from exc

    def authenticate(self, username: str, password: str) -> User | None:
        with self._connect() as conn:
            row = conn.execute("select * from users where username = ?", (username.strip(),)).fetchone()
        if not row:
            return None
        if _hash_password(password, row["salt"]) != row["password_hash"]:
            return None
        return User(id=int(row["id"]), username=row["username"])

    def create_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        with self._connect() as conn:
            conn.execute(
                "insert into sessions(token, user_id, created_at) values (?, ?, ?)",
                (token, user_id, _now()),
            )
        return token

    def delete_session(self, token: str) -> None:
        with self._connect() as conn:
            conn.execute("delete from sessions where token = ?", (token,))

    def user_by_session(self, token: str | None) -> User | None:
        if not token:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                select users.id, users.username
                from sessions join users on users.id = sessions.user_id
                where sessions.token = ?
                """,
                (token,),
            ).fetchone()
        if not row:
            return None
        return User(id=int(row["id"]), username=row["username"])

    def create_conversation(self, user_id: int, title: str) -> int:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "insert into conversations(user_id, title, created_at, updated_at) values (?, ?, ?, ?)",
                (user_id, title[:40] or "新的问答", now, now),
            )
            return int(cursor.lastrowid)

    def get_conversation(self, user_id: int, conversation_id: int) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                "select * from conversations where id = ? and user_id = ?",
                (conversation_id, user_id),
            ).fetchone()

    def list_conversations(self, user_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select c.id, c.title, c.updated_at,
                       (select count(*) from messages m where m.conversation_id = c.id) as message_count
                from conversations c
                where c.user_id = ?
                order by c.updated_at desc
                limit 50
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_conversation(self, user_id: int, conversation_id: int) -> bool:
        if not self.get_conversation(user_id, conversation_id):
            return False
        with self._connect() as conn:
            conn.execute("delete from messages where conversation_id = ?", (conversation_id,))
            conn.execute("delete from conversations where id = ? and user_id = ?", (conversation_id, user_id))
        return True

    def clear_conversation_messages(self, user_id: int, conversation_id: int) -> bool:
        if not self.get_conversation(user_id, conversation_id):
            return False
        now = _now()
        with self._connect() as conn:
            conn.execute("delete from messages where conversation_id = ?", (conversation_id,))
            conn.execute("update conversations set title = ?, updated_at = ? where id = ?", ("新的问答", now, conversation_id))
        return True

    def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        provider: str | None = None,
        sources: list[dict[str, Any]] | None = None,
    ) -> None:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                insert into messages(conversation_id, role, content, provider, sources_json, created_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                (conversation_id, role, content, provider, json.dumps(sources or [], ensure_ascii=False), now),
            )
            conn.execute("update conversations set updated_at = ? where id = ?", (now, conversation_id))

    def create_service_request(
        self,
        user_id: int,
        title: str,
        category: str = "综合办事",
        details: str = "",
        priority: str = "normal",
        due_date: str | None = None,
    ) -> dict[str, Any]:
        now = _now()
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("title is required")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                insert into service_requests(
                    user_id, category, title, details, status, priority, due_date, created_at, updated_at
                )
                values (?, ?, ?, ?, 'open', ?, ?, ?, ?)
                """,
                (user_id, category, clean_title[:120], details.strip(), priority, due_date, now, now),
            )
            row = conn.execute("select * from service_requests where id = ?", (cursor.lastrowid,)).fetchone()
        return _service_request_dict(row)

    def list_service_requests(self, user_id: int, status: str = "open", limit: int = 20) -> list[dict[str, Any]]:
        allowed_status = {"open", "done", "cancelled", "all"}
        normalized_status = status if status in allowed_status else "open"
        limit = max(1, min(limit, 50))
        sql = "select * from service_requests where user_id = ?"
        params: list[Any] = [user_id]
        if normalized_status != "all":
            sql += " and status = ?"
            params.append(normalized_status)
        sql += " order by case status when 'open' then 0 else 1 end, updated_at desc limit ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_service_request_dict(row) for row in rows]

    def update_service_request_status(self, user_id: int, request_id: int, status: str) -> dict[str, Any] | None:
        if status not in {"open", "done", "cancelled"}:
            raise ValueError("Unsupported status")
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "update service_requests set status = ?, updated_at = ? where id = ? and user_id = ?",
                (status, now, request_id, user_id),
            )
            if cursor.rowcount == 0:
                return None
            row = conn.execute("select * from service_requests where id = ? and user_id = ?", (request_id, user_id)).fetchone()
        return _service_request_dict(row)

    def log_agent_action(
        self,
        user_id: int | None,
        conversation_id: int | None,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into agent_action_logs(user_id, conversation_id, tool_name, arguments_json, result_json, created_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    conversation_id,
                    tool_name,
                    json.dumps(arguments, ensure_ascii=False),
                    json.dumps(result, ensure_ascii=False),
                    _now(),
                ),
            )

    def messages(self, user_id: int, conversation_id: int) -> list[dict[str, Any]]:
        if not self.get_conversation(user_id, conversation_id):
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "select * from messages where conversation_id = ? order by id asc",
                (conversation_id,),
            ).fetchall()
        return [_message_dict(row) for row in rows]

    def context_messages(self, user_id: int, conversation_id: int) -> list[dict[str, str]]:
        messages = self.messages(user_id, conversation_id)
        pairs = [m for m in messages if m["role"] in {"user", "assistant"}][-CONTEXT_TURNS * 2 :]
        trimmed: list[dict[str, str]] = []
        total = 0
        for item in reversed(pairs):
            content = item["content"]
            if total + len(content) > CONTEXT_MAX_CHARS and trimmed:
                break
            trimmed.append({"role": item["role"], "content": content[:CONTEXT_MAX_CHARS]})
            total += len(content)
        return list(reversed(trimmed))


def _message_dict(row: sqlite3.Row) -> dict[str, Any]:
    sources_raw = row["sources_json"] or "[]"
    try:
        sources = json.loads(sources_raw)
    except json.JSONDecodeError:
        sources = []
    return {
        "id": row["id"],
        "conversation_id": row["conversation_id"],
        "role": row["role"],
        "content": row["content"],
        "provider": row["provider"],
        "sources": sources,
        "created_at": row["created_at"],
    }


def _service_request_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "user_id": int(row["user_id"]),
        "category": row["category"],
        "title": row["title"],
        "details": row["details"],
        "status": row["status"],
        "priority": row["priority"],
        "due_date": row["due_date"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _hash_password(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return digest.hex()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
