"""Glue between :class:`DefaultDataAdapter` and the bridge / runner stack.

The adapter layer is intentionally a single function (no wrapper class) so
that the branch added to ``DefaultDataAdapter._on_inference`` stays narrow
and every benchmark gets external-agent support for free.

``AgentLoopAdapter`` benchmarks (e.g. SWE-bench Pro) reach the same entry
point but pass an ``environment_override`` produced by their per-sample
``build_environment(sample)``, plus a ``post_run_hook`` that recovers the
benchmark's prediction artifact (e.g. ``git diff``) from the sandbox
before it is closed.
"""

import os
import platform
import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, Optional

from evalscope.api.agent import AgentEnvironment, AgentTrace
from evalscope.api.evaluator import InferenceResult
from evalscope.api.messages import ChatMessageAssistant, ChatMessageSystem, ChatMessageUser, PerformanceMetrics
from evalscope.api.model import GenerateConfig, Model, ModelOutput, ModelUsage, get_model
from evalscope.api.model.model_output import ChatCompletionChoice
from evalscope.api.registry import get_environment
from evalscope.utils.function_utils import AsyncioLoopRunner
from evalscope.utils.logger import get_logger
from .bridge import ModelProxyServer
from .bridge.server import DOCKER_ENV_NAMES
from .config import ExternalAgentConfig
from .runners import AgentRunResult, ExternalAgentTask, RunnerTimeoutError, get_runner

if TYPE_CHECKING:
    from evalscope.api.dataset import Sample

logger = get_logger()

#: Type alias for the optional post-run extraction hook. Receives the
#: still-open environment, the runner result, and the sample; returns the
#: prediction string used for ``InferenceResult.output``.
PostRunHook = Callable[[AgentEnvironment, AgentRunResult, 'Sample'], Awaitable[str]]


def run_external_agent(
    config: ExternalAgentConfig,
    model: Model,
    sample: 'Sample',
    *,
    environment_override: Optional[AgentEnvironment] = None,
    instruction_override: Optional[str] = None,
    post_run_hook: Optional[PostRunHook] = None,
) -> InferenceResult:
    """Synchronously drive one sample through an external agent runner.

    Returns an :class:`InferenceResult` whose ``output`` text is the
    agent's final stdout (or ``post_run_hook`` return value when set),
    ``messages`` is the bridge-reconstructed transcript, and ``trace``
    is the shared :class:`AgentTrace` (same shape as native AgentLoop
    runs, distinguished by ``framework``).

    Parameters
    ----------
    environment_override:
        Pre-built :class:`AgentEnvironment` from the caller. When set,
        ``config.environment`` / ``config.environment_extra`` are ignored
        — used by :class:`AgentLoopAdapter` benchmarks that need a
        per-sample sandbox (e.g. SWE-bench Pro's per-instance image).
    instruction_override:
        Replaces the default ``sample.input``-derived instruction. Used
        by adapters with a richer per-sample template (e.g. SWE-bench
        Pro's ``INSTANCE_TEMPLATE``).
    post_run_hook:
        Optional ``async (env, run_result, sample) -> str`` callback
        invoked inside the environment context, before close. Its return
        value replaces ``run_result.output`` as the InferenceResult text
        — the typical use is ``extract_patch(env, cwd)`` for SWE-bench
        adapters that recover a ``git diff`` from the working tree.

    Uses :class:`AsyncioLoopRunner` to submit the coroutine to the calling
    thread's long-lived background loop.  That loop is reused across
    samples so the :class:`ModelProxyServer` singleton (which binds to it)
    only spins up once per worker thread instead of once per sample.
    """
    instruction = instruction_override if instruction_override is not None else _instruction_from_sample(sample)
    return AsyncioLoopRunner.run(
        _run_async(
            config=config,
            model=model,
            sample=sample,
            instruction=instruction,
            environment_override=environment_override,
            post_run_hook=post_run_hook,
        )
    )


async def _run_async(
    config: ExternalAgentConfig,
    model: Model,
    sample: 'Sample',
    instruction: str,
    environment_override: Optional[AgentEnvironment],
    post_run_hook: Optional[PostRunHook],
) -> InferenceResult:
    runner_cls = get_runner(config.framework)
    runner_kwargs = dict(config.kwargs)
    runner_kwargs.setdefault('model_name', getattr(model, 'name', '') or '')
    runner = runner_cls(**runner_kwargs)

    if environment_override is not None:
        env: AgentEnvironment = environment_override
    else:
        env_cls = get_environment(config.environment)
        env = env_cls(**config.environment_extra)

    # Resolve env *before* starting the bridge so a dockerized env can
    # force the bind to 0.0.0.0 — otherwise the bridge would listen on
    # 127.0.0.1 inside the host and the agent inside the container would
    # see "connection refused" with no useful diagnostic.
    env_name = getattr(env, 'name', '') or ''
    is_docker_env = env_name in DOCKER_ENV_NAMES
    proxy_host = '0.0.0.0' if is_docker_env else config.bridge.proxy_host

    if is_docker_env and platform.system() == 'Linux':
        _maybe_inject_host_gateway(env)

    proxy = await ModelProxyServer.get_or_start(
        host=proxy_host,
        port=config.bridge.proxy_port,
    )

    model_routes = _build_bridge_model_routes(config)
    async with proxy.trial_session(
        model=model,
        framework=config.framework,
        model_routes=model_routes,
        strict_model_routing=config.bridge.strict_model_routing,
    ) as session:
        task = ExternalAgentTask(
            instruction=instruction,
            timeout=config.timeout,
            metadata={'sample_id': getattr(sample, 'id', None)},
        )
        async with env:
            session.recorder.record_run_start(
                framework=config.framework,
                cmd_summary=runner_cls.__name__,
            )
            run_started = time.monotonic()
            run_error: Optional[str] = None
            run_returncode = -1
            run_timed_out = False
            run_wall_time = 0.0
            run_metrics: Dict[str, Any] = {}
            try:
                await runner.setup(env)
                result = await runner.run(
                    task=task,
                    env=env,
                    bridge=session.endpoint_view(for_env=env),
                )
                run_returncode = int(result.metrics.get('returncode', 0))
                run_metrics = dict(result.metrics)
            except RunnerTimeoutError as exc:
                run_error = repr(exc)
                run_timed_out = True
                raise
            except Exception as exc:
                run_error = repr(exc)
                raise
            finally:
                run_wall_time = time.monotonic() - run_started
                session.recorder.record_run_end(
                    returncode=run_returncode,
                    timed_out=run_timed_out,
                    wall_time=run_wall_time,
                    error=run_error,
                    metrics=run_metrics,
                )

            # Run the post-run hook inside the env context so adapters can
            # still query the sandbox (e.g. extract a ``git diff``) before
            # the per-sample environment is closed.
            if post_run_hook is not None:
                final_text = await post_run_hook(env, result, sample)
            else:
                final_text = result.output

        trace: AgentTrace = session.recorder.snapshot()
        # Prefer the env's own ``name`` (set on the AgentEnvironment subclass)
        # over ``config.environment`` so AgentLoopAdapter-driven runs
        # (where the env comes from ``build_environment(sample)`` and
        # ``config.environment`` is ``None``) still record a meaningful
        # source on the trace.
        trace.environment = getattr(env, 'name', None) or config.environment
        messages = session.recorder.messages()

        # For external agents without a post_run_hook, prefer the last
        # assistant message captured by the bridge (clean model text) over
        # the raw runner stdout which may contain protocol-level noise
        # (e.g. opencode's JSON stream events).  The bridge intercepts
        # every LLM response through the proxy, so ``messages`` always
        # holds the authoritative transcript.
        if post_run_hook is None and messages:
            for msg in reversed(messages):
                if isinstance(msg, ChatMessageAssistant) and msg.text:
                    final_text = msg.text
                    break

    output = _to_model_output(
        final_text,
        model_name=getattr(model, 'name', '') or '',
        usage=trace.total_usage,
        latency=run_wall_time,
        runner_metrics=run_metrics,
    )
    return InferenceResult(output=output, messages=messages, trace=trace)


def _build_bridge_model_routes(config: ExternalAgentConfig) -> Dict[str, Model]:
    """Instantiate exact request-model routes declared on ``BridgeConfig``."""
    routes: Dict[str, Model] = {}
    for request_model, route in config.bridge.model_routes.items():
        api_key = None
        if route.api_key_env:
            api_key = os.getenv(route.api_key_env)
            if not api_key:
                raise ValueError(
                    f'bridge model route {request_model!r} requires environment variable '
                    f'{route.api_key_env!r}'
                )
        routes[request_model] = get_model(
            model=route.model_id,
            eval_type=route.eval_type,
            base_url=route.api_url,
            api_key=api_key,
            config=GenerateConfig(**route.generation_config),
            model_args=route.model_args,
        )
    if not routes and not config.bridge.strict_model_routing:
        return {}
    if config.bridge.strict_model_routing and not routes:
        raise ValueError('strict_model_routing requires at least one bridge.model_routes entry')
    return routes


def _maybe_inject_host_gateway(env: AgentEnvironment) -> None:
    """On Linux, register ``host.docker.internal:host-gateway`` as an
    extra host entry so the agent inside the container can resolve back
    to the bridge running on the host (Docker Desktop on macOS / Windows
    provides the alias natively).
    """
    merge = getattr(env, 'merge_sandbox_config', None)
    if not callable(merge):
        # Custom env without the overlay hook — can't know whether the
        # underlying engine supports extra_hosts at all.
        logger.debug(f'_maybe_inject_host_gateway: env {type(env).__name__} has no merge_sandbox_config hook')
        return
    try:
        merge({'extra_hosts': {'host.docker.internal': 'host-gateway'}})
    except RuntimeError as exc:
        # Sandbox already started — caller ordering bug, warn loudly.
        logger.warning(f'_maybe_inject_host_gateway: sandbox already running, host-gateway not injected ({exc})')


def _instruction_from_sample(sample: 'Sample') -> str:
    """Render the sample input as a single instruction string."""
    inp = sample.input
    if isinstance(inp, str):
        return inp
    parts = []
    for msg in inp or []:
        if isinstance(msg, (ChatMessageSystem, ChatMessageUser)):
            parts.append(msg.text)
        else:
            parts.append(getattr(msg, 'text', '') or '')
    return '\n\n'.join(p for p in parts if p)


def _to_model_output(
    text: str,
    *,
    model_name: str,
    usage: Optional[ModelUsage] = None,
    latency: float = 0.0,
    runner_metrics: Optional[Dict[str, Any]] = None,
) -> ModelOutput:
    """Wrap the agent answer and aggregate bridge usage in a ModelOutput."""
    choice = ChatCompletionChoice.from_content(text)
    meta: Dict[str, Any] = {'source': 'agent.external'}
    if runner_metrics:
        meta['runner_metrics'] = runner_metrics
    normalized_usage = None
    if usage is not None:
        total_tokens = int(usage.input_tokens or 0) + int(usage.output_tokens or 0)
        normalized_usage = usage.model_copy(update={'total_tokens': total_tokens})
        meta['task_usage'] = {
            'input_tokens': int(normalized_usage.input_tokens or 0),
            'output_tokens': int(normalized_usage.output_tokens or 0),
            'total_tokens': total_tokens,
        }
        choice.message.perf_metrics = PerformanceMetrics(
            latency=max(0.0, latency),
            input_tokens=int(normalized_usage.input_tokens or 0),
            output_tokens=int(normalized_usage.output_tokens or 0),
        )
    return ModelOutput(
        model=model_name,
        choices=[choice],
        usage=normalized_usage,
        time=max(0.0, latency),
        metadata=meta,
    )
