"""
Worldbook node for managing dynamic knowledge base.
"""

import json
from typing import Any

from ..knowledge.worldbook import WorldbookManager


class AWPWorldbook:
    """管理会话的世界书条目。"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "session_id": ("STRING", {
                    "default": "default",
                    "placeholder": "会话ID",
                    "forceInput": True,
                }),
                "resource_ref": ("STRING", {
                    "default": "main",
                    "placeholder": "世界书资源引用",
                    "forceInput": True,
                }),
            },
            "optional": {
                "operation": (["query", "add", "update", "delete", "set_activation"], {"default": "query"}),
                "entry_id": ("STRING", {"default": "", "placeholder": "条目ID（update/delete/set_activation时需要）"}),
                "content": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "条目内容（add/update时需要）",
                }),
                "title": ("STRING", {"default": "", "placeholder": "标题"}),
                "tags": ("STRING", {"default": "", "placeholder": "标签/关键词（逗号分隔）"}),
                "priority": ("FLOAT", {"default": 0.0, "min": -10.0, "max": 10.0, "step": 0.1}),
                "activation": (["常开", "关键词触发", "关闭"], {"default": "关键词触发"}),
                "query_tags": ("STRING", {"default": "", "placeholder": "查询标签（query时过滤）"}),
                "limit": ("INT", {"default": 20, "min": 1, "max": 500}),
            },
        }
    
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("条目文本", "条目JSON")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/知识库"
    OUTPUT_NODE = True
    
    def execute(
        self,
        session_id: str,
        resource_ref: str,
        operation: str = "query",
        entry_id: str = "",
        content: str = "",
        title: str = "",
        tags: str = "",
        priority: float = 0.0,
        activation: str = "关键词触发",
        query_tags: str = "",
        limit: int = 20,
    ):
        """Execute worldbook operation."""
        manager = WorldbookManager()
        worldbook = manager.get_worldbook(session_id, resource_ref)
        
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
        
        if operation == "add":
            if not content:
                return ("Error: content is required for add operation", "[]")
            
            entry = worldbook.add_entry(
                content=content,
                title=title if title else None,
                tags=tag_list,
                priority=priority,
                metadata={"activation": activation, "enabled": activation != "关闭"},
            )
            return (f"Added entry: {entry.id}", json.dumps([{"id": entry.id, "content": entry.content, "activation": activation}], ensure_ascii=False))
        
        elif operation == "update":
            if not entry_id:
                return ("Error: entry_id is required for update operation", "[]")
            
            entry = worldbook.update_entry(
                entry_id=entry_id,
                content=content if content else None,
                title=title if title else None,
                tags=tag_list,
                priority=priority,
            )
            if entry:
                return (f"Updated entry: {entry.id}", json.dumps([{"id": entry.id, "content": entry.content}], ensure_ascii=False))
            return ("Error: entry not found", "[]")
        
        elif operation == "set_activation":
            if not entry_id:
                return ("Error: entry_id is required for set_activation", "[]")
            entry = worldbook.get_entry(entry_id)
            if not entry:
                return ("Error: entry not found", "[]")
            # Update metadata with new activation mode
            entry.metadata["activation"] = activation
            entry.metadata["enabled"] = activation != "关闭"
            if activation == "常开":
                entry.metadata["constant"] = True
                entry.metadata["selective"] = False
            elif activation == "关键词触发":
                entry.metadata["constant"] = False
                entry.metadata["selective"] = True
            else:  # 关闭
                entry.metadata["constant"] = False
                entry.metadata["selective"] = False
            worldbook.save()
            return (f"Set activation '{activation}' for entry: {entry_id}", json.dumps({"id": entry_id, "activation": activation, "enabled": activation != "关闭"}, ensure_ascii=False))
        
        elif operation == "delete":
            if not entry_id:
                return ("Error: entry_id is required for delete operation", "[]")
            
            success = worldbook.delete_entry(entry_id)
            return (f"Deleted: {success}" if success else "Entry not found", "[]")
        
        else:  # query
            query_tag_list = [t.strip() for t in query_tags.split(",") if t.strip()] if query_tags else None
            
            entries = worldbook.query(
                tags_any=query_tag_list,
                limit=limit,
            )
            
            if entries:
                lines = []
                for e in entries:
                    title_str = f"[{e.title}]" if e.title else ""
                    tags_str = f" (tags: {', '.join(e.tags)})" if e.tags else ""
                    # Show activation status
                    meta = e.metadata or {}
                    act = meta.get("activation", "关键词触发")
                    enabled = meta.get("enabled", True)
                    status = "ON" if enabled else "OFF"
                    act_icon = {"常开": "◆", "关键词触发": "◇", "关闭": "✕"}.get(act, "◇")
                    lines.append(f"[{status}] {act_icon} {act} | p={e.priority} | {title_str} {e.content[:150]}...{tags_str}")
                entries_text = "\n".join(lines)
            else:
                entries_text = "(No entries found)"
            
            entries_json = json.dumps([
                {
                    "id": e.id,
                    "title": e.title,
                    "content": e.content,
                    "tags": e.tags,
                    "priority": e.priority,
                    "activation": (e.metadata or {}).get("activation", "关键词触发"),
                    "enabled": (e.metadata or {}).get("enabled", True),
                    "constant": (e.metadata or {}).get("constant", False),
                    "selective": (e.metadata or {}).get("selective", False),
                }
                for e in entries
            ], ensure_ascii=False, indent=2)
            
            return (entries_text, entries_json)


class AWPWorldbookList:
    """渲染 SillyTavern 风格的世界书条目列表。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "worldbook_json": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "[]",
                        "placeholder": "连接角色卡或世界书输出的 worldbook_json...",
                        "forceInput": True,
                    },
                ),
            },
            "optional": {
                "enabled_only": ("BOOLEAN", {"default": False}),
                "limit": ("INT", {"default": 50, "min": 1, "max": 500}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("列表文本", "列表JSON")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/知识库"
    OUTPUT_NODE = True

    def execute(self, worldbook_json: str, enabled_only: bool = False, limit: int = 50):
        entries = _parse_worldbook_entries(worldbook_json)
        rows = []
        for entry in entries:
            metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
            enabled = bool(metadata.get("enabled", entry.get("enabled", True)))
            if enabled_only and not enabled:
                continue
            keywords = entry.get("tags") or metadata.get("keywords") or entry.get("keys") or []
            if isinstance(keywords, str):
                keywords = [keywords]
            constant = bool(metadata.get("constant", entry.get("constant", False)))
            selective = bool(metadata.get("selective", entry.get("selective", False)))
            activation = "常开" if constant else ("关键词" if keywords or selective else "手动")
            rows.append({
                "id": entry.get("id", ""),
                "title": entry.get("title") or entry.get("comment") or entry.get("name") or "(untitled)",
                "enabled": enabled,
                "activation": activation,
                "constant": constant,
                "selective": selective,
                "keywords": keywords,
                "priority": entry.get("priority", 0),
                "content_preview": str(entry.get("content", ""))[:160],
            })

        rows = rows[:limit]
        if rows:
            lines = []
            for row in rows:
                switch = "ON" if row["enabled"] else "OFF"
                keyword_text = ", ".join(map(str, row["keywords"])) if row["keywords"] else "-"
                lines.append(
                    f"[{switch}] {row['activation']} | p={row['priority']} | {row['title']} | keys: {keyword_text}"
                )
                if row["content_preview"]:
                    lines.append(f"  {row['content_preview']}")
        else:
            lines = ["(No worldbook entries)"]

        return (
            "\n".join(lines),
            json.dumps(rows, ensure_ascii=False, indent=2),
        )


def _parse_worldbook_entries(worldbook_json: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(worldbook_json) if worldbook_json.strip() else []
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        for key in ("entries", "worldbook", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        return []
    return [entry for entry in data if isinstance(entry, dict)]
