"""Memory tools — read and write long-term memories."""

from __future__ import annotations

import json
from typing import Any

from ...memory.long_term import LongTermMemory
from ..registry import ToolRegistry, ToolDefinition


def _memory_read(args: dict[str, Any]) -> str:
    """Read memories from long-term storage."""
    namespace = args.get("namespace", "default")
    tags_any = args.get("tags_any", [])
    type_filter = args.get("type_filter", "")
    limit = args.get("limit", 10)

    memory = LongTermMemory()
    records = memory.query(
        namespace=namespace,
        tags_any=tags_any if tags_any else None,
        type_filter=type_filter if type_filter else None,
        limit=limit,
    )
    return json.dumps([
        {
            "id": r.id,
            "title": r.title,
            "content": r.content,
            "type": r.type,
            "tags": r.tags,
            "importance": r.importance,
        }
        for r in records
    ], ensure_ascii=False, indent=2)


def _memory_write(args: dict[str, Any]) -> str:
    """Write a memory to long-term storage."""
    namespace = args.get("namespace", "default")
    content = args.get("content", "")
    title = args.get("title", "")
    memory_type = args.get("type", "event")
    tags = args.get("tags", [])
    importance = args.get("importance", 0.5)

    if not content:
        return "Error: content is required"

    memory = LongTermMemory()
    record = memory.write(
        namespace=namespace,
        content=content,
        title=title if title else None,
        type=memory_type,
        tags=tags if tags else None,
        importance=importance,
    )
    return f"Memory saved: {record.id}"


def register_memory_tools(registry: ToolRegistry) -> None:
    """Register memory tools."""
    registry.register(ToolDefinition(
        name="memory_read",
        description="Read memories from long-term storage. Use this to recall past events, relationships, and context for the current RP session or novel project.",
        parameters={
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Memory namespace (usually the session ID or project ID).",
                },
                "tags_any": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags to filter (matches any).",
                },
                "type_filter": {
                    "type": "string",
                    "description": "Optional type filter (e.g. 'event', 'relationship-change', 'commitment').",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of memories to return.",
                    "default": 10,
                },
            },
            "required": ["namespace"],
        },
        execute_fn=_memory_read,
        required_permissions=["memory:read"],
        category="memory",
    ))

    registry.register(ToolDefinition(
        name="memory_write",
        description="Write a new memory to long-term storage. Use this to save important events, relationship changes, promises, or discoveries from the current turn.",
        parameters={
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Memory namespace (usually the session ID or project ID).",
                },
                "content": {
                    "type": "string",
                    "description": "The memory content to store.",
                },
                "title": {
                    "type": "string",
                    "description": "Optional title for the memory.",
                },
                "type": {
                    "type": "string",
                    "description": "Memory type: 'event', 'relationship-change', 'commitment', 'discovery', 'state-change'.",
                    "default": "event",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags for categorization.",
                },
                "importance": {
                    "type": "number",
                    "description": "Importance score 0.0-1.0.",
                    "default": 0.5,
                },
            },
            "required": ["namespace", "content"],
        },
        execute_fn=_memory_write,
        required_permissions=["memory:write"],
        category="memory",
    ))
