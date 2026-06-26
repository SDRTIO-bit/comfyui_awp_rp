"""Deterministic round routing.

Decides — without any LLM call — whether to read long-term memory, which
worldbook queries to run, and which sub-agents (if any) to dispatch for the
current turn. The main writer is no longer asked to "volunteer" tool calls;
this router makes those calls happen (or not) with explicit, testable rules.

Fail-open by design: every decision is a best-effort hint. Downstream nodes
must tolerate ``should_read_memory=False`` returning empty and sub-agents
failing without blocking the writer.
"""

from __future__ import annotations

from typing import Any

from .round_contracts import RoundRoutingDecision, SubAgentJob


# ── Signal vocabularies (deterministic keyword sets) ────────────────────────

MEMORY_RECALL_SIGNALS = (
    "之前", "上次", "上回", "曾经", "答应", "还记得", "记得", "当时", "那天",
    "那天晚上", "约定", "承诺", "发誓", "从前", "刚才", "提到", "说过", "旧",
    "以前", "过往", "回忆",
)

SCENE_CHANGE_SIGNALS = (
    "第二天", "几天后", "次日", "入夜", "清晨", "黄昏", "后来", "随后",
    "离开", "前往", "回到", "走进", "来到", "转场", "与此同时", "不久",
    "数日后", "一周后", "一个月后",
)

RELATIONSHIP_SIGNALS = (
    "怨", "恨", "原谅", "信任", "怀疑", "背叛", "秘密", "隐瞒", "坦白",
    "揭露", "旧账", "兑现", "翻脸", "和好", "疏远", "亲近", "试探", "质问",
    "其实", "真相", "身份",
)

HIGH_COMPLEXITY_SIGNALS = (
    "冲突", "对峙", "决裂", "选择", "重大", "决定", "摊牌", "抉择", "危机",
    "转折", "关键", "必须",
)

MULTI_CHARACTER_HINT = 3  # ≥ this many distinct known characters mentioned → multi-character


def _normalize_text(text: Any) -> str:
    return str(text or "")


def _extract_known_entity_names(variables: Any, open_threads: Any) -> list[str]:
    """Collect character/entity names visible in current state + open threads."""
    names: list[str] = []
    variables = variables if isinstance(variables, dict) else {}
    # relationship_state-style: {name: {...}}
    for key in variables:
        if isinstance(key, str) and len(key) <= 12:
            names.append(key)
    rel = variables.get("relationship_state") if isinstance(variables, dict) else None
    if isinstance(rel, dict):
        names.extend(k for k in rel if isinstance(k, str))
    if isinstance(open_threads, list):
        for t in open_threads:
            if isinstance(t, dict):
                for k in ("entity", "character", "subject", "who"):
                    v = t.get(k)
                    if isinstance(v, str) and v not in names:
                        names.append(v)
    # dedupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _count_mentioned(text: str, names: list[str]) -> list[str]:
    found: list[str] = []
    for n in names:
        if n and n in text:
            found.append(n)
    return found


def build_round_routing_decision(
    user_input: str,
    *,
    current_variables: Any = None,
    recent_summary: str = "",
    open_threads: Any = None,
    recent_messages: Any = None,
    turn_index: int = 0,
    last_memory_read_turn: int = 0,
    memory_read_interval: int = 5,
    worldbook_core_keywords: Any = None,
    enable_subagents: bool = True,
    worldbook_budget_tokens: int = 4000,
) -> RoundRoutingDecision:
    """Build a deterministic routing decision for one turn.

    Args:
        user_input: The player's input this turn.
        current_variables: MVU variable state (may carry relationship_state).
        recent_summary: Short-term summary already in context.
        open_threads: List of unresolved thread dicts (names/subjects).
        recent_messages: Recent turn texts (list of str) — used to tell whether
            a mentioned entity is already in short-term context.
        turn_index: 1-based current turn number.
        last_memory_read_turn: Turn index of last memory read.
        memory_read_interval: Re-read memory every N turns even without signal.
        worldbook_core_keywords: Keywords already covered by core/constant
            worldbook entries; mentions outside this set trigger retrieval.
        enable_subagents: Whether sub-agent dispatch is allowed at all.
        worldbook_budget_tokens: Token budget for worldbook injection.

    Returns:
        A :class:`RoundRoutingDecision` with explicit ``reasons`` and ``trace``.
    """
    text = _normalize_text(user_input)
    reasons: list[str] = []
    trace: dict[str, Any] = {
        "turn_index": turn_index,
        "input_len": len(text),
        "signals": {},
    }

    variables = current_variables if isinstance(current_variables, dict) else {}
    threads = open_threads if isinstance(open_threads, list) else []
    core_kw = (
        [str(k) for k in worldbook_core_keywords]
        if isinstance(worldbook_core_keywords, (list, tuple, set))
        else []
    )

    # ── Memory read decision ────────────────────────────────────────────────
    should_read_memory = False
    memory_queries: list[str] = []

    hit_recall = [s for s in MEMORY_RECALL_SIGNALS if s in text]
    if hit_recall:
        should_read_memory = True
        reasons.append(f"recall-signal: {','.join(hit_recall[:3])}")
        memory_queries.extend(hit_recall[:3])
        trace["signals"]["recall"] = hit_recall

    # Entities mentioned in input but absent from short-term context
    known_names = _extract_known_entity_names(variables, threads)
    short_term_blob = _normalize_text(recent_summary) + " " + _normalize_text(
        " ".join(recent_messages) if isinstance(recent_messages, list) else ""
    )
    mentioned_in_input = _count_mentioned(text, known_names)
    new_mentions = [n for n in mentioned_in_input if n not in short_term_blob]
    if new_mentions:
        should_read_memory = True
        reasons.append(f"new-entity-mention: {','.join(new_mentions[:3])}")
        memory_queries.extend(new_mentions[:3])
        trace["signals"]["new_mentions"] = new_mentions

    # Scene / time change
    hit_scene = [s for s in SCENE_CHANGE_SIGNALS if s in text]
    if hit_scene:
        should_read_memory = True
        reasons.append(f"scene-change: {','.join(hit_scene[:2])}")
        trace["signals"]["scene"] = hit_scene

    # Relationship reversal / secret / promise
    hit_rel = [s for s in RELATIONSHIP_SIGNALS if s in text]
    if hit_rel:
        should_read_memory = True
        reasons.append(f"relationship-signal: {','.join(hit_rel[:3])}")
        memory_queries.extend([s for s in hit_rel if s in text][:3])
        trace["signals"]["relationship"] = hit_rel

    # Periodic refresh
    if turn_index > 0 and (turn_index - last_memory_read_turn) >= memory_read_interval:
        should_read_memory = True
        reasons.append(f"periodic-refresh (interval={memory_read_interval})")

    # ── Worldbook retrieval decision ────────────────────────────────────────
    should_search_worldbook = False
    worldbook_queries: list[str] = []
    # Short noun-like candidates only (2-6 chars, split on punctuation). Whole-
    # sentence chitchat must NOT be treated as a worldbook query.
    short_candidates = [
        w.strip() for w in text.replace("，", ",").replace("。", ",").replace("、", ",").split(",")
        if 2 <= len(w.strip()) <= 6 and w.strip() not in short_term_blob
    ]
    candidate_terms = new_mentions + short_candidates
    retrieval_terms = [
        t for t in candidate_terms
        if t and t not in core_kw and t not in worldbook_queries
    ]
    # Trigger retrieval only when there is a baseline to compare against:
    # either a known entity newly mentioned, or core keywords were provided.
    # This keeps plain chitchat (no entities, no core baseline) from triggering.
    has_baseline = bool(new_mentions) or bool(core_kw)
    if retrieval_terms and has_baseline:
        should_search_worldbook = True
        worldbook_queries = retrieval_terms[:5]
        reasons.append(f"worldbook-retrieval: {','.join(worldbook_queries[:3])}")
        trace["signals"]["worldbook_queries"] = worldbook_queries

    # ── Sub-agent routing (Phase 1: rp-director / rp-critic only) ───────────
    high_complexity = [s for s in HIGH_COMPLEXITY_SIGNALS if s in text]
    is_multi_character = len(mentioned_in_input) >= MULTI_CHARACTER_HINT
    strong_emotion = bool(hit_rel)

    subagent_jobs: list[SubAgentJob] = []
    if enable_subagents:
        # rp-critic: emotional conflict / OOC risk / secret/promise/identity
        if strong_emotion or ("真相" in text or "身份" in text or "隐瞒" in text):
            subagent_jobs.append(SubAgentJob(
                profile="rp-critic",
                task_type="review",
                task="检查当前冲突中角色行为是否符合既定关系状态，列出风险与不可违背事实。",
                priority="high" if strong_emotion else "normal",
                max_result_tokens=800,
            ))
            reasons.append("subagent:rp-critic (conflict/secret risk)")

        # rp-director: multi-character / scene change / major plot push / open choice
        if is_multi_character or hit_scene or high_complexity:
            # cap: at most 2 jobs per turn
            if len(subagent_jobs) < 2:
                subagent_jobs.append(SubAgentJob(
                    profile="rp-director",
                    task_type="direction",
                    task="给出简短场景计划：目标、冲突、可揭露信息、角色短期意图、禁止事项。",
                    priority="normal",
                    max_result_tokens=800,
                ))
                reasons.append("subagent:rp-director (multi-character/scene/complexity)")

    # ── Phase 2: Memory curator trigger (after V1 sub-agent routing) ──────
    # New rules, do NOT modify V1 rp-critic / rp-director logic above.
    CURATION_SIGNALS = (
        "冲突", "对峙", "决裂", "重大", "决定",
        "怨", "恨", "原谅", "信任", "背叛",
        "秘密", "揭露", "真相", "身份",
        "答应", "承诺", "约定", "发誓",
        "第一次", "首次", "突然", "终于",
    )

    should_curate_memory = False
    memory_curation_trigger = ""

    hit_curation = [s for s in CURATION_SIGNALS if s in text]
    if hit_curation:
        should_curate_memory = True
        memory_curation_trigger = f"signal:{','.join(hit_curation[:3])}"
        reasons.append(f"curate-memory: {','.join(hit_curation[:3])}")

    # Periodic curation every 3 turns
    if turn_index > 0 and turn_index % 3 == 0 and not should_curate_memory:
        should_curate_memory = True
        memory_curation_trigger = "periodic"
        reasons.append("curate-memory:periodic")

    # Scene change triggers curation (append to existing signal)
    if hit_scene and not should_curate_memory:
        should_curate_memory = True
        memory_curation_trigger = "scene-change"
        reasons.append("curate-memory:scene-change")

    trace["signals"]["curation"] = {
        "triggered": should_curate_memory,
        "trigger": memory_curation_trigger,
        "hit_signals": hit_curation,
    }

    should_run_continuity_check = bool(hit_rel or hit_recall)
    should_scan_npc_activity = is_multi_character

    confidence = 0.6 + 0.1 * min(len(reasons), 4)

    trace.update({
        "should_read_memory": should_read_memory,
        "memory_queries": memory_queries,
        "should_search_worldbook": should_search_worldbook,
        "worldbook_queries": worldbook_queries,
        "subagent_profiles": [j.profile for j in subagent_jobs],
        "known_names": known_names,
        "mentioned_in_input": mentioned_in_input,
        "new_mentions": new_mentions,
        "subagent_count": len(subagent_jobs),
    })

    return RoundRoutingDecision(
        should_read_memory=should_read_memory,
        memory_queries=memory_queries[:6],
        should_search_worldbook=should_search_worldbook,
        worldbook_queries=worldbook_queries,
        subagent_jobs=subagent_jobs[:2],
        should_run_continuity_check=should_run_continuity_check,
        should_scan_npc_activity=should_scan_npc_activity,
        worldbook_budget_tokens=worldbook_budget_tokens,
        reasons=reasons,
        confidence=round(min(confidence, 0.95), 2),
        should_curate_memory=should_curate_memory,
        memory_curation_trigger=memory_curation_trigger,
        trace=trace,
    )
