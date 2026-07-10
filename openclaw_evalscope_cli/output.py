"""Helpers for extracting final text from OpenClaw JSON output."""

from __future__ import annotations

import json
from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _payload_texts(payloads: Any) -> list[str]:
    if not isinstance(payloads, list):
        return []

    texts: list[str] = []
    for payload in payloads:
        record = _as_dict(payload)
        text = record.get("text")
        if isinstance(text, str) and text.strip():
            texts.append(text.strip())
    return texts


def _responses_output_texts(output: Any) -> list[str]:
    if not isinstance(output, list):
        return []

    texts: list[str] = []
    for item in output:
        record = _as_dict(item)
        content = record.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            part_record = _as_dict(part)
            text = part_record.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
    return texts


def extract_text_from_openclaw_json(value: Any) -> str:
    """Return the visible assistant text from OpenClaw CLI/Gateway JSON."""

    data = _as_dict(value)

    for payloads in (
        data.get("payloads"),
        _as_dict(data.get("result")).get("payloads"),
    ):
        texts = _payload_texts(payloads)
        if texts:
            return "\n".join(texts).strip()

    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    texts = _responses_output_texts(data.get("output"))
    if texts:
        return "\n".join(texts).strip()

    summary = data.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()

    return ""


def parse_openclaw_stdout(stdout: str) -> tuple[dict[str, Any], str]:
    """Parse OpenClaw ``--json`` stdout and extract final visible text."""

    raw = stdout.strip()
    if not raw:
        raise ValueError("OpenClaw CLI produced empty stdout")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = None
        for line in reversed(raw.splitlines()):
            candidate = line.strip()
            if not candidate:
                continue
            try:
                data = json.loads(candidate)
                break
            except json.JSONDecodeError:
                continue
        if data is None:
            raise ValueError("OpenClaw CLI stdout did not contain valid JSON")

    if not isinstance(data, dict):
        raise ValueError("OpenClaw CLI JSON output is not an object")

    text = extract_text_from_openclaw_json(data)
    return data, text
