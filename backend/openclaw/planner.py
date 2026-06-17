from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from .as2_adapter import AS2Status, build_user_message_snapshot, map_local_event_to_as2
from .as2_openai import generate_as2_openai_plan
from .audit import render_audit_markdown
from .models import AuditEvent, CandidateStep, RunState, utc_now
from .permissions import PermissionEngine
from .storage import RunStorage


EventSink = Callable[[AuditEvent], None]


class LocalAuditPlanner:
    """Deterministic, auditable planner scaffold inspired by AS2 event flow."""

    def __init__(
        self,
        storage: RunStorage,
        permission_engine: PermissionEngine,
        as2_status: AS2Status,
        event_sink: EventSink | None = None,
    ) -> None:
        self.storage = storage
        self.permission_engine = permission_engine
        self.as2_status = as2_status
        self.event_sink = event_sink

    def run(self, state: RunState) -> RunState:
        state.status = "running"
        state.updated_at = utc_now()
        self.storage.save_state(state)

        self._emit(state, "run_started", "Run accepted by AS2-backed audit runtime.", {
            "as2": self.as2_status.to_dict(),
            "as2_user_msg": build_user_message_snapshot(state.goal, state.run_id),
        })
        self._emit(state, "goal_analysis", "Normalized user goal and extracted audit intent.", {
            "goal": state.goal.strip(),
            "permission_mode": state.permission_mode,
        })

        candidates = self._generate_candidates_from_runtime(state)
        for candidate in candidates:
            self._emit(state, "candidate_step", f"Candidate generated: {candidate.title}", {
                "candidate": candidate.to_dict(),
            })

        selected = sorted(candidates, key=lambda item: item.score, reverse=True)[:5]
        self._emit(state, "planning", "Selected bounded high-value planner path.", {
            "selected_titles": [step.title for step in selected],
            "selection_rule": "top_5_by_impact_evidence_reversibility_minus_risk",
        })

        completed_titles: list[str] = []
        blocked_titles: list[str] = []
        critique_notes: list[str] = []

        for index, step in enumerate(selected, start=1):
            self._emit(state, "reasoning", f"Step {index}: {step.rationale}", {
                "step": step.to_dict(),
            })
            decision = self.permission_engine.decide(step, state.permission_mode)
            self._emit(state, "permission", f"Permission decision for {step.tool_name}: {decision.behavior}", {
                "step_title": step.title,
                "decision": decision.to_dict(),
            })

            if decision.behavior == "deny":
                blocked_titles.append(step.title)
                critique = self._critique(step, "denied")
                critique_notes.append(critique)
                self._emit(state, "critique", "Verifier marked the step as blocked by policy.", {
                    "step_title": step.title,
                    "critique": critique,
                })
                continue

            if decision.behavior == "ask":
                blocked_titles.append(step.title)
                critique = self._critique(step, "requires_human")
                critique_notes.append(critique)
                self._emit(state, "human_gate", "Step paused because human confirmation is required.", {
                    "step_title": step.title,
                    "suggested_next_action": "Switch to ACCEPT_EDITS/BYPASS or add an explicit approval rule for this action.",
                })
                self._emit(state, "critique", "Verifier kept the action out of automatic execution.", {
                    "step_title": step.title,
                    "critique": critique,
                })
                continue

            self._emit(state, "tool_call", f"Executing simulated tool: {step.tool_name}", {
                "tool_name": step.tool_name,
                "action": step.action,
            })
            result = self._simulate_tool(step, state.workspace_path)
            completed_titles.append(step.title)
            self._emit(state, "tool_result", f"Tool completed: {step.tool_name}", {
                "tool_name": step.tool_name,
                "result": result,
            })
            critique = self._critique(step, "completed")
            critique_notes.append(critique)
            self._emit(state, "critique", "Verifier checked evidence value and residual risk.", {
                "step_title": step.title,
                "critique": critique,
            })
            time.sleep(0.05)

        state.final_response = self._final_response(completed_titles, blocked_titles, critique_notes)
        self._emit(state, "final", "Planner produced final recommendation.", {
            "final_response": state.final_response,
        })
        state.status = "completed"
        state.updated_at = utc_now()
        state.event_count = len(self.storage.load_events(state.run_id)) + 1
        self.storage.save_state(state)
        self._emit(state, "run_completed", "Run completed and audit report is ready.", {
            "status": state.status,
        })

        events = self.storage.load_events(state.run_id)
        audit_path = self.storage.write_audit(state.run_id, render_audit_markdown(state, events))
        state.audit_path = str(audit_path)
        state.event_count = len(events)
        state.updated_at = utc_now()
        self.storage.save_state(state)
        return state

    def _generate_candidates_from_runtime(self, state: RunState) -> list[CandidateStep]:
        if not self.as2_status.model_ready:
            self._emit(state, "as2_model_skipped", "AS2 model planner skipped because no provider key is configured.", {
                "model_ready": False,
            })
            return self._generate_candidates(state.goal)

        self._emit(state, "as2_model_started", "Requesting candidate plan from AS2 OpenAI-compatible Agent.", {
            "model_provider": self.as2_status.model_provider,
            "model_name": self.as2_status.default_model,
            "model_base_url": self.as2_status.model_base_url,
            "as2_runtime": self.as2_status.runtime,
        })
        result = generate_as2_openai_plan(state.goal, state.permission_mode)
        for raw_event in result.raw_events[:40]:
            self._emit(state, "as2_model_event", f"AS2 stream event: {raw_event.event_type}", {
                "as2_event_type": raw_event.event_type,
                "payload": raw_event.payload,
            })

        if result.used_model:
            self._emit(state, "as2_model_result", "AS2 OpenAI Agent produced planner candidates.", {
                "model_name": result.model_name,
                "candidate_count": len(result.candidates),
            })
            return result.candidates

        self._emit(state, "as2_model_fallback", "Falling back to deterministic planner candidates.", {
            "model_name": result.model_name,
            "error": result.error,
        })
        return self._generate_candidates(state.goal)

    def _emit(self, state: RunState, event_type: str, message: str, data: dict | None = None) -> AuditEvent:
        event_data = data or {}
        event_data.setdefault("as2_event_type", map_local_event_to_as2(event_type, event_data))
        event_id = len(self.storage.load_events(state.run_id)) + 1
        event = AuditEvent(
            run_id=state.run_id,
            event_id=event_id,
            event_type=event_type,
            message=message,
            data=event_data,
        )
        self.storage.append_event(event)
        state.event_count = event.event_id
        state.updated_at = event.timestamp
        self.storage.save_state(state)
        if self.event_sink:
            self.event_sink(event)
        return event

    def _generate_candidates(self, goal: str) -> list[CandidateStep]:
        lower_goal = goal.lower()
        mutating_goal = any(term in lower_goal for term in ["write", "edit", "deploy", "delete", "remove", "优化", "修改"])
        production_goal = any(term in lower_goal for term in ["prod", "production", "上线", "部署"])

        candidates = [
            CandidateStep(
                title="Define audit boundary",
                action="Record task scope, actor, workspace, and success criteria.",
                tool_name="goal_analyzer",
                rationale="A good audit starts by freezing what the run is allowed to attempt.",
                impact=4,
                evidence_value=5,
                reversibility=5,
                risk=1,
            ),
            CandidateStep(
                title="Inspect workspace safely",
                action="List project files and identify runtime boundaries without modifying files.",
                tool_name="workspace_inspector",
                rationale="Workspace context prevents the planner from inventing nonexistent surfaces.",
                impact=4,
                evidence_value=4,
                reversibility=5,
                risk=1,
            ),
            CandidateStep(
                title="Build bounded plan candidates",
                action="Generate alternative plan steps and score them by impact, evidence, reversibility, and risk.",
                tool_name="planner",
                rationale="Bounded Tree-of-Thoughts exploration improves planner quality without runaway cost.",
                impact=5,
                evidence_value=4,
                reversibility=4,
                risk=1,
            ),
            CandidateStep(
                title="Review permission posture",
                action="Classify proposed actions into allow, ask, or deny before any execution.",
                tool_name="risk_model",
                rationale="Permission decisions are first-class audit artifacts in AS2-style runtimes.",
                impact=5,
                evidence_value=5,
                reversibility=5,
                risk=1,
            ),
            CandidateStep(
                title="Verify planner output",
                action="Critique each accepted or blocked step for missing evidence and residual risk.",
                tool_name="verifier",
                rationale="Reflexion-style verification catches weak or unsafe plan transitions.",
                impact=4,
                evidence_value=5,
                reversibility=5,
                risk=1,
            ),
            CandidateStep(
                title="Prepare implementation change",
                action="Write or edit files inside the configured workspace only.",
                tool_name="file_writer",
                rationale="If the goal requires implementation, changes must remain workspace-scoped.",
                impact=5 if mutating_goal else 2,
                evidence_value=4,
                reversibility=3,
                risk=3,
                mutates_workspace=True,
            ),
            CandidateStep(
                title="Run validation command",
                action="Run project validation command and capture logs.",
                tool_name="command_runner",
                rationale="Evidence is stronger when generated by a reproducible command.",
                impact=4,
                evidence_value=5,
                reversibility=3,
                risk=3,
                mutates_workspace=True,
            ),
            CandidateStep(
                title="Gate production deployment",
                action="Deploy to production only after explicit human approval.",
                tool_name="deploy_runner",
                rationale="Production deployment is high impact and should not run under silent automation.",
                impact=5 if production_goal else 1,
                evidence_value=5,
                reversibility=1,
                risk=5,
                mutates_workspace=True,
            ),
        ]
        return candidates

    def _simulate_tool(self, step: CandidateStep, workspace_path: str) -> str:
        workspace = Path(workspace_path)
        if step.tool_name == "workspace_inspector":
            if not workspace.exists():
                return f"Workspace does not exist: {workspace}"
            visible = sorted(path.name for path in workspace.iterdir() if not path.name.startswith("."))
            return f"Workspace visible entries: {visible[:12]}"
        if step.tool_name == "planner":
            return "Planner selected a bounded ToT path with ReAct-style action checkpoints."
        if step.tool_name == "risk_model":
            return "Permission policy created explicit allow/ask/deny evidence for each candidate action."
        if step.tool_name == "verifier":
            return "Verifier produced critique notes for completed and blocked steps."
        if step.tool_name == "goal_analyzer":
            return "Goal boundary recorded for audit replay."
        return "MVP simulation captured the action without applying external side effects."

    def _critique(self, step: CandidateStep, outcome: str) -> str:
        if outcome == "denied":
            return f"{step.title}: blocked correctly; policy evidence is more valuable than unsafe execution."
        if outcome == "requires_human":
            return f"{step.title}: requires explicit approval; preserve pause state and suggested rule."
        return (
            f"{step.title}: evidence value={step.evidence_value}, risk={step.risk}; "
            "acceptable for MVP trace, revisit with real AS2 tool result validation."
        )

    def _final_response(self, completed: list[str], blocked: list[str], critiques: list[str]) -> str:
        completed_text = ", ".join(completed) if completed else "none"
        blocked_text = ", ".join(blocked) if blocked else "none"
        critique_text = " ".join(critiques[:3])
        return (
            f"Completed audited planner steps: {completed_text}. "
            f"Blocked or gated steps: {blocked_text}. "
            f"Verifier summary: {critique_text}"
        )


class PlannerThread(threading.Thread):
    def __init__(self, planner: LocalAuditPlanner, state: RunState) -> None:
        super().__init__(daemon=True)
        self.planner = planner
        self.state = state

    def run(self) -> None:
        try:
            self.planner.run(self.state)
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            self.state.status = "failed"
            self.state.final_response = f"Planner failed: {exc}"
            self.state.updated_at = utc_now()
            self.planner.storage.save_state(self.state)
            self.planner._emit(self.state, "run_failed", "Planner failed.", {
                "error": repr(exc),
            })
