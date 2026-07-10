"""Minimal AgentScope service entrypoint for the AliyunCS provider."""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from typing import Any, Literal

from agentscope.agent import Agent
from agentscope.app import create_app
from agentscope.app.message_bus import RedisMessageBus
from agentscope.app.storage import RedisStorage
from agentscope.app.workspace_manager import LocalWorkspaceManager
from agentscope.message import UserMsg
from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from aliyuncs import create_chat_model, register_provider


class ChatRequest(BaseModel):
    """Request body for the minimal AliyunCS chat example."""

    message: str = Field(..., min_length=1)


class ChatResponse(BaseModel):
    """Response body for the minimal AliyunCS chat example."""

    reply: str


class OpenAIMessage(BaseModel):
    """Minimal OpenAI-compatible chat message."""

    role: str
    content: str | list[dict[str, Any]] | None = None


class ChatCompletionRequest(BaseModel):
    """Subset of the OpenAI chat completions request used by EvalScope."""

    model: str = Field(default="agentscope-aliyuncs-demo")
    messages: list[OpenAIMessage] = Field(..., min_length=1)
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False


class ChatCompletionChoice(BaseModel):
    """OpenAI-compatible chat completion choice."""

    index: int = 0
    message: OpenAIMessage
    finish_reason: Literal["stop"] = "stop"


class ChatCompletionResponse(BaseModel):
    """Minimal OpenAI-compatible chat completions response."""

    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: dict[str, int]


def build_demo_agent() -> Agent:
    """Create a tiny AgentScope agent backed by the AliyunCS provider."""

    register_provider()
    return Agent(
        name="aliyuncs_demo",
        system_prompt="You are a concise and helpful assistant.",
        model=create_chat_model(stream=False),
    )


def _message_content_to_text(content: str | list[dict[str, Any]] | None) -> str:
    """Convert a minimal OpenAI message content payload to plain text."""

    if content is None:
        return ""
    if isinstance(content, str):
        return content

    parts: list[str] = []
    for item in content:
        if item.get("type") == "text" and isinstance(item.get("text"), str):
            parts.append(item["text"])
        elif isinstance(item.get("content"), str):
            parts.append(item["content"])
    return "\n".join(parts)


def _messages_to_prompt(messages: list[OpenAIMessage]) -> str:
    """Flatten OpenAI-style messages into one AgentScope user prompt."""

    lines: list[str] = []
    for message in messages:
        text = _message_content_to_text(message.content).strip()
        if not text:
            continue
        if message.role == "user":
            lines.append(text)
        elif message.role == "system":
            lines.append(f"System instruction:\n{text}")
        else:
            lines.append(f"{message.role}:\n{text}")
    return "\n\n".join(lines).strip()


def _estimate_tokens(text: str) -> int:
    """Cheap usage estimate for OpenAI-compatible clients."""

    return max(1, len(text.split())) if text else 0


def build_app():
    """Create the FastAPI app and register the AliyunCS credential."""
    register_provider()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    return create_app(
        storage=RedisStorage(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            password=os.getenv("REDIS_PASSWORD") or None,
        ),
        message_bus=RedisMessageBus(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            password=os.getenv("REDIS_PASSWORD") or None,
        ),
        workspace_manager=LocalWorkspaceManager(
            basedir=os.path.join(base_dir, "workspaces"),
        ),
        extra_middlewares=[
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["*"],
                allow_headers=["*"],
            ),
        ],
    )


async def run_chat_loop() -> None:
    """Run a minimal terminal chat loop against the AliyunCS provider."""

    agent = build_demo_agent()
    print("AliyunCS chat loop. Type 'exit' or 'quit' to stop.")

    while True:
        message = input("You> ").strip()
        if message.lower() in {"exit", "quit"}:
            break
        if not message:
            continue

        result = await agent.reply(UserMsg(name="user", content=message))
        print(f"Assistant> {result.get_text_content()}\n")


async def run_agent_once() -> None:
    """Run the AgentScope agent once with stdin as the instruction."""

    instruction = sys.stdin.read().strip()
    if not instruction:
        raise SystemExit("No instruction was provided on stdin.")
    agent = build_demo_agent()
    result = await agent.reply(UserMsg(name="user", content=instruction))
    print(result.get_text_content())


if __name__ == "__main__" and "--chat" in sys.argv:
    asyncio.run(run_chat_loop())
    raise SystemExit(0)


if __name__ == "__main__" and "--agent-once" in sys.argv:
    asyncio.run(run_agent_once())
    raise SystemExit(0)


app = build_app()


@app.post("/examples/chat", response_model=ChatResponse)
async def chat_once(request: ChatRequest) -> ChatResponse:
    """Minimal one-shot chat endpoint using the AliyunCS provider."""

    agent = build_demo_agent()
    result = await agent.reply(UserMsg(name="user", content=request.message))
    return ChatResponse(reply=result.get_text_content())


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check for EvalScope and local smoke tests."""

    return {"status": "ok"}


@app.get("/v1/models")
async def list_models() -> dict[str, Any]:
    """Minimal OpenAI-compatible models endpoint."""

    return {
        "object": "list",
        "data": [
            {
                "id": "agentscope-aliyuncs-demo",
                "object": "model",
                "created": 0,
                "owned_by": "local",
            }
        ],
    }


@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(request: ChatCompletionRequest) -> ChatCompletionResponse:
    """OpenAI-compatible endpoint that routes EvalScope prompts to the AgentScope agent."""

    if request.stream:
        raise ValueError("Streaming responses are not implemented for this local AgentScope bridge.")

    prompt = _messages_to_prompt(request.messages)
    agent = build_demo_agent()
    result = await agent.reply(UserMsg(name="user", content=prompt))
    reply = result.get_text_content()

    prompt_tokens = _estimate_tokens(prompt)
    completion_tokens = _estimate_tokens(reply)
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex}",
        created=int(time.time()),
        model=request.model,
        choices=[
            ChatCompletionChoice(
                message=OpenAIMessage(role="assistant", content=reply),
            )
        ],
        usage={
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("RELOAD", "1") == "1",
    )