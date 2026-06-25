"""
MVU (MagVarUpdate) Node — Execute variable updates from AI output.

This is the ComfyUI-native MVU node. It takes the AI's response text,
extracts MVU commands (_.set(), _.add(), <JSONPatch>, <UpdateVariable>),
executes them against the current variable state, and outputs the updated
state plus matched worldbook entries for the next turn's context.

Designed to be placed AFTER the MainAgent node in a ComfyUI workflow:
  MainAgent → AWPMVUNode → (next turn re-injection)
"""

import json
from typing import Any

from ..mvu.engine import (
    Command,
    SchemaNode,
    audit_variables,
    execute_commands,
    extract_commands,
    generate_schema,
    validate_command,
)
from ..mvu.matcher import match_worldbook_by_variables
from ..mvu.checker import generate_variable_checklist


class AWPMVUNode:
    """执行 AI 回复文本中的 MVU 变量更新命令。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "ai_response": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "AI 回复文本（含 _.set() / <UpdateVariable> 命令）",
                    "forceInput": True,
                }),
                "current_variables": ("STRING", {
                    "multiline": True,
                    "default": "{}",
                    "placeholder": "当前变量状态 JSON (stat_data)",
                    "forceInput": True,
                }),
            },
            "optional": {
                "worldbook_index": ("STRING", {
                    "multiline": True,
                    "default": "[]",
                    "placeholder": "世界书索引 JSON（用于变量驱动匹配）",
                    "forceInput": True,
                }),
                "enable_worldbook_match": ("BOOLEAN", {
                    "default": True,
                    "label": "变量驱动世界书匹配",
                }),
                "enable_validation": ("BOOLEAN", {
                    "default": True,
                    "label": "Schema 验证",
                }),
                "top_n_matches": ("INT", {
                    "default": 3,
                    "min": 1,
                    "max": 10,
                    "label": "最多匹配条目数",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("更新后变量", "变更记录", "匹配的世界书", "变量清单", "审计报告")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/MVU"

    def execute(
        self,
        ai_response: str,
        current_variables: str,
        worldbook_index: str = "[]",
        enable_worldbook_match: bool = True,
        enable_validation: bool = True,
        top_n_matches: int = 3,
    ) -> tuple[str, str, str, str, str]:
        """Execute MVU pipeline on AI response.

        Returns:
            (updated_variables_json, changes_json, matched_worldbook_json,
             checklist_json, audit_json)
        """
        # ── Parse current state ──
        try:
            prev_data: dict[str, Any] = json.loads(current_variables) if current_variables.strip() else {}
        except json.JSONDecodeError:
            prev_data = {}
        if not isinstance(prev_data, dict):
            prev_data = {}

        # ── Parse worldbook index ──
        wb_index: list[dict[str, Any]] = []
        if worldbook_index.strip():
            try:
                wb_index = json.loads(worldbook_index)
            except json.JSONDecodeError:
                wb_index = []
        if not isinstance(wb_index, list):
            wb_index = []

        # ── Step 1: Extract commands ──
        commands: list[Command] = extract_commands(ai_response)

        # ── Step 2: Validate (optional) ──
        validation_errors: list[dict[str, Any]] = []
        if enable_validation and commands:
            schema = generate_schema(prev_data) if prev_data else None
            for cmd in commands:
                ok, err = validate_command(cmd, schema)
                if not ok:
                    validation_errors.append({
                        "command": cmd.full_match[:200] if cmd.full_match else str(cmd.args),
                        "error": err,
                    })

        # ── Step 3: Execute commands ──
        if commands:
            new_data, changes = execute_commands(prev_data, commands)
        else:
            new_data = prev_data
            changes = {}

        # ── Step 4: Audit ──
        audit = audit_variables(prev_data, new_data)
        if validation_errors:
            audit["_validation_errors"] = validation_errors

        # ── Step 5: Worldbook matching ──
        matched_entries: list[dict[str, Any]] = []
        if enable_worldbook_match and changes:
            matched_entries = match_worldbook_by_variables(
                audit=audit,
                worldbook_index=wb_index,
                initvar=prev_data,
                top_n=top_n_matches,
            )

        # ── Step 6: Variable checklist ──
        checklist = generate_variable_checklist(new_data, audit)

        # ── Metadata ──
        metadata = {
            "commands_extracted": len(commands),
            "commands_executed": len(changes),
            "validation_errors": len(validation_errors),
            "matches_found": len(matched_entries),
            "total_paths": checklist.get("total_paths", 0),
        }
        checklist["_metadata"] = metadata

        return (
            json.dumps(new_data, ensure_ascii=False, indent=2),
            json.dumps(changes, ensure_ascii=False, indent=2),
            json.dumps(matched_entries, ensure_ascii=False, indent=2),
            json.dumps(checklist, ensure_ascii=False, indent=2),
            json.dumps(audit, ensure_ascii=False, indent=2),
        )


class AWPMVUMacroResolver:
    """解析文本中的 {{getvar}} / {{formatvar}} 宏为变量值。

    此节点可放在最终输出之前，用于解析引用实时变量值的模板宏。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "含 {{getvar::path}} 宏的文本",
                    "forceInput": True,
                }),
                "variables": ("STRING", {
                    "multiline": True,
                    "default": "{}",
                    "placeholder": "变量 JSON (stat_data)",
                    "forceInput": True,
                }),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("解析后文本",)
    FUNCTION = "execute"
    CATEGORY = "AWP RP/MVU"

    def execute(self, text: str, variables: str) -> tuple[str]:
        from ..mvu.engine import resolve_macros

        try:
            data = json.loads(variables) if variables.strip() else {}
        except json.JSONDecodeError:
            data = {}

        resolved = resolve_macros(text, data)
        return (resolved,)
