"""EvalScope AgentRunner for the minimal AgentScope AliyunCS CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from evalscope.agent.external.runners import AgentRunResult, AgentRunner, BridgeEndpoint, ExternalAgentTask
from evalscope.agent.external.runners.base import RunnerTimeoutError
from evalscope.api.agent import AgentEnvironment
from evalscope.api.registry import register_runner
from evalscope.utils.logger import get_logger

from .constants import (
    API_KEY_ENV,
    BASE_URL_ENV,
    DEFAULT_SYSTEM_PROMPT,
    FRAMEWORK_NAME,
    MODEL_ENV,
    PROTOCOL_ENV,
    SYSTEM_PROMPT_ENV,
)

logger = get_logger()


@register_runner(FRAMEWORK_NAME)
class AgentScopeAliyunCSCliRunner(AgentRunner):
    """Launch ``python -m agentscope_aliyuncs_cli`` as an external agent CLI.

    Kwargs accepted through ``ExternalAgentConfig.kwargs``:

    * ``python_bin``: Python executable used to run the CLI.
    * ``project_dir``: repository root containing this package.
    * ``protocol``: ``responses`` by default; ``chat`` is also supported.
    * ``extra_args``: extra arguments appended before ``--prompt``.
    * ``setup_probe``: import-check the CLI dependencies before each run.
    """

    framework = FRAMEWORK_NAME

    def __init__(
        self,
        *,
        python_bin: str = "python",
        project_dir: str | None = None,
        module: str = "agentscope_aliyuncs_cli",
        protocol: str = "responses",
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        extra_args: List[str] | None = None,
        setup_probe: bool = True,
        setup_timeout_s: float = 30.0,
        model_name: str = "",
        **_: Any,
    ) -> None:
        self._python_bin = python_bin
        self._project_dir = project_dir or str(Path(__file__).resolve().parents[1])
        self._module = module
        self._protocol = protocol
        self._system_prompt = system_prompt
        self._extra_args = list(extra_args or [])
        self._setup_probe = setup_probe
        self._setup_timeout_s = setup_timeout_s
        self._model_name = model_name

    async def setup(self, env: AgentEnvironment) -> None:
        """Verify that the local CLI and AgentScope dependencies import."""

        if not self._setup_probe:
            return

        probe = await env.exec(
            [
                self._python_bin,
                "-c",
                "import agentscope, aliyuncs, agentscope_aliyuncs_cli.cli",
            ],
            cwd=self._project_dir,
            timeout=self._setup_timeout_s,
        )
        if probe.timed_out:
            raise RunnerTimeoutError(f"{FRAMEWORK_NAME} setup probe timed out after {self._setup_timeout_s}s")
        if probe.returncode != 0:
            tail = (probe.stderr or probe.stdout or "").strip()[-2000:]
            raise RuntimeError(f"{FRAMEWORK_NAME} setup probe failed with code {probe.returncode}: {tail}")

    async def run(
        self,
        task: ExternalAgentTask,
        env: AgentEnvironment,
        bridge: BridgeEndpoint,
    ) -> AgentRunResult:
        """Execute the CLI once and return its stdout."""

        model_name = self._model_name or "evalscope-bridge"
        env_vars: Dict[str, str] = {
            BASE_URL_ENV: f"{bridge.base_url}/openai/v1",
            API_KEY_ENV: bridge.trial_token,
            MODEL_ENV: model_name,
            PROTOCOL_ENV: self._protocol,
            SYSTEM_PROMPT_ENV: self._system_prompt,
            "PYTHONUNBUFFERED": "1",
        }
        cmd = [self._python_bin, "-m", self._module]
        cmd.extend(self._extra_args)
        cmd.extend(["--prompt", task.instruction])

        sample_id = (task.metadata or {}).get("sample_id")
        env_name = getattr(env, "name", type(env).__name__)
        logger.info(
            f"{FRAMEWORK_NAME} launching: sample={sample_id} env={env_name} "
            f"model={model_name} protocol={self._protocol} timeout={task.timeout}s "
            f"instruction_chars={len(task.instruction)}"
        )
        result = await env.exec(
            cmd,
            cwd=self._project_dir,
            timeout=task.timeout,
            env=env_vars,
        )
        logger.info(
            f"{FRAMEWORK_NAME} exited: sample={sample_id} rc={result.returncode} "
            f"wall={result.duration:.1f}s stdout={len(result.stdout or '')}B "
            f"stderr={len(result.stderr or '')}B timed_out={result.timed_out}"
        )
        if result.timed_out:
            raise RunnerTimeoutError(f"{FRAMEWORK_NAME} timed out after {task.timeout}s")
        if result.returncode != 0:
            tail_stderr = (result.stderr or "").strip()[-2000:]
            tail_stdout = (result.stdout or "").strip()[-2000:]
            raise RuntimeError(
                f"{FRAMEWORK_NAME} exited with code {result.returncode}: "
                f"{tail_stderr or tail_stdout}"
            )

        return AgentRunResult(
            output=result.stdout.strip(),
            metrics={
                "wall_time": result.duration,
                "returncode": result.returncode,
                "protocol": self._protocol,
            },
        )
