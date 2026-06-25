"""
Preset node for selecting RP presets.
"""

import json
from ..preset.preset import PresetManager


class AWPPreset:
    """选择 RP 预设用于生成。"""
    
    @classmethod
    def INPUT_TYPES(cls):
        manager = PresetManager()
        presets = manager.list_presets()
        preset_ids = [p["id"] for p in presets]
        
        return {
            "required": {
                "preset_id": (preset_ids if preset_ids else ["rp-default-v1"], {"default": "rp-default-v1"}),
            },
        }
    
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("预设ID", "提示词片段", "模型配置")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/配置"
    
    def execute(self, preset_id: str):
        """Select a preset."""
        manager = PresetManager()
        resolved = manager.resolve_preset(preset_id)
        
        if not resolved:
            return ("", "[]", "{}")
        
        prompt_sections = json.dumps(resolved.prompt_sections, ensure_ascii=False, indent=2)
        model_config = json.dumps(resolved.model_config, ensure_ascii=False, indent=2)
        
        return (preset_id, prompt_sections, model_config)
