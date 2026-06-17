from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Iterable

from .models import AuditEvent, RunState


class RunStorage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.runs_root = self.root / "runs"
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def run_dir(self, run_id: str) -> Path:
        return self.runs_root / run_id

    def create_run(self, state: RunState) -> None:
        with self._lock:
            run_dir = self.run_dir(state.run_id)
            run_dir.mkdir(parents=True, exist_ok=True)
            self.save_state(state)
            (run_dir / "events.jsonl").touch(exist_ok=True)

    def save_state(self, state: RunState) -> None:
        path = self.run_dir(state.run_id) / "state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(state.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_state(self, run_id: str) -> RunState | None:
        path = self.run_dir(run_id) / "state.json"
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return RunState(**payload)

    def list_states(self) -> list[RunState]:
        states: list[RunState] = []
        for state_path in sorted(self.runs_root.glob("*/state.json"), reverse=True):
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            states.append(RunState(**payload))
        return states

    def append_event(self, event: AuditEvent) -> None:
        line = json.dumps(event.to_dict(), ensure_ascii=False)
        with self._lock:
            events_path = self.run_dir(event.run_id) / "events.jsonl"
            with events_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def load_events(self, run_id: str) -> list[AuditEvent]:
        events_path = self.run_dir(run_id) / "events.jsonl"
        if not events_path.exists():
            return []
        events: list[AuditEvent] = []
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            events.append(AuditEvent(**json.loads(line)))
        return events

    def write_audit(self, run_id: str, content: str) -> Path:
        audit_path = self.run_dir(run_id) / "audit.md"
        audit_path.write_text(content, encoding="utf-8")
        return audit_path

    def read_audit(self, run_id: str) -> str | None:
        audit_path = self.run_dir(run_id) / "audit.md"
        if not audit_path.exists():
            return None
        return audit_path.read_text(encoding="utf-8")

    def states_as_dicts(self) -> list[dict]:
        return [state.to_dict() for state in self.list_states()]

    def events_as_dicts(self, run_id: str) -> list[dict]:
        return [event.to_dict() for event in self.load_events(run_id)]

    def hydrate_event_count(self, states: Iterable[RunState]) -> None:
        for state in states:
            state.event_count = len(self.load_events(state.run_id))

