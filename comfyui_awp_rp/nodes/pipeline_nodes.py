"""ComfyUI-native RP pipeline nodes."""

import json

from ..core.config import get_config
from ..core.llm_router import create_default_router
from ..profile.profile import ProfileManager
from ..preset.preset import PresetManager
from ..rp_pipeline import (
    apply_quality_gate,
    apply_context_mode,
    build_context_bundle,
    build_director_prompt,
    build_side_effect_decision,
    json_dumps,
    parse_rp_input,
    propose_turn_patches,
    render_final_output,
    safe_json_loads,
)


def _provider_choices() -> list[str]:
    config = get_config()
    providers = list(config.providers.keys())
    return providers or ["deepseek"]


def _profile_choices() -> list[str]:
    profiles = [item["id"] for item in ProfileManager().list_profiles()]
    return profiles or ["rp-writer"]


def _preset_choices() -> list[str]:
    presets = [item["id"] for item in PresetManager().list_presets()]
    return presets or ["rp-default-v1"]


class AWPInputParser:
    """解析原始 RP 玩家输入为结构化字段。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "user_input": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "placeholder": "玩家本轮输入、动作或台词...",
                        "forceInput": True,
                    },
                ),
            },
            "optional": {
                "known_entities_json": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "[]",
                        "placeholder": "可选实体候选 JSON，用于解析提及。",
                        "forceInput": True,
                    },
                ),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("解析结果JSON", "调试")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/管线"

    def execute(self, user_input: str, known_entities_json: str = "[]"):
        parsed = parse_rp_input(user_input, known_entities_json)
        debug = {
            "parserMode": parsed["diagnostics"]["parserMode"],
            "mentions": len(parsed["mentions"]),
            "dialogues": len(parsed["dialogues"]),
            "actions": len(parsed["actions"]),
            "intents": [item["type"] for item in parsed["intents"]],
        }
        return (json_dumps(parsed), json_dumps(debug))


class AWPContextAssembler:
    """将角色、场景、世界观、记忆和预设组装为模型上下文。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "parsed_input_json": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "{}",
                        "placeholder": "AWPInputParser 输出",
                        "forceInput": True,
                    },
                ),
            },
            "optional": {
                "character_profile_json": ("STRING", {"multiline": True, "default": "{}", "forceInput": True}),
                "scene_state_json": ("STRING", {"multiline": True, "default": "{}", "forceInput": True}),
                "worldbook_context_json": ("STRING", {"multiline": True, "default": "[]", "forceInput": True}),
                "memory_context_json": ("STRING", {"multiline": True, "default": "[]", "forceInput": True}),
                "preset_sections_json": ("STRING", {"multiline": True, "default": "[]", "forceInput": True}),
                "target_tokens": ("INT", {"default": 3000, "min": 500, "max": 16000}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("上下文提示词", "上下文包JSON", "调试")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/管线"

    def execute(
        self,
        parsed_input_json: str,
        character_profile_json: str = "{}",
        scene_state_json: str = "{}",
        worldbook_context_json: str = "[]",
        memory_context_json: str = "[]",
        preset_sections_json: str = "[]",
        target_tokens: int = 3000,
    ):
        bundle = build_context_bundle(
            parsed_input_json,
            character_profile_json=character_profile_json,
            scene_state_json=scene_state_json,
            worldbook_context_json=worldbook_context_json,
            memory_context_json=memory_context_json,
            preset_sections_json=preset_sections_json,
            target_tokens=target_tokens,
        )
        return (bundle["prompt"], json_dumps(bundle), json_dumps(bundle["debug"]))


class AWPDialogueDirector:
    """根据组装上下文生成玩家可见的 RP 回复。"""

    @classmethod
    def INPUT_TYPES(cls):
        providers = _provider_choices()
        profiles = _profile_choices()
        presets = _preset_choices()
        return {
            "required": {
                "context_bundle_json": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "{}",
                        "placeholder": "AWPContextAssembler 输出",
                        "forceInput": True,
                    },
                ),
                "session_id": ("STRING", {"default": "default", "forceInput": True}),
            },
            "optional": {
                "provider": (providers, {"default": providers[0]}),
                "model": ("STRING", {"default": ""}),
                "profile": (profiles, {"default": "rp-writer" if "rp-writer" in profiles else profiles[0]}),
                "preset_id": (presets, {"default": "rp-default-v1" if "rp-default-v1" in presets else presets[0]}),
                "context_mode": (
                    ["full_context", "no_memory", "stateless_no_context"],
                    {"default": "full_context"},
                ),
                "reply_rules": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "长度适中；自然停在玩家可继续行动的位置。",
                    },
                ),
                "temperature": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.05}),
                "max_tokens": ("INT", {"default": 2048, "min": 128, "max": 8192}),
                "dry_run": ("BOOLEAN", {"default": False}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("回复", "候选状态补丁", "候选记忆补丁", "元数据")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/管线"
    OUTPUT_NODE = True

    def execute(
        self,
        context_bundle_json: str,
        session_id: str,
        provider: str = "deepseek",
        model: str = "",
        profile: str = "rp-writer",
        preset_id: str = "rp-default-v1",
        context_mode: str = "full_context",
        reply_rules: str = "长度适中；自然停在玩家可继续行动的位置。",
        temperature: float = 0.8,
        max_tokens: int = 2048,
        dry_run: bool = False,
    ):
        profile_manager = ProfileManager()
        agent_profile = profile_manager.get_profile(profile)
        if not agent_profile:
            metadata = {"error": "profile_not_found", "profile": profile}
            return ("", "{}", "{}", json_dumps(metadata))

        preset_manager = PresetManager()
        resolved_preset = preset_manager.resolve_preset(preset_id)
        preset_sections = resolved_preset.prompt_sections if resolved_preset else []
        model_config = dict(resolved_preset.model_config) if resolved_preset else {}

        filtered_bundle = apply_context_mode(context_bundle_json, context_mode)

        prompt = build_director_prompt(
            filtered_bundle,
            system_prompt=agent_profile.foundational_system_prompt,
            preset_sections_json=preset_sections,
            reply_rules=reply_rules,
        )

        config = get_config()
        provider_config = config.providers.get(provider)
        resolved_model = model or model_config.get("model") or (provider_config.default_model if provider_config else "")
        reply = ""
        metadata = {
            "provider": provider,
            "model": resolved_model,
            "profile": profile,
            "preset_id": preset_id,
            "context_mode": context_mode,
            "dry_run": dry_run,
            "prompt_tokens_estimated": len(prompt) // 4,
        }

        if dry_run:
            reply = "[DRY RUN] " + prompt[-1200:]
        elif not provider_config or not provider_config.api_key:
            metadata["error"] = "provider_not_configured"
            reply = (
                "LLM provider is not configured. Set DEEPSEEK_API_KEY/RP_MODEL or configure "
                "comfyui_awp_rp/data/config.json."
            )
        else:
            node_config = {
                "provider": provider,
                "model": resolved_model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            try:
                text, usage, resolved_provider, resolved_model = create_default_router().complete_with_config(
                    node_config=node_config,
                    workflow_defaults=model_config,
                    prompt=prompt,
                )
                reply = text
                metadata.update(
                    {
                        "provider": resolved_provider,
                        "model": resolved_model,
                        "token_usage": {"input": usage.input, "output": usage.output},
                    }
                )
            except Exception as exc:
                metadata["error"] = str(exc)
                reply = f"LLM Error: {exc}"

        bundle = filtered_bundle
        parsed = {}
        if isinstance(bundle, dict):
            raw_section = bundle.get("sections", {}).get("rawUserInputSection", "")
            parsed = {"rawText": raw_section.replace("[Raw User Input]\n", "", 1)}
        patches = propose_turn_patches(session_id, parsed, reply)
        return (
            reply,
            json_dumps(patches["candidateStatePatch"]),
            json_dumps(patches["candidateMemoryPatch"]),
            json_dumps(metadata),
        )


class AWPQualityGate:
    """RP 回复的确定性质量门禁。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "reply": ("STRING", {"multiline": True, "default": "", "forceInput": True}),
            },
            "optional": {
                "critic_review_json": ("STRING", {"multiline": True, "default": "", "forceInput": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("决策JSON", "状态", "修订指令")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/管线"

    def execute(self, reply: str, critic_review_json: str = ""):
        decision = apply_quality_gate(reply, critic_review_json)
        status = "accept" if decision["accepted"] else "revise"
        return (json_dumps(decision), status, decision.get("revisionInstruction") or "")


class AWPPatchProposal:
    """创建待审核的记忆/状态补丁。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "session_id": ("STRING", {"default": "default", "forceInput": True}),
                "parsed_input_json": ("STRING", {"multiline": True, "default": "{}", "forceInput": True}),
                "reply": ("STRING", {"multiline": True, "default": "", "forceInput": True}),
            },
            "optional": {
                "character_id": ("STRING", {"default": ""}),
                "scene_id": ("STRING", {"default": ""}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("候选状态补丁", "候选记忆补丁", "调试")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/管线"

    def execute(
        self,
        session_id: str,
        parsed_input_json: str,
        reply: str,
        character_id: str = "",
        scene_id: str = "",
    ):
        patches = propose_turn_patches(session_id, parsed_input_json, reply, character_id, scene_id)
        return (
            json_dumps(patches["candidateStatePatch"]),
            json_dumps(patches["candidateMemoryPatch"]),
            json_dumps(patches["debug"]),
        )


class AWPSideEffectDecision:
    """将副作用权限暴露为显式工作流对象。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "quality_decision_json": ("STRING", {"multiline": True, "default": "{}", "forceInput": True}),
            },
            "optional": {
                "candidate_state_patch": ("STRING", {"multiline": True, "default": "{}", "forceInput": True}),
                "candidate_memory_patch": ("STRING", {"multiline": True, "default": "{}", "forceInput": True}),
                "allow_commit_when_accepted": ("BOOLEAN", {"default": False}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("决策JSON", "状态")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/管线"

    def execute(
        self,
        quality_decision_json: str,
        candidate_state_patch: str = "{}",
        candidate_memory_patch: str = "{}",
        allow_commit_when_accepted: bool = False,
    ):
        patches = {
            "candidateStatePatch": safe_json_loads(candidate_state_patch, {}),
            "candidateMemoryPatch": safe_json_loads(candidate_memory_patch, {}),
        }
        decision = build_side_effect_decision(
            quality_decision_json,
            patches,
            allow_commit_when_accepted=allow_commit_when_accepted,
        )
        status = "output_allowed" if decision["allowPlayerOutput"] else "blocked"
        return (json_dumps(decision), status)


class AWPOutputRenderer:
    """组合最终玩家回复，附带隐藏诊断信息和待处理补丁。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "reply": ("STRING", {"multiline": True, "default": "", "forceInput": True}),
            },
            "optional": {
                "context_bundle_json": ("STRING", {"multiline": True, "default": "{}", "forceInput": True}),
                "candidate_state_patch": ("STRING", {"multiline": True, "default": "{}", "forceInput": True}),
                "candidate_memory_patch": ("STRING", {"multiline": True, "default": "{}", "forceInput": True}),
                "quality_decision_json": ("STRING", {"multiline": True, "default": "{}", "forceInput": True}),
                "side_effect_decision_json": ("STRING", {"multiline": True, "default": "{}", "forceInput": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("最终回复", "最终输出JSON", "调试日志")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/管线"
    OUTPUT_NODE = True

    def execute(
        self,
        reply: str,
        context_bundle_json: str = "{}",
        candidate_state_patch: str = "{}",
        candidate_memory_patch: str = "{}",
        quality_decision_json: str = "{}",
        side_effect_decision_json: str = "{}",
    ):
        final_output = render_final_output(
            reply=reply,
            context_bundle=context_bundle_json,
            candidate_state_patch=candidate_state_patch,
            candidate_memory_patch=candidate_memory_patch,
            quality_decision=quality_decision_json or apply_quality_gate(reply),
            side_effect_decision=side_effect_decision_json,
        )
        return (
            final_output["narrative"],
            json_dumps(final_output),
            json_dumps(final_output["debugLog"]),
        )


class AWPRoundPreparer:
    """回合前机械准备：世界书匹配 + 记忆召回 + 变量清单。

    自动执行 oh-story-claudecode 中 round_prepare.py 所做的机械上下文组装。
    接收原始用户输入、当前变量状态、世界书索引和记忆存储，
    产出可直接送入 MainAgent 的组装上下文包。

    AI 不再需要手动查询世界书/记忆 —— 此节点为每轮预计算最相关的上下文。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "user_input": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "玩家本轮输入",
                    "forceInput": True,
                }),
                "session_id": ("STRING", {
                    "default": "default",
                    "forceInput": True,
                }),
            },
            "optional": {
                "current_variables": ("STRING", {
                    "multiline": True,
                    "default": "{}",
                    "placeholder": "当前变量状态 JSON（从上一轮 MVU 输出）",
                    "forceInput": True,
                }),
                "worldbook_index": ("STRING", {
                    "multiline": True,
                    "default": "[]",
                    "placeholder": "世界书索引 JSON",
                    "forceInput": True,
                }),
                "memory_context": ("STRING", {
                    "multiline": True,
                    "default": "[]",
                    "placeholder": "近期记忆 JSON",
                    "forceInput": True,
                }),
                "var_diff": ("STRING", {
                    "multiline": True,
                    "default": "{}",
                    "placeholder": "上轮变量变更 JSON（从 MVU audit 输出）",
                    "forceInput": True,
                }),
                # --- P6.3: Author's Note injection ---
                "authors_note": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "用户自定义注入内容（Author's Note），插入到上下文最前方",
                    "forceInput": True,
                }),
                "character_note": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "角色备注（Character Note），注入到角色描述之后",
                    "forceInput": True,
                }),
                "injection_rules_json": ("STRING", {
                    "multiline": True,
                    "default": "[]",
                    "placeholder": "变量驱动注入规则 JSON",
                    "forceInput": True,
                }),
                "project_root": ("STRING", {
                    "default": "",
                    "placeholder": "项目根目录（含 .story-system 合约文件）",
                    "forceInput": True,
                }),
                "chapter_num": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 99999,
                    "label": "剧情合约章节号",
                }),
                "story_genre": ("STRING", {
                    "default": "",
                    "placeholder": "剧情合约类型（用于合约解析）",
                }),
                "target_tokens": ("INT", {
                    "default": 4000,
                    "min": 500,
                    "max": 16000,
                    "label": "目标 Token 数",
                }),
                "top_worldbook": ("INT", {
                    "default": 3,
                    "min": 1,
                    "max": 8,
                    "label": "世界书匹配数",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("组装上下文", "匹配的世界书", "变量清单", "预算报告")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/管线"

    def execute(
        self,
        user_input: str,
        session_id: str,
        current_variables: str = "{}",
        worldbook_index: str = "[]",
        memory_context: str = "[]",
        var_diff: str = "{}",
        target_tokens: int = 4000,
        top_worldbook: int = 3,
        authors_note: str = "",
        character_note: str = "",
        injection_rules_json: str = "[]",
        project_root: str = "",
        chapter_num: int = 0,
        story_genre: str = "",
    ):
        from ..mvu.matcher import match_worldbook_by_variables, extract_topics_from_changes
        from ..mvu.checker import generate_variable_checklist
        from ..rp_pipeline import safe_json_loads, estimate_tokens, truncate_text

        # ── Parse inputs ──
        try:
            import json
            variables = json.loads(current_variables) if current_variables.strip() else {}
        except json.JSONDecodeError:
            variables = {}
        if not isinstance(variables, dict):
            variables = {}

        try:
            wb_index = json.loads(worldbook_index) if worldbook_index.strip() else []
        except json.JSONDecodeError:
            wb_index = []
        if not isinstance(wb_index, list):
            wb_index = []

        try:
            v_diff = json.loads(var_diff) if var_diff.strip() else {}
        except json.JSONDecodeError:
            v_diff = {}
        if not isinstance(v_diff, dict):
            v_diff = {}

        memories = safe_json_loads(memory_context, [])
        if not isinstance(memories, list):
            memories = []

        try:
            injection_rules = json.loads(injection_rules_json) if injection_rules_json.strip() else []
        except json.JSONDecodeError:
            injection_rules = []
        if not isinstance(injection_rules, list):
            injection_rules = []

        story_contract_context = ""
        story_contract_loaded = False
        if project_root.strip() and chapter_num > 0:
            try:
                from ..core.story_contracts import StoryContracts
                contracts = StoryContracts(project_root.strip())
                if contracts.load_all():
                    runtime_contract = contracts.resolve(chapter_num, story_genre)
                    rendered_contract = contracts.render_contract_context(runtime_contract)
                    if rendered_contract:
                        story_contract_context = "## Story Contract\n" + rendered_contract
                        story_contract_loaded = True
            except Exception:
                story_contract_context = ""
                story_contract_loaded = False

        # ── Step 1: Variable-driven worldbook matching ──
        matched_wb: list[dict] = []
        if wb_index and v_diff:
            matched_wb = match_worldbook_by_variables(
                audit=v_diff,
                worldbook_index=wb_index,
                initvar=variables,
                top_n=top_worldbook,
            )

        injection_matched: list[dict] = []
        if wb_index and injection_rules:
            from ..tools.builtin.injection_tool import get_injection_keywords, resolve_injections
            injection_keywords = get_injection_keywords(variables, injection_rules)
            injection_matched = resolve_injections(
                injection_keywords,
                wb_index,
                max_entries=top_worldbook,
            )
            for match in injection_matched:
                match["source"] = "injection_rule"
                match["score"] = max(float(match.get("score", 0) or 0), 100.0)

        # ── Step 2: Input-driven worldbook matching (keyword overlap) ──
        # Also match based on user input keywords against worldbook index
        input_matched: list[dict] = []
        if wb_index and user_input.strip():
            from ..mvu.matcher import score_match
            # Extract keywords from user input
            input_topics = [s for s in user_input.replace("，", ",").replace("。", ",").split(",") if len(s.strip()) >= 2]
            for entry in wb_index:
                kw = entry.get("keyword", "")
                score, reason = score_match(kw, input_topics)
                if score >= 5 and kw not in {m["keyword"] for m in matched_wb + input_matched}:
                    input_matched.append({
                        "keyword": kw,
                        "title": entry.get("title", kw),
                        "section": entry.get("section", f"## {kw}"),
                        "one_liner": entry.get("one_liner", ""),
                        "score": score,
                        "reason": reason,
                        "source": "input_match",
                    })
            input_matched.sort(key=lambda x: x["score"], reverse=True)
            input_matched = input_matched[:top_worldbook]

        all_matches = injection_matched + matched_wb + input_matched
        # Deduplicate by keyword, keep highest score
        seen_kw: set[str] = set()
        deduped: list[dict] = []
        for m in sorted(all_matches, key=lambda x: x.get("score", 0), reverse=True):
            if m["keyword"] not in seen_kw:
                seen_kw.add(m["keyword"])
                deduped.append(m)
        all_matches = deduped[:top_worldbook * 2]

        # ── Step 3: Variable checklist ──
        var_checklist = generate_variable_checklist(variables, v_diff)

        # ── Step 4: Assemble context ──
        sections: list[str] = []

        # P6.3: Author's Note — highest priority injection
        if authors_note.strip():
            sections.append(f"## Author's Note\n{authors_note.strip()}")

        if story_contract_context:
            sections.append(story_contract_context)

        sections.append(f"## User Input\n{user_input}")

        # P6.3: Character Note — injected after user input, before world data
        if character_note.strip():
            sections.append(f"## Character Note\n{character_note.strip()}")

        if variables:
            checklist_text = str(var_checklist.get("checklist", "")).strip()
            if checklist_text:
                sections.append(f"## Current Variable State\n{checklist_text}")

        for match in all_matches:
            source_tag = {
                "input_match": "input-match",
                "injection_rule": "injection-rule",
            }.get(match.get("source"), "var-driven")
            sections.append(
                f"## Worldbook: {match['keyword']} [{source_tag} score={match.get('score', 0)}]\n"
                f"Title: {match.get('title', '')}\n"
                f"{match.get('one_liner', '')}"
            )

        if memories:
            mem_text = "\n".join(
                f"- [{m.get('type', 'event')}] {truncate_text(str(m.get('content', m.get('summary', ''))), 200)}"
                for m in memories[:8]
                if m.get("content") or m.get("summary")
            )
            if mem_text:
                sections.append(f"## Recent Memories\n{mem_text}")

        # ── Step 5: Token budget ──
        assembled = "\n\n".join(sections)
        estimated = estimate_tokens(assembled)
        warnings: list[str] = []
        if estimated > target_tokens:
            warnings.append(f"Estimated {estimated} tokens exceeds target {target_tokens}")

        budget = {
            "target": target_tokens,
            "estimated": estimated,
            "worldbook_matches": len(all_matches),
            "injection_matches": len(injection_matched),
            "story_contract_loaded": story_contract_loaded,
            "memory_records": len(memories),
            "warnings": warnings,
        }

        return (
            assembled,
            json.dumps(all_matches, ensure_ascii=False, indent=2),
            json.dumps(var_checklist, ensure_ascii=False, indent=2),
            json.dumps(budget, ensure_ascii=False, indent=2),
        )
