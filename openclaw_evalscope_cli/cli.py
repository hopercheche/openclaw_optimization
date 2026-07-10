"""Local debug wrapper for ``openclaw agent --json``."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from .constants import DEFAULT_AGENT_ID, DEFAULT_SESSION_KEY_PREFIX
from .output import parse_openclaw_stdout


def _prompt_from_args(args: argparse.Namespace) -> str:
    prompt = args.prompt_option or args.prompt or sys.stdin.read()
    prompt = prompt.strip()
    if not prompt:
        raise SystemExit("No prompt provided. Pass --prompt, a positional prompt, or stdin.")
    return prompt


def _build_agent_command(args: argparse.Namespace, prompt_file: Path) -> list[str]:
    cmd = [
        args.openclaw_bin,
        "agent",
        "--agent",
        args.agent,
        "--session-key",
        args.session_key,
        "--message-file",
        str(prompt_file),
        "--json",
        "--timeout",
        str(args.agent_timeout),
    ]
    if args.model:
        cmd.extend(["--model", args.model])
    cmd.extend(args.extra_arg or [])
    return cmd


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one OpenClaw CLI harness turn.")
    parser.add_argument("prompt", nargs="?", help="Prompt text. stdin is used when omitted.")
    parser.add_argument("--prompt", dest="prompt_option", help="Prompt text.")
    parser.add_argument("--openclaw-bin", default="openclaw", help="OpenClaw executable.")
    parser.add_argument("--agent", default=DEFAULT_AGENT_ID, help="OpenClaw agent id.")
    parser.add_argument("--model", default="", help="Optional provider/model override.")
    parser.add_argument(
        "--session-key",
        default=f"agent:{DEFAULT_AGENT_ID}:{DEFAULT_SESSION_KEY_PREFIX}-cli",
        help="OpenClaw session key.",
    )
    parser.add_argument("--agent-timeout", type=int, default=600, help="OpenClaw timeout in seconds.")
    parser.add_argument("--exec-timeout", type=float, default=660.0, help="Subprocess timeout in seconds.")
    parser.add_argument(
        "--extra-arg",
        action="append",
        default=[],
        help="Extra argument appended to `openclaw agent`.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    prompt = _prompt_from_args(args)

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        prompt_path = Path(handle.name)
        handle.write(prompt)

    try:
        result = subprocess.run(
            _build_agent_command(args, prompt_path),
            text=True,
            capture_output=True,
            timeout=args.exec_timeout,
            check=False,
        )
    finally:
        prompt_path.unlink(missing_ok=True)

    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise SystemExit(f"OpenClaw CLI exited with code {result.returncode}: {stderr[-2000:]}")

    _, text = parse_openclaw_stdout(result.stdout)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
