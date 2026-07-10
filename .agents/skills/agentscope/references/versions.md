# Agentscope - Versions

**Pages:** 15

---

## Agent - AgentScope

**URL:** https://docs.agentscope.io/versions/2.0.2/en/building-blocks/agent

**Contents:**
- On this page
- Agent
- ​Overview
  - ​Core Interfaces
  - ​Main Loop
- ​Configure Agent
  - ​Parameters
- ​Run the Agent
  - ​reply
  - ​reply_stream

Learn how to define and configure agents in AgentScope v2.0

Receive the RequireUserConfirmEvent

Show child attributes

Build the confirmation result

Receive the RequireExternalExecutionEvent

Show child attributes

Execute externally and build results

**Examples:**

Example 1 (sass):
```sass
from agentscope.agent import Agent
from agentscope.model import DashScopeChatModel
from agentscope.credential import DashScopeCredential

agent = Agent(
    name="my_agent",
    system_prompt="You are a helpful assistant.",
    model=DashScopeChatModel(
        credential=DashScopeCredential(api_key="YOUR_API_KEY"),
        model="qwen-max",
    ),
)
```

Example 2 (python):
```python
import asyncio
from agentscope.message import UserMsg

async def main():
    msg = UserMsg(name="user", content="What files are in the current directory?")
    result = await agent.reply(msg)
    print(result.get_text_content())

asyncio.run(main())
```

Example 3 (python):
```python
async def main():
    msg = UserMsg(name="user", content="Summarize the README.")
    async for event in agent.reply_stream(msg):
        if hasattr(event, "delta"):
            print(event.delta, end="", flush=True)

asyncio.run(main())
```

Example 4 (dart):
```dart
await agent.observe(other_agent_msg)
```

---

## Agent Service - AgentScope

**URL:** https://docs.agentscope.io/versions/2.0.2/en/deploy/agent-service

**Contents:**
- On this page
- Agent Service
  - ​Capabilities
- ​Quickstart
  - ​Try the bundled example
  - ​From your own code
  - ​create_app parameters
  - ​Typical operation flow
- ​Resource Model
- ​API Overview

Host your agent as a multi-tenant, multi-session HTTP service

Start the example backend

Start the example frontend

Create and configure a credential

Create a session and select a model

Configure MCPs and skills (optional)

**Examples:**

Example 1 (unknown):
```unknown
git clone https://github.com/agentscope-ai/agentscope.git
cd agentscope
```

Example 2 (unknown):
```unknown
cd examples/agent_service
python main.py
```

Example 3 (unknown):
```unknown
cd examples/web_ui
pnpm install
pnpm dev
```

Example 4 (sass):
```sass
import uvicorn
from agentscope.app import create_app
from agentscope.app.storage import RedisStorage
from agentscope.app.message_bus import RedisMessageBus
from agentscope.app.workspace_manager import LocalWorkspaceManager

# Persistence layer for agents, sessions, credentials, messages, and schedules.
# Its connection pool is opened on app startup and closed on shutdown.
storage = RedisStorage(host="localhost", port=6379)

# Redis-backed message bus: session locks, replay logs, inbox queues, and
# wakeup signals that decouple chat triggering from event delivery and
# let multiple worker processes share one logical service.
message_bus = RedisMessageBus(host="localhost", port=6379)

# Workspace lifecycle — working directory, MCP clients, skills.
# The built-in manager isolates per agent: sessions of the same agent
# share one workspace. Idle workspaces are evicted after `ttl` seconds.
workspace_manager = LocalWorkspaceManager(
    basedir="/data/workspaces",
    ttl=3600.0,
)

app = create_app(
    storage=storage,
    message_bus=message_bus,
    workspace_manager=workspace_manager,
)

uvicorn.run(app, host="0.0.0.0", port=8000)
```

---

## Agent Team - AgentScope

**URL:** https://docs.agentscope.io/versions/2.0.2/en/deploy/agent-team

**Contents:**
- On this page
- Agent Team
- ​Quickstart
- ​Concepts
- ​Usage
  - ​Creating a team
  - ​Custom sub-agent types
    - ​Registering templates
    - ​Template fields
    - ​System prompt placeholders

Leader agents that spawn and coordinate worker agents through built-in team tools

**Examples:**

Example 1 (sass):
```sass
from agentscope.app import create_app, SubAgentTemplate
from agentscope.permission import PermissionContext, PermissionMode

app = create_app(
    storage=storage,
    message_bus=message_bus,
    workspace_manager=workspace_manager,
    sub_agent_templates=[
        SubAgentTemplate(
            type="explorer",
            description=(
                "Read-only agents specialized in exploration tasks. "
                "Use this type when you need to investigate the "
                "codebase without making any changes."
            ),
            system_prompt_template="""You are {member_name}, an explorer \
agent in team '{team_name}' led by {leader_name}.

Team purpose: {team_description}

Your role: {member_description}

## Responsibilities
- Complete the exploration tasks assigned by the team leader.
- You are read-only: you may inspect files and the codebase, but \
you must never modify, create, or delete anything.

## Reporting
- Always report the task result back to {leader_name} using the \
TeamSay tool, whether the task succeeds or fails.""",
            permission_context=PermissionContext(
                mode=PermissionMode.EXPLORE,
            ),
        ),
    ],
)
```

---

## Context - AgentScope

**URL:** https://docs.agentscope.io/versions/2.0.2/en/building-blocks/context

**Contents:**
- On this page
- Context
- ​Overview
- ​Compact Context
  - ​Configure ContextConfig
  - ​Compress Context
  - ​Truncate Tool Results
- ​Offload Context
  - ​Use the Offloader Protocol
  - ​Use LocalWorkspace

Manage agent context window for stable, long-running execution

**Examples:**

Example 1 (lua):
```lua
from agentscope.agent import Agent
from agentscope.agent import ContextConfig

agent = Agent(
    name="my_agent",
    system_prompt="...",
    model=model,
    toolkit=toolkit,
    context_config=ContextConfig(
        trigger_ratio=0.8,
        reserve_ratio=0.1,
        tool_result_limit=3000,
    ),
)
```

Example 2 (sass):
```sass
# Force-check using the agent's default config
await agent.compress_context()

# Or override the config for this single call (e.g. compress more aggressively)
from agentscope.agent import ContextConfig

await agent.compress_context(
    context_config=ContextConfig(trigger_ratio=0.5, reserve_ratio=0.1),
)
```

Example 3 (typescript):
```typescript
<<<TRUNCATED>>>
<system-reminder>The remaining content has been omitted for limited context.</system-reminder>
```

Example 4 (typescript):
```typescript
<<<TRUNCATED>>>
<system-reminder>The remaining content has been omitted for limited context. You can refer to the file in '/path/to/tool_result-<id>.txt' for the truncated content if needed.</system-reminder>
```

---

## FAQ - AgentScope

**URL:** https://docs.agentscope.io/versions/2.0.2/zh/others/faq

**Contents:**
- FAQ

AgentScope 2.0 与 1.0 兼容吗？

AgentScope 是否支持沙箱化执行？

AgentScope 2.0 有配套的前端吗？

2.0 还会提供 RAG 和 long-term memory 吗？

---

## FAQ - AgentScope

**URL:** https://docs.agentscope.io/versions/2.0.2/en/others/faq

**Contents:**
- FAQ

Frequently asked questions about AgentScope v2.0

Is AgentScope 2.0 compatible with 1.0?

Does AgentScope support sandboxed execution?

Is there a frontend for AgentScope 2.0?

Will RAG and long-term memory return in 2.0?

Are there language bindings other than Python?

---

## Message & Event - AgentScope

**URL:** https://docs.agentscope.io/versions/2.0.2/en/building-blocks/message-and-event

**Contents:**
- On this page
- Message & Event
- ​Message
  - ​Structure
  - ​Content Blocks
  - ​Create Messages
  - ​Access Content
- ​Event
  - ​Event Lifecycle
  - ​Event Types

The core data abstractions for agent communication and streaming

Text Streaming Events

Thinking Streaming Events

Data Streaming Events

Tool Call Streaming Events

Tool Result Streaming Events

Human-in-the-Loop Events

**Examples:**

Example 1 (lua):
```lua
from agentscope.message import UserMsg, AssistantMsg, SystemMsg

# User message — text and optional images
user_msg = UserMsg(name="user", content="What's in this image?")

# User message with multimodal content
from agentscope.message import TextBlock, DataBlock, Base64Source
user_msg = UserMsg(
    name="user",
    content=[
        TextBlock(text="Describe this image:"),
        DataBlock(source=Base64Source(data="...", media_type="image/png")),
    ],
)

# System message — text only
system_msg = SystemMsg(name="system", content="You are a helpful assistant.")

# Assistant message — all block types allowed
assistant_msg = AssistantMsg(name="agent", content="Here is the result...")
```

Example 2 (lua):
```lua
# Get all text content
text = msg.get_text_content()

# Get all tool calls
tool_calls = msg.get_content_blocks("tool_call")

# Check if message has tool results
if msg.has_content_blocks("tool_result"):
    ...
```

Example 3 (sass):
```sass
from agentscope.message import Msg, AssistantMsg

msg = None

# Accumulate events into the message
async for event in agent.reply_stream(user_msg):
	if isinstance(event, ReplyStartEvent):
		# Create a new message when the reply starts
		msg = AssistantMsg(name=event.name, content=[], id=event.reply_id)

	else:
		# For all other events, append to the message to reconstruct its state
        msg.append_event(event)
```

Example 4 (elixir):
```elixir
pnpm install @agentscope-ai/agentscope
```

---

## Middleware - AgentScope

**URL:** https://docs.agentscope.io/versions/2.0.2/en/building-blocks/middleware

**Contents:**
- On this page
- Middleware
- ​Overview
- ​Equip Middleware
- ​Built-in Middleware
  - ​TracingMiddleware
    - ​Add Additional Spans
  - ​TTSMiddleware
- ​Custom Middleware
  - ​Execution Order

Intercept and extend agent behavior at key lifecycle points

**Examples:**

Example 1 (sass):
```sass
from agentscope.agent import Agent
from agentscope.middleware import TracingMiddleware

agent = Agent(
    name="assistant",
    system_prompt="You are a helpful assistant.",
    model=model,
    toolkit=toolkit,
    middlewares=[TracingMiddleware()],
)
```

Example 2 (python):
```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

provider = TracerProvider()
provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint="http://localhost:4318/v1/traces")),
)
trace.set_tracer_provider(provider)
```

Example 3 (sass):
```sass
from agentscope.agent import Agent
from agentscope.middleware import TracingMiddleware

agent = Agent(
    name="assistant",
    system_prompt="You are a helpful assistant.",
    model=model,
    toolkit=toolkit,
    middlewares=[TracingMiddleware()],
)
```

Example 4 (python):
```python
from opentelemetry import trace
from agentscope import __version__

tracer = trace.get_tracer("agentscope", __version__)

with tracer.start_as_current_span(
    name="your_span_name",
    attributes={
        # Optional key-value pairs attached to the span,
        # e.g. function name, input arguments, or any custom metadata.
    },
    end_on_exit=True,
) as span:
    # your code here
```

---

## Model - AgentScope

**URL:** https://docs.agentscope.io/versions/2.0.2/en/building-blocks/model

**Contents:**
- On this page
- Model
- ​Overview
- ​Chat Model
  - ​Create Chat Model
  - ​Call Chat Model
  - ​Generate Structured Output
  - ​Formatter
  - ​Custom Provider
    - ​Step 1: Define the Credential

Configure and connect LLM model providers in AgentScope

**Examples:**

Example 1 (sass):
```sass
import os
from agentscope.model import DashScopeChatModel
from agentscope.credential import DashScopeCredential

model = DashScopeChatModel(
    credential=DashScopeCredential(api_key=os.environ["DASHSCOPE_API_KEY"]),
    model="qwen-plus",
    stream=True,
)
```

Example 2 (python):
```python
async def __call__(
    self,
    messages: list[Msg],
    tools: list[dict] | None = None,
    tool_choice: ToolChoice | None = None,
    **kwargs: Any,
) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
```

Example 3 (python):
```python
import asyncio
import os
from agentscope.model import DashScopeChatModel
from agentscope.credential import DashScopeCredential
from agentscope.message import UserMsg

async def main():
    model = DashScopeChatModel(
        credential=DashScopeCredential(api_key=os.environ["DASHSCOPE_API_KEY"]),
        model="qwen-plus",
        stream=True,
    )
    msgs = [UserMsg(name="user", content="Count from 1 to 5.")]

    async for chunk in await model(msgs):
        if chunk.is_last:
            print("Final:", chunk.content)   # full accumulated content
        else:
            print("Delta:", chunk.content)   # delta only

asyncio.run(main())
```

Example 4 (yaml):
```yaml
Delta: [TextBlock(text='1')]
Delta: [TextBlock(text=', 2,')]
Delta: [TextBlock(text=' 3, ')]
Delta: [TextBlock(text='4, 5')]
Final: [TextBlock(text='1, 2, 3, 4, 5')]
```

---

## Permission System - AgentScope

**URL:** https://docs.agentscope.io/versions/2.0.2/en/building-blocks/permission-system

**Contents:**
- On this page
- Permission System
- ​Overview
- ​Permission Mode
- ​Permission Rules
  - ​Pattern Examples
  - ​Configuring Rules
- ​Built-in Checks
  - ​Custom tools
  - ​Safety check contract

Fine-grained control over which tools your agents can execute and when

Full read-only command list

**Examples:**

Example 1 (lua):
```lua
from agentscope.agent import Agent
from agentscope.state import AgentState
from agentscope.permission import PermissionContext, PermissionMode

agent = Agent(
    name="my_agent",
    system_prompt="...",
    model=model,
    state=AgentState(
        permission_context=PermissionContext(
            mode=PermissionMode.DEFAULT,
        )
    ),
)
```

Example 2 (sass):
```sass
PermissionRule(
    tool_name="Bash",
    rule_content="npm run:*",
    behavior=PermissionBehavior.ALLOW,
    source="userSettings",
)
```

Example 3 (sass):
```sass
PermissionRule(
    tool_name="Write",
    rule_content="src/**",
    behavior=PermissionBehavior.ALLOW,
    source="userSettings",
)
```

Example 4 (lua):
```lua
from agentscope.agent import Agent
from agentscope.state import AgentState
from agentscope.permission import (
    PermissionContext, PermissionMode, PermissionRule, PermissionBehavior
)

agent = Agent(
    name="my_agent",
    system_prompt="...",
    model=model,
    state=AgentState(
        permission_context=PermissionContext(
            mode=PermissionMode.DEFAULT,
            allow_rules={
                "Bash": [PermissionRule(tool_name="Bash", rule_content="npm run:*",
                                        behavior=PermissionBehavior.ALLOW, source="userSettings")],
                "Write": [PermissionRule(tool_name="Write", rule_content="src/**",
                                         behavior=PermissionBehavior.ALLOW, source="userSettings")],
            },
            deny_rules={
                "Bash": [PermissionRule(tool_name="Bash", rule_content="rm:*",
                                        behavior=PermissionBehavior.DENY, source="userSettings")],
            },
        )
    ),
)
```

---

## Tool - AgentScope

**URL:** https://docs.agentscope.io/versions/2.0.2/en/building-blocks/tool

**Contents:**
- On this page
- Tool
- ​Overview
- ​Python Tool
  - ​ToolBase Interface
  - ​Use Built-in Tools
    - ​Bash
    - ​File Tools (Read, Write, Edit)
  - ​Create Custom Tool
  - ​Wrap Function as Tool

Define, register, and manage the capabilities an agent can call

**Examples:**

Example 1 (sql):
```sql
from agentscope.tool import Toolkit, Bash, Read, Write, Edit

toolkit = Toolkit(
    tools=[Bash(), Read(), Write(), Edit()],
)
```

Example 2 (sql):
```sql
from agentscope.tool import Bash

bash = Bash(
    additional_dangerous_files=[".secrets"],
    additional_dangerous_directories=[".credentials"],
)
```

Example 3 (python):
```python
from agentscope.tool import ToolBase, ToolChunk
from agentscope.permission import (
    PermissionContext, PermissionDecision, PermissionBehavior,
)
from agentscope.message import TextBlock

class WebSearch(ToolBase):
    name = "WebSearch"
    description = "Search the web for information on a given query."
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
        },
        "required": ["query"],
    }
    is_concurrency_safe = True
    is_read_only = True

    async def check_permissions(
        self, tool_input: dict, context: PermissionContext,
    ) -> PermissionDecision:
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="Web search is read-only.",
        )

    async def __call__(self, query: str) -> ToolChunk:
        results = await do_search(query)
        return ToolChunk(content=[TextBlock(text=results)])
```

Example 4 (python):
```python
from agentscope.tool import FunctionTool, Toolkit

def get_weather(city: str, unit: str = "celsius") -> str:
    """Get the current weather for a city.

    Args:
        city: The city name to look up.
        unit: Temperature unit, either "celsius" or "fahrenheit".
    """
    return f"The weather in {city} is 22°{unit[0].upper()}"

toolkit = Toolkit(tools=[FunctionTool(get_weather)])
```

---

## What's AgentScope 2.0? - AgentScope

**URL:** https://docs.agentscope.io/versions/2.0.2

**Contents:**
- What's AgentScope 2.0?
- Event System
- Execution Security
- Human-in-the-loop
- Efficient Agent
- Workspace System
- Agent Service

More secure, more efficient, more flexible, and more complete agent development.

---

## What's AgentScope 2.0? - AgentScope

**URL:** https://docs.agentscope.io/versions/2.0.2/en

**Contents:**
- What's AgentScope 2.0?
- Event System
- Execution Security
- Human-in-the-loop
- Efficient Agent
- Workspace System
- Agent Service

More secure, more efficient, more flexible, and more complete agent development.

---

## Workspace - AgentScope

**URL:** https://docs.agentscope.io/versions/2.0.2/en/building-blocks/workspace

**Contents:**
- On this page
- Workspace
- ​Overview
- ​Use a Workspace
  - ​Create a Workspace
  - ​Integrate with Agent
- ​Workspace Manager
- ​MCP Gateway
- ​Further Reading
- Agent

The execution environment that supplies tools, skills, and context offloading

**Examples:**

Example 1 (json):
```json
{workdir}/
├── .mcp           # registered MCP client configs (JSON array)
├── data/          # offloaded multimodal payloads (deduped by SHA-256)
├── skills/        # skill subdirectories, each with SKILL.md
│   └── .skills    # name/hash index for de-duplication
└── sessions/      # per-session context.jsonl and tool-result files
```

Example 2 (swift):
```swift
from agentscope.workspace import LocalWorkspace

workspace = LocalWorkspace(
    workdir="/data/my-workspace",
    default_mcps=[],
    skill_paths=["./skills/web-search"],
)
await workspace.initialize()
```

Example 3 (json):
```json
{workdir}/         # host directory, bind-mounted to /workspace in container
├── .mcp           # registered MCP client configs (JSON array)
├── data/          # offloaded multimodal payloads
├── skills/        # skill subdirectories, each with SKILL.md
└── sessions/      # per-session context.jsonl and tool-result files
```

Example 4 (swift):
```swift
from agentscope.workspace import DockerWorkspace

workspace = DockerWorkspace(
    base_image="python:3.11-slim",
    workdir="/data/docker-workspaces/agent-1",  # bind-mounted to /workspace
    node_version="20",
    extra_pip=["numpy", "pandas"],
    default_mcps=[],
    skill_paths=["./skills/web-search"],
)
await workspace.initialize()
```

---

## 智能体 - AgentScope

**URL:** https://docs.agentscope.io/versions/2.0.2/zh/building-blocks/agent

**Contents:**
- 在此页面
- 智能体
- ​概述
  - ​核心接口
  - ​主循环
- ​配置智能体
  - ​参数说明
- ​运行智能体
  - ​reply
  - ​reply_stream

了解如何在 AgentScope v2.0 中定义和配置智能体

接收 RequireUserConfirmEvent

接收 RequireExternalExecutionEvent

**Examples:**

Example 1 (sass):
```sass
from agentscope.agent import Agent
from agentscope.model import DashScopeChatModel
from agentscope.credential import DashScopeCredential

agent = Agent(
    name="my_agent",
    system_prompt="你是一个有帮助的助手。",
    model=DashScopeChatModel(
        credential=DashScopeCredential(api_key="YOUR_API_KEY"),
        model="qwen-max",
    ),
)
```

Example 2 (python):
```python
import asyncio
from agentscope.message import UserMsg

async def main():
    msg = UserMsg(name="user", content="当前目录有哪些文件？")
    result = await agent.reply(msg)
    print(result.get_text_content())

asyncio.run(main())
```

Example 3 (python):
```python
async def main():
    msg = UserMsg(name="user", content="总结一下 README 的内容。")
    async for event in agent.reply_stream(msg):
        if hasattr(event, "delta"):
            print(event.delta, end="", flush=True)

asyncio.run(main())
```

Example 4 (dart):
```dart
await agent.observe(other_agent_msg)
```

---
