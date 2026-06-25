# AWP RP — 使用说明书

> 一个 ComfyUI 自定义节点包，在可视化画布上搭建角色扮演和长篇网文创作工作流。

---

## 目录

- [1. 安装](#1-安装)
- [2. 快速开始：第一次 RP](#2-快速开始第一次-rp)
- [3. 导入角色卡](#3-导入角色卡)
- [4. 两种工作模式](#4-两种工作模式)
- [5. 完整工作流示例](#5-完整工作流示例)
- [6. 所有节点一览](#6-所有节点一览)
- [7. 常见场景](#7-常见场景)
- [8. 独立 Web 前端](#8-独立-web-前端)
- [9. 高级功能](#9-高级功能)
- [10. 故障排查](#10-故障排查)

---

## 1. 安装

### 前提条件

- ComfyUI 已安装并能正常运行
- 一个 LLM API Key（推荐 [DeepSeek](https://platform.deepseek.com)）

### 安装步骤

```
1. 将 awp-demo-turn-lifecycle 目录放入 ComfyUI 的 custom_nodes/ 目录

2. 配置 API Key：复制 .env.example 为 .env，填入你的 API Key
   DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx

3. 重启 ComfyUI
```

启动 ComfyUI 后，在节点菜单中搜索 "AWP" 即可看到所有节点（共 39 个）。

### 可选依赖

```bash
# 中文分词（提高检索精度）
pip install jieba

# 向量语义检索
pip install chromadb

# YAML 支持（formatvar 宏输出更美观）
pip install pyyaml
```

---

## 2. 快速开始：第一次 RP

### 2.1 添加节点

在 ComfyUI 画布空白处右键，搜索并添加以下节点：

| 搜索关键词 | 节点名 | 作用 |
|-----------|--------|------|
| `AWPRound` | AWPRoundPreparer | 回合预处理 |
| `AWPMain` | AWPMainAgent | 主 Agent |
| `AWPText` | AWPTextInput | 文本输入 |
| `AWPText` | AWPTextOutput | 文本输出 |

### 2.2 连线

```
AWPTextInput (text) → AWPRoundPreparer (user_input)
AWPRoundPreparer (assembled_context) → AWPMainAgent (user_input)
AWPMainAgent (reply) → AWPTextOutput (text)
```

### 2.3 配置 MainAgent

点击 `AWPMainAgent` 节点，设置以下参数：

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| `provider` | deepseek | LLM 提供商 |
| `model` | deepseek-chat | 模型名称 |
| `profile` | rp-writer | Agent 角色（写手） |
| `enable_agent_loop` | true | **重要！** 开启 Agent Loop |
| `temperature` | 0.8 | 创造性（0=保守，1=大胆） |
| `max_iterations` | 5 | Agent 最多调用几次工具 |

### 2.4 运行

1. 在 `AWPTextInput` 中输入你的行动/对话
2. 点击 ComfyUI 的 Queue Prompt 按钮
3. 等待生成完成，在 `AWPTextOutput` 中查看回复

> **提示**：首次运行较慢，因为需要加载所有模块。后续运行会很快。

---

## 3. 导入角色卡

AWP 支持 SillyTavern V3 格式的角色卡（`.json` 和 `.png`）。

### 3.1 方法一：粘贴 JSON

添加 `AWPCardImport` 节点，在 `card_json` 框中粘贴角色卡的完整 JSON。

### 3.2 方法二：文件路径

在同一个节点的 `card_path` 框填写文件路径：

```
F:\cards\我的角色卡.png
F:\cards\我的角色卡.json
```

PNG 文件会自动提取嵌入数据。

### 3.3 使用导入的角色卡

把这三个节点串起来：

```
AWPCardImport (card_id) → AWPCardSelect (card_id)
                         → AWPGreeting (card_id) → 开场白文本

AWPCardSelect (角色卡数据) → AWPRoundPreparer (character_profile)
AWPCardSelect (世界书JSON) → AWPRoundPreparer (worldbook_index)
```

### 3.4 没有角色卡？试试这个

粘贴到 `AWPCardImport` 的 `card_json`：

```json
{
  "spec": "chara_card_v3",
  "spec_version": "3.0",
  "data": {
    "name": "璃夏",
    "description": "旧书店店主，外表25岁女性。冷静敏锐，习惯用克制的语气试探对方。",
    "personality": "冷静、敏锐，内心藏着对过去的恐惧。",
    "scenario": "雨夜，玩家走进一家旧书店避雨。",
    "first_mes": "门铃轻响。她从书页间抬起头，目光在你身上停顿了一秒。'这么晚了还来书店？'",
    "mes_example": "她将书放回书架。'有些书，读过之后就再也回不去了。'"
  }
}
```

### 3.5 切换开场白

如果角色卡有多个开场白（`alternate_greetings`）：

1. 将 `AWPGreeting` 的 `mode` 设为 `list`
2. 运行一次，查看输出 `开场白列表`
3. 找到想要的 `greeting_id`，填回 `greeting_id` 框
4. 将 `mode` 改回 `select`，再次运行

---

## 4. 两种工作模式

AWP 提供两条路径，适合不同场景。

### 4.1 Direct Pipeline（简单直连）

适合**快速生成**、不需要复杂上下文检索的场景。

```
InputParser → ContextAssembler → DialogueDirector → QualityGate → OutputRenderer
```

**优点**：快，一步到位。**缺点**：不会主动查记忆/世界书，Agent Loop 的全部功能不可用。

### 4.2 Agent Loop（推荐）

适合**沉浸式 RP** 和**长篇创作**。

```
RoundPreparer → MainAgent (Agent Loop + 工具调用 + 自我反思)
```

Agent Loop 在生成回复前会**自动调用工具**获取上下文：

```
用户输入 "璃夏，你认识记忆之书吗？"
  ↓
Agent 思考 → 调用 memory_read → 调用 worldbook_read → 调用 npc_activity_scan
  ↓
结合检索结果生成回复
  ↓
Quality Gate 检查 → 如有问题自动修订
  ↓
输出最终回复 + 变量更新 + 行动选项
```

**要启用 Agent Loop**：在 `AWPMainAgent` 节点中把 `enable_agent_loop` 设为 `true`。

---

## 5. 完整工作流示例

### 5.1 RP 完整工作流（推荐）

```
┌─────────────────┐
│  AWPTextInput    │  ← 你在这里输入
│  (用户输入)       │
└────────┬────────┘
         │
┌────────▼────────┐
│ AWPRoundPreparer │  ← 自动匹配世界书、召回记忆、生成变量清单
│  (回合预处理)     │
└────────┬────────┘
         │
┌────────▼────────┐
│  AWPMainAgent   │  ← Agent Loop：调工具、生成、自省
│  (主Agent)       │     enable_agent_loop = true
└───┬───┬───┬─────┘
    │   │   │
    │   │   └──→ 变量更新 → 下轮回灌
    │   └──────→ 行动选项
    └──────────→ 回复文本
                  │
         ┌────────▼────────┐
         │  AWPTextOutput   │  ← 你在这里看回复
         │  (文本输出)       │
         └─────────────────┘
```

**可选扩展**：在 MainAgent 后面接 `AWPMVUNode` 做变量管理，接 `AWPSessionReroll` 做重生成。

### 5.2 小说写作工作流

```
AWPTextInput (章节指令) → AWPRoundPreparer → AWPMainAgent (profile=novel-long-writer)
                                                         ↓
                                                  AWPQualityGate
                                                         ↓
                                                  AWPOutputRenderer
```

在 MainAgent 中设置：
- `profile`: `novel-long-writer`
- `skill_ids`: `rp_thinking_flow,hard_gates_full,genre_xianxia`
- `max_tokens`: `4096`

### 5.3 预置工作流模板

`workflows/` 目录下有可直接加载的 JSON 工作流：

| 文件 | 用途 |
|------|------|
| `rp_agent_full.json` | RP Agent Loop（推荐） |
| `novel_writing.json` | 小说写作流程 |
| `rp_basic_workflow.json` | 基础 Direct Pipeline |
| `rp_full_node_workflow.json` | 全节点串联 |

加载方法：ComfyUI 菜单 → Load → 选择 `workflows/` 下的 JSON 文件。

---

## 6. 所有节点一览

### Agent 节点

| 节点 | 中文名 | 核心功能 |
|------|--------|---------|
| **AWPMainAgent** | 主Agent | Agent Loop，工具调用，子Agent派发，自我反思，MVU更新 |
| **AWPSubAgent** | 子Agent | 专用任务（审查/提取/拆书） |

### 管线节点

| 节点 | 中文名 | 核心功能 |
|------|--------|---------|
| **AWPRoundPreparer** | 回合预处理 | 变量驱动世界书匹配 + 输入关键词匹配 + 记忆召回 + Author's Note |
| AWPInputParser | 输入解析 | 用户输入→结构化JSON |
| AWPContextAssembler | 上下文组装 | 角色+场景+世界书+记忆→上下文 |
| AWPDialogueDirector | 对话导演 | LLM 生成 RP 回复 |
| AWPQualityGate | 质量门 | 7 维度文本质量检查 |
| AWPOutputRenderer | 最终输出 | 最终回复组装 |

### MVU 节点（变量管理）

| 节点 | 中文名 | 核心功能 |
|------|--------|---------|
| **AWPMVUNode** | MVU变量更新 | 解析 AI 输出中的变量命令，执行更新，匹配世界书 |
| **AWPMVUMacroResolver** | MVU宏解析 | `{{getvar::路径}}` 模板替换 |

### 会话节点

| 节点 | 中文名 | 核心功能 |
|------|--------|---------|
| AWPSessionLoad | 加载会话 | 读取历史对话 |
| AWPSessionSave | 保存会话 | 保存/清除会话 |
| **AWPSessionReroll** | 重roll/回退 | 删除最后一轮重新生成，或回退到指定轮次 |

### 记忆/检索/世界书

| 节点 | 中文名 | 核心功能 |
|------|--------|---------|
| AWPMemoryRead | 记忆读取 | 按标签/类型召回长期记忆 |
| AWPMemoryWrite | 记忆写入 | 持久化事件/关系 |
| AWPRetriever | 检索器 | BM25 / TF-IDF语义 / 混合检索 |
| AWPWorldbook | 世界书 | 读写世界书条目 |

### 角色卡

| 节点 | 中文名 | 核心功能 |
|------|--------|---------|
| **AWPCardImport** | 导入角色卡 | 粘贴 JSON / 填写文件路径 |
| **AWPCardSelect** | 选择角色卡 | 按 ID 选择已导入的卡 |
| **AWPGreeting** | 开场白 | 选择/切换/列出开场白 |

> **加粗** = 最常用的节点。其他节点为辅助/UI管理用。

---

## 7. 常见场景

### 7.1 怎么让 AI 不替我说话？

在 MainAgent 的 `skill_ids` 中添加 `rp_player_agency`。这个 Skill 会告诉 AI 绝不替玩家决定行动、情绪和发言。

### 7.2 怎么提高回复质量？

1. 开启 Agent Loop（`enable_agent_loop = true`）
2. 添加 Skills：`rp_thinking_flow,hard_gates_full`
3. 降低 temperature（如 `0.6`）
4. 使用 `AWPRoundPreparer` 做回合预处理

### 7.3 怎么追踪角色状态变化？

1. 在 AI 回复中包含 `<UpdateVariable>` 块（参考 [MVU 变量系统](#91-mvu-变量系统)）
2. 在 MainAgent 后面接 `AWPMVUNode`
3. 把 `更新后变量` 输出连回下一轮的 `current_variables` 输入

### 7.4 回复不满意怎么办？

使用 `AWPSessionReroll` 节点：

- `operation = reroll_last`：删除最后一轮，返回用户原始输入（把输出连回 MainAgent 的 `user_input` 重新生成）
- `operation = delete_from` + `from_index = 3`：删除第 3 轮及之后的所有内容

### 7.5 怎么写小说而不是 RP？

1. 将 MainAgent 的 `profile` 改为 `novel-long-writer`
2. 添加 `skill_ids`：`rp_thinking_flow,hard_gates_full,genre_xianxia,cool_point_loops`
3. 使用 `AWPRoundPreparer` 做写前上下文准备
4. 输入章节指令而不是对话（如 "写第100章：主角突破金丹期"）

### 7.6 怎么让 NPC 看起来像活人？

Agent Loop 启用后会自动注入 `rp_npc_activity` Skill。每轮 AI 会自动：

1. 扫描所有不在当前场景的 NPC
2. 推进他们的时间线
3. 检查是否与当前场景产生交集
4. 决定是静默推进、背景提及、还是主动介入

你也可以手动调用 `npc_activity_scan` 工具查看当前 NPC 活性状态。

### 7.7 Author's Note 和 Character Note 怎么用？

在 `AWPRoundPreparer` 节点中有两个可选的输入框：

- **Author's Note**：注入到上下文最前方，用于全局写作指令（如"本章要写出紧张感""所有对话用短句"）
- **Character Note**：注入到角色描述之后，用于角色特定指令（如"璃夏今天心情特别好"）

---

## 8. 独立 Web 前端

除了在 ComfyUI 画布中使用，AWP 还提供了一个独立的 Web 聊天界面。

### 启动

```bash
cd awp-demo-turn-lifecycle/server
python server.py --port=8765
```

浏览器打开 `http://localhost:8765`

### 功能

- 聊天界面：输入框 + 对话历史
- 行动选项：AI 生成的选项以按钮形式显示，点击直接发送
- Reroll：重新生成最后一次回复
- Clear：清空对话历史
- Settings：切换 Provider / Profile

### 工作原理

前端通过 HTTP API 调用 AWP 的 Agent 系统：

```
浏览器 → POST /api/generate → MainAgent.execute() → 返回回复 + 选项
浏览器 → POST /api/reroll   → SessionManager.reroll_last()
```

---

## 9. 高级功能

### 9.1 MVU 变量系统

MVU 让你在叙事中追踪和更新角色状态变量。

#### AI 怎么写变量更新

在回复中加入 `<UpdateVariable>` 块：

```xml
<UpdateVariable>
<Analysis>
- time passed: about 10 minutes
- 璃夏.好感度: +2 (玩家展现了诚意)
</Analysis>
<JSONPatch>
[
  {"op": "replace", "path": "/世界/时间", "value": "3月15日 14:45"},
  {"op": "delta", "path": "/璃夏/好感度", "value": 2},
  {"op": "replace", "path": "/璃夏/当前状况", "value": "坐在窗边，手指轻轻敲着书页"}
]
</JSONPatch>
</UpdateVariable>
```

支持的操作：`replace`（设置值）、`delta`（数值增减）、`insert`（插入）、`remove`（删除）、`move`（移动）。

#### 在正文中引用变量值

```
{{getvar::璃夏.好感度}}     → 输出 "42"
{{formatvar::互动对象}}     → 输出格式化的 YAML/JSON
```

使用 `AWPMVUMacroResolver` 节点来替换这些宏。

### 9.2 剧情规划（每 8 轮自动触发）

Agent Loop 模式下，每 8 轮会自动运行一次剧情规划分析。AI 会检查：

- 价值转换（每条回复是否有情感变化？）
- 情节模式（当前遵循哪种故事模式？）
- 伏笔审计（有哪些未回收的伏笔？）
- 情感波浪线（情绪是否在波动？）
- 下阶段方向建议

结果记录在 `metadata.story_plan` 中。

### 9.3 可用的 Agent Profile

| Profile ID | 用途 | 适合场景 |
|-----------|------|---------|
| `rp-writer` | RP 写手 | 沉浸式角色扮演 |
| `rp-critic` | RP 评审 | 质量审查 |
| `rp-director` | RP 导演 | 场景规划 |
| `rp-memory-curator` | 记忆管理 | 提取关键事件 |
| `novel-context-agent` | 写前研究 | 输出写作任务书 |
| `novel-reviewer` | 小说审查 | 5 维度事实审查 |
| `novel-data-agent` | 事实提取 | 从正文提取结构化信息 |
| `novel-deconstruction` | 拆书分析 | 参考书拆解 |
| `novel-long-writer` | 长篇写作 | 网文章节写作 |
| `novel-deslop` | 去AI味润色 | 修正 AI 写作痕迹 |

### 9.4 可用的 Skills

在 MainAgent 的 `skill_ids` 中添加（逗号分隔）：

| Skill ID | 作用 |
|----------|------|
| `rp_thinking_flow` | **推荐** — 5 步生成前思考流程 |
| `hard_gates_full` | **推荐** — 10+ 条文风级硬性门禁 |
| `rp_player_agency` | 防止 AI 替玩家做决定 |
| `rp_npc_activity` | 后台 NPC 活性管理 |
| `rp_continuity` | 确保世界书和记忆一致性 |
| `rp_persona` | 保持角色人设 |
| `narrative_theory` | 注入六大叙事理论框架 |
| `story_planning` | 剧情规划分析指导 |
| `genre_xianxia` | 仙侠题材写作指导 |
| `cool_point_loops` | 爽点循环设计 |
| `anti_trope_rules` | 反套路创作规则 |
| `anti_ai_writing` | 去 AI 味写作 |
| `prose` | 生动克制的中文叙述 |
| `world_context` | 稳定的世界观提取 |

### 9.5 注入规则

如果你有变量驱动的世界书注入需求，在 `AWPRoundPreparer` 中使用注入规则格式：

```json
[
  {
    "source_path": "世界设定.性癖",
    "split_pattern": "[，、]",
    "prefix": ""
  }
]
```

当变量 `世界设定.性癖` 发生变化时，其值会被拆分并自动匹配世界书条目。

---

## 10. 故障排查

### "LLM provider not configured"

检查 `.env` 文件中的 API Key 是否正确。如果没有 `.env`，复制 `.env.example` 创建。

### "No response generated" / 生成空白

- 检查 `enable_agent_loop` 是否开启
- 检查 `max_iterations` 是否太小（至少 3）
- 检查 Provider 和 Model 是否正确

### 角色卡导入失败

- 确保是 SillyTavern V3 格式（`"spec": "chara_card_v3"`）
- PNG 文件确保是从 SillyTavern 导出的（右键角色→导出）
- JSON 确保是完整有效的 JSON

### Agent Loop 生成太慢

- 减小 `max_iterations`（从 5 降到 3）
- 关闭不必要的 Skills
- 将 `enable_agent_loop` 设为 false 使用 Direct Pipeline 快速模式

### 中文检索不准确

安装 jieba 分词库：

```bash
pip install jieba
```

没有 jieba 时会自动退化为字符级 bigram，召回率会下降。

### ChromaDB 无法使用

ChromaDB 是可选的。未安装时会自动退化为 TF-IDF 检索，功能不受影响。

```bash
pip install chromadb  # 可选安装
```

---

## 附录

### 项目结构速查

```
awp-demo-turn-lifecycle/
├── ARCHITECTURE.md          ← 架构文档
├── docs/                    ← 全部文档
│   ├── ROADMAP.md           ← 路线图
│   ├── FUTURE_WORK.md       ← 未来功能规格
│   ├── IMPLEMENTATION_GUIDE.md ← 代码模式
│   └── CONTEXT_FOR_NEXT_SESSION.md ← AI会话上下文
├── comfyui_awp_rp/          ← Python 核心包
├── server/                  ← 独立 Web 前端
├── workflows/               ← 预置工作流 JSON
└── plugins/                 ← 节点插件定义
```

### 获取帮助

- 架构问题：读 `ARCHITECTURE.md`
- 功能怎么实现：读 `docs/FUTURE_WORK.md`
- 代码怎么写：读 `docs/IMPLEMENTATION_GUIDE.md`
- 还有什么没做：读 `docs/ROADMAP.md`
