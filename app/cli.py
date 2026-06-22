from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.config import settings
from app.eval.evaluator import evaluate, write_markdown_report
from app.factory import build_agent
from app.rag.loader import load_documents
from app.rag.seeder import write_seed_markdown
from app.rag.splitter import split_documents
from app.rag.vectorstore import LocalVectorStore


def main() -> None:
    parser = argparse.ArgumentParser(description="EduRAG-Agent command line interface")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Build local vector store from documents")
    ingest_parser.add_argument("--input", default="data/raw", help="Input file or directory")

    seed_parser = subparsers.add_parser("seed", help="Generate synthetic but reasonable campus knowledge data")
    seed_parser.add_argument("--count", type=int, default=220)
    seed_parser.add_argument("--output", default="data/raw/synthetic_campus_knowledge.md")

    ask_parser = subparsers.add_parser("ask", help="Ask a question")
    ask_parser.add_argument("question")
    ask_parser.add_argument("--top-k", type=int, default=4)

    eval_parser = subparsers.add_parser("eval", help="Evaluate question answering behavior")
    eval_parser.add_argument("--dataset", default="app/eval/test_cases.json")
    eval_parser.add_argument("--output", default="docs/evaluation_report.md")

    args = parser.parse_args()
    if args.command == "ingest":
        ingest(Path(args.input))
    elif args.command == "seed":
        seed(args.count, Path(args.output))
    elif args.command == "ask":
        ask(args.question, args.top_k)
    elif args.command == "eval":
        run_eval(Path(args.dataset), Path(args.output))


def ingest(input_path: Path) -> None:
    documents = load_documents(input_path)
    chunks = split_documents(documents)
    vectorstore = LocalVectorStore(settings.vectorstore_path)
    vectorstore.build(chunks)
    vectorstore.save()
    print(json.dumps({"documents": len(documents), "chunks": len(chunks), "path": str(settings.vectorstore_path)}, ensure_ascii=False, indent=2))


def seed(count: int, output_path: Path) -> None:
    path = write_seed_markdown(output_path, count=count)
    print(json.dumps({"records": count, "path": str(path)}, ensure_ascii=False, indent=2))


def ask(question: str, top_k: int) -> None:
    agent = build_agent()
    state = agent.run(question, top_k=top_k)
    print(state.answer)
    if state.evidence:
        print("\n检索来源：")
        for item in state.evidence:
            print(f"- {item.chunk.chunk_id} {item.chunk.title} score={item.score:.4f}")


def run_eval(dataset_path: Path, output_path: Path) -> None:
    agent = build_agent()
    report = evaluate(agent, dataset_path)
    write_markdown_report(report, output_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
