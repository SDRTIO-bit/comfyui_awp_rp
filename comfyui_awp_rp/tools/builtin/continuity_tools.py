"""Continuity tools — check narrative consistency across turns/chapters.

Borrows the 5-dimension review pattern from webnovel-writer's reviewer agent:
setting consistency, timeline, narrative continuity, character consistency,
and logic.
"""

from __future__ import annotations

import json
from typing import Any

from ..registry import ToolRegistry, ToolDefinition


# Forbidden format patterns (mirrors rp_pipeline.py FORBIDDEN_FORMAT_PATTERNS)
_FORBIDDEN_FORMAT_PATTERNS = (
    "```json", "```yaml", "<analysis>", "思考过程", "[Status:", "debugLog",
)

# Player agency violation patterns
_PLAYER_AGENCY_PATTERNS = (
    "你决定", "你选择", "你转身", "你拿起", "你说：", "你回答", "你意识到", "你心想",
)

# Knowledge leak patterns
_KNOWLEDGE_LEAK_PATTERNS = (
    "系统提示", "开发者指令", "worldbook", "runtime", "metadata", "候选补丁",
)


def _continuity_check(args: dict[str, Any]) -> str:
    """Run a deterministic continuity check on a piece of text.

    This is a lightweight, non-LLM check that scans for:
    - Format violations (JSON/status leaking into narrative)
    - Player agency violations (narrative controlling the player)
    - Knowledge boundary leaks (internal/runtime terms exposed)

    For full 5-dimension LLM review, use the ``delegate_to_sub_agent`` tool
    with the ``novel-reviewer`` profile.
    """
    text = args.get("text", "")
    check_type = args.get("check_type", "all")

    if not text.strip():
        return json.dumps({
            "passed": False,
            "issues": [{"code": "empty", "severity": "error", "message": "Text is empty."}],
        }, ensure_ascii=False, indent=2)

    issues: list[dict[str, Any]] = []

    if check_type in ("all", "format"):
        for pattern in _FORBIDDEN_FORMAT_PATTERNS:
            if pattern in text:
                issues.append({
                    "code": "format",
                    "severity": "error",
                    "message": f"Text contains forbidden format pattern: '{pattern}'.",
                    "suggestion": "Remove JSON, status bars, or meta-commentary from narrative.",
                })
                break

    if check_type in ("all", "player_agency"):
        for pattern in _PLAYER_AGENCY_PATTERNS:
            if pattern in text:
                issues.append({
                    "code": "player-agency",
                    "severity": "error",
                    "message": f"Text appears to control the player: '{pattern}'.",
                    "suggestion": "Describe NPC/world reactions and leave player choices to the user.",
                })
                break

    if check_type in ("all", "knowledge_leak"):
        lowered = text.lower()
        for pattern in _KNOWLEDGE_LEAK_PATTERNS:
            if pattern.lower() in lowered:
                issues.append({
                    "code": "knowledge-leak",
                    "severity": "error",
                    "message": f"Text exposes internal knowledge: '{pattern}'.",
                    "suggestion": "Keep hidden context implicit.",
                })
                break

    passed = len(issues) == 0
    return json.dumps({
        "passed": passed,
        "decision": "accept" if passed else "revise",
        "issues": issues,
        "dimensions_checked": ["format", "player_agency", "knowledge_leak"] if check_type == "all" else [check_type],
    }, ensure_ascii=False, indent=2)


def register_continuity_tools(registry: ToolRegistry) -> None:
    """Register continuity check tools."""
    registry.register(ToolDefinition(
        name="continuity_check",
        description="Run a deterministic continuity check on narrative text. Checks for format violations, player agency violations, and knowledge boundary leaks. For full 5-dimension LLM review (setting/timeline/continuity/character/logic), delegate to the 'novel-reviewer' sub-agent instead.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The narrative text to check."},
                "check_type": {
                    "type": "string",
                    "enum": ["all", "format", "player_agency", "knowledge_leak"],
                    "description": "Type of check to run.",
                    "default": "all",
                },
            },
            "required": ["text"],
        },
        execute_fn=_continuity_check,
        required_permissions=[],
        category="quality",
    ))
