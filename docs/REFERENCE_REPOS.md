# 参考仓库 — 借鉴摘要

> 本文档记录从三个参考仓库中提取的关键借鉴点、代码位置和设计决策。

---

## oh-story-claudecode（AIRP_ClaudeCode-master）

**路径**: `F:\game\AIRP_ClaudeCode-master\AIRP_ClaudeCode-master`

**定位**: Claude Code 直驱 RP 引擎。Claude Code 本身就是 RP 引擎，不做 prompt 工程，AI 自己驱动一切。

### 核心设计哲学
- **三大管线**: 导入管线 → 回合管线 → 清理管线
- **AI 做创作决策，Python 做机械操作**: 所有文件读取/变量更新/世界书匹配都是脚本化的
- **力大砖飞**: 靠模型原始能力硬推叙事，不依赖复杂 prompt 模板

### 已借鉴的部分（P0-P3）

| AWP 实现 | 来源文件 | 源位置 |
|----------|---------|--------|
| rp_thinking_flow Skill | CLAUDE.md「生成前思考流程」 | 第 477-493 行 |
| hard_gates_full Skill | CLAUDE.md「硬性门禁」 | 第 499-515 行 |
| narrative_theory Skill | STORY.md 全文 | - |
| mvu/engine.py | skills/mvu_engine.py 全文 | ~500行 |
| mvu/matcher.py | skills/match_worldbook.py | ~100行 |
| mvu/checker.py | skills/mvu_check.py | ~60行 |
| npc_tools.py | CLAUDE.md「后台 NPC 活性检查」 | 第 469-475 行 |
| AWPRoundPreparer | skills/round_prepare.py 模式 | - |
| SessionReroll | skills/handler.py reroll_last() | ~40行 |

### 尚未借鉴的部分

| 功能 | 源文件 | 源位置 |
|------|--------|--------|
| 剧情规划 | CLAUDE.md「剧情规划」 | 第 320-360 行 |
| 注入规则 | handler.py apply_injections() + mvu_server.js /inject | ~80行 |
| 行动选项 | CLAUDE.md「行动选项」 | 第 517-528 行 |
| 卡结构检测 | import_prepare.py + CLAUDE.md | - |
| Web 前端 | server.py + index.html | ~500行 |
| Token 统计 | token_stats.py | ~100行 |
| MVU Zod 验证 | mvu_server.js + mvu_shared.js | ~500行 JS |

### 关键文件清单

```
skills/
├── handler.py          # 回复处理 + chat_log + content.js 重建（~500行）
├── server.py           # HTTP 桥接服务器 + 前端（~400行）
├── mvu_engine.py       # MVU 核心引擎（~500行，已完全移植到 mvu/engine.py）
├── mvu_server.js       # Node.js Zod 验证服务器（~300行，未移植）
├── mvu_shared.js       # Zod扩展 + 工具函数（~200行，未移植）
├── mvu_check.py        # 变量清单生成（~60行，已移植到 mvu/checker.py）
├── match_worldbook.py  # 变量驱动世界书匹配（~100行，已移植到 mvu/matcher.py）
├── round_prepare.py    # 回合预处理管线
├── round_deliver.py    # 回合后处理管线
├── import_prepare.py   # 导入预处理管线
├── import_card.py      # 角色卡导入
├── write_memory.py     # 记忆写入
├── token_stats.py      # Token 统计
└── start_server.py     # 启动服务器
```

### 未被移植的关键差异

oh-story-claudecode 的 `mvu_server.js` 是 **Node.js 常驻进程**，用 `vm.createContext()` 在真实 JS 运行时中执行角色卡的 Zod schema 脚本。AWP 作为 ComfyUI 纯 Python 插件，无法运行 Node.js。当前的折中方案是 `mvu/engine.py` 中使用纯 Python 的 `SchemaNode` + `validate_command()` 做类型检查，精度低于 Zod 但满足基本验证需求。

**如果未来需要 Zod 级别的验证**：可以将 `mvu_shared.js` 的 `generateSchemaMeta()` + `generateInitvar()` 逻辑移植到 Python，用 Python 的 `jsonschema` 库替代 Zod。

---

## webnovel-writer

**仓库**: `https://github.com/lingfengQAQ/webnovel-writer`
**本地克隆**: `F:\zhao\webnovel-writer\webnovel-writer`

**定位**: Claude Code 长篇网文创作插件。4 个 sub-agent + 7 个 skill + Python 工具脚本。

### 核心架构
- **4 个 Agent**: context-agent（写前研究）、reviewer（审查）、data-agent（事实提取）、deconstruction-agent（拆书）
- **7 个 Skill**: init / plan / write / review / query / learn / dashboard
- **写章流水线**: context → draft → review → polish → commit

### 已借鉴的部分（P0-P3）

| AWP 实现 | 来源 | 说明 |
|----------|------|------|
| novel-context-agent Profile | agents/context-agent.md | 五段写作任务书 |
| novel-reviewer Profile | agents/reviewer.md | 5维度审查 |
| novel-data-agent Profile | agents/data-agent.md | 结构化事实提取 |
| novel-deconstruction Profile | agents/deconstruction-agent.md | 参考书拆解 |
| genre_xianxia Skill | skills/webnovel-write/references/writing/ | 仙侠写作指导 |
| cool_point_loops Skill | references/shared/cool-points-guide.md | 爽点循环设计 |
| anti_trope_rules Skill | skills/webnovel-init/references/creativity/ | 反套路创作规则 |

### 尚未借鉴的写作资源

`skills/webnovel-write/references/` 目录下有大量未使用的写作参考资料：

```
references/
├── anti-ai-guide.md          # 8种AI癖好（部分已吸收到 hard_gates_full）
├── polish-guide.md           # 润色指南
├── style-adapter.md          # 风格适配器
├── style-variants.md         # 风格变体
├── writing/
│   ├── combat-scenes.md      # 战斗场景写作
│   ├── desire-description.md # 欲望描写
│   ├── dialogue-writing.md   # 对话写作
│   ├── emotion-psychology.md # 情感心理
│   ├── genre-hook-payoff-library.md  # 题材钩子回报库
│   ├── scene-description.md  # 场景描写
│   └── typesetting.md        # 排版格式
shared/
├── core-constraints.md       # 核心约束
├── naming-and-voice-gaps.md  # 命名与角色声音
└── strand-weave-pattern.md   # 多线编织模式
```

这些都可以打包为 AWP Skills。

### 尚未借鉴的系统功能

| 功能 | 源文件 | 说明 |
|------|--------|------|
| story-system contracts | `scripts/webnovel.py` story-system 命令 | 三层合同树 |
| memory-contract 查询 | `scripts/webnovel.py` memory-contract 命令 | 结构化记忆查询 |
| reference_search.py | `scripts/reference_search.py` | CSV 检索写作参考 |
| webnovel-dashboard | `skills/webnovel-dashboard/` + `dashboard/` | 可视化面板 |
| genre-profiles | `references/genre-profiles.md` | 题材档案 |

---

## SillyTavern（酒馆）

**定位**: 最成熟的 RP 前端。AWP 不与酒馆竞争，而是作为 ComfyUI 生态中的可视化 RP 工作流系统。

### 酒馆有而 AWP 没有的

| 功能 | 说明 | 对 AWP 的意义 |
|------|------|--------------|
| Group Chat | 多角色群聊 | 低优先级（ComfyUI 节点不适合做聊天界面） |
| Character Expressions | 角色立绘/表情系统 | 低优先级 |
| TTS Integration | 语音合成 | 已有 Spark-TTS 节点可联动 |
| Author's Note | 深度注入点 | **中优先级** — 可在 AWPRoundPreparer 增加 |
| Vector Storage | ChromaDB 语义检索 | **中优先级** — P7.1 |
| STscript | 宏脚本语言 | 已被 MVU 部分替代 |
| Regex Scripts | 正则文本转换 | 低优先级 |
| Mobile Frontend | 移动端适配 | 低优先级 |

### 酒馆的角色卡格式

AWP 已支持 SillyTavern V3 PNG 角色卡导入（`card/import_card.py`），包括：
- 角色描述、性格、场景
- 开场白（含多选）
- 嵌入的世界书条目
- 变量定义（tavern_helper Zod schema）

---

## 快速查阅指南

| 如果要实现... | 先读... |
|--------------|--------|
| 剧情规划 | oh-story-claudecode `CLAUDE.md` 剧情规划章节 |
| 注入规则 | oh-story-claudecode `handler.py` apply_injections() |
| 行动选项 | oh-story-claudecode `CLAUDE.md` 行动选项章节 |
| Token 管理 | oh-story-claudecode `short_term.py` get_context_for_prompt() |
| 卡结构检测 | oh-story-claudecode `import_prepare.py` Phase 1 |
| 战斗场景 Skill | webnovel-writer `combat-scenes.md` |
| 对话写作 Skill | webnovel-writer `dialogue-writing.md` |
| 合同系统 | webnovel-writer `scripts/webnovel.py` story-system 命令 |
| ChromaDB 集成 | 网上的 ChromaDB Python 教程 |
| Zod 级别验证 | oh-story-claudecode `mvu_shared.js` + Python jsonschema |
