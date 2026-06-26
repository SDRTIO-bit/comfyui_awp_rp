"""
P4D-1: Card state nodes for stateful card runtime.

AWPCardStateInit — Initialize or load card state for a session.
AWPConditionalWorldbook — Deterministic condition evaluation against card state.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..card.card_state_contract import (
    CardState,
    ConditionNode,
    ConditionEntry,
    ConditionEvaluationResult,
    WriterContract,
    CastInfo,
    StateInfo,
    SceneInfo,
    ContinuityInfo,
    WorldbookInfo,
    OutputRequirements,
    BudgetInfo,
    CandidateCardStatePatch,
    evaluate_condition,
    _resolve_json_path,
    validate_candidate_patch,
    apply_commit_operations_strict,
    compute_patch_hash,
    CARD_STATE_SCHEMA,
    CANDIDATE_PATCH_SCHEMA,
    COMMIT_RESULT_SCHEMA,
)
from ..card.card_state_store import CardStateStore


class AWPCardStateInit:
    """Initialize or load card state for a card+session combination.

    Idempotent: if state already exists for this cardId+sessionId, returns
    the existing state without modification.

    Bootstrap priority:
      1. Existing persistent state (idempotent)
      2. Explicit initial_state_json input
      3. Selected greeting's separatedInitialPatch
      4. Card-level safe initial state / variables
      5. bootstrap_required (empty variables + diagnostic)

    Inputs:
        card_id: Character card ID
        session_id: Session ID
        initial_state_json: Optional initial variables/state JSON
        card_data_json: Card data for extracting initial state
        greeting_text: Greeting text for scene extraction
        greeting_json: Selected greeting JSON with separatedInitialPatch
        greeting_id: Explicit greeting ID to select from greetings list
        greetings_json: Full greetings array from card import

    Outputs:
        card_state_json: Full CardState JSON
        diagnostics_json: Initialization diagnostics
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "card_id": ("STRING", {
                    "default": "",
                    "placeholder": "角色卡ID",
                    "forceInput": True,
                }),
                "session_id": ("STRING", {
                    "default": "default",
                    "forceInput": True,
                }),
            },
            "optional": {
                "initial_state_json": ("STRING", {
                    "multiline": True,
                    "default": "{}",
                    "placeholder": "初始变量状态 JSON（可选）",
                    "forceInput": True,
                }),
                "card_data_json": ("STRING", {
                    "multiline": True,
                    "default": "{}",
                    "placeholder": "角色卡数据 JSON（用于提取初始状态）",
                    "forceInput": True,
                }),
                "greeting_text": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "开场白文本（用于提取初始场景）",
                    "forceInput": True,
                }),
                "greeting_json": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "选中的 greeting JSON（含 separatedInitialPatch）",
                    "forceInput": True,
                }),
                "greeting_id": ("STRING", {
                    "default": "",
                    "placeholder": "指定 greeting ID（可选）",
                    "forceInput": True,
                }),
                "greetings_json": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "greetings 数组 JSON（来自导入结果）",
                    "forceInput": True,
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("card_state_json", "diagnostics_json")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/状态"

    # Bootstrap status constants
    _BOOT_EXISTING = "initialized_from_existing_state"
    _BOOT_EXPLICIT = "initialized_from_explicit_input"
    _BOOT_GREETING = "initialized_from_selected_greeting_patch"
    _BOOT_CARD = "initialized_from_card"
    _BOOT_REQUIRED = "bootstrap_required"
    _BOOT_INVALID_PATCH = "invalid_initial_patch"

    def execute(
        self,
        card_id: str,
        session_id: str,
        initial_state_json: str = "{}",
        card_data_json: str = "{}",
        greeting_text: str = "",
        greeting_json: str = "",
        greeting_id: str = "",
        greetings_json: str = "",
    ):
        store = CardStateStore()
        diagnostics: list[dict[str, Any]] = []

        # Validate inputs
        if not card_id.strip():
            diagnostics.append({
                "code": "missing_card_id",
                "message": "card_id is empty",
                "severity": "error",
            })
            empty_state = CardState(cardId="", sessionId=session_id, diagnostics=diagnostics)
            return (empty_state.to_json(), json.dumps(diagnostics, ensure_ascii=False))

        if not session_id.strip():
            diagnostics.append({
                "code": "missing_session_id",
                "message": "session_id is empty",
                "severity": "error",
            })
            empty_state = CardState(cardId=card_id, sessionId="", diagnostics=diagnostics)
            return (empty_state.to_json(), json.dumps(diagnostics, ensure_ascii=False))

        # ── Priority 1: Idempotent — existing state ──
        existing = store.load(card_id, session_id)
        if existing and existing.is_initialized():
            diagnostics.append({
                "code": "state_already_exists",
                "bootstrapStatus": self._BOOT_EXISTING,
                "bootstrapSource": "existing_state",
                "message": f"Returning existing state (revision={existing.revision})",
                "severity": "info",
            })
            return (existing.to_json(), json.dumps(diagnostics, ensure_ascii=False))

        # ── Priority 2: Explicit initial_state_json ──
        initial_vars: dict[str, Any] = {}
        bootstrap_status = self._BOOT_REQUIRED
        bootstrap_source = "none"

        try:
            parsed = json.loads(initial_state_json) if initial_state_json.strip() else {}
            if isinstance(parsed, dict) and parsed:
                initial_vars = parsed
                bootstrap_status = self._BOOT_EXPLICIT
                bootstrap_source = "explicit_input"
                diagnostics.append({
                    "code": "vars_from_explicit_input",
                    "bootstrapStatus": bootstrap_status,
                    "bootstrapSource": bootstrap_source,
                    "message": f"Using explicit initial_state_json ({len(parsed)} keys)",
                    "severity": "info",
                })
        except json.JSONDecodeError:
            diagnostics.append({
                "code": "invalid_initial_state_json",
                "message": "Could not parse initial_state_json",
                "severity": "warning",
            })

        # ── Priority 3: Selected greeting's separatedInitialPatch ──
        if not initial_vars:
            greeting_vars, g_status, g_source, g_diags = self._extract_from_greeting(
                greeting_json=greeting_json,
                greeting_id=greeting_id,
                greetings_json=greetings_json,
            )
            diagnostics.extend(g_diags)
            if greeting_vars:
                initial_vars = greeting_vars
                bootstrap_status = g_status
                bootstrap_source = g_source

        # ── Priority 4: Card-level safe initial state ──
        if not initial_vars and card_data_json.strip():
            try:
                card_data = json.loads(card_data_json)
                if isinstance(card_data, dict):
                    card_vars = self._extract_initial_vars(card_data, diagnostics)
                    if card_vars:
                        initial_vars = card_vars
                        bootstrap_status = self._BOOT_CARD
                        bootstrap_source = "card"
            except json.JSONDecodeError:
                pass

        # ── Priority 5: bootstrap_required ──
        if not initial_vars:
            bootstrap_status = self._BOOT_REQUIRED
            bootstrap_source = "none"
            diagnostics.append({
                "code": "no_initial_variables",
                "bootstrapStatus": bootstrap_status,
                "bootstrapSource": bootstrap_source,
                "message": "No safe initial state source found; state starts empty",
                "severity": "warning",
            })

        # Extract scene from greeting if available
        scene_state: dict[str, Any] = {
            "location": "",
            "time": "",
            "activeCharacterIds": [],
            "lastAcceptedTurn": "",
        }
        if greeting_text.strip():
            scene_state = self._extract_scene_from_greeting(greeting_text, diagnostics)

        # Create new state
        state = CardState(
            cardId=card_id,
            sessionId=session_id,
            revision=0,
            variables=initial_vars,
            eventFlags={},
            activeStageIds=[],
            sceneState=scene_state,
            diagnostics=diagnostics,
        )

        # Save to store
        store.save(state)
        diagnostics.append({
            "code": "state_initialized",
            "bootstrapStatus": bootstrap_status,
            "bootstrapSource": bootstrap_source,
            "message": f"CardState created for {card_id}/{session_id}",
            "severity": "info",
        })

        return (state.to_json(), json.dumps(diagnostics, ensure_ascii=False))

    def _extract_from_greeting(
        self,
        greeting_json: str,
        greeting_id: str,
        greetings_json: str,
    ) -> tuple[dict[str, Any], str, str, list[dict[str, Any]]]:
        """Extract initial variables from greeting's separatedInitialPatch.

        Returns (variables, bootstrap_status, bootstrap_source, diagnostics).
        """
        diagnostics: list[dict[str, Any]] = []
        empty = ({}, self._BOOT_REQUIRED, "none", diagnostics)

        # Try to find the selected greeting
        selected_greeting: dict[str, Any] | None = None

        # Option A: Direct greeting_json input
        if greeting_json.strip():
            try:
                g = json.loads(greeting_json)
                if isinstance(g, dict):
                    selected_greeting = g
            except json.JSONDecodeError:
                diagnostics.append({
                    "code": "invalid_greeting_json",
                    "message": "Could not parse greeting_json",
                    "severity": "warning",
                })

        # Option B: Find by greeting_id in greetings array
        if selected_greeting is None and greetings_json.strip():
            try:
                greetings = json.loads(greetings_json)
                if isinstance(greetings, list) and greetings:
                    if greeting_id.strip():
                        # Explicit greeting_id — find it
                        for g in greetings:
                            if isinstance(g, dict) and str(g.get("greetingId", "")) == greeting_id.strip():
                                selected_greeting = g
                                break
                        if selected_greeting is None:
                            diagnostics.append({
                                "code": "greeting_id_not_found",
                                "message": f"greeting_id '{greeting_id}' not found in greetings array",
                                "severity": "warning",
                            })
                    else:
                        # No explicit greeting_id — check for unique default
                        defaults = [
                            g for g in greetings
                            if isinstance(g, dict) and g.get("isDefault")
                        ]
                        if len(defaults) == 1:
                            selected_greeting = defaults[0]
                            diagnostics.append({
                                "code": "greeting_default_selected",
                                "message": "Using unique default greeting",
                                "severity": "info",
                            })
                        elif len(defaults) > 1:
                            diagnostics.append({
                                "code": "ambiguous_greeting_selection",
                                "bootstrapStatus": self._BOOT_REQUIRED,
                                "bootstrapSource": "none",
                                "message": f"Multiple default greetings ({len(defaults)}); cannot auto-select",
                                "severity": "warning",
                            })
                            return empty
                        elif len(greetings) == 1:
                            # Only one greeting — use it
                            selected_greeting = greetings[0]
                            diagnostics.append({
                                "code": "greeting_single_selected",
                                "message": "Only one greeting available; using it",
                                "severity": "info",
                            })
                        else:
                            diagnostics.append({
                                "code": "ambiguous_greeting_selection",
                                "bootstrapStatus": self._BOOT_REQUIRED,
                                "bootstrapSource": "none",
                                "message": f"Multiple greetings ({len(greetings)}) but none marked default; cannot auto-select",
                                "severity": "warning",
                            })
                            return empty
            except json.JSONDecodeError:
                diagnostics.append({
                    "code": "invalid_greetings_json",
                    "message": "Could not parse greetings_json",
                    "severity": "warning",
                })

        if selected_greeting is None:
            return empty

        # Extract separatedInitialPatch from the selected greeting
        patches_raw = selected_greeting.get("separatedInitialPatch")
        if not patches_raw:
            # Check hadUnappliedInitialPatch flag for diagnostic
            if selected_greeting.get("hadUnappliedInitialPatch"):
                diagnostics.append({
                    "code": "greeting_had_unapplied_patch",
                    "message": "Greeting had unapplied initial patch but separatedInitialPatch is empty",
                    "severity": "warning",
                })
            return ({}, self._BOOT_REQUIRED, "none", diagnostics)

        # Apply patches safely
        greeting_id_val = selected_greeting.get("greetingId", "unknown")
        variables, apply_diags = self._apply_initial_patches(patches_raw)
        diagnostics.extend(apply_diags)

        if variables:
            return (
                variables,
                self._BOOT_GREETING,
                f"greeting:{greeting_id_val}",
                diagnostics,
            )

        # Patches were present but all failed
        return ({}, self._BOOT_INVALID_PATCH, "none", diagnostics)

    def _apply_initial_patches(
        self,
        patches_raw: list[Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Safely apply separatedInitialPatch operations to build initial variables.

        Only allows 'replace' and 'add' operations on dot-path keys.
        Rejects patches that target protected fields or use dangerous paths.

        Returns (variables, diagnostics).
        """
        from ..card.card_state_contract import _validate_path

        diagnostics: list[dict[str, Any]] = []
        variables: dict[str, Any] = {}

        # Protected paths that patches must never write to
        _PROTECTED_PREFIXES = ("cardId", "sessionId", "revision", "diagnostics", "schemaId")

        valid_ops = {"replace", "add"}
        applied = 0
        rejected = 0

        for i, raw_patch in enumerate(patches_raw):
            # Parse patch — may be a JSON string or a dict
            patch: dict[str, Any] | None = None
            if isinstance(raw_patch, dict):
                patch = raw_patch
            elif isinstance(raw_patch, str):
                try:
                    parsed = json.loads(raw_patch)
                    if isinstance(parsed, dict):
                        patch = parsed
                except json.JSONDecodeError:
                    diagnostics.append({
                        "code": "patch_parse_error",
                        "index": i,
                        "message": f"Could not parse patch string at index {i}",
                        "severity": "warning",
                    })
                    rejected += 1
                    continue

            if not isinstance(patch, dict):
                rejected += 1
                continue

            op = patch.get("op")
            path = patch.get("path", "")
            value = patch.get("value")

            # Validate operation type
            if op not in valid_ops:
                diagnostics.append({
                    "code": "patch_rejected_op",
                    "index": i,
                    "op": op,
                    "message": f"Operation '{op}' not allowed; only {valid_ops}",
                    "severity": "warning",
                })
                rejected += 1
                continue

            # Validate path is a string
            if not isinstance(path, str) or not path:
                diagnostics.append({
                    "code": "patch_rejected_path",
                    "index": i,
                    "message": "Patch path is empty or not a string",
                    "severity": "warning",
                })
                rejected += 1
                continue

            # Normalize JSON Pointer path to dot notation
            dot_path = path.lstrip("/").replace("/", ".")
            if not dot_path:
                rejected += 1
                continue

            # Check protected prefixes
            root_key = dot_path.split(".")[0]
            if root_key in _PROTECTED_PREFIXES:
                diagnostics.append({
                    "code": "patch_rejected_protected",
                    "index": i,
                    "path": dot_path,
                    "message": f"Patch targets protected field '{root_key}'",
                    "severity": "warning",
                })
                rejected += 1
                continue

            # Validate path safety
            valid_path, reason = _validate_path(dot_path)
            if not valid_path:
                diagnostics.append({
                    "code": "patch_rejected_unsafe_path",
                    "index": i,
                    "path": dot_path,
                    "reason": reason,
                    "message": f"Path '{dot_path}' rejected: {reason}",
                    "severity": "warning",
                })
                rejected += 1
                continue

            # Apply: set value at dot path
            self._set_nested(variables, dot_path, value)
            applied += 1

        if applied > 0:
            diagnostics.append({
                "code": "greeting_patches_applied",
                "applied": applied,
                "rejected": rejected,
                "message": f"Applied {applied} greeting patches ({rejected} rejected)",
                "severity": "info",
            })

        return variables, diagnostics

    @staticmethod
    def _set_nested(obj: dict, dot_path: str, value: Any) -> None:
        """Set a value at a dotted path in a nested dict."""
        parts = dot_path.split(".")
        current = obj
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    def _extract_initial_vars(
        self, card_data: dict, diagnostics: list
    ) -> dict[str, Any]:
        """Extract initial variables from card data.

        Looks for safe, parseable initial state patterns.
        Does NOT execute any scripts or EJS.
        """
        variables: dict[str, Any] = {}

        # Check for extensions.tavern_helper for MVU schema hints
        extensions = card_data.get("extensions", {})
        if isinstance(extensions, dict):
            tavern = extensions.get("tavern_helper", {})
            if isinstance(tavern, dict):
                # Look for initial variable definitions
                state_data = tavern.get("state") or tavern.get("variables") or {}
                if isinstance(state_data, dict) and state_data:
                    variables = state_data
                    diagnostics.append({
                        "code": "vars_from_tavern_helper",
                        "message": f"Extracted {len(state_data)} variable groups from tavern_helper",
                        "severity": "info",
                    })

        # Check for data.initial_variables or data.state
        data = card_data.get("data", card_data)
        if isinstance(data, dict):
            for key in ("initial_variables", "initial_state", "state", "variables"):
                candidate = data.get(key)
                if isinstance(candidate, dict) and candidate and not variables:
                    variables = candidate
                    diagnostics.append({
                        "code": f"vars_from_data_{key}",
                        "message": f"Extracted variables from data.{key}",
                        "severity": "info",
                    })
                    break

        return variables

    def _extract_scene_from_greeting(
        self, greeting: str, diagnostics: list
    ) -> dict[str, Any]:
        """Extract scene hints from greeting text.

        Simple pattern matching for location/time markers.
        """
        scene: dict[str, Any] = {
            "location": "",
            "time": "",
            "activeCharacterIds": [],
            "lastAcceptedTurn": "",
        }

        # Common location patterns
        location_patterns = [
            r'(?:在|来到|走进|位于|身处)\s*[「「]?\s*(.{2,15}?)[」」]?\s*(?:，|。|\.|$)',
            r'(.{2,10}(?:村|镇|城|山|河|湖|庄|院|宅|屋|室|房|楼|阁|庙|寺|洞|谷|林|))',
        ]
        for pattern in location_patterns:
            match = re.search(pattern, greeting)
            if match:
                scene["location"] = match.group(1).strip()
                break

        # Time patterns
        time_patterns = [
            r'(清晨|黎明|上午|中午|下午|傍晚|黄昏|晚上|夜晚|深夜|午夜|凌晨)',
            r'(第[一二三四五六七八九十\d]+天|次日|几天后)',
        ]
        for pattern in time_patterns:
            match = re.search(pattern, greeting)
            if match:
                scene["time"] = match.group(1).strip()
                break

        if scene["location"]:
            diagnostics.append({
                "code": "scene_from_greeting",
                "message": f"Location: {scene['location']}, Time: {scene['time'] or 'unknown'}",
                "severity": "info",
            })

        return scene


class AWPConditionalWorldbook:
    """Deterministic condition evaluation against card state.

    Evaluates worldbook entry conditions against the current card state.
    Never calls LLM, never executes JavaScript/EJS/eval.

    Inputs:
        card_state_json: Current CardState JSON
        worldbook_json: Worldbook entries JSON (from card import)
        player_input: Current player input
        active_character_ids_json: Optional list of active character IDs
        current_scene_json: Optional current scene state

    Outputs:
        active_entries_json: Entries whose conditions are met
        blocked_entries_json: Entries whose conditions are not met
        condition_evaluation_json: Full evaluation result
        debug_json: Debug information
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "card_state_json": ("STRING", {
                    "multiline": True,
                    "default": "{}",
                    "placeholder": "CardState JSON（来自 AWPCardStateInit）",
                    "forceInput": True,
                }),
                "worldbook_json": ("STRING", {
                    "multiline": True,
                    "default": "[]",
                    "placeholder": "世界书条目 JSON（来自角色卡导入）",
                    "forceInput": True,
                }),
                "player_input": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "玩家本轮输入",
                    "forceInput": True,
                }),
            },
            "optional": {
                "active_character_ids_json": ("STRING", {
                    "multiline": True,
                    "default": "[]",
                    "placeholder": "当前在场角色 ID 列表 JSON",
                    "forceInput": True,
                }),
                "current_scene_json": ("STRING", {
                    "multiline": True,
                    "default": "{}",
                    "placeholder": "当前场景状态 JSON",
                    "forceInput": True,
                }),
                "deferred_worldbook_json": ("STRING", {
                    "multiline": True,
                    "default": "[]",
                    "placeholder": "Deferred 世界书条目 JSON（含未支持条件）",
                    "forceInput": True,
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("active_entries_json", "blocked_entries_json", "condition_evaluation_json", "debug_json")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/状态"

    def execute(
        self,
        card_state_json: str,
        worldbook_json: str,
        player_input: str,
        active_character_ids_json: str = "[]",
        current_scene_json: str = "{}",
        deferred_worldbook_json: str = "[]",
    ):
        # Parse inputs
        card_state = CardState.from_json(card_state_json)
        worldbook = self._safe_json_list(worldbook_json)
        deferred = self._safe_json_list(deferred_worldbook_json)
        active_chars = self._safe_json_list(active_character_ids_json)
        scene = self._safe_json(current_scene_json, {})

        debug: dict[str, Any] = {
            "stateVariables": bool(card_state.variables),
            "worldbookEntries": len(worldbook),
            "deferredEntries": len(deferred),
            "activeChars": len(active_chars),
            "playerInputLen": len(player_input),
        }

        # Build evaluation context (merged state for condition resolution)
        eval_context = self._build_eval_context(card_state, scene, active_chars)

        # Evaluate all entries
        active_entries: list[dict[str, Any]] = []
        blocked_entries: list[dict[str, Any]] = []
        evaluation_details: list[dict[str, Any]] = []
        eligible_event_ids: list[str] = []
        blocked_event_ids: list[str] = []
        active_stage_ids: list[str] = []
        forbidden_stage_moves: list[str] = []

        # Process normal worldbook entries
        for entry in worldbook:
            if not isinstance(entry, dict):
                continue
            result = self._evaluate_entry(entry, eval_context, player_input)
            evaluation_details.append(result)
            if result["status"] == "active":
                active_entries.append(entry)
                eid = self._extract_event_id(entry)
                if eid:
                    eligible_event_ids.append(eid)
                stage = entry.get("metadata", {}).get("stage", "")
                if stage and stage not in active_stage_ids:
                    active_stage_ids.append(stage)
            else:
                blocked_entries.append(entry)
                if result.get("reasonCode") == "event_already_consumed":
                    eid = self._extract_event_id(entry)
                    if eid:
                        blocked_event_ids.append(eid)

        # Process deferred entries (from card import)
        collected_diagnostics: list[dict[str, Any]] = []
        for entry in deferred:
            if not isinstance(entry, dict):
                continue
            result = self._evaluate_deferred_entry(entry, eval_context, player_input)
            evaluation_details.append(result)
            # Collect diagnostics from deferred entry evaluation
            entry_diags = result.get("diagnostics")
            if isinstance(entry_diags, list):
                collected_diagnostics.extend(entry_diags)
            # Merge result metadata into the entry for downstream consumers
            enriched = dict(entry)
            for key in ("status", "reasonCode", "source", "activeBranches",
                        "diagnostics", "untranslatedCount", "untranslatedReasons",
                        "translatedCount", "groupCount"):
                if key in result and result[key] is not None:
                    enriched[key] = result[key]
            if result["status"] == "active":
                active_entries.append(enriched)
            else:
                blocked_entries.append(enriched)

        result_obj = ConditionEvaluationResult(
            activeEntries=active_entries,
            blockedEntries=blocked_entries,
            conditionEvaluation=evaluation_details,
            eligibleEventIds=eligible_event_ids,
            blockedEventIds=blocked_event_ids,
            activeStageIds=active_stage_ids,
            forbiddenStageMoves=forbidden_stage_moves,
            diagnostics=collected_diagnostics,
        )

        debug["activeCount"] = len(active_entries)
        debug["blockedCount"] = len(blocked_entries)
        debug["eligibleEvents"] = len(eligible_event_ids)

        return (
            json.dumps(active_entries, ensure_ascii=False, indent=2),
            json.dumps(blocked_entries, ensure_ascii=False, indent=2),
            result_obj.to_json(),
            json.dumps(debug, ensure_ascii=False, indent=2),
        )

    def _safe_json(self, text: str, default: Any) -> Any:
        try:
            result = json.loads(text) if text and text.strip() else default
            return result if isinstance(result, type(default)) else default
        except (json.JSONDecodeError, TypeError):
            return default

    def _safe_json_list(self, text: str) -> list:
        try:
            result = json.loads(text) if text and text.strip() else []
            return result if isinstance(result, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    def _build_eval_context(
        self,
        state: CardState,
        scene: dict[str, Any],
        active_chars: list,
    ) -> dict[str, Any]:
        """Build the evaluation context by merging state variables and scene."""
        context: dict[str, Any] = {}

        # Add state variables at root level for path resolution
        if state.variables:
            context.update(state.variables)

        # Add event flags
        if state.eventFlags:
            context["eventFlags"] = state.eventFlags

        # Add active stage IDs
        context["activeStageIds"] = state.activeStageIds

        # Add scene state
        if scene:
            context["scene"] = scene
        elif state.sceneState:
            context["scene"] = state.sceneState

        # Add active character IDs
        context["activeCharacterIds"] = active_chars or state.sceneState.get("activeCharacterIds", [])

        return context

    def _evaluate_entry(
        self,
        entry: dict[str, Any],
        context: dict[str, Any],
        player_input: str,
    ) -> dict[str, Any]:
        """Evaluate a single worldbook entry's conditions."""
        entry_id = str(entry.get("id", entry.get("entryId", "")))
        title = str(entry.get("title", entry.get("comment", "")))

        # Check if disabled
        meta = entry.get("metadata", {})
        if isinstance(meta, dict):
            if meta.get("enabled") is False or meta.get("disable") is True:
                return {
                    "entryId": entry_id,
                    "title": title,
                    "status": "blocked",
                    "reasonCode": "entry_disabled",
                }

        # Check if constant (always active)
        is_constant = bool(
            entry.get("constant") or
            (isinstance(meta, dict) and meta.get("constant"))
        )
        if is_constant:
            return {
                "entryId": entry_id,
                "title": title,
                "status": "active",
                "reasonCode": "constant",
            }

        # Check for keyword activation (simple)
        keys = entry.get("keys") or entry.get("tags") or []
        if isinstance(keys, str):
            keys = [keys]
        if isinstance(meta, dict):
            meta_keys = meta.get("keywords") or meta.get("tags") or []
            if isinstance(meta_keys, list):
                keys = list(set(keys + meta_keys))

        if keys:
            search_text = player_input.lower()
            matched_key = None
            for key in keys:
                if isinstance(key, str) and key.lower() in search_text:
                    matched_key = key
                    break
            if matched_key:
                return {
                    "entryId": entry_id,
                    "title": title,
                    "status": "active",
                    "reasonCode": "keyword_match",
                    "matchedKey": matched_key,
                }

        # Check for condition AST
        condition_data = entry.get("conditionAst") or (meta.get("conditionAst") if isinstance(meta, dict) else None)
        if condition_data:
            if isinstance(condition_data, dict):
                node = ConditionNode.from_dict(condition_data)
                ok, reason = evaluate_condition(node, context)
                return {
                    "entryId": entry_id,
                    "title": title,
                    "status": "active" if ok else "blocked",
                    "reasonCode": reason if not ok else "condition_met",
                }

        # Check for event consumption
        event_id = self._extract_event_id(entry)
        if event_id and isinstance(context.get("eventFlags"), dict):
            if context["eventFlags"].get(event_id):
                return {
                    "entryId": entry_id,
                    "title": title,
                    "status": "blocked",
                    "reasonCode": "event_already_consumed",
                }

        # No condition → check if selective
        is_selective = bool(
            entry.get("selective") or
            (isinstance(meta, dict) and meta.get("selective"))
        )
        if is_selective and not keys:
            # Selective entry with no keys → blocked
            return {
                "entryId": entry_id,
                "title": title,
                "status": "blocked",
                "reasonCode": "selective_no_keys",
            }

        # Default: if has keys but no match, blocked; if no keys and not selective, active
        if keys:
            return {
                "entryId": entry_id,
                "title": title,
                "status": "blocked",
                "reasonCode": "no_keyword_match",
            }

        return {
            "entryId": entry_id,
            "title": title,
            "status": "active",
            "reasonCode": "no_condition",
        }

    def _evaluate_deferred_entry(
        self,
        entry: dict[str, Any],
        context: dict[str, Any],
        player_input: str,
    ) -> dict[str, Any]:
        """Evaluate a deferred entry (from card import with unsupported conditions).

        P4D-1A: Attempts legacy EJS→AST translation before falling back.
        P4D-1C: Correct first-match-wins semantics per branchGroup.
        """
        from ..card.card_state_contract import (
            translate_legacy_ejs_conditions,
            evaluate_condition,
            ConditionNode,
        )

        entry_id = str(entry.get("sourceEntryUid", entry.get("id", "")))
        title = str(entry.get("title", entry.get("comment", "")))

        # Check for condition AST (may have been parsed during import)
        condition_data = entry.get("conditionAst")
        if condition_data and isinstance(condition_data, dict):
            node = ConditionNode.from_dict(condition_data)
            ok, reason = evaluate_condition(node, context)
            return {
                "entryId": entry_id,
                "title": title,
                "status": "active" if ok else "blocked",
                "reasonCode": reason if not ok else "condition_met",
                "source": "deferred",
            }

        # P4D-1A: Try legacy EJS→AST translation on original content
        original_content = entry.get("originalContent", "") or entry.get("content", "")
        if original_content and ("getvar" in original_content or "<%" in original_content):
            translations = translate_legacy_ejs_conditions(original_content)
            if translations:
                translated_branches = [t for t in translations if t["status"] == "translated"]
                untranslated = [t for t in translations if t["status"] != "translated"]

                # Check if ALL branches are deferred due to unsupported else
                all_else_unsupported = (
                    untranslated
                    and not translated_branches
                    and all(
                        t.get("reason") == "unsupported_else_branch"
                        for t in untranslated
                    )
                )
                if all_else_unsupported:
                    return {
                        "entryId": entry_id,
                        "title": title,
                        "status": "blocked",
                        "reasonCode": "unsupported_else_branch",
                        "source": "deferred",
                        "diagnostics": [{
                            "code": "unsupported_else_branch",
                            "entryId": entry_id,
                            "branchCount": len(untranslated),
                            "severity": "warning",
                        }],
                    }

                if translated_branches:
                    result = self._evaluate_branch_groups(
                        translated_branches, context, entry_id, title,
                    )
                    # Attach untranslated info if present
                    if untranslated:
                        result["untranslatedCount"] = len(untranslated)
                        result["untranslatedReasons"] = [
                            t.get("reason", "") for t in untranslated[:3]
                        ]
                    return result

                # None could be translated
                if untranslated:
                    return {
                        "entryId": entry_id,
                        "title": title,
                        "status": "blocked",
                        "reasonCode": "partial_translation",
                        "source": "deferred",
                        "translatedCount": 0,
                        "untranslatedCount": len(untranslated),
                        "untranslatedReasons": [
                            t.get("reason", "") for t in untranslated[:3]
                        ],
                    }

        # No parseable condition → stays deferred/unsupported
        return {
            "entryId": entry_id,
            "title": title,
            "status": "blocked",
            "reasonCode": "unsupported_condition_syntax",
            "source": "deferred",
        }

    def _evaluate_branch_groups(
        self,
        translated_branches: list[dict[str, Any]],
        context: dict[str, Any],
        entry_id: str,
        title: str,
    ) -> dict[str, Any]:
        """Evaluate translated branches with correct branchGroup semantics.

        Rules:
        - Branches are grouped by branchGroupId.
        - Within each group, branches are sorted by branchOrder ascending.
        - First-match-wins within each group (if/else-if semantics).
        - Different groups are independent; each can activate one branch.
        - Invalid branchOrder (missing, duplicate, non-integer) → diagnostic,
          that group is fail-safe blocked.
        - Entry is active if ANY group has a matching branch.
        """
        from ..card.card_state_contract import evaluate_condition, ConditionNode

        # Group branches by branchGroupId
        groups: dict[str, list[dict[str, Any]]] = {}
        for branch in translated_branches:
            gid = branch.get("branchGroupId", "__ungrouped__")
            groups.setdefault(gid, []).append(branch)

        diagnostics: list[dict[str, Any]] = []
        active_groups: list[dict[str, Any]] = []

        for gid, branches in groups.items():
            # Check if any branch in this group is deferred_unsupported
            # If so, the ENTIRE group is deferred (no partial activation)
            unsupported_branches = [
                b for b in branches if b.get("status") == "deferred_unsupported"
            ]
            if unsupported_branches:
                reasons = set()
                for b in unsupported_branches:
                    reasons.add(b.get("reason", "unsupported"))
                diagnostics.append({
                    "code": "unsupported_else_branch",
                    "branchGroupId": gid,
                    "reasons": sorted(reasons),
                    "branchCount": len(branches),
                    "unsupportedCount": len(unsupported_branches),
                    "severity": "warning",
                })
                continue  # Skip this entire group

            # Validate branchOrder
            orders_valid = True
            seen_orders: set[int] = set()
            for b in branches:
                order = b.get("branchOrder")
                if not isinstance(order, int) or order < 0:
                    diagnostics.append({
                        "code": "invalid_branch_order",
                        "branchGroupId": gid,
                        "branchOrder": order,
                        "severity": "warning",
                    })
                    orders_valid = False
                    break
                if order in seen_orders:
                    diagnostics.append({
                        "code": "duplicate_branch_order",
                        "branchGroupId": gid,
                        "branchOrder": order,
                        "severity": "warning",
                    })
                    orders_valid = False
                    break
                seen_orders.add(order)

            if not orders_valid:
                # Fail-safe: this group is blocked, but other groups continue
                diagnostics.append({
                    "code": "branch_group_fail_safe_blocked",
                    "branchGroupId": gid,
                    "severity": "warning",
                })
                continue

            # Sort by branchOrder ascending — first match wins
            sorted_branches = sorted(branches, key=lambda b: b["branchOrder"])

            group_match = None
            for branch in sorted_branches:
                ast_dict = branch.get("ast")
                if not ast_dict:
                    continue
                node = ConditionNode.from_dict(ast_dict)
                ok, reason = evaluate_condition(node, context)
                if ok:
                    group_match = branch
                    break  # first match wins — skip remaining in this group

            if group_match:
                active_groups.append(group_match)

        if active_groups:
            # Entry is active — report which groups matched
            return {
                "entryId": entry_id,
                "title": title,
                "status": "active",
                "reasonCode": "legacy_condition_translated",
                "source": "deferred",
                "activeBranches": [
                    {
                        "branchGroupId": b.get("branchGroupId", ""),
                        "branchOrder": b.get("branchOrder", -1),
                        "branchIndex": b.get("branch_index", -1),
                    }
                    for b in active_groups
                ],
                "diagnostics": diagnostics if diagnostics else None,
            }
        else:
            return {
                "entryId": entry_id,
                "title": title,
                "status": "blocked",
                "reasonCode": "condition_false",
                "source": "deferred",
                "groupCount": len(groups),
                "diagnostics": diagnostics if diagnostics else None,
            }

    def _extract_event_id(self, entry: dict[str, Any]) -> str:
        """Extract event ID from entry metadata."""
        meta = entry.get("metadata", {})
        if isinstance(meta, dict):
            eid = meta.get("eventId") or meta.get("event_id")
            if eid:
                return str(eid)
        # Try from tags
        tags = entry.get("tags", [])
        for tag in tags:
            if isinstance(tag, str) and tag.startswith("event_"):
                return tag
        return ""


class AWPCardStateCommit:
    """P4D-2A: Deterministic, LLM-free, atomic CardState commit.

    This is the ONLY sanctioned write path from a candidate patch into the
    CardStateStore. It is not a Writer and not a state proposer.

    Pipeline:
        existing CardState
        + CandidateCardStatePatch
        + SideEffectDecision (card_state_decision, awp.rp.side-effect-card-state.v1)
        + expected revision
        → strict validation (gate + patch + atomic apply)
        → atomic store write (revision bump + patch-id log, one transaction)
        → updated state + commit result + diagnostics

    Gate is an ABSOLUTE precondition. allow_manual_commit never bypasses the
    QualityGate / SideEffectDecision; it only permits commitPolicy="manual"
    patches through (a future human-approval mode).

    expected_revision resolution (deterministic, no guessing):
        1. explicit node input expected_revision (>= 0)
        2. patch.expectedRevision (>= 0)
        3. card_state.revision
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "card_state_json": ("STRING", {
                    "multiline": True,
                    "default": "{}",
                    "placeholder": "当前 CardState JSON",
                    "forceInput": True,
                }),
                "candidate_card_state_patch_json": ("STRING", {
                    "multiline": True,
                    "default": "{}",
                    "placeholder": "CandidateCardStatePatch JSON（含 patchId/expectedRevision）",
                    "forceInput": True,
                }),
                "side_effect_decision_json": ("STRING", {
                    "multiline": True,
                    "default": "{}",
                    "placeholder": "AWPSideEffectDecision 的 card_state_decision 输出",
                    "forceInput": True,
                }),
            },
            "optional": {
                "expected_revision": ("INT", {
                    "default": -1,
                    "tooltip": "显式期望 revision（>=0 生效；-1 表示未提供，改用 patch/card_state）",
                }),
                "allow_manual_commit": ("BOOLEAN", {"default": False}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("updated_card_state_json", "commit_result_json", "diagnostics_json")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/状态"

    _SIDE_EFFECT_SCHEMA = "awp.rp.side-effect-card-state.v1"

    def execute(
        self,
        card_state_json: str,
        candidate_card_state_patch_json: str,
        side_effect_decision_json: str,
        expected_revision: int = -1,
        allow_manual_commit: bool = False,
    ):
        diagnostics: list[dict[str, Any]] = []

        card_state = CardState.from_json(card_state_json)

        result: dict[str, Any] = {
            "schemaId": COMMIT_RESULT_SCHEMA,
            "status": "invalid_patch",
            "cardId": card_state.cardId,
            "sessionId": card_state.sessionId,
            "previousRevision": card_state.revision,
            "currentRevision": card_state.revision,
            "patchId": "",
            "appliedOperationCount": 0,
            "reasonCodes": [],
        }

        def reject(status: str, reason_codes: list[str], message: str = "") -> tuple:
            result["status"] = status
            result["reasonCodes"] = reason_codes
            diag: dict[str, Any] = {
                "code": status,
                "severity": "warning",
                "reasonCodes": reason_codes,
            }
            if message:
                diag["message"] = message
            diagnostics.append(diag)
            # On rejection the store is untouched; return the original state.
            return (card_state.to_json(), json.dumps(result, ensure_ascii=False),
                    json.dumps(diagnostics, ensure_ascii=False))

        # ── 1. Gate: side_effect_decision must be present, valid, and allow commit ──
        sed = self._safe_json(side_effect_decision_json, None)
        if not isinstance(sed, dict) or not sed:
            return reject(
                "rejected_by_gate",
                ["side_effect_decision_missing_or_invalid"],
                "side_effect_decision is missing or invalid",
            )

        sed_schema = sed.get("schemaId", "")
        if sed_schema != self._SIDE_EFFECT_SCHEMA:
            return reject(
                "rejected_by_gate",
                ["side_effect_decision_schema_mismatch"],
                f"expected {self._SIDE_EFFECT_SCHEMA}, got {sed_schema!r}",
            )

        if sed.get("reason") == "quality-gate-rejected" or not sed.get("allowCardStateCommit", False):
            # Distinguish quality-gate rejection from side-effect disallowal.
            if sed.get("reason") == "quality-gate-rejected":
                rc = ["quality_gate_not_accepted"]
            else:
                rc = ["side_effect_decision_disallows_commit"]
            return reject(
                "rejected_by_gate",
                rc,
                "gate precondition not satisfied",
            )

        # allow_manual_commit may never bypass the gate (already enforced above).

        # ── 2. Candidate patch: present + valid schemaId + identity match ──
        patch_data = self._safe_json(candidate_card_state_patch_json, None)
        if not isinstance(patch_data, dict) or not patch_data:
            return reject(
                "invalid_patch",
                ["candidate_patch_missing_or_invalid"],
                "candidate patch is missing or invalid",
            )

        if patch_data.get("schemaId") != CANDIDATE_PATCH_SCHEMA:
            return reject(
                "invalid_patch",
                ["patch_schema_id_mismatch"],
                f"expected {CANDIDATE_PATCH_SCHEMA}",
            )

        patch = CandidateCardStatePatch.from_dict(patch_data)

        if not patch.cardId or not patch.sessionId:
            return reject("invalid_patch", ["patch_missing_identity"])

        if patch.cardId != card_state.cardId:
            return reject(
                "invalid_patch",
                [f"cardId_mismatch:patch={patch.cardId}:state={card_state.cardId}"],
            )
        if patch.sessionId != card_state.sessionId:
            return reject(
                "invalid_patch",
                [f"sessionId_mismatch:patch={patch.sessionId}:state={card_state.sessionId}"],
            )

        result["cardId"] = patch.cardId
        result["sessionId"] = patch.sessionId

        # ── 3. commitPolicy gate ──
        policy = patch.commitPolicy
        if policy == "auto":
            pass
        elif policy == "manual":
            if not allow_manual_commit:
                return reject(
                    "rejected_by_gate",
                    ["commit_policy_disallow"],
                    "commitPolicy='manual' requires allow_manual_commit=True",
                )
        else:  # "pending" or unknown
            return reject(
                "rejected_by_gate",
                ["commit_policy_disallow"],
                f"commitPolicy={policy!r} does not allow automatic commit",
            )

        # ── 4. Stable patchId required for idempotency ──
        if not patch.patchId:
            return reject("invalid_patch", ["missing_patch_id"])

        result["patchId"] = patch.patchId

        # ── 5. Patch structural validation ──
        valid, errors = validate_candidate_patch(patch, card_state)
        if not valid:
            return reject("invalid_patch", errors, "patch validation failed")

        # ── 6. Strict atomic apply (in-memory; no store write yet) ──
        new_state, apply_errors, applied_count = apply_commit_operations_strict(
            card_state, patch.operations,
        )
        if new_state is None:
            return reject("invalid_patch", apply_errors, "strict patch application rejected")

        result["appliedOperationCount"] = applied_count

        # ── 7. Resolve expected revision (deterministic rule) ──
        if expected_revision is not None and expected_revision >= 0:
            eff_expected = expected_revision
        elif patch.expectedRevision is not None and patch.expectedRevision >= 0:
            eff_expected = patch.expectedRevision
        else:
            eff_expected = card_state.revision

        # ── 8. Atomic store commit ──
        patch_hash = compute_patch_hash(patch)
        store = CardStateStore()
        commit_outcome = store.commit_patch(
            card_id=patch.cardId,
            session_id=patch.sessionId,
            new_state=new_state,
            expected_revision=eff_expected,
            patch_id=patch.patchId,
            patch_hash=patch_hash,
        )

        status = commit_outcome["status"]
        result["status"] = status
        result["reasonCodes"] = commit_outcome.get("reasonCodes", [])

        if status == "committed":
            result["previousRevision"] = commit_outcome["previousRevision"]
            result["currentRevision"] = commit_outcome["currentRevision"]
            diagnostics.append({
                "code": "committed",
                "severity": "info",
                "previousRevision": result["previousRevision"],
                "currentRevision": result["currentRevision"],
                "appliedOperationCount": applied_count,
                "message": (
                    f"patch {patch.patchId} committed "
                    f"(rev {result['previousRevision']}→{result['currentRevision']})"
                ),
            })
            updated = store.load(patch.cardId, patch.sessionId) or new_state
            return (
                updated.to_json(),
                json.dumps(result, ensure_ascii=False),
                json.dumps(diagnostics, ensure_ascii=False),
            )

        if status == "idempotent_replay":
            result["previousRevision"] = commit_outcome.get("previousRevision", card_state.revision)
            result["currentRevision"] = commit_outcome.get("currentRevision", card_state.revision)
            result["appliedOperationCount"] = 0
            diagnostics.append({
                "code": "idempotent_replay",
                "severity": "info",
                "patchId": patch.patchId,
                "currentRevision": result["currentRevision"],
                "message": f"patch {patch.patchId} already applied; no rewrite",
            })
            updated = store.load(patch.cardId, patch.sessionId) or card_state
            return (
                updated.to_json(),
                json.dumps(result, ensure_ascii=False),
                json.dumps(diagnostics, ensure_ascii=False),
            )

        # stale_revision | patch_id_conflict | store_error
        if "previousRevision" in commit_outcome:
            result["previousRevision"] = commit_outcome["previousRevision"]
        if "currentRevision" in commit_outcome and commit_outcome["currentRevision"] is not None:
            result["currentRevision"] = commit_outcome["currentRevision"]
        diagnostics.append({
            "code": status,
            "severity": "warning",
            "reasonCodes": result["reasonCodes"],
            "message": f"commit not applied: {status}",
        })
        # Store untouched — return original state.
        return (
            card_state.to_json(),
            json.dumps(result, ensure_ascii=False),
            json.dumps(diagnostics, ensure_ascii=False),
        )

    @staticmethod
    def _safe_json(text: str, default: Any) -> Any:
        try:
            if not text or not text.strip():
                return default
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return default
