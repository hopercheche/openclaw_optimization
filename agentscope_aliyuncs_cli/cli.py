"""A tiny third-party Agent CLI backed by AgentScope and AliyunCS.

When launched by ``AgentScopeAliyunCSCliRunner`` this CLI talks to the
EvalScope bridge through the OpenAI Responses endpoint. When run directly, it
can also talk to AliyunCS using the OpenAI-compatible chat endpoint.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Literal

from agentscope.agent import Agent
from agentscope.message import UserMsg
from agentscope.model import OpenAIResponseModel

from aliyuncs import ALIYUNCS_BASE_URL, create_chat_model, create_credential, get_model_name, register_provider

from .constants import (
    API_KEY_ENV,
    BASE_URL_ENV,
    DEFAULT_SYSTEM_PROMPT,
    LOAD_DOTENV_ENV,
    MODEL_ENV,
    PROTOCOL_ENV,
    SYSTEM_PROMPT_ENV,
)

Protocol = Literal["chat", "responses"]


def load_dotenv_file(path: str | Path = ".env") -> None:
    """Load simple KEY=VALUE pairs from a local .env file if present."""

    if os.getenv(LOAD_DOTENV_ENV, "1").lower() in {"0", "false", "no"}:
        return

    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def build_agent(
    *,
    protocol: Protocol,
    base_url: str,
    api_key: str | None,
    model_name: str,
    system_prompt: str,
) -> Agent:
    """Create one AgentScope agent for a single CLI invocation."""

    register_provider()
    credential = create_credential(api_key=api_key, base_url=base_url)
    if protocol == "responses":
        model = OpenAIResponseModel(
            credential=credential,
            model=model_name,
            stream=False,
        )
    else:
        model = create_chat_model(
            credential=credential,
            model=model_name,
            stream=False,
        )

    return Agent(
        name="agentscope_aliyuncs_cli",
        system_prompt=system_prompt,
        model=model,
    )


async def reply_once(args: argparse.Namespace) -> str:
    prompt = args.prompt_option or args.prompt or sys.stdin.read()
    prompt = prompt.strip()
    if not prompt:
        raise SystemExit("No prompt provided. Pass --prompt, a positional prompt, or stdin.")

    agent = build_agent(
        protocol=args.protocol,
        base_url=args.base_url,
        api_key=args.api_key,
        model_name=args.model,
        system_prompt=args.system_prompt,
    )
    result = await agent.reply(UserMsg(name="user", content=prompt))
    return result.get_text_content()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    load_dotenv_file()

    parser = argparse.ArgumentParser(description="Run one AgentScope AliyunCS reply.")
    parser.add_argument("prompt", nargs="?", help="Prompt text. stdin is used when omitted.")
    parser.add_argument("--prompt", dest="prompt_option", help="Prompt text.")
    parser.add_argument(
        "--protocol",
        choices=("chat", "responses"),
        default=os.getenv(PROTOCOL_ENV, "chat"),
        help="Wire protocol for the model endpoint.",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv(BASE_URL_ENV, ALIYUNCS_BASE_URL),
        help="OpenAI-compatible base URL.",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv(API_KEY_ENV),
        help="API key. Prefer environment variables for normal use.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv(MODEL_ENV, get_model_name()),
        help="Model name forwarded to the endpoint.",
    )
    parser.add_argument(
        "--system-prompt",
        default=os.getenv(SYSTEM_PROMPT_ENV, DEFAULT_SYSTEM_PROMPT),
        help="System prompt for the AgentScope agent.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    reply = asyncio.run(reply_once(parse_args(argv)))
    print(reply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
