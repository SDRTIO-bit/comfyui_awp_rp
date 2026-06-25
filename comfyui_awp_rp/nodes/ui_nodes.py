"""UI helper nodes — let users view and edit data without leaving ComfyUI.

These nodes implement the "节点即 UI" principle: users should not need
to open files or folders to manage their RP/novel data. Everything is
editable through nodes on the canvas.
"""

import json
import os
import uuid
from typing import Any

from ..core.store import get_store
from ..core.config import get_config
from ..memory.long_term import LongTermMemory
from ..card.import_card import CardImporter
from ..preset.preset import PresetManager
from ..tools.skill_manager import SkillManager
from ..tools.registry import get_global_registry


class AWPMemoryList:
    """列出并查看长期记忆，支持筛选。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "namespace": ("STRING", {
                    "default": "default",
                    "placeholder": "记忆命名空间（通常是session_id）",
                }),
            },
            "optional": {
                "tags_any": ("STRING", {"default": "", "placeholder": "标签筛选（逗号分隔）"}),
                "type_filter": ("STRING", {"default": "", "placeholder": "类型筛选"}),
                "limit": ("INT", {"default": 20, "min": 1, "max": 100}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("记忆文本", "记忆JSON")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/记忆"
    OUTPUT_NODE = True

    def execute(self, namespace: str, tags_any: str = "", type_filter: str = "", limit: int = 20):
        memory = LongTermMemory()
        tags = [t.strip() for t in tags_any.split(",") if t.strip()] if tags_any else None
        records = memory.query(
            namespace=namespace,
            tags_any=tags,
            type_filter=type_filter if type_filter else None,
            limit=limit,
        )
        if not records:
            return ("(No memories found)", "[]")
        lines: list[str] = []
        for r in records:
            tags_str = f" [{', '.join(r.tags)}]" if r.tags else ""
            imp_str = f" (importance={r.importance})" if r.importance is not None else ""
            lines.append(f"[{r.title or r.id}]{tags_str}{imp_str}")
            lines.append(f"  {r.content}")
            lines.append("")
        text = "\n".join(lines)
        j = json.dumps([
            {"id": r.id, "title": r.title, "content": r.content, "type": r.type,
             "tags": r.tags, "importance": r.importance}
            for r in records
        ], ensure_ascii=False, indent=2)
        return (text, j)


class AWPMemoryEdit:
    """编辑或删除记忆记录。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "namespace": ("STRING", {"default": "default", "placeholder": "记忆命名空间"}),
                "operation": (["update", "delete"], {"default": "update"}),
                "memory_id": ("STRING", {"default": "", "placeholder": "记忆ID"}),
            },
            "optional": {
                "content": ("STRING", {"multiline": True, "default": "", "placeholder": "新内容"}),
                "title": ("STRING", {"default": "", "placeholder": "新标题"}),
                "tags": ("STRING", {"default": "", "placeholder": "新标签（逗号分隔）"}),
                "importance": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.1}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("状态",)
    FUNCTION = "execute"
    CATEGORY = "AWP RP/记忆"
    OUTPUT_NODE = True

    def execute(
        self,
        namespace: str,
        operation: str,
        memory_id: str,
        content: str = "",
        title: str = "",
        tags: str = "",
        importance: float = 0.5,
    ):
        if not memory_id:
            return ("Error: memory_id is required",)
        store = get_store()
        if operation == "delete":
            count = store.delete_memory(namespace, [memory_id])
            return (f"Deleted {count} memory record(s)",)
        elif operation == "update":
            # Read existing, then update
            existing = store.get_memory(namespace, memory_id)
            if not existing:
                return (f"Error: memory '{memory_id}' not found",)
            tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else existing.tags
            from ..core.types import MemoryRecord
            updated = MemoryRecord(
                id=existing.id,
                namespace=existing.namespace,
                content=content if content else existing.content,
                title=title if title else existing.title,
                type=existing.type,
                tags=tag_list,
                entity_ids=existing.entity_ids,
                importance=importance if importance != 0.5 else existing.importance,
                created_at=existing.created_at,
                updated_at="",
                metadata=existing.metadata,
            )
            store.upsert_memory(namespace, [updated])
            return (f"Updated memory: {memory_id}",)
        return ("Unknown operation",)


class AWPCardEditor:
    """查看和编辑角色卡详情。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "card_id": ("STRING", {
                    "default": "",
                    "placeholder": "角色卡ID",
                    "forceInput": True,
                }),
                "operation": (["view", "update_manifest", "update_greeting", "add_greeting"], {"default": "view"}),
            },
            "optional": {
                "manifest_json": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "更新后的 manifest JSON...",
                }),
                "greeting_id": ("STRING", {"default": "", "placeholder": "开场白ID"}),
                "greeting_content": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "开场白内容...",
                }),
                "greeting_label": ("STRING", {"default": "", "placeholder": "开场白标签"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("角色卡信息", "状态")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/角色卡"
    OUTPUT_NODE = True

    def execute(
        self,
        card_id: str,
        operation: str,
        manifest_json: str = "",
        greeting_id: str = "",
        greeting_content: str = "",
        greeting_label: str = "",
    ):
        if not card_id:
            return ("", "Error: card_id is required")
        importer = CardImporter()
        card = importer.get_card(card_id)
        if not card:
            return ("", f"Error: card '{card_id}' not found")

        if operation == "view":
            info = json.dumps({
                "card_id": card["card_id"],
                "manifest": card.get("manifest", {}),
                "greetings": card.get("greetings", []),
                "worldbook_count": len(card.get("worldbook", [])),
            }, ensure_ascii=False, indent=2)
            return (info, "OK")

        elif operation == "update_manifest":
            try:
                new_manifest = json.loads(manifest_json) if manifest_json.strip() else {}
            except json.JSONDecodeError as e:
                return ("", f"JSON error: {e}")
            # Merge with existing
            existing_manifest = card.get("manifest", {})
            existing_manifest.update(new_manifest)
            store = get_store()
            store.save_card(
                card_id=card_id,
                manifest=existing_manifest,
                greetings=card.get("greetings", []),
                worldbook=card.get("worldbook", []),
                deferred=card.get("deferred_worldbook", []),
                report=card.get("import_report", {}),
            )
            return (json.dumps(existing_manifest, ensure_ascii=False, indent=2), "Manifest updated")

        elif operation == "update_greeting":
            if not greeting_id:
                return ("", "Error: greeting_id required for update_greeting")
            greetings = card.get("greetings", [])
            updated = False
            for g in greetings:
                if g.get("greeting_id") == greeting_id:
                    if greeting_content:
                        g["content"] = greeting_content
                    if greeting_label:
                        g["label"] = greeting_label
                    updated = True
                    break
            if not updated:
                return ("", f"Greeting '{greeting_id}' not found")
            store = get_store()
            store.save_card(
                card_id=card_id,
                manifest=card.get("manifest", {}),
                greetings=greetings,
                worldbook=card.get("worldbook", []),
                deferred=card.get("deferred_worldbook", []),
                report=card.get("import_report", {}),
            )
            return (json.dumps(greetings, ensure_ascii=False, indent=2), f"Greeting '{greeting_id}' updated")

        elif operation == "add_greeting":
            if not greeting_content:
                return ("", "Error: greeting_content required for add_greeting")
            greetings = card.get("greetings", [])
            new_id = f"g{len(greetings)}"
            greetings.append({
                "greeting_id": new_id,
                "index": len(greetings),
                "label": greeting_label or f"Greeting {len(greetings)}",
                "content": greeting_content,
                "is_default": False,
            })
            store = get_store()
            store.save_card(
                card_id=card_id,
                manifest=card.get("manifest", {}),
                greetings=greetings,
                worldbook=card.get("worldbook", []),
                deferred=card.get("deferred_worldbook", []),
                report=card.get("import_report", {}),
            )
            return (json.dumps(greetings[-1], ensure_ascii=False, indent=2), f"Added greeting: {new_id}")

        return ("", "Unknown operation")


class AWPPresetEditor:
    """查看和编辑预设规则及输出合约。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "preset_id": ("STRING", {
                    "default": "rp-default-v1",
                    "placeholder": "预设ID",
                }),
                "operation": (["view", "add_rule", "remove_rule", "update_contract"], {"default": "view"}),
            },
            "optional": {
                "rule_section": (["coreRules", "styleRules", "additionalInstructions"], {"default": "coreRules"}),
                "rule_id": ("STRING", {"default": "", "placeholder": "规则ID（remove时需要）"}),
                "rule_content": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "规则内容...",
                }),
                "rule_priority": ("INT", {"default": 50, "min": 0, "max": 100}),
                "contract_json": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "Output Contract JSON...",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("预设信息", "状态")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/预设"
    OUTPUT_NODE = True

    def execute(
        self,
        preset_id: str,
        operation: str,
        rule_section: str = "coreRules",
        rule_id: str = "",
        rule_content: str = "",
        rule_priority: int = 50,
        contract_json: str = "",
    ):
        pm = PresetManager()
        preset = pm.get_preset(preset_id)
        if not preset:
            return ("", f"Error: preset '{preset_id}' not found")

        if operation == "view":
            info = {
                "id": preset.id,
                "name": preset.name,
                "prompt": {
                    k: [{"id": f.id, "content": f.content, "priority": f.priority} for f in v]
                    for k, v in (preset.prompt or {}).items()
                },
                "output_contract": {
                    "mode": preset.output_contract.mode if preset.output_contract else None,
                    "forbidden_patterns": preset.output_contract.forbidden_patterns if preset.output_contract else [],
                } if preset.output_contract else None,
            }
            return (json.dumps(info, ensure_ascii=False, indent=2), "OK")

        elif operation == "add_rule":
            if not rule_content:
                return ("", "Error: rule_content required for add_rule")
            from ..core.types import PromptFragment
            sections = preset.prompt or {}
            rules = sections.get(rule_section, [])
            rid = rule_id or f"rule_{uuid.uuid4().hex[:6]}"
            rules.append(PromptFragment(id=rid, content=rule_content, priority=rule_priority))
            sections[rule_section] = rules
            preset.prompt = sections
            pm.save_preset(preset)
            return (json.dumps({"rule_id": rid}, ensure_ascii=False), f"Added rule to {rule_section}")

        elif operation == "remove_rule":
            if not rule_id:
                return ("", "Error: rule_id required for remove_rule")
            sections = preset.prompt or {}
            rules = sections.get(rule_section, [])
            preset.prompt = {k: [r for r in v if r.id != rule_id] if k == rule_section else v for k, v in sections.items()}
            pm.save_preset(preset)
            return (json.dumps({"removed": rule_id}, ensure_ascii=False), f"Removed rule {rule_id}")

        elif operation == "update_contract":
            try:
                contract_data = json.loads(contract_json) if contract_json.strip() else {}
            except json.JSONDecodeError as e:
                return ("", f"JSON error: {e}")
            from ..core.types import OutputContract
            if preset.output_contract:
                preset.output_contract.mode = contract_data.get("mode", preset.output_contract.mode)
                preset.output_contract.forbidden_patterns = contract_data.get("forbidden_patterns", preset.output_contract.forbidden_patterns)
                preset.output_contract.allow_extra_text = contract_data.get("allow_extra_text", preset.output_contract.allow_extra_text)
            pm.save_preset(preset)
            return (json.dumps({"updated": True}, ensure_ascii=False), "Contract updated")

        return ("", "Unknown operation")


class AWPSkillManagerNode:
    """查看、添加和管理技能。为 Agent 分配技能。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "operation": (["list", "view", "add", "delete"], {"default": "list"}),
            },
            "optional": {
                "skill_id": ("STRING", {"default": "", "placeholder": "技能ID"}),
                "label_zh": ("STRING", {"default": "", "placeholder": "中文名称"}),
                "label_en": ("STRING", {"default": "", "placeholder": "英文名称"}),
                "content_zh": ("STRING", {"multiline": True, "default": "", "placeholder": "中文内容"}),
                "content_en": ("STRING", {"multiline": True, "default": "", "placeholder": "英文内容"}),
                "category": ("STRING", {"default": "general", "placeholder": "分类"}),
                "tags": ("STRING", {"default": "", "placeholder": "标签（逗号分隔）"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("技能列表文本", "技能列表JSON")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/工具"
    OUTPUT_NODE = True

    def execute(
        self,
        operation: str,
        skill_id: str = "",
        label_zh: str = "",
        label_en: str = "",
        content_zh: str = "",
        content_en: str = "",
        category: str = "general",
        tags: str = "",
    ):
        sm = SkillManager()

        if operation == "list":
            skills = sm.list_skills()
            lines: list[str] = []
            for s in skills:
                tags_str = f" [{', '.join(s.tags)}]" if s.tags else ""
                lines.append(f"[{s.skill_id}] {s.label_zh}{tags_str}")
                if s.content_zh:
                    lines.append(f"  {s.content_zh[:100]}")
                lines.append("")
            j = json.dumps([
                {"skill_id": s.skill_id, "label_zh": s.label_zh, "label_en": s.label_en,
                 "category": s.category, "tags": s.tags}
                for s in skills
            ], ensure_ascii=False, indent=2)
            return ("\n".join(lines) if lines else "(No skills)", j)

        elif operation == "view":
            if not skill_id:
                return ("Error: skill_id required", "{}")
            skill = sm.get_skill(skill_id)
            if not skill:
                return (f"Skill '{skill_id}' not found", "{}")
            info = json.dumps({
                "skill_id": skill.skill_id,
                "label_zh": skill.label_zh,
                "label_en": skill.label_en,
                "content_zh": skill.content_zh,
                "content_en": skill.content_en,
                "category": skill.category,
                "tags": skill.tags,
            }, ensure_ascii=False, indent=2)
            return (info, info)

        elif operation == "add":
            if not skill_id or not content_zh:
                return ("Error: skill_id and content_zh required", "{}")
            tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
            from ..tools.skill_manager import Skill
            skill = Skill(
                skill_id=skill_id,
                label_zh=label_zh or skill_id,
                label_en=label_en or skill_id,
                content_zh=content_zh,
                content_en=content_en,
                category=category,
                tags=tag_list,
            )
            sm.save_skill(skill)
            return (f"Saved skill: {skill_id}", json.dumps({"skill_id": skill_id}, ensure_ascii=False))

        elif operation == "delete":
            # Skills are managed in memory + data/skills/ directory
            config = get_config()
            filepath = os.path.join(config.data_dir, "skills", f"{skill_id}.json")
            if os.path.exists(filepath):
                os.remove(filepath)
                return (f"Deleted skill file: {skill_id}", json.dumps({"deleted": skill_id}, ensure_ascii=False))
            return (f"Skill file not found: {skill_id}", "{}")

        return ("Unknown operation", "{}")


class AWPToolList:
    """列出所有已注册工具及其描述。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
            "optional": {
                "category": ("STRING", {"default": "", "placeholder": "按分类筛选（留空=全部）"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("工具列表文本", "工具列表JSON")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/工具"
    OUTPUT_NODE = True

    def execute(self, category: str = ""):
        registry = get_global_registry()
        tools = registry.list_tools()
        if category:
            tools = [t for t in tools if t.category == category]
        lines: list[str] = []
        for t in tools:
            perms = ", ".join(t.required_permissions) if t.required_permissions else "none"
            lines.append(f"[{t.name}] ({t.category}) perms: {perms}")
            lines.append(f"  {t.description[:120]}")
            lines.append("")
        j = json.dumps([
            {"name": t.name, "category": t.category, "description": t.description,
             "permissions": t.required_permissions}
            for t in tools
        ], ensure_ascii=False, indent=2)
        return ("\n".join(lines) if lines else "(No tools)", j)
