# EduRAG-Agent Demo 展示脚本

## 1. 启动服务

```powershell
python -m app.cli ingest --input data/raw
uvicorn app.main:app --reload --port 8000
```

浏览器访问：

```text
http://127.0.0.1:8000
```

## 2. Web 工作台演示

1. 使用默认示例账号注册或登录。
2. 打开“智能问答”。
3. 提问：`CS599 大作业有哪些加分项？`
4. 展示回答中的 MCP、Agentic RAG、云服务器、生产级能力等关键词。
5. 点击“本轮检索来源”，说明答案不是纯生成，而是来自知识库证据。
6. 继续追问：`那这个项目已经做了哪个加分项？`
7. 展示多轮会话上下文和来源详情。

## 3. 真实资料演示

可依次提问：

```text
研究生因病想休学，一般需要准备什么材料和审批？
```

```text
论文盲审送审前一般要完成哪些检查？
```

```text
校外访问图书馆数据库时，VPN 或 WebVPN 使用上要注意什么？
```

展示重点：

- 知识库包含 `real_public_grad_service_knowledge.md`。
- 回答会引用公开资料摘要。
- 系统提醒具体办理以所在学校最新通知为准。

## 4. 知识库浏览演示

1. 打开“知识库浏览”。
2. 按分类筛选“学位论文”或“信息服务”。
3. 搜索关键词：`预答辩`、`VPN`、`国家奖学金`。
4. 点击知识卡片进入详情页。

## 5. 评估证据演示

运行：

```powershell
python -m app.cli eval --dataset app/eval/test_cases.json --output docs/evaluation_report.md
pytest
```

展示结果：

- 25 条评估用例。
- 平均关键词命中率 1.0。
- 平均来源命中率 1.0。
- 平均耗时约 1.8ms。
- 自动化测试 4 passed。

打开：

```text
docs/evaluation_report.md
```

## 6. MCP 加分项演示

启动 MCP Server：

```powershell
python -m app.mcp_server
```

说明：

- MCP Server 使用 stdio JSON-RPC。
- 暴露工具 `search_knowledge_base`。
- 外部 Agent 或 MCP Host 可以通过该工具调用同一个 RAG 检索能力。
- 测试文件 `tests/test_mcp_server.py` 已验证工具列表和工具调用。

## 7. 对评分点总结

| 评分项 | 展示材料 |
|---|---|
| 选题与设计思想 | 报告第一章、真实研究生教务场景 |
| Specs 规格设计 | `docs/product_spec.md`、`docs/architecture_spec.md`、`docs/api_spec.md` |
| 系统架构与设计 | Agentic RAG 架构图、状态机图 |
| 关键实现与代码 | `app/agent/graph.py`、`app/agent/tools.py`、`app/mcp_server.py` |
| 测试与评估 | `docs/evaluation_report.md`、`pytest` 输出 |
| 升级扩展设想 | 报告第六章 |
| 课程总结 | 报告第七章 |
| 加分项 | MCP Server、Agentic RAG、Web 工作台、评估闭环 |
