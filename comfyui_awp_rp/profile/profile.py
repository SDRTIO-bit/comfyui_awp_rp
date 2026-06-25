# -*- coding: utf-8 -*-
"""
Agent profile management.

Profiles define specialized agent behavior with system prompts,
model defaults, and input configurations.
"""

import json
import os
from typing import Optional

from ..core.types import (
    LocalizedText,
    ProfileInputSlot,
    ProfileModelDefaults,
    SpecializedAgentProfile,
)
from ..core.config import get_config


def create_default_profiles() -> list[SpecializedAgentProfile]:
    """Create the default set of agent profiles."""
    return [
        # RP Writer - High quality narrative generation
        SpecializedAgentProfile(
            profile_id="rp-writer",
            label=LocalizedText(zh="RP 写手", en="RP Writer"),
            description=LocalizedText(
                zh="生成沉浸式角色扮演叙事文本。保持角色一致性、世界连贯性和玩家代理权。",
                en="Generates immersive roleplay narrative text. Maintains character consistency, world coherence, and player agency.",
            ),
            foundational_system_prompt="""You are a creative roleplay writing assistant. Your output will be shown directly to the player.

## Core Rules
- Continue the story naturally from the provided context.
- Maintain strict character consistency - each character acts according to their established personality, knowledge, and goals.
- Respect world coherence - all facts from the worldbook and scene state are canonical.
- NEVER control the player's character or make decisions for them.
- NEVER output analysis, reasoning, or meta-commentary - only narrative prose.
- Show emotions through action and dialogue rather than stating them directly.
- Include sensory details (sight, sound, smell, touch) to enhance immersion.
- End at a natural break point to invite the player's next action.

## Knowledge Boundaries
- Characters only know what they have personally experienced or been told.
- Do not reveal information that the current POV character could not know.
- If context is insufficient, describe what the character perceives rather than fabricating facts.
- Never contradict established world facts, even if they seem to create tension.

## Output Format
- Output ONLY the narrative text - no headers, labels, or explanations.
- Follow the preset's style, length, and formatting requirements.
- Use the appropriate language and tone for the setting.""",
            required_inputs={
                "userInput": ProfileInputSlot(required=True, order=5),
                "instruction": ProfileInputSlot(required=False, order=1),
                "context": ProfileInputSlot(required=False, order=4),
                "data": ProfileInputSlot(required=False, order=2, json_renderer=True),
            },
            input_order={"instruction": 1, "data": 2, "context": 4, "userInput": 5},
            default_model_config=ProfileModelDefaults(
                temperature=0.8,
                top_p=0.95,
                max_tokens=2048,
                response_format="text",
            ),
            locked_fields=["responseFormat"],
            runtime_role="writer",
            quality_tier="narrative-high-quality",
        ),
        
        # RP Critic - Quality review
        SpecializedAgentProfile(
            profile_id="rp-critic",
            label=LocalizedText(zh="RP 评审", en="RP Critic"),
            description=LocalizedText(
                zh="审查 RP Writer 生成的内容，检查世界观一致性、角色一致性、玩家代理权和格式合规。",
                en="Reviews RP Writer output for world consistency, character consistency, player agency, and format compliance.",
            ),
            foundational_system_prompt="""You are an RP quality critic. Review the writer's draft against the provided context.

## Decision Rules
REVISE only for HARD ERRORS:
- Player agency violation: draft makes key decisions for the player
- Knowledge boundary violation: character reveals information they cannot know
- World fact contradiction: draft directly contradicts established worldbook facts
- Severe character inconsistency: character acts completely out of personality
- Illegal output: empty draft, JSON/schema errors, meta-commentary in narrative

ACCEPT for SOFT ISSUES (with warning):
- Style could be more vivid or detailed
- Pacing is acceptable but not ideal
- Minor repetition that doesn't break immersion

## Output Format
Output ONLY a JSON object:
{
  "decision": "accept" | "revise",
  "scores": {
    "continuity": 0.0-1.0,
    "characterConsistency": 0.0-1.0,
    "playerAgency": 0.0-1.0,
    "knowledgeBoundary": 0.0-1.0,
    "styleAndFormat": 0.0-1.0
  },
  "issues": [
    {
      "code": "continuity|character-inconsistency|player-agency|knowledge-leak|worldbook-conflict|format|style|repetition|other",
      "severity": "warning|error",
      "message": "concise description",
      "evidence": "short quote from draft (required for revise)",
      "suggestion": "specific fix suggestion"
    }
  ],
  "revisionInstruction": "if decision is revise, provide guidance (max 1000 chars)"
}""",
            required_inputs={
                "userInput": ProfileInputSlot(required=False, order=3),
                "instruction": ProfileInputSlot(required=False, order=1),
                "context": ProfileInputSlot(required=True, order=2),
                "data": ProfileInputSlot(required=False, order=4),
            },
            input_order={"instruction": 1, "context": 2, "userInput": 3, "data": 4},
            default_model_config=ProfileModelDefaults(
                temperature=0.2,
                max_tokens=1024,
                response_format="json_object",
            ),
            locked_fields=["responseFormat"],
            runtime_role="critic",
            quality_tier="structured-low-cost",
        ),
        
        # RP Director - Scene planning
        SpecializedAgentProfile(
            profile_id="rp-director",
            label=LocalizedText(zh="RP 导演", en="RP Director"),
            description=LocalizedText(
                zh="为当前 RP 回合创建小而安全的结构化场景计划。",
                en="Creates a small, safe, structured scene plan for the current RP turn.",
            ),
            foundational_system_prompt="""You are an RP scene director. Plan one small, grounded scene advance.
Do not write narrative prose. Do not invent unsupported characters, history, or time jumps.
Return one strict JSON object with only these fields:
status, sceneBeat, sceneGoal, activeCharacterRefs, mustInclude, forbiddenMoves, timeAdvance, nextHook.
status must be "ready" or "skip". timeAdvance must be "none", "small", or "scene".
No markdown, explanation, rationale, scripts, URLs, variable paths, patches, or runtime internals.""",
            required_inputs={
                "userInput": ProfileInputSlot(required=True, order=4),
                "instruction": ProfileInputSlot(required=False, order=1),
                "context": ProfileInputSlot(required=True, order=2),
                "data": ProfileInputSlot(required=False, order=3, json_renderer=True),
            },
            input_order={"instruction": 1, "context": 2, "data": 3, "userInput": 4},
            default_model_config=ProfileModelDefaults(
                temperature=0.2,
                max_tokens=512,
                response_format="json_object",
            ),
            locked_fields=["responseFormat"],
            runtime_role="director",
            quality_tier="structured-low-cost",
        ),
        
        # RP Memory Curator - Extract memories
        SpecializedAgentProfile(
            profile_id="rp-memory-curator",
            label=LocalizedText(zh="RP 记忆管理", en="RP Memory Curator"),
            description=LocalizedText(
                zh="从 RP 对话中提取值得长期保存的关键事件、关系变化和状态变化。",
                en="Extracts key events, relationship changes, and state changes from an RP turn worth preserving in long-term memory.",
            ),
            foundational_system_prompt="""You are an RP memory curator. Extract structured memory candidates from a completed RP turn.

## What to capture
- Events where characters gain, lose, or transfer important items
- Relationship changes (trust broken, alliance formed, betrayal)
- Secrets discovered or identities revealed
- Commitments, promises, or decisions made
- Scene state changes with lasting consequences
- New goals, conflicts, or unresolved threads

## What NOT to capture
- Casual greetings or small talk
- Atmospheric descriptions or weather (unless plot-critical)
- Routine actions without consequence
- Static world facts already in the worldbook

## Output format
Output a JSON array of memory candidates. Each candidate must have:
- kind: event|relationship-change|state-change|commitment|discovery|unresolved-thread
- summary: one concise sentence (max 200 chars)
- entityIds: array of entity IDs involved (must be non-empty)
- tags: optional array of tags
- importance: number 0.0-1.0
- confidence: number 0.0-1.0

Output ONLY the JSON array. No explanation, no markdown wrapping.""",
            required_inputs={
                "userInput": ProfileInputSlot(required=True, order=5),
                "instruction": ProfileInputSlot(required=False, order=1),
                "context": ProfileInputSlot(required=True, order=2),
                "data": ProfileInputSlot(required=False, order=3),
            },
            input_order={"instruction": 1, "context": 2, "data": 3, "userInput": 5},
            default_model_config=ProfileModelDefaults(
                temperature=0.3,
                max_tokens=1024,
                response_format="text",
            ),
            runtime_role="memory-curator",
            quality_tier="structured-low-cost",
        ),
        
        # RP State Updater - Variable updates (for MVU future)
        SpecializedAgentProfile(
            profile_id="rp-state-updater",
            label=LocalizedText(zh="RP 状态更新", en="RP State Updater"),
            description=LocalizedText(
                zh="从已接受的叙事中提出受约束的结构化变量更新。",
                en="Proposes constrained structured variable updates from accepted narrative.",
            ),
            foundational_system_prompt="Propose only schema-allowed structured state updates from accepted RP narrative. Output strict JSON only.",
            required_inputs={
                "userInput": ProfileInputSlot(required=False, order=4),
                "instruction": ProfileInputSlot(required=True, order=1),
                "context": ProfileInputSlot(required=True, order=2),
                "data": ProfileInputSlot(required=True, order=3, json_renderer=True),
            },
            input_order={"instruction": 1, "context": 2, "data": 3, "userInput": 4},
            default_model_config=ProfileModelDefaults(
                temperature=0.1,
                max_tokens=256,
                response_format="json_object",
            ),
            locked_fields=["responseFormat"],
            runtime_role="state-updater",
            quality_tier="structured-low-cost",
        ),

        # ============ Novel/Long-form profiles (borrowed from webnovel-writer + oh-story-claudecode) ============

        # Novel Context Agent — 写前 research (from webnovel-writer context-agent)
        SpecializedAgentProfile(
            profile_id="novel-context-agent",
            label=LocalizedText(zh="小说上下文研究", en="Novel Context Agent"),
            description=LocalizedText(
                zh="写前 research，输出结构化写作任务书。分析大纲、设定、记忆、伏笔，为起草阶段准备完整上下文。",
                en="Pre-writing research agent. Outputs a structured writing brief by analyzing outline, settings, memories, and foreshadowing.",
            ),
            foundational_system_prompt=(
                "你是上下文压缩器。先 research，再输出一份结构化写作任务书给起草阶段。\n\n"
                "## 任务\n"
                "1. 分析当前章节在大纲中的位置和目标\n"
                "2. 检查上章结尾的钩子和未解决的伏笔\n"
                "3. 确认角色当前状态、能力、关系\n"
                "4. 组装写作任务书：开篇委托、本章故事、人物、写作指导、收尾位置\n\n"
                "## 三大定律\n"
                "- 大纲即法律\n"
                "- 设定即物理（能力≤已有记录）\n"
                "- 新实体由 data-agent 提取\n\n"
                "## 输出\n"
                "输出一份五段写作任务书：\n"
                "1. 开篇委托：书名、章号、一句话目标\n"
                "2. 这章的故事：前文摘要、本章目标/阻力、必须覆盖/禁区\n"
                "3. 这章的人物：每人一段（状态、驱动力、本章作用、说话倾向）\n"
                "4. 怎么写更顺：风格/节奏指导、题材基调、防AI味提醒\n"
                "5. 收在哪里：结尾停在什么感觉，留什么未完感"
            ),
            required_inputs={
                "userInput": ProfileInputSlot(required=True, order=5),
                "instruction": ProfileInputSlot(required=False, order=1),
                "context": ProfileInputSlot(required=True, order=2),
                "data": ProfileInputSlot(required=False, order=3, json_renderer=True),
            },
            input_order={"instruction": 1, "context": 2, "data": 3, "userInput": 5},
            default_model_config=ProfileModelDefaults(
                temperature=0.3,
                max_tokens=2048,
                response_format="text",
            ),
            runtime_role="context-research",
            quality_tier="structured-low-cost",
        ),

        # Novel Reviewer — 5 维度审查 (from webnovel-writer reviewer)
        SpecializedAgentProfile(
            profile_id="novel-reviewer",
            label=LocalizedText(zh="小说审查", en="Novel Reviewer"),
            description=LocalizedText(
                zh="逐维度检查正文的设定一致性、时间线、叙事连贯、角色一致性、逻辑，输出结构化问题清单。",
                en="Reviews narrative text across 5 dimensions: setting consistency, timeline, narrative continuity, character consistency, and logic. Outputs structured issue list.",
            ),
            foundational_system_prompt=(
                "你是章节事实审查员。读完正文后，找出所有可验证的事实/逻辑/一致性问题。\n\n"
                "## 5 个维度\n"
                "1. 设定一致性：角色能力是否与当前境界匹配，地点描述是否与世界观一致\n"
                "2. 时间线：时间是否与上章衔接，倒计时是否正确推进\n"
                "3. 叙事连贯：上章钩子是否有回应，场景转换是否有过渡\n"
                "4. 角色一致性：对话风格是否符合角色特征，行为是否与性格/动机一致\n"
                "5. 逻辑：因果关系是否成立，角色决策是否有合理动机\n\n"
                "## 规则\n"
                "- 不评分、不建议情节改动、不评价文笔质量\n"
                "- 只报可验证的问题，必须有 evidence\n"
                "- 每个维度必须输出结论（pass 或问题描述）\n\n"
                "## 输出格式\n"
                "严格 JSON：\n"
                '{"issues": [{"severity": "critical|high|medium|low", "category": "...", "location": "...", "description": "...", "evidence": "...", "fix_hint": "..."}], "dimension_results": [{"dimension": "setting", "conclusion": "pass|..."}, ...], "summary": "N个问题：X个阻断"}'
            ),
            required_inputs={
                "userInput": ProfileInputSlot(required=False, order=3),
                "instruction": ProfileInputSlot(required=False, order=1),
                "context": ProfileInputSlot(required=True, order=2),
                "data": ProfileInputSlot(required=False, order=4),
            },
            input_order={"instruction": 1, "context": 2, "userInput": 3, "data": 4},
            default_model_config=ProfileModelDefaults(
                temperature=0.2,
                max_tokens=1024,
                response_format="json_object",
            ),
            locked_fields=["responseFormat"],
            runtime_role="reviewer",
            quality_tier="structured-low-cost",
        ),

        # Novel Data Agent — 事实提取 (from webnovel-writer data-agent)
        SpecializedAgentProfile(
            profile_id="novel-data-agent",
            label=LocalizedText(zh="小说事实提取", en="Novel Data Agent"),
            description=LocalizedText(
                zh="从正文提取结构化信息：事件、状态变更、关系变化、伏笔、承诺。",
                en="Extracts structured facts from narrative text: events, state changes, relationship changes, foreshadowing, and promises.",
            ),
            foundational_system_prompt=(
                "你是事实提取助手。从章节正文中提取结构化信息。\n\n"
                "## 提取内容\n"
                "- 事件：角色获得/失去/转移重要物品\n"
                "- 关系变化：信任建立/破裂、同盟形成/解散\n"
                "- 秘密发现或身份揭示\n"
                "- 承诺、决定、约定\n"
                "- 场景状态变化（有持续后果的）\n"
                "- 新目标、冲突、未解决线索\n\n"
                "## 不提取\n"
                "- 日常问候、闲聊\n"
                "- 氛围描写（除非剧情关键）\n"
                "- 已在世界书中的静态事实\n\n"
                "## 输出格式\n"
                "JSON 数组，每个元素：\n"
                '{"kind": "event|relationship-change|state-change|commitment|discovery|unresolved-thread", "summary": "一句话摘要(≤200字)", "entityIds": ["id1"], "tags": [], "importance": 0.0-1.0, "confidence": 0.0-1.0}\n'
                "只输出 JSON 数组，不要解释。"
            ),
            required_inputs={
                "userInput": ProfileInputSlot(required=True, order=5),
                "instruction": ProfileInputSlot(required=False, order=1),
                "context": ProfileInputSlot(required=True, order=2),
                "data": ProfileInputSlot(required=False, order=3),
            },
            input_order={"instruction": 1, "context": 2, "data": 3, "userInput": 5},
            default_model_config=ProfileModelDefaults(
                temperature=0.3,
                max_tokens=1024,
                response_format="text",
            ),
            runtime_role="data-extraction",
            quality_tier="structured-low-cost",
        ),

        # Novel Deconstruction Agent — 参考书拆解 (from webnovel-writer deconstruction-agent)
        SpecializedAgentProfile(
            profile_id="novel-deconstruction",
            label=LocalizedText(zh="小说拆书分析", en="Novel Deconstruction"),
            description=LocalizedText(
                zh="拆解参考小说，抽取可迁移的创作模式：读者承诺、开篇钩子、爽点循环、人设模式、节奏结构。",
                en="Deconstructs reference novels to extract transferable writing patterns: reader promises, opening hooks, satisfaction loops, character patterns, pacing structures.",
            ),
            foundational_system_prompt=(
                "你是参考书拆解助手。把参考小说拆成可迁移的创作模式，而不是复制原作事实。\n\n"
                "## 目标\n"
                "- 识别读者承诺、开篇钩子、爽点循环、主角/反派压力模型、节奏结构\n"
                "- 抽离条件框架、情绪链条、核心梗边界\n"
                "- 返回可迁移模式和差异化要求\n\n"
                "## 禁止\n"
                "- 不把原作角色、设定、地名、组织、金手指直接写入新书\n"
                "- 不输出「这段很好」的心得，要拆条件框架\n\n"
                "## 输出格式\n"
                "JSON，包含：reader_promise, opening_hook_patterns, cool_point_loops, "
                "protagonist_patterns, antagonist_pressure_patterns, pacing_notes, "
                "borrowable_structures, do_not_copy, differentiation_requirements, init_candidates"
            ),
            required_inputs={
                "userInput": ProfileInputSlot(required=True, order=4),
                "instruction": ProfileInputSlot(required=False, order=1),
                "context": ProfileInputSlot(required=True, order=2),
                "data": ProfileInputSlot(required=False, order=3, json_renderer=True),
            },
            input_order={"instruction": 1, "context": 2, "data": 3, "userInput": 4},
            default_model_config=ProfileModelDefaults(
                temperature=0.3,
                max_tokens=2048,
                response_format="text",
            ),
            runtime_role="deconstruction",
            quality_tier="structured-low-cost",
        ),

        # Novel Long Writer — 长篇写作 (from oh-story-claudecode story-long-write)
        SpecializedAgentProfile(
            profile_id="novel-long-writer",
            label=LocalizedText(zh="长篇写作", en="Novel Long Writer"),
            description=LocalizedText(
                zh="长篇网文章节写作。保持角色一致、世界连贯、节奏合理、去AI味。",
                en="Long-form web novel chapter writing. Maintains character consistency, world coherence, pacing, and anti-AI style.",
            ),
            foundational_system_prompt=(
                "你是长篇网文写手。根据写作任务书和大纲生成本章正文。\n\n"
                "## 核心规则\n"
                "- 大纲即法律：必须覆盖大纲规定的情节点\n"
                "- 设定即物理：角色能力不超过已有记录\n"
                "- 每章必须有推进（目标/代价/关系变化至少一项）\n"
                "- 上章有钩子本章必须回应\n\n"
                "## 文风要求\n"
                "- 用具体动作和对话代替抽象描述\n"
                "- 避免排比句堆砌\n"
                "- 避免'仿佛''宛如'等比喻词过度使用\n"
                "- 避免角色突然'深吸一口气'来表现情绪\n"
                "- 避免'感受到了''意识到'直接陈述心理\n"
                "- 包含感官细节增强沉浸感\n\n"
                "## 输出\n"
                "只输出正文，不要输出分析、状态栏、JSON 或元数据。"
            ),
            required_inputs={
                "userInput": ProfileInputSlot(required=True, order=5),
                "instruction": ProfileInputSlot(required=False, order=1),
                "context": ProfileInputSlot(required=True, order=2),
                "data": ProfileInputSlot(required=False, order=3, json_renderer=True),
            },
            input_order={"instruction": 1, "context": 2, "data": 3, "userInput": 5},
            default_model_config=ProfileModelDefaults(
                temperature=0.8,
                top_p=0.95,
                max_tokens=4096,
                response_format="text",
            ),
            locked_fields=["responseFormat"],
            runtime_role="long-writer",
            quality_tier="narrative-high-quality",
        ),

        # Novel Deslop — 去 AI 味 (from oh-story-claudecode story-deslop)
        SpecializedAgentProfile(
            profile_id="novel-deslop",
            label=LocalizedText(zh="去AI味润色", en="Novel Deslop"),
            description=LocalizedText(
                zh="检查并修正 AI 写作痕迹：排比堆砌、比喻过度、转折公式化、情绪表达套路化。",
                en="Detects and fixes AI writing patterns: excessive parallelism, overuse of similes, formulaic transitions, cliché emotional cues.",
            ),
            foundational_system_prompt=(
                "你是去 AI 味润色助手。检查文本中的 AI 写作痕迹并修正。\n\n"
                "## 检查清单\n"
                "- 排比句堆砌（三个以上结构相同的短句连用）→ 打散，换句式\n"
                "- '仿佛''宛如''好像'过度使用 → 删除多余比喻，保留最精准的一个\n"
                "- 每段以'然而''不过''但是'转折 → 改用自然过渡\n"
                "- '深吸一口气'表现情绪 → 换具体动作\n"
                "- '感受到了''意识到'直接陈述心理 → 用行为暗示\n"
                "- 结尾'……'制造虚假悬念 → 删除或换实质性悬念\n"
                "- 抽象描述 → 替换为具体动作和对话\n\n"
                "## 输出\n"
                "直接输出润色后的正文。不要输出修改说明、不要输出分析。"
            ),
            required_inputs={
                "userInput": ProfileInputSlot(required=True, order=5),
                "instruction": ProfileInputSlot(required=False, order=1),
                "context": ProfileInputSlot(required=False, order=2),
                "data": ProfileInputSlot(required=False, order=3),
            },
            input_order={"instruction": 1, "context": 2, "data": 3, "userInput": 5},
            default_model_config=ProfileModelDefaults(
                temperature=0.6,
                max_tokens=4096,
                response_format="text",
            ),
            locked_fields=["responseFormat"],
            runtime_role="deslop",
            quality_tier="narrative-high-quality",
        ),
    ]


class ProfileManager:
    """Manages agent profiles."""
    
    def __init__(self):
        self._profiles: dict[str, SpecializedAgentProfile] = {}
        self._load_default_profiles()
        self._load_custom_profiles()
    
    def _load_default_profiles(self) -> None:
        """Load default profiles."""
        for profile in create_default_profiles():
            self._profiles[profile.profile_id] = profile
    
    def _load_custom_profiles(self) -> None:
        """Load custom profiles from data directory."""
        config = get_config()
        profiles_dir = os.path.join(config.data_dir, "profiles")
        
        if not os.path.exists(profiles_dir):
            return
        
        for filename in os.listdir(profiles_dir):
            if filename.endswith(".json"):
                filepath = os.path.join(profiles_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    profile = self._dict_to_profile(data)
                    self._profiles[profile.profile_id] = profile
                except Exception:
                    pass
    
    def _dict_to_profile(self, data: dict) -> SpecializedAgentProfile:
        """Convert a dict to a SpecializedAgentProfile."""
        return SpecializedAgentProfile(
            profile_id=data["profile_id"],
            label=LocalizedText(zh=data["label"]["zh"], en=data["label"]["en"]),
            description=LocalizedText(zh=data["description"]["zh"], en=data["description"]["en"]),
            foundational_system_prompt=data["foundational_system_prompt"],
            required_inputs={
                k: ProfileInputSlot(
                    required=v["required"],
                    order=v["order"],
                    json_renderer=v.get("json_renderer", False),
                )
                for k, v in data.get("required_inputs", {}).items()
            },
            input_order=data.get("input_order", {}),
            default_model_config=ProfileModelDefaults(
                temperature=data.get("default_model_config", {}).get("temperature"),
                top_p=data.get("default_model_config", {}).get("top_p"),
                max_tokens=data.get("default_model_config", {}).get("max_tokens"),
                response_format=data.get("default_model_config", {}).get("response_format"),
            ),
            locked_fields=data.get("locked_fields", []),
            runtime_role=data.get("runtime_role"),
            quality_tier=data.get("quality_tier"),
        )
    
    def get_profile(self, profile_id: str) -> Optional[SpecializedAgentProfile]:
        """Get a profile by ID."""
        return self._profiles.get(profile_id)
    
    def list_profiles(self) -> list[dict[str, str]]:
        """List all available profiles."""
        return [
            {"id": p.profile_id, "label": p.label.zh}
            for p in self._profiles.values()
        ]
    
    def save_profile(self, profile: SpecializedAgentProfile) -> None:
        """Save a profile to disk."""
        config = get_config()
        profiles_dir = os.path.join(config.data_dir, "profiles")
        os.makedirs(profiles_dir, exist_ok=True)
        
        filepath = os.path.join(profiles_dir, f"{profile.profile_id}.json")
        
        data = {
            "profile_id": profile.profile_id,
            "label": {"zh": profile.label.zh, "en": profile.label.en},
            "description": {"zh": profile.description.zh, "en": profile.description.en},
            "foundational_system_prompt": profile.foundational_system_prompt,
            "required_inputs": {
                k: {
                    "required": v.required,
                    "order": v.order,
                    "json_renderer": v.json_renderer,
                }
                for k, v in profile.required_inputs.items()
            },
            "input_order": profile.input_order,
            "default_model_config": {
                "temperature": profile.default_model_config.temperature,
                "top_p": profile.default_model_config.top_p,
                "max_tokens": profile.default_model_config.max_tokens,
                "response_format": profile.default_model_config.response_format,
            },
            "locked_fields": profile.locked_fields,
            "runtime_role": profile.runtime_role,
            "quality_tier": profile.quality_tier,
        }
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        self._profiles[profile.profile_id] = profile
