# AgentScope AliyunCS CLI for EvalScope

This folder is a minimal third-party Agent CLI example for EvalScope's
external-agent bridge.

What it adds:

- `cli.py`: a one-shot AgentScope CLI that uses the existing `aliyuncs/`
  provider code.
- `runner.py`: an EvalScope `AgentRunner` registered as
  `agentscope-aliyuncs-cli`.
- `run_evalscope.py`: a small EvalScope task that imports the runner before
  creating `ExternalAgentConfig`.

The EvalScope path uses the OpenAI Responses protocol between this CLI and the
EvalScope bridge. The upstream model call still uses the existing AliyunCS
OpenAI-compatible endpoint from `aliyuncs/credential.py`.

Run from the repository root:

```powershell
.\agentscope_aliyuncs_cli\run_evalscope.ps1
```

or:

```bash
bash agentscope_aliyuncs_cli/run_evalscope.sh
```

The runner reads `ALIYUNCS_API_KEY` from `.env` or the process environment.
