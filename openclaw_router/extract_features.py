#!/usr/bin/env python3
"""CLI for feature extraction."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console
from rich.table import Table

from src.feature import FeatureExtractor

console = Console()


def _preview_embedding(embedding: list[float], head: int = 5) -> str:
    shown = ", ".join(f"{v:.3f}" for v in embedding[:head])
    return f"[{shown}, ..., {embedding[-1]:.3f}]"


def cmd_extract(args: argparse.Namespace) -> None:
    extractor = FeatureExtractor()
    feature = extractor.extract(args.text)

    table = Table(title="Feature Vector", show_header=True)
    table.add_column("字段", style="cyan")
    table.add_column("值")
    table.add_row("embedding_dim", str(len(feature.embedding)))
    table.add_row("embedding_backend", feature.metadata.get("backend", "unknown"))
    table.add_row("embedding_preview", _preview_embedding(feature.embedding))
    table.add_row("token_count", str(feature.token_count))
    table.add_row("char_count", str(feature.char_count))
    table.add_row("sentence_count", str(feature.sentence_count))
    table.add_row("reasoning_keyword_count", str(feature.reasoning_keyword_count))
    console.print(table)

    if args.output:
        payload = feature.to_dict()
        Path(args.output).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        console.print(f"[green]Saved to {args.output}[/green]")
    elif args.full:
        console.print_json(data=feature.to_dict())


def cmd_batch(args: argparse.Namespace) -> None:
    queries = Path(args.file).read_text(encoding="utf-8").strip().splitlines()
    queries = [q.strip() for q in queries if q.strip()]
    extractor = FeatureExtractor()
    batch = extractor.extract_batch(queries)

    rows = []
    for query, feature in zip(queries, batch):
        rows.append(
            {
                "query": query,
                "token_count": feature.token_count,
                "char_count": feature.char_count,
                "sentence_count": feature.sentence_count,
                "reasoning_keyword_count": feature.reasoning_keyword_count,
                "embedding_dim": len(feature.embedding),
            }
        )

    if args.output:
        Path(args.output).write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        console.print(f"[green]Saved {len(rows)} feature rows to {args.output}[/green]")
    else:
        console.print_json(data=rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Feature extraction CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_extract = sub.add_parser("extract", help="Extract features from one query")
    p_extract.add_argument("text", help="Input query")
    p_extract.add_argument("--output", "-o", help="Save full feature JSON")
    p_extract.add_argument("--full", action="store_true", help="Print full JSON to stdout")
    p_extract.set_defaults(func=cmd_extract)

    p_batch = sub.add_parser("batch", help="Extract features from a query file")
    p_batch.add_argument("--file", required=True, help="One query per line")
    p_batch.add_argument("--output", "-o", help="Save summary JSON")
    p_batch.set_defaults(func=cmd_batch)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
