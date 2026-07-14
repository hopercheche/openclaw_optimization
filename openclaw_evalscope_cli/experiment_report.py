"""Build a self-contained JSON report for one EvalScope evaluation run."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


REPORT_SCHEMA_VERSION = "1.1"
REPORT_FILENAME = "experiment_report.json"
_MILLION = Decimal(1_000_000)
_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "gateway_token",
    "trial_token",
}


def generate_experiment_report(
    *,
    task_config: Any,
    status: str,
    started_at: datetime,
    finished_at: datetime,
    error: BaseException | None = None,
) -> Path:
    """Collect EvalScope artifacts into ``experiment_report.json``.

    The task configuration is serialized through ``TaskConfig.to_dict()``
    when available, then recursively redacted. Per-task entries are compact
    projections of prediction/review caches; the original JSONL files remain
    listed under ``artifacts`` for full-fidelity debugging.
    """
    work_dir = Path(task_config.work_dir).expanduser().resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    datasets = list(getattr(task_config, "datasets", None) or [])

    artifact_paths = _discover_artifacts(work_dir)
    dataset_reports = _load_dataset_reports(work_dir, artifact_paths["dataset_reports"])
    task_results = _load_task_results(
        work_dir=work_dir,
        datasets=datasets,
        prediction_paths=artifact_paths["predictions"],
        review_paths=artifact_paths["reviews"],
    )

    pricing = _load_pricing()
    router_pricing = _load_router_pricing()
    usage_summary = _summarize_usage(task_results)
    cost_summary = _apply_costs(task_results, usage_summary, pricing, router_pricing)
    routing_summary = _summarize_routing(task_results)
    runtime_metrics = _summarize_runtime_metrics(task_results)

    config_dict = task_config.to_dict() if hasattr(task_config, "to_dict") else task_config
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": status,
        "started_at": _isoformat(started_at),
        "finished_at": _isoformat(finished_at),
        "duration_seconds": round(max(0.0, (finished_at - started_at).total_seconds()), 3),
        "task_config": _redact(_jsonable(config_dict)),
        "runtime": _runtime_metadata(),
        "results": {
            "dataset_reports": dataset_reports,
            "task_results": task_results,
        },
        "usage": usage_summary,
        "routing": routing_summary,
        "openclaw_runtime_metrics": runtime_metrics,
        "cost_estimate": cost_summary,
        "artifacts": {
            key: [_relative(path, work_dir) for path in paths]
            for key, paths in artifact_paths.items()
        },
        "error": _error_payload(error),
    }

    report_path = work_dir / REPORT_FILENAME
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report_path


def _discover_artifacts(work_dir: Path) -> dict[str, list[Path]]:
    return {
        "dataset_reports": sorted(path for path in (work_dir / "reports").glob("*/*.json") if path.is_file()),
        "predictions": sorted(path for path in (work_dir / "predictions").glob("*/*.jsonl") if path.is_file()),
        "reviews": sorted(path for path in (work_dir / "reviews").glob("*/*.jsonl") if path.is_file()),
        "configs": sorted(path for path in (work_dir / "configs").glob("*") if path.is_file()),
        "logs": sorted(path for path in (work_dir / "logs").glob("*") if path.is_file()),
    }


def _load_dataset_reports(work_dir: Path, paths: Iterable[Path]) -> list[dict[str, Any]]:
    reports = []
    for path in paths:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            reports.append({"path": _relative(path, work_dir), "error": str(exc)})
            continue
        reports.append({"path": _relative(path, work_dir), "report": report})
    return reports


def _load_task_results(
    *,
    work_dir: Path,
    datasets: list[str],
    prediction_paths: Iterable[Path],
    review_paths: Iterable[Path],
) -> list[dict[str, Any]]:
    records: dict[tuple[str, str, int], dict[str, Any]] = {}

    for source, paths in (("prediction", prediction_paths), ("review", review_paths)):
        for path in paths:
            dataset, subset = _dataset_subset(path.stem, datasets)
            for row_number, record in enumerate(_read_jsonl(path)):
                index = _as_int(record.get("index"), row_number)
                key = (dataset, subset, index)
                merged = records.setdefault(
                    key,
                    {
                        "dataset": dataset,
                        "subset": subset,
                        "index": index,
                        "sources": {},
                    },
                )
                merged["sources"][source] = _relative(path, work_dir)
                if source == "prediction":
                    merged["prediction_record"] = record
                else:
                    merged["review_record"] = record

    results = []
    for key in sorted(records):
        item = records[key]
        prediction = item.pop("prediction_record", {})
        review = item.pop("review_record", {})
        combined = dict(prediction)
        combined.update(review)
        results.append(_compact_task_result(item, combined))
    return results


def _compact_task_result(identity: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    model_output = record.get("model_output") or {}
    score_wrapper = ((record.get("sample_score") or {}).get("score") or {})
    usage = _extract_usage(record)
    model_calls = _extract_model_calls(record)
    runner_metrics = _extract_runner_metrics(record)
    return {
        **identity,
        "sample_id": (record.get("sample_score") or {}).get("sample_id", record.get("index")),
        "group_id": (record.get("sample_score") or {}).get("group_id"),
        "target": record.get("target"),
        "model": record.get("model") or model_output.get("model"),
        "prediction": score_wrapper.get("prediction") or _model_completion(model_output),
        "extracted_prediction": score_wrapper.get("extracted_prediction"),
        "score": score_wrapper.get("value"),
        "main_score_name": score_wrapper.get("main_score_name"),
        "score_explanation": score_wrapper.get("explanation"),
        "sample_metadata": (record.get("sample_score") or {}).get("sample_metadata"),
        "usage": usage,
        "model_calls": model_calls,
        "runner_metrics": runner_metrics,
        "latency_seconds": _latency_seconds(record),
        "error": model_output.get("error"),
    }


def _extract_model_calls(record: dict[str, Any]) -> list[dict[str, Any]]:
    calls = []
    for event in (record.get("agent_trace") or {}).get("events") or []:
        if event.get("type") != "model_generate":
            continue
        payload = event.get("payload") or {}
        usage = event.get("token_usage") or {}
        calls.append({
            "step": event.get("step"),
            "requested_model": payload.get("requested_model"),
            "resolved_model": payload.get("resolved_model"),
            "latency_ms": event.get("latency_ms"),
            "usage": {
                "input_tokens": _as_int(usage.get("input"), 0),
                "output_tokens": _as_int(usage.get("output"), 0),
                "total_tokens": _as_int(usage.get("input"), 0) + _as_int(usage.get("output"), 0),
                "cached_input_tokens": _as_int(usage.get("cache_read"), 0),
                "cache_write_tokens": _as_int(usage.get("cache_write"), 0),
                "reasoning_tokens": _as_int(usage.get("reasoning"), 0),
            },
        })
    return calls


def _extract_runner_metrics(record: dict[str, Any]) -> dict[str, Any] | None:
    model_output = record.get("model_output") or {}
    metadata_metrics = (model_output.get("metadata") or {}).get("runner_metrics")
    if isinstance(metadata_metrics, dict):
        return metadata_metrics
    for event in reversed((record.get("agent_trace") or {}).get("events") or []):
        if event.get("type") != "run_end":
            continue
        metrics = (event.get("payload") or {}).get("runner_metrics")
        return metrics if isinstance(metrics, dict) else None
    return None


def _extract_usage(record: dict[str, Any]) -> dict[str, int] | None:
    model_output = record.get("model_output") or {}
    metadata_usage = (model_output.get("metadata") or {}).get("task_usage")
    trace_usage = (record.get("agent_trace") or {}).get("total_usage")
    output_usage = model_output.get("usage")
    source = metadata_usage or trace_usage or output_usage
    if not isinstance(source, dict):
        return None

    input_tokens = _as_int(source.get("input_tokens", source.get("input")), 0)
    output_tokens = _as_int(source.get("output_tokens", source.get("output")), 0)
    cache_source = trace_usage if isinstance(trace_usage, dict) else source
    cached_input_tokens = _as_int(
        cache_source.get("input_tokens_cache_read", cache_source.get("cached_input_tokens")),
        0,
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cached_input_tokens": cached_input_tokens,
    }


def _summarize_usage(task_results: list[dict[str, Any]]) -> dict[str, Any]:
    usages = [result["usage"] for result in task_results if result.get("usage")]
    input_tokens = sum(usage["input_tokens"] for usage in usages)
    output_tokens = sum(usage["output_tokens"] for usage in usages)
    cached_input_tokens = sum(usage["cached_input_tokens"] for usage in usages)
    return {
        "scope": "evaluated_harness_model_only",
        "n_tasks": len(task_results),
        "n_tasks_with_usage": len(usages),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cached_input_tokens": cached_input_tokens,
        "excludes": ["llm_judge", "analysis_report", "tool_service_fees"],
    }


def _load_pricing() -> dict[str, Any] | None:
    input_raw = os.getenv("EVALSCOPE_INPUT_PRICE_PER_MILLION")
    output_raw = os.getenv("EVALSCOPE_OUTPUT_PRICE_PER_MILLION")
    if input_raw is None or output_raw is None:
        return None
    try:
        input_price = Decimal(input_raw)
        output_price = Decimal(output_raw)
        cached_raw = os.getenv("EVALSCOPE_CACHED_INPUT_PRICE_PER_MILLION")
        cached_price = Decimal(cached_raw) if cached_raw is not None else input_price
    except InvalidOperation as exc:
        raise ValueError("EvalScope price environment variables must be valid decimal numbers") from exc
    if min(input_price, output_price, cached_price) < 0:
        raise ValueError("EvalScope price environment variables cannot be negative")
    return {
        "currency": os.getenv("EVALSCOPE_COST_CURRENCY", "CNY"),
        "input_per_million": input_price,
        "output_per_million": output_price,
        "cached_input_per_million": cached_price,
        "cached_price_explicit": cached_raw is not None,
    }


def _load_router_pricing() -> dict[str, dict[str, Any]]:
    raw = os.getenv("EVALSCOPE_ROUTER_MODEL_ROUTES")
    if not raw:
        return {}
    try:
        routes = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"EVALSCOPE_ROUTER_MODEL_ROUTES must be valid JSON: {exc}") from exc
    if not isinstance(routes, dict):
        return {}

    pricing: dict[str, dict[str, Any]] = {}
    currency = os.getenv("EVALSCOPE_COST_CURRENCY", "USD")
    for request_model, route in routes.items():
        if not isinstance(route, dict):
            continue
        model_config = route.get("openclaw_model") or {}
        cost = model_config.get("cost") if isinstance(model_config, dict) else None
        if not isinstance(cost, dict):
            continue
        try:
            values = {
                "input_per_million": Decimal(str(cost.get("input", 0))),
                "output_per_million": Decimal(str(cost.get("output", 0))),
                "cached_input_per_million": Decimal(str(cost.get("cacheRead", 0))),
                "cache_write_per_million": Decimal(str(cost.get("cacheWrite", 0))),
            }
        except InvalidOperation as exc:
            raise ValueError(f"invalid router pricing for {request_model!r}") from exc
        if min(values.values()) < 0:
            raise ValueError(f"router pricing cannot be negative for {request_model!r}")
        pricing[str(request_model)] = {
            "currency": currency,
            "cached_price_explicit": True,
            **values,
        }
    return pricing


def _apply_costs(
    task_results: list[dict[str, Any]],
    usage_summary: dict[str, Any],
    pricing: dict[str, Any] | None,
    router_pricing: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if router_pricing:
        return _apply_router_costs(task_results, router_pricing)
    if pricing is None:
        return {
            "status": "unavailable",
            "estimated": True,
            "reason": (
                "Set EVALSCOPE_INPUT_PRICE_PER_MILLION and "
                "EVALSCOPE_OUTPUT_PRICE_PER_MILLION to calculate model cost."
            ),
            "limitations": _cost_limitations(cached_price_explicit=False),
        }

    task_costs: list[Decimal] = []
    for task in task_results:
        usage = task.get("usage")
        if not usage:
            task["cost_estimate"] = None
            continue
        cost = _calculate_cost(usage, pricing)
        task["cost_estimate"] = cost
        task_costs.append(Decimal(str(cost["total_cost"])))

    aggregate = _calculate_cost(usage_summary, pricing)
    aggregate.update({
        "n_tasks_priced": len(task_costs),
        "mean_cost_per_task": _money(sum(task_costs) / len(task_costs)) if task_costs else None,
        "min_cost_per_task": _money(min(task_costs)) if task_costs else None,
        "max_cost_per_task": _money(max(task_costs)) if task_costs else None,
    })
    return {
        "status": "estimated",
        "estimated": True,
        "currency": pricing["currency"],
        "pricing_per_million_tokens": {
            "input": _number(pricing["input_per_million"]),
            "output": _number(pricing["output_per_million"]),
            "cached_input": _number(pricing["cached_input_per_million"]),
        },
        **aggregate,
        "limitations": _cost_limitations(pricing["cached_price_explicit"]),
    }


def _apply_router_costs(
    task_results: list[dict[str, Any]],
    router_pricing: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    task_costs: list[Decimal] = []
    model_totals: dict[str, Decimal] = {}
    n_calls_priced = 0
    for task in task_results:
        call_costs = []
        task_total = Decimal(0)
        for call in task.get("model_calls") or []:
            model = call.get("requested_model") or call.get("resolved_model")
            model_price = router_pricing.get(str(model))
            if model_price is None:
                call["cost_estimate"] = None
                continue
            cost = _calculate_cost(call.get("usage") or {}, model_price)
            cache_write_tokens = Decimal(_as_int((call.get("usage") or {}).get("cache_write_tokens"), 0))
            cache_write_cost = cache_write_tokens * model_price["cache_write_per_million"] / _MILLION
            total = Decimal(str(cost["total_cost"])) + cache_write_cost
            cost["cache_write_cost"] = _money(cache_write_cost)
            cost["total_cost"] = _money(total)
            cost["model"] = model
            call["cost_estimate"] = cost
            call_costs.append(cost)
            task_total += total
            model_totals[str(model)] = model_totals.get(str(model), Decimal(0)) + total
            n_calls_priced += 1
        task["model_costs"] = call_costs
        task["cost_estimate"] = {
            "currency": next(iter(router_pricing.values()))["currency"],
            "total_cost": _money(task_total),
        } if call_costs else None
        if call_costs:
            task_costs.append(task_total)

    total = sum(task_costs, Decimal(0))
    return {
        "status": "estimated",
        "estimated": True,
        "source": "per_model_bridge_trace",
        "currency": next(iter(router_pricing.values()))["currency"],
        "n_tasks_priced": len(task_costs),
        "n_model_calls_priced": n_calls_priced,
        "total_cost": _money(total),
        "mean_cost_per_task": _money(total / len(task_costs)) if task_costs else None,
        "min_cost_per_task": _money(min(task_costs)) if task_costs else None,
        "max_cost_per_task": _money(max(task_costs)) if task_costs else None,
        "cost_by_model": {model: _money(value) for model, value in sorted(model_totals.items())},
        "pricing_per_million_tokens": {
            model: {
                "input": _number(price["input_per_million"]),
                "output": _number(price["output_per_million"]),
                "cache_read": _number(price["cached_input_per_million"]),
                "cache_write": _number(price["cache_write_per_million"]),
            }
            for model, price in sorted(router_pricing.items())
        },
        "limitations": _cost_limitations(cached_price_explicit=True),
    }


def _summarize_routing(task_results: list[dict[str, Any]]) -> dict[str, Any]:
    raw_tiers = os.getenv("OPENCLAW_ROUTER_TIERS")
    try:
        tiers = json.loads(raw_tiers) if raw_tiers else {}
    except json.JSONDecodeError:
        tiers = {}
    model_to_tier = {str(model): str(tier) for tier, model in tiers.items()} if isinstance(tiers, dict) else {}
    by_model: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    total_calls = 0
    for task in task_results:
        for call in task.get("model_calls") or []:
            model = str(call.get("requested_model") or call.get("resolved_model") or "unknown")
            tier = model_to_tier.get(model, "unknown")
            by_model[model] = by_model.get(model, 0) + 1
            by_tier[tier] = by_tier.get(tier, 0) + 1
            total_calls += 1
    return {
        "n_model_calls": total_calls,
        "calls_by_model": dict(sorted(by_model.items())),
        "calls_by_tier": dict(sorted(by_tier.items())),
    }


def _summarize_runtime_metrics(task_results: list[dict[str, Any]]) -> dict[str, Any]:
    series: dict[str, float] = {}
    tasks_with_metrics = 0
    for task in task_results:
        metrics = task.get("runner_metrics") or {}
        delta = metrics.get("openclaw_prometheus_delta")
        if not isinstance(delta, dict):
            continue
        tasks_with_metrics += 1
        for name, value in delta.items():
            if isinstance(value, (int, float)):
                series[name] = series.get(name, 0.0) + float(value)
    return {
        "n_tasks_with_metrics": tasks_with_metrics,
        "prometheus_counter_delta": dict(sorted(series.items())),
    }


def _calculate_cost(usage: dict[str, Any], pricing: dict[str, Any]) -> dict[str, Any]:
    input_tokens = Decimal(_as_int(usage.get("input_tokens"), 0))
    output_tokens = Decimal(_as_int(usage.get("output_tokens"), 0))
    cached_tokens = Decimal(min(_as_int(usage.get("cached_input_tokens"), 0), int(input_tokens)))
    regular_input_tokens = input_tokens - cached_tokens
    input_cost = regular_input_tokens * pricing["input_per_million"] / _MILLION
    cached_input_cost = cached_tokens * pricing["cached_input_per_million"] / _MILLION
    output_cost = output_tokens * pricing["output_per_million"] / _MILLION
    return {
        "currency": pricing["currency"],
        "input_cost": _money(input_cost),
        "cached_input_cost": _money(cached_input_cost),
        "output_cost": _money(output_cost),
        "total_cost": _money(input_cost + cached_input_cost + output_cost),
    }


def _cost_limitations(cached_price_explicit: bool) -> list[str]:
    limitations = [
        "This is a token-price estimate, not the provider invoice.",
        "LLM judge, analysis report, subscription discounts, taxes, and tool-service charges are excluded.",
    ]
    if not cached_price_explicit:
        limitations.append("Cached input tokens use the normal input price unless a cached-input price is configured.")
    return limitations


def _runtime_metadata() -> dict[str, Any]:
    names = [
        "OPENCLAW_IMAGE",
        "OPENCLAW_ROUTER_ENABLED",
        "OPENCLAW_ROUTER_GATEWAY_IMAGE",
        "OPENCLAW_ROUTER_API_IMAGE",
        "OPENCLAW_ROUTER_EMBEDDING_MODE",
        "OPENCLAW_ROUTER_CONFIDENCE_THRESHOLD",
        "OPENCLAW_COMPOSE_PROJECT",
        "OPENCLAW_GATEWAY_PORT",
        "OPENCLAW_AGENT_ID",
        "OPENCLAW_EVAL_PROTOCOL",
        "OPENCLAW_EVAL_STATE_DIR",
        "EVALSCOPE_MODEL_ID",
        "EVALSCOPE_DATASET_HUB",
    ]
    return {name: os.environ[name] for name in names if name in os.environ}


def _dataset_subset(stem: str, datasets: list[str]) -> tuple[str, str]:
    for dataset in sorted(datasets, key=len, reverse=True):
        prefix = f"{dataset}_"
        if stem == dataset:
            return dataset, "default"
        if stem.startswith(prefix):
            return dataset, stem[len(prefix):]
    if "_" in stem:
        return tuple(stem.split("_", 1))  # type: ignore[return-value]
    return stem, "default"


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            yield value


def _model_completion(model_output: dict[str, Any]) -> Any:
    choices = model_output.get("choices") or []
    if not choices:
        return None
    return (choices[0].get("message") or {}).get("content")


def _latency_seconds(record: dict[str, Any]) -> float | None:
    model_output = record.get("model_output") or {}
    value = model_output.get("time")
    if isinstance(value, (int, float)):
        return round(float(value), 6)
    for event in reversed((record.get("agent_trace") or {}).get("events") or []):
        if event.get("type") == "run_end":
            wall_time = (event.get("payload") or {}).get("wall_time")
            if isinstance(wall_time, (int, float)):
                return round(float(wall_time), 6)
    return None


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
            result[key] = "<redacted>" if normalized in _SENSITIVE_KEYS else _redact(item)
        return result
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _error_payload(error: BaseException | None) -> dict[str, str] | None:
    if error is None:
        return None
    return {"type": type(error).__name__, "message": str(error)}


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.00000001")))


def _number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral() else float(value)
