"""EvalScope AgentRunner for an OpenClaw CLI harness."""

from __future__ import annotations

import asyncio
import json
import re
import shlex
from typing import Any, Dict, Iterable, List
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from evalscope.agent.external.runners import AgentRunResult, AgentRunner, BridgeEndpoint, ExternalAgentTask
from evalscope.agent.external.runners.base import RunnerTimeoutError
from evalscope.api.agent import AgentEnvironment
from evalscope.api.registry import register_runner
from evalscope.utils.logger import get_logger

from .constants import (
    DEFAULT_AGENT_ID,
    DEFAULT_CLI_SERVICE,
    DEFAULT_COMPOSE_PROJECT,
    DEFAULT_GATEWAY_INTERNAL_PORT,
    DEFAULT_GATEWAY_SERVICE,
    DEFAULT_PROTOCOL,
    DEFAULT_PROVIDER_ID,
    DEFAULT_SESSION_KEY_PREFIX,
    FRAMEWORK_NAME,
)
from .output import parse_openclaw_stdout

logger = get_logger()


def _tail(text: str | None, limit: int = 2000) -> str:
    return (text or "").strip()[-limit:]


def _redact(text: str, secrets: Iterable[str]) -> str:
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "<redacted>")
    return redacted


def _safe_fragment(value: Any) -> str:
    raw = str(value or "").strip()
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._-")
    return safe or uuid4().hex[:12]


def _as_list(value: str | List[str] | None) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _as_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    raise TypeError(f"expected an object, got {type(value).__name__}")


def _parse_prometheus(text: str) -> Dict[str, float]:
    samples: Dict[str, float] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or not line.startswith("openclaw_"):
            continue
        try:
            series, raw_value = line.rsplit(None, 1)
            samples[series] = float(raw_value)
        except (ValueError, TypeError):
            continue
    return samples


def _prometheus_delta(before: Dict[str, float], after: Dict[str, float]) -> Dict[str, float]:
    result: Dict[str, float] = {}
    for series, value in after.items():
        delta = value - before.get(series, 0.0)
        if delta > 0:
            result[series] = delta
    return result


DEFAULT_WORKSPACE_PRESERVE_ENTRIES = [
    ".git",
    ".agents",
    "skills",
    "memory",
    "AGENTS.md",
    "SOUL.md",
    "TOOLS.md",
    "IDENTITY.md",
    "USER.md",
    "HEARTBEAT.md",
    "BOOTSTRAP.md",
    "MEMORY.md",
    "openclaw-workspace-state.json",
]


def _normalize_workspace_entries(entries: Iterable[Any]) -> List[str]:
    normalized: List[str] = []
    seen: set[str] = set()
    for entry in entries:
        name = str(entry or "").strip().strip("/")
        if not name or name in {".", ".."} or "/" in name:
            continue
        if name not in seen:
            seen.add(name)
            normalized.append(name)
    return normalized


@register_runner(FRAMEWORK_NAME)
class OpenClawCliHarnessRunner(AgentRunner):
    """Drive ``openclaw agent --json`` through Docker Compose.

    Kwargs accepted through ``ExternalAgentConfig.kwargs``:

    * ``compose_project``: Docker Compose project name.
    * ``compose_files`` / ``compose_file``: compose file path(s).
    * ``compose_dir``: working directory for docker compose commands.
    * ``gateway_service``: long-running OpenClaw Gateway service.
    * ``cli_service``: service used for one-off CLI invocations.
    * ``agent_id``: OpenClaw agent id, default ``main``.
    * ``protocol``: ``responses`` (default) or ``chat`` for the bridge provider.
    * ``bridge_host_for_container``: replace host-loopback bridge URLs with this host.
    * ``auto_up``: run ``docker compose up -d <gateway_service>`` in setup.
    * ``clean_workspace``: remove files from the OpenClaw workspace before each sample.
    """

    framework = FRAMEWORK_NAME

    def __init__(
        self,
        *,
        compose_project: str = DEFAULT_COMPOSE_PROJECT,
        compose_files: str | List[str] | None = None,
        compose_file: str | List[str] | None = None,
        compose_dir: str | None = None,
        gateway_service: str = DEFAULT_GATEWAY_SERVICE,
        cli_service: str = DEFAULT_CLI_SERVICE,
        gateway_internal_port: int = DEFAULT_GATEWAY_INTERNAL_PORT,
        agent_id: str = DEFAULT_AGENT_ID,
        provider_id: str = DEFAULT_PROVIDER_ID,
        protocol: str = DEFAULT_PROTOCOL,
        provider_api: str | None = None,
        model_name: str = "",
        router_enabled: bool = False,
        router_service: str = "openclaw-router-api",
        router_plugin_id: str = "openclaw-router",
        router_endpoint: str = "http://openclaw-router-api:3000",
        router_entry_model: str = "router-entry",
        router_tiers: Dict[str, str] | str | None = None,
        router_models: List[Dict[str, Any]] | str | None = None,
        router_confidence_threshold: float = 0.5,
        router_request_timeout_ms: int = 5000,
        router_strict: bool = True,
        router_collect_metrics: bool = True,
        router_plugin_path: str = "/opt/openclaw-plugins/openclaw-router",
        prometheus_plugin_path: str = "/opt/openclaw-plugins/diagnostics-prometheus",
        bridge_host_for_container: str = "host.docker.internal",
        auto_up: bool = True,
        setup_timeout_s: float = 180.0,
        health_timeout_s: float = 120.0,
        health_interval_s: float = 2.0,
        agent_timeout_s: int = 600,
        exec_timeout_grace_s: float = 30.0,
        clean_workspace: bool = True,
        workspace_path: str = "/home/node/.openclaw/workspace",
        preserve_workspace_git: bool = True,
        workspace_preserve_entries: str | List[str] | None = None,
        workspace_preserve_extra_entries: str | List[str] | None = None,
        workspace_clean_timeout_s: float = 60.0,
        extra_agent_args: List[str] | None = None,
        session_key_template: str | None = None,
        **_: Any,
    ) -> None:
        self._compose_project = compose_project
        self._compose_files = _as_list(compose_files) + _as_list(compose_file)
        self._compose_dir = compose_dir
        self._gateway_service = gateway_service
        self._cli_service = cli_service
        self._gateway_internal_port = int(gateway_internal_port)
        self._agent_id = agent_id
        self._router_enabled = _as_bool(router_enabled, False)
        self._router_service = router_service
        self._router_plugin_id = router_plugin_id
        self._router_endpoint = router_endpoint.rstrip("/")
        self._router_entry_model = router_entry_model
        self._router_tiers = _as_dict(router_tiers)
        if isinstance(router_models, str):
            parsed_models = json.loads(router_models)
        else:
            parsed_models = router_models
        if parsed_models is not None and not isinstance(parsed_models, list):
            raise TypeError("router_models must be a list")
        self._router_models = list(parsed_models or [])
        self._router_confidence_threshold = float(router_confidence_threshold)
        self._router_request_timeout_ms = int(router_request_timeout_ms)
        self._router_strict = _as_bool(router_strict, True)
        self._router_collect_metrics = _as_bool(router_collect_metrics, True)
        self._router_plugin_path = router_plugin_path
        self._prometheus_plugin_path = prometheus_plugin_path
        self._provider_id = self._router_plugin_id if self._router_enabled else provider_id
        self._protocol = protocol
        self._provider_api = provider_api
        self._model_name = model_name
        self._bridge_host_for_container = bridge_host_for_container
        self._auto_up = _as_bool(auto_up, True)
        self._setup_timeout_s = float(setup_timeout_s)
        self._health_timeout_s = float(health_timeout_s)
        self._health_interval_s = float(health_interval_s)
        self._agent_timeout_s = int(agent_timeout_s)
        self._exec_timeout_grace_s = float(exec_timeout_grace_s)
        self._clean_workspace_enabled = _as_bool(clean_workspace, True)
        self._workspace_path = workspace_path or "/home/node/.openclaw/workspace"
        self._preserve_workspace_git = _as_bool(preserve_workspace_git, True)
        preserve_entries = (
            _as_list(workspace_preserve_entries)
            if workspace_preserve_entries is not None
            else list(DEFAULT_WORKSPACE_PRESERVE_ENTRIES)
        )
        preserve_entries.extend(_as_list(workspace_preserve_extra_entries))
        if not self._preserve_workspace_git:
            preserve_entries = [entry for entry in preserve_entries if entry != ".git"]
        self._workspace_preserve_entries = _normalize_workspace_entries(preserve_entries)
        self._workspace_clean_timeout_s = float(workspace_clean_timeout_s)
        self._extra_agent_args = list(extra_agent_args or [])
        self._session_key_template = session_key_template

        if self._router_enabled:
            missing_tiers = {"small", "mid", "large"} - set(self._router_tiers)
            if missing_tiers:
                raise ValueError(f"router_tiers is missing: {sorted(missing_tiers)}")
            model_ids = {str(model.get("id", "")) for model in self._router_models}
            unknown_targets = set(self._router_tiers.values()) - model_ids
            if unknown_targets:
                raise ValueError(f"router tier targets are missing from router_models: {sorted(unknown_targets)}")

    async def setup(self, env: AgentEnvironment) -> None:
        compose_version = await env.exec(["docker", "compose", "version"], timeout=self._setup_timeout_s)
        if compose_version.returncode != 0:
            raise RuntimeError(f"docker compose probe failed: {_tail(compose_version.stderr or compose_version.stdout)}")

        if self._auto_up:
            up = await env.exec(
                self._compose_cmd(["up", "-d", self._gateway_service]),
                cwd=self._compose_dir,
                timeout=self._setup_timeout_s,
            )
            if up.returncode != 0:
                raise RuntimeError(f"OpenClaw gateway startup failed: {_tail(up.stderr or up.stdout)}")

        await self._wait_for_gateway_health(env)

        version = await self._compose_run_cli(env, ["--version"], timeout=self._setup_timeout_s)
        if version.returncode != 0:
            raise RuntimeError(f"OpenClaw CLI version probe failed: {_tail(version.stderr or version.stdout)}")

        if self._router_enabled:
            plugin_was_loaded = await self._router_plugin_loaded(env)
            await self._configure_router_plugins(env)
            if not plugin_was_loaded:
                restart = await env.exec(
                    self._compose_cmd(["restart", self._gateway_service]),
                    cwd=self._compose_dir,
                    timeout=self._setup_timeout_s,
                )
                if restart.returncode != 0:
                    raise RuntimeError(f"OpenClaw gateway restart failed: {_tail(restart.stderr or restart.stdout)}")
                await self._wait_for_gateway_health(env)
            await self._verify_router_setup(env)

    async def run(
        self,
        task: ExternalAgentTask,
        env: AgentEnvironment,
        bridge: BridgeEndpoint,
    ) -> AgentRunResult:
        model_name = self._router_entry_model if self._router_enabled else (self._model_name or "evalscope-bridge")
        model_ref = f"{self._provider_id}/{model_name}"
        sample_id = (task.metadata or {}).get("sample_id")
        session_key = self._build_session_key(sample_id)
        agent_timeout = max(1, int(task.timeout or self._agent_timeout_s))
        sample_label = sample_id if sample_id is not None else "<none>"

        workspace_cleanup: Dict[str, Any] = {"enabled": self._clean_workspace_enabled}
        if self._clean_workspace_enabled:
            workspace_cleanup = await self._clean_workspace(env, sample_label)

        await self._configure_bridge_provider(
            env=env,
            bridge=bridge,
            model_name=model_name,
            model_ref=model_ref,
        )
        if self._router_enabled:
            await self._configure_router_sample_id(env, str(sample_label))

        prometheus_before = await self._scrape_prometheus(env) if self._router_collect_metrics and self._router_enabled else {}

        agent_cmd = [
            "openclaw",
            "agent",
            "--agent",
            self._agent_id,
            "--session-key",
            session_key,
            "--model",
            model_ref,
            "--message-file",
            "__PROMPT_FILE__",
            "--json",
            "--timeout",
            str(agent_timeout),
        ]
        agent_cmd.extend(self._extra_agent_args)
        agent_shell_cmd = shlex.join(agent_cmd).replace("__PROMPT_FILE__", '"$prompt_file"')
        script = "\n".join(
            [
                "set -eu",
                'prompt_file="$(mktemp -t evalscope-openclaw.XXXXXX)"',
                'trap \'rm -f "$prompt_file"\' EXIT',
                'cat > "$prompt_file"',
                f"exec {agent_shell_cmd}",
            ]
        )

        logger.info(
            f"{FRAMEWORK_NAME} launching: sample={sample_label} model={model_ref} "
            f"session={session_key} timeout={task.timeout}s instruction_chars={len(task.instruction)}"
        )
        exec_timeout = float(task.timeout or agent_timeout) + self._exec_timeout_grace_s
        result = await self._compose_run_cli(
            env,
            ["-lc", script],
            input=task.instruction,
            timeout=exec_timeout,
            entrypoint="sh",
        )
        logger.info(
            f"{FRAMEWORK_NAME} exited: sample={sample_label} rc={result.returncode} "
            f"wall={result.duration:.1f}s stdout={len(result.stdout or '')}B "
            f"stderr={len(result.stderr or '')}B timed_out={result.timed_out}"
        )
        if result.timed_out:
            raise RunnerTimeoutError(f"{FRAMEWORK_NAME} timed out after {exec_timeout}s")
        if result.returncode != 0:
            err = _redact(_tail(result.stderr or result.stdout), [bridge.trial_token])
            raise RuntimeError(f"{FRAMEWORK_NAME} exited with code {result.returncode}: {err}")

        try:
            envelope, output = parse_openclaw_stdout(result.stdout)
        except ValueError as exc:
            err = _redact(_tail(result.stdout), [bridge.trial_token])
            raise RuntimeError(f"{FRAMEWORK_NAME} could not parse OpenClaw JSON: {exc}; stdout_tail={err}") from exc

        prometheus_after = await self._scrape_prometheus(env) if self._router_collect_metrics and self._router_enabled else {}
        agent_meta = self._extract_agent_meta(envelope)

        return AgentRunResult(
            output=output,
            metrics={
                "wall_time": result.duration,
                "returncode": result.returncode,
                "protocol": self._protocol,
                "model_ref": model_ref,
                "session_key": session_key,
                "openclaw_status": envelope.get("status"),
                "workspace_cleanup": workspace_cleanup,
                "router_enabled": self._router_enabled,
                "router_tiers": self._router_tiers if self._router_enabled else None,
                "openclaw_agent_meta": agent_meta,
                "openclaw_prometheus_delta": _prometheus_delta(prometheus_before, prometheus_after),
            },
        )

    def _compose_cmd(self, subcommand: List[str]) -> List[str]:
        cmd = ["docker", "compose"]
        for compose_file in self._compose_files:
            cmd.extend(["-f", compose_file])
        if self._compose_project:
            cmd.extend(["-p", self._compose_project])
        cmd.extend(subcommand)
        return cmd

    async def _compose_run_cli(
        self,
        env: AgentEnvironment,
        args: List[str],
        *,
        input: str | None = None,
        timeout: float | None = None,
        entrypoint: str | None = None,
    ):
        cmd = self._compose_cmd(["run", "--rm", "--no-deps", "-T"])
        if entrypoint:
            cmd.extend(["--entrypoint", entrypoint])
        cmd.append(self._cli_service)
        cmd.extend(args)
        return await env.exec(cmd, cwd=self._compose_dir, input=input, timeout=timeout)

    async def _compose_exec_gateway(self, env: AgentEnvironment, args: List[str], *, timeout: float | None = None):
        return await env.exec(
            self._compose_cmd(["exec", "-T", self._gateway_service, *args]),
            cwd=self._compose_dir,
            timeout=timeout,
        )

    async def _clean_workspace(self, env: AgentEnvironment, sample_label: Any) -> Dict[str, Any]:
        workspace_literal = shlex.quote(self._workspace_path)
        preserve_entries = "\n".join(self._workspace_preserve_entries)
        script = "\n".join(
            [
                "set -eu",
                f"workspace={workspace_literal}",
                'preserve_file="$(mktemp -t openclaw-preserve.XXXXXX)"',
                'removed_file="$(mktemp -t openclaw-removed.XXXXXX)"',
                'trap \'rm -f "$preserve_file" "$removed_file"\' EXIT',
                "cat > \"$preserve_file\" <<'PRESERVE_ENTRIES'",
                preserve_entries,
                "PRESERVE_ENTRIES",
                'mkdir -p "$workspace"',
                'before="$(find "$workspace" -mindepth 1 -maxdepth 1 | wc -l | tr -d \' \')"',
                "removed_count=0",
                'for path in "$workspace"/* "$workspace"/.[!.]* "$workspace"/..?*; do',
                '  [ -e "$path" ] || continue',
                '  base="${path##*/}"',
                '  if grep -Fxq -- "$base" "$preserve_file"; then',
                "    continue",
                "  fi",
                '  rm -rf -- "$path"',
                '  removed_count=$((removed_count + 1))',
                '  printf "%s\\n" "$base" >> "$removed_file"',
                "done",
                'after="$(find "$workspace" -mindepth 1 -maxdepth 1 | wc -l | tr -d \' \')"',
                'node - "$workspace" "$before" "$after" "$removed_count" "$preserve_file" "$removed_file" <<\'NODE\'',
                "const fs = require('fs');",
                "const [workspace, before, after, removedCount, preservePath, removedPath] = process.argv.slice(2);",
                "const readLines = (file) => fs.readFileSync(file, 'utf8').split(/\\n/).filter(Boolean);",
                "console.log(JSON.stringify({",
                "  enabled: true,",
                "  workspace,",
                "  entries_before: Number(before),",
                "  entries_after: Number(after),",
                "  removed_count: Number(removedCount),",
                "  removed_entries: readLines(removedPath),",
                "  preserved_entries: readLines(preservePath),",
                "}));",
                "NODE",
            ]
        )
        result = await self._compose_run_cli(
            env,
            ["-lc", script],
            timeout=self._workspace_clean_timeout_s,
            entrypoint="sh",
        )
        if result.returncode != 0:
            raise RuntimeError(f"OpenClaw workspace cleanup failed: {_tail(result.stderr or result.stdout)}")
        try:
            payload = json.loads((result.stdout or "").strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"OpenClaw workspace cleanup returned invalid JSON: {_tail(result.stdout)}") from exc

        logger.info(
            f"{FRAMEWORK_NAME} workspace cleanup: sample={sample_label} "
            f"path={payload.get('workspace')} before={payload.get('entries_before')} "
            f"after={payload.get('entries_after')} removed={payload.get('removed_count')} "
            f"preserved={len(payload.get('preserved_entries') or [])}"
        )
        return payload

    async def _wait_for_gateway_health(self, env: AgentEnvironment) -> None:
        script = (
            f"fetch('http://127.0.0.1:{self._gateway_internal_port}/healthz')"
            ".then((r)=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
        )
        deadline = asyncio.get_running_loop().time() + self._health_timeout_s
        last = None
        while True:
            last = await self._compose_exec_gateway(env, ["node", "-e", script], timeout=15.0)
            if last.returncode == 0:
                return
            if asyncio.get_running_loop().time() >= deadline:
                break
            await asyncio.sleep(self._health_interval_s)
        raise RuntimeError(f"OpenClaw gateway health check failed: {_tail((last.stderr or last.stdout) if last else '')}")

    async def _configure_bridge_provider(
        self,
        *,
        env: AgentEnvironment,
        bridge: BridgeEndpoint,
        model_name: str,
        model_ref: str,
    ) -> None:
        base_url = f"{self._rewrite_bridge_base_url(bridge.base_url).rstrip('/')}/openai/v1"
        models: List[Dict[str, Any]]
        if self._router_enabled:
            max_context = max((int(model.get("contextWindow", 0) or 0) for model in self._router_models), default=128000)
            max_output = max((int(model.get("maxTokens", 0) or 0) for model in self._router_models), default=8192)
            entry_model = {
                "id": self._router_entry_model,
                "name": self._router_entry_model,
                "reasoning": True,
                "input": ["text"],
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                "contextWindow": max_context or 128000,
                "maxTokens": max_output or 8192,
            }
            models = [entry_model, *self._router_models]
        else:
            models = [{"id": model_name, "name": model_name}]
        provider_config: Dict[str, Any] = {
            "baseUrl": base_url,
            "apiKey": bridge.trial_token,
            "api": self._resolve_provider_api(),
            "models": models,
        }
        await self._openclaw_config_set(
            env,
            f"models.providers.{self._provider_id}",
            provider_config,
            secrets=[bridge.trial_token],
        )
        await self._openclaw_config_set(
            env,
            "agents.defaults.models",
            {model_ref: {}},
            merge=True,
            secrets=[bridge.trial_token],
        )

    async def _configure_router_plugins(self, env: AgentEnvironment) -> None:
        plugin_config: Dict[str, Any] = {
            "endpoint": self._router_endpoint,
            "confidenceThreshold": self._router_confidence_threshold,
            "requestTimeoutMs": self._router_request_timeout_ms,
            "strict": self._router_strict,
            "tiers": self._router_tiers,
        }

        await self._openclaw_config_set(
            env,
            "plugins",
            {
                "load": {"paths": [self._router_plugin_path]},
                "allow": [self._router_plugin_id, "diagnostics-prometheus"],
                "entries": {
                    self._router_plugin_id: {"enabled": True, "config": plugin_config},
                    "diagnostics-prometheus": {"enabled": True},
                },
            },
            merge=True,
        )
        await self._openclaw_config_set(env, "diagnostics.enabled", True)

    async def _configure_router_sample_id(self, env: AgentEnvironment, sample_id: str) -> None:
        await self._openclaw_config_set(
            env,
            f"plugins.entries.{self._router_plugin_id}.config.evalSampleId",
            sample_id,
        )

    async def _verify_router_setup(self, env: AgentEnvironment) -> None:
        plugin = await self._compose_run_cli(
            env,
            ["plugins", "inspect", self._router_plugin_id],
            timeout=self._setup_timeout_s,
        )
        if plugin.returncode != 0 or "Status: loaded" not in (plugin.stdout or ""):
            raise RuntimeError(f"OpenClaw router plugin probe failed: {_tail(plugin.stderr or plugin.stdout)}")

        router_health_script = (
            f"fetch('http://{self._router_service}:3000/health')"
            ".then(async(r)=>{const b=await r.text();console.log(b);process.exit(r.ok?0:1)})"
            ".catch((e)=>{console.error(e);process.exit(1)})"
        )
        health = await self._compose_exec_gateway(env, ["node", "-e", router_health_script], timeout=15.0)
        if health.returncode != 0:
            raise RuntimeError(f"OpenClaw router API health probe failed: {_tail(health.stderr or health.stdout)}")

        if self._router_collect_metrics:
            await self._scrape_prometheus(env)

    async def _router_plugin_loaded(self, env: AgentEnvironment) -> bool:
        result = await self._compose_run_cli(
            env,
            ["plugins", "inspect", self._router_plugin_id],
            timeout=self._setup_timeout_s,
        )
        return result.returncode == 0 and "Status: loaded" in (result.stdout or "")

    async def _scrape_prometheus(self, env: AgentEnvironment) -> Dict[str, float]:
        script = f"""
const token = process.env.OPENCLAW_GATEWAY_TOKEN || '';
fetch('http://127.0.0.1:{self._gateway_internal_port}/api/diagnostics/prometheus', {{
  headers: {{ Authorization: `Bearer ${{token}}` }},
}}).then(async (response) => {{
  const body = await response.text();
  if (!response.ok) {{
    console.error(`${{response.status}}: ${{body}}`);
    process.exit(1);
  }}
  process.stdout.write(body);
}}).catch((error) => {{
  console.error(error);
  process.exit(1);
}});
""".strip()
        result = await self._compose_exec_gateway(env, ["node", "-e", script], timeout=15.0)
        if result.returncode != 0:
            raise RuntimeError(f"OpenClaw Prometheus scrape failed: {_tail(result.stderr or result.stdout)}")
        return _parse_prometheus(result.stdout or "")

    @staticmethod
    def _extract_agent_meta(envelope: Dict[str, Any]) -> Dict[str, Any] | None:
        candidates = [
            ((envelope.get("result") or {}).get("meta") or {}).get("agentMeta"),
            ((envelope.get("meta") or {}).get("agentMeta")),
        ]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            return {
                key: candidate.get(key)
                for key in ("provider", "model", "usage", "lastCallUsage", "durationMs")
                if candidate.get(key) is not None
            }
        return None

    async def _openclaw_config_set(
        self,
        env: AgentEnvironment,
        path: str,
        value: Any,
        *,
        merge: bool = False,
        secrets: Iterable[str] = (),
    ) -> None:
        encoded = json.dumps(value, separators=(",", ":"))
        args = ["config", "set", path, encoded, "--strict-json"]
        if merge:
            args.append("--merge")
        result = await self._compose_run_cli(env, args, timeout=self._setup_timeout_s)
        if result.returncode != 0:
            err = _redact(_tail(result.stderr or result.stdout), secrets)
            raise RuntimeError(f"OpenClaw config set failed for {path}: {err}")

    def _resolve_provider_api(self) -> str:
        if self._provider_api:
            return self._provider_api
        if self._protocol == "responses":
            return "openai-responses"
        if self._protocol == "chat":
            return "openai-completions"
        raise ValueError("protocol must be 'responses' or 'chat' unless provider_api is set")

    def _rewrite_bridge_base_url(self, base_url: str) -> str:
        if not self._bridge_host_for_container:
            return base_url
        parts = urlsplit(base_url)
        if parts.hostname not in {"127.0.0.1", "localhost", "0.0.0.0"}:
            return base_url
        netloc = self._bridge_host_for_container
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))

    def _build_session_key(self, sample_id: Any) -> str:
        safe_sample = _safe_fragment(sample_id)
        if self._session_key_template:
            return self._session_key_template.format(
                agent_id=self._agent_id,
                sample_id=safe_sample,
                raw_sample_id=sample_id or "",
                uuid=uuid4().hex,
            )
        return f"agent:{self._agent_id}:{DEFAULT_SESSION_KEY_PREFIX}-{safe_sample}"
