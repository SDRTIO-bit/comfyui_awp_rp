"""V1 routing nodes: AWPRoundRouter and AWPSubAgentOrchestrator.

These are thin ComfyUI wrappers around the framework-agnostic runtime modules
in ``comfyui_awp_rp.runtime``. All inputs have defaults so old workflows that
do not wire them keep loading.
"""

from __future__ import annotations

import json
from typing import Any

from ..runtime.round_routing import build_round_routing_decision
from ..runtime.subagent_orchestrator import SubAgentOrchestrator
from ..runtime.round_contracts import RoundContextPacket


class AWPRoundRouter:
    """确定性回合路由节点。

    根据用户输入、当前变量状态、开放线索、近期消息，零 LLM 成本地决定：
    是否读取长期记忆、检索哪些世界书 query、是否派发子 Agent、世界书预算。
    输出 routing decision JSON，供 RoundPreparer / MemoryRead / Orchestrator 消费。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "user_input": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "forceInput": True,
                }),
                "session_id": ("STRING", {"default": "default", "forceInput": True}),
            },
            "optional": {
                "current_variables": ("STRING", {
                    "default": "{}", "forceInput": True,
                    "label": "当前变量状态（MVU）",
                }),
                "recent_summary": ("STRING", {"default": "", "forceInput": True}),
                "open_threads": ("STRING", {
                    "default": "[]", "multiline": True, "forceInput": True,
                }),
                "recent_messages": ("STRING", {
                    "default": "[]", "multiline": True, "forceInput": True,
                }),
                "turn_index": ("INT", {"default": 0, "min": 0, "max": 999999}),
                "last_memory_read_turn": ("INT", {"default": 0, "min": 0, "max": 999999}),
                "memory_read_interval": ("INT", {"default": 5, "min": 1, "max": 50}),
                "worldbook_core_keywords": ("STRING", {
                    "default": "", "label": "core关键词（逗号分隔）",
                }),
                "enable_subagents": ("BOOLEAN", {"default": True}),
                "worldbook_budget_tokens": ("INT", {"default": 4000, "min": 500, "max": 32000}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("路由决策JSON", "调试")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/路由"
    OUTPUT_NODE = False

    def execute(
        self,
        user_input: str,
        session_id: str,
        current_variables: str = "{}",
        recent_summary: str = "",
        open_threads: str = "[]",
        recent_messages: str = "[]",
        turn_index: int = 0,
        last_memory_read_turn: int = 0,
        memory_read_interval: int = 5,
        worldbook_core_keywords: str = "",
        enable_subagents: bool = True,
        worldbook_budget_tokens: int = 4000,
    ):
        def _loads(s: str, default):
            try:
                return json.loads(s) if s and s.strip() else default
            except json.JSONDecodeError:
                return default

        variables = _loads(current_variables, {})
        threads = _loads(open_threads, [])
        messages = _loads(recent_messages, [])
        core_kw = [
            k.strip() for k in worldbook_core_keywords.split(",") if k.strip()
        ] if worldbook_core_keywords else []

        decision = build_round_routing_decision(
            user_input,
            current_variables=variables,
            recent_summary=recent_summary,
            open_threads=threads,
            recent_messages=messages,
            turn_index=turn_index,
            last_memory_read_turn=last_memory_read_turn,
            memory_read_interval=memory_read_interval,
            worldbook_core_keywords=core_kw,
            enable_subagents=enable_subagents,
            worldbook_budget_tokens=worldbook_budget_tokens,
        )
        decision_json = json.dumps(decision.to_dict(), ensure_ascii=False, indent=2)
        debug = {
            "should_read_memory": decision.should_read_memory,
            "should_search_worldbook": decision.should_search_worldbook,
            "subagent_profiles": [j.profile for j in decision.subagent_jobs],
            "reasons": decision.reasons,
            "confidence": decision.confidence,
        }
        return (decision_json, json.dumps(debug, ensure_ascii=False))


class AWPSubAgentOrchestrator:
    """子 Agent 编排节点。

    消费 routing decision 中的 subagent_jobs，执行子 Agent（超时+fail-open），
    输出 advice JSON 与组装好的 RoundContextPacket JSON。
    无任务时零成本跳过（输出空 advice 与最小 packet）。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "routing_decision_json": ("STRING", {
                    "multiline": True, "default": "{}", "forceInput": True,
                }),
                "user_input": ("STRING", {
                    "multiline": True, "default": "", "forceInput": True,
                }),
            },
            "optional": {
                "session_id": ("STRING", {"default": "default", "forceInput": True}),
                "current_variables": ("STRING", {
                    "default": "{}", "forceInput": True, "label": "当前变量状态（MVU）",
                }),
                "recent_summary": ("STRING", {"default": "", "forceInput": True}),
                "open_threads": ("STRING", {
                    "default": "[]", "multiline": True, "forceInput": True,
                }),
                "retrieved_memories": ("STRING", {
                    "default": "[]", "multiline": True, "forceInput": True,
                    "label": "本轮召回记忆JSON",
                }),
                "retrieved_worldbook": ("STRING", {
                    "default": "[]", "multiline": True, "forceInput": True,
                    "label": "本轮命中世界书JSON",
                }),
                "timeout_seconds": ("INT", {"default": 30, "min": 5, "max": 120}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("子Agent建议JSON", "回合上下文包JSON", "调试")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/路由"
    OUTPUT_NODE = False

    def execute(
        self,
        routing_decision_json: str,
        user_input: str,
        session_id: str = "default",
        current_variables: str = "{}",
        recent_summary: str = "",
        open_threads: str = "[]",
        retrieved_memories: str = "[]",
        retrieved_worldbook: str = "[]",
        timeout_seconds: int = 30,
    ):
        from ..runtime.round_contracts import RoundRoutingDecision

        def _loads(s: str, default):
            try:
                return json.loads(s) if s and s.strip() else default
            except json.JSONDecodeError:
                return default

        decision = RoundRoutingDecision.from_dict(_loads(routing_decision_json, {}))
        variables = _loads(current_variables, {})
        threads = _loads(open_threads, [])
        memories = _loads(retrieved_memories, [])
        worldbook = _loads(retrieved_worldbook, [])

        # scene_state: derive a minimal view from variables if present
        scene_state = variables.get("scene_state") if isinstance(variables, dict) else None
        if not isinstance(scene_state, dict):
            scene_state = {}
        relationship_state = variables.get("relationship_state") if isinstance(variables, dict) else None
        if not isinstance(relationship_state, dict):
            relationship_state = {}

        orchestrator = SubAgentOrchestrator()
        results = []
        advice_error_note = ""
        if decision.subagent_jobs:
            try:
                results = orchestrator.run_jobs(
                    decision.subagent_jobs,
                    scene_state=scene_state,
                    relationship_state=relationship_state,
                    open_threads=threads,
                    relevant_memories=memories,
                    user_input=user_input,
                    recent_summary=recent_summary,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:  # noqa: BLE001 — fail-open
                advice_error_note = f"orchestrator-failed: {exc}"
                results = []

        advice_field = SubAgentOrchestrator.advice_to_packet_field(results)

        # ── Phase 2: Query structured memories for context assembly (read side) ─
        structured_mem: dict[str, Any] = {"story_facts": [], "open_threads": [], "scene_state": None}
        try:
            from ..memory.structured import StructuredMemoryManager
            mgr = StructuredMemoryManager()
            # Derive search keywords from user input (simple word overlap)
            _raw_terms = [
                w.strip() for w in
                user_input.replace("，", ",").replace("。", ",").replace("？", ",").replace("？", ",").split(",")
            ]
            search_terms = {w for w in _raw_terms if 2 <= len(w) <= 20}
            # If no punctuation gave terms, use the full input (bounded)
            if not search_terms and len(user_input.strip()) <= 20:
                search_terms = {user_input.strip()}
            # Entity match: any entity from facts whose name appears in input
            known_names = list(variables) if isinstance(variables, dict) else []
            entity_ids_mentioned = [k for k in known_names if k in user_input][:5]

            all_facts = mgr.query_story_facts(session_id, limit=30)
            # Also generate 2-3 char substrings from each search term for
            # fuzzy matching (e.g. "那件答应的事" → substrings include "答应")
            _sub_terms: set[str] = set()
            for t in search_terms:
                for win in (2, 3):
                    for i in range(len(t) - win + 1):
                        _sub_terms.add(t[i:i + win])
            _sub_terms.discard("")

            matched_facts = [
                f for f in all_facts
                if any(t in (f.content or "") for t in search_terms | _sub_terms)
                or bool(set(entity_ids_mentioned) & set(f.entity_ids or []))
                or any(eid in user_input for eid in (f.entity_ids or []))
            ][:5]
            structured_mem["story_facts"] = [
                {"summary": f.content, "tags": f.tags or [], "turn": f.metadata.get("evidence_turn", 0)}
                for f in matched_facts
            ]
            structured_mem["open_threads"] = [
                {"topic": t.content, "status": t.metadata.get("status", "open")}
                for t in mgr.query_open_threads(session_id, status="open", limit=10)
            ]
            scene = mgr.get_scene_state(session_id)
            if scene:
                structured_mem["scene_state"] = {
                    "location": scene.location, "time_of_day": scene.time_of_day,
                    "characters_present": scene.characters_present,
                    "mood": scene.mood, "narrative_summary": scene.narrative_summary,
                }
        except Exception:  # noqa: BLE001 — fail-open, empty structured_mem
            pass

        packet = RoundContextPacket(
            context_owner="routed",
            current_scene_state=scene_state,
            relationship_state=relationship_state,
            open_threads=threads,
            recent_summary=recent_summary,
            retrieved_memories=memories if isinstance(memories, list) else [],
            retrieved_worldbook_entries=worldbook if isinstance(worldbook, list) else [],
            subagent_advice=advice_field,
            routing_trace=decision.trace,
            should_curate_memory=decision.should_curate_memory,
            memory_curation_trigger=decision.memory_curation_trigger,
            structured_memories=structured_mem,
        )

        advice_json = json.dumps(advice_field, ensure_ascii=False, indent=2)
        packet_json = json.dumps(packet.to_dict(), ensure_ascii=False, indent=2)
        debug = {
            "jobs_requested": [j.profile for j in decision.subagent_jobs],
            "jobs_ok": [r.profile for r in results if r.ok],
            "jobs_failed": [
                {"profile": r.profile, "error": r.error} for r in results if not r.ok
            ],
            "note": advice_error_note,
        }
        return (advice_json, packet_json, json.dumps(debug, ensure_ascii=False))
