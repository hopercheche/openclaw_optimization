# Planner Profile Model Report

- Model path: `data/planner_models/profile_policy_model_safe_distill_v2_dev_20260708.json`
- Examples: 1000 (800 dev, 200 holdout)
- Profile hints stripped during training/eval: True
- Balanced class prior: True
- Terminal template repeats: 0

## Holdout Accuracy

- Planner profile: 98.00%
- Execution tools: 90.50%
- Policy mode: 72.50%

## Dev Accuracy

- Planner profile: 99.25%
- Execution tools: 96.37%
- Policy mode: 89.38%

## Training Distribution

- Sources: `{"phoneharness": 144, "phoneharness_synthetic": 250, "skillsbench": 11, "tau2": 184, "terminalworld_safe_network": 311, "toolbench": 100}`
- Profiles: `{"api_planning": 100, "mobile_or_mcp_workflow": 394, "policy_tool_agent": 184, "skill_workflow": 11, "terminal_cli_workflow": 311}`
- Policies: `{"act": 740, "confirm": 197, "refuse": 63}`
- Tools: `{"command_runner": 322, "file_writer": 11, "mcp_tool_runner": 396, "mobile_cli_runner": 170, "mobile_gui_runner": 206}`

## Method

The model is a standard-library multinomial Naive Bayes classifier trained on local multi-source planner fixtures. It learns three supervised labels from the datasets: planner profile, execution-tool set, and policy mode. OpenClaw uses the model only as a conservative hint when explicit `execution_tool(s)=...` metadata is absent.
