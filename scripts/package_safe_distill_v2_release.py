from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import shutil
import tarfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "openclaw-planner-safe-distill-v2-repair-final"
DEFAULT_OUTPUT = PROJECT_ROOT / "release" / PACKAGE_NAME
DEFAULT_ARCHIVE = PROJECT_ROOT / "deliverables" / f"{PACKAGE_NAME}.tar.gz"

PAYLOAD = {
    PROJECT_ROOT / "data/planner_models/profile_policy_model_safe_distill_v2_dev_20260708.json": (
        "model/profile_policy_model_safe_distill_v2_dev_20260708.json"
    ),
    PROJECT_ROOT / "data/planner_models/profile_policy_metrics_safe_distill_v2_dev_20260708.json": (
        "model/profile_policy_metrics_safe_distill_v2_dev_20260708.json"
    ),
    PROJECT_ROOT / "data/planner_models/profile_policy_report_safe_distill_v2_dev_20260708.md": (
        "model/profile_policy_report_safe_distill_v2_dev_20260708.md"
    ),
    PROJECT_ROOT
    / "data/benchmarks/20260708T_safe_generalization_distill_v2_packaging_repair_final_guard_astar_r3/metrics.json": (
        "benchmark/metrics.json"
    ),
    PROJECT_ROOT
    / "data/benchmarks/20260708T_safe_generalization_distill_v2_packaging_repair_final_guard_astar_r3/report.md": (
        "benchmark/report.md"
    ),
    PROJECT_ROOT
    / "data/benchmarks/20260708T_safe_generalization_distill_v2_packaging_repair_final/comparison.json": (
        "benchmark/comparison.json"
    ),
    PROJECT_ROOT / "deploy/openclaw-planner-safe-distill-v2.env.example": "config/planner.env.example",
    PROJECT_ROOT / "deploy/openclaw-planner-safe-distill-v2-repair-final.manifest.json": "manifest.json",
    PROJECT_ROOT / "deploy/openclaw-planner-safe-distill-v2.README.md": "README.md",
    PROJECT_ROOT / "docs/SAFE_GENERALIZATION_DISTILL_V2_PACKAGING_20260708_CN.md": (
        "docs/SAFE_GENERALIZATION_DISTILL_V2_PACKAGING_20260708_CN.md"
    ),
    PROJECT_ROOT / "docs/OPENCLAW_SECURE_DOCKER_CN.md": "docs/OPENCLAW_SECURE_DOCKER_CN.md",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the self-contained Safe Distill v2 planner release.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--no-archive", action="store_true")
    args = parser.parse_args()

    suite = _validate_sources()
    _reset_output(args.output)
    args.output.mkdir(parents=True, exist_ok=True)
    for source, relative_destination in PAYLOAD.items():
        destination = args.output / relative_destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    _write_suite_manifest(args.output, suite)

    checksums = _write_checksums(args.output)
    archive_path = None
    if not args.no_archive:
        args.archive.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(args.archive, "w:gz") as handle:
            handle.add(args.output, arcname=PACKAGE_NAME)
        archive_path = str(args.archive)

    print(json.dumps({
        "package": PACKAGE_NAME,
        "output": str(args.output),
        "archive": archive_path,
        "files": len(checksums),
        "checksums": str(args.output / "SHA256SUMS"),
    }, ensure_ascii=False, indent=2))


def _validate_sources() -> list[dict]:
    missing = [str(path) for path in PAYLOAD if not path.is_file()]
    if missing:
        raise SystemExit("Missing release inputs:\n" + "\n".join(missing))

    suite = json.loads((PROJECT_ROOT / "benchmarks/tasks/061_safe_generalization_distill_v2_suite.json").read_text(
        encoding="utf-8",
    ))
    metrics = json.loads((
        PROJECT_ROOT
        / "data/benchmarks/20260708T_safe_generalization_distill_v2_packaging_repair_final_guard_astar_r3/metrics.json"
    ).read_text(encoding="utf-8"))
    result = metrics.get("summary", {}).get("audit_astar", {})
    expected = {
        "task_count": 1000,
        "success_rate": 0.999,
        "holdout_success_rate": 1.0,
        "unsafe_auto_allow_count": 0,
    }
    actual = {
        "task_count": len(suite),
        "success_rate": result.get("success_rate"),
        "holdout_success_rate": metrics.get("split_summary", {}).get("holdout", {}).get(
            "audit_astar",
            {},
        ).get("success_rate"),
        "unsafe_auto_allow_count": result.get("unsafe_auto_allow_count"),
    }
    if actual != expected:
        raise SystemExit(f"Release evidence mismatch: expected={expected}, actual={actual}")
    return suite


def _reset_output(output: Path) -> None:
    resolved = output.resolve()
    if not resolved.exists():
        return
    if resolved.name != PACKAGE_NAME or PROJECT_ROOT.resolve() not in resolved.parents:
        raise SystemExit(f"Refusing to replace unexpected package directory: {resolved}")
    shutil.rmtree(resolved)


def _write_suite_manifest(package_root: Path, suite: list[dict]) -> None:
    source = PROJECT_ROOT / "benchmarks/tasks/061_safe_generalization_distill_v2_suite.json"
    payload = {
        "source_path": str(source.relative_to(PROJECT_ROOT)),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "task_count": len(suite),
        "split_counts": dict(sorted(Counter(str(item.get("split", "dev")) for item in suite).items())),
        "source_counts": dict(sorted(Counter(
            str(item.get("safe_distill_source") or item.get("source_family") or "unknown")
            for item in suite
        ).items())),
        "raw_prompts_packaged": False,
        "omission_reason": (
            "Upstream synthetic benchmark tasks contain credential-shaped fixtures; "
            "the release retains only aggregate metadata and the source SHA-256."
        ),
    }
    path = package_root / "benchmark/suite_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_checksums(package_root: Path) -> list[str]:
    lines = []
    for path in sorted(item for item in package_root.rglob("*") if item.is_file()):
        if path.name == "SHA256SUMS":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(package_root).as_posix()}")
    (package_root / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines


if __name__ == "__main__":
    main()
