from __future__ import annotations

import heapq
import re
from dataclasses import dataclass, field
from typing import Iterable

from .models import CandidateStep, RunState
from .permissions import PermissionEngine
from .planner_profile_model import predict_goal_profile


DEFAULT_PLANNER_STRATEGY = "greedy_topk"
SUPPORTED_PLANNER_STRATEGIES = {"greedy_topk", "audit_astar", "audit_reflexion"}
_EXECUTION_TOOLS = {
    "file_writer",
    "command_runner",
    "deploy_runner",
    "mobile_gui_runner",
    "mobile_cli_runner",
    "mcp_tool_runner",
}


@dataclass(slots=True)
class PlannerTraceEvent:
    event_type: str
    message: str
    data: dict


@dataclass(slots=True)
class PlannerSelection:
    strategy_name: str
    selected: list[CandidateStep]
    selection_rule: str
    trace_events: list[PlannerTraceEvent] = field(default_factory=list)


@dataclass(slots=True)
class _SearchNode:
    node_id: int
    path: tuple[int, ...]
    tool_names: frozenset[str]
    action_signatures: frozenset[str]
    evidence_total: int
    risk_total: int
    g_cost: float
    h_cost: float
    value: float
    priority: float

    @property
    def depth(self) -> int:
        return len(self.path)

    @property
    def utility(self) -> float:
        return self.value - self.g_cost - self.h_cost


def normalize_planner_strategy(strategy_name: str | None) -> str:
    normalized = (strategy_name or DEFAULT_PLANNER_STRATEGY).strip().lower()
    if normalized not in SUPPORTED_PLANNER_STRATEGIES:
        return DEFAULT_PLANNER_STRATEGY
    return normalized


def select_planner_path(
    candidates: Iterable[CandidateStep],
    state: RunState,
    permission_engine: PermissionEngine,
    strategy_name: str | None,
    max_steps: int = 5,
) -> PlannerSelection:
    strategy = normalize_planner_strategy(strategy_name)
    unique_candidates = _deduplicate_candidates(candidates)
    if strategy == "audit_astar":
        return AuditAStarPlannerStrategy(permission_engine=permission_engine, max_depth=max_steps).select(
            unique_candidates,
            state,
        )
    if strategy == "audit_reflexion":
        return AuditReflexionPlannerStrategy(permission_engine=permission_engine, max_depth=max_steps).select(
            unique_candidates,
            state,
        )
    return GreedyTopKPlannerStrategy(max_steps=max_steps).select(unique_candidates, state)


class GreedyTopKPlannerStrategy:
    name = "greedy_topk"

    def __init__(self, max_steps: int = 5) -> None:
        self.max_steps = max_steps

    def select(self, candidates: list[CandidateStep], _state: RunState) -> PlannerSelection:
        selected = sorted(candidates, key=lambda item: item.score, reverse=True)[: self.max_steps]
        return PlannerSelection(
            strategy_name=self.name,
            selected=selected,
            selection_rule="top_5_by_impact_evidence_reversibility_minus_risk",
        )


class AuditAStarPlannerStrategy:
    """A bounded A* selector for audit-first tool/action candidates."""

    name = "audit_astar"

    def __init__(
        self,
        permission_engine: PermissionEngine,
        max_depth: int = 5,
        max_expansions: int = 48,
        max_trace_events: int = 120,
    ) -> None:
        self.permission_engine = permission_engine
        self.max_depth = max_depth
        self.max_expansions = max_expansions
        self.max_trace_events = max_trace_events

    def select(self, candidates: list[CandidateStep], state: RunState) -> PlannerSelection:
        trace: list[PlannerTraceEvent] = []
        desired_tools = _desired_tools_for_goal(state.goal)
        self._record(trace, "search_started", "Audit-aware A* planner started.", {
            "strategy": self.name,
            "desired_tools": sorted(desired_tools),
            "candidate_count": len(candidates),
            "max_depth": self.max_depth,
            "max_expansions": self.max_expansions,
            "research_basis": ["ToolChain*", "Tree of Thoughts", "LATS"],
        })

        if not candidates:
            return PlannerSelection(
                strategy_name=self.name,
                selected=[],
                selection_rule="audit_astar_empty_candidate_set",
                trace_events=trace,
            )

        shortcut = self._select_profile_aligned_path(candidates, state, desired_tools, trace)
        if shortcut is not None:
            return shortcut

        root = _SearchNode(
            node_id=0,
            path=(),
            tool_names=frozenset(),
            action_signatures=frozenset(),
            evidence_total=0,
            risk_total=0,
            g_cost=0.0,
            h_cost=self._heuristic(frozenset(), 0, 0, desired_tools),
            value=0.0,
            priority=0.0,
        )
        root.priority = root.g_cost + root.h_cost - root.value

        frontier: list[tuple[float, float, int, _SearchNode]] = []
        heapq.heappush(frontier, (root.priority, -root.value, 0, root))
        best = root
        expanded = 0
        next_node_id = 1

        while frontier and expanded < self.max_expansions:
            _priority, _negative_value, _order, node = heapq.heappop(frontier)
            expanded += 1
            self._record(trace, "search_expand", "Expanded planner search node.", {
                "node_id": node.node_id,
                "depth": node.depth,
                "path_titles": [candidates[index].title for index in node.path],
                "g_cost": _rounded(node.g_cost),
                "h_cost": _rounded(node.h_cost),
                "value": _rounded(node.value),
                "priority": _rounded(node.priority),
                "utility": _rounded(node.utility),
            })

            if self._is_better(node, best):
                best = node

            if node.depth >= self.max_depth:
                self._record(trace, "search_prune", "Pruned node at maximum search depth.", {
                    "node_id": node.node_id,
                    "depth": node.depth,
                })
                continue

            for candidate_index, candidate in enumerate(candidates):
                if candidate_index in node.path:
                    continue

                signature = _action_signature(candidate)
                if signature in node.action_signatures:
                    self._record(trace, "search_prune", "Pruned duplicate action signature.", {
                        "node_id": node.node_id,
                        "candidate_title": candidate.title,
                        "signature": signature,
                    })
                    continue

                decision = self.permission_engine.decide(candidate, state.permission_mode)
                tool_names = frozenset((*node.tool_names, candidate.tool_name))
                signatures = frozenset((*node.action_signatures, signature))
                evidence_total = node.evidence_total + candidate.evidence_value
                risk_total = node.risk_total + candidate.risk
                transition_cost = self._transition_cost(candidate, decision.behavior)
                action_value = self._action_value(candidate, desired_tools, node.tool_names, decision.behavior)
                g_cost = node.g_cost + transition_cost
                h_cost = self._heuristic(
                    tool_names,
                    node.depth + 1,
                    evidence_total,
                    desired_tools,
                )
                value = node.value + action_value
                priority = g_cost + h_cost - value
                child = _SearchNode(
                    node_id=next_node_id,
                    path=(*node.path, candidate_index),
                    tool_names=tool_names,
                    action_signatures=signatures,
                    evidence_total=evidence_total,
                    risk_total=risk_total,
                    g_cost=g_cost,
                    h_cost=h_cost,
                    value=value,
                    priority=priority,
                )
                next_node_id += 1

                self._record(trace, "search_score", "Scored planner transition.", {
                    "from_node_id": node.node_id,
                    "to_node_id": child.node_id,
                    "candidate_title": candidate.title,
                    "tool_name": candidate.tool_name,
                    "permission_behavior": decision.behavior,
                    "candidate_score": candidate.score,
                    "transition_cost": _rounded(transition_cost),
                    "action_value": _rounded(action_value),
                    "h_cost": _rounded(h_cost),
                    "priority": _rounded(priority),
                    "remaining_desired_tools": sorted(desired_tools - tool_names),
                })

                if self._is_better(child, best):
                    best = child
                heapq.heappush(frontier, (child.priority, -child.value, child.node_id, child))

        selected = [candidates[index] for index in best.path]
        if not selected:
            selected = sorted(candidates, key=lambda item: item.score, reverse=True)[: self.max_depth]
        selected = selected[: self.max_depth]

        self._record(
            trace,
            "search_selected",
            "A* planner selected audited action path.",
            {
                "strategy": self.name,
                "expanded_nodes": expanded,
                "selected_titles": [step.title for step in selected],
                "selected_tools": [step.tool_name for step in selected],
                "best_utility": _rounded(best.utility),
                "best_priority": _rounded(best.priority),
            },
            force=True,
        )

        return PlannerSelection(
            strategy_name=self.name,
            selected=selected,
            selection_rule=(
                "audit_astar_priority_g_plus_h_minus_value_with_permission_"
                "risk_loop_and_evidence_terms"
            ),
            trace_events=trace,
        )

    def _select_profile_aligned_path(
        self,
        candidates: list[CandidateStep],
        state: RunState,
        desired_tools: set[str],
        trace: list[PlannerTraceEvent],
    ) -> PlannerSelection | None:
        if not (
            _goal_has_explicit_execution_hints(state.goal)
            or _goal_has_learned_execution_hints(state.goal)
        ):
            return None
        if not desired_tools & _EXECUTION_TOOLS:
            return None
        if len(desired_tools) > self.max_depth:
            return None

        selected: list[CandidateStep] = []
        missing_tools: list[str] = []
        for tool_name in _reflection_tool_order(desired_tools):
            if tool_name not in desired_tools:
                continue
            candidate = _best_candidate_for_tool(candidates, tool_name, selected)
            if candidate is None:
                missing_tools.append(tool_name)
                continue
            selected.append(candidate)

        selected = _deduplicate_candidates(_order_reflection_path(selected, desired_tools))
        covered_tools = {step.tool_name for step in selected}
        if missing_tools or not desired_tools.issubset(covered_tools):
            self._record(trace, "search_prune", "Skipped profile-aligned shortcut because coverage was incomplete.", {
                "desired_tools": sorted(desired_tools),
                "covered_tools": sorted(covered_tools),
                "missing_tools": sorted(desired_tools - covered_tools),
            })
            return None

        self._record(trace, "search_expand", "Expanded profile-aligned coverage shortcut.", {
            "node_id": 0,
            "depth": len(selected),
            "path_titles": [candidate.title for candidate in selected],
            "desired_tools": sorted(desired_tools),
            "optimization_basis": "planner_profile execution_tool metadata",
        })
        total_value = 0.0
        total_cost = 0.0
        for index, candidate in enumerate(selected, start=1):
            decision = self.permission_engine.decide(candidate, state.permission_mode)
            action_value = self._action_value(
                candidate,
                desired_tools,
                frozenset(step.tool_name for step in selected[: index - 1]),
                decision.behavior,
            )
            transition_cost = self._transition_cost(candidate, decision.behavior)
            total_value += action_value
            total_cost += transition_cost
            self._record(trace, "search_score", "Scored profile-aligned coverage step.", {
                "candidate_title": candidate.title,
                "tool_name": candidate.tool_name,
                "permission_behavior": decision.behavior,
                "candidate_score": candidate.score,
                "transition_cost": _rounded(transition_cost),
                "action_value": _rounded(action_value),
                "coverage_index": index,
                "remaining_desired_tools": sorted(desired_tools - {step.tool_name for step in selected[:index]}),
            })

        self._record(
            trace,
            "search_selected",
            "A* planner selected profile-aligned coverage path.",
            {
                "strategy": self.name,
                "expanded_nodes": 1,
                "selected_titles": [step.title for step in selected],
                "selected_tools": [step.tool_name for step in selected],
                "best_utility": _rounded(total_value - total_cost),
                "best_priority": _rounded(total_cost - total_value),
            },
            force=True,
        )
        return PlannerSelection(
            strategy_name=self.name,
            selected=selected[: self.max_depth],
            selection_rule="audit_astar_profile_aligned_coverage_shortcut",
            trace_events=trace,
        )

    def _heuristic(
        self,
        tool_names: frozenset[str],
        depth: int,
        evidence_total: int,
        desired_tools: set[str],
    ) -> float:
        remaining_tools = desired_tools - set(tool_names)
        remaining_slots = max(0, self.max_depth - depth)
        unreachable_tools = max(0, len(remaining_tools) - remaining_slots)
        evidence_target = min(20, max(12, len(desired_tools) * 3))
        evidence_gap = max(0, evidence_target - evidence_total) / 2
        return len(remaining_tools) * 3.0 + unreachable_tools * 2.0 + evidence_gap

    def _transition_cost(self, candidate: CandidateStep, permission_behavior: str) -> float:
        permission_cost = {
            "allow": 0.0,
            "ask": 1.5,
            "deny": 2.5,
        }.get(permission_behavior, 3.0)
        mutation_cost = 1.5 if candidate.mutates_workspace else 0.0
        reversibility_gap = max(0, 5 - candidate.reversibility) * 0.7
        return 1.0 + candidate.risk * 1.4 + reversibility_gap + mutation_cost + permission_cost

    def _action_value(
        self,
        candidate: CandidateStep,
        desired_tools: set[str],
        current_tools: frozenset[str],
        permission_behavior: str,
    ) -> float:
        coverage_reward = 10.0 if candidate.tool_name in desired_tools - set(current_tools) else 0.0
        permission_reward = 1.0 if permission_behavior == "allow" else 0.0
        return (
            candidate.impact * 2.0
            + candidate.evidence_value * 1.5
            + candidate.reversibility * 0.5
            + coverage_reward
            + permission_reward
        )

    def _is_better(self, candidate: _SearchNode, best: _SearchNode) -> bool:
        if not candidate.path:
            return False
        if candidate.utility > best.utility + 0.001:
            return True
        if abs(candidate.utility - best.utility) <= 0.001:
            if len(candidate.tool_names) > len(best.tool_names):
                return True
            if candidate.evidence_total > best.evidence_total:
                return True
        return False

    def _record(
        self,
        trace: list[PlannerTraceEvent],
        event_type: str,
        message: str,
        data: dict,
        force: bool = False,
    ) -> None:
        if len(trace) >= self.max_trace_events and not force:
            return
        trace.append(PlannerTraceEvent(event_type=event_type, message=message, data=data))


class AuditReflexionPlannerStrategy:
    """A* path search followed by deterministic Reflexion-style path repair."""

    name = "audit_reflexion"

    def __init__(
        self,
        permission_engine: PermissionEngine,
        max_depth: int = 5,
    ) -> None:
        self.permission_engine = permission_engine
        self.max_depth = max_depth
        self.astar = AuditAStarPlannerStrategy(
            permission_engine=permission_engine,
            max_depth=max_depth,
            max_expansions=64,
            max_trace_events=96,
        )

    def select(self, candidates: list[CandidateStep], state: RunState) -> PlannerSelection:
        base = self.astar.select(candidates, state)
        trace = list(base.trace_events)
        desired_tools = _desired_tools_for_goal(state.goal)
        selected = _deduplicate_candidates(base.selected)
        issues: list[str] = []

        _append_trace(trace, "reflection_started", "Reflexion planner started deterministic path review.", {
            "strategy": self.name,
            "base_strategy": base.strategy_name,
            "desired_tools": sorted(desired_tools),
            "base_selected_tools": [step.tool_name for step in selected],
            "research_basis": [
                "LATS",
                "Reflexion",
                "Self-Refine",
                "Tree of Thoughts",
                "ToolChain*",
                "AFlow",
            ],
        })

        if _goal_disallows_mutation(state.goal):
            selected = _remove_mutating_steps(selected, issues)

        selected = self._ensure_tool(selected, candidates, "risk_model", issues, position="front")
        for tool_name in _reflection_tool_order(desired_tools):
            selected = self._ensure_tool(selected, candidates, tool_name, issues, position="auto")
        selected = self._ensure_tool(selected, candidates, "verifier", issues, position="back")

        selected = _order_reflection_path(selected, desired_tools)
        selected = _trim_reflection_path(selected, desired_tools, self.max_depth, issues)
        selected = _deduplicate_candidates(selected)

        if not selected and candidates:
            issues.append("fallback_to_greedy_candidates_after_empty_reflection")
            selected = GreedyTopKPlannerStrategy(max_steps=self.max_depth).select(candidates, state).selected

        if not issues:
            issues.append("no_path_repair_needed")
        for issue in issues:
            _append_trace(trace, "reflection_issue", "Reflexion planner recorded a path review note.", {
                "issue": issue,
            })

        _append_trace(trace, "reflection_refined", "Reflexion planner selected repaired audited path.", {
            "strategy": self.name,
            "selected_titles": [step.title for step in selected],
            "selected_tools": [step.tool_name for step in selected],
            "covered_desired_tools": sorted(desired_tools & {step.tool_name for step in selected}),
            "missing_desired_tools": sorted(desired_tools - {step.tool_name for step in selected}),
            "issues": issues,
        })

        return PlannerSelection(
            strategy_name=self.name,
            selected=selected,
            selection_rule=(
                "audit_reflexion_astar_path_plus_reflection_coverage_"
                "safety_bookends_and_read_only_repair"
            ),
            trace_events=trace,
        )

    def _ensure_tool(
        self,
        selected: list[CandidateStep],
        candidates: list[CandidateStep],
        tool_name: str,
        issues: list[str],
        position: str,
    ) -> list[CandidateStep]:
        if any(step.tool_name == tool_name for step in selected):
            return selected

        candidate = _best_candidate_for_tool(candidates, tool_name, selected)
        if candidate is None:
            issues.append(f"missing_candidate_for_{tool_name}")
            return selected

        issues.append(f"inserted_{tool_name}")
        if position == "front":
            return [candidate, *selected]
        if position == "back":
            return [*selected, candidate]
        return [*selected, candidate]


def _deduplicate_candidates(candidates: Iterable[CandidateStep]) -> list[CandidateStep]:
    unique: list[CandidateStep] = []
    seen: set[str] = set()
    for candidate in candidates:
        signature = _action_signature(candidate)
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(candidate)
    return unique


def _desired_tools_for_goal(goal: str) -> set[str]:
    lower_goal = goal.lower()
    desired = {
        "goal_analyzer",
        "workspace_inspector",
        "planner",
        "risk_model",
        "verifier",
    }
    explicit_no_edit = _goal_disallows_mutation(goal)
    mutating_goal = not explicit_no_edit and any(term in lower_goal for term in [
        "write",
        "edit",
        "test",
        "delete",
        "remove",
        "优化",
        "修改",
        "测试",
        "验证",
        "删除",
    ])
    production_goal = any(term in lower_goal for term in ["prod", "production", "deploy", "上线", "部署"])
    if mutating_goal:
        desired = {"risk_model", "planner", "file_writer", "command_runner", "verifier"}
    if production_goal:
        desired = {"goal_analyzer", "risk_model", "planner", "deploy_runner", "verifier"}
    profile_tools = _profile_execution_tools_for_goal(goal)
    mobile_tools = _mobile_execution_tools_for_goal(goal)
    learned_tools = _learned_execution_tools_for_goal(goal)
    execution_tools = profile_tools or _merge_learned_and_mobile_execution_tools(goal, learned_tools, mobile_tools)
    if execution_tools:
        if _goal_has_safety_policy(goal) or _learned_policy_mode_for_goal(goal) in {"confirm", "refuse"}:
            desired = {"risk_model", "safety_guard", "planner", execution_tools[0], "verifier"}
        else:
            desired = {"risk_model", "planner", "verifier", *execution_tools[:2]}
    return desired


def _action_signature(candidate: CandidateStep) -> str:
    normalized_action = " ".join(candidate.action.lower().split())[:120]
    return f"{candidate.tool_name}:{normalized_action}"


def _goal_disallows_mutation(goal: str) -> bool:
    lower_goal = goal.lower()
    return any(term in lower_goal for term in [
        "without editing",
        "without modifying",
        "without writing",
        "no edits",
        "read-only",
        "不修改",
        "不要修改",
        "不写入",
        "不要写入",
        "只读",
    ])


def _remove_mutating_steps(candidates: list[CandidateStep], issues: list[str]) -> list[CandidateStep]:
    filtered = [candidate for candidate in candidates if not _is_mutating_step(candidate)]
    removed = len(candidates) - len(filtered)
    if removed:
        issues.append(f"removed_{removed}_mutating_steps_for_explicit_read_only_goal")
    return filtered


def _is_mutating_step(candidate: CandidateStep) -> bool:
    return candidate.mutates_workspace or candidate.tool_name in {
        "file_writer",
        "command_runner",
        "deploy_runner",
        "mobile_gui_runner",
        "mobile_cli_runner",
        "mcp_tool_runner",
    }


def _best_candidate_for_tool(
    candidates: list[CandidateStep],
    tool_name: str,
    selected: list[CandidateStep],
) -> CandidateStep | None:
    selected_signatures = {_action_signature(step) for step in selected}
    matching = [
        candidate
        for candidate in candidates
        if candidate.tool_name == tool_name and _action_signature(candidate) not in selected_signatures
    ]
    if not matching:
        return None
    return sorted(
        matching,
        key=lambda item: (
            item.score,
            item.evidence_value,
            item.reversibility,
            -item.risk,
        ),
        reverse=True,
    )[0]


def _reflection_tool_order(desired_tools: set[str]) -> list[str]:
    if "deploy_runner" in desired_tools:
        return ["goal_analyzer", "risk_model", "planner", "deploy_runner", "verifier"]
    if any(tool in desired_tools for tool in ["mobile_gui_runner", "mobile_cli_runner", "mcp_tool_runner"]):
        return [
            "risk_model",
            "safety_guard",
            "planner",
            "mcp_tool_runner",
            "mobile_cli_runner",
            "mobile_gui_runner",
            "verifier",
        ]
    if "file_writer" in desired_tools or "command_runner" in desired_tools:
        return ["risk_model", "planner", "file_writer", "command_runner", "verifier"]
    return ["goal_analyzer", "workspace_inspector", "planner", "risk_model", "verifier"]


def _profile_execution_tools_for_goal(goal: str) -> list[str]:
    lower_goal = goal.lower()
    found: list[str] = []
    for marker in ["execution_tools=", "execution_tool="]:
        start = lower_goal.find(marker)
        if start < 0:
            continue
        raw_value = lower_goal[start + len(marker):]
        raw_value = raw_value.split("]", 1)[0].split(";", 1)[0]
        raw_value = raw_value.replace("|", ",").replace(" ", ",")
        for item in raw_value.split(","):
            tool_name = item.strip()
            if tool_name in _EXECUTION_TOOLS:
                found.append(tool_name)
    return _ordered_execution_tools(found)


def _learned_execution_tools_for_goal(goal: str) -> list[str]:
    if _profile_execution_tools_for_goal(goal):
        return []
    if _goal_disallows_mutation(goal):
        return []
    prediction = predict_goal_profile(goal)
    if prediction.tools_confidence < 0.55:
        return []
    if _goal_has_local_project_terms(goal) and not _allow_learned_tools_for_local_goal(prediction):
        return []
    return _ordered_execution_tools(prediction.execution_tools or [])


def _merge_learned_and_mobile_execution_tools(
    goal: str,
    learned_tools: list[str],
    mobile_tools: list[str],
) -> list[str]:
    if not learned_tools:
        return mobile_tools
    prediction = predict_goal_profile(goal)
    if (
        prediction.profile_confidence >= 0.55
        and prediction.planner_profile in {"skill_workflow", "api_planning", "policy_tool_agent"}
    ):
        return learned_tools
    return _ordered_execution_tools([*learned_tools, *mobile_tools])


def _goal_has_learned_execution_hints(goal: str) -> bool:
    if _profile_execution_tools_for_goal(goal):
        return False
    if _goal_disallows_mutation(goal):
        return False
    prediction = predict_goal_profile(goal)
    if not prediction.has_execution_tools or prediction.tools_confidence < 0.55:
        return False
    if _goal_has_local_project_terms(goal) and not _allow_learned_tools_for_local_goal(prediction):
        return False
    return True


def _allow_learned_tools_for_local_goal(prediction) -> bool:
    return (
        prediction.planner_profile == "skill_workflow"
        and prediction.profile_confidence >= 0.85
        and prediction.tools_confidence >= 0.85
    )


def _mobile_execution_tools_for_goal(goal: str) -> list[str]:
    lower_goal = goal.lower()
    mobile_context = _has_mobile_context(lower_goal)
    tools: list[str] = []
    if any(term in lower_goal for term in [
        "mcp",
        "email",
        "mail",
        "send_email",
        "calendar",
        "create_calendar",
        "邮件",
        "邮箱",
        "日历",
        "提醒",
    ]):
        tools.append("mcp_tool_runner")
    if mobile_context and any(term in lower_goal for term in [
        "cli",
        "shell",
        "adb",
        "termux",
        "command",
        "python",
        "命令",
        "脚本",
    ]):
        tools.append("mobile_cli_runner")
    if any(term in lower_goal for term in [
        "phoneharness",
        "gui",
        "app",
        "android",
        "phone",
        "mobile",
        "手机",
        "打开",
        "搜索",
        "查看",
        "设置",
        "美团",
        "地图",
        "视频",
        "音乐",
        "相册",
        "照片",
        "浏览器",
    ]):
        tools.append("mobile_gui_runner")
    return _ordered_execution_tools(tools)


def _has_mobile_context(lower_goal: str) -> bool:
    return any(term in lower_goal for term in [
        "phoneharness",
        "mobile",
        "android",
        "gui/",
        "gui-primary",
        "adb",
        "termux",
        "手机",
    ])


def _goal_has_safety_policy(goal: str) -> bool:
    lower_goal = goal.lower()
    return any(term in lower_goal for term in [
        "safety_policy",
        "policy_mode=refuse",
        "policy_mode=confirm",
        "safe_complete",
        "confirm_first",
        "never_auto",
        "安全",
        "确认",
        "禁止自动",
    ])


def _learned_policy_mode_for_goal(goal: str) -> str:
    if _profile_execution_tools_for_goal(goal):
        return ""
    prediction = predict_goal_profile(goal)
    if prediction.policy_confidence < 0.55:
        return ""
    if (
        prediction.planner_profile != "policy_tool_agent"
        and not _has_sensitive_policy_terms(goal)
    ):
        return ""
    return prediction.policy_mode


def _has_sensitive_policy_terms(goal: str) -> bool:
    lower_goal = goal.lower()
    return any(term in lower_goal for term in [
        "confirm",
        "confirmation",
        "approval",
        "refund",
        "cancel",
        "cancellation",
        "delete",
        "export",
        "privacy",
        "private",
        "sensitive",
        "确认",
        "批准",
        "退款",
        "取消",
        "删除",
        "删",
        "导出",
        "隐私",
        "通讯录",
        "联系人",
        "电话",
        "相册",
        "照片",
        "清理",
        "存储",
        "敏感",
    ])


def _goal_has_local_project_terms(goal: str) -> bool:
    lower_goal = goal.lower()
    if re.search(r"\b(benchmark|readme|openclaw|repository|workspace|production|deploy)\b", lower_goal):
        return True
    if re.search(r"\bplanner\b", lower_goal) and re.search(
        r"\b(code|file|files|workspace|benchmark|implementation)\b",
        lower_goal,
    ):
        return True
    return any(term in lower_goal for term in [
        "优化",
        "修改",
        "测试",
        "验证",
        "删除",
        "部署",
        "上线",
    ])


def _goal_has_explicit_execution_hints(goal: str) -> bool:
    lower_goal = goal.lower()
    return any(term in lower_goal for term in [
        "planner_profile=",
        "source_family=",
        "execution_tool=",
        "execution_tools=",
    ])


def _ordered_execution_tools(tools: Iterable[str]) -> list[str]:
    seen = set(tools)
    ordered = [
        "mcp_tool_runner",
        "mobile_cli_runner",
        "mobile_gui_runner",
        "file_writer",
        "command_runner",
        "deploy_runner",
    ]
    return [tool for tool in ordered if tool in seen]


def _order_reflection_path(candidates: list[CandidateStep], desired_tools: set[str]) -> list[CandidateStep]:
    order = _reflection_tool_order(desired_tools)
    priority = {tool_name: index for index, tool_name in enumerate(order)}
    return sorted(
        candidates,
        key=lambda item: (
            priority.get(item.tool_name, len(priority) + 1),
            -item.score,
            item.risk,
            item.title,
        ),
    )


def _trim_reflection_path(
    candidates: list[CandidateStep],
    desired_tools: set[str],
    max_depth: int,
    issues: list[str],
) -> list[CandidateStep]:
    if len(candidates) <= max_depth:
        return candidates

    required = set(desired_tools)
    selected: list[CandidateStep] = []
    for candidate in candidates:
        if candidate.tool_name in required:
            selected.append(candidate)
            required.remove(candidate.tool_name)
        if len(selected) == max_depth:
            break
    for candidate in candidates:
        if len(selected) == max_depth:
            break
        if _action_signature(candidate) in {_action_signature(step) for step in selected}:
            continue
        selected.append(candidate)

    issues.append(f"trimmed_path_from_{len(candidates)}_to_{len(selected)}")
    return selected


def _append_trace(
    trace: list[PlannerTraceEvent],
    event_type: str,
    message: str,
    data: dict,
) -> None:
    trace.append(PlannerTraceEvent(event_type=event_type, message=message, data=data))


def _rounded(value: float) -> float:
    return round(value, 3)
