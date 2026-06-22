# API Spec：EduRAG-Agent

## 1. Health Check

### Request

`GET /health`

### Response

```json
{
  "status": "ok",
  "app": "EduRAG-Agent"
}
```

## 2. Auth

### Register

`POST /api/register`

```json
{
  "username": "student001",
  "password": "123456"
}
```

成功后服务端写入 `session_id` HttpOnly Cookie。

### Login

`POST /api/login`

```json
{
  "username": "student001",
  "password": "123456"
}
```

### Current User

`GET /api/me`

需要 `session_id` Cookie。

### Logout

`POST /api/logout`

清除当前 session。

## 3. Ask Question

### Request

`POST /api/ask`

需要 `session_id` Cookie。

```json
{
  "question": "报告 PDF 必须包含哪些章节？",
  "top_k": 4,
  "conversation_id": 1
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `question` | string | 是 | 用户自然语言问题 |
| `top_k` | integer | 否 | 最大召回证据数量，默认 4，范围 1-8 |
| `conversation_id` | integer/null | 否 | 为空时自动创建新会话 |

### Response

```json
{
  "conversation_id": 1,
  "question": "报告 PDF 必须包含哪些章节？",
  "answer": "根据知识库资料，可以得到以下回答：...",
  "provider": "local-extractive",
  "elapsed_ms": 32,
  "history_messages": 4,
  "sources": [
    {
      "ref": "资料1",
      "chunk_id": "abc123-0001",
      "category": "报告要求",
      "display_title": "报告 PDF 导航目录",
      "title": "cs599_course_requirements / 报告要求",
      "score": 0.42,
      "path": "data/raw/cs599_course_requirements.md",
      "text": "报告主要章节包括..."
    }
  ]
}
```

## 4. Conversation API

| Method | Path | 说明 |
|---|---|---|
| `GET` | `/api/conversations` | 获取当前用户最近会话 |
| `POST` | `/api/conversations` | 创建新会话 |
| `GET` | `/api/conversations/{conversation_id}/messages` | 获取会话消息 |

所有会话接口都需要登录 Cookie。上下文窗口保留最近 6 轮问答，最长约 4000 字。

## 5. Knowledge API

### Stats

`GET /api/stats`

返回知识片段数量、资料来源数量、分类统计和当前模型模式。

### List Knowledge

`GET /api/knowledge?category=学位论文&q=预答辩&page=1&page_size=12`

返回分页知识片段，支持分类和关键词过滤。

### Knowledge Detail

`GET /api/knowledge/{chunk_id}`

返回单个知识片段完整内容、来源路径和展示标题。

## 6. Tool Schema

系统内部工具 `search_knowledge_base` 的 Function Calling Schema：

```json
{
  "name": "search_knowledge_base",
  "description": "Search course, academic affairs, and CS599 project documents.",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "User question or rewritten search query."
      },
      "top_k": {
        "type": "integer",
        "description": "Maximum number of evidence chunks."
      }
    },
    "required": ["query"]
  }
}
```

## 7. MCP Tool

启动命令：

```powershell
python -m app.mcp_server
```

MCP Server 使用 stdio JSON-RPC，暴露工具：

```json
{
  "name": "search_knowledge_base",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": { "type": "string" },
      "top_k": { "type": "integer", "minimum": 1, "maximum": 8, "default": 4 }
    },
    "required": ["query"]
  }
}
```

工具返回文本 JSON，包含 `answer`、`provider`、`elapsed_ms` 和 `sources`。

## 8. Error Policy

- 未登录访问受保护接口：返回 `401 Login required`。
- 会话不存在或不属于当前用户：返回 `404 Conversation not found`。
- 知识库为空：返回“知识库中没有检索到足够相关的资料”。
- LLM API 调用失败：自动降级为本地抽取式回答。
- API Key 缺失：默认使用本地模式，不阻塞 Demo。
