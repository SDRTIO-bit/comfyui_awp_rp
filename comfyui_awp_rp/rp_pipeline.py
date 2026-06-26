"""ComfyUI-native RP pipeline helpers.

The functions in this module intentionally avoid storage writes. They mirror
the original AWP RP workflow boundary: read context, generate player-visible
text, and emit pending candidate patches that another explicit node may review.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Optional


RP_CONTEXT_VERSION = "awp.comfy.rp-context-bundle.v1"
FINAL_OUTPUT_VERSION = "awp.comfy.rp-final-output.v1"


def utc_now_iso() -> str:
    """Return a compact UTC timestamp for diagnostics and candidate IDs."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe_json_loads(value: Any, default: Any) -> Any:
    """Parse JSON strings while accepting already-structured values."""
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return default
    text = value.strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def json_dumps(data: Any, indent: Optional[int] = 2) -> str:
    return json.dumps(data, ensure_ascii=False, indent=indent)


def truncate_text(text: str, max_chars: int = 240) -> str:
    clean = " ".join(str(text).split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 1].rstrip() + "…"


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4) if text else 0


def _dedupe_dicts(items: Iterable[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        value = str(item.get(key, "")).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(item)
    return out


def _normalize_entities(known_entities: Any) -> list[dict[str, Any]]:
    data = safe_json_loads(known_entities, [])
    if isinstance(data, dict):
        for key in ("entities", "entries", "worldbook", "candidates"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        return []

    entities: list[dict[str, Any]] = []
    for idx, raw in enumerate(data):
        if not isinstance(raw, dict):
            continue
        name = raw.get("name") or raw.get("title") or raw.get("id") or f"entity-{idx}"
        aliases = raw.get("aliases") if isinstance(raw.get("aliases"), list) else []
        entity_id = (
            raw.get("entityId")
            or raw.get("entity_id")
            or raw.get("id")
            or raw.get("card_id")
            or str(name)
        )
        entities.append(
            {
                "entityId": str(entity_id),
                "entryId": str(raw.get("entryId") or raw.get("entry_id") or raw.get("id") or ""),
                "name": str(name),
                "aliases": [str(alias) for alias in aliases],
                "category": str(raw.get("category") or raw.get("type") or "character"),
                "shortDescription": str(raw.get("shortDescription") or raw.get("description") or ""),
            }
        )
    return entities


def _extract_dialogues(raw_text: str) -> list[dict[str, Any]]:
    patterns = [
        r'"([^"]+)"',
        r"'([^']+)'",
        r"“([^”]+)”",
        r"「([^」]+)」",
        r"『([^』]+)』",
    ]
    dialogues: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, raw_text):
            text = match.group(1).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            dialogues.append(
                {
                    "speakerEntityId": "player",
                    "targetEntityIds": [],
                    "text": text,
                    "toneHints": _extract_tone_hints(raw_text[: match.start()]),
                }
            )
    return dialogues


def _extract_actions(raw_text: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for match in re.finditer(r"\*([^*]+)\*", raw_text):
        action = match.group(1).strip()
        if action:
            actions.append(
                {
                    "actorEntityId": "player",
                    "action": action,
                    "targetEntityIds": [],
                    "objectEntityIds": [],
                    "locationEntityIds": [],
                }
            )
    return actions


def _extract_tone_hints(prefix: str) -> list[str]:
    hints: list[str] = []
    mapping = {
        "低声": "quiet",
        "小声": "quiet",
        "大喊": "shout",
        "喊": "shout",
        "笑": "warm",
        "冷冷": "cold",
        "颤抖": "fearful",
        "犹豫": "hesitant",
    }
    tail = prefix[-16:]
    for keyword, hint in mapping.items():
        if keyword in tail and hint not in hints:
            hints.append(hint)
    return hints


INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "investigate": ("调查", "检查", "搜索", "搜查", "inspect", "investigate", "search"),
    "question": ("询问", "问", "为什么", "吗", "?", "？", "question", "ask"),
    "protect": ("保护", "挡住", "守住", "护住", "protect"),
    "escape": ("逃", "离开", "撤退", "逃跑", "escape"),
    "delay": ("拖延", "等待时机", "delay"),
    "conceal": ("隐藏", "隐瞒", "藏起", "掩饰", "conceal", "hide"),
    "confront": ("质问", "对峙", "逼近", "confront"),
    "use_item": ("使用", "拿出", "握紧", "举起", "打开", "use"),
    "move": ("走向", "靠近", "进入", "退后", "穿过", "move"),
    "observe": ("观察", "看向", "凝视", "望向", "observe", "look"),
    "wait": ("等", "等待", "wait"),
}


def _extract_intents(raw_text: str) -> list[dict[str, Any]]:
    lowered = raw_text.lower()
    intents: list[dict[str, Any]] = []
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            intents.append({"type": intent, "targetEntityIds": []})
    return intents


def _extract_mentions(raw_text: str, known_entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mentions: list[dict[str, Any]] = []
    lowered = raw_text.lower()
    for entity in known_entities:
        names = [entity.get("name", ""), *entity.get("aliases", [])]
        matched_name = ""
        for name in names:
            name_text = str(name).strip()
            if name_text and name_text.lower() in lowered:
                matched_name = name_text
                break
        if not matched_name:
            continue
        mentions.append(
            {
                "text": matched_name,
                "entityId": entity.get("entityId"),
                "entryId": entity.get("entryId"),
                "category": entity.get("category", "character"),
                "confidence": 0.95,
                "evidence": f'matched literal "{matched_name}"',
            }
        )
    return _dedupe_dicts(mentions, "text")


def parse_rp_input(raw_text: str, known_entities: Any = None) -> dict[str, Any]:
    """Parse player input into the original project's ParsedRpInputV1 shape."""
    text = str(raw_text or "")
    entities = _normalize_entities(known_entities)
    warnings: list[str] = []
    if not text.strip():
        warnings.append("Input is empty")

    parsed = {
        "version": "parsed-rp-input-v1",
        "rawText": text,
        "mentions": _extract_mentions(text, entities),
        "references": [],
        "dialogues": _extract_dialogues(text),
        "actions": _extract_actions(text),
        "intents": _extract_intents(text),
        "historicalReferences": [],
        "relationshipSignals": [],
        "unresolvedReferences": [],
        "diagnostics": {
            "parserMode": "regex-fallback",
            "parseAttempts": 0,
            "removedInvalidEntityIds": [],
            "removedInvalidEntryIds": [],
            "warnings": warnings,
        },
    }
    return parsed


def _normalize_list_context(value: Any, item_name: str) -> list[dict[str, Any]]:
    data = safe_json_loads(value, [])
    if isinstance(data, dict):
        for key in ("entries", "hits", "records", "memories", "items", item_name):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        return []

    out: list[dict[str, Any]] = []
    for idx, item in enumerate(data):
        if isinstance(item, str):
            out.append({"id": f"{item_name}-{idx + 1}", "content": item})
            continue
        if not isinstance(item, dict):
            continue
        content = item.get("content") or item.get("text") or item.get("summary") or ""
        if not content and item.get("entry") and isinstance(item["entry"], dict):
            entry = item["entry"]
            content = entry.get("content") or entry.get("text") or ""
            item = {**entry, **item}
        out.append(
            {
                "id": str(item.get("id") or item.get("record_id") or f"{item_name}-{idx + 1}"),
                "title": item.get("title"),
                "content": str(content),
                "tags": item.get("tags", []),
                "score": item.get("score"),
                "priority": item.get("priority"),
                "metadata": item.get("metadata", {}),
            }
        )
    return out


def _render_object(title: str, data: Any) -> str:
    if data in ({}, [], None, ""):
        return ""
    if isinstance(data, str):
        return f"[{title}]\n{data}"
    return f"[{title}]\n{json_dumps(data)}"


def _render_entries(title: str, entries: list[dict[str, Any]], max_entries: int = 8) -> str:
    if not entries:
        return ""
    lines = [f"[{title}]"]
    for entry in entries[:max_entries]:
        label = entry.get("title") or entry.get("id") or "Untitled"
        line = f"- {label}"
        if entry.get("id"):
            line += f" (id={entry['id']})"
        if entry.get("score") is not None:
            line += f" score={entry['score']}"
        lines.append(line)
        if entry.get("content"):
            lines.append(f"  {truncate_text(str(entry['content']), 600)}")
    return "\n".join(lines)


def _section(id_: str, title: str, content: str, source: str, priority: int, trust: str) -> dict[str, Any]:
    return {
        "id": id_,
        "title": title,
        "source": source,
        "content": content,
        "priority": priority,
        "visibility": "model_visible",
        "trust": trust,
    }


def _render_prompt_section(section: dict[str, Any]) -> str:
    return f"## {section['title']}\n\n{section['content']}"


def build_context_bundle(
    parsed_input: Any,
    character_profile_json: Any = "",
    scene_state_json: Any = "",
    worldbook_context_json: Any = "",
    memory_context_json: Any = "",
    preset_sections_json: Any = "",
    target_tokens: int = 3000,
) -> dict[str, Any]:
    """Assemble structured RP context and a compiled Markdown prompt."""
    parsed = safe_json_loads(parsed_input, parsed_input)
    if not isinstance(parsed, dict):
        parsed = parse_rp_input(str(parsed_input or ""))

    character_profile = safe_json_loads(character_profile_json, {})
    scene_state = safe_json_loads(scene_state_json, {})
    worldbook_entries = _normalize_list_context(worldbook_context_json, "worldbook")
    memory_entries = _normalize_list_context(memory_context_json, "memory")
    preset_sections = safe_json_loads(preset_sections_json, [])
    if not isinstance(preset_sections, list):
        preset_sections = []

    section_map: dict[str, str] = {
        "rawUserInputSection": f"[Raw User Input]\n{parsed.get('rawText', '')}",
    }

    if parsed.get("mentions"):
        section_map["mentionsSection"] = _render_object("Mentions", parsed["mentions"])
    if parsed.get("dialogues"):
        lines = ["[Dialogues]"]
        for dialogue in parsed["dialogues"]:
            lines.append(f"- {dialogue.get('speakerEntityId', 'player')}: \"{dialogue.get('text', '')}\"")
        section_map["dialoguesSection"] = "\n".join(lines)
    if parsed.get("actions"):
        lines = ["[Actions]"]
        for action in parsed["actions"]:
            lines.append(f"- {action.get('actorEntityId', 'player')} {action.get('action', '')}")
        section_map["actionsSection"] = "\n".join(lines)
    if parsed.get("intents"):
        section_map["intentsSection"] = _render_object("Intents", parsed["intents"])

    profile_text = _render_object("Character Profile", character_profile)
    if profile_text:
        section_map["characterProfileSection"] = profile_text

    scene_text = _render_object("Current Scene State", scene_state)
    if scene_text:
        section_map["sceneStateSection"] = scene_text

    worldbook_text = _render_entries("Worldbook Context", worldbook_entries)
    if worldbook_text:
        section_map["worldbookSection"] = worldbook_text

    memory_text = _render_entries("Recalled Memories", memory_entries)
    if memory_text:
        section_map["memorySection"] = memory_text

    preset_text = "\n".join(
        f"- {item.get('content', '')}" for item in sorted(preset_sections, key=lambda x: x.get("priority", 0), reverse=True)
        if isinstance(item, dict) and item.get("content")
    )
    if preset_text:
        section_map["presetRulesSection"] = f"[Preset Rules]\n{preset_text}"

    descriptors = [
        ("presetRulesSection", "Preset Rules", "preset", 100, "system"),
        ("rawUserInputSection", "User Input (raw)", "user_input", 99, "user_content"),
        ("dialoguesSection", "Parsed Dialogues", "user_input", 92, "user_content"),
        ("actionsSection", "Parsed Actions", "user_input", 92, "user_content"),
        ("mentionsSection", "Parsed Mentions", "user_input", 90, "user_content"),
        ("intentsSection", "Parsed Intents", "user_input", 86, "user_content"),
        ("characterProfileSection", "Character Profile", "character_profile", 82, "world_data"),
        ("sceneStateSection", "Current Scene State", "state", 75, "world_data"),
        ("worldbookSection", "Worldbook Context", "worldbook", 65, "world_data"),
        ("memorySection", "Recalled Memories", "memory", 45, "world_data"),
    ]

    sections: list[dict[str, Any]] = []
    for id_, title, source, priority, trust in descriptors:
        content = section_map.get(id_)
        if content:
            sections.append(_section(id_, title, content, source, priority, trust))

    prompt_parts = [_render_prompt_section(section) for section in sections]
    prompt = "\n\n".join(prompt_parts)
    actual_tokens = estimate_tokens(prompt)
    warnings: list[str] = []
    if target_tokens > 0 and actual_tokens > target_tokens:
        warnings.append(f"Estimated tokens {actual_tokens} exceed target {target_tokens}")

    return {
        "version": RP_CONTEXT_VERSION,
        "sections": {section["id"]: section["content"] for section in sections},
        "promptDocument": {
            "version": "prompt-document-v1",
            "target": "writer",
            "sections": sections,
        },
        "prompt": prompt,
        "usedContext": {
            "usedWorldbookEntries": worldbook_entries,
            "recalledMemories": memory_entries,
            "usedSceneState": scene_state,
            "characterProfile": character_profile,
        },
        "budgetReport": {
            "targetTokens": target_tokens,
            "actualTokens": actual_tokens,
            "warnings": warnings,
        },
        "debug": {
            "parserFieldsCovered": [
                key
                for key in (
                    "rawText",
                    "mentions",
                    "dialogues",
                    "actions",
                    "intents",
                    "historicalReferences",
                    "relationshipSignals",
                    "unresolvedReferences",
                )
                if parsed.get(key)
            ],
            "sectionIds": [section["id"] for section in sections],
        },
    }


def render_writer_contract_state(contract: dict[str, Any]) -> str:
    """Render a WriterContract dict into a short, stable, writer-facing prompt section.

    This is NOT raw JSON injection. It produces a structured markdown section
    that tells the writer what is immutably true this turn:
    - cast / user identity / relationships
    - scene location and time
    - active stage and events
    - forbidden moves
    - output length requirements
    """
    if not isinstance(contract, dict) or not contract.get("schemaId"):
        return ""

    lines: list[str] = ["## 当前不可违背状态"]

    # ── Cast ──
    cast = contract.get("cast", {})
    if isinstance(cast, dict):
        locked = cast.get("lockedCharacters", [])
        if locked:
            names = []
            for c in locked:
                if isinstance(c, dict):
                    name = c.get("name", "")
                    role = c.get("role", "")
                    names.append(f"{name}({role})" if role else name)
            if names:
                lines.append(f"- 核心角色：{'、'.join(names)}")

        user_id = cast.get("userIdentity", {})
        if isinstance(user_id, dict) and user_id.get("name"):
            lines.append(f"- 用户身份：{user_id['name']}")

        bindings = cast.get("relationshipBindings", [])
        if bindings:
            rels = []
            for b in bindings:
                if isinstance(b, dict):
                    src = b.get("source", "")
                    tgt = b.get("target", "")
                    rtype = b.get("type", "")
                    if src and tgt:
                        rels.append(f"{src}→{tgt}({rtype})" if rtype else f"{src}→{tgt}")
            if rels:
                lines.append(f"- 身份/关系：{'、'.join(rels)}")

    # ── Scene ──
    scene = contract.get("scene", {})
    if isinstance(scene, dict):
        loc = scene.get("location", "")
        time = scene.get("time", "")
        chars = scene.get("activeCharacterIds", [])
        if loc:
            lines.append(f"- 当前地点：{loc}")
        if time:
            lines.append(f"- 当前时间：{time}")
        if chars:
            lines.append(f"- 在场人物：{'、'.join(str(c) for c in chars)}")

    # ── State: stages, events, forbidden ──
    state = contract.get("state", {})
    if isinstance(state, dict):
        stages = state.get("activeStageIds", [])
        if stages:
            lines.append(f"- 当前阶段：{'、'.join(stages)}")
        events = state.get("eligibleEventIds", [])
        if events:
            lines.append(f"- 已激活事件：{'、'.join(events)}")
        forbidden = state.get("forbiddenStageMoves", [])
        if forbidden:
            lines.append(f"- 禁止阶段转移：{'、'.join(forbidden)}")

    # ── Output requirements ──
    output_req = contract.get("outputRequirements", {})
    if isinstance(output_req, dict):
        min_chars = output_req.get("minBodyChars", 0)
        if min_chars > 0:
            lines.append(f"- 正文要求：不少于 {min_chars} 中文字符，<options> 块不计入正文")

    # Only return if we have content beyond the header
    if len(lines) <= 1:
        return ""

    return "\n".join(lines)


def build_director_prompt(
    context_bundle: Any,
    system_prompt: str = "",
    preset_sections_json: Any = "",
    reply_rules: str = "",
    writer_contract_json: Any = "",
) -> str:
    bundle = safe_json_loads(context_bundle, {})
    if not isinstance(bundle, dict):
        bundle = {}
    base_prompt = str(bundle.get("prompt", ""))
    preset_sections = safe_json_loads(preset_sections_json, [])
    preset_text = ""
    if isinstance(preset_sections, list):
        preset_text = "\n".join(
            f"- {section.get('content')}" for section in preset_sections
            if isinstance(section, dict) and section.get("content")
        )

    # P4D-1A: Render writer contract as structured state section
    contract = safe_json_loads(writer_contract_json, {})
    contract_section = render_writer_contract_state(contract)

    parts = [
        system_prompt.strip(),
        "你是互动 RP 写手。只输出玩家可见的角色表演内容，不输出 JSON、状态栏、分析或调试信息。",
        "硬性边界：不要替玩家决定行动、台词、心理结论；不要泄露角色不可知道的信息；不要自动提交记忆或状态。",
    ]
    if preset_text:
        parts.append(f"## Resolved Preset Rules\n{preset_text}")
    # Contract state section goes BEFORE base_prompt (near generation point)
    if contract_section:
        parts.append(contract_section)
    if base_prompt:
        parts.append(base_prompt)
    if reply_rules.strip():
        parts.append(f"## Turn Reply Rules\n{reply_rules.strip()}")
    parts.append("请基于以上上下文续写本回合。")
    return "\n\n".join(part for part in parts if part)


def apply_context_mode(context_bundle: Any, context_mode: str) -> dict[str, Any]:
    """Return a context bundle filtered for an agent memory/context mode.

    Modes:
    - full_context: keep character, scene, worldbook, memory, and current input.
    - no_memory: keep current input, character, scene, worldbook; drop memories.
    - stateless_no_context: keep only current player input and parsed input.
    """
    bundle = safe_json_loads(context_bundle, {})
    if not isinstance(bundle, dict):
        return {}

    mode = context_mode or "full_context"
    if mode == "full_context":
        return bundle

    sections = dict(bundle.get("sections", {}) if isinstance(bundle.get("sections"), dict) else {})
    prompt_document = dict(bundle.get("promptDocument", {}) if isinstance(bundle.get("promptDocument"), dict) else {})
    document_sections = list(prompt_document.get("sections", []) if isinstance(prompt_document.get("sections"), list) else [])
    used_context = dict(bundle.get("usedContext", {}) if isinstance(bundle.get("usedContext"), dict) else {})

    if mode == "no_memory":
        drop_ids = {"memorySection", "recentMessagesSection"}
        used_context["recalledMemories"] = []
    elif mode == "stateless_no_context":
        keep_ids = {
            "presetRulesSection",
            "rawUserInputSection",
            "dialoguesSection",
            "actionsSection",
            "mentionsSection",
            "intentsSection",
        }
        drop_ids = set(sections.keys()) - keep_ids
        used_context = {
            "usedWorldbookEntries": [],
            "recalledMemories": [],
            "usedSceneState": {},
            "characterProfile": {},
        }
    else:
        drop_ids = set()

    for section_id in drop_ids:
        sections.pop(section_id, None)

    prompt_sections = [
        section
        for section in document_sections
        if isinstance(section, dict) and section.get("id") not in drop_ids
    ]
    prompt_document["sections"] = prompt_sections
    prompt = "\n\n".join(_render_prompt_section(section) for section in prompt_sections)

    filtered = dict(bundle)
    filtered["sections"] = sections
    filtered["promptDocument"] = prompt_document
    filtered["prompt"] = prompt
    filtered["usedContext"] = used_context
    filtered["contextMode"] = mode
    filtered["budgetReport"] = {
        **(bundle.get("budgetReport", {}) if isinstance(bundle.get("budgetReport"), dict) else {}),
        "actualTokens": estimate_tokens(prompt),
    }
    return filtered


def _make_memory_candidate(session_id: str, reply: str, character_id: str = "") -> dict[str, Any]:
    kind = "event"
    tags = ["rp-turn"]
    if any(word in reply for word in ("约定", "答应", "承诺", "发誓", "记住")):
        kind = "commitment"
        tags.append("commitment")
    elif any(word in reply for word in ("发现", "揭示", "得知")):
        kind = "discovery"
        tags.append("discovery")
    elif any(word in reply for word in ("关系", "信任", "怀疑", "敌意")):
        kind = "relationship-change"
        tags.append("relationship")

    entity_ids = [character_id] if character_id else ["player"]
    return {
        "kind": kind,
        "summary": truncate_text(reply, 180),
        "entityIds": entity_ids,
        "tags": tags,
        "importance": 0.55 if kind == "event" else 0.7,
        "confidence": 0.65,
        "evidence": truncate_text(reply, 120),
        "sessionId": session_id,
    }


def propose_turn_patches(
    session_id: str,
    parsed_input: Any,
    reply: str,
    character_id: str = "",
    scene_id: str = "",
) -> dict[str, Any]:
    """Build pending state/memory patch proposals without writing storage."""
    parsed = safe_json_loads(parsed_input, parsed_input)
    if not isinstance(parsed, dict):
        parsed = parse_rp_input(str(parsed_input or ""))

    now = utc_now_iso()
    raw_input = str(parsed.get("rawText", ""))
    reply_text = str(reply or "")
    memory_candidates: list[dict[str, Any]] = []
    if reply_text.strip():
        memory_candidates.append(_make_memory_candidate(session_id, reply_text, character_id))

    state_operations = [
        {
            "op": "set",
            "path": "/lastTurn/playerInput",
            "value": truncate_text(raw_input, 300),
        },
        {
            "op": "set",
            "path": "/lastTurn/assistantReply",
            "value": truncate_text(reply_text, 300),
        },
    ]
    if scene_id:
        state_operations.append({"op": "set", "path": "/activeSceneId", "value": scene_id})
    if character_id:
        state_operations.append({"op": "add", "path": "/activeCharacterIds/-", "value": character_id})

    candidate_state_patch = {
        "schemaId": "awp.rp-candidate-state-patch.v1",
        "sessionId": session_id,
        "sceneId": scene_id or None,
        "commitPolicy": "pending",
        "autoCommit": False,
        "operations": state_operations,
        "createdAt": now,
        "source": "AWPPatchProposal",
        "warnings": ["Candidate only. Review before formal state commit."],
    }
    candidate_memory_patch = {
        "schemaId": "awp.rp-candidate-memory-patch.v1",
        "sessionId": session_id,
        "commitPolicy": "pending",
        "autoCommit": False,
        "candidates": memory_candidates,
        "createdAt": now,
        "source": "AWPPatchProposal",
        "warnings": ["Candidate only. Do not connect directly to AWPMemoryWrite without review."],
    }
    return {
        "candidateStatePatch": candidate_state_patch,
        "candidateMemoryPatch": candidate_memory_patch,
        "debug": {
            "parsedDialogues": len(parsed.get("dialogues", [])),
            "parsedActions": len(parsed.get("actions", [])),
            "candidateMemoryCount": len(memory_candidates),
        },
    }


FORBIDDEN_FORMAT_PATTERNS = ("```json", "```yaml", "<analysis>", "思考过程", "[Status:", "debugLog")
PLAYER_AGENCY_PATTERNS = (
    "你决定",
    "你选择",
    "你转身",
    "你拿起",
    "你说：",
    "你回答",
    "你意识到",
    "你心想",
)
KNOWLEDGE_LEAK_PATTERNS = ("系统提示", "开发者指令", "worldbook", "runtime", "metadata", "候选补丁")

# === Expanded hard gates (from oh-story-claudecode + webnovel-writer) ===

# 禁用全知修饰词 — 来自 oh-story-claudecode 硬性门禁
OMNISCIENT_ADVERB_PATTERNS = (
    "不自觉地", "下意识地", "不由自主地", "情不自禁",
    "鬼使神差", "微不可察", "极力掩饰", "不易察觉",
)

# 禁用八股微表情 — 来自 oh-story-claudecode 硬性门禁
CLICHE_MICRO_PATTERNS = (
    "瞳孔微缩", "瞳孔一缩", "喉结滚动", "睫毛颤动",
    "睫毛微颤", "呼吸一滞", "身体一僵", "指节泛白",
)

# 禁用临床/学术语言 — 来自 oh-story-claudecode 硬性门禁
CLINICAL_LANGUAGE_PATTERNS = (
    "博弈", "操控", "主导", "试探", "攻防",
    "拿捏", "接管", "打压", "争夺",
)

# 禁用极端标签化情感词 — 来自 oh-story-claudecode 硬性门禁
EXTREME_EMOTION_PATTERNS = (
    "崩溃", "绝望", "沦陷", "虔诚", "崇拜",
    "臣服", "支配", "征服", "占有", "驯化",
    "猎物", "玩物", "祭品", "共犯",
)

# AI 写作癖好 — 来自 webnovel-writer anti-ai-guide
AI_WRITING_PATTERNS = (
    "深深吸了一口气", "深吸一口气", "眸中闪过一丝",
    "心中暗道", "心中暗想", "心中涌起", "一时间",
    "不知不觉", "不知过了多久", "不知何时", "不知为何",
    "也许这就是", "或许这就是", "一瞬间", "在这一刻",
)

# 网文套话 — 句式禁止
FORBIDDEN_PHRASE_PATTERNS = (
    "不容", "最后一根稻草",
)


def apply_quality_gate(reply: str, review: Any = None) -> dict[str, Any]:
    """Deterministic quality gate for ComfyUI workflows.
    
    Checks span 6 dimensions now:
    - styleAndFormat (format violations, AI writing tells)
    - playerAgency (player control)
    - knowledgeBoundary (internal knowledge leaks)
    - proseStyle (omniscient adverbs, cliché micro-expressions, clinical language)
    - emotionTaste (extreme label emotions)
    - dialogueQuality (cliché phrases)
    """
    text = str(reply or "")
    issues: list[dict[str, Any]] = []
    scores = {
        "continuity": 0.9,
        "characterConsistency": 0.9,
        "playerAgency": 0.95,
        "knowledgeBoundary": 0.95,
        "styleAndFormat": 0.85,
        "proseStyle": 0.9,
        "emotionTaste": 0.9,
    }

    if not text.strip():
        issues.append(
            {
                "code": "format",
                "severity": "error",
                "message": "Reply is empty.",
                "suggestion": "Generate player-visible narrative text.",
            }
        )
        scores["styleAndFormat"] = 0.0

    if any(pattern in text for pattern in FORBIDDEN_FORMAT_PATTERNS):
        issues.append(
            {
                "code": "format",
                "severity": "error",
                "message": "Reply leaks JSON, status, or internal analysis formatting.",
                "suggestion": "Return narrative prose only.",
            }
        )
        scores["styleAndFormat"] = min(scores["styleAndFormat"], 0.2)

    if any(pattern in text for pattern in PLAYER_AGENCY_PATTERNS):
        issues.append(
            {
                "code": "player-agency",
                "severity": "error",
                "message": "Reply appears to control the player's action, speech, or private thoughts.",
                "suggestion": "Describe NPC/world reactions and leave player choices to the user.",
            }
        )
        scores["playerAgency"] = min(scores["playerAgency"], 0.2)

    lowered = text.lower()
    if any(pattern.lower() in lowered for pattern in KNOWLEDGE_LEAK_PATTERNS):
        issues.append(
            {
                "code": "knowledge-leak",
                "severity": "error",
                "message": "Reply exposes internal/runtime knowledge.",
                "suggestion": "Keep hidden context implicit and only show what characters can perceive.",
            }
        )
        scores["knowledgeBoundary"] = min(scores["knowledgeBoundary"], 0.2)

    # --- NEW: 全知修饰词检查 ---
    if any(pattern in text for pattern in OMNISCIENT_ADVERB_PATTERNS):
        issues.append(
            {
                "code": "omniscient-adverb",
                "severity": "warning",
                "message": "Reply uses omniscient-perspective adverbs (不自觉地/下意识地/鬼使神差 etc.).",
                "suggestion": "Remove the adverb and show the action directly; let readers judge.",
            }
        )
        scores["proseStyle"] = min(scores["proseStyle"], 0.4)

    # --- NEW: 八股微表情检查 ---
    if any(pattern in text for pattern in CLICHE_MICRO_PATTERNS):
        issues.append(
            {
                "code": "cliche-micro",
                "severity": "warning",
                "message": "Reply uses cliché micro-expressions (瞳孔微缩/喉结滚动/睫毛颤动 etc.).",
                "suggestion": "Replace with character-specific habitual gestures, or delete.",
            }
        )
        scores["proseStyle"] = min(scores["proseStyle"], 0.5)

    # --- NEW: 临床/学术语言检查 ---
    if any(pattern in text for pattern in CLINICAL_LANGUAGE_PATTERNS):
        issues.append(
            {
                "code": "clinical-language",
                "severity": "warning",
                "message": "Reply uses clinical/academic terms in emotional context (博弈/操控/试探 etc.).",
                "suggestion": "Replace with concrete behavioral verbs: 讨价还价/套话/斗嘴/哄/使绊子.",
            }
        )
        scores["emotionTaste"] = min(scores["emotionTaste"], 0.5)

    # --- NEW: 极端标签化情感词检查 ---
    if any(pattern in text for pattern in EXTREME_EMOTION_PATTERNS):
        issues.append(
            {
                "code": "extreme-emotion-label",
                "severity": "warning",
                "message": "Reply uses extreme label emotions (崩溃/沦陷/虔诚/臣服 etc.).",
                "suggestion": "Use plain emotion descriptors: 撑不住/陷进去/很在意/佩服/听他的/想要.",
            }
        )
        scores["emotionTaste"] = min(scores["emotionTaste"], 0.4)

    # --- NEW: AI 写作癖好检查 ---
    if any(pattern in text for pattern in AI_WRITING_PATTERNS):
        issues.append(
            {
                "code": "ai-writing-tell",
                "severity": "warning",
                "message": "Reply shows AI writing patterns (深吸一口气/眸中闪过一丝/心中暗道 etc.).",
                "suggestion": "Remove the cliché cue; use specific physical actions or imply emotion through behavior.",
            }
        )
        scores["styleAndFormat"] = min(scores["styleAndFormat"], 0.5)

    # --- NEW: 网文套话检查 ---
    if any(pattern in text for pattern in FORBIDDEN_PHRASE_PATTERNS):
        issues.append(
            {
                "code": "forbidden-phrase",
                "severity": "warning",
                "message": "Reply uses web-novel cliché phrases (不容XX/最后一根稻草 etc.).",
                "suggestion": "Rewrite with original phrasing; avoid template expressions.",
            }
        )
        scores["styleAndFormat"] = min(scores["styleAndFormat"], 0.6)

    review_data = safe_json_loads(review, None)
    if isinstance(review_data, dict) and isinstance(review_data.get("issues"), list):
        for issue in review_data["issues"]:
            if isinstance(issue, dict):
                issues.append(issue)

    failed_checks = sorted({str(issue.get("code", "other")) for issue in issues if issue.get("severity") == "error"})
    accepted = len(failed_checks) == 0
    return {
        "schemaId": "awp.rp-quality-gate.v2",
        "accepted": accepted,
        "decision": "accept" if accepted else "revise",
        "failedChecks": failed_checks,
        "scores": scores,
        "issues": issues,
        "revisionInstruction": None
        if accepted
        else "修订回复：只输出玩家可见叙事，不控制玩家，不泄露内部信息，并保持角色/世界连续性。",
    }


def build_side_effect_decision(
    quality_decision: Any,
    patches: Any = None,
    allow_commit_when_accepted: bool = False,
) -> dict[str, Any]:
    """Derive explicit side-effect permissions from gate and patch policy."""
    quality = safe_json_loads(quality_decision, quality_decision)
    if not isinstance(quality, dict):
        quality = {"accepted": False, "decision": "revise"}
    accepted = bool(quality.get("accepted"))

    patch_data = safe_json_loads(patches, patches)
    state_policy = "pending"
    memory_policy = "pending"
    if isinstance(patch_data, dict):
        state = patch_data.get("candidateStatePatch", patch_data)
        memory = patch_data.get("candidateMemoryPatch", patch_data)
        if isinstance(state, dict):
            state_policy = str(state.get("commitPolicy", "pending"))
        if isinstance(memory, dict):
            memory_policy = str(memory.get("commitPolicy", "pending"))

    allow_state = bool(accepted and allow_commit_when_accepted and state_policy == "auto")
    allow_memory = bool(accepted and allow_commit_when_accepted and memory_policy == "auto")
    return {
        "schemaId": "awp.rp-side-effect-decision.v1",
        "accepted": accepted,
        "allowPlayerOutput": accepted,
        "allowStateCommit": allow_state,
        "allowMemoryCommit": allow_memory,
        "allowWorldbookCommit": False,
        "reason": "accepted-pending-review" if accepted else "quality-gate-revise",
        "commitPolicies": {
            "state": state_policy,
            "memory": memory_policy,
        },
    }


def render_final_output(
    reply: str,
    context_bundle: Any = None,
    candidate_state_patch: Any = None,
    candidate_memory_patch: Any = None,
    quality_decision: Any = None,
    side_effect_decision: Any = None,
) -> dict[str, Any]:
    """Compose the stable final output object used by workflow samples."""
    bundle = safe_json_loads(context_bundle, {})
    state_patch = safe_json_loads(candidate_state_patch, candidate_state_patch or {})
    memory_patch = safe_json_loads(candidate_memory_patch, candidate_memory_patch or {})
    quality = safe_json_loads(quality_decision, quality_decision or apply_quality_gate(reply))
    side_effects = safe_json_loads(
        side_effect_decision,
        side_effect_decision or build_side_effect_decision(quality, {}),
    )
    if not isinstance(bundle, dict):
        bundle = {}

    used_context = bundle.get("usedContext", {}) if isinstance(bundle.get("usedContext"), dict) else {}
    debug_log = [
        {
            "node": "AWPOutputRenderer",
            "message": "Rendered final RP output with pending candidate patches.",
            "at": utc_now_iso(),
        },
        {
            "node": "AWPQualityGate",
            "message": f"decision={quality.get('decision', 'unknown')}",
            "failedChecks": quality.get("failedChecks", []),
        },
    ]

    return {
        "schemaId": FINAL_OUTPUT_VERSION,
        "narrative": str(reply or ""),
        "quality": quality,
        "candidateStatePatch": state_patch,
        "candidateMemoryPatch": memory_patch,
        "sideEffectDecision": side_effects,
        "usedWorldbookEntries": used_context.get("usedWorldbookEntries", []),
        "recalledMemories": used_context.get("recalledMemories", []),
        "usedSceneState": used_context.get("usedSceneState", {}),
        "debugLog": debug_log,
    }
