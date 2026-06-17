from __future__ import annotations

from .models import CandidateStep, PermissionDecision


READ_ONLY_TOOLS = {
    "goal_analyzer",
    "workspace_inspector",
    "planner",
    "risk_model",
    "verifier",
    "audit_reader",
}

MUTATING_TOOLS = {
    "file_writer",
    "command_runner",
    "deploy_runner",
}

DANGEROUS_TERMS = {
    "delete",
    "remove",
    "rm ",
    "drop",
    "prod",
    "production",
    "secret",
    "credential",
    "token",
}


class PermissionEngine:
    """Small AS2-inspired permission gate for MVP auditability."""

    def decide(self, step: CandidateStep, mode: str) -> PermissionDecision:
        normalized_mode = mode.upper()
        action = step.action.lower()
        has_dangerous_term = any(term in action for term in DANGEROUS_TERMS)

        if step.tool_name in READ_ONLY_TOOLS and not step.mutates_workspace:
            return PermissionDecision(
                behavior="allow",
                reason="Read-only planning or verification step.",
                tool_name=step.tool_name,
                rule="read_only_auto_allow",
            )

        if normalized_mode == "EXPLORE":
            return PermissionDecision(
                behavior="deny",
                reason="EXPLORE mode allows read-only planning but denies mutating actions.",
                tool_name=step.tool_name,
                rule="mode_explore",
            )

        if normalized_mode == "DONT_ASK":
            return PermissionDecision(
                behavior="deny" if step.mutates_workspace or has_dangerous_term else "allow",
                reason="DONT_ASK converts uncertain or mutating actions to deny.",
                tool_name=step.tool_name,
                rule="mode_dont_ask",
            )

        if has_dangerous_term:
            return PermissionDecision(
                behavior="ask",
                reason="Action contains production, destructive, or credential-sensitive language.",
                tool_name=step.tool_name,
                rule="safety_ask",
                requires_human=True,
            )

        if normalized_mode == "BYPASS":
            return PermissionDecision(
                behavior="allow",
                reason="BYPASS mode permits non-denied mutating actions in this sandboxed MVP.",
                tool_name=step.tool_name,
                rule="mode_bypass",
            )

        if normalized_mode == "ACCEPT_EDITS" and step.tool_name in MUTATING_TOOLS:
            return PermissionDecision(
                behavior="allow",
                reason="ACCEPT_EDITS allows bounded workspace edits in development mode.",
                tool_name=step.tool_name,
                rule="mode_accept_edits",
            )

        if step.mutates_workspace:
            return PermissionDecision(
                behavior="ask",
                reason="DEFAULT mode requires confirmation before mutating workspace actions.",
                tool_name=step.tool_name,
                rule="mode_default_ask",
                requires_human=True,
            )

        return PermissionDecision(
            behavior="allow",
            reason="No matching deny or ask rule.",
            tool_name=step.tool_name,
            rule="fallback_allow",
        )

