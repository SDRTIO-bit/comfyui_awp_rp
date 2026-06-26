"""
Memory nodes for reading and writing long-term memories.
"""

import json
from typing import Any

from ..memory.long_term import LongTermMemory


class AWPMemoryRead:
    """从长期存储中读取记忆。

    V1: 受 routing decision 控制。当 ``routing_decision_json`` 提供且其
    ``should_read_memory`` 为 False 时，本节点不做真实读取，返回空（不报错）。
    这消除了"工作流预读 + agent loop 强制工具读取"的双重读取问题：是否读
    由路由器统一决定。旧工作流不传 routing_decision 时保持原行为。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "namespace": ("STRING", {
                    "default": "default",
                    "placeholder": "记忆命名空间（通常是session_id）",
                    "forceInput": True,
                }),
            },
            "optional": {
                "tags_any": ("STRING", {
                    "default": "",
                    "placeholder": "标签（逗号分隔，匹配任一）",
                }),
                "type_filter": ("STRING", {
                    "default": "",
                    "placeholder": "类型过滤（如 event, relationship-change）",
                }),
                "limit": ("INT", {"default": 10, "min": 1, "max": 100}),
                "run_id": ("INT", {"default": 0, "min": 0, "max": 999999999, "label": "运行ID（变化可刷新缓存）"}),
                "routing_decision_json": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "forceInput": True,
                    "label": "路由决策JSON（routed v1，留空=legacy）",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("记忆文本", "记忆JSON")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/记忆"

    def execute(
        self,
        namespace: str,
        tags_any: str = "",
        type_filter: str = "",
        limit: int = 10,
        run_id: int = 0,
        routing_decision_json: str = "",
    ):
        """Read memories from storage, gated by routing decision when provided."""
        # V1: honor routing decision. should_read_memory=False → no real read.
        if routing_decision_json and routing_decision_json.strip():
            try:
                decision = json.loads(routing_decision_json)
            except json.JSONDecodeError:
                decision = {}
            if isinstance(decision, dict) and decision.get("should_read_memory") is False:
                # Routing said skip — return empty, no error.
                return ("(memory read skipped by router)", "[]")

        memory = LongTermMemory()

        tags = [t.strip() for t in tags_any.split(",") if t.strip()] if tags_any else None
        type_f = type_filter if type_filter else None

        try:
            records = memory.query(
                namespace=namespace,
                tags_any=tags,
                type_filter=type_f,
                limit=limit,
            )
        except Exception:
            # fail-open: never block the main reply on a memory read error
            records = []
        
        # Format as readable text
        if records:
            lines = []
            for r in records:
                title = r.title or "Untitled"
                content = r.content
                tags_str = ", ".join(r.tags) if r.tags else ""
                lines.append(f"[{title}]")
                lines.append(content)
                if tags_str:
                    lines.append(f"Tags: {tags_str}")
                lines.append("")
            memories_text = "\n".join(lines)
        else:
            memories_text = "(No memories found)"
        
        # JSON output
        memory_json = json.dumps([
            {
                "id": r.id,
                "title": r.title,
                "content": r.content,
                "type": r.type,
                "tags": r.tags,
                "importance": r.importance,
            }
            for r in records
        ], ensure_ascii=False, indent=2)
        
        return (memories_text, memory_json)


class AWPMemoryWrite:
    """写入记忆到长期存储。"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "namespace": ("STRING", {
                    "default": "default",
                    "placeholder": "记忆命名空间",
                }),
                "content": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "记忆内容...",
                }),
            },
            "optional": {
                "title": ("STRING", {
                    "default": "",
                    "placeholder": "标题（可选）",
                }),
                "memory_type": ("STRING", {
                    "default": "event",
                    "placeholder": "类型（event, relationship-change, state-change等）",
                }),
                "tags": ("STRING", {
                    "default": "",
                    "placeholder": "标签（逗号分隔）",
                }),
                "entity_ids": ("STRING", {
                    "default": "",
                    "placeholder": "实体ID（逗号分隔）",
                }),
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
        content: str,
        title: str = "",
        memory_type: str = "event",
        tags: str = "",
        entity_ids: str = "",
        importance: float = 0.5,
    ):
        """Write a memory to storage."""
        memory = LongTermMemory()
        
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
        entity_list = [e.strip() for e in entity_ids.split(",") if e.strip()] if entity_ids else None
        
        record = memory.write(
            namespace=namespace,
            content=content,
            title=title if title else None,
            type=memory_type if memory_type else None,
            tags=tag_list,
            entity_ids=entity_list,
            importance=importance,
        )
        
        return (f"Memory saved: {record.id}",)
