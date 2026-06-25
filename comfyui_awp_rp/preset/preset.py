"""
Preset system for RP generation.

Presets configure model behavior, style rules, and output contracts.
They can be overridden by directives from worldbook or runtime.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from ..core.types import LocalizedText, OutputContract, PromptFragment, RpPreset
from ..core.config import get_config


# Default RP preset
DEFAULT_RP_PRESET = RpPreset(
    version="rp-preset-v1",
    id="rp-default-v1",
    name="Default RP Writer",
    model={
        "temperature": 0.8,
        "maxOutputTokens": 2048,
    },
    prompt={
        "coreRules": [
            PromptFragment(
                id="core-no-player-control",
                content="1. 不要替玩家做决定或控制玩家角色的行动和对话。只控制你自己的角色。",
                priority=100,
            ),
            PromptFragment(
                id="core-cognitive-boundary",
                content="2. 保持角色认知边界。角色不能知道没有被感知或被告知的信息。",
                priority=100,
            ),
            PromptFragment(
                id="core-no-leak-secrets",
                content="3. 不要用旁白或括号方式直接泄露设定或Runtime内部信息。",
                priority=100,
            ),
            PromptFragment(
                id="core-continuity",
                content="4. 保持地点、时间、人物和道具的连续性。不要突然推进角色状态或剧情逻辑。",
                priority=100,
            ),
            PromptFragment(
                id="core-rp-visible-only",
                content="5. 只输出玩家可见的角色表演内容。不要输出状态栏、JSON或其他元数据。",
                priority=100,
            ),
        ],
        "styleRules": [
            PromptFragment(
                id="style-show-dont-tell",
                content="通过动作、表情、对话和对话来展示角色，不要直接陈述情绪。",
                priority=80,
            ),
            PromptFragment(
                id="style-sensory-detail",
                content="包含感官细节（视觉、听觉、触觉、嗅觉）来增强沉浸感。",
                priority=70,
            ),
            PromptFragment(
                id="style-voice-consistency",
                content="保持角色的说话模式和语气的一致性。",
                priority=75,
            ),
        ],
        "additionalInstructions": [
            PromptFragment(
                id="inst-respond-to-actions",
                content="响应用户的动作和对话。确保你知道用户说了什么、做了什么、观察到了什么。",
                priority=90,
            ),
            PromptFragment(
                id="inst-npc-reactions",
                content="提供与NPC对当前情境和状态一致的反应。",
                priority=85,
            ),
            PromptFragment(
                id="inst-scene-ending",
                content="以自然的断点结束回复，留给玩家继续行动的空间。",
                priority=60,
            ),
        ],
    },
    output_contract=OutputContract(
        version="output-contract-v1",
        mode="narrative_only",
        slots=[{"id": "narrative", "required": True, "order": 10}],
        forbidden_patterns=["```json", "<analysis>", "思考过程：", "[Status:", "```yaml"],
        allow_extra_text=False,
    ),
    retry_policy={
        "maxWriterRetries": 2,
        "maxFormatRepairs": 1,
    },
)


# 长篇叙事预设 — 1200-1800字/回复，第三人称user视角
LONG_NARRATIVE_PRESET = RpPreset(
    version="rp-preset-v1",
    id="long-narrative-v1",
    name="长篇叙事预设",
    model={
        "temperature": 0.85,
        "maxOutputTokens": 4096,
    },
    prompt={
        "coreRules": [
            PromptFragment(
                id="core-no-player-control",
                content="1. 不要替玩家做决定、控制玩家角色的行动、台词或心理。你只负责NPC和环境。",
                priority=100,
            ),
            PromptFragment(
                id="core-cognitive-boundary",
                content="2. 保持角色认知边界。角色只能知道他们亲身经历、感知到或被告知的信息。",
                priority=100,
            ),
            PromptFragment(
                id="core-no-leak-secrets",
                content="3. 不要用旁白或括号泄露设定、世界书内部信息或Runtime元数据。",
                priority=100,
            ),
            PromptFragment(
                id="core-continuity",
                content="4. 保持地点、时间、人物、道具的连续性。不要突然推进角色状态或跳过合理过程。",
                priority=100,
            ),
            PromptFragment(
                id="core-rp-visible-only",
                content="5. 只输出玩家可见的叙事正文。不输出状态栏、JSON、分析或调试信息。",
                priority=100,
            ),
            PromptFragment(
                id="core-third-person-user-pov",
                content="6. 用第三人称叙述，以「你」指代玩家角色。例如：你推开了祠堂的大门，阳光刺得你眯起了眼。",
                priority=99,
            ),
            PromptFragment(
                id="core-length-1200-1800",
                content="7. 每次回复必须写到1200-1800字（中文字符）。这是硬性要求，不是建议。如果内容不够1200字，展开环境描写、NPC的微表情和小动作、对话的来回交锋来充实。如果超过1800字，在最近的自然断点收束。不要为了凑字数重复信息，也不要在字数达标前草率收尾。",
                priority=98,
            ),
        ],
        "styleRules": [
            PromptFragment(
                id="style-show-dont-tell",
                content="通过动作、表情、对话和环境细节展示角色状态，不要直接陈述情绪。",
                priority=80,
            ),
            PromptFragment(
                id="style-sensory-detail",
                content="包含视觉、听觉、触觉、嗅觉等感官细节来增强沉浸感。每个场景至少调动两种以上感官。",
                priority=75,
            ),
            PromptFragment(
                id="style-voice-consistency",
                content="保持每个角色的说话方式和语气一致。不同角色的用词、句式、语气应有明显区分。",
                priority=78,
            ),
            PromptFragment(
                id="style-environment-as-character",
                content="把环境当作角色来写。天气、光线、气味、声音都应服务于氛围和情绪。",
                priority=70,
            ),
            PromptFragment(
                id="style-natural-dialogue",
                content="对话要像真人说话，有口语感、停顿、犹豫、打断。避免书面化长句。",
                priority=72,
            ),
        ],
        "additionalInstructions": [
            PromptFragment(
                id="inst-respond-to-actions",
                content="认真回应玩家的具体动作和台词。玩家做了什么、说了什么，NPC和环境必须给出对应的反馈。",
                priority=90,
            ),
            PromptFragment(
                id="inst-npc-reactions",
                content="NPC的反应必须基于其人设、当前情绪、与玩家的关系和所处情境。不要让所有NPC反应千篇一律。",
                priority=88,
            ),
            PromptFragment(
                id="inst-scene-progression",
                content="每次回复要让场景有实质推进：要么揭示新信息，要么改变关系状态，要么制造新冲突。不要原地踏步。",
                priority=85,
            ),
            PromptFragment(
                id="inst-natural-ending",
                content="在1200-1800字内自然收束，停在玩家可以做出有意义选择的节点。不要用省略号制造虚假悬念。",
                priority=82,
            ),
            PromptFragment(
                id="inst-anti-ai",
                content="避免AI写作痕迹：不堆砌排比句，不滥用「仿佛」「宛如」等比喻词，不用「然而」「不过」公式化转折，不写「深吸一口气」表现情绪，不用「感受到了」「意识到」直接陈述心理。",
                priority=86,
            ),
            PromptFragment(
                id="inst-pacing",
                content="节奏要有快有慢。对话密集时用短句快速推进，环境描写和内心戏用长句放慢。不要全篇一个节奏。",
                priority=65,
            ),
        ],
    },
    output_contract=OutputContract(
        version="output-contract-v1",
        mode="narrative_only",
        slots=[{"id": "narrative", "required": True, "order": 10}],
        forbidden_patterns=["```json", "<analysis>", "思考过程：", "[Status:", "```yaml", "debugLog"],
        allow_extra_text=False,
    ),
    retry_policy={
        "maxWriterRetries": 2,
        "maxFormatRepairs": 1,
    },
)


@dataclass
class ResolvedPreset:
    """A resolved preset with merged prompt sections."""
    preset_id: str
    model_config: dict[str, Any]
    prompt_sections: list[dict[str, Any]]
    output_contract: Optional[OutputContract]
    diagnostics: dict[str, Any] = field(default_factory=dict)


class PresetManager:
    """Manages RP presets."""
    
    def __init__(self):
        self._presets: dict[str, RpPreset] = {
            DEFAULT_RP_PRESET.id: DEFAULT_RP_PRESET,
            LONG_NARRATIVE_PRESET.id: LONG_NARRATIVE_PRESET,
        }
        self._load_custom_presets()
    
    def _load_custom_presets(self) -> None:
        """Load custom presets from data directory."""
        config = get_config()
        presets_dir = os.path.join(config.data_dir, "presets")
        
        if not os.path.exists(presets_dir):
            return
        
        for filename in os.listdir(presets_dir):
            if filename.endswith(".json"):
                filepath = os.path.join(presets_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    preset = self._dict_to_preset(data)
                    self._presets[preset.id] = preset
                except Exception:
                    pass
    
    def _dict_to_preset(self, data: dict[str, Any]) -> RpPreset:
        """Convert a dict to an RpPreset."""
        prompt_data = data.get("prompt", {})
        
        core_rules = [
            PromptFragment(id=f["id"], content=f["content"], priority=f.get("priority", 50))
            for f in prompt_data.get("coreRules", [])
        ]
        style_rules = [
            PromptFragment(id=f["id"], content=f["content"], priority=f.get("priority", 50))
            for f in prompt_data.get("styleRules", [])
        ]
        additional = [
            PromptFragment(id=f["id"], content=f["content"], priority=f.get("priority", 50))
            for f in prompt_data.get("additionalInstructions", [])
        ]
        
        output_data = data.get("output_contract", {})
        output_contract = OutputContract(
            version=output_data.get("version", "output-contract-v1"),
            mode=output_data.get("mode", "narrative_only"),
            slots=output_data.get("slots", []),
            forbidden_patterns=output_data.get("forbidden_patterns", []),
            allow_extra_text=output_data.get("allow_extra_text", False),
        ) if output_data else None
        
        return RpPreset(
            version=data.get("version", "rp-preset-v1"),
            id=data["id"],
            name=data["name"],
            model=data.get("model"),
            prompt={
                "coreRules": core_rules,
                "styleRules": style_rules,
                "additionalInstructions": additional,
            },
            output_contract=output_contract,
            retry_policy=data.get("retry_policy"),
        )
    
    def get_preset(self, preset_id: str) -> Optional[RpPreset]:
        """Get a preset by ID."""
        return self._presets.get(preset_id)
    
    def list_presets(self) -> list[dict[str, str]]:
        """List all available presets."""
        return [
            {"id": p.id, "name": p.name}
            for p in self._presets.values()
        ]
    
    def resolve_preset(
        self,
        preset_id: str,
        directives: Optional[list[dict[str, Any]]] = None,
    ) -> Optional[ResolvedPreset]:
        """Resolve a preset with optional directives.
        
        Directives can append or override prompt fragments.
        """
        preset = self.get_preset(preset_id)
        if not preset:
            return None
        
        sections: list[dict[str, Any]] = []
        conflicts: list[dict[str, str]] = []
        applied_directive_ids: list[str] = []
        
        # Convert core rules to sections
        if preset.prompt:
            for fragment in preset.prompt.get("coreRules", []):
                sections.append({
                    "id": fragment.id,
                    "title": fragment.content[:60],
                    "source": "core_rules",
                    "content": fragment.content,
                    "priority": fragment.priority,
                    "visibility": "model_visible",
                    "trust": "system",
                    "provenance": {"presetId": preset.id},
                })
            
            # Convert style rules
            for fragment in preset.prompt.get("styleRules", []):
                sections.append({
                    "id": fragment.id,
                    "title": fragment.content[:60],
                    "source": "node_instruction",
                    "content": fragment.content,
                    "priority": fragment.priority,
                    "visibility": "model_visible",
                    "trust": "system",
                    "provenance": {"presetId": preset.id},
                })
            
            # Convert additional instructions
            for fragment in preset.prompt.get("additionalInstructions", []):
                sections.append({
                    "id": fragment.id,
                    "title": fragment.content[:60],
                    "source": "node_instruction",
                    "content": fragment.content,
                    "priority": fragment.priority,
                    "visibility": "model_visible",
                    "trust": "system",
                    "provenance": {"presetId": preset.id},
                })
        
        # Apply directives
        if directives:
            for directive in directives:
                merge = directive.get("merge", "append")
                
                if merge == "append":
                    sections.append({
                        "id": directive.get("id", "directive"),
                        "title": directive.get("content", "")[:60],
                        "source": "preset",
                        "content": directive.get("content", ""),
                        "priority": directive.get("priority", 50),
                        "visibility": "model_visible",
                        "trust": "world_data",
                        "provenance": {"presetId": directive.get("id")},
                    })
                    applied_directive_ids.append(directive.get("id", ""))
                
                elif merge == "override":
                    # Find and override if priority is higher
                    target_id = directive.get("target_id")
                    override_priority = directive.get("priority", 0)
                    
                    for i, section in enumerate(sections):
                        if section["id"] == target_id:
                            if override_priority > section.get("priority", 0):
                                sections[i] = {
                                    **section,
                                    "content": directive.get("content", ""),
                                    "priority": override_priority,
                                }
                                applied_directive_ids.append(directive.get("id", ""))
                            else:
                                conflicts.append({
                                    "targetId": target_id,
                                    "reason": f"Priority {override_priority} <= existing",
                                })
                            break
        
        # Build model config
        model_config = {}
        if preset.model:
            if "model" in preset.model:
                model_config["model"] = preset.model["model"]
            if "temperature" in preset.model:
                model_config["temperature"] = preset.model["temperature"]
            if "maxOutputTokens" in preset.model:
                model_config["max_tokens"] = preset.model["maxOutputTokens"]
        
        return ResolvedPreset(
            preset_id=preset.id,
            model_config=model_config,
            prompt_sections=sections,
            output_contract=preset.output_contract,
            diagnostics={
                "appliedDirectiveIds": applied_directive_ids,
                "conflicts": conflicts,
            },
        )
    
    def save_preset(self, preset: RpPreset) -> None:
        """Save a preset to disk."""
        config = get_config()
        presets_dir = os.path.join(config.data_dir, "presets")
        os.makedirs(presets_dir, exist_ok=True)
        
        filepath = os.path.join(presets_dir, f"{preset.id}.json")
        
        data = {
            "version": preset.version,
            "id": preset.id,
            "name": preset.name,
            "model": preset.model,
            "prompt": {
                "coreRules": [
                    {"id": f.id, "content": f.content, "priority": f.priority}
                    for f in (preset.prompt or {}).get("coreRules", [])
                ],
                "styleRules": [
                    {"id": f.id, "content": f.content, "priority": f.priority}
                    for f in (preset.prompt or {}).get("styleRules", [])
                ],
                "additionalInstructions": [
                    {"id": f.id, "content": f.content, "priority": f.priority}
                    for f in (preset.prompt or {}).get("additionalInstructions", [])
                ],
            },
            "output_contract": {
                "version": preset.output_contract.version,
                "mode": preset.output_contract.mode,
                "slots": preset.output_contract.slots,
                "forbidden_patterns": preset.output_contract.forbidden_patterns,
                "allow_extra_text": preset.output_contract.allow_extra_text,
            } if preset.output_contract else None,
            "retry_policy": preset.retry_policy,
        }
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        self._presets[preset.id] = preset
