"""Tool executor — receives LLM tool calls and dispatches them to registered tools.

This sits between the LLM and the ToolRegistry.  When the LLM returns
``tool_calls``, the agent loop passes them here for execution, and the
results are formatted as ``tool`` role messages to append back to the
conversation.

Supports both serial and parallel (P6.2) execution of multiple tool calls.
"""

from __future__ import annotations

import concurrent.futures
import json
import traceback
from typing import Any

from ..core.types import LlmToolCall
from .registry import ToolRegistry, get_global_registry


class ToolExecutor:
    """Executes LLM-requested tool calls against the tool registry."""

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self._registry = registry or get_global_registry()

    def execute_call(self, call: LlmToolCall) -> dict[str, Any]:
        """Execute a single tool call.

        Returns an OpenAI-format tool result message ready to append
        to the conversation messages list.
        """
        args = call.parse_arguments()
        tool = self._registry.get(call.name)

        if tool is None:
            result_text = f"Error: tool '{call.name}' is not registered."
        else:
            try:
                result_text = tool.execute(args)
            except Exception as exc:
                result_text = f"Error executing tool '{call.name}': {exc}"
                tb = traceback.format_exc()
                if len(tb) > 500:
                    tb = tb[:500] + "..."
                result_text += f"\n\nTraceback:\n{tb}"

        return {
            "role": "tool",
            "tool_call_id": call.id,
            "name": call.name,
            "content": str(result_text),
        }

    def execute_calls(self, calls: list[LlmToolCall]) -> list[dict[str, Any]]:
        """Execute multiple tool calls, returning all result messages.

        Uses serial execution by default for compatibility.
        Use execute_calls_parallel() for concurrent execution.
        """
        return [self.execute_call(call) for call in calls]

    def execute_calls_parallel(
        self,
        calls: list[LlmToolCall],
        max_workers: int = 4,
    ) -> list[dict[str, Any]]:
        """Execute multiple tool calls in parallel using ThreadPoolExecutor.

        Best for independent tool calls (e.g., query memory + query worldbook
        simultaneously). Do NOT use for dependent calls where one tool's output
        feeds another tool's input.

        Args:
            calls: List of tool calls to execute.
            max_workers: Maximum number of concurrent threads.

        Returns:
            List of tool result messages (order may differ from input).
        """
        if len(calls) <= 1:
            return self.execute_calls(calls)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_call = {
                executor.submit(self.execute_call, call): call
                for call in calls
            }
            results: list[dict[str, Any]] = []
            for future in concurrent.futures.as_completed(future_to_call):
                try:
                    results.append(future.result(timeout=30))
                except concurrent.futures.TimeoutError:
                    call = future_to_call[future]
                    results.append({
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": f"Error: tool '{call.name}' timed out after 30s.",
                    })
                except Exception as exc:
                    call = future_to_call[future]
                    results.append({
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": f"Error: tool '{call.name}' failed: {exc}",
                    })
            return results


# Dependency-aware parallel execution
_DEPENDENCY_GRAPH: dict[str, list[str]] = {
    # Tools that should be serialized (output of A feeds into B)
    "story_plan_build_context": ["story_plan_analysis_task"],
    "get_injection_keywords": ["resolve_injections"],
}


def should_parallelize(calls: list[LlmToolCall]) -> bool:
    """Check if tool calls can be safely parallelized.

    Returns False if any tool depends on the output of another.
    """
    names = {c.name for c in calls}
    for name in names:
        deps = _DEPENDENCY_GRAPH.get(name, [])
        for dep in deps:
            if dep in names:
                return False
    return True
