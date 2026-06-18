#!/usr/bin/env python3
"""The Strategist MVP — CLI Demo & Benchmark."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.config import get_provider_mode
from src.evaluation import build_report
from src.pipeline import InferencePipeline

console = Console()

SAMPLE_QUERIES = [
    "今天天气怎么样？",
    "什么是机器学习？",
    "请解释为什么梯度下降在凸优化问题中能够收敛到全局最优。",
    "Compare and contrast supervised learning vs unsupervised learning, and explain when to use each approach.",
    "Prove that the square root of 2 is irrational using proof by contradiction.",
    """Analyze the following Python code and explain why it might cause a memory leak:

```python
class Cache:
    _store = {}
    def add(self, key, obj):
        self._store[key] = obj
        obj.cache = self
```

Also discuss how to fix it and compare with weak references.""",
]


def print_result(result) -> None:
    r = result.routing
    resp = result.response
    table = Table(title="路由决策", show_header=True)
    table.add_column("字段", style="cyan")
    table.add_column("值")
    table.add_row("目标模型", f"[bold]{r.tier.value.upper()}[/bold] ({resp.model})")
    table.add_row("置信度", f"{r.confidence:.1%}")
    table.add_row("关键词得分", str(r.scores["keyword"]))
    table.add_row("长度得分", str(r.scores["length"]))
    table.add_row("复杂度得分", str(r.scores["complexity"]))
    table.add_row("综合得分", str(r.scores["combined"]))
    console.print(table)

    console.print("\n[bold]路由原因:[/bold]")
    for reason in r.reasons:
        console.print(f"  • {reason}")

    console.print(Panel(resp.content, title=f"回答 ({resp.model})", border_style="green"))
    console.print(
        f"[dim]延迟: {resp.latency_ms:.0f}ms | "
        f"Tokens: {resp.total_tokens} | "
        f"成本: ${resp.cost_usd:.6f}[/dim]\n"
    )


def cmd_query(args: argparse.Namespace) -> None:
    pipeline = InferencePipeline()
    console.print(f"[dim]Provider: {get_provider_mode()}[/dim]\n")
    result = pipeline.run(args.text)
    print_result(result)


def cmd_demo(args: argparse.Namespace) -> None:
    pipeline = InferencePipeline()
    console.print(Panel(
        "[bold]The Strategist MVP Demo[/bold]\n"
        "Rule-based LLM Routing — 输入 → 路由 → 模型调用 → 输出",
        border_style="blue",
    ))
    console.print(f"[dim]Provider: {get_provider_mode()}[/dim]\n")

    results = []
    for i, q in enumerate(SAMPLE_QUERIES, 1):
        console.rule(f"Query {i}/{len(SAMPLE_QUERIES)}")
        console.print(f"[bold]输入:[/bold] {q[:120]}{'...' if len(q) > 120 else ''}\n")
        result = pipeline.run(q)
        print_result(result)
        results.append(result)

    report = build_report(results)
    summary = report.to_dict()
    console.rule("Benchmark Summary")
    console.print(json.dumps(summary, indent=2, ensure_ascii=False))


def cmd_benchmark(args: argparse.Namespace) -> None:
    pipeline = InferencePipeline()
    queries = SAMPLE_QUERIES
    if args.file:
        queries = Path(args.file).read_text(encoding="utf-8").strip().split("\n")
        queries = [q.strip() for q in queries if q.strip()]

    results = [pipeline.run(q) for q in queries]
    report = build_report(results)
    output = report.to_dict()

    if args.output:
        Path(args.output).write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
        console.print(f"[green]Report saved to {args.output}[/green]")
    else:
        console.print(json.dumps(output, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="The Strategist MVP — Rule-based LLM Router")
    sub = parser.add_subparsers(dest="command", required=True)

    p_query = sub.add_parser("query", help="Route and answer a single query")
    p_query.add_argument("text", help="User query text")
    p_query.set_defaults(func=cmd_query)

    p_demo = sub.add_parser("demo", help="Run demo with sample queries")
    p_demo.set_defaults(func=cmd_demo)

    p_bench = sub.add_parser("benchmark", help="Run benchmark and output metrics")
    p_bench.add_argument("--file", help="File with one query per line")
    p_bench.add_argument("--output", "-o", help="Save JSON report to file")
    p_bench.set_defaults(func=cmd_benchmark)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
