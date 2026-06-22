from __future__ import annotations

import html
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_MD = ROOT / "docs" / "report.md"
REPORT_HTML = ROOT / "docs" / "CS599_大作业报告.html"
REPORT_PDF = ROOT / "docs" / "CS599_大作业报告.pdf"
RAW_PDF = ROOT / "docs" / "CS599_大作业报告.raw.pdf"


def main() -> None:
    markdown = REPORT_MD.read_text(encoding="utf-8")
    title, fields, content = split_cover(markdown)
    body, toc, headings = render_markdown(content)
    REPORT_HTML.write_text(render_page(title, fields, toc, body), encoding="utf-8")
    print(f"HTML: {REPORT_HTML}")

    browser = find_browser()
    if not browser:
        print("PDF: skipped, Edge/Chrome was not found.", file=sys.stderr)
        return
    render_pdf(browser)
    add_pdf_outline(REPORT_PDF, [(1, title), *headings])
    print(f"PDF:  {REPORT_PDF}")


def split_cover(markdown: str) -> tuple[str, list[tuple[str, str]], str]:
    lines = markdown.splitlines()
    title = "企业级应用软件设计与开发期末大作业报告"
    fields: list[tuple[str, str]] = []
    content_start = 0

    for index, line in enumerate(lines):
        if line.startswith("# "):
            title = line[2:].strip()
            content_start = index + 1
            break

    for index in range(content_start, len(lines)):
        line = lines[index].strip()
        if line.startswith("## "):
            content_start = index
            break
        if not line:
            continue
        key, sep, value = line.partition("：")
        if not sep:
            key, sep, value = line.partition(":")
        if sep and value.strip():
            fields.append((key.strip(), value.strip()))

    return title, fields, "\n".join(lines[content_start:])


def render_markdown(markdown: str) -> tuple[str, str, list[tuple[int, str]]]:
    lines = markdown.splitlines()
    blocks: list[str] = []
    toc_items: list[tuple[int, str, str]] = []
    headings: list[tuple[int, str]] = []
    paragraph: list[str] = []
    unordered_items: list[str] = []
    ordered_items: list[str] = []
    table_lines: list[str] = []
    in_code = False
    code_lang = ""
    code_lines: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(f"<p>{inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def flush_unordered() -> None:
        if unordered_items:
            blocks.append("<ul>" + "".join(f"<li>{inline(item)}</li>" for item in unordered_items) + "</ul>")
            unordered_items.clear()

    def flush_ordered() -> None:
        if ordered_items:
            blocks.append("<ol>" + "".join(f"<li>{inline(item)}</li>" for item in ordered_items) + "</ol>")
            ordered_items.clear()

    def flush_table() -> None:
        if table_lines:
            blocks.append(render_table(table_lines))
            table_lines.clear()

    def flush_lists_and_table() -> None:
        flush_unordered()
        flush_ordered()
        flush_table()

    for raw in lines:
        line = raw.rstrip()
        if line.startswith("```"):
            if in_code:
                if code_lang.startswith("diagram"):
                    name = code_lang.replace("diagram", "", 1).strip() or "architecture"
                    blocks.append(render_diagram(name))
                else:
                    blocks.append(
                        f'<pre><code class="language-{html.escape(code_lang)}">'
                        f"{html.escape(chr(10).join(code_lines))}</code></pre>"
                    )
                in_code = False
                code_lines.clear()
                code_lang = ""
            else:
                flush_paragraph()
                flush_lists_and_table()
                in_code = True
                code_lang = line.strip("`").strip()
            continue
        if in_code:
            code_lines.append(line)
            continue
        if not line:
            flush_paragraph()
            flush_lists_and_table()
            continue
        image = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", line)
        if image:
            flush_paragraph()
            flush_lists_and_table()
            alt = image.group(1).strip()
            src = image.group(2).strip()
            blocks.append(
                f'<figure class="screenshot"><img src="{html.escape(src)}" alt="{html.escape(alt)}">'
                f"<figcaption>{html.escape(alt)}</figcaption></figure>"
            )
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            flush_lists_and_table()
            level = len(heading.group(1))
            title = heading.group(2).strip()
            anchor = slugify(title)
            headings.append((level, title))
            if level <= 3:
                toc_items.append((level, title, anchor))
            blocks.append(f'<h{level} id="{anchor}">{inline(title)}</h{level}>')
            continue
        if line.startswith("|") and line.endswith("|"):
            flush_paragraph()
            flush_unordered()
            flush_ordered()
            table_lines.append(line)
            continue
        bullet = re.match(r"^-\s+(.+)$", line)
        if bullet:
            flush_paragraph()
            flush_ordered()
            flush_table()
            unordered_items.append(bullet.group(1))
            continue
        numbered = re.match(r"^\d+\.\s+(.+)$", line)
        if numbered:
            flush_paragraph()
            flush_unordered()
            flush_table()
            ordered_items.append(numbered.group(1))
            continue
        paragraph.append(line)

    flush_paragraph()
    flush_lists_and_table()
    toc = "<nav class=\"toc\"><h2>目录</h2>" + "".join(
        f'<a class="toc-l{level}" href="#{anchor}">{html.escape(title)}</a>'
        for level, title, anchor in toc_items
    ) + "</nav>"
    return "\n".join(blocks), toc, headings


def render_table(lines: list[str]) -> str:
    rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in lines]
    if len(rows) >= 2 and all(re.fullmatch(r":?-{3,}:?", cell) for cell in rows[1]):
        head, body = rows[0], rows[2:]
    else:
        head, body = [], rows
    parts = ["<table>"]
    if head:
        parts.append("<thead><tr>" + "".join(f"<th>{inline(cell)}</th>" for cell in head) + "</tr></thead>")
    if body:
        parts.append("<tbody>")
        for row in body:
            parts.append("<tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in row) + "</tr>")
        parts.append("</tbody>")
    parts.append("</table>")
    return "".join(parts)


def inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped.replace("  ", "<br>")


def slugify(text: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", text, flags=re.UNICODE).strip("-").lower()
    return cleaned or "section"


def render_diagram(name: str) -> str:
    diagrams = {
        "architecture": architecture_svg(),
        "agent": agent_svg(),
        "dataflow": dataflow_svg(),
        "evaluation": evaluation_svg(),
        "spec": spec_svg(),
        "implementation": implementation_svg(),
        "localtest": local_test_svg(),
        "qademo": qa_demo_svg(),
        "sourcedemo": source_demo_svg(),
        "deepseek": deepseek_svg(),
        "chatdb": chatdb_svg(),
        "dbschema": dbschema_svg(),
        "dbdemo": dbdemo_svg(),
        "dbtest": dbtest_svg(),
        "dbinteraction": dbinteraction_svg(),
    }
    return f'<figure class="diagram">{diagrams.get(name, architecture_svg())}</figure>'


def svg_text(x: int, y: int, text: str, size: int = 14, weight: str = "500") -> str:
    return f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" text-anchor="middle">{html.escape(text)}</text>'


def box(x: int, y: int, w: int, h: int, title: str, subtitle: str = "", fill: str = "#f8fafc") -> str:
    text = svg_text(x + w // 2, y + 27, title, 14, "700")
    if subtitle:
        text += svg_text(x + w // 2, y + 50, subtitle, 12, "400")
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="#64748b"/>{text}'


def arrow(x1: int, y1: int, x2: int, y2: int) -> str:
    return f'<path d="M{x1} {y1} L{x2} {y2}" stroke="#334155" stroke-width="1.8" fill="none" marker-end="url(#arrow)"/>'


def svg_defs() -> str:
    return (
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#334155"/></marker></defs>'
    )


def architecture_svg() -> str:
    return f"""
<svg viewBox="0 0 900 480" role="img" aria-label="EduRAG-Agent 系统架构图">
  {svg_defs()}
  <style>svg {{ font-family: "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif; }} text {{ fill: #0f172a; }}</style>
  {box(30, 40, 170, 70, "资料层", "课程 / 教务 / 校园", "#e0f2fe")}
  {box(250, 40, 150, 70, "Loader", "文档读取", "#fef3c7")}
  {box(450, 40, 150, 70, "Splitter", "文本切分", "#fef3c7")}
  {box(650, 40, 170, 70, "Vector Store", "本地检索索引", "#dcfce7")}
  {arrow(200, 75, 250, 75)}{arrow(400, 75, 450, 75)}{arrow(600, 75, 650, 75)}
  {box(30, 200, 170, 70, "入口层", "CLI / Web / MCP", "#ede9fe")}
  {box(250, 200, 170, 70, "EduRagAgent", "plan / act / observe", "#dbeafe")}
  {box(470, 200, 170, 70, "ToolRegistry", "工具 schema", "#fce7f3")}
  {box(690, 200, 170, 70, "Answer", "答案 + 来源", "#dcfce7")}
  {arrow(200, 235, 250, 235)}{arrow(420, 235, 470, 235)}{arrow(640, 235, 690, 235)}
  {arrow(555, 200, 720, 110)}{arrow(735, 110, 735, 200)}
  {box(250, 350, 170, 70, "AppStore", "用户 / 会话 / 待办", "#f1f5f9")}
  {box(470, 350, 170, 70, "JSONL Logs", "行为观测", "#f1f5f9")}
  {arrow(335, 270, 335, 350)}{arrow(420, 235, 555, 350)}
</svg>
"""


def agent_svg() -> str:
    return f"""
<svg viewBox="0 0 900 260" role="img" aria-label="Agent 状态机">
  {svg_defs()}
  <style>svg {{ font-family: "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif; }} text {{ fill: #0f172a; }}</style>
  {box(30, 90, 130, 70, "plan", "识别意图", "#dbeafe")}
  {box(210, 30, 140, 70, "retrieve", "检索证据", "#dcfce7")}
  {box(210, 150, 140, 70, "act", "系统工具", "#fce7f3")}
  {box(410, 90, 140, 70, "answer", "生成回答", "#fef3c7")}
  {box(610, 90, 140, 70, "observe", "日志记录", "#f1f5f9")}
  {box(800, 90, 70, 70, "done", "结束", "#e2e8f0")}
  {arrow(160, 112, 210, 68)}{arrow(160, 138, 210, 182)}
  {arrow(350, 65, 410, 112)}{arrow(350, 185, 410, 138)}
  {arrow(550, 125, 610, 125)}{arrow(750, 125, 800, 125)}
</svg>
"""


def dataflow_svg() -> str:
    return f"""
<svg viewBox="0 0 900 330" role="img" aria-label="数据流设计图">
  {svg_defs()}
  <style>svg {{ font-family: "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif; }} text {{ fill: #0f172a; }}</style>
  {box(40, 45, 170, 70, "data/raw", "原始资料", "#e0f2fe")}
  {box(270, 45, 150, 70, "Chunks", "结构化片段", "#fef3c7")}
  {box(480, 45, 170, 70, "vectorstore.json", "持久化索引", "#dcfce7")}
  {arrow(210, 80, 270, 80)}{arrow(420, 80, 480, 80)}
  {box(40, 205, 170, 70, "User Question", "自然语言问题", "#ede9fe")}
  {box(270, 205, 150, 70, "Retriever", "top_k 召回", "#dbeafe")}
  {box(480, 205, 170, 70, "Evidence", "chunk + score", "#fce7f3")}
  {box(710, 205, 150, 70, "Response", "答案 + 引用", "#dcfce7")}
  {arrow(210, 240, 270, 240)}{arrow(420, 240, 480, 240)}{arrow(650, 240, 710, 240)}
  {arrow(565, 115, 345, 205)}
</svg>
"""


def evaluation_svg() -> str:
    return f"""
<svg viewBox="0 0 900 270" role="img" aria-label="测试评估结果图">
  <style>svg {{ font-family: "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif; }} text {{ fill: #0f172a; }}</style>
  <rect x="40" y="40" width="820" height="190" rx="10" fill="#f8fafc" stroke="#cbd5e1"/>
  {svg_text(160, 95, "25", 34, "800")}{svg_text(160, 125, "评估用例", 14, "500")}
  {svg_text(365, 95, "1.00", 34, "800")}{svg_text(365, 125, "关键词命中率", 14, "500")}
  {svg_text(570, 95, "1.00", 34, "800")}{svg_text(570, 125, "来源命中率", 14, "500")}
  {svg_text(755, 95, "7 passed", 28, "800")}{svg_text(755, 125, "自动化测试", 14, "500")}
  <path d="M90 175 H810" stroke="#94a3b8" stroke-width="2"/>
  <circle cx="160" cy="175" r="9" fill="#2563eb"/><circle cx="365" cy="175" r="9" fill="#16a34a"/>
  <circle cx="570" cy="175" r="9" fill="#16a34a"/><circle cx="755" cy="175" r="9" fill="#7c3aed"/>
  {svg_text(450, 215, "评估同时检查答案事实与来源证据，避免只凭主观观感判断效果。", 14, "500")}
</svg>
"""


def spec_svg() -> str:
    return f"""
<svg viewBox="0 0 900 320" role="img" aria-label="SDD 规格到实现映射图">
  {svg_defs()}
  <style>svg {{ font-family: "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif; }} text {{ fill: #0f172a; }}</style>
  {box(40, 45, 190, 70, "Product Spec", "用户 / 痛点 / 指标", "#e0f2fe")}
  {box(40, 135, 190, 70, "Architecture Spec", "模块 / 状态 / 数据流", "#dcfce7")}
  {box(40, 225, 190, 70, "API Spec", "接口 / Schema / 错误", "#fef3c7")}
  {box(355, 45, 190, 70, "data/raw", "三类知识资料", "#f8fafc")}
  {box(355, 135, 190, 70, "app/agent", "状态机与工具", "#f8fafc")}
  {box(355, 225, 190, 70, "app/main.py", "Web API 与工作台", "#f8fafc")}
  {box(670, 90, 190, 70, "可执行系统", "CLI / Web / MCP", "#ede9fe")}
  {box(670, 195, 190, 70, "可评估产物", "pytest / eval report", "#fce7f3")}
  {arrow(230, 80, 355, 80)}{arrow(230, 170, 355, 170)}{arrow(230, 260, 355, 260)}
  {arrow(545, 80, 670, 125)}{arrow(545, 170, 670, 125)}{arrow(545, 260, 670, 230)}
</svg>
"""


def implementation_svg() -> str:
    return f"""
<svg viewBox="0 0 900 360" role="img" aria-label="关键实现结构图">
  {svg_defs()}
  <style>svg {{ font-family: "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif; }} text {{ fill: #0f172a; }}</style>
  {box(40, 45, 190, 70, "EduRagAgent", "plan / retrieve / act", "#dbeafe")}
  {box(355, 45, 190, 70, "ToolRegistry", "统一工具入口", "#fce7f3")}
  {box(670, 45, 190, 70, "Retriever", "知识库召回", "#dcfce7")}
  {box(40, 160, 190, 70, "LLM Router", "DeepSeek / local", "#ede9fe")}
  {box(355, 160, 190, 70, "AppStore", "用户 / 会话 / 待办", "#f8fafc")}
  {box(670, 160, 190, 70, "MCP Server", "stdio JSON-RPC", "#fef3c7")}
  {box(270, 275, 360, 55, "Observe", "写入 logs/interactions.jsonl，保留问题、来源、耗时、工具结果", "#e2e8f0")}
  {arrow(230, 80, 355, 80)}{arrow(545, 80, 670, 80)}
  {arrow(135, 115, 135, 160)}{arrow(450, 115, 450, 160)}{arrow(765, 115, 765, 160)}
  {arrow(135, 230, 330, 275)}{arrow(450, 230, 450, 275)}{arrow(765, 230, 570, 275)}
</svg>
"""


def local_test_svg() -> str:
    return f"""
<svg viewBox="0 0 900 280" role="img" aria-label="本地自动化测试结果图">
  <style>svg {{ font-family: "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif; }} text {{ fill: #0f172a; }}</style>
  <rect x="55" y="45" width="790" height="190" rx="10" fill="#f8fafc" stroke="#cbd5e1"/>
  {svg_text(190, 95, "RAG Pipeline", 18, "800")}{svg_text(190, 132, "2 passed", 28, "800")}{svg_text(190, 165, "导入 / 检索 / 回答", 13, "500")}
  {svg_text(450, 95, "MCP Server", 18, "800")}{svg_text(450, 132, "2 passed", 28, "800")}{svg_text(450, 165, "tools/list / tools/call", 13, "500")}
  {svg_text(710, 95, "Agent Actions", 18, "800")}{svg_text(710, 132, "3 passed", 28, "800")}{svg_text(710, 165, "创建 / 查询 / 完成待办", 13, "500")}
  <path d="M115 205 H785" stroke="#16a34a" stroke-width="4"/>
  {svg_text(450, 230, "pytest 总结果：7 passed，本地核心能力验证通过。", 14, "700")}
</svg>
"""


def qa_demo_svg() -> str:
    return """
<svg viewBox="0 0 900 440" role="img" aria-label="问答 Demo 展示图">
  <style>svg { font-family: "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif; } text { fill: #0f172a; }</style>
  <rect x="45" y="35" width="810" height="370" rx="10" fill="#f8fafc" stroke="#cbd5e1"/>
  <rect x="45" y="35" width="210" height="370" rx="10" fill="#eef2ff" stroke="#cbd5e1"/>
  <text x="75" y="75" font-size="22" font-weight="800">EduRAG-Agent</text>
  <text x="75" y="115" font-size="13">会话列表</text>
  <rect x="70" y="135" width="155" height="42" rx="6" fill="#dbeafe"/>
  <text x="148" y="162" text-anchor="middle" font-size="13">CS599 报告要求</text>
  <rect x="285" y="65" width="520" height="62" rx="8" fill="#e0f2fe" stroke="#bae6fd"/>
  <text x="310" y="92" font-size="14" font-weight="700">用户</text>
  <text x="310" y="114" font-size="14">报告 PDF 必须包含哪些章节？</text>
  <rect x="285" y="155" width="520" height="165" rx="8" fill="#ffffff" stroke="#cbd5e1"/>
  <text x="310" y="184" font-size="14" font-weight="700">Agent 回答</text>
  <text x="310" y="214" font-size="14">1. 选题背景与设计思想</text>
  <text x="310" y="238" font-size="14">2. Specs 规格文档</text>
  <text x="310" y="262" font-size="14">3. 系统架构与设计；4. 关键实现与代码展示</text>
  <text x="310" y="286" font-size="14">5. 测试与评估；6. 系统升级与扩展；7. 课程总结</text>
  <text x="310" y="308" font-size="13" fill="#2563eb">来源：资料1、资料3</text>
  <rect x="285" y="345" width="155" height="36" rx="6" fill="#2563eb"/>
  <text x="362" y="368" text-anchor="middle" font-size="14" fill="#ffffff">查看来源详情</text>
</svg>
"""


def source_demo_svg() -> str:
    return """
<svg viewBox="0 0 900 390" role="img" aria-label="来源详情 Demo 展示图">
  <style>svg { font-family: "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif; } text { fill: #0f172a; }</style>
  <rect x="50" y="40" width="800" height="300" rx="10" fill="#ffffff" stroke="#cbd5e1"/>
  <text x="85" y="82" font-size="22" font-weight="800">来源详情</text>
  <rect x="85" y="105" width="720" height="55" rx="8" fill="#f1f5f9" stroke="#cbd5e1"/>
  <text x="110" y="130" font-size="14" font-weight="700">资料1：cs599_course_requirements / 报告要求</text>
  <text x="110" y="150" font-size="12">path: data/raw/cs599_course_requirements.md ｜ score: 0.9913</text>
  <rect x="85" y="180" width="720" height="115" rx="8" fill="#f8fafc" stroke="#e2e8f0"/>
  <text x="110" y="212" font-size="14">报告章节要求：选题背景与设计思想、Specs 规格文档、系统架构与设计、</text>
  <text x="110" y="238" font-size="14">关键实现与代码展示、测试与评估、系统升级与扩展、课程总结。</text>
  <text x="110" y="264" font-size="14">PDF 必须包含可用导航窗格，便于评阅翻阅。</text>
  <rect x="640" y="305" width="165" height="34" rx="6" fill="#dcfce7" stroke="#86efac"/>
  <text x="722" y="327" text-anchor="middle" font-size="13" font-weight="700">证据可追溯</text>
</svg>
"""


def deepseek_svg() -> str:
    return f"""
<svg viewBox="0 0 900 360" role="img" aria-label="DeepSeek 联调测试结果图">
  <style>svg {{ font-family: "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif; }} text {{ fill: #0f172a; }}</style>
  <rect x="50" y="35" width="800" height="285" rx="10" fill="#f8fafc" stroke="#cbd5e1"/>
  {svg_text(450, 78, "DeepSeek API 联调通过", 24, "800")}
  {svg_text(180, 135, "4/4", 36, "800")}{svg_text(180, 168, "联调用例通过", 14, "500")}
  {svg_text(450, 135, "LLM + Tool", 24, "800")}{svg_text(450, 168, "问答生成与工具路由", 14, "500")}
  {svg_text(720, 135, "1.00", 36, "800")}{svg_text(720, 168, "关键词命中率", 14, "500")}
  <rect x="110" y="205" width="680" height="58" rx="8" fill="#ffffff" stroke="#cbd5e1"/>
  {svg_text(450, 230, "测试覆盖：报告章节、加分技术点、VPN 风险、聊天创建待办", 14, "700")}
  {svg_text(450, 253, "DeepSeek 负责答案生成和工具路由，数据库写入仍由受控后端执行。", 13, "500")}
</svg>
"""


def chatdb_svg() -> str:
    return f"""
<svg viewBox="0 0 900 360" role="img" aria-label="聊天操作数据库流程图">
  {svg_defs()}
  <style>svg {{ font-family: "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif; }} text {{ fill: #0f172a; }}</style>
  {box(35, 55, 170, 70, "聊天输入", "创建 / 查询 / 完成", "#e0f2fe")}
  {box(250, 55, 170, 70, "LLM Router", "DeepSeek 结构化意图", "#ede9fe")}
  {box(465, 55, 170, 70, "ToolRegistry", "受控工具调用", "#fce7f3")}
  {box(680, 55, 170, 70, "AppStore", "SQLite 读写", "#dcfce7")}
  {box(250, 210, 170, 70, "Fallback Rules", "无 Key 时本地规则", "#fef3c7")}
  {box(465, 210, 170, 70, "Action Answer", "执行结果格式化", "#f8fafc")}
  {box(680, 210, 170, 70, "Audit Log", "工具入参与结果", "#f1f5f9")}
  {arrow(205, 90, 250, 90)}{arrow(420, 90, 465, 90)}{arrow(635, 90, 680, 90)}
  {arrow(335, 125, 335, 210)}{arrow(765, 125, 765, 210)}
  {arrow(680, 245, 635, 245)}{arrow(465, 245, 420, 245)}
</svg>
"""


def dbschema_svg() -> str:
    return """
<svg viewBox="0 0 900 410" role="img" aria-label="数据库表设计图">
  <style>svg { font-family: "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif; } text { fill: #0f172a; }</style>
  <defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="#334155"/></marker></defs>
  <rect x="70" y="45" width="340" height="300" rx="10" fill="#f8fafc" stroke="#64748b"/>
  <text x="240" y="82" text-anchor="middle" font-size="20" font-weight="800">service_requests</text>
  <text x="105" y="120" font-size="14">id: integer primary key</text>
  <text x="105" y="148" font-size="14">user_id: 所属用户</text>
  <text x="105" y="176" font-size="14">category: 业务分类</text>
  <text x="105" y="204" font-size="14">title / details: 标题与描述</text>
  <text x="105" y="232" font-size="14">status: open / done / cancelled</text>
  <text x="105" y="260" font-size="14">priority: low / normal / high</text>
  <text x="105" y="288" font-size="14">due_date / created_at / updated_at</text>
  <rect x="490" y="45" width="340" height="300" rx="10" fill="#f8fafc" stroke="#64748b"/>
  <text x="660" y="82" text-anchor="middle" font-size="20" font-weight="800">agent_action_logs</text>
  <text x="525" y="120" font-size="14">id: integer primary key</text>
  <text x="525" y="148" font-size="14">user_id / conversation_id</text>
  <text x="525" y="176" font-size="14">tool_name: 工具名称</text>
  <text x="525" y="204" font-size="14">arguments_json: 结构化入参</text>
  <text x="525" y="232" font-size="14">result_json: 工具返回</text>
  <text x="525" y="260" font-size="14">created_at: 调用时间</text>
  <path d="M410 165 H490" stroke="#334155" stroke-width="2" marker-end="url(#arrow)"/>
  <text x="450" y="150" text-anchor="middle" font-size="13">审计</text>
</svg>
"""


def dbdemo_svg() -> str:
    return """
<svg viewBox="0 0 900 430" role="img" aria-label="聊天创建数据库记录 Demo 图">
  <style>svg { font-family: "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif; } text { fill: #0f172a; }</style>
  <rect x="45" y="35" width="810" height="350" rx="10" fill="#ffffff" stroke="#cbd5e1"/>
  <rect x="75" y="70" width="500" height="62" rx="8" fill="#e0f2fe" stroke="#bae6fd"/>
  <text x="100" y="96" font-size="14" font-weight="800">用户</text>
  <text x="100" y="118" font-size="14">帮我创建一条待办：明天提交开题报告，紧急</text>
  <rect x="75" y="160" width="500" height="92" rx="8" fill="#f8fafc" stroke="#cbd5e1"/>
  <text x="100" y="188" font-size="14" font-weight="800">Agent</text>
  <text x="100" y="214" font-size="14">已创建办事记录：#1 [open] 提交开题报告</text>
  <text x="100" y="238" font-size="13">分类：论文与学位 ｜ 优先级：high ｜ 截止：2026-06-23</text>
  <rect x="625" y="70" width="185" height="182" rx="8" fill="#dcfce7" stroke="#86efac"/>
  <text x="718" y="104" text-anchor="middle" font-size="16" font-weight="800">SQLite 写入</text>
  <text x="650" y="138" font-size="13">table: service_requests</text>
  <text x="650" y="164" font-size="13">status: open</text>
  <text x="650" y="190" font-size="13">priority: high</text>
  <text x="650" y="216" font-size="13">user_id: 当前用户</text>
  <rect x="75" y="285" width="735" height="55" rx="8" fill="#f1f5f9" stroke="#cbd5e1"/>
  <text x="442" y="318" text-anchor="middle" font-size="14" font-weight="700">聊天入口和办事待办页面共享同一份数据库记录</text>
</svg>
"""


def dbtest_svg() -> str:
    return """
<svg viewBox="0 0 900 300" role="img" aria-label="聊天操作数据库测试图">
  <style>svg { font-family: "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif; } text { fill: #0f172a; }</style>
  <rect x="55" y="45" width="790" height="200" rx="10" fill="#f8fafc" stroke="#cbd5e1"/>
  <text x="450" y="86" text-anchor="middle" font-size="22" font-weight="800">tests/test_agent_actions.py</text>
  <text x="185" y="145" text-anchor="middle" font-size="28" font-weight="800">创建</text>
  <text x="185" y="176" text-anchor="middle" font-size="13">create_service_request</text>
  <text x="450" y="145" text-anchor="middle" font-size="28" font-weight="800">查询</text>
  <text x="450" y="176" text-anchor="middle" font-size="13">list_service_requests</text>
  <text x="715" y="145" text-anchor="middle" font-size="28" font-weight="800">完成</text>
  <text x="715" y="176" text-anchor="middle" font-size="13">update_service_request</text>
  <path d="M120 215 H780" stroke="#16a34a" stroke-width="4"/>
  <text x="450" y="238" text-anchor="middle" font-size="14" font-weight="700">3 passed，并验证 LLM Router 优先于本地规则</text>
</svg>
"""


def dbinteraction_svg() -> str:
    return """
<svg viewBox="0 0 900 430" role="img" aria-label="聊天操作数据库交互展示图">
  <style>svg { font-family: "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif; } text { fill: #0f172a; }</style>
  <rect x="45" y="35" width="810" height="350" rx="10" fill="#ffffff" stroke="#cbd5e1"/>
  <rect x="65" y="55" width="250" height="310" rx="8" fill="#eef2ff" stroke="#cbd5e1"/>
  <text x="190" y="88" text-anchor="middle" font-size="18" font-weight="800">聊天可完成的操作</text>
  <text x="95" y="130" font-size="14">创建待办：提交开题报告</text>
  <text x="95" y="165" font-size="14">查看待办：查看我的待办</text>
  <text x="95" y="200" font-size="14">更新状态：完成待办 1</text>
  <text x="95" y="235" font-size="14">自动分类：论文与学位</text>
  <rect x="350" y="75" width="455" height="72" rx="8" fill="#f8fafc" stroke="#cbd5e1"/>
  <text x="380" y="105" font-size="15" font-weight="800">我的办事待办</text>
  <text x="380" y="130" font-size="14">#1 提交开题报告 ｜ open ｜ high ｜ 2026-06-23</text>
  <rect x="350" y="178" width="455" height="72" rx="8" fill="#dcfce7" stroke="#86efac"/>
  <text x="380" y="208" font-size="15" font-weight="800">聊天更新后</text>
  <text x="380" y="233" font-size="14">#1 提交开题报告 ｜ done ｜ high ｜ 2026-06-23</text>
  <rect x="350" y="282" width="455" height="45" rx="8" fill="#f1f5f9" stroke="#cbd5e1"/>
  <text x="578" y="310" text-anchor="middle" font-size="14" font-weight="700">聊天、HTTP API、页面列表三端数据一致</text>
</svg>
"""


def render_page(title: str, fields: list[tuple[str, str]], toc: str, body: str) -> str:
    field_rows = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(v)}</td></tr>" for k, v in fields)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>CS599 大作业报告 - EduRAG-Agent</title>
  <style>
    @page {{ size: A4; margin: 18mm 16mm; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; color: #111827; font-family: "Microsoft YaHei", "Noto Sans CJK SC", "SimSun", Arial, sans-serif; line-height: 1.68; }}
    main {{ max-width: 920px; margin: 0 auto; }}
    .cover {{ min-height: 255mm; display: flex; flex-direction: column; justify-content: center; page-break-after: always; }}
    .cover h1 {{ font-size: 30px; text-align: center; margin: 0 0 36px; letter-spacing: 0; }}
    .cover table {{ width: 78%; margin: 0 auto; font-size: 17px; }}
    .cover th {{ width: 28%; background: #eef2f7; text-align: left; }}
    h2 {{ font-size: 22px; margin-top: 28px; border-bottom: 1px solid #cbd5e1; padding-bottom: 6px; page-break-after: avoid; }}
    h3 {{ font-size: 17px; margin-top: 20px; color: #0f172a; page-break-after: avoid; }}
    p {{ margin: 8px 0; text-align: justify; }}
    ul, ol {{ margin: 8px 0 12px 22px; padding: 0; }}
    li {{ margin: 4px 0; }}
    code {{ background: #f2f4f8; border: 1px solid #e2e8f0; border-radius: 4px; padding: 1px 4px; font-family: Consolas, monospace; }}
    pre {{ background: #f8fafc; border: 1px solid #dbe3ef; border-radius: 6px; padding: 12px; overflow: auto; white-space: pre-wrap; }}
    pre code {{ background: transparent; border: 0; padding: 0; }}
    table {{ width: 100%; border-collapse: collapse; margin: 10px 0 16px; font-size: 14px; page-break-inside: avoid; }}
    th, td {{ border: 1px solid #cbd5e1; padding: 7px 9px; vertical-align: top; }}
    th {{ background: #eef2f7; }}
    .toc {{ border: 1px solid #cbd5e1; background: #f8fafc; padding: 18px 22px; margin: 0 0 24px; page-break-after: always; }}
    .toc h2 {{ margin-top: 0; border-bottom: 0; }}
    .toc a {{ display: block; color: #1d4ed8; text-decoration: none; margin: 4px 0; }}
    .toc-l3 {{ padding-left: 20px; font-size: 14px; }}
    .diagram {{ margin: 12px 0 18px; page-break-inside: avoid; }}
    .diagram svg {{ width: 100%; height: auto; display: block; }}
    .screenshot {{ margin: 12px 0 18px; page-break-inside: avoid; }}
    .screenshot img {{ width: 100%; border: 1px solid #cbd5e1; border-radius: 8px; display: block; }}
    .screenshot figcaption {{ color: #475569; font-size: 13px; text-align: center; margin-top: 6px; }}
    @media print {{ a {{ color: inherit; }} }}
  </style>
</head>
<body>
  <main>
    <section class="cover">
      <h1>{html.escape(title)}</h1>
      <table>{field_rows}</table>
    </section>
    {toc}
    {body}
  </main>
</body>
</html>
"""


def find_browser() -> str | None:
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        shutil.which("msedge"),
        shutil.which("chrome"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def render_pdf(browser: str) -> None:
    if RAW_PDF.exists():
        RAW_PDF.unlink()
    command = [
        browser,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--no-pdf-header-footer",
        f"--print-to-pdf={RAW_PDF}",
        REPORT_HTML.resolve().as_uri(),
    ]
    subprocess.run(command, check=True)
    RAW_PDF.replace(REPORT_PDF)


def add_pdf_outline(pdf_path: Path, headings: list[tuple[int, str]]) -> None:
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        print("PDF outline: skipped, pypdf is not installed.", file=sys.stderr)
        return

    reader = PdfReader(pdf_path)
    page_texts = [normalize_text(page.extract_text() or "") for page in reader.pages]
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.add_metadata(
        {
            "/Title": "CS599 大作业报告 - EduRAG-Agent",
            "/Author": "黎逆翔",
            "/Subject": "企业级应用软件设计与开发期末大作业报告",
        }
    )

    parents: dict[int, object] = {}
    last_page = 0
    for level, title in headings:
        page_index = find_heading_page(page_texts, title, last_page)
        last_page = max(last_page, page_index)
        parent = parents.get(level - 1)
        item = writer.add_outline_item(title, page_index, parent=parent)
        parents[level] = item
        for deeper in [key for key in parents if key > level]:
            parents.pop(deeper, None)

    tmp_path = pdf_path.with_suffix(".outlined.pdf")
    with tmp_path.open("wb") as output:
        writer.write(output)
    tmp_path.replace(pdf_path)


def normalize_text(text: str) -> str:
    replacements = {
        "\u2f24": "大",
        "\u2f00": "一",
        "\u2f06": "二",
        "\u2f08": "人",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return re.sub(r"\s+", "", text)


def find_heading_page(page_texts: list[str], title: str, start_page: int) -> int:
    needle = normalize_text(title)
    for index in range(start_page, len(page_texts)):
        if needle in page_texts[index]:
            return index
    for index, page_text in enumerate(page_texts):
        if needle in page_text:
            return index
    return min(start_page, max(0, len(page_texts) - 1))


if __name__ == "__main__":
    main()
