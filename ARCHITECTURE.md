# AWP RP — 架构文档

> **写给后来者**：这份文档记录了 2026-06-25 完成的一次大规模功能升级（P0-P3），以及项目的完整架构。如果你是新加入的开发者，从这里开始。

## 📋 目录

- [项目概述](#项目概述)
- [目录结构](#目录结构)
- [核心架构](#核心架构)
- [节点清单（39个）](#节点清单)
- [Skill 清单（15个）](#skill-清单)
- [Tool 清单](#tool-清单)
- [MVU 变量系统](#mvu-变量系统)
- [数据流](#数据流)
- [P0-P3 升级记录](#p0-p3-升级记录)
- [参考仓库](#参考仓库)
- [下一步 (P4+)](#下一步)

---

## 项目概述

AWP RP 是一个 **ComfyUI 自定义节点包**，为 RP（角色扮演）和长篇小说创作提供可视化工作流节点。运行在 ComfyUI 的 `custom_nodes/` 目录下。

**核心设计哲学**：
- **双路径**：Direct Pipeline（静态 DAG 节点链）和 Agent Path（Agent Loop + 工具调用）
- **ComfyUI 原生**：所有功能都是 ComfyUI 节点，通过连线传递数据
- **纯 Python**：零外部依赖（除 LLM API 调用所需的 `requests`/`openai`）

## 目录结构

```
awp-demo-turn-lifecycle/
├── __init__.py                    # ComfyUI 入口
├── comfyui_awp_rp/               # 核心包
│   ├── core/                     # LLM路由 + SQLite存储 + 类型定义
│   │   ├── config.py             # 多Provider配置
│   │   ├── llm_router.py         # OpenAI兼容LLM路由
│   │   ├── store.py              # SQLite持久化
│   │   └── types.py              # 全量类型定义（~467行）
│   ├── nodes/                    # ComfyUI节点（39个）
│   │   ├── main_agent.py         # ★ 主Agent节点（Agent Loop核心）
│   │   ├── sub_agent.py          # 子Agent
│   │   ├── pipeline_nodes.py     # 管线节点（7个）+ 回合预处理
│   │   ├── mvu_node.py           # MVU变量更新节点
│   │   ├── memory_nodes.py       # 记忆读写
│   │   ├── retriever_node.py     # 检索器
│   │   ├── session_node.py       # 会话管理 + 重roll
│   │   ├── card_nodes.py         # 角色卡导入
│   │   ├── worldbook_node.py     # 世界书
│   │   ├── preset_node.py        # 预设
│   │   ├── project_nodes.py      # 项目/大纲
│   │   ├── input_nodes.py        # 输入/输出节点
│   │   ├── ui_nodes.py           # UI编辑节点
│   │   └── __init__.py           # 节点注册
│   ├── mvu/                      # ★ MVU变量引擎（P1新建）
│   │   ├── engine.py             # 命令解析+执行+验证（~1200行）
│   │   ├── matcher.py            # 变量驱动世界书匹配
│   │   └── checker.py            # 变量清单生成
│   ├── memory/                   # 记忆系统
│   │   ├── short_term.py         # 短期会话记忆 + reroll
│   │   └── long_term.py          # 长期记忆
│   ├── retrieval/                # 检索系统
│   │   ├── bm25.py               # BM25关键词检索
│   │   ├── embedding.py          # ★ TF-IDF语义检索（P3新建）
│   │   ├── scorer.py             # 检索评分器
│   │   └── tokenizer.py          # 分词器
│   ├── tools/                    # Agent工具系统
│   │   ├── registry.py           # 工具注册表
│   │   ├── tool_executor.py      # 工具执行器
│   │   ├── skill_manager.py      # Skill管理器（15个技能）
│   │   └── builtin/              # 内置工具（7类15个工具）
│   │       ├── memory_tools.py
│   │       ├── worldbook_tools.py
│   │       ├── retrieval_tools.py
│   │       ├── card_tools.py
│   │       ├── continuity_tools.py
│   │       ├── delegate_tool.py
│   │       └── npc_tools.py      # ★ NPC活性工具（P2新建）
│   ├── knowledge/
│   │   └── worldbook.py          # 世界书CRUD
│   ├── card/                     # 角色卡
│   │   ├── import_card.py        # ST V3 PNG导入
│   │   ├── greeting.py           # 开场白
│   │   └── variable.py           # 变量状态
│   ├── profile/
│   │   └── profile.py            # Agent档案（11种）
│   ├── preset/
│   │   └── preset.py             # RP预设
│   └── rp_pipeline.py            # RP管线逻辑（含质量门禁）
├── plugins/                      # 插件定义
├── workflows/                    # 示例工作流JSON
├── data/                         # 运行时数据（配置、技能、档案）
└── docs/                         # 文档
```

## 核心架构

```
┌─────────────────────────────────────────────────────────────┐
│                    ComfyUI 画布                              │
│                                                             │
│  Direct Pipeline 路径:                                      │
│  ┌──────────┐   ┌──────────────┐   ┌───────────────┐       │
│  │InputParser│──▶│ContextAssembler│──▶│DialogueDirector│    │
│  └──────────┘   └──────────────┘   └───────┬───────┘       │
│                                             │               │
│                          ┌──────────────────▼──────────┐   │
│                          │ QualityGate → OutputRenderer │   │
│                          └─────────────────────────────┘   │
│                                                             │
│  Agent Path 路径:                                           │
│  ┌────────────┐   ┌──────────┐   ┌───────────────┐        │
│  │RoundPreparer│──▶│MainAgent │──▶│   MVU Node    │        │
│  └────────────┘   │(AgentLoop│   │(变量更新+匹配) │        │
│                   │ +Tools)  │   └───────────────┘        │
│                   └──────────┘                             │
│                                                             │
│  支持节点:                                                  │
│  - SessionReroll (重roll/回退)                              │
│  - MemoryRead/Write (记忆管理)                              │
│  - Worldbook (世界书)                                       │
│  - Retriever (BM25 + Embedding + Hybrid 检索)              │
│  - CardImport (角色卡导入)                                   │
└─────────────────────────────────────────────────────────────┘
```

**MainAgent 的 Agent Loop 内部流程**：

```
while iterations < max_iterations:
    LLM(tools) → response
    if has_tool_calls:
        execute tools → append results → loop
    else:
        final_text = response.text
        break

if enable_self_reflection:          # P2 新增
    apply_quality_gate(final_text) → if errors:
        feed back for revision (max 2 retries)

extract MVU commands from final_text  # P1 新增
execute variable updates
audit changes
return (reply, context, metadata, updated_variables, changes)
```

## 节点清单（39个）

### Agent 节点
| 节点 | 中文名 | 说明 |
|------|--------|------|
| AWPMainAgent | 主Agent | Agent Loop核心，工具调用+子Agent派发+自省+MVU |
| AWPSubAgent | 子Agent | 专用任务执行（审查/提取/拆书） |

### 管线节点
| 节点 | 中文名 | 说明 |
|------|--------|------|
| AWPInputParser | 输入解析 | 用户输入→结构化JSON（mention/dialogue/action/intent） |
| AWPContextAssembler | 上下文组装 | 角色+场景+世界书+记忆→上下文 |
| AWPDialogueDirector | 对话导演 | LLM生成RP回复 |
| AWPQualityGate | 质量门 | 7维度文本检查 |
| AWPPatchProposal | 候选补丁 | 状态/记忆变更提案 |
| AWPSideEffectDecision | 副作用决策 | 提交策略决策 |
| AWPOutputRenderer | 最终输出 | 最终回复组装 |
| **AWPRoundPreparer** ⭐ | 回合预处理 | 自动化上下文组装（变量驱动世界书匹配+输入匹配+清单+预算） |

### MVU 节点 ⭐
| 节点 | 中文名 | 说明 |
|------|--------|------|
| **AWPMVUNode** | MVU变量更新 | 解析AI输出→执行变量命令→审计→世界书匹配 |
| **AWPMVUMacroResolver** | MVU宏解析 | {{getvar::}} / {{formatvar::}} 模板宏替换 |

### 会话节点
| 节点 | 中文名 | 说明 |
|------|--------|------|
| AWPSessionLoad | 加载会话 | 读取会话历史 |
| AWPSessionSave | 保存会话 | 保存/清除会话 |
| **AWPSessionReroll** ⭐ | 重roll/回退 | 删除最后一轮或指定轮次起 |

### 记忆节点
| 节点 | 中文名 | 说明 |
|------|--------|------|
| AWPMemoryRead | 记忆读取 | 按标签/类型召回 |
| AWPMemoryWrite | 记忆写入 | 持久化事件/关系 |

### 检索节点
| 节点 | 中文名 | 说明 |
|------|--------|------|
| AWPRetriever | 检索器 | 支持 keyword / bm25 / hybrid / embedding / hybrid_semantic |

### 世界书节点
| 节点 | 中文名 | 说明 |
|------|--------|------|
| AWPWorldbook | 世界书 | 读写世界书条目 |
| AWPWorldbookList | 世界书列表 | 列出条目 |

### 角色卡节点
| 节点 | 中文名 | 说明 |
|------|--------|------|
| AWPCardImport | 导入角色卡 | ST V3 PNG/JSON导入 |
| AWPCardSelect | 选择角色卡 | 从已导入卡中选择 |
| AWPGreeting | 开场白 | 管理和切换开场白 |
| AWPCardEditor | 角色卡编辑 | UI编辑 |

### 预设节点
| 节点 | 中文名 | 说明 |
|------|--------|------|
| AWPPreset | 预设 | RP预设管理 |
| AWPPresetEditor | 预设编辑 | UI编辑 |

### 项目/大纲节点
| 节点 | 中文名 | 说明 |
|------|--------|------|
| AWPProjectSave | 保存项目快照 | |
| AWPProjectLoad | 加载项目快照 | |
| AWPProjectList | 项目列表 | |
| AWPOutlineEditor | 大纲编辑 | |
| AWPOutlineQuery | 大纲查询 | |

### IO 节点
| 节点 | 中文名 | 说明 |
|------|--------|------|
| AWPTextInput | 文本输入 | |
| AWPJsonInput | JSON输入 | |
| AWPTextOutput | 文本输出 | |
| AWPJsonOutput | JSON输出 | |

### UI 管理节点
| 节点 | 中文名 | 说明 |
|------|--------|------|
| AWPMemoryList | 记忆列表 | |
| AWPMemoryEdit | 记忆编辑 | |
| AWPSkillManagerNode | 技能管理 | |
| AWPToolList | 工具列表 | |

> ⭐ = P0-P3 新增

## Skill 清单（15个）

| ID | 中文名 | 来源 | 说明 |
|----|--------|------|------|
| rp_persona | RP 角色扮演 | 原有 | 角色人设/语气/边界 |
| rp_player_agency | 玩家行动权保护 | 原有 | 不替玩家决定 |
| rp_continuity | RP 连续性 | 原有 | 世界书+记忆为正史 |
| rp_slow_burn | RP 慢热叙事 | 原有 | 每轮只揭示一个细节 |
| prose | 散文写作 | 原有 | 生动克制的中文叙述 |
| world_context | 世界观上下文 | 原有 | 提取稳定的世界观设定 |
| consistency | 一致性检查 | 原有 | 检查矛盾/遗漏 |
| anti_ai_writing | 去 AI 味写作 | 原有 | 避免排比/比喻/转折公式化 |
| **rp_thinking_flow** ⭐ | RP 生成前思考流程 | oh-story-claudecode | 五步强制思考流程 |
| **narrative_theory** ⭐ | 叙事理论框架 | oh-story-claudecode STORY.md | 六大学术框架 |
| **hard_gates_full** ⭐ | 硬性门禁（完整版） | oh-story-claudecode | 10+ 条文风级门禁 |
| **rp_npc_activity** ⭐ | 后台NPC活性管理 | oh-story-claudecode | 每轮扫描后台NPC |
| **genre_xianxia** ⭐ | 仙侠题材写作指导 | webnovel-writer | 战力/爽点/节奏 |
| **cool_point_loops** ⭐ | 爽点循环设计 | webnovel-writer | 四层结构+铺放比 |
| **anti_trope_rules** ⭐ | 反套路创作规则 | webnovel-writer | 陌生化四大手法 |

## Tool 清单

| 工具名 | 类别 | 说明 |
|--------|------|------|
| memory_read | memory | 读取长期记忆 |
| memory_write | memory | 写入长期记忆 |
| worldbook_read | worldbook | 读取世界书条目 |
| worldbook_write | worldbook | 写入世界书条目 |
| retrieval_search | retrieval | BM25/关键词检索 |
| card_query | card | 查询角色卡信息 |
| card_greeting | card | 获取/切换开场白 |
| continuity_check | quality | 确定性质量检查 |
| delegate_to_sub_agent | delegation | 派发子Agent |
| **npc_activity_scan** ⭐ | npc | 扫描后台NPC活性 |
| **npc_update_state** ⭐ | npc | 更新NPC状态 |

## MVU 变量系统

MVU（MagVarUpdate）是 P1 移植的核心系统，来自 oh-story-claudecode。

### 架构

```
AI 输出 <UpdateVariable><JSONPatch>[...]</JSONPatch></UpdateVariable>
         │
         ▼
   extract_commands()  ← 正则提取（支持3种格式）
         │
         ▼
   validate_command()  ← Schema 类型检查
         │
         ▼
   execute_commands()  ← 五种操作（replace/delta/insert/remove/move）
         │
         ▼
   audit_variables()   ← Deep diff + 分区摘要
         │
         ├──→ match_worldbook_by_variables()  ← 变量→世界书条目
         └──→ generate_variable_checklist()   ← 下轮变量清单
```

### 五种操作

| 操作 | Python 语法 | JSONPatch |
|------|------------|-----------|
| replace | `_.set('a.b', value)` | `{"op":"replace","path":"/a/b","value":...}` |
| delta | `_.add('a.b', delta)` | `{"op":"delta","path":"/a/b","value":...}` |
| insert | `_.insert('a.b', key, val)` | `{"op":"add","path":"/a/b/-","value":...}` |
| remove | `_.delete('a.b')` | `{"op":"remove","path":"/a/b"}` |
| move | `_.move('a', 'b')` | `{"op":"move","from":"/a","path":"/b"}` |

### 模板宏

```
{{getvar::璃夏.好感度}}     → 42
{{formatvar::互动对象}}     → YAML/JSON缩进块
```

## 数据流

### 完整 RP 回合流程

```
用户输入
  │
  ▼
AWPRoundPreparer ←── var_diff (上轮变更) + worldbook_index + memories
  │
  ├─ 变量驱动世界书匹配
  ├─ 输入关键词世界书匹配
  ├─ 变量清单生成
  └─ Token预算检查
  │
  ▼ 上下文
AWPMainAgent (Agent Loop)
  │
  ├─ System prompt: Profile + Preset + Skills + Context
  ├─ Agent Loop: LLM(tools) → tool calls → execute → loop
  ├─ Self-reflection: QualityGate → retry (max 2)
  └─ MVU: extract_commands → execute → audit
  │
  ├──→ 回复（叙事文本）
  ├──→ 会话上下文
  ├──→ 元数据（token使用/工具调用/反思记录）
  ├──→ 更新后变量 → 下一轮的 current_variables
  └──→ 变更记录 → 下一轮的 var_diff
```

## P0-P3 升级记录

### 提交历史

```
d9547ce P3 — Round preparer, reroll/rollback, semantic retrieval
c241091 P2 — Background NPC activity, agent self-reflection, genre writing skills
a385c5e P0+P1 — Agent thinking flow, hard gates, MVU variable engine
```

### P0 — Agent 思考流程 + 硬性门禁扩充
- `skill_manager.py`: 新增 3 个 Skills（rp_thinking_flow, narrative_theory, hard_gates_full）
- `main_agent.py`: Agent loop 自动注入思考流程 Skills
- `rp_pipeline.py`: Quality gate 从 4 维扩展到 7 维

### P1 — MVU 变量运行系统
- `mvu/engine.py` (1183行): 完整 MVU 引擎
- `mvu/matcher.py`: 变量驱动世界书匹配
- `mvu/checker.py`: 变量清单生成
- `nodes/mvu_node.py`: AWPMVUNode + AWPMVUMacroResolver
- `main_agent.py`: Agent loop 产出 updated_variables + changes_json

### P2 — 后台NPC活性 + Agent自省 + 写作扩充
- `tools/builtin/npc_tools.py`: npc_activity_scan + npc_update_state
- `skill_manager.py`: 新增 4 个 Skills（npc_activity, genre_xianxia, cool_point_loops, anti_trope_rules）
- `main_agent.py`: Agent 自省回路（quality gate → retry）
- Skills 总数: 11→15

### P3 — 回合预处理 + 重roll/回退 + 语义检索
- `nodes/pipeline_nodes.py`: AWPRoundPreparer (219行)
- `retrieval/embedding.py`: TF-IDF 语义检索 + HybridRetriever (265行)
- `memory/short_term.py`: reroll_last() + delete_turns_from()
- `nodes/session_node.py`: AWPSessionReroll
- 节点总数: 37→39

## 参考仓库

本项目的设计和功能大量借鉴了以下三个仓库：

### oh-story-claudecode（AIRP_ClaudeCode-master）
- **设计哲学**: "Claude Code 本身就是 RP 引擎"，AI 做创作决策，Python 做机械操作
- **借鉴**: Thinking flow（5步）、硬性门禁、MVU 引擎、NPC 活性、回合预处理模式
- **STORY.md**: 叙事理论六大框架（麦基/布克/坎贝尔/救猫咪/皮尔逊/ATU）

### webnovel-writer（github.com/lingfengQAQ/webnovel-writer）
- **架构**: 4 个 sub-agent + 7 个 skill + Python 工具脚本
- **借鉴**: Agent Profiles（context/reviewer/data/deconstruction）、anti-ai-guide、genre-profiles、cool-point-loops
- **5步写章流水线**: context → draft → review → polish → commit

### SillyTavern（酒馆）
- **对照参考**: 角色卡 V3 格式、World Info、STscript 变量系统
- **AWP 未实现**: Group chat、Character expressions、TTS、Author's Note、Vector storage

## 下一步

### 可能的 P4+ 方向

1. **独立 Web 前端**: oh-story-claudecode 的 Python HTTP + static HTML 方案，作为 ComfyUI 之外的可选辅助面板
2. **ChromaDB 向量存储**: 真正的语义记忆检索（当前 TF-IDF 是轻量方案）
3. **流式输出**: Agent loop 支持 SSE/token-by-token 流式输出
4. **Author's Note 注入点**: 在 ContextAssembler 中增加用户自定义注入层
5. **多角色群聊**: 同时操控多个 NPC 的对话场景
6. **TTS 集成**: 已有 Spark-TTS 节点可联动
7. **工作流模板库**: 预置更多开箱即用的 RP/写作工作流

### 维护注意事项

- `mvu/engine.py` 是项目最大的单文件（~1200行），修改时务必运行自测：`python mvu/engine.py`
- Skill 内容存储在 `skill_manager.py` 的 `_load_builtin_skills()` 中，也在 `plugins/rp-skills/skill.plugin.json` 有映射
- 新增 ComfyUI 节点后需同时在 `nodes/__init__.py` 的 `NODE_CLASS_MAPPINGS` 和 `NODE_DISPLAY_NAME_MAPPINGS` 中注册
- Agent Loop 的最大迭代次数默认 5，谨慎提高（Token 消耗激增）
- Quality Gate 中新增的检查默认是 "warning" 级别，不会阻塞工作流；如需升级为 "error"，在 `rp_pipeline.py` 中修改 severity
- 中文分词依赖 jieba（可选），未安装时自动退化为 2-gram，召回率会下降但不会报错
