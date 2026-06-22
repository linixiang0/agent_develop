# Agent 系统操作与数据库设计

## 目标

让用户在聊天中触发受控的系统功能，而不是让 Agent 直接拼 SQL。当前实现的第一组能力是个人办事/待办记录，覆盖创建、查询、完成和取消。

## 聊天触发示例

- `帮我创建一条待办：明天提交开题报告，紧急`
- `查看我的待办`
- `查看全部办事记录`
- `完成待办 1`
- `取消工单 #2`

命中这些意图时，Agent 会选择系统工具，普通教务问答仍然走知识库 RAG。

## 数据库表

### service_requests

用户级业务记录表。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | integer primary key | 业务记录 ID |
| user_id | integer | 所属用户 |
| category | text | 业务分类，例如学籍与培养、论文与学位、校园服务 |
| title | text | 记录标题 |
| details | text | 原始用户描述或补充信息 |
| status | text | open、done、cancelled |
| priority | text | low、normal、high |
| due_date | text | 可选 ISO 日期 |
| created_at | text | 创建时间 |
| updated_at | text | 更新时间 |

### agent_action_logs

Agent 工具调用审计表。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | integer primary key | 日志 ID |
| user_id | integer | 触发用户 |
| conversation_id | integer | 触发会话 |
| tool_name | text | 工具名称 |
| arguments_json | text | 工具入参 JSON |
| result_json | text | 工具返回 JSON |
| created_at | text | 调用时间 |

## HTTP 接口

- `GET /api/service-requests?status=open`
- `POST /api/service-requests`
- `PATCH /api/service-requests/{request_id}`

这些接口和聊天工具共用 `AppStore`，因此权限隔离和数据结构一致。
