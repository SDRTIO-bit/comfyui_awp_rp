"""Story planning tools — periodic narrative analysis.

Port of oh-story-claudecode's per-N-turns story planning mechanism.
Every PLAN_INTERVAL turns (default 8), the agent performs a narrative
health check using the frameworks from STORY.md.
"""

from __future__ import annotations

import json
from typing import Any

from ..registry import ToolRegistry, ToolDefinition


def _story_plan_check(args: dict[str, Any]) -> str:
    """Check whether story planning should be triggered this turn.

    Returns a JSON with should_plan flag and reason.
    """

    generated_count = args.get("generated_count", 0)
    plan_interval = args.get("plan_interval", 8)
    last_plan_turn = args.get("last_plan_turn", 0)
    current_phase = args.get("current_phase", "normal")
    narrative_pacing = args.get("narrative_pacing", "normal")

    # Dynamic interval adjustment based on narrative pacing
    if narrative_pacing == "fast":
        plan_interval = max(5, plan_interval // 2)
    elif narrative_pacing == "slow":
        plan_interval = min(12, plan_interval * 2 // 1)

    # Don't plan on first turn
    if generated_count <= 1:
        return json.dumps({
            "should_plan": False,
            "reason": "First turn, no history to analyze",
            "next_plan_at": plan_interval,
        }, ensure_ascii=False)

    # Check if it's time
    turns_since_plan = generated_count - last_plan_turn
    if turns_since_plan >= plan_interval:
        return json.dumps({
            "should_plan": True,
            "reason": f"Turns since last plan: {turns_since_plan} >= {plan_interval}",
            "interval": plan_interval,
            "next_plan_at": generated_count + plan_interval,
        }, ensure_ascii=False)

    return json.dumps({
        "should_plan": False,
        "reason": f"Next plan at turn {last_plan_turn + plan_interval}",
        "turns_remaining": plan_interval - turns_since_plan,
    }, ensure_ascii=False)


def _story_plan_build_context(args: dict[str, Any]) -> str:
    """Build the context bundle for story planning analysis.

    Gathers recent turns, current state, NPC roster, and output
    formats the analysis brief for the sub-agent.
    """
    session_id = args.get("session_id", "")
    generated_count = args.get("generated_count", 0)
    recent_turns_summary = args.get("recent_turns_summary", "")
    current_state = args.get("current_state", {})
    npc_list = args.get("npc_list", [])
    unresolved_hooks = args.get("unresolved_hooks", [])
    worldbook_topics = args.get("worldbook_topics", [])

    # Build the analysis context for the sub-agent
    context_parts: list[str] = []

    context_parts.append(f"## Session: {session_id} (Turn {generated_count})")

    if recent_turns_summary:
        context_parts.append(f"## Recent Turns\n{recent_turns_summary}")

    if current_state:
        if isinstance(current_state, dict):
            state_summary = "\n".join(
                f"- {k}: {v}" for k, v in current_state.items()
                if not isinstance(v, dict)
            )
            if state_summary:
                context_parts.append(f"## Current State\n{state_summary}")

    if npc_list:
        npc_summary = "\n".join(
            f"- {n.get('name', '?')}: {n.get('last_action', '')}"
            for n in npc_list[:10]
            if isinstance(n, dict)
        )
        if npc_summary:
            context_parts.append(f"## NPC Roster\n{npc_summary}")

    if unresolved_hooks:
        hooks_text = "\n".join(
            f"- [{h.get('type', 'hook')}] {h.get('description', '')}"
            for h in unresolved_hooks[:10]
            if isinstance(h, dict)
        )
        if hooks_text:
            context_parts.append(f"## Unresolved Hooks\n{hooks_text}")

    if worldbook_topics:
        topics_text = ", ".join(str(t) for t in worldbook_topics[:20])
        context_parts.append(f"## Active Worldbook Topics: {topics_text}")

    return "\n\n".join(context_parts)


def _story_plan_analysis_task(args: dict[str, Any]) -> str:
    """Build the task description for the sub-agent to perform story planning.

    This returns the task text that should be passed to delegate_to_sub_agent
    with the novel-context-agent profile.
    """
    context = args.get("context", "")
    generated_count = args.get("generated_count", 0)

    task = (
        "## 剧情规划分析 — 第 {turn} 轮\n\n"
        "你是剧情导演。基于提供的上下文，完成以下分析（内部思考，不输出给玩家）：\n\n"
        "### 1. 价值转换检查（麦基场景检验）\n"
        "最近几轮每轮是否有有效价值变化？情感状态是否在波动？\n"
        "NSFW/氛围沉浸/日常温情场景豁免——这些场景的'停滞'是合法的。\n\n"
        "### 2. 布克模式定位\n"
        "当前故事遵循哪种基本情节模式（战胜怪物/从穷到富/追寻/远航与回归/喜剧/悲剧/重生）？\n"
        "如果没有清晰模式（日常向/NSFW向），填'自由模式'，不强套框架。\n\n"
        "### 3. 节拍定位（救猫咪15节拍，松散参考）\n"
        "当前处于哪个节拍位置？仅做松散参考，不强制映射。\n\n"
        "### 4. 角色原型追踪（皮尔逊12原型）\n"
        "每个主要NPC当前处于哪个原型阶段？弧线进展是否自然？\n\n"
        "### 5. 伏笔审计\n"
        "哪些已埋未收？计划何时回收？有没有被遗忘的伏笔？\n\n"
        "### 6. 情感波浪线\n"
        "最近几轮的张力曲线是否在波动？有没有过久的单一情绪？\n\n"
        "### 7. 信息不对称检查\n"
        "当前悬念配置是什么？观众知道>角色知道？角色知道>观众知道？是否需要切换？\n\n"
        "## 输出格式\n"
        "输出一段结构化的剧情规划报告（中文）：\n"
        "1. 当前定位（一句话）\n"
        "2. 价值转换：最近的价值变化总结\n"
        "3. 未落地伏笔：列出并建议回收时机\n"
        "4. 下阶段方向：接下来3-5轮的剧情方向建议\n"
        "5. 情感波浪线：当前情绪位置和下阶段情绪走向\n"
        "6. 节拍进度预估：当前大致处于什么节拍，何时进入下一节拍\n\n"
        "## 关键原则\n"
        "框架服务于故事，故事不服务于框架。如果分析结论与当前场景的直觉冲突，信任场景。"
    ).format(turn=generated_count)

    return task


def register_story_plan_tools(registry: ToolRegistry) -> None:
    """Register story planning tools."""
    registry.register(ToolDefinition(
        name="story_plan_check",
        description=(
            "Check whether story planning should be triggered this turn. "
            "Returns should_plan flag and reason. Call this near the end of "
            "each turn to see if it's time for a narrative analysis."
        ),
        parameters={
            "type": "object",
            "properties": {
                "generated_count": {
                    "type": "integer",
                    "description": "Number of turns generated so far.",
                },
                "plan_interval": {
                    "type": "integer",
                    "description": "How many turns between story plans (default 8).",
                    "default": 8,
                },
                "last_plan_turn": {
                    "type": "integer",
                    "description": "Turn index of last story plan execution.",
                    "default": 0,
                },
                "current_phase": {
                    "type": "string",
                    "description": "Current narrative phase.",
                    "default": "normal",
                },
                "narrative_pacing": {
                    "type": "string",
                    "enum": ["slow", "normal", "fast"],
                    "description": "Current narrative pacing.",
                    "default": "normal",
                },
            },
            "required": ["generated_count"],
        },
        execute_fn=_story_plan_check,
        required_permissions=[],
        category="story-planning",
    ))

    registry.register(ToolDefinition(
        name="story_plan_build_context",
        description=(
            "Build the analysis context for story planning. Gathers recent "
            "turns, NPC state, unresolved hooks, and active worldbook topics "
            "into a structured brief for the planning sub-agent."
        ),
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID."},
                "generated_count": {"type": "integer", "description": "Current turn count."},
                "recent_turns_summary": {"type": "string", "description": "Summary of recent turns."},
                "current_state": {"type": "object", "description": "Current world/character state."},
                "npc_list": {"type": "array", "items": {"type": "object"}, "description": "NPC roster."},
                "unresolved_hooks": {"type": "array", "items": {"type": "object"}, "description": "Unresolved plot hooks."},
                "worldbook_topics": {"type": "array", "items": {"type": "string"}, "description": "Active worldbook topics."},
            },
            "required": ["session_id"],
        },
        execute_fn=_story_plan_build_context,
        required_permissions=[],
        category="story-planning",
    ))

    registry.register(ToolDefinition(
        name="story_plan_analysis_task",
        description=(
            "Build the task description for the sub-agent to perform story planning "
            "analysis. Returns the task text to pass to delegate_to_sub_agent with "
            "the novel-context-agent or novel-reviewer profile."
        ),
        parameters={
            "type": "object",
            "properties": {
                "context": {"type": "string", "description": "Analysis context from story_plan_build_context."},
                "generated_count": {"type": "integer", "description": "Current turn count."},
            },
            "required": ["context", "generated_count"],
        },
        execute_fn=_story_plan_analysis_task,
        required_permissions=[],
        category="story-planning",
    ))
