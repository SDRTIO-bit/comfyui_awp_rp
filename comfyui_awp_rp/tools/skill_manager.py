"""Skill manager — loads skill content from storage and injects into agent prompts.

A skill is a prompt fragment (optionally with an associated tool list) that
can be granted to an agent.  Skills live in the ``skills`` SQLite table and
in the ``data/skills/`` directory as JSON files.

This module mirrors the pattern from oh-story-claudecode where the
``references/`` directory contains structured writing knowledge that is
injected into agent system prompts.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from ..core.config import get_config
from ..core.store import SQLiteStore, get_store


@dataclass
class Skill:
    """A skill definition."""

    skill_id: str
    label_zh: str
    label_en: str
    content_zh: str
    content_en: str
    category: str = "general"
    tags: list[str] = field(default_factory=list)


class SkillManager:
    """Manages skill definitions and resolves them for agent injection."""

    def __init__(self, store: Optional[SQLiteStore] = None) -> None:
        self._store = store or get_store()
        self._skills: dict[str, Skill] = {}
        self._load_builtin_skills()
        self._load_custom_skills()

    def _load_builtin_skills(self) -> None:
        """Load built-in RP skills (mirrors plugins/rp-skills/skill.plugin.json)."""
        builtin = [
            Skill(
                skill_id="rp_persona",
                label_zh="RP 角色扮演",
                label_en="RP Persona",
                content_zh="保持角色人设、语气、关系立场、秘密和边界。不打破第四面墙。",
                content_en="Stay in character. Preserve the character card's persona, voice, relationship stance, secrets, and boundaries.",
                category="roleplay",
                tags=["persona", "voice", "immersion"],
            ),
            Skill(
                skill_id="rp_player_agency",
                label_zh="玩家行动权保护",
                label_en="RP Player Agency",
                content_zh="绝不替玩家决定行动、情绪、发言或意图。只描述 NPC 和环境，然后留出清晰的行动入口。",
                content_en="Never decide the player's action, emotion, speech, or intention. Describe NPCs and environment, then leave a clear hook for the player.",
                category="safety",
                tags=["agency", "boundary", "player"],
            ),
            Skill(
                skill_id="rp_continuity",
                label_zh="RP 连续性",
                label_en="RP Continuity",
                content_zh="以世界书事实和长期记忆作为正史。避免矛盾、关系跳跃和未经铺垫的揭示。",
                content_en="Use worldbook facts and long-term memory as canon. Avoid contradictions, sudden relationship jumps, and unexplained reveals.",
                category="roleplay",
                tags=["continuity", "canon", "memory"],
            ),
            Skill(
                skill_id="rp_slow_burn",
                label_zh="RP 慢热叙事",
                label_en="RP Slow Burn",
                content_zh="悬疑类 RP 每轮只揭示一个有意义的细节。保持紧张感、氛围和未回答的问题。",
                content_en="For mystery roleplay, reveal one meaningful detail per turn. Keep tension, atmosphere, and unanswered questions alive.",
                category="roleplay",
                tags=["slow-burn", "mystery", "tension", "pacing"],
            ),
            Skill(
                skill_id="prose",
                label_zh="散文写作",
                label_en="Prose Writing",
                content_zh="写出生动、克制的中文叙述。避免过度修饰和陈词滥调。",
                content_en="Write vivid, restrained prose. Avoid overwrought descriptions and clichés.",
                category="writing",
                tags=["prose", "style", "narrative"],
            ),
            Skill(
                skill_id="world_context",
                label_zh="世界观上下文",
                label_en="World Context",
                content_zh="提取和使用稳定的世界观设定。保持与既有世界书事实一致。",
                content_en="Extract and use stable setting facts. Stay consistent with established worldbook canon.",
                category="knowledge",
                tags=["worldbuilding", "canon", "facts"],
            ),
            Skill(
                skill_id="consistency",
                label_zh="一致性检查",
                label_en="Consistency",
                content_zh="检查是否存在矛盾、遗漏事实或违反已确立的设定。",
                content_en="Check for contradictions, missing facts, or violations of established canon.",
                category="safety",
                tags=["consistency", "logic", "fact-checking"],
            ),
            Skill(
                skill_id="anti_ai_writing",
                label_zh="去 AI 味写作",
                label_en="Anti-AI Writing",
                content_zh=(
                    "避免 AI 写作的常见痕迹：\n"
                    "- 避免排比句堆砌（三个以上结构相同的短句连用）\n"
                    "- 避免'仿佛''宛如''好像'等比喻词过度使用\n"
                    "- 避免每段都以'然而''不过''但是'转折\n"
                    "- 避免角色突然'深吸一口气'来表现情绪\n"
                    "- 避免用'感受到了''意识到'直接陈述心理\n"
                    "- 避免结尾用'……'制造虚假悬念\n"
                    "- 用具体动作和对话代替抽象描述"
                ),
                content_en=(
                    "Avoid common AI writing patterns: excessive parallelism, "
                    "overuse of similes, formulaic transitions, cliché emotional "
                    "cues like 'took a deep breath', stating emotions directly, "
                    "and trailing dots for false suspense."
                ),
                category="writing",
                tags=["anti-ai", "deslop", "style"],
            ),
            Skill(
                skill_id="rp_thinking_flow",
                label_zh="RP 生成前思考流程",
                label_en="RP Pre-Generation Thinking Flow",
                content_zh=(
                    "每轮回复生成前，在内部走完以下五步（不输出到回复中）：\n\n"
                    "**Step 1 翻记忆**：上轮发生了什么？有什么未落地的伏笔、未回复的问题？"
                    "每个 NPC 上轮在做什么、心里惦记什么？\n\n"
                    "**Step 2 看盘面**：当前 Day/时间/地点。用户这轮说了什么做了什么"
                    "——只取字面意思，不替用户脑补隐藏动机。谁在场、谁离场但需要追踪？\n\n"
                    "**Step 3 判场景**：当前什么调性（日常/紧张/温情/冲突/亲密）？"
                    "节奏有没有停滞——有没有到了时间该发生的日历事件、该行动的 NPC、"
                    "该浮现的伏笔？\n\n"
                    "**Step 4 人事物怎么动**：每个在场 NPC 对这轮有什么反应"
                    "（从角色卡性格和前文经历出发，不套模板）？谁该入场/退场？"
                    "背景 NPC 有什么进展需要交代？本轮场景是否触及世界书索引中的话题？\n\n"
                    "**Step 5 输出前检查**：对照硬性门禁（禁用全知修饰词、禁用八股微表情、"
                    "禁用临床/学术语言、禁用极端标签化情感词），这轮最容易踩哪几个雷？"
                    "有没有不自觉套标签或 OOC 的风险？"
                ),
                content_en=(
                    "Before generating each turn's reply, walk through these five steps internally:\n\n"
                    "Step 1 Review Memory: What happened last turn? Unresolved hooks? Unanswered questions?\n"
                    "Step 2 Assess Board: Current time/location. Who's present? Who's off-screen?\n"
                    "Step 3 Judge Scene: Current tone. Is pacing stagnating?\n"
                    "Step 4 Character Reactions: How does each NPC react? Who enters/exits?\n"
                    "Step 5 Pre-Output Check: Run against hard gates."
                ),
                category="roleplay",
                tags=["thinking", "preparation", "quality"],
            ),
            Skill(
                skill_id="narrative_theory",
                label_zh="叙事理论框架",
                label_en="Narrative Theory Framework",
                content_zh=(
                    "基于叙事学六大理论体系指导创作：\n\n"
                    "## 价值转换（麦基·每个场景的铁律）\n"
                    "每个场景结束时必须有某种价值发生逆转——希望→绝望、信任→背叛、亲近→疏离。"
                    "如果场景结束时情感状态与开始时相同，这个场景就是多余的。在角色扮演中，每轮回复至少推动一个微小的价值变化。\n\n"
                    "## 信息不对称（保持悬念的核心引擎）\n"
                    "三种配置灵活切换：观众知道>角色知道（戏剧性反讽）、角色知道>观众知道（神秘叙事）、"
                    "所有人都不完全知道（悬疑叙事）。信息逐层释放，每一层既回答旧问题又引出新问题。\n\n"
                    "## 打破预期（熟悉+新颖=最佳体验）\n"
                    "用熟悉的原型给读者安全感，再用意外转折打破惯性。"
                    "陌生化：经典模式放入意想不到的背景。类型混合：两种以上类型元素碰撞出新化学反应。\n\n"
                    "## 情感波浪线\n"
                    "情感在场景之间持续波动——推高、拉低、再推高。波动幅度渐进增大，"
                    "在高潮处达到最大振幅。先跌后升的形状在叙事中收益最高。\n\n"
                    "## 伏笔与呼应\n"
                    "在早期自然植入线索，后期以意想不到方式呼应。"
                    "第一次出现时不引起注意，回顾时重要性清晰可见。\n\n"
                    "## 潜文本\n"
                    "场景中真正发生的事与表面上看起来发生的事之间的差异。"
                    "对话说表面，潜文本讲真相。"
                ),
                content_en=(
                    "Narrative theory framework based on McKee, Booker, Campbell, Snyder, Pearson, ATU.\n\n"
                    "Value Change: Every scene must have a value reversal.\n"
                    "Information Asymmetry: Three configurations for suspense.\n"
                    "Expectation Breaking: Familiar + Novel = Best Experience.\n"
                    "Emotional Wave: Continuous fluctuation between scenes.\n"
                    "Foreshadowing: Plant clues early, pay off unexpectedly.\n"
                    "Subtext: What happens vs what appears to happen."
                ),
                category="writing",
                tags=["narrative", "theory", "story-structure", "quality"],
            ),
            Skill(
                skill_id="hard_gates_full",
                label_zh="硬性门禁（完整版）",
                label_en="Hard Gates (Full)",
                content_zh=(
                    "以下规则适用于所有 RP 输出。踩中一条即视为不合格：\n\n"
                    "## 禁用全知修饰词\n"
                    "禁止在动作描写前加全知视角副词：不自觉地、下意识地、不由自主地、"
                    "情不自禁、鬼使神差、微不可察、极力掩饰、不易察觉。裸写动作本身，让读者自己判断。\n\n"
                    "## 禁用八股微表情\n"
                    "禁止：瞳孔微缩、喉结滚动、睫毛颤动、呼吸一滞、身体一僵、指节泛白。"
                    "换成角色自己的习惯小动作，或者直接不写。\n\n"
                    "## 禁用临床/学术语言\n"
                    "情感表达场景严禁：博弈、操控、主导、试探、攻防、拿捏、接管、打压、争夺。"
                    "换成具体行为词：讨价还价、套话、斗嘴、哄、使绊子。\n\n"
                    "## 禁用极端标签化情感词\n"
                    "禁止：崩溃、绝望、沦陷、虔诚、崇拜、臣服、支配、征服、占有、驯化、"
                    "猎物、玩物、祭品、共犯。换成朴素情绪词：撑不住、陷进去、很在意、"
                    "佩服、听他的、想要、习惯了、盯上了。\n\n"
                    "## 句式禁止\n"
                    "禁止「不容XX」「最后一根稻草」等网文套话。"
                    "禁止在普通名词上加暗示性引号（如：「营养」的）。\n\n"
                    "## 台词检查\n"
                    "这句话从角色嘴里说出来违和吗（年龄/身份/性格对得上吗）？"
                    "所有角色都在说同一种调调吗（每个人声口应当不同）？"
                    "像中国人自然会说的话吗（不是翻译腔）？\n\n"
                    "## 动作描写检查\n"
                    "动作干净吗（不堆形容词）？人是主语吗（不是「嘴角勾起弧度」，是「勾了下嘴角」）？"
                    "写的是角色自己能感觉到的东西吗（不是后背的曲线、自己眼睛的颜色）？"
                ),
                content_en=(
                    "Hard gates for all RP output:\n"
                    "No omniscient adverbs (unconsciously, subconsciously, involuntarily).\n"
                    "No cliché micro-expressions (pupils contracting, throat bobbing, lashes trembling).\n"
                    "No clinical/academic language in emotional scenes.\n"
                    "No extreme label emotions (collapse, despair, devotion, worship).\n"
                    "Sentence bans on web-novel clichés.\n"
                    "Dialogue check: voice matches character age/identity/personality.\n"
                    "Action check: clean, character as subject, only what they can perceive."
                ),
                category="safety",
                tags=["quality", "gates", "anti-cliché"],
            ),
            Skill(
                skill_id="rp_npc_activity",
                label_zh="后台NPC活性管理",
                label_en="Background NPC Activity",
                content_zh=(
                    "每轮生成前，扫描所有不在当前场景的角色，维护'世界在运转'的感觉：\n\n"
                    "## 后台 NPC 活性检查（每轮强制）\n"
                    "从上一轮状态中扫描所有不在当前场景的角色，对每个后台角色执行：\n\n"
                    "**1. 时间推进**：该角色上轮在做什么？过了本轮的时间后自然进展到什么状态？\n\n"
                    "**2. 轨迹交叉**：其行动/想法是否与当前场景有时间、地点、人际的重叠？\n"
                    "- 人际交叉 → 主动联系玩家（来电/消息）\n"
                    "- 地点交叉 → 偶遇（街头/走廊/同一空间）\n"
                    "- 时间交叉 → 留言/未读消息/前台便条\n"
                    "- 危机驱动 → 该角色遇到麻烦，主动求助\n\n"
                    "**3. 决策**：每角色判为三类之一：\n"
                    "- 静默推进：更新变量，不在叙事中展现\n"
                    "- 背景提及：1-2句环境细节（消息提醒/旁人提及/环境音）\n"
                    "- 主动介入：直接打断场景（敲门/来电/偶遇），该角色变为出场角色\n\n"
                    "每轮至少更新 2 个后台角色的'当前行动'和'内心想法'（即使只是'继续做同一件事'也要更新）。"
                    "轮转优先级：上次更新距今最久者优先。\n\n"
                    "使用 npc_activity_scan 工具获取待处理列表，"
                    "使用 npc_update_state 工具记录更新结果。"
                ),
                content_en=(
                    "Before each turn, scan all off-screen NPCs to maintain the sense "
                    "of a living world. For each NPC: advance their timeline, check "
                    "trajectory crossing with the current scene, and decide: silent "
                    "advance / background mention / active intervention. Update at "
                    "least 2 background NPCs per turn."
                ),
                category="roleplay",
                tags=["npc", "activity", "background", "continuity"],
            ),
            Skill(
                skill_id="genre_xianxia",
                label_zh="仙侠题材写作指导",
                label_en="Xianxia Genre Writing",
                content_zh=(
                    "仙侠网文写作核心要点（来自 webnovel-writer）：\n\n"
                    "## 战力体系\n"
                    "- 主角实力不超过 state.json 中的当前境界记录\n"
                    "- 越级战斗必须：金手指/秘法加持/对手受伤被削弱/环境优势\n"
                    "- 境界提升必须有明确的突破事件和铺垫\n\n"
                    "## 爽点设计\n"
                    "- 每章至少 1 个爽点（过渡章也要有）\n"
                    "- 经典爽点模式：扮猪吃虎、打脸装逼、奇遇得宝、突破打脸\n"
                    "- 爽点循环：铺垫→压力积累→释放→反应（他人震惊/重新评估）→衔接下一铺垫\n\n"
                    "## 节奏控制\n"
                    "- 战斗章句子变短变碎，平静章可以有长段描写\n"
                    "- 高潮前信息密度递增，高潮后再放松\n"
                    "- 每章末尾留钩子，不让读者找到停下不读的借口\n\n"
                    "## 对话\n"
                    "- A级反派有智商有个性，B级以下可脸谱化\n"
                    "- 嘲讽要有信息量和角色特色，不是千篇一律的'你这个蝼蚁！'\n"
                    "- 主角说话应有个人口癖和惯用语"
                ),
                content_en=(
                    "Xianxia web novel writing guidelines: power system consistency, "
                    "satisfaction point (shuang dian) design every chapter, pacing "
                    "control, and dialogue quality by character tier."
                ),
                category="writing",
                tags=["genre", "xianxia", "power-system", "pacing"],
            ),
            Skill(
                skill_id="cool_point_loops",
                label_zh="爽点循环设计",
                label_en="Cool Point Loop Design",
                content_zh=(
                    "爽点循环四层结构（来自 webnovel-writer）：\n\n"
                    "1. **铺垫层**：埋下矛盾、展示差距、制造期待\n"
                    "2. **释放层**：主角以超出预期的方式解决矛盾\n"
                    "3. **反应层**：旁观者震惊/重新评估/态度转变\n"
                    "4. **衔接层**：引出下一个矛盾或更高层次的挑战\n\n"
                    "## 关键指标\n"
                    "- 铺放比：铺垫长度 vs 释放长度，经典比例约 3:1 到 2:1\n"
                    "- 反应层数：每波爽点至少 2-3 层反应（单人→围观→传播→权威认可）\n"
                    "- 间接爽点：通过他人之口/侧面描写/环境变化体现主角成长\n\n"
                    "## 避免\n"
                    "- 爽点过于密集导致麻木（应在高潮间留呼吸空间）\n"
                    "- 同一套路重复使用（每次换地图/角色/冲突/奖励）\n"
                    "- 配角沦为工具人（给配角独立动机和弧线）"
                ),
                content_en=(
                    "Four-layer cool point structure: setup, release, reaction layers, "
                    "transition. Key metrics: setup/release ratio, reaction layer count, "
                    "indirect satisfaction points."
                ),
                category="writing",
                tags=["cool-point", "pacing", "structure", "satisfaction"],
            ),
            Skill(
                skill_id="anti_trope_rules",
                label_zh="反套路创作规则",
                label_en="Anti-Trope Rules",
                content_zh=(
                    "反套路创作的核心不是拒绝套路，而是用陌生化的套路制造新鲜感"
                    "（来自 webnovel-writer creativity references）：\n\n"
                    "## 规则一：套路是骨架，反套路是血肉\n"
                    "保留读者熟悉的类型框架（废柴逆袭/退婚流/穿越），"
                    "但在执行层面做差异化——换动机、换方式、换后果。\n\n"
                    "## 规则二：陌生化四大手法\n"
                    "- **视角反转**：从反派/配角/围观群众视角重述经典桥段\n"
                    "- **因果重写**：保留结果但改变原因（不是你想象的那样）\n"
                    "- **尺度缩放**：把宏大冲突缩小为日常细节，或反过来\n"
                    "- **类型混合**：仙侠+推理、科幻+田园、武侠+校园\n\n"
                    "## 规则三：读者的三种期待\n"
                    "- **类型期待**：必须兑现（仙侠要有修仙，言情要有感情线）\n"
                    "- **套路期待**：可以调整但不能完全落空\n"
                    "- **意外期待**：必须超额兑现（读者不知道但会喜欢的）"
                ),
                content_en=(
                    "Anti-trope writing: keep the genre skeleton readers expect, "
                    "but differentiate in execution. Four defamiliarization techniques: "
                    "perspective reversal, causal rewrite, scale zoom, genre mixing."
                ),
                category="writing",
                tags=["anti-trope", "creativity", "genre", "freshness"],
            ),
            Skill(
                skill_id="story_planning",
                label_zh="剧情规划分析",
                label_en="Story Planning Analysis",
                content_zh=(
                    "## 剧情规划流程\n\n"
                    "你是剧情导演。基于以下框架分析当前故事走向（内部思考，不输出给玩家）：\n\n"
                    "### 1. 价值转换检查（麦基场景检验）\n"
                    "每个场景结束时必须有价值逆转。最近几轮每轮是否有有效价值变化？\n"
                    "NSFW/氛围沉浸/日常温情场景豁免——这些场景的'停滞'是合法的。\n\n"
                    "### 2. 布克模式定位\n"
                    "当前故事遵循哪种基本情节模式？\n"
                    "7种模式：战胜怪物/从穷到富/追寻/远航与回归/喜剧/悲剧/重生\n"
                    "五阶段节奏：期待→梦想→挫折→噩梦→奇迹/毁灭\n"
                    "如果没有清晰模式，填'自由模式'，不强套框架。\n\n"
                    "### 3. 角色原型追踪（皮尔逊12原型）\n"
                    "自我层面：无辜者→孤儿→战士→关怀者\n"
                    "灵魂层面：探索者→毁灭者→爱人\n"
                    "自性层面：统治者→魔术师→智者→愚者\n"
                    "每个NPC当前处于哪个原型阶段？弧线是否自然？\n\n"
                    "### 4. 伏笔审计\n"
                    "已埋未收的伏笔有哪些？计划何时回收？有没有被遗忘的？\n"
                    "核心伏笔应在50轮内回收。\n\n"
                    "### 5. 情感波浪线\n"
                    "最近几轮的张力曲线是否在波动？有没有过久的单一情绪？\n"
                    "波动幅度应渐进增大，在高潮处达到最大振幅。\n\n"
                    "### 6. 信息不对称检查\n"
                    "当前悬念配置：观众知道>角色知道？角色知道>观众知道？\n"
                    "信息逐层释放，每层既回答旧问题又引出新问题。\n\n"
                    "## 关键原则\n"
                    "框架服务于故事，故事不服务于框架。如果分析结论与当前场景的直觉冲突，信任场景。\n"
                    "每8轮自动触发一次。快节奏时缩短至5轮，慢节奏时延长至12轮。"
                ),
                content_en=(
                    "Story planning workflow: McKee value change check, Booker plot mode, "
                    "Pearson character archetypes, foreshadowing audit, emotional wave analysis, "
                    "information asymmetry check. Framework serves story, not vice versa."
                ),
                category="roleplay",
                tags=["story-planning", "narrative", "analysis", "director"],
            ),
        ]
        for skill in builtin:
            self._skills[skill.skill_id] = skill

    def _load_custom_skills(self) -> None:
        """Load custom skills from data/skills/ directory."""
        config = get_config()
        skills_dir = os.path.join(config.data_dir, "skills")
        if not os.path.exists(skills_dir):
            return
        for filename in os.listdir(skills_dir):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(skills_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                skill = Skill(
                    skill_id=data["skill_id"],
                    label_zh=data.get("label_zh", data["skill_id"]),
                    label_en=data.get("label_en", data["skill_id"]),
                    content_zh=data.get("content_zh", ""),
                    content_en=data.get("content_en", ""),
                    category=data.get("category", "general"),
                    tags=data.get("tags", []),
                )
                self._skills[skill.skill_id] = skill
            except Exception:
                pass

    def get_skill(self, skill_id: str) -> Optional[Skill]:
        """Get a skill by ID."""
        return self._skills.get(skill_id)

    def list_skills(self) -> list[Skill]:
        """List all available skills."""
        return list(self._skills.values())

    def list_skill_ids(self) -> list[str]:
        """List all skill IDs."""
        return list(self._skills.keys())

    def resolve_skills_content(
        self,
        skill_ids: list[str],
        lang: str = "zh",
    ) -> str:
        """Resolve a list of skill IDs into a prompt fragment.

        Args:
            skill_ids: List of skill IDs to include.
            lang: 'zh' or 'en'.

        Returns:
            A markdown string with skill contents, ready to inject into
            an agent system prompt.
        """
        parts: list[str] = []
        for sid in skill_ids:
            skill = self._skills.get(sid)
            if not skill:
                continue
            content = skill.content_zh if lang == "zh" else skill.content_en
            if not content:
                continue
            label = skill.label_zh if lang == "zh" else skill.label_en
            parts.append(f"### {label}\n{content}")
        if not parts:
            return ""
        return "## 授予的技能\n\n" + "\n\n".join(parts) if lang == "zh" else "## Granted Skills\n\n" + "\n\n".join(parts)

    def save_skill(self, skill: Skill) -> None:
        """Save a custom skill to disk."""
        config = get_config()
        skills_dir = os.path.join(config.data_dir, "skills")
        os.makedirs(skills_dir, exist_ok=True)
        filepath = os.path.join(skills_dir, f"{skill.skill_id}.json")
        data = {
            "skill_id": skill.skill_id,
            "label_zh": skill.label_zh,
            "label_en": skill.label_en,
            "content_zh": skill.content_zh,
            "content_en": skill.content_en,
            "category": skill.category,
            "tags": skill.tags,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self._skills[skill.skill_id] = skill
