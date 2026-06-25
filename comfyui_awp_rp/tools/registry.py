"""Tool registry — registers callable tools and resolves them by name.

Each tool declares:
- name: unique identifier the LLM uses to call it
- description: natural language description for the LLM
- parameters: JSON Schema describing accepted arguments
- execute(args) -> result string
- required_permissions: which agent roles may use this tool
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class ToolDefinition:
    """Definition of a callable tool."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    execute_fn: Callable[[dict[str, Any]], str]
    required_permissions: list[str] = field(default_factory=list)
    category: str = "general"

    def execute(self, args: dict[str, Any]) -> str:
        """Execute the tool with the given arguments."""
        return self.execute_fn(args)


class ToolRegistry:
    """Registry for callable tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool."""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDefinition]:
        """List all registered tools."""
        return list(self._tools.values())

    def list_names(self) -> list[str]:
        """List all tool names."""
        return list(self._tools.keys())

    def get_for_permissions(
        self,
        permissions: Optional[list[str]] = None,
        tool_ids: Optional[list[str]] = None,
    ) -> list[ToolDefinition]:
        """Get tools filtered by permissions and/or explicit tool IDs.

        Args:
            permissions: If provided, only return tools whose
                required_permissions are a subset of permissions.
            tool_ids: If provided, only return tools with these names.
        """
        result: list[ToolDefinition] = []
        for tool in self._tools.values():
            if tool_ids and tool.name not in tool_ids:
                continue
            if permissions:
                if not set(tool.required_permissions).issubset(set(permissions)):
                    continue
            result.append(tool)
        return result

    def to_llm_definitions(
        self,
        tools: Optional[list[ToolDefinition]] = None,
    ) -> list["LlmToolDefinition"]:
        """Convert registered tools to LlmToolDefinition list for the LLM API."""
        from ..core.types import LlmToolDefinition

        tools = tools or self.list_tools()
        return [
            LlmToolDefinition(
                name=tool.name,
                description=tool.description,
                parameters=tool.parameters,
            )
            for tool in tools
        ]


# Global registry instance
_global_registry: Optional[ToolRegistry] = None


def get_global_registry() -> ToolRegistry:
    """Get or create the global tool registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
        # Register built-in tools lazily
        from .builtin import register_builtin_tools
        register_builtin_tools(_global_registry)
    return _global_registry
