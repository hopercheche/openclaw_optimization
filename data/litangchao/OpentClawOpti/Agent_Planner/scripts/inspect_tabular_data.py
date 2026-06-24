#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Arrow/Parquet planner datasets.")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--rows", type=int, default=2)
    args = parser.parse_args()

    try:
        import pyarrow as pa  # noqa: F401
        import pyarrow.ipc as ipc
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SystemExit("pyarrow is required. Install it with: .venv/bin/python -m pip install pyarrow") from exc

    for path in args.paths:
        if path.is_dir():
            files = sorted([*path.glob("*.arrow"), *path.glob("*.parquet")])
        else:
            files = [path]
        for file_path in files:
            print(f"# {file_path}")
            if file_path.suffix == ".parquet":
                table = pq.read_table(file_path)
            elif file_path.suffix == ".arrow":
                table = _read_arrow_table(file_path, ipc)
            else:
                print("unsupported file suffix")
                continue
            print(table.schema)
            for row in table.slice(0, args.rows).to_pylist():
                print(json.dumps(row, ensure_ascii=False)[:2000])


def _read_arrow_table(path: Path, ipc):
    with path.open("rb") as handle:
        try:
            return ipc.open_file(handle).read_all()
        except Exception:
            handle.seek(0)
            return ipc.open_stream(handle).read_all()


if __name__ == "__main__":
    main()
