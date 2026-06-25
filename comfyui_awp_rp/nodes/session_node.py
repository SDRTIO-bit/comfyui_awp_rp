"""
Session nodes for loading and saving conversation sessions.
"""

import json
from ..memory.short_term import AgentSessionManager
from ..core.types import AgentSessionKey


class AWPSessionLoad:
    """加载对话会话。"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "session_id": ("STRING", {
                    "default": "default",
                    "placeholder": "会话ID",
                    "forceInput": True,
                }),
            },
            "optional": {
                "include_history": ("BOOLEAN", {
                    "default": True,
                    "label": "包含对话历史",
                }),
            },
        }
    
    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("会话ID", "会话上下文", "轮次数")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/会话"
    
    def execute(self, session_id: str, include_history: bool = True):
        """Load a session.

        When include_history is True, returns the full conversation
        history so the user can see what happened in previous turns.
        """
        manager = AgentSessionManager()
        session_key = manager.create_key(
            tenant_id="default",
            workflow_instance_id="comfyui-rp",
            conversation_id=session_id,
            agent_node_id="main-agent",
        )

        context = manager._memory.load(session_key)

        if context:
            turn_count = len(context.turns)
            # Build history list for user visibility
            history_list = []
            if include_history:
                for t in context.turns:
                    history_list.append({
                        "turn": t.turn_index,
                        "input": str(t.input)[:200] if t.input else "",
                        "output": str(t.assistant_output)[:200] if t.assistant_output else "",
                        "created_at": t.created_at,
                    })

            session_context = json.dumps({
                "session_id": session_id,
                "turn_count": turn_count,
                "summary": context.summary,
                "estimated_tokens": context.estimated_tokens,
                "truncated": context.truncated,
                "history": history_list,
            }, ensure_ascii=False, indent=2)
        else:
            turn_count = 0
            session_context = json.dumps({
                "session_id": session_id,
                "turn_count": 0,
                "summary": None,
                "estimated_tokens": 0,
                "truncated": False,
                "history": [],
            }, ensure_ascii=False, indent=2)

        return (session_id, session_context, turn_count)


class AWPSessionSave:
    """保存/更新对话会话。"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "session_id": ("STRING", {
                    "default": "default",
                    "placeholder": "会话ID",
                    "forceInput": True,
                }),
            },
            "optional": {
                "summary": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "会话摘要（可选）",
                    "forceInput": True,
                }),
                "clear_session": ("BOOLEAN", {"default": False}),
            },
        }
    
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("状态",)
    FUNCTION = "execute"
    CATEGORY = "AWP RP/会话"
    OUTPUT_NODE = True
    
    def execute(
        self,
        session_id: str,
        summary: str = "",
        clear_session: bool = False,
    ):
        """Save/update a session."""
        manager = AgentSessionManager()
        session_key = manager.create_key(
            tenant_id="default",
            workflow_instance_id="comfyui-rp",
            conversation_id=session_id,
            agent_node_id="main-agent",
        )
        
        if clear_session:
            manager._memory.delete(session_key)
            return ("Session cleared",)
        
        if summary:
            manager._memory.summarize(session_key, summary)
            return ("Summary updated",)
        
        return ("Session unchanged",)


class AWPSessionReroll:
    """重roll最近一轮或从指定位置删除对话轮次。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "session_id": ("STRING", {
                    "default": "default",
                    "placeholder": "会话ID",
                    "forceInput": True,
                }),
                "operation": (["reroll_last", "delete_from"], {
                    "default": "reroll_last",
                    "label": "操作类型",
                }),
            },
            "optional": {
                "from_index": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 1000,
                    "label": "删除起始轮次（delete_from 时使用）",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("用户输入（供重生成）", "删除/影响轮次")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/会话"

    def execute(
        self,
        session_id: str,
        operation: str = "reroll_last",
        from_index: int = 0,
    ):
        manager = AgentSessionManager()
        session_key = manager.create_key(
            tenant_id="default",
            workflow_instance_id="comfyui-rp",
            conversation_id=session_id,
            agent_node_id="main-agent",
        )

        if operation == "reroll_last":
            user_input = manager.reroll_last(session_key)
            if user_input:
                return (user_input, 1)
            return ("[No turns to reroll — session empty or last turn is opening]", 0)

        elif operation == "delete_from":
            deleted = manager.delete_turns_from(session_key, from_index)
            return (f"Deleted {deleted} turns from index {from_index}", deleted)

        return ("Unknown operation", 0)
