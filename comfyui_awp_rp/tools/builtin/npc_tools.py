"""NPC activity tools — background NPC scan and state tracking.

Port of oh-story-claudecode's per-turn NPC activity mechanism. Every turn,
the agent should scan all off-screen NPCs for:
1. Time advancement: what were they doing last turn? What naturally progresses now?
2. Trajectory crossing: does their activity intersect with the current scene?
3. Decision: silent advance / background mention / active intervention.
"""

from __future__ import annotations

import json
from typing import Any

from ..registry import ToolRegistry, ToolDefinition


def _npc_activity_scan(args: dict[str, Any]) -> str:
    """Scan background NPCs and determine their activity level.

    This tool returns the current NPC roster with activity status,
    helping the agent decide which NPCs need attention this turn.

    The agent should call this tool at the START of each turn's thinking
    flow (before Step 4 "人事物怎么动") to get a full picture of who
    needs updating.
    """
    npc_list = args.get("npc_list", [])
    current_scene = args.get("current_scene", "")
    current_location = args.get("current_location", "")
    time_passed = args.get("time_passed", "unknown")

    if not isinstance(npc_list, list):
        npc_list = []

    on_screen: list[dict[str, Any]] = []
    off_screen: list[dict[str, Any]] = []
    needs_attention: list[dict[str, Any]] = []

    for npc in npc_list:
        if not isinstance(npc, dict):
            continue
        name = npc.get("name", "Unknown")
        present = npc.get("present", False)
        last_action = npc.get("last_action", "")
        last_thought = npc.get("last_thought", "")
        last_updated_turn = npc.get("last_updated_turn", 0)
        location = npc.get("location", "")

        entry = {
            "name": name,
            "present": present,
            "last_action": last_action,
            "last_thought": last_thought,
            "last_updated_turn": last_updated_turn,
            "location": location,
        }

        if present:
            on_screen.append(entry)
        else:
            # Determine urgency
            turns_since_update = max(0, args.get("current_turn", 0) - last_updated_turn)
            entry["turns_since_update"] = turns_since_update

            # Check trajectory crossing
            crossing_type = _check_trajectory_crossing(
                entry, current_scene, current_location, time_passed
            )
            entry["crossing_type"] = crossing_type

            off_screen.append(entry)
            if turns_since_update >= 2 or crossing_type != "none":
                needs_attention.append(entry)

    return json.dumps({
        "on_screen": on_screen,
        "off_screen": off_screen,
        "needs_attention": needs_attention,
        "instructions": (
            "For each NPC in 'needs_attention':\n"
            "1. 时间推进：该角色上轮在做什么？过了本轮时间后自然进展到什么状态？\n"
            "2. 轨迹交叉：其行动/想法是否与当前场景有时间、地点、人际的重叠？\n"
            "   - 人际交叉 → 主动联系玩家（来电/消息）\n"
            "   - 地点交叉 → 偶遇（街头/走廊/同一空间）\n"
            "   - 时间交叉 → 留言/未读消息/前台便条\n"
            "   - 危机驱动 → 该角色遇到麻烦，主动求助\n"
            "3. 决策（三选一）：\n"
            "   - 静默推进：更新变量，不在叙事中展现\n"
            "   - 背景提及：1-2句环境细节（消息提醒/旁人提及/环境音）\n"
            "   - 主动介入：直接打断场景（敲门/来电/偶遇），该角色变为出场角色\n"
            "每轮至少更新 2 个后台角色的行动和内心状态。"
        ),
    }, ensure_ascii=False, indent=2)


def _check_trajectory_crossing(
    npc: dict[str, Any],
    current_scene: str,
    current_location: str,
    time_passed: str,
) -> str:
    """Check if an NPC's trajectory crosses with the current scene.

    Returns: "none" | "time" | "location" | "relationship" | "crisis"
    """
    npc_location = npc.get("location", "")
    last_action = npc.get("last_action", "")
    turns_since = npc.get("turns_since_update", 0)

    # Location crossing
    if current_location and npc_location and (
        current_location in npc_location or npc_location in current_location
    ):
        return "location"

    # Time-based: long silence → worth checking in
    if turns_since >= 5:
        return "time"

    # Crisis keywords in last action
    crisis_keywords = ("求救", "遇险", "危机", "受伤", "被困", "追", "逃")
    if any(kw in last_action for kw in crisis_keywords):
        return "crisis"

    return "none"


def _npc_update_state(args: dict[str, Any]) -> str:
    """Record an NPC's updated state after this turn's processing.

    The agent calls this tool AFTER processing each NPC to record
    what they're now doing and thinking. This updates the NPC roster
    for the next turn's scan.
    """
    npc_name = args.get("name", "")
    new_action = args.get("new_action", "")
    new_thought = args.get("new_thought", "")
    decision = args.get("decision", "silent")
    current_turn = args.get("current_turn", 0)

    if not npc_name:
        return "Error: npc name is required"

    return json.dumps({
        "name": npc_name,
        "action": new_action,
        "thought": new_thought,
        "decision": decision,
        "updated_turn": current_turn,
        "status": "updated",
    }, ensure_ascii=False, indent=2)


def register_npc_tools(registry: ToolRegistry) -> None:
    """Register NPC activity tools."""
    registry.register(ToolDefinition(
        name="npc_activity_scan",
        description=(
            "Scan all NPCs to determine who needs attention this turn. "
            "Returns on-screen NPCs, off-screen NPCs sorted by urgency, "
            "and trajectory crossing analysis. "
            "Call this at the START of every turn's thinking flow to know "
            "which background characters need time advancement or intervention."
        ),
        parameters={
            "type": "object",
            "properties": {
                "npc_list": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "List of NPC state objects, each with: name, present(bool), last_action, last_thought, last_updated_turn, location.",
                },
                "current_scene": {
                    "type": "string",
                    "description": "Brief description of current scene context.",
                },
                "current_location": {
                    "type": "string",
                    "description": "Current location name.",
                },
                "time_passed": {
                    "type": "string",
                    "description": "How much time has passed this turn.",
                },
                "current_turn": {
                    "type": "integer",
                    "description": "Current turn index number.",
                    "default": 0,
                },
            },
            "required": ["npc_list", "current_scene"],
        },
        execute_fn=_npc_activity_scan,
        required_permissions=["npc:read"],
        category="npc",
    ))

    registry.register(ToolDefinition(
        name="npc_update_state",
        description=(
            "Record an NPC's updated action and mental state after processing. "
            "Call this for each NPC whose state changed this turn (even if just "
            "'继续做同一件事'). This feeds the next turn's npc_activity_scan."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "NPC name.",
                },
                "new_action": {
                    "type": "string",
                    "description": "What the NPC is now doing (past tense or present).",
                },
                "new_thought": {
                    "type": "string",
                    "description": "What the NPC is thinking/worrying about.",
                },
                "decision": {
                    "type": "string",
                    "enum": ["silent", "bg_mention", "intervene"],
                    "description": "Activity decision: silent advance, background mention, or active intervention.",
                    "default": "silent",
                },
                "current_turn": {
                    "type": "integer",
                    "description": "Current turn index.",
                    "default": 0,
                },
            },
            "required": ["name"],
        },
        execute_fn=_npc_update_state,
        required_permissions=["npc:write"],
        category="npc",
    ))
