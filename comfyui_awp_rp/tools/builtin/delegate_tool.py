"""Delegate tool — allows the main agent to spawn a sub-agent for a sub-task.

This implements the "派发子 Agent" pattern: the main agent, during its
agent loop, can call this tool to delegate a sub-task to a specialized
sub-agent profile. The sub-agent runs its own mini agent loop, completes,
and the result is fed back to the main agent.

This bypasses ComfyUI's static DAG model by doing the delegation inside
a single node's execution, not via workflow connections.
"""

from __future__ import annotations

import json
from typing import Any

from ...core.llm_router import create_default_router
from ...profile.profile import ProfileManager
from ...core.types import LlmToolCall
from ..registry import ToolDefinition, ToolRegistry, get_global_registry
from ..skill_manager import SkillManager
from ..tool_executor import ToolExecutor


def _run_sub_agent(
    profile_id: str,
    task: str,
    context: str = "",
    data: str = "",
    tool_ids: list[str] | None = None,
    skill_ids: list[str] | None = None,
    max_iterations: int = 3,
    provider: str = "deepseek",
    model: str = "",
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Run a sub-agent with its own mini agent loop.

    Args:
        profile_id: The sub-agent profile (e.g. 'rp-critic', 'novel-reviewer').
        task: The task description for the sub-agent.
        context: Optional context string.
        data: Optional data string.
        tool_ids: Optional list of tool IDs the sub-agent may use.
        skill_ids: Optional list of skill IDs to inject.
        max_iterations: Max agent loop iterations for the sub-agent.
        provider: LLM provider.
        model: LLM model (empty = use profile default).
        temperature: LLM temperature.
        max_tokens: LLM max tokens.

    Returns:
        The sub-agent's final text output.
    """
    profile_manager = ProfileManager()
    agent_profile = profile_manager.get_profile(profile_id)
    if not agent_profile:
        return f"Error: profile '{profile_id}' not found"

    # Build system prompt with skills
    skill_manager = SkillManager()
    skills_content = ""
    if skill_ids:
        skills_content = skill_manager.resolve_skills_content(skill_ids, "zh")

    system_prompt = agent_profile.foundational_system_prompt
    if skills_content:
        system_prompt = system_prompt + "\n\n" + skills_content

    # Build the initial messages
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]
    if context:
        messages.append({"role": "user", "content": f"## Context\n{context}"})
    if data:
        messages.append({"role": "user", "content": f"## Data\n{data}"})
    messages.append({"role": "user", "content": f"## Task\n{task}"})

    # Resolve tools
    registry = ToolRegistry()
    # Copy from global registry to avoid mutation
    global_reg = get_global_registry()
    for tool in global_reg.list_tools():
        if not tool_ids or tool.name in tool_ids:
            registry.register(tool)

    tools = registry.to_llm_definitions() if registry.list_tools() else None
    executor = ToolExecutor(registry)

    router = create_default_router()
    defaults = agent_profile.default_model_config
    node_config = {
        "provider": provider,
        "model": model or "",
        "temperature": temperature if temperature is not None else defaults.temperature,
        "max_tokens": max_tokens if max_tokens is not None else defaults.max_tokens,
    }
    if defaults.top_p is not None:
        node_config["top_p"] = defaults.top_p
    if defaults.timeout_ms is not None:
        node_config["timeout_ms"] = defaults.timeout_ms
    if defaults.response_format:
        node_config["response_format"] = defaults.response_format

    iterations = 0
    while iterations < max_iterations:
        iterations += 1
        try:
            result, resolved_provider, resolved_model = router.complete_with_tools(
                node_config=node_config,
                messages=messages,
                tools=tools,
                tool_choice="auto" if tools else None,
            )
        except Exception as exc:
            return f"Sub-agent LLM error: {exc}"

        # Append assistant message to conversation
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": result.text}
        if result.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in result.tool_calls
            ]
        messages.append(assistant_msg)

        if not result.has_tool_calls:
            # Sub-agent is done
            final_output = result.text
            # --- P5.5: Sub-agent result validation ---
            validation_notes = _validate_sub_agent_result(profile_id, final_output)
            if validation_notes:
                final_output = final_output + "\n\n[Validation: " + validation_notes + "]"
            return final_output

        # Execute tool calls and append results
        tool_results = executor.execute_calls(result.tool_calls)
        messages.extend(tool_results)

    return result.text if 'result' in dir() else "Sub-agent reached max iterations without completing."


def _validate_sub_agent_result(profile_id: str, output: str) -> str:
    """Validate sub-agent output against expected format for the profile type.

    Returns error notes string if validation fails, empty string if OK.
    """
    issues: list[str] = []

    if profile_id in ("novel-reviewer", "rp-critic"):
        # Check for required JSON structure
        try:
            import json as _json
            data = _json.loads(output) if output.strip().startswith("{") else {}
        except Exception:
            data = {}
            issues.append("reviewer output is not valid JSON")
        if isinstance(data, dict):
            if "dimension_results" not in data and "issues" not in data:
                issues.append("reviewer missing dimension_results or issues")

    elif profile_id in ("novel-data-agent", "rp-memory-curator"):
        # Check for required extraction fields
        if "event" not in output.lower() and "relationship" not in output.lower():
            issues.append("data-agent output missing event/relationship keywords")

    elif profile_id in ("novel-context-agent",):
        # Check for 5-section task book
        sections = ["开篇委托", "这章的故事", "这章的人物", "怎么写更顺", "收在哪里"]
        found = sum(1 for s in sections if s in output)
        if found < 3:
            issues.append(f"context-agent task book missing sections ({found}/5 found)")

    return "; ".join(issues) if issues else ""


def _delegate_to_sub_agent(args: dict[str, Any]) -> str:
    """Tool function: delegate a sub-task to a sub-agent."""
    profile = args.get("profile", "rp-critic")
    task = args.get("task", "")
    context = args.get("context", "")
    data = args.get("data", "")
    tool_ids = args.get("tool_ids", [])
    skill_ids = args.get("skill_ids", [])
    max_iterations = args.get("max_iterations", 3)

    if not task:
        return "Error: task is required for delegation"

    return _run_sub_agent(
        profile_id=profile,
        task=task,
        context=context,
        data=data,
        tool_ids=tool_ids if tool_ids else None,
        skill_ids=skill_ids if skill_ids else None,
        max_iterations=max_iterations,
    )


def register_delegate_tool(registry: ToolRegistry) -> None:
    """Register the delegate-to-sub-agent tool."""
    # Get available profiles for description
    pm = ProfileManager()
    profiles = [p["id"] for p in pm.list_profiles()]
    profile_list = ", ".join(profiles[:10])

    registry.register(ToolDefinition(
        name="delegate_to_sub_agent",
        description=(
            f"Delegate a sub-task to a specialized sub-agent. The sub-agent runs its own "
            f"reasoning loop and returns the result. Available profiles: {profile_list}. "
            f"Use this when you need specialized help (e.g. review, context research, "
            f"fact extraction, deconstruction, deslop)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "profile": {
                    "type": "string",
                    "description": f"The sub-agent profile ID. Available: {profile_list}",
                },
                "task": {
                    "type": "string",
                    "description": "The task description for the sub-agent.",
                },
                "context": {
                    "type": "string",
                    "description": "Optional context to pass to the sub-agent.",
                },
                "data": {
                    "type": "string",
                    "description": "Optional data to pass to the sub-agent.",
                },
                "tool_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of tool IDs the sub-agent may use.",
                },
                "skill_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of skill IDs to inject into the sub-agent.",
                },
                "max_iterations": {
                    "type": "integer",
                    "description": "Max iterations for the sub-agent loop.",
                    "default": 3,
                },
            },
            "required": ["profile", "task"],
        },
        execute_fn=_delegate_to_sub_agent,
        required_permissions=["agent:delegate"],
        category="delegation",
    ))
