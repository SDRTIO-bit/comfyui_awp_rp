# AWP RP 确定性回合路由与状态记忆改造 V1 — 实施报告

**日期**：2026-06-26
**范围**：Phase 1（确定性路由 + 输出净化 + 世界书预算两层裁剪 + 消除重复路径）
**状态**：实施完成，**等待人工评审决定是否冻结**（未自行声明冻结）

---

## 1. 改动文件清单

### 新增
| 文件 | 作用 |
|------|------|
| `comfyui_awp_rp/runtime/__init__.py` | runtime 包入口 |
| `comfyui_awp_rp/runtime/round_contracts.py` | 数据合同（RoundRoutingDecision / SubAgentJob / SubAgentResult / RoundContextPacket） |
| `comfyui_awp_rp/runtime/round_routing.py` | 确定性路由 `build_round_routing_decision`（零 LLM） |
| `comfyui_awp_rp/runtime/output_sanitizer.py` | 分级输出净化 |
| `comfyui_awp_rp/runtime/subagent_orchestrator.py` | 子 Agent 编排（超时 + fail-open） |
| `comfyui_awp_rp/nodes/router_nodes.py` | AWPRoundRouter / AWPSubAgentOrchestrator 节点 |
| `comfyui_awp_rp/test_runtime_v1.py` | Phase 1 单测（34 项） |
| `workflows/rp_full_features_routed_v1_workflow.json` | routed v1 工作流 |
| `docs/awp-rp-routing-memory-v1-plan.md` | 设计计划 |
| `docs/awp-rp-routing-memory-v1-report.md` | 本报告 |

### 修改
| 文件 | 改动 |
|------|------|
| `comfyui_awp_rp/nodes/main_agent.py` | 移除"每轮必调工具"等 5 条强制提示词；新增 `round_context_packet` 输入；routed 时跳过内部 `build_filtered_worldbook_text` 二次注入；注入子 Agent advice；接入 output_sanitizer 到自反思循环；metadata 增 sanitizer/routed 字段 |
| `comfyui_awp_rp/nodes/memory_nodes.py` | AWPMemoryRead 新增 `routing_decision_json`，`should_read_memory=False` 时不做真实读取；读取异常 fail-open |
| `comfyui_awp_rp/nodes/pipeline_nodes.py` | AWPRoundPreparer 新增 `routing_decision_json`，世界书组装接入 `apply_worldbook_budget` token 预算裁剪；预算报告输出 core/retrieved token、considered/included/dropped、drop_reasons、context_owner |
| `comfyui_awp_rp/knowledge/worldbook.py` | 新增 `apply_worldbook_budget`；`build_filtered_worldbook_text` legacy fallback 加 `budget_tokens`（默认 8000）上限，常开不再无限累积 |
| `comfyui_awp_rp/nodes/__init__.py` | 注册 AWPRoundRouter / AWPSubAgentOrchestrator |

> 注：`test_plugin.py`、`server/static/index.html` 在会话开始前已是 modified 状态（见初始 git status），非本次改动。

## 2. 新旧调用链对比

### 旧链路（`rp_full_features_api_workflow.json`）
```
TextInput ─┬─> RoundPreparer ─(世界书匹配, 常开全量)─┐
           ├─> MemoryRead ─(无条件预读)──────────────┤
           └─> CardSelect ─(card_id)─────────────────┤
                                                    ▼
                          MainAgent (agent_loop=True)
                          ├─ worldbook_context ← RoundPreparer
                          ├─ memory_context    ← MemoryRead
                          └─ 内部又调 build_filtered_worldbook_text 二次过滤  ← 64k 爆炸根因
                          └─ 系统提示词强制"每轮必调 memory_read/worldbook_search" ← 模型不配合,空转
                                   │
                                   ▼
                          MVU → QualityGate → MemoryWrite → OutputRenderer
```

### 新链路（`rp_full_features_routed_v1_workflow.json`）
```
TextInput ─┬──────────────────────────────┐
           ├─> AWPRoundRouter ─(路由决策JSON)─┬─> RoundPreparer (routing_decision_json)
           │                                 ├─> MemoryRead (routing_decision_json, 受控)
           │                                 └─> AWPSubAgentOrchestrator (routing_decision_json)
           ├─> CardSelect ──────────────────────────────────────────────┐
           │                                                              ▼
           └────────────────────────────────────────────> MainAgent
                          ├─ worldbook_context  ← RoundPreparer (已预算裁剪)
                          ├─ memory_context     ← MemoryRead (受路由控制)
                          ├─ round_context_packet ← Orchestrator (含 advice)
                          └─ routed 时不再二次过滤世界书; 不再强制每轮调工具
                                   │
                                   ▼
                          MVU → QualityGate(+sanitizer) → MemoryWrite → OutputRenderer
```

## 3. Canonical Context 所有权

| 节点 | 拥有 |
|------|------|
| **AWPRoundRouter** | 路由决策：是否读记忆、世界书 query、子 Agent 派发、预算参数、trace |
| **AWPRoundPreparer** | canonical 世界书上下文（已预算裁剪）+ 组装上下文 |
| **AWPMemoryRead** | 本轮记忆文本（仅路由允许时读取） |
| **AWPSubAgentOrchestrator** | RoundContextPacket（含 subagent_advice，context_owner="routed"） |
| **AWPMainAgent** | 消费 packet 生成正文；不再拥有世界书二次过滤权；不再拥有"是否调工具"决定权 |

`context_owner` 字段在 RoundPreparer 预算报告与 RoundContextPacket 中均记录（`"routed"` / `"legacy"`），可审计。

## 4. 世界书两层路径如何避免重复

**根因**：旧路径中 RoundPreparer 匹配一份世界书注入 `worldbook_context`，MainAgent 内部又用 `card_id` 调 `build_filtered_worldbook_text` 二次过滤并拼接；而该函数对 `constant` 条目只排序不按 token 裁剪，常开条目累积到 64k+。

**V1 修复（两层都改）**：
1. **MainAgent 层**（`main_agent.py`）：当 `round_context_packet` 的 `context_owner=="routed"` 时，**跳过**内部 `build_filtered_worldbook_text`，直接信任 RoundPreparer 提供的 `worldbook_context`。legacy 路径（无 packet）保留 fallback，但调用时传入 `budget_tokens=8000`。
2. **RoundPreparer 层**（`pipeline_nodes.py`）：常开条目原本不受 `top_worldbook` 限制（另一条 64k 路径）。现接入 `apply_worldbook_budget`，按 routing decision 的 `worldbook_budget_tokens`（默认 4000）裁剪，常开优先但计入预算。
3. **`build_filtered_worldbook_text`**（`worldbook.py`）：legacy fallback 新增 `budget_tokens` 参数（默认 8000），经 `apply_worldbook_budget` 裁剪。

**可观测**（RoundPreparer 预算报告）：`core_worldbook_token_estimate / retrieved_worldbook_token_estimate / worldbook_entries_considered / worldbook_entries_included / worldbook_entries_dropped / worldbook_budget_tokens / worldbook_drop_reasons / context_owner`。

**测试证明**：
- `test_core_capped_by_budget`：50 条常开条目在 500 token 预算下被限制在预算内，dropped>0。
- `test_build_filtered_text_legacy_budget`：60 条常开条目经 legacy fallback 后文本 < 6000 字符（非 64k）。
- `test_routed_path_skips_internal_worldbook_filter`：routed packet 存在时，`build_filtered_worldbook_text` 不被调用（patch 为 fail-on-call，断言调用次数=0）。

## 5. 记忆读取如何避免双重读取

**根因**：workflow 层 MemoryRead 无条件预读 + agent loop 系统提示词强制"每轮必须调用 memory_read 工具"。模型不调工具 → 只靠预读，且强制提示词空转。

**V1 修复**：
1. **AWPMemoryRead** 新增 `routing_decision_json` 输入。当 `should_read_memory=False` 时返回空（`"(memory read skipped by router)"` / `"[]"`），不做真实读取、不报错。
2. **MainAgent** 移除"每轮必须调用 memory_read"强制提示词。工具调用不再是每轮义务，仅作运行时事实缺口 fallback。
3. 是否读记忆由 **AWPRoundRouter** 统一决定（回忆信号词 / 新实体提及 / 场景切换 / 关系信号 / 周期刷新）。

**测试**：`test_memory_read_gated_by_router_skip`（should_read_memory=False → 不读）、`test_memory_read_gated_legacy_when_no_decision`（无 routing → legacy 行为，fail-open 空）。

## 6. 子 Agent 真实触发场景

Phase 1 接入 `rp-director` 与 `rp-critic`（`rp-memory-curator` 留 Phase 2）。

| 触发条件 | 派发 |
|----------|------|
| 强烈情感信号（怨/恨/原谅/信任/怀疑/背叛/秘密/隐瞒/坦白/揭露/旧账/兑现/真相/身份） | `rp-critic`（review） |
| 多角色（≥3 个已知角色被提及）/ 场景切换 / 高复杂度（冲突/对峙/决裂/选择/重大/决定/摊牌/危机/转折/关键/必须） | `rp-director`（direction） |
| 普通闲聊 | 0 个 |
| 一般复杂 | ≤1 个 |
| 高复杂 | ≤2 个（硬上限 `MAX_JOBS_PER_TURN=2`） |

子 Agent 编排：超时（默认 30s）+ 异常 fail-open，advice 经 compaction（≤1200 字符）进入 MainAgent 内部上下文，**不进用户正文**。

**测试**：`test_multi_character_conflict_triggers_subagent`、`test_high_complexity_max_two_subagents`、`test_orchestrator_node_runs_mocked_job`（mock `_run_sub_agent` 验证真实执行链路）、`test_timeout_fail_open`、`test_exception_fail_open`、`test_max_jobs_capped`、`test_advice_not_leaking_to_packet_raw`。

## 7. 确定性运行时逻辑 vs prompt fallback

| 行为 | 类型 |
|------|------|
| 是否读记忆 | ✅ 确定性运行时（路由规则） |
| 世界书是否检索 + query | ✅ 确定性运行时（路由规则） |
| 世界书 token 预算裁剪 | ✅ 确定性运行时（`apply_worldbook_budget`） |
| 是否派发子 Agent + 派哪个 | ✅ 确定性运行时（路由规则） |
| 子 Agent 超时/异常 fail-open | ✅ 确定性运行时（编排器） |
| 输出净化（显式标签拒绝/元话语清理） | ✅ 确定性运行时（`sanitize_output`） |
| 质量门禁（格式/player-agency/泄露） | ✅ 确定性运行时（`apply_quality_gate`，既有） |
| 子 Agent 内部推理内容 | ⚠️ LLM 生成（受 profile system prompt 约束） |
| MainAgent 不输出元话语/内部推理 | ⚠️ prompt fallback（系统提示词约束 + 净化器兜底） |
| MainAgent 工具调用作为缺口补充 | ⚠️ prompt fallback（非强制，模型自主） |

## 8. 测试命令与结果

```bash
# Phase 1 V1 单测（全 mock，离线）
python -m unittest comfyui_awp_rp.test_runtime_v1
# Ran 34 tests in 5.0s — OK

# 既有回归
python -m unittest comfyui_awp_rp.test_rp_pipeline_nodes
# Ran 12 tests — OK

python -m unittest comfyui_awp_rp.test_p6_p7_regressions
# Ran 16 tests — FAILED (errors=1)
#   失败项：FileNotFoundError: workflows/rp_agent_full.json
#   原因：pre-existing，该工作流从未纳入 git，与本次改动无关
```

**覆盖的验收场景**（全部通过）：
1. 普通闲聊：不读记忆、不检索世界书、不派子 Agent ✅
2. 旧承诺/旧事件：触发记忆读取 ✅
3. 未在短期上下文出现的实体：触发世界书检索 ✅
4. 多角色冲突：触发 rp-director/rp-critic ✅
5. 子 Agent 超时/失败：Writer 继续（fail-open）✅
6. routed 路径不发生 MainAgent 二次世界书注入 ✅
7. legacy fallback 有世界书硬预算 ✅
8. `<thinking>`/`<analysis>` 被拒绝并触发有限重试 ✅
9. 开场元话语被安全清理 ✅
10. routing trace 可序列化，且不泄露到最终文本 ✅

**mock 说明**：所有子 Agent 执行通过 `run_fn` 注入或 patch `_run_sub_agent` 模拟，未发起真实 LLM/API 调用。MainAgent routed 路径测试 patch 了 `create_default_router`，不消耗 DeepSeek API。

## 9. 已知限制

1. **路由规则为关键词驱动**：纯规则无法完美区分专名与闲聊词，已通过"短候选(2-6字) + 基线比照(已知实体或 core 关键词)"缓解，但极端边界仍可能误判。`reasons`/`trace` 可审计。
2. **结构化记忆未做**：Phase 1 不引入 `story_facts/open_threads/scene_state` 分区，`RoundContextPacket` 的这些字段已预留但本期不持久化。当前 `relationship_state`/`scene_state` 从 MVU `current_variables` 透传（可能为空）。
3. **output_sanitizer 的 B 级前缀清理**仅作用于首行，依赖元话语出现在开头；若元话语混在中间则不处理（保守，避免误伤叙事）。
4. **真实长对话回归未做**：20–40 回合真实 DeepSeek API 回归留 Phase 3，需显式开关，不默认消耗成本。
5. **`test_p6_p7_regressions`** 1 项 pre-existing 失败（依赖缺失工作流），非本次引入。
6. **子 Agent profile system prompt** 本期未改动；rp-critic/rp-director 的输出格式约束依赖既有 profile。

## 10. 留给 Phase 2 / Phase 3 的事项

- **Phase 2**：结构化记忆（`story_facts / open_threads / scene_state` 分区 + 幂等合并 + schema 校验 + `rp-memory-curator` 按路由触发写入），`relationship_state` 复用 MVU 变量系统而非另造。
- **Phase 3**：20–40 回合真实 API 长对话回归，产出指标报告（子 Agent 调用次数 / 记忆读取次数 / 世界书检索次数 / 平均 core context / 质量门禁重试次数 / 元信息泄露次数 / fallback 次数），需显式开关。

## 11. 是否可冻结

**不自行声明冻结。** 本报告提交后，由评审方基于代码变更、测试结果与本报告决定是否接受并冻结。

- 确定性运行时行为（路由/预算/净化/编排 fail-open）均已由单测覆盖并通过。
- prompt fallback 部分（不输出元话语、工具作缺口补充）已接入净化器与质量门禁兜底，但最终效果需 Phase 3 真实 LLM 验证。
- 未接入默认工作流的组件：无。`rp_full_features_routed_v1_workflow.json` 已包含全部新节点连线；旧工作流保持不变可继续运行。
