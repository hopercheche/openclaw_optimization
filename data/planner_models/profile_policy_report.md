# Planner Profile Model Report

- Model path: `/home/litangchao/OpenClawPOpti/data/planner_models/profile_policy_model.json`
- Examples: 325 (244 dev, 81 holdout)
- Profile hints stripped during training/eval: True

## Holdout Accuracy

- Planner profile: 100.00%
- Execution tools: 95.06%
- Policy mode: 64.20%

## Dev Accuracy

- Planner profile: 100.00%
- Execution tools: 98.77%
- Policy mode: 84.02%

## Training Distribution

- Sources: `{"phoneharness": 30, "skillsbench": 11, "tau2": 184, "toolbench": 100}`
- Profiles: `{"api_planning": 100, "mobile_or_mcp_workflow": 30, "policy_tool_agent": 184, "skill_workflow": 11}`
- Policies: `{"act": 255, "confirm": 63, "refuse": 7}`
- Tools: `{"command_runner": 11, "file_writer": 11, "mcp_tool_runner": 296, "mobile_cli_runner": 15, "mobile_gui_runner": 23}`

## Method

The model is a standard-library multinomial Naive Bayes classifier trained on local multi-source planner fixtures. It learns three supervised labels from the datasets: planner profile, execution-tool set, and policy mode. OpenClaw uses the model only as a conservative hint when explicit `execution_tool(s)=...` metadata is absent.
