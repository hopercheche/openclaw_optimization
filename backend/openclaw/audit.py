from __future__ import annotations

from collections import Counter

from .models import AuditEvent, RunState


def render_audit_markdown(state: RunState, events: list[AuditEvent]) -> str:
    counts = Counter(event.event_type for event in events)
    permissions = [
        event
        for event in events
        if event.event_type == "permission"
    ]
    denied = [
        event
        for event in permissions
        if event.data.get("decision", {}).get("behavior") == "deny"
    ]
    asks = [
        event
        for event in permissions
        if event.data.get("decision", {}).get("behavior") == "ask"
    ]

    lines = [
        f"# Audit Report: {state.run_id}",
        "",
        "## Summary",
        "",
        f"- Goal: {state.goal}",
        f"- Status: {state.status}",
        f"- Permission mode: {state.permission_mode}",
        f"- Planner strategy: {state.planner_strategy}",
        f"- Workspace: `{state.workspace_path}`",
        f"- Created at: {state.created_at}",
        f"- Updated at: {state.updated_at}",
        f"- AS2 available: {state.as2_available}",
        f"- Total events: {len(events)}",
        f"- Permission asks: {len(asks)}",
        f"- Permission denies: {len(denied)}",
        "",
        "## Final Response",
        "",
        state.final_response or "No final response was produced.",
        "",
        "## Event Counts",
        "",
    ]

    for event_type, count in sorted(counts.items()):
        lines.append(f"- {event_type}: {count}")

    lines.extend(["", "## Permission Decisions", ""])
    if not permissions:
        lines.append("- No permission events were recorded.")
    else:
        for event in permissions:
            decision = event.data.get("decision", {})
            lines.append(
                "- "
                f"{event.timestamp} | {decision.get('behavior')} | "
                f"{decision.get('tool_name')} | {decision.get('reason')}"
            )

    lines.extend(["", "## Timeline", ""])
    for event in events:
        lines.append(f"### {event.event_id}. {event.event_type}")
        lines.append("")
        lines.append(f"- Time: {event.timestamp}")
        lines.append(f"- Message: {event.message}")
        if event.data:
            lines.append("- Data:")
            for key, value in event.data.items():
                lines.append(f"  - {key}: `{value}`")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
