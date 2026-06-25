"""
Sub Agent Node - Specialized agent for specific tasks.

Sub-agents handle specific tasks like:
- Search/Retrieval
- Summarization
- Quality review
- Memory curation
"""

import json
from typing import Any

from ..core.llm_router import create_default_router
from ..core.config import get_config
from ..profile.profile import ProfileManager


class AWPSubAgent:
    """子 Agent 节点 —— 使用专用 Profile 处理特定任务。"""
    
    @classmethod
    def INPUT_TYPES(cls):
        config = get_config()
        providers = list(config.providers.keys()) if config.providers else ["deepseek"]
        
        profile_manager = ProfileManager()
        profiles = [p["id"] for p in profile_manager.list_profiles()]
        
        return {
            "required": {
                "task": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "任务描述或指令...",
                }),
                "profile": (profiles, {"default": "rp-critic"}),
            },
            "optional": {
                "provider": (providers, {"default": providers[0] if providers else "deepseek"}),
                "model": ("STRING", {"default": "deepseek-chat"}),
                "context": ("STRING", {"default": "", "forceInput": True}),
                "data": ("STRING", {"default": "", "forceInput": True}),
                "temperature": ("FLOAT", {"default": 0.3, "min": 0.0, "max": 2.0, "step": 0.1}),
                "max_tokens": ("INT", {"default": 1024, "min": 100, "max": 4096}),
            },
        }
    
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("结果", "元数据")
    FUNCTION = "execute"
    CATEGORY = "AWP RP"
    
    def execute(
        self,
        task: str,
        profile: str,
        provider: str = "deepseek",
        model: str = "deepseek-chat",
        context: str = "",
        data: str = "",
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ):
        """Execute the sub-agent task."""
        
        # Get profile
        profile_manager = ProfileManager()
        agent_profile = profile_manager.get_profile(profile)
        
        if not agent_profile:
            return (
                f"Error: Profile '{profile}' not found",
                json.dumps({"error": "profile_not_found"}),
            )
        
        # Build prompt
        prompt_parts = [agent_profile.foundational_system_prompt]
        
        if context:
            prompt_parts.append(f"## Context\n{context}")
        
        if data:
            prompt_parts.append(f"## Data\n{data}")
        
        prompt_parts.append(f"## Task\n{task}")
        
        full_prompt = "\n\n".join(prompt_parts)
        
        # Call LLM
        try:
            router = create_default_router()
            
            node_config = {
                "provider": provider,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            
            text, token_usage, resolved_provider, resolved_model = router.complete_with_config(
                node_config=node_config,
                workflow_defaults=None,
                prompt=full_prompt,
            )
            
            metadata = {
                "provider": resolved_provider,
                "model": resolved_model,
                "profile": profile,
                "token_usage": {
                    "input": token_usage.input,
                    "output": token_usage.output,
                },
            }
            
            return (text, json.dumps(metadata, ensure_ascii=False))
            
        except Exception as e:
            return (f"Error: {str(e)}", json.dumps({"error": str(e)}))
