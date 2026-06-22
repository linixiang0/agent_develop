from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any

from app.agent.graph import EduRagAgent


def evaluate(agent: EduRagAgent, dataset_path: Path) -> dict[str, Any]:
    cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    results = []
    for case in cases:
        state = agent.run(case["question"], top_k=case.get("top_k", 4))
        source_text = "\n".join(item.chunk.text for item in state.evidence)
        source_titles = "\n".join(item.chunk.title for item in state.evidence)
        expected_keywords = case.get("expected_keywords", [])
        expected_sources = case.get("expected_sources", [])
        matched_keywords = [keyword for keyword in expected_keywords if keyword in state.answer or keyword in source_text]
        missing_keywords = [keyword for keyword in expected_keywords if keyword not in matched_keywords]
        matched_sources = [
            expected
            for expected in expected_sources
            if any(
                expected in (item.chunk.title or "")
                or expected in item.chunk.chunk_id
                or expected in str(item.chunk.metadata.get("path", ""))
                for item in state.evidence
            )
        ]
        missing_sources = [expected for expected in expected_sources if expected not in matched_sources]
        results.append(
            {
                "id": case.get("id"),
                "question": case["question"],
                "keyword_hit_rate": len(matched_keywords) / max(len(expected_keywords), 1),
                "source_hit_rate": len(matched_sources) / max(len(expected_sources), 1),
                "matched_keywords": matched_keywords,
                "missing_keywords": missing_keywords,
                "matched_sources": matched_sources,
                "missing_sources": missing_sources,
                "elapsed_ms": state.elapsed_ms,
                "provider": state.provider,
                "answer_excerpt": state.answer[:240],
                "sources": [
                    {
                        "chunk_id": item.chunk.chunk_id,
                        "title": item.chunk.title,
                        "score": round(item.score, 4),
                        "path": item.chunk.metadata.get("path"),
                    }
                    for item in state.evidence
                ],
                "source_titles": source_titles,
            }
        )

    return {
        "case_count": len(results),
        "avg_keyword_hit_rate": round(mean(item["keyword_hit_rate"] for item in results), 4) if results else 0,
        "avg_source_hit_rate": round(mean(item["source_hit_rate"] for item in results), 4) if results else 0,
        "avg_elapsed_ms": round(mean(item["elapsed_ms"] for item in results), 2) if results else 0,
        "results": results,
    }


def write_markdown_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# EduRAG-Agent 评估报告",
        "",
        "## 汇总指标",
        "",
        f"- 测试用例数：{report['case_count']}",
        f"- 平均关键词命中率：{report['avg_keyword_hit_rate']}",
        f"- 平均来源命中率：{report['avg_source_hit_rate']}",
        f"- 平均耗时：{report['avg_elapsed_ms']} ms",
        "",
        "## 明细",
        "",
        "| ID | 关键词命中率 | 来源命中率 | 耗时 ms | 命中关键词 | 缺失关键词 | 首个来源 |",
        "|---|---:|---:|---:|---|---|---|",
    ]
    for item in report["results"]:
        first_source = item["sources"][0]["title"] if item["sources"] else ""
        lines.append(
            "| {id} | {keyword:.2f} | {source:.2f} | {elapsed} | {matched} | {missing} | {first_source} |".format(
                id=_md_escape(str(item["id"])),
                keyword=item["keyword_hit_rate"],
                source=item["source_hit_rate"],
                elapsed=item["elapsed_ms"],
                matched=_md_escape("、".join(item["matched_keywords"])),
                missing=_md_escape("、".join(item["missing_keywords"]) or "-"),
                first_source=_md_escape(first_source),
            )
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
