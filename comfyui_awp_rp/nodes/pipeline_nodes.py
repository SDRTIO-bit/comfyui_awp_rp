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
                "writer_contract_json": ("STRING", {
                    "multiline": True, "default": "",
                    "forceInput": True,
                    "label": "WriterContract JSON（P4D-1A：渲染为不可违背状态段）",
                }),
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
        writer_contract_json: str = "",
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
            writer_contract_json=writer_contract_json,
        )

        # Track contract usage in metadata
        _contract_provided = bool(writer_contract_json.strip())
        _contract_rendered = bool(writer_contract_json.strip())

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
            "writer_contract_provided": _contract_provided,
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
    """RP 回复的确定性质量门禁。

    P4D-1: 增加 writer_contract_json 可选输入，支持：
    - 身份检查（核心角色/用户身份/关系绑定被替换）
    - 长度检查（最小正文字数，排除选项块）
    - 连续性检查（场景跳转、禁止阶段移动、角色范围）
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "reply": ("STRING", {"multiline": True, "default": "", "forceInput": True}),
            },
            "optional": {
                "critic_review_json": ("STRING", {"multiline": True, "default": "", "forceInput": True}),
                "writer_contract_json": ("STRING", {
                    "multiline": True, "default": "",
                    "forceInput": True,
                    "label": "WriterContract JSON（P4D-1 身份/长度/连续性检查）",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("决策JSON", "状态", "修订指令")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/管线"

    def execute(self, reply: str, critic_review_json: str = "", writer_contract_json: str = ""):
        decision = apply_quality_gate(reply, critic_review_json)

        # P4D-1: Contract-based deterministic checks
        contract = safe_json_loads(writer_contract_json, {})
        if isinstance(contract, dict) and contract.get("schemaId"):
            contract_issues = self._check_writer_contract(reply, contract)
            if contract_issues:
                decision.setdefault("issues", []).extend(contract_issues)
                # Update accepted status if any error-severity issues
                has_errors = any(i.get("severity") == "error" for i in contract_issues)
                if has_errors:
                    decision["accepted"] = False
                    decision["decision"] = "revise"
                    decision["failedChecks"] = sorted(set(
                        decision.get("failedChecks", []) +
                        [i.get("code", "contract") for i in contract_issues if i.get("severity") == "error"]
                    ))

        status = "accept" if decision["accepted"] else "revise"
        return (json_dumps(decision), status, decision.get("revisionInstruction") or "")

    def _check_writer_contract(self, reply: str, contract: dict) -> list[dict[str, Any]]:
        """Run deterministic checks against writer contract."""
        issues: list[dict[str, Any]] = []
        text = str(reply or "")

        # ── Identity checks ──
        cast = contract.get("cast", {})
        if isinstance(cast, dict):
            issues.extend(self._check_identity(text, cast))

        # ── Length checks ──
        output_req = contract.get("outputRequirements", {})
        if isinstance(output_req, dict):
            issues.extend(self._check_length(text, output_req))

        # ── Continuity checks ──
        state = contract.get("state", {})
        scene = contract.get("scene", {})
        if isinstance(state, dict):
            issues.extend(self._check_continuity(text, state, scene))

        return issues

    def _check_identity(self, text: str, cast: dict) -> list[dict[str, Any]]:
        """Check for identity violations in the reply."""
        issues: list[dict[str, Any]] = []

        # Get locked character names
        locked = cast.get("lockedCharacters", [])
        known_names: set[str] = set()
        for char in locked:
            if isinstance(char, dict):
                name = char.get("name", "")
                if name:
                    known_names.add(name)
                for alias in char.get("aliases", []):
                    if isinstance(alias, str):
                        known_names.add(alias)

        # Get user identity
        user_id = cast.get("userIdentity", {})
        user_name = ""
        if isinstance(user_id, dict):
            user_name = str(user_id.get("name", ""))

        # Get relationship bindings
        bindings = cast.get("relationshipBindings", [])
        binding_names: dict[str, str] = {}
        for b in bindings:
            if isinstance(b, dict):
                src = b.get("source", "")
                target = b.get("target", "")
                if src and target:
                    binding_names[src] = target

        # ── Check: core character replaced by stranger ──
        # Look for character names in reply that are NOT in known_names
        # Only flag high-confidence cases: names appearing in dialogue markers
        import re
        dialogue_names = re.findall(r'[「「]([^」」]{1,20}?)[：:]', text)
        narrator_names = re.findall(r'(?:^|[，。！？\n])(.{1,6}?)(?:说道|道|说|问|答|喊|叫|笑|叹|怒|哭)', text)

        # Generic terms that should NOT be flagged
        generic_terms = {"村民", "邻居", "路人", "大家", "众人", "他们", "她", "他", "你", "我", "陌生人"}

        for name in set(dialogue_names + narrator_names):
            name = name.strip()
            if not name or len(name) < 2:
                continue
            if name in generic_terms:
                continue
            if name in known_names:
                continue
            # High-confidence: appears as a speaker but not a known character
            issues.append({
                "code": "identity_suspect",
                "severity": "warning",
                "message": f"疑似陌生角色名 '{name}' 出现在对话中，但不在已知角色列表中",
                "suggestion": "确认该角色是否为合法新增角色",
            })

        # ── Check: user identity replaced ──
        if user_name:
            # Check if the reply speaks AS the user (player control)
            user_patterns = [f"{user_name}心想", f"{user_name}决定", f"{user_name}选择"]
            for pattern in user_patterns:
                if pattern in text:
                    issues.append({
                        "code": "identity_violation",
                        "severity": "error",
                        "message": f"回复替用户 '{user_name}' 做出了行动或思想决定",
                        "suggestion": "描述NPC/世界反应，让玩家自主决定",
                    })
                    break

        # ── Check: relationship binding violation ──
        # This is hard to do deterministically, so we only check for
        # explicit contradictions in very specific patterns
        for src, target in binding_names.items():
            # If a binding says "A trusts B" but the reply says "A suspects B"
            trust_terms = {"信任", "信赖", "依赖"}
            suspect_terms = {"怀疑", "不信任", "警惕", "防备"}
            if f"{src}信任{target}" in text:
                # This is fine
                pass
            # Note: full relationship consistency check would need LLM
            # This is a placeholder for deterministic patterns only

        return issues

    def _check_length(self, text: str, output_req: dict) -> list[dict[str, Any]]:
        """Check reply length against contract requirements."""
        issues: list[dict[str, Any]] = []

        min_chars = int(output_req.get("minBodyChars", 800))
        exclude_options = output_req.get("excludeOptionsBlock", True)

        # Strip options block if required
        body = text
        if exclude_options:
            import re
            body = re.sub(r'<options>[\s\S]*?</options>', '', body, flags=re.IGNORECASE)
            body = re.sub(r'\[options\][\s\S]*?\[/options\]', '', body, flags=re.IGNORECASE)

        # Strip HTML tags, markdown formatting, whitespace for counting
        import re
        clean_body = re.sub(r'<[^>]+>', '', body)
        clean_body = re.sub(r'\*\*|__|~~|~~|`', '', clean_body)
        clean_body = clean_body.strip()

        # Count Chinese characters (the primary metric)
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', clean_body))
        # Also count other non-whitespace chars
        total_visible = len(clean_body.replace('\n', '').replace('\r', '').replace(' ', ''))

        # Use max of chinese_chars and total_visible as the body length
        body_length = max(chinese_chars, total_visible)

        if body_length < min_chars:
            issues.append({
                "code": "below_min_length",
                "severity": "error",
                "message": f"正文长度 {body_length} 字符低于最低要求 {min_chars}",
                "suggestion": f"增加正文内容至至少 {min_chars} 字符",
            })

        # Check for provider truncation (ends mid-sentence)
        if text and not text.rstrip().endswith(('。', '！', '？', '…', '"', '」', '）', '）')):
            # Only flag if the text is suspiciously short
            if body_length < min_chars * 0.8:
                issues.append({
                    "code": "provider_output_truncated",
                    "severity": "warning",
                    "message": "回复可能被 provider 截断（不以标点结尾且长度不足）",
                    "suggestion": "增加 max_tokens 或重试",
                })

        return issues

    def _check_continuity(self, text: str, state: dict, scene: dict) -> list[dict[str, Any]]:
        """Check for continuity violations."""
        issues: list[dict[str, Any]] = []

        # ── Forbidden stage move ──
        forbidden = state.get("forbiddenStageMoves", [])
        if forbidden:
            # Check if reply mentions any forbidden stage transitions
            for stage in forbidden:
                if isinstance(stage, str) and stage in text:
                    issues.append({
                        "code": "forbidden_stage_move",
                        "severity": "error",
                        "message": f"回复提及了禁止的阶段转移 '{stage}'",
                        "suggestion": f"避免使用 '{stage}' 相关的剧情推进",
                    })

        # ── Active character scope ──
        active_chars = scene.get("activeCharacterIds", [])
        if active_chars:
            # Only check if we have a defined character scope
            # This is a soft check - new characters can be introduced
            pass

        # ── Scene jump detection (deterministic) ──
        location = scene.get("location", "")
        if location:
            # Check for sudden location change without transition words
            transition_words = ["来到", "走进", "前往", "离开", "回到", "抵达", "出发"]
            # If a different location is mentioned without transition
            import re
            location_patterns = re.findall(r'(?:在|位于|身处)([^，。！？]{2,10})', text)
            for mentioned_loc in location_patterns:
                mentioned_loc = mentioned_loc.strip()
                if mentioned_loc != location and mentioned_loc:
                    # Check if there's a transition word nearby
                    has_transition = any(tw in text for tw in transition_words)
                    if not has_transition:
                        issues.append({
                            "code": "scene_jump_without_transition",
                            "severity": "warning",
                            "message": f"场景从 '{location}' 跳转到 '{mentioned_loc}' 但缺少过渡",
                            "suggestion": "添加过渡描写（如 '来到/走进/离开'）",
                        })

        return issues


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
    """将副作用权限暴露为显式工作流对象。

    P4D-1: 增加 candidate_card_state_patch_json 输入，确保：
    - quality gate rejected 时阻止状态/记忆/卡状态提交
    - 卡状态补丁必须通过 schema/path/type/range 校验
    """

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
                "candidate_card_state_patch_json": ("STRING", {
                    "multiline": True, "default": "",
                    "forceInput": True,
                    "label": "候选卡状态补丁 JSON（P4D-1，仅 accepted 时可提交）",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("决策JSON", "状态", "card_state_decision")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/管线"

    def execute(
        self,
        quality_decision_json: str,
        candidate_state_patch: str = "{}",
        candidate_memory_patch: str = "{}",
        allow_commit_when_accepted: bool = False,
        candidate_card_state_patch_json: str = "",
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

        # P4D-1: Card state patch decision
        card_state_decision = self._decide_card_state_patch(
            quality_decision_json,
            candidate_card_state_patch_json,
            allow_commit_when_accepted,
        )

        return (json_dumps(decision), status, json_dumps(card_state_decision))

    def _decide_card_state_patch(
        self,
        quality_decision_json: str,
        card_state_patch_json: str,
        allow_commit: bool,
    ) -> dict[str, Any]:
        """Determine whether the card state patch can be committed."""
        quality = safe_json_loads(quality_decision_json, {})
        if not isinstance(quality, dict):
            quality = {"accepted": False}

        accepted = bool(quality.get("accepted", False))

        if not card_state_patch_json.strip():
            return {
                "schemaId": "awp.rp.side-effect-card-state.v1",
                "allowCardStateCommit": False,
                "reason": "no_card_state_patch_provided",
            }

        patch_data = safe_json_loads(card_state_patch_json, {})
        if not isinstance(patch_data, dict):
            return {
                "schemaId": "awp.rp.side-effect-card-state.v1",
                "allowCardStateCommit": False,
                "reason": "invalid_patch_format",
            }

        # Gate: quality must be accepted
        if not accepted:
            return {
                "schemaId": "awp.rp.side-effect-card-state.v1",
                "allowCardStateCommit": False,
                "reason": "quality-gate-rejected",
                "patchSchemaId": patch_data.get("schemaId", ""),
            }

        # Validate patch structure
        from ..card.card_state_contract import CandidateCardStatePatch, validate_candidate_patch
        try:
            patch = CandidateCardStatePatch.from_dict(patch_data)
            valid, errors = validate_candidate_patch(patch)
            if not valid:
                return {
                    "schemaId": "awp.rp.side-effect-card-state.v1",
                    "allowCardStateCommit": False,
                    "reason": "patch_validation_failed",
                    "errors": errors,
                }
        except Exception as exc:
            return {
                "schemaId": "awp.rp.side-effect-card-state.v1",
                "allowCardStateCommit": False,
                "reason": f"patch_parse_error: {exc}",
            }

        # All checks passed
        return {
            "schemaId": "awp.rp.side-effect-card-state.v1",
            "allowCardStateCommit": allow_commit,
            "reason": "accepted-pending-commit-policy" if allow_commit else "accepted-manual-commit",
            "commitPolicy": patch.commitPolicy,
        }


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
                "routing_decision_json": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "forceInput": True,
                    "label": "路由决策JSON（routed v1，留空=legacy）",
                }),
                # --- P4D-1: Card state inputs for writer contract ---
                "card_state_json": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "forceInput": True,
                    "label": "CardState JSON（来自 AWPCardStateInit）",
                }),
                "condition_evaluation_json": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "forceInput": True,
                    "label": "条件求值结果 JSON（来自 AWPConditionalWorldbook）",
                }),
                "cast_info_json": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "forceInput": True,
                    "label": "角色阵容 JSON（lockedCharacters/userIdentity）",
                }),
                "recent_history_json": ("STRING", {
                    "default": "[]",
                    "multiline": True,
                    "forceInput": True,
                    "label": "最近回合历史 JSON（3-5回合）",
                }),
                "card_id": ("STRING", {
                    "default": "",
                    "forceInput": True,
                    "label": "角色卡ID",
                }),
                "min_body_chars": ("INT", {
                    "default": 800,
                    "min": 100,
                    "max": 5000,
                    "label": "最小正文字数",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("组装上下文", "匹配的世界书", "变量清单", "预算报告", "writer_contract_json")
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
        routing_decision_json: str = "",
        card_state_json: str = "",
        condition_evaluation_json: str = "",
        cast_info_json: str = "",
        recent_history_json: str = "[]",
        card_id: str = "",
        min_body_chars: int = 800,
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

        # ── Step 2.5: Load constant (always-on) worldbook entries ──
        constant_matched: list[dict] = []
        if wb_index:
            for entry in wb_index:
                activation = entry.get("activation", "")
                if activation == "const":
                    kw = entry.get("keyword", "")
                    if kw not in {m["keyword"] for m in matched_wb + input_matched + injection_matched + constant_matched}:
                        constant_matched.append({
                            "keyword": kw,
                            "title": entry.get("title", kw),
                            "section": entry.get("section", f"## {kw}"),
                            "one_liner": entry.get("one_liner", ""),
                            "content": entry.get("content", ""),
                            "score": 200.0,  # 常开条目给予最高优先级
                            "reason": "constant (always-on)",
                            "source": "constant",
                        })

        all_matches = injection_matched + matched_wb + input_matched + constant_matched
        # Deduplicate by keyword, keep highest score
        seen_kw: set[str] = set()
        deduped: list[dict] = []
        # 常开条目优先保留
        for m in sorted(all_matches, key=lambda x: (x.get("source") == "constant", x.get("score", 0)), reverse=True):
            if m["keyword"] not in seen_kw:
                seen_kw.add(m["keyword"])
                deduped.append(m)
        # 常开条目不受 top_worldbook 限制
        constant_entries = [m for m in deduped if m.get("source") == "constant"]
        other_entries = [m for m in deduped if m.get("source") != "constant"]
        all_matches = constant_entries + other_entries[:top_worldbook]

        # ── Step 2.6: Worldbook token budget (V1) ──
        # Constant entries used to accumulate unbounded (the 64k root cause on
        # this path too). Enforce a budget from the routing decision (default
        # 4000), keeping core/constant first then triggered by score.
        from ..knowledge.worldbook import apply_worldbook_budget
        try:
            _routing = json.loads(routing_decision_json) if routing_decision_json.strip() else {}
        except json.JSONDecodeError:
            _routing = {}
        wb_budget = int(
            (_routing.get("worldbook_budget_tokens") if isinstance(_routing, dict) else None)
            or 4000
        )
        # Adapt all_matches to the budget function's entry shape.
        _wb_for_budget = [
            {
                "comment": m.get("title") or m.get("keyword"),
                "content": m.get("content") or m.get("one_liner", ""),
                "constant": m.get("source") == "constant",
                "priority": float(m.get("score", 0) or 0),
            }
            for m in all_matches
        ]
        _included_wb, wb_budget_report = apply_worldbook_budget(
            _wb_for_budget, wb_budget, keep_core=True
        )
        included_keys = [
            (e.get("comment"), bool(e.get("constant"))) for e in _included_wb
        ]
        # Re-filter all_matches preserving order by included comment+constancy.
        included_set = set(included_keys)
        all_matches = [
            m for m in all_matches
            if ((m.get("title") or m.get("keyword")), m.get("source") == "constant") in included_set
        ]

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
                "constant": "constant",
            }.get(match.get("source"), "var-driven")
            # 常开条目使用完整内容，其他使用 one_liner
            if match.get("source") == "constant" and match.get("content"):
                content = match["content"]
            else:
                content = match.get("one_liner", "")
            sections.append(
                f"## Worldbook: {match['keyword']} [{source_tag} score={match.get('score', 0)}]\n"
                f"Title: {match.get('title', '')}\n"
                f"{content}"
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
            "context_owner": "routed" if routing_decision_json.strip() else "legacy",
            "core_worldbook_token_estimate": wb_budget_report.get("core_worldbook_token_estimate", 0),
            "retrieved_worldbook_token_estimate": wb_budget_report.get("retrieved_worldbook_token_estimate", 0),
            "worldbook_entries_considered": wb_budget_report.get("worldbook_entries_considered", 0),
            "worldbook_entries_included": wb_budget_report.get("worldbook_entries_included", 0),
            "worldbook_entries_dropped": wb_budget_report.get("worldbook_entries_dropped", 0),
            "worldbook_budget_tokens": wb_budget,
            "worldbook_drop_reasons": wb_budget_report.get("drop_reasons", []),
        }

        # ── Step 6: Build WriterContract v1 ──
        writer_contract = self._build_writer_contract(
            session_id=session_id,
            card_id=card_id,
            card_state_json=card_state_json,
            condition_evaluation_json=condition_evaluation_json,
            cast_info_json=cast_info_json,
            recent_history_json=recent_history_json,
            variables=variables,
            all_matches=all_matches,
            constant_entries=constant_entries,
            other_entries=other_entries,
            wb_budget_report=wb_budget_report,
            memories=memories,
            assembled_text=assembled,
            min_body_chars=min_body_chars,
        )

        return (
            assembled,
            json.dumps(all_matches, ensure_ascii=False, indent=2),
            json.dumps(var_checklist, ensure_ascii=False, indent=2),
            json.dumps(budget, ensure_ascii=False, indent=2),
            json.dumps(writer_contract, ensure_ascii=False, indent=2),
        )

    def _build_writer_contract(
        self,
        session_id: str,
        card_id: str,
        card_state_json: str,
        condition_evaluation_json: str,
        cast_info_json: str,
        recent_history_json: str,
        variables: dict,
        all_matches: list,
        constant_entries: list,
        other_entries: list,
        wb_budget_report: dict,
        memories: list,
        assembled_text: str,
        min_body_chars: int,
    ) -> dict:
        """Build a WriterContract v1 from available data."""
        from ..card.card_state_contract import (
            WriterContract, CastInfo, StateInfo, SceneInfo,
            ContinuityInfo, WorldbookInfo, OutputRequirements, BudgetInfo,
            CardState, ConditionEvaluationResult,
            WRITER_CONTRACT_SCHEMA,
        )
        from ..rp_pipeline import estimate_tokens, truncate_text, safe_json_loads

        # Parse card state
        cs = CardState.from_json(card_state_json) if card_state_json.strip() else CardState()

        # Parse condition evaluation
        cond_eval = safe_json_loads(condition_evaluation_json, {})
        if not isinstance(cond_eval, dict):
            cond_eval = {}

        # Parse cast info
        cast_data = safe_json_loads(cast_info_json, {})
        if not isinstance(cast_data, dict):
            cast_data = {}

        # Parse recent history
        history = safe_json_loads(recent_history_json, [])
        if not isinstance(history, list):
            history = []
        # Limit to 3-5 turns
        recent_history = history[-5:] if len(history) > 5 else history

        # Build cast
        cast = CastInfo(
            lockedCharacters=list(cast_data.get("lockedCharacters") or []),
            userIdentity=dict(cast_data.get("userIdentity") or {}),
            relationshipBindings=list(cast_data.get("relationshipBindings") or []),
            aliases=list(cast_data.get("aliases") or []),
        )

        # Build state
        state = StateInfo(
            variables=dict(cs.variables or variables),
            activeStageIds=list(cond_eval.get("activeStageIds") or cs.activeStageIds),
            eligibleEventIds=list(cond_eval.get("eligibleEventIds") or []),
            forbiddenStageMoves=list(cond_eval.get("forbiddenStageMoves") or []),
        )

        # Build scene
        scene_data = cs.sceneState or {}
        scene = SceneInfo(
            location=str(scene_data.get("location", "")),
            time=str(scene_data.get("time", "")),
            activeCharacterIds=list(scene_data.get("activeCharacterIds") or []),
            lastAcceptedTurn=str(scene_data.get("lastAcceptedTurn", "")),
        )

        # Build continuity
        recent_history_items = []
        for h in recent_history:
            if isinstance(h, dict):
                recent_history_items.append({
                    "turn": h.get("turn", 0),
                    "input": truncate_text(str(h.get("input", "")), 200),
                    "output": truncate_text(str(h.get("output", "")), 200),
                })
            elif isinstance(h, str):
                recent_history_items.append({"text": truncate_text(h, 200)})

        # Extract open threads from structured memories
        open_threads = []
        for m in memories:
            if isinstance(m, dict) and m.get("type") == "open_thread":
                open_threads.append({
                    "topic": m.get("content", ""),
                    "status": m.get("metadata", {}).get("status", "open"),
                })

        # Build summary from scene state if available
        _narrative_summary = ""
        if isinstance(cs.sceneState, dict) and cs.sceneState.get("narrativeSummary"):
            _narrative_summary = str(cs.sceneState["narrativeSummary"])
        continuity = ContinuityInfo(
            recentHistory=recent_history_items,
            summary=_narrative_summary,
            openThreads=open_threads,
            relevantFacts=[],
        )

        # Build worldbook info
        pinned_core = []
        conditional_active = []
        retrieved_dynamic = []
        dropped = []

        # Pinned core: cast characters + constant entries
        for entry in constant_entries:
            pinned_core.append({
                "title": entry.get("title", ""),
                "content": truncate_text(str(entry.get("content", "") or entry.get("one_liner", "")), 500),
                "source": "constant",
            })

        # Conditional active from condition evaluation
        active_entries = cond_eval.get("activeEntries", [])
        for entry in active_entries:
            if isinstance(entry, dict):
                conditional_active.append({
                    "title": entry.get("title", ""),
                    "content": truncate_text(str(entry.get("content", "")), 300),
                })

        # Dynamic retrieved from round preparer matches
        for entry in other_entries:
            if entry not in constant_entries:
                retrieved_dynamic.append({
                    "title": entry.get("title", ""),
                    "content": truncate_text(str(entry.get("content", "") or entry.get("one_liner", "")), 300),
                    "score": entry.get("score", 0),
                })

        # Dropped entries
        drop_reasons = wb_budget_report.get("drop_reasons", [])
        for dr in drop_reasons:
            if isinstance(dr, dict):
                dropped.append({
                    "title": dr.get("comment", ""),
                    "reason": dr.get("reason", "budget-exceeded"),
                })

        wb_info = WorldbookInfo(
            pinnedCore=pinned_core,
            conditionalActive=conditional_active,
            retrievedDynamic=retrieved_dynamic,
            dropped=dropped,
        )

        # Build output requirements
        output_req = OutputRequirements(
            minBodyChars=min_body_chars,
            targetBodyChars=[min_body_chars + 100, min_body_chars + 400],
            excludeOptionsBlock=True,
        )

        # Build budget
        budget = BudgetInfo(
            historyChars=sum(len(str(h.get("input", ""))) + len(str(h.get("output", ""))) for h in recent_history_items if isinstance(h, dict)),
            memoryChars=sum(len(str(m.get("content", "") or m.get("summary", ""))) for m in memories),
            worldbookChars=sum(len(str(e.get("content", "") or e.get("one_liner", ""))) for e in all_matches),
            totalEstimatedTokens=estimate_tokens(assembled_text),
        )

        contract = WriterContract(
            schemaId=WRITER_CONTRACT_SCHEMA,
            sessionId=session_id,
            cardId=card_id or cs.cardId,
            cast=cast,
            state=state,
            scene=scene,
            continuity=continuity,
            worldbook=wb_info,
            outputRequirements=output_req,
            budget=budget,
            diagnostics=[],
        )

        return contract.to_dict()
