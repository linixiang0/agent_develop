# EduRAG-Agent

面向研究生教务与课程资料的智能问答 Agent。项目用于《企业级应用软件设计与开发》CS599 期末大作业，方向一：Agentic AI 原生开发。

## 项目价值

传统教务资料分散在课程通知、培养方案、作业要求和 FAQ 中，学生需要人工翻找。EduRAG-Agent 通过 Agentic RAG 架构，把本地课程资料构建为可检索知识库，并让 Agent 根据问题自动执行检索、证据整理、答案生成和日志记录。

## 核心能力

- 文档导入：支持 Markdown、TXT，安装 `pypdf` 后支持 PDF。
- 本地向量检索：无需 API Key 即可运行 Demo。
- Agent 状态机：`plan -> retrieve -> answer -> observe`。
- 工具调用：通过 `ToolRegistry` 暴露 `search_knowledge_base` 等工具。
- MCP 加分项：`python -m app.mcp_server` 可通过 stdio 暴露知识库检索工具。
- 真实资料扩展：`data/raw/real_public_grad_service_knowledge.md` 整理公开研究生教务、论文、奖助、图书馆、信息化服务资料。
- Web 工作台：支持注册登录、多轮会话、知识库浏览、来源详情查看。
- 可观测性：记录问题、检索来源、耗时和回答到 `logs/interactions.jsonl`。
- 评估脚本：基于 25 条测试集计算来源命中率、关键词命中率和平均耗时，并生成 `docs/evaluation_report.md`。
- 可选 LLM：配置 DeepSeek/OpenAI 兼容接口后生成更自然答案。

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

构建知识库：

```powershell
python -m app.cli ingest --input data/raw
```

命令行提问：

```powershell
python -m app.cli ask "期末大作业截止时间是什么？"
```

运行 Web API：

```powershell
uvicorn app.main:app --reload --port 8000
```

访问：

- `GET http://127.0.0.1:8000/health`
- `POST http://127.0.0.1:8000/api/ask`

请求示例：

```json
{
  "question": "报告 PDF 必须包含哪些章节？",
  "top_k": 4
}
```

运行评估：

```powershell
python -m app.cli eval --dataset app/eval/test_cases.json
pytest
```

启动 MCP Server：

```powershell
python -m app.mcp_server
```

MCP Host 可调用工具：

- `search_knowledge_base(query: string, top_k?: integer)`

Docker 部署：

```powershell
docker compose up --build
```

## 技术要素对应

| 课程要求 | 项目实现 |
|---|---|
| SDD 规格驱动开发 | `docs/product_spec.md`、`docs/architecture_spec.md`、`docs/api_spec.md` |
| 工具使用 / Function Calling / MCP | `app/agent/tools.py` 工具注册和调用，`app/mcp_server.py` 对外暴露 MCP 工具 |
| 记忆机制 | `data/processed/vectorstore.json` 本地向量知识库，包含课程要求、公开教务资料和演示校园服务资料 |
| 状态管理与多步骤推理 | `app/agent/graph.py` Agent 状态机 |
| 可观测性与评估 | `logs/interactions.jsonl`、`app/eval/evaluator.py`、`docs/evaluation_report.md` |
| Agentic RAG | 检索、证据压缩、答案生成、来源引用闭环 |

## 资料来源说明

知识库包含三类资料：

1. `data/raw/cs599_course_requirements.md`：课程项目要求与评分点摘要。
2. `data/raw/real_public_grad_service_knowledge.md`：根据教育部规章、高校公开办事指南和信息化/图书馆公开说明整理的摘要资料。
3. `data/raw/synthetic_campus_knowledge.md`：用于扩充演示覆盖面的合成校园服务条目。

Agent 回答一般教务问题时会提醒以所在学校最新通知为准；回答 CS599 项目问题时优先引用课程要求资料。

## 目录结构

```text
.
├── app/
│   ├── agent/
│   ├── core/
│   ├── eval/
│   ├── llm/
│   └── rag/
├── data/
│   ├── raw/
│   └── processed/
├── docs/
├── tests/
├── README.md
├── requirements.txt
└── .env.example
```

## 学术纪律说明

本项目代码为课程大作业实现。使用的第三方依赖已在 `requirements.txt` 标注；API Key 仅通过 `.env` 环境变量读取，不会写入代码仓库。
