from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openclaw.as2_adapter import detect_as2
from openclaw.models import RunState, new_run_id
from openclaw.permissions import PermissionEngine
from openclaw.planner import LocalAuditPlanner, PlannerThread
from openclaw.storage import RunStorage


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.environ.get("OPENCLAW_DATA_DIR", PROJECT_ROOT / "data"))
DEFAULT_WORKSPACE = Path(os.environ.get("OPENCLAW_WORKSPACE", PROJECT_ROOT))


class EventBroker:
    def __init__(self) -> None:
        self._condition = threading.Condition()

    def notify(self) -> None:
        with self._condition:
            self._condition.notify_all()

    def wait(self, timeout: float = 1.0) -> None:
        with self._condition:
            self._condition.wait(timeout=timeout)


class RunManager:
    def __init__(self, storage: RunStorage, broker: EventBroker) -> None:
        self.storage = storage
        self.broker = broker
        self.as2_status = detect_as2()
        self.permission_engine = PermissionEngine()

    def create_run(self, goal: str, permission_mode: str, workspace_path: str | None = None) -> RunState:
        state = RunState(
            run_id=new_run_id(),
            goal=goal.strip(),
            permission_mode=permission_mode.upper(),
            workspace_path=str(Path(workspace_path).expanduser().resolve()) if workspace_path else str(DEFAULT_WORKSPACE),
            as2_available=self.as2_status.available,
        )
        self.storage.create_run(state)
        planner = LocalAuditPlanner(
            storage=self.storage,
            permission_engine=self.permission_engine,
            as2_status=self.as2_status,
            event_sink=lambda _event: self.broker.notify(),
        )
        PlannerThread(planner, state).start()
        return state


STORAGE = RunStorage(DATA_ROOT)
BROKER = EventBroker()
MANAGER = RunManager(STORAGE, BROKER)


class OpenClawHandler(BaseHTTPRequestHandler):
    server_version = "OpenClawPOptiMVP/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), format % args))

    def do_OPTIONS(self) -> None:
        self._send_empty(HTTPStatus.NO_CONTENT)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/api/health":
            self._send_json({
                "ok": True,
                "service": "openclaw-audit-mvp",
                "as2": MANAGER.as2_status.to_dict(),
            })
            return

        if path == "/api/runs":
            states = STORAGE.list_states()
            STORAGE.hydrate_event_count(states)
            self._send_json({"runs": [state.to_dict() for state in states]})
            return

        if path.startswith("/api/runs/"):
            self._handle_run_get(path, parse_qs(parsed.query))
            return

        self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path != "/api/runs":
            self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
            return

        try:
            payload = self._read_json()
        except ValueError as exc:
            self._send_json({"error": "invalid_json", "detail": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        goal = str(payload.get("goal", "")).strip()
        if not goal:
            self._send_json({"error": "goal_required"}, status=HTTPStatus.BAD_REQUEST)
            return

        permission_mode = str(payload.get("permission_mode", "DEFAULT")).upper()
        if permission_mode not in {"DEFAULT", "EXPLORE", "ACCEPT_EDITS", "BYPASS", "DONT_ASK"}:
            self._send_json({"error": "invalid_permission_mode"}, status=HTTPStatus.BAD_REQUEST)
            return

        workspace_path = payload.get("workspace_path")
        state = MANAGER.create_run(goal, permission_mode, workspace_path)
        self._send_json({"run": state.to_dict()}, status=HTTPStatus.CREATED)

    def _handle_run_get(self, path: str, query: dict[str, list[str]]) -> None:
        parts = path.split("/")
        if len(parts) < 4:
            self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
            return

        run_id = parts[3]
        state = STORAGE.load_state(run_id)
        if state is None:
            self._send_json({"error": "run_not_found"}, status=HTTPStatus.NOT_FOUND)
            return

        suffix = parts[4] if len(parts) >= 5 else ""
        if not suffix:
            self._send_json({"run": state.to_dict()})
            return

        if suffix == "events":
            self._send_json({"events": STORAGE.events_as_dicts(run_id)})
            return

        if suffix == "audit.md":
            audit = STORAGE.read_audit(run_id)
            if audit is None:
                self._send_json({"error": "audit_not_ready"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_text(audit, content_type="text/markdown; charset=utf-8")
            return

        if suffix == "stream":
            last_event_id = int(query.get("last_event_id", ["0"])[0] or "0")
            self._send_sse(run_id, last_event_id)
            return

        self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def _send_sse(self, run_id: str, last_event_id: int) -> None:
        self.send_response(HTTPStatus.OK)
        self._send_common_headers(content_type="text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        sent = last_event_id
        deadline = time.time() + 300
        try:
            while time.time() < deadline:
                events = STORAGE.load_events(run_id)
                for event in events:
                    if event.event_id <= sent:
                        continue
                    payload = json.dumps(event.to_dict(), ensure_ascii=False)
                    self.wfile.write(f"id: {event.event_id}\n".encode("utf-8"))
                    self.wfile.write(f"event: {event.event_type}\n".encode("utf-8"))
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    sent = event.event_id

                state = STORAGE.load_state(run_id)
                if state and state.status in {"completed", "failed"} and sent >= len(events):
                    break
                BROKER.wait(timeout=0.5)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(exc.msg) from exc
        if not isinstance(payload, dict):
            raise ValueError("expected JSON object")
        return payload

    def _send_empty(self, status: HTTPStatus) -> None:
        self.send_response(status)
        self._send_common_headers()
        self.end_headers()

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self._send_common_headers(content_type="application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(
        self,
        body: str,
        status: HTTPStatus = HTTPStatus.OK,
        content_type: str = "text/plain; charset=utf-8",
    ) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self._send_common_headers(content_type=content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_common_headers(self, content_type: str = "application/json; charset=utf-8") -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


def build_server(host: str, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), OpenClawHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenClawPOpti AS2 audit MVP backend")
    parser.add_argument("--host", default=os.environ.get("OPENCLAW_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("OPENCLAW_PORT", "8787")))
    args = parser.parse_args()

    server = build_server(args.host, args.port)
    print(f"OpenClawPOpti API listening on http://{args.host}:{args.port}")
    print(f"Data directory: {DATA_ROOT}")
    print(f"AS2 status: {MANAGER.as2_status.to_dict()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
