# AWP RP — 完整路线图

> 最后更新: 2026-06-25 | 当前版本: P0-P4 已完成

## 已完成 (P0-P4)

### P0 — Agent 思考流程 + 硬性门禁
| 功能 | 文件 | 说明 |
|------|------|------|
| rp_thinking_flow Skill | `tools/skill_manager.py` | 5步生成前思考流程（翻记忆→看盘面→判场景→人事物→输出检查） |
| narrative_theory Skill | `tools/skill_manager.py` | 六大学术叙事框架（麦基/布克/坎贝尔/救猫咪/皮尔逊/ATU） |
| hard_gates_full Skill | `tools/skill_manager.py` | 10+ 条文风级硬性门禁（全知修饰词/八股微表情/临床语言/极端情感词/句式禁止） |
| Agent loop 自动注入 | `nodes/main_agent.py` | 开启 agent loop 时自动注入 thinking_flow + hard_gates |
| Quality gate 扩展 | `rp_pipeline.py` | 4维→7维（+全知修饰词/八股微表情/临床语言/极端情感词/AI写作癖好/网文套话） |

### P1 — MVU 变量运行时
| 功能 | 文件 | 说明 |
|------|------|------|
| MVU 引擎 | `mvu/engine.py` (~1200行) | 命令解析（3种格式）+ 执行（5种操作）+ Schema验证 + 宏解析 + 审计 |
| 世界书匹配器 | `mvu/matcher.py` | 变量变更→世界书条目匹配（打分+top-k） |
| 变量清单 | `mvu/checker.py` | 为AI生成步骤提供变量路径清单 |
| AWPMVUNode | `nodes/mvu_node.py` | ComfyUI节点：解析→执行→审计→匹配 |
| AWPMVUMacroResolver | `nodes/mvu_node.py` | {{getvar::}} / {{formatvar::}} 模板宏替换 |
| Agent MVU集成 | `nodes/main_agent.py` | Agent loop 产出 updated_variables + changes_json |

### P2 — Agent 能力增强
| 功能 | 文件 | 说明 |
|------|------|------|
| NPC 活性工具 | `tools/builtin/npc_tools.py` | npc_activity_scan + npc_update_state |
| rp_npc_activity Skill | `tools/skill_manager.py` | 后台NPC三级决策（静默/提及/进场） |
| Agent 自省回路 | `nodes/main_agent.py` | quality gate → 修订反馈 → 最多2次重试 |
| 写作 Skill 扩充 | `tools/skill_manager.py` | genre_xianxia / cool_point_loops / anti_trope_rules |

### P3 — 管线工程化
| 功能 | 文件 | 说明 |
|------|------|------|
| AWPRoundPreparer | `nodes/pipeline_nodes.py` | 回合预处理：变量驱动+输入驱动世界书匹配 + 清单 + 预算 |
| AWPSessionReroll | `nodes/session_node.py` | 重roll（删除最后一轮）/ 回退（删除指定轮次起） |
| Embedding 检索 | `retrieval/embedding.py` | TF-IDF语义检索 + HybridRetriever（BM25+Embedding加权） |
| retriever_node 扩展 | `nodes/retriever_node.py` | 新增 embedding / hybrid_semantic 策略 |

### P4 — 文档
| 功能 | 文件 | 说明 |
|------|------|------|
| 架构文档 | `ARCHITECTURE.md` | 完整架构说明，420行 |
| 路线图 | `docs/ROADMAP.md` | 本文件 |
| 未来工作 | `docs/FUTURE_WORK.md` | 未实现功能详细规格 |
| 参考仓库 | `docs/REFERENCE_REPOS.md` | 三库借鉴摘要 |
| 实现指引 | `docs/IMPLEMENTATION_GUIDE.md` | 代码级实现指南 |
| 会话上下文 | `docs/CONTEXT_FOR_NEXT_SESSION.md` | 给下一个AI会话的完整上下文 |

---

## 待实现 (P5+)

### P5 — 叙事深度功能（中工作量）

| 优先级 | 功能 | 来源 | 涉及文件 |
|--------|------|------|---------|
| P5.1 | **剧情规划**（每8轮 STORY.md 分析） | oh-story-claudecode | `tools/builtin/story_plan_tool.py` + Skill |
| P5.2 | **注入规则**（变量→世界书条目自动注入） | oh-story-claudecode | `tools/builtin/injection_tool.py` + AWPRoundPreparer 集成 |
| P5.3 | **Action Options**（每轮3个行动选项） | oh-story-claudecode | `nodes/main_agent.py` system prompt + output parser |
| P5.4 | **Token 预算管理**（Agent loop 内截断） | oh-story-claudecode | `nodes/main_agent.py` agent loop 改造 |
| P5.5 | **子Agent 结果验证**（delegate后审查） | webnovel-writer | `tools/builtin/delegate_tool.py` |

### P6 — 工程增强（中-大工作量）

| 优先级 | 功能 | 来源 | 涉及文件 |
|--------|------|------|---------|
| P6.1 | **流式输出**（SSE token-by-token） | 酒馆 | `core/llm_router.py` + `nodes/main_agent.py` |
| P6.2 | **并行工具调用**（Agent loop 内并行执行） | Agent节点 | `tools/tool_executor.py` + `nodes/main_agent.py` |
| P6.3 | **Author's Note 注入点** | 酒馆 | `nodes/pipeline_nodes.py` AWPRoundPreparer |
| P6.4 | **卡结构检测**（阶段人设+事件库） | oh-story-claudecode | `card/` + `tools/builtin/card_structure_tool.py` |

### P7 — 基础设施（大工作量）

| 优先级 | 功能 | 来源 | 涉及文件 |
|--------|------|------|---------|
| P7.1 | **ChromaDB 向量存储**（真·语义检索） | 酒馆 | `retrieval/` + 新 `retrieval/vector_store.py` |
| P7.2 | **story-system contracts**（MASTER/volume/chapter 合同树） | webnovel-writer | `core/store.py` + 新 `core/story_contracts.py` |
| P7.3 | **工作流模板库** | 原创 | `workflows/` 预置模板 |
| P7.4 | **独立 Web 前端**（HTTP server + HTML） | oh-story-claudecode | 新 `server/` 目录 |

---

## 技术债务

| 项目 | 严重程度 | 说明 |
|------|---------|------|
| Token 估计粗糙 | 中 | `estimate_tokens()` 用 `len(text)//4`，未使用真实 tokenizer |
| 中文分词依赖 jieba | 低 | jieba 不可用时退化为 2-gram，召回率下降 |
| Agent loop 无并行工具执行 | 中 | 多个 tool_call 串行执行 |
| 无流式输出 | 中 | 用户需等待完整回复 |
| Skill 内容硬编码 | 低 | Skills 在 `_load_builtin_skills()` 中硬编码，应迁移到 JSON 文件 |

---

## 统计

| 指标 | 当前值 |
|------|--------|
| 节点总数 | 39 |
| Skill 总数 | 15 |
| Tool 总数 | 11 |
| 源文件数 | 58 (.py) |
| 总代码行数 | ~8000 |
| Git commits | 4 (P0-P4) |
