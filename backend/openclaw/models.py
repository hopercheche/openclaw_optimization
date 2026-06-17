from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4


RunStatus = Literal["queued", "running", "completed", "failed"]
PermissionBehavior = Literal["allow", "ask", "deny"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_run_id() -> str:
    return f"run_{uuid4().hex[:12]}"


@dataclass(slots=True)
class AuditEvent:
    run_id: str
    event_id: int
    event_type: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PermissionDecision:
    behavior: PermissionBehavior
    reason: str
    tool_name: str
    rule: str = "mode"
    requires_human: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CandidateStep:
    title: str
    action: str
    tool_name: str
    rationale: str
    impact: int
    evidence_value: int
    reversibility: int
    risk: int
    mutates_workspace: bool = False

    @property
    def score(self) -> int:
        return self.impact * 2 + self.evidence_value + self.reversibility - self.risk

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["score"] = self.score
        return payload


@dataclass(slots=True)
class RunState:
    run_id: str
    goal: str
    permission_mode: str
    workspace_path: str
    status: RunStatus = "queued"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    final_response: str = ""
    audit_path: str = ""
    event_count: int = 0
    as2_available: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

