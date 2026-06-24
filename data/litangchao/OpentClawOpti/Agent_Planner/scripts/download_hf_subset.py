#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_MANIFEST = Path(__file__).resolve().parents[1] / "configs" / "dataset_manifest.json"
HF_API_ROOT = "https://huggingface.co/api/datasets"
HF_RESOLVE_ROOT = "https://huggingface.co/datasets"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download selected Hugging Face dataset files without cloning a full repo.",
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source", required=True, help="Source key in dataset_manifest.json")
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-cache", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limit-files", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.2, help="Seconds between file downloads")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    source = manifest["sources"].get(args.source)
    if not source:
        available = ", ".join(sorted(manifest["sources"]))
        raise SystemExit(f"Unknown source {args.source!r}. Available: {available}")

    repo_id = source["repo_id"]
    revision = source.get("revision", "main")
    selected = _select_files(repo_id, source, include_cache=args.include_cache)
    if args.limit_files:
        selected = selected[: args.limit_files]

    expected_gib = source.get("reported_subset_size_gib")
    if expected_gib and float(expected_gib) > float(manifest.get("size_limit_gib", 50)):
        raise SystemExit(f"Refusing to download {expected_gib} GiB; exceeds manifest limit")

    target_dir = args.target_root / args.source
    print(json.dumps({
        "source": args.source,
        "repo_id": repo_id,
        "revision": revision,
        "target_dir": str(target_dir),
        "file_count": len(selected),
        "dry_run": args.dry_run,
        "include_cache": args.include_cache,
        "reported_subset_size_gib": expected_gib,
    }, ensure_ascii=False, indent=2))

    for rfilename in selected:
        dest = target_dir / rfilename
        url = _resolve_url(repo_id, revision, rfilename)
        print(f"{'DRY ' if args.dry_run else ''}{rfilename}")
        if args.dry_run:
            continue
        _download(url, dest, force=args.force)
        if args.sleep:
            time.sleep(args.sleep)


def _select_files(repo_id: str, source: dict[str, Any], *, include_cache: bool) -> list[str]:
    metadata = _fetch_json(f"{HF_API_ROOT}/{repo_id}")
    prefixes = source.get("selected_prefixes") or []
    all_files = [item["rfilename"] for item in metadata.get("siblings", [])]
    selected: list[str] = []
    for rfilename in all_files:
        if rfilename == ".gitattributes":
            continue
        if not _matches(rfilename, prefixes):
            continue
        name = Path(rfilename).name
        if not include_cache and name.startswith("cache-"):
            continue
        selected.append(rfilename)
    return selected


def _matches(rfilename: str, prefixes: list[str]) -> bool:
    if not prefixes:
        return True
    for prefix in prefixes:
        if prefix.endswith("/"):
            if rfilename.startswith(prefix):
                return True
        elif rfilename == prefix:
            return True
    return False


def _fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "openclaw-agent-planner/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _resolve_url(repo_id: str, revision: str, rfilename: str) -> str:
    quoted_repo = "/".join(urllib.parse.quote(part, safe="") for part in repo_id.split("/"))
    quoted_file = "/".join(urllib.parse.quote(part, safe="") for part in rfilename.split("/"))
    quoted_revision = urllib.parse.quote(revision, safe="")
    return f"{HF_RESOLVE_ROOT}/{quoted_repo}/resolve/{quoted_revision}/{quoted_file}"


def _download(url: str, dest: Path, *, force: bool) -> None:
    if dest.exists() and dest.stat().st_size > 0 and not force:
        print(f"skip existing {dest}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp_dest = dest.with_suffix(dest.suffix + ".part")
    if force and temp_dest.exists():
        temp_dest.unlink()

    resume_from = temp_dest.stat().st_size if temp_dest.exists() and not force else 0
    headers = {"User-Agent": "openclaw-agent-planner/0.1"}
    if resume_from:
        headers["Range"] = f"bytes={resume_from}-"
        print(f"resume {dest} from {_format_bytes(resume_from)}")
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            append = resume_from > 0 and response.getcode() == 206
            if resume_from and not append:
                print(f"server did not resume {dest}; restarting partial download")
                resume_from = 0
            mode = "ab" if append else "wb"
            downloaded = resume_from
            next_report = downloaded + 256 * 1024 * 1024
            with temp_dest.open(mode) as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if downloaded >= next_report:
                        print(f"  {dest.name}: {_format_bytes(downloaded)}")
                        next_report = downloaded + 256 * 1024 * 1024
        print(f"complete {dest} ({_format_bytes(temp_dest.stat().st_size)})")
        os.replace(temp_dest, dest)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SystemExit(f"Download failed for {url}: {exc}; partial kept at {temp_dest}") from exc


def _format_bytes(value: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    amount = float(value)
    for unit in units:
        if amount < 1024.0 or unit == units[-1]:
            return f"{amount:.1f}{unit}"
        amount /= 1024.0


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("Interrupted")
