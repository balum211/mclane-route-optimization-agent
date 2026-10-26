---
name: adk-tool-builder
description: Use when adding or changing a Google ADK function tool or agent in route_optimizer (tools/, agent.py, prompts.py), including tools that need user confirmation.
---

# ADK tool builder

## Goal
Add a tool the model can use correctly the first time: clear docstring, simple typed arguments,
compact JSON-serializable output, and confirmation for side effects.

## Instructions
1. Put the function in the right module under `route_optimizer/tools/`. Use `_common.q()` for SQL
   (named `:params`, dates via `as_date`) and `get_repository().insert()` for writes.
2. Signature: only `str`, `int`, `float`, `bool` (with defaults) plus `tool_context: ToolContext` if
   you read or write session state (`tool_context.state["last_plan_id"]`). ADK hides `tool_context`
   from the model.
3. Docstring is the tool description: one-line summary, when to use it, `Args:` and `Returns:`.
   Write it for a dispatcher-facing model, not for developers.
4. Return a dict. Keep it small (cap lists at about 15 to 25 items), with times in HH:MM via
   `fmt_time` and money rounded to cents. Raise `ToolError` with an actionable message for bad input.
5. Side effects on TMW, customers or approvals: wrap with
   `FunctionTool(fn, require_confirmation=True)` and register the wrapped tool.
6. Register the tool on exactly one specialist in `agent.py` and mention it in that agent's prompt in
   `prompts.py`. Keep braces out of prompts, except ADK state placeholders like `{last_plan_id?}`.
7. Add a test in `tests/test_tools.py`. If delegation changes, extend `tests/test_agent_flow.py`.

## Examples
See `examples/example_tool.py` for a read-only tool and a confirmed write tool.

## Constraints
- No LLM calls inside tools. No network calls without a config flag and an offline fallback.
- Do not return raw DB rows with dozens of columns; select what the model needs.
