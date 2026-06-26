# P4B — RP Canonical Identity, Scene Continuity & Length Contract V1

**日期**: 2026-06-26
**分支**: `phase-2-structured-memory`（基于 Phase 2 未提交代码）
**范围**: 不改 Phase 1 冻结文件；不改 Phase 2 结构化记忆逻辑；不改 Curator；不 commit/tag/freeze。

---

## 0. P3B 取证摘要

| Turn | 正确角色名 | Writer 实际输出 | 漂移角色名 | 正文字数 |
|------|-----------|----------------|-----------|---------|
| T01  | 周语晴    | 周语晴 ✓       | —         | ~450    |
| T02  | 周语晴    | **翠英** ✗     | 翠英      | ~498    |
| T05  | 周语晴    | **苏杏儿** ✗   | 苏杏儿    | ~422    |
| T07  | 周语晴    | **秀兰** ✗     | 秀兰      | ~622    |

**根因**: Writer 系统提示词中无任何角色身份锚定。世界书条目过多（13–19 条/轮）稀释了角色信息。Writer 将无关世界书 NPC 名字误认为当前场景角色。错误输出被写入历史后自我放大（T02 错误 → T03+ 历史含"翠英" → 后续继续漂移）。

**关键结论**: 这不是纯 prompt 工程问题。是 MainAgent 的上下文合同缺失、输出验证不足、提交边界不存在的三重问题。

---

## 1. 设计目标与不变量

### 目标
1. 固定角色在任何回合中不得被改名或替换为无来源名字。
2. Writer 不得凭空引入未授权人物作为当前场景的说话者、行动者或关系替代者。
3. 世界书 NPC 条目不得因关键词匹配而反复污染不相关场景的 Writer 上下文。
4. Writer 输出必须通过身份/场景/长度合同验证后才能写入历史、记忆、MVU。
5. 每回合正文不少于 800 汉字（不含 `<options>` 块）。

### Phase 1 不变量（不得违反）
- routed worldbook 不二次注入（`main_agent.py` 中 `is_routed` 分支保持不变）
- Writer 总调用 ≤ 2（初始 1 次 + 统一修订 1 次）
- `<thinking>/<analysis>/advice` 安全屏障不回归
- `output_sanitizer.py` 不修改
- `round_routing.py` V1 子 Agent 路由逻辑不修改
- `rp-memory-curator` 不修改

### Phase 2 不变量
- `memory/structured.py` 不修改
- 结构化记忆读写逻辑不修改
- curator 触发逻辑不修改

---

## 2. Canonical Cast Contract（演员合同）

### 2.1 数据结构

```python
# runtime/cast_contract.py (新文件)

@dataclass
class CastMember:
    canonical_id: str          # 来自卡片/变量的实体 ID
    canonical_name: str        # 正式名字（如"周语晴"）
    allowed_aliases: list[str] # 允许的别名（如"语晴"）
    role: str                  # 角色身份（如"儿媳"）
    relationship: str          # 与主角的关系（如"公公→儿媳"）
    state: str                 # "active" | "referenced" | "inactive"
    source: str                # "card" | "variable" | "worldbook" | "user_input"

@dataclass
class CastContract:
    session_characters: list[CastMember]   # 所有已知角色
    scene_characters: list[str]            # 当前场景在场角色 ID
    speakable_characters: list[str]        # 允许说话/行动的角色 ID
    user_introduced: list[str]             # 本回合用户引入的新角色名
    known_names_whitelist: set[str]        # 所有合法名字（canonical + aliases）
    player_identity: str                   # 玩家扮演的角色身份
    narrator_name: str                     # 主角名字（如"老马"）
```

### 2.2 构造逻辑

**输入来源**（不硬编码任何人名）：
1. **角色卡 worldbook 条目**: `entity_ids` 字段提取角色 ID 和名字
2. **当前变量状态** (`current_variables`): `relationship_state` 的 key 是已知名字
3. **场景状态** (`scene_state`): `characters_present` 是在场角色
4. **用户输入**: 本回合新引入的名字（与已知名字集合做差集）
5. **Open threads**: `entity` 字段提取被提及的角色

**构造流程**:
```
1. 从 worldbook entries 提取 entity_ids → 候选角色池
2. 从 variables 提取 relationship_state keys → 候选角色池
3. 合并去重 → session_characters
4. 从 scene_state.characters_present → scene_characters
5. scene_characters + 常开角色 → speakable_characters
6. 用户输入中出现但不在 session_characters 中的名字 → user_introduced（候选，不自动授权）
7. 汇总所有 known_names_whitelist = canonical_name + allowed_aliases
```

**桃花村卡示例**（自动推导，不硬编码）：
```python
# 卡片 worldbook 条目包含:
# - entity_ids: ["周语晴"] with role "儿媳"
# - entity_ids: ["老马"] with role "公公"（主角）
# variables 中 relationship_state: {"周语晴": {...}}
# scene_state.characters_present: ["周语晴", "老马"]

CastContract(
    session_characters=[
        CastMember("周语晴", "周语晴", ["语晴"], "儿媳", "儿媳", "active", "card"),
        CastMember("老马", "老马", [], "公公/主角", "玩家", "active", "card"),
    ],
    scene_characters=["周语晴", "老马"],
    speakable_characters=["周语晴", "老马"],
    user_introduced=[],
    known_names_whitelist={"周语晴", "语晴", "老马"},
    player_identity="公公",
    narrator_name="老马",
)
```

### 2.3 注入位置

**Writer 系统提示词中**，在所有世界书、历史、记忆之前：

```
## 角色合同（不可违反）

你正在扮演：{player_identity}（{narrator_name}）

当前场景在场人物：
- 周语晴（儿媳，老马的儿媳）—— 唯一在场女性，唯一可说话的女性角色
- 老马（公公，你扮演的角色）

### 硬性规则
1. 在场人物的名字和身份不可更改。不得用"翠英""苏杏儿""秀兰""青荷""宋招娣"等任何其他名字替代"周语晴"。
2. 不得自行引入新的说话者或行动者。用户未明确引入的 NPC 不得出现在当前场景中。
3. 人物称谓必须与上述角色关系一致。
```

### 2.4 接口

```python
def build_cast_contract(
    worldbook_entries: list[dict],     # 当前轮匹配的世界书条目
    current_variables: dict,           # MVU 变量状态
    scene_state: dict,                 # 当前场景状态
    user_input: str,                   # 用户输入（检测新引入角色）
    open_threads: list[dict],          # 开放线索
) -> CastContract:
    """从卡/会话状态构造演员合同。零 LLM，纯确定性。"""
```

---

## 3. Scene Continuity Contract（场景连续性合同）

### 3.1 数据结构

```python
# runtime/scene_contract.py (新文件)

@dataclass
class SceneContract:
    location: str                  # 当前地点
    time_of_day: str               # 当前时间
    characters_present: list[str]  # 当前在场人物名
    last_valid_action: str         # 上回合最后有效动作（摘要）
    relationship_constraint: str   # 当前关系/情绪约束（如"周语晴脸红，气氛暧昧"）
    open_commitments: list[str]    # 未完成承诺或动作
    immutable_facts: list[str]     # 本回合不可改写的事实
    allowed_changes: list[str]     # 允许的场景变化
    forbidden_changes: list[str]   # 禁止的场景变化
```

### 3.2 构造逻辑

**输入来源**：
1. `scene_state` (来自结构化记忆或变量): location, time_of_day, characters_present, mood
2. 最近一轮 history_turns: 提取最后有效动作
3. `open_threads`: 未完成承诺
4. 变量中的 `relationship_state`: 当前关系约束

**构造流程**:
```
1. scene_state → location, time_of_day, characters_present
2. 最近一轮 ai_reply 前 200 字 → last_valid_action
3. relationship_state 最新值 → relationship_constraint
4. open_threads 中 status=open → open_commitments
5. scene_state.mood + 变量 diff → immutable_facts / allowed_changes / forbidden_changes
```

### 3.3 注入位置

**系统提示词中**，在角色合同之后、世界书之前：

```
## 场景状态（锚定）

地点：{location}（{具体描述}）
时间：{time_of_day}
在场人物：{characters_present（与角色合同一致）}
上一动作：{last_valid_action}
当前氛围：{relationship_constraint}
未完成：{open_commitments}

### 场景规则
- 不得自行跳转地点或时间
- 不得自行改变在场人物
- 不得违反当前氛围约束（如不得突然从暧昧变冷漠）
```

**重复锚点**：在用户输入之前（系统提示词末尾），放置简短版本：

```
## 当前场景提醒
地点={location} | 时间={time_of_day} | 在场={characters_present} | 关系={relationship_constraint}
```

---

## 4. Cast-aware Worldbook Filter（角色感知世界书过滤）

### 4.1 设计原则

不推翻 Phase 1 Router 和预算逻辑。在 `apply_worldbook_budget` 之后、进入 Writer 系统提示词之前，增加一层角色感知过滤。

### 4.2 过滤规则

```
对于每个世界书条目：
1. 如果是世界观底层规则（无 entity_ids 或 entity_ids 为空）→ 保留
2. 如果 entity_ids 中有当前 scene_characters → 保留
3. 如果 entity_ids 中的角色在 user_input 中被明确提及 → 保留（来源=用户提及）
4. 如果 entity_ids 中的角色在 scene_contract.immutable_facts 中被提及 → 保留
5. 否则 → 过滤掉（记录 trace）
```

### 4.3 Trace 记录

```python
@dataclass
class WBFilterTrace:
    entry_id: str
    entity_type: str          # "world_rule" | "character" | "location" | "event"
    allowed: bool
    reason: str               # "active_cast" | "user_mentioned" | "world_rule" | "not_in_scene"
    active_scene_relevance: float  # 0.0-1.0
```

### 4.4 接口

```python
def apply_cast_aware_filter(
    worldbook_entries: list[dict],
    cast_contract: CastContract,
    scene_contract: SceneContract,
    user_input: str,
) -> tuple[list[dict], list[WBFilterTrace]]:
    """在预算之后、注入之前，按角色相关性过滤世界书条目。"""
```

### 4.5 注入位置

在 `main_agent.py` 中，当 `is_routed=True` 时：
- routed worldbook 已由 RoundPreparer 处理（Phase 1 逻辑不变）
- 在 `resolved_worldbook` 文本拼装后，但在注入 Writer 之前，应用 cast-aware filter

当 `is_routed=False`（legacy path）时：
- 在 `build_filtered_worldbook_text` 之后应用

**实现方式**: 在 `main_agent.py` 的 `execute` 方法中，context_text 组装之前，对 worldbook 条目列表应用过滤。需要将 resolved_worldbook 从文本回溯为条目列表，或在 `RoundContextPacket` 中保留条目列表（`retrieved_worldbook_entries` 已有此字段）。

---

## 5. Identity / Role / Scene Guard（身份/场景守卫）

### 5.1 检查项

```python
# runtime/identity_guard.py (新文件)

@dataclass
class GuardViolation:
    code: str                  # 违规类型码
    severity: str              # "error" | "warning"
    message: str               # 人类可读描述
    evidence: str              # 文本中的证据片段
    suggestion: str            # 修订建议

# 违规类型码：
# UNAUTHORIZED_NEW_CHARACTER  — 出现不在 cast_contract 中的新角色名
# FIXED_CHARACTER_REPLACED    — 固定角色被改名（如用"翠英"替代"周语晴"）
# NON_SCENE_CHARACTER_ACTING  — 不在场人物承担当前动作/对话
# UNAUTHORIZED_LOCATION_JUMP  — 无授权的地点跳转
# UNAUTHORIZED_TIME_JUMP      — 无授权的时间跳转
# RELATIONSHIP_MISMATCH       — 关系称谓与 canonical contract 冲突
```

### 5.2 检测逻辑

#### 5.2.1 人名检测白名单

```python
def _build_name_whitelist(cast_contract: CastContract) -> set[str]:
    """构建合法名字白名单。"""
    whitelist = set()
    for member in cast_contract.session_characters:
        whitelist.add(member.canonical_name)
        whitelist.update(member.allowed_aliases)
    whitelist.update(cast_contract.user_introduced)  # 用户引入的可提及
    return whitelist
```

#### 5.2.2 未授权角色名检测

```python
def _detect_unauthorized_names(
    text: str,
    whitelist: set[str],
    known_non_name_patterns: set[str],  # 常见非人名词（避免误报）
) -> list[GuardViolation]:
    """检测文本中出现的、不在白名单中的人名。

    策略：
    1. 从文本中提取 2-4 字的中文词，过滤掉常见非人名词
    2. 检查是否在白名单中
    3. 检查是否在世界书条目标题中（可能是合法 NPC 引用）
    4. 不在任何已知集合中 → 标记为未授权
    """
```

#### 5.2.3 固定角色替换检测

```python
def _detect_character_replacement(
    text: str,
    cast_contract: CastContract,
    worldbook_entry_names: set[str],
) -> list[GuardViolation]:
    """检测固定角色是否被替换。

    策略：
    1. 如果 scene_characters 中的 canonical_name 不在文本中出现
    2. 但世界书中的其他 NPC 名字出现在文本中
    3. 且该 NPC 不在 scene_characters 中
    4. → 标记为 FIXED_CHARACTER_REPLACED

    但：如果 canonical_name 和 NPC 名字同时出现，可能是合法引用。
    """
```

#### 5.2.4 场景/时间跳转检测

```python
def _detect_scene_jump(
    text: str,
    scene_contract: SceneContract,
) -> list[GuardViolation]:
    """检测无授权的地点/时间跳转。

    策略：
    1. 检测文本中出现的地点词（村口、田里、镇上...）
    2. 如果不在 scene_contract.allowed_changes 中
    3. 且不在 scene_contract.location 中
    4. → 标记为 UNAUTHORIZED_LOCATION_JUMP

    时间同理。
    """
```

### 5.3 修订指令生成

当 identity guard 检测到违规时，生成具体的修订指令：

```python
def build_identity_revision_prompt(violations: list[GuardViolation], cast_contract: CastContract) -> str:
    """生成修订指令，要求 Writer 统一修正。"""
    # 示例输出：
    # "## 身份合同未通过
    #  1. 你使用了"翠英"，但当前场景在场人物为周语晴（儿媳）。请使用正确名字。
    #  2. 当前场景在院门口，不得跳转到其他地点。
    #  请重新撰写，确保所有角色名字、场景地点与上述合同一致。"
```

### 5.4 与现有修复循环的集成

**不替换**现有 `sanitize_output` + `apply_quality_gate` 修复循环。在其之后、session 记录之前，增加 identity guard + length guard。

**关键约束**: 第一次检测到违规 → 进入统一修订（与现有修复共享同一次 Writer 调用）。第二次仍不合格 → 进入受控质量失败，不写入历史/记忆/MVU。

### 5.5 接口

```python
def validate_writer_output(
    text: str,
    cast_contract: CastContract,
    scene_contract: SceneContract,
    worldbook_entry_names: set[str],
) -> tuple[list[GuardViolation], str]:
    """验证 Writer 输出是否符合身份/场景合同。

    返回: (violations, revision_prompt)
    violations 为空 → 通过
    violations 非空 → revision_prompt 可直接送入 Writer 修订
    """
```

---

## 6. 800 汉字正文合同

### 6.1 正文长度计算

```python
def count_narrative_hanzi(text: str) -> int:
    """计算正文字数（汉字数）。

    1. 去除 <options>...</options> 块
    2. 去除 HTML 标签（<font>, <br>, <div> 等）
    3. 去除 Markdown 标记（#、**、*、`、>）
    4. 去除空白字符
    5. 统计 Unicode 汉字范围 \u4e00-\u9fff 的字符数
    """
```

### 6.2 Writer Profile 修改

修改 `rp-writer` 的 `foundational_system_prompt`（profile.py 中），在输出格式部分增加：

```
## 长度要求
- 每回合叙事正文不少于 800 个汉字
- 目标正文长度：900-1200 汉字
- <options> 块不计入正文长度
- 选项块限制为 3 个简短选项，不挤占叙事预算
```

### 6.3 max_tokens 调整

将 `rp-writer` 的 `default_model_config.max_tokens` 从 2048 提升到 4096，确保空间充足。

### 6.4 长度验证

```python
def validate_narrative_length(text: str) -> tuple[bool, int, str]:
    """验证正文长度是否满足 800 汉字要求。

    返回: (passed, hanzi_count, revision_prompt)
    """
```

### 6.5 统一修订

当长度不足时，生成修订指令：

```
"## 正文长度不足
当前正文仅 {count} 汉字，要求不少于 800 汉字。
请扩展叙事，增加细节描写、对话、动作、环境感知，使正文达到 800 汉字以上。
<options> 块不计入正文字数。"
```

---

## 7. MainAgent 修复循环重构

### 7.1 当前流程

```
Writer LLM 调用（初始）
→ sanitize_output（标签/元话语）
→ apply_quality_gate（确定性检查）
→ 如果失败：修订 Writer 调用（共 1 次）
→ 最终安全屏障
→ 写入历史/记忆/MVU
```

### 7.2 新流程

```
Writer LLM 调用（初始）
→ sanitize_output（标签/元话语）          ← 不变
→ apply_quality_gate（确定性检查）         ← 不变
→ identity_guard（身份/场景合同验证）      ← 新增
→ length_guard（800 汉字验证）             ← 新增
→ 如果任何一项失败：统一修订 Writer 调用（共 1 次）
  → 修订指令合并：sanitize + quality gate + identity + length 的所有失败项
→ 最终安全屏障                             ← 不变
→ identity_guard 再次验证（最终门）         ← 新增
→ length_guard 再次验证（最终门）            ← 新增
→ 如果最终门仍失败：REJECT_GIVE_UP，不写入历史/记忆/MVU  ← 新增
→ 写入历史/记忆/MVU                        ← 仅在全部通过后执行
```

### 7.3 提交边界

**核心变更**: 将 `session_manager.record_turn()` 和 MVU `execute_commands()` 移到最终验证通过之后。

当前代码中，`session_manager.record_turn()` 在最终安全屏障之后执行——这已经是正确的。但需要确保 identity guard 和 length guard 也在 record 之前。

```python
# 伪代码
final_verdict = sanitize_output(...)
# ... existing barrier logic ...

# P4B: Identity + Length final gate
cast_violations, cast_rev_prompt = validate_writer_output(final_text, cast_contract, scene_contract, wb_names)
length_ok, hanzi_count, length_rev_prompt = validate_narrative_length(final_text)

if cast_violations or not length_ok:
    # 不合格 → 不写入历史/记忆/MVU
    final_text = "[生成质量失败] 本回合内容未通过身份或长度合同检查。请重新发送消息。"
    # 跳过 record_turn, MVU, memory_curation
else:
    # 合格 → 写入
    session_manager.record_turn(...)
    # MVU extraction
    # memory curation
```

---

## 8. 文件变更清单

### 新增文件（5 个）

| 文件 | 用途 | 行数估算 |
|------|------|---------|
| `runtime/cast_contract.py` | Canonical Cast Contract 数据结构 + 构造逻辑 | ~150 |
| `runtime/scene_contract.py` | Scene Continuity Contract 数据结构 + 构造逻辑 | ~120 |
| `runtime/cast_aware_wb_filter.py` | 角色感知世界书过滤 + trace | ~100 |
| `runtime/identity_guard.py` | 身份/场景/角色守卫 + 检测 + 修订指令生成 | ~200 |
| `runtime/length_guard.py` | 800 汉字正文长度验证 + 计算 | ~60 |

### 修改文件（3 个）

| 文件 | 变更内容 | 影响范围 |
|------|---------|---------|
| `runtime/round_contracts.py` | `RoundContextPacket` 新增 `canonical_cast` 和 `scene_continuity` 字段（带默认空值，向后兼容） | 数据合同 |
| `runtime/round_routing.py` | `build_round_routing_decision` 新增可选参数 `worldbook_entries` 和 `scene_state`，传递给 cast/scene contract 构造 | 路由决策 |
| `nodes/router_nodes.py` | `AWPSubAgentOrchestrator.execute()` 中构造 cast_contract 和 scene_contract，注入 RoundContextPacket | 节点编排 |

### 修改文件（2 个，核心变更）

| 文件 | 变更内容 | 影响范围 |
|------|---------|---------|
| `nodes/main_agent.py` | (1) 注入 cast/scene contract 到 Writer 系统提示词（高优先级位置）；(2) 应用 cast-aware worldbook filter；(3) 修复循环中集成 identity guard + length guard；(4) 将 session 记录/MVU 移到最终验证通过之后 | 主 Agent 节点 |
| `profile/profile.py` | (1) `rp-writer` system prompt 增加长度要求和角色锚定框架；(2) `max_tokens` 从 2048 → 4096 | Profile 定义 |

### 不修改的文件

| 文件 | 原因 |
|------|------|
| `runtime/output_sanitizer.py` | Phase 1 冻结 |
| `runtime/subagent_orchestrator.py` | Phase 1 冻结 |
| `runtime/round_routing.py` 中 V1 路由逻辑 | Phase 1 冻结（仅新增可选参数，不改现有逻辑） |
| `nodes/memory_nodes.py` | Phase 1 冻结 |
| `memory/structured.py` | Phase 2 不修改 |
| `knowledge/worldbook.py` | Phase 1 冻结（budget 逻辑不变，cast filter 在 budget 之后独立执行） |
| `nodes/pipeline_nodes.py` | Phase 1 冻结（legacy path 不变） |

---

## 9. 与 Phase 1/2 的边界

| 边界 | 处理方式 |
|------|---------|
| Phase 1 routed worldbook 不二次注入 | 保持。cast-aware filter 在 `resolved_worldbook` 文本组装之后、注入 Writer 之前执行，不重新调用 `build_filtered_worldbook_text` |
| Phase 1 Writer ≤ 2 次调用 | 保持。identity/length guard 复用已有的 1 次修订机会，不新增 Writer 调用。最终门是验证而非再生成 |
| Phase 1 安全屏障 | 保持。identity guard 在 sanitize_output 之后执行，不冲突 |
| Phase 2 结构化记忆 | 保持。cast contract 从 scene_state 读取 characters_present，不修改 scene_state |
| Phase 2 curator | 保持。curator 在 identity guard 通过后执行（如果 should_curate_memory=True） |

---

## 10. 测试矩阵

### 测试文件

新增: `test_p4b_identity_scene_length.py`

### 测试用例（≥ 14 项）

#### 10.1 Cast Contract 构造（3 项）

| # | 测试名 | 描述 |
|---|--------|------|
| T1 | `test_cast_contract_from_card` | 从 worldbook 条目 + 变量构造 contract，验证 canonical_name、role、relationship |
| T2 | `test_cast_contract_user_introduced` | 用户输入含新名字 → user_introduced 列表正确，不自动授权为 speakable |
| T3 | `test_cast_contract_empty_state` | 空变量/空 worldbook → contract 有默认值，不崩溃 |

#### 10.2 Identity Guard 检测（4 项）

| # | 测试名 | 描述 |
|---|--------|------|
| T4 | `test_guard_detects_drift_name` | Writer 输出含"翠英"，canonical_name="周语晴" → 检测到 FIXED_CHARACTER_REPLACED |
| T5 | `test_guard_allows_correct_name` | Writer 输出含"周语晴" → 无违规 |
| T6 | `test_guard_allows_user_introduced_npc` | 用户输入含"张三"，Writer 输出提及"张三" → 不误判 |
| T7 | `test_guard_filters_unauthorized_scene_character` | 世界书有"苏杏儿"条目但不在场 → 非 speakable，检测到 NON_SCENE_CHARACTER_ACTING |

#### 10.3 Length Guard（2 项）

| # | 测试名 | 描述 |
|---|--------|------|
| T8 | `test_length_guard_short_text` | 295 汉字 → 不通过，revision_prompt 包含字数和扩展要求 |
| T9 | `test_length_guard_options_excluded` | 正文 700 汉字 + `<options>` 150 汉字 → 不通过（options 不计入） |

#### 10.4 Cast-aware Worldbook Filter（2 项）

| # | 测试名 | 描述 |
|---|--------|------|
| T10 | `test_wb_filter_inactive_npc_filtered` | 世界书有"苏杏儿"条目，但不在场、用户未提及 → 过滤掉 |
| T11 | `test_wb_filter_world_rule_preserved` | 世界观底层规则（无 entity_ids）→ 保留 |

#### 10.5 集成测试（3 项）

| # | 测试名 | 描述 |
|---|--------|------|
| T12 | `test_drift_detected_revision_then_pass` | Writer 输出含"翠英" → identity guard 检测 → 修订指令 → 模拟修订后含"周语晴" → 通过 |
| T13 | `test_drift_twice_reject_give_up` | Writer 两次输出都含错误名字 → REJECT_GIVE_UP，不写入历史 |
| T14 | `test_p3b_t01_t02_minimal_repro` | T01 正确身份 → T02 不得漂移 → 无效输出不污染下一轮历史 |

#### 10.6 Phase 1 不变量回归（3 项）

| # | 测试名 | 描述 |
|---|--------|------|
| T15 | `test_routed_worldbook_no_double_injection` | is_routed=True 时不调用 build_filtered_worldbook_text |
| T16 | `test_writer_call_count_max_two` | 修复后 Writer 总调用 ≤ 2 |
| T17 | `test_safety_barrier_not_regressed` | `<thinking>` 标签仍触发 REJECT_RETRY / REJECT_GIVE_UP |

---

## 11. 实施顺序

### Step 1: 数据层（纯函数，无依赖）
1. `runtime/cast_contract.py` — CastContract + build_cast_contract
2. `runtime/scene_contract.py` — SceneContract + build_scene_contract
3. `runtime/length_guard.py` — count_narrative_hanzi + validate_narrative_length

### Step 2: 过滤层（依赖 Step 1）
4. `runtime/cast_aware_wb_filter.py` — apply_cast_aware_filter

### Step 3: 验证层（依赖 Step 1）
5. `runtime/identity_guard.py` — validate_writer_output + build_identity_revision_prompt

### Step 4: 数据合同扩展
6. `runtime/round_contracts.py` — RoundContextPacket 新增字段

### Step 5: Profile 修改
7. `profile/profile.py` — rp-writer prompt 增强 + max_tokens

### Step 6: 节点层集成
8. `nodes/router_nodes.py` — 构造 cast/scene contract
9. `nodes/main_agent.py` — 注入 prompt + filter + guard + 提交边界

### Step 7: 测试
10. `test_p4b_identity_scene_length.py` — 14+ 测试用例

---

## 12. 风险与回滚

| 风险 | 缓解 | 回滚 |
|------|------|------|
| 人名误报：普通叙事词被误判为未授权人名 | 白名单 + 常见非人名词过滤 + 用户引入角色豁免 | 降低 guard 灵敏度为 warning-only，不阻断 |
| 过度过滤：世界书条目被误杀 | 只过滤有 entity_ids 且不在场的 NPC 条目，世界规则永不杀 | 禁用 cast-aware filter（feature flag） |
| Writer 修订后仍不足 800 字 | 最终门检查 → REJECT_GIVE_UP（受控失败） | 降低阈值到 600 字 |
| identity guard 检测遗漏（如用第三人称描述替代直接命名） | 保守检测 + 白名单兜底 | 这是已知限制，不在 V1 范围内 |
| Phase 1 不变量违反 | 测试矩阵 T15-T17 强制回归 | revert 相关文件到 Phase 1 冻结状态 |

---

## 13. 与 P4A Curator 修复的关系

P4A（Curator 可靠性修复）与 P4B **完全独立**：

- P4A 修改 `rp-memory-curator` profile（加 `response_format='json_object'`）
- P4B 修改 `rp-writer` profile + MainAgent 节点 + 新增 runtime 模块
- 两者无文件交叉（curator profile ≠ writer profile，curator 执行逻辑 ≠ identity guard）
- P4A 可在 P4B 之前、之后或同时进行
- 建议：P4B 先行（解决第一阻塞项），P4A 随后（提升 curator 成功率）

---

## 14. 预计工作量

| 步骤 | 文件 | 预计行数 | 预计时间 |
|------|------|---------|---------|
| Step 1 | 3 个新 runtime 模块 | ~330 行 | 中 |
| Step 2 | 1 个新 runtime 模块 | ~100 行 | 低 |
| Step 3 | 1 个新 runtime 模块 | ~200 行 | 中 |
| Step 4 | round_contracts.py 修改 | ~15 行 | 低 |
| Step 5 | profile.py 修改 | ~20 行 | 低 |
| Step 6 | router_nodes.py + main_agent.py 修改 | ~150 行 | 高 |
| Step 7 | 测试文件 | ~400 行 | 高 |
| **合计** | **5 新 + 4 改 + 1 测试** | **~1200 行** | **高** |
