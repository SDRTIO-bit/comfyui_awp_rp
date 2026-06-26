# AWP RP 确定性回合路由与状态记忆改造 V1 — 实施计划

**创建日期**：2026-06-26
**范围**：Phase 1（确定性路由 + 输出净化 + 世界书预算两层裁剪 + 消除重复路径）
**状态**：实施中

---

## 1. 背景

`docs/pending-issues.md` 记录了 4 个已验证问题：子 Agent 不被调用、工具调用不积极、长期记忆利用率低、偶发元话语泄露。审计代码后确认根因不在"提示词不够强"，而在架构层存在重复路径与缺失的确定性调度层。

## 2. 当前实际调用链（审计结论）

主测试工作流 `workflows/rp_full_features_api_workflow.json` 真实链路：

```
AWPTextInput ─┬─> AWPRoundPreparer ──(匹配世界书 out1)──┐
              ├─> AWPMemoryRead ────(记忆文本 out1)─────┤
              └─> AWPCardSelect ───(card_id)────────────┤
                                                         ▼
                          AWPMainAgent (enable_agent_loop=True)
                          ├─ worldbook_context  ← RoundPreparer
                          ├─ memory_context     ← MemoryRead
                          ├─ card_id            ← CardSelect
                          └─ 内部又调 build_filtered_worldbook_text 二次过滤
                                   │
                                   ▼
                AWPMVUNode → AWPQualityGate → AWPMemoryWrite → AWPOutputRenderer
```

### 四个关键实情（提示词提出者未必知道）

1. **世界书双重处理**：`AWPRoundPreparer` 已在 workflow 层匹配一份注入 `worldbook_context`；但 `main_agent.py:229-256` 在 `card_id` 存在时**又调用 `build_filtered_worldbook_text` 二次过滤并拼接**。`build_filtered_worldbook_text` 对 `constant` 条目只排序、不按 token 裁剪，`max_entries=40` 优先保留常开 → **64k 爆炸根因在 MainAgent 内部这层**。
2. **记忆双重读取**：workflow 层 `AWPMemoryRead`(Node 11) 已预读一份喂 `memory_context`；agent loop 系统提示词又强制"每轮必须调用 memory_read 工具"。模型实际不调 → 记忆只靠预读那份，且强制提示词空转。
3. **MainAgent 已堆满强制提示词**：`main_agent.py:382-417` 已有 5 条"强制规则"+ 行动选项块。继续堆提示词无效，需**移除**。
4. **质量门禁缺口**：`apply_quality_gate` 已检测 `<analysis>`/`思考过程`/`[Status:`/player-agency/knowledge-leak，但**不检测开场元话语**（"好，现在""让我""进入角色"）。输出净化恰好补此缺口。

### 既有可复用资产

- profile 齐全：`rp-writer / rp-critic / rp-director / rp-memory-curator / rp-state-updater / novel-*`（代码内置，`data/profiles` 空）。
- MVU 变量系统：`current_variables` + `mvu.engine.extract_commands/execute_commands`。Phase 2 的 `relationship_state` 应复用 MVU，本期不引入第二套。
- `LongTermMemory`：扁平 event 记录，namespace=session_id 隔离；`query(namespace, tags_any, type_filter, limit)`。
- `complete_with_tools(node_config, messages, tools, tool_choice)`：单次同步调用，无显式超时包裹（Phase 1 编排器需自加超时）。
- 节点注册集中在 `comfyui_awp_rp/nodes/__init__.py` 的 `NODE_CLASS_MAPPINGS` / `NODE_DISPLAY_NAME_MAPPINGS`。

## 3. 兼容策略

- 保留 `rp_full_features_api_workflow.json` 不覆盖；新增 `rp_full_features_routed_v1_workflow.json`。
- 所有新节点输入/输出带默认值；routed packet 缺失时安全回退 legacy 行为。
- `build_filtered_worldbook_text` 不删除：routed 路径下 MainAgent 跳过其二次注入；legacy fallback 保留但加预算上限。
- 不引入第二套 `relationship_state`；Phase 2 复用 MVU。
- 旧工作流必须仍可加载、可运行。

## 4. 上下文所有权（消除重复路径的核心）

| 节点 | 职责 |
|------|------|
| `AWPRoundRouter`（新） | 决定是否读记忆、检索哪些世界书 query、是否派发子 Agent、预算参数、routing trace |
| `AWPRoundPreparer` | 执行 Router 决策，组装本轮 canonical context packet |
| `AWPMemoryRead` | 仅在 routing decision 允许时读取；不允许时返回空不报错 |
| `AWPSubAgentOrchestrator`（新） | 始终可执行；无任务零成本跳过；有任务执行并 fail-open |
| `AWPMainAgent` | 消费 canonical context packet 生成正文；不再二次拼接全量世界书；不再强制每轮调工具 |

## 5. 新增 / 修改文件

### 新增
```
comfyui_awp_rp/runtime/__init__.py
comfyui_awp_rp/runtime/round_contracts.py      # dataclass 数据合同
comfyui_awp_rp/runtime/round_routing.py        # 确定性路由 build_round_routing_decision
comfyui_awp_rp/runtime/output_sanitizer.py     # 分级输出净化
comfyui_awp_rp/runtime/subagent_orchestrator.py# 子 Agent 编排（超时+fail-open）
comfyui_awp_rp/nodes/router_nodes.py           # AWPRoundRouter / AWPSubAgentOrchestrator 节点
comfyui_awp_rp/test_runtime_v1.py              # Phase 1 单测
workflows/rp_full_features_routed_v1_workflow.json
docs/awp-rp-routing-memory-v1-report.md
```

### 修改
```
comfyui_awp_rp/nodes/main_agent.py        # 移除强制提示词；消费 packet；跳过二次世界书注入
comfyui_awp_rp/nodes/memory_nodes.py      # AWPMemoryRead 受 routing_decision 控制
comfyui_awp_rp/knowledge/worldbook.py     # build_filtered_worldbook_text 加 token 预算 legacy fallback
comfyui_awp_rp/nodes/pipeline_nodes.py    # AWPRoundPreparer 加 token 预算 + 消费 routing decision
comfyui_awp_rp/nodes/__init__.py          # 注册新节点
```

## 6. 数据合同（round_contracts.py）

dataclass，JSON 可序列化，`schema_version` 字段，全字段默认值：

- `RoundRoutingDecision`: should_read_memory, memory_queries, should_search_worldbook, worldbook_queries, subagent_jobs, should_run_continuity_check, should_scan_npc_activity, reasons, confidence, worldbook_budget_tokens, trace
- `SubAgentJob`: profile, task_type, task, priority, max_result_tokens
- `SubAgentResult`: profile, task_type, ok, advice, error, elapsed_ms
- `RoundContextPacket`: schema_version, current_scene_state, relationship_state, open_threads, recent_summary, retrieved_memories, retrieved_worldbook_entries, subagent_advice, routing_trace, context_owner

## 7. 确定性路由规则（round_routing.py）

纯规则，零 LLM 成本，可单测。输入：user_input、current_variables、recent_summary、open_threads、recent_messages、turn_index、last_memory_read_turn、card/worldbook 基础信息。

### 记忆读取触发（任一）
1. 回忆信号词："之前/上次/曾经/答应/还记得/当时/那天/约定/承诺"
2. 提及未在短期上下文出现的实体（与 open_threads / relationship_state 比对）
3. 场景切换 / 时间跳转信号
4. 关系反转 / 秘密 / 旧账 / 承诺兑现信号
5. 距上次记忆检索 ≥ N 轮（默认 5）
fail-open：检索异常不阻断主回复。

### 世界书检索触发
当 user_input 含未在 core/常开条目覆盖的关键实体/地点/物品 → 产出 worldbook_queries；否则仅 core。

### 子 Agent 路由（Phase 1 仅 rp-director / rp-critic）
- `rp-director`：多角色场景 / 场景切换 / 重大剧情推进 / 开放式选择
- `rp-critic`：强烈情感冲突 / OOC 风险 / 旧事件秘密承诺身份揭露
- 普通闲聊：0；一般复杂：≤1；高复杂：≤2；单轮最多 2 任务
- `rp-memory-curator` 留 Phase 2

## 8. 输出净化（output_sanitizer.py）

- A 级（显式标签 `<thinking>/<analysis>/<tool>/<tool_call>`）：判定失败，触发一次有限重试
- B 级（开头元话语"好，现在/让我/我先/进入角色/根据设定/作为/开始生成"）：保守前缀清理，只移除开头明显元话语段，不跨段 regex
- 清理后为空/太短（< 阈值）/格式损坏：判定失败
- 重试上限默认 1
- 自然叙事"我想了想""让他进入房间"不得误杀（B 级只匹配开头 + 明显元话语动词组合）

## 9. 子 Agent 编排（subagent_orchestrator.py）

- 消费 `subagent_jobs`，构造最小必要上下文（scene_state + 相关记忆 + 用户输入摘要，不含全量历史/正文）
- 复用 `delegate_tool._run_sub_agent`，外层包 `concurrent.futures` 超时（默认 30s）+ try/except
- 失败 fail-open：记录 error，advice 为空，Writer 继续
- 最大并发：普通 1，高复杂 2；单轮最多 2 任务
- advice 仅进入 MainAgent 内部上下文，不进用户正文

## 10. 世界书预算两层裁剪

新增稳定估算 `estimate_tokens`（已在 rp_pipeline，`len//4`）。预算策略：
- 保留：当前登场角色、当前场景、世界底层规则、已锁定剧情事实
- 其余条目走条件检索
- constant 不再无限累积；超预算时按优先级裁剪

可观测字段（trace）：`core_worldbook_token_estimate / retrieved_worldbook_token_estimate / worldbook_entries_considered / worldbook_entries_included / worldbook_entries_dropped / drop_reason / context_owner`

两层：
1. `AWPRoundPreparer` 组装加预算 + 常开裁剪
2. `build_filtered_worldbook_text` legacy fallback 加预算上限；routed packet 存在时 MainAgent 跳过其二次注入

## 11. 测试计划（全部 mock 可离线运行）

`comfyui_awp_rp/test_runtime_v1.py`，unittest 风格，沿用 `sys.path` 注入。

路由器：闲聊不读记忆/不派子Agent；旧承诺触发记忆；未出现实体触发世界书；多角色冲突触发 director/critic；高复杂最多2；子Agent不可用主流程继续；core超预算可预测裁剪；trace可序列化。
净化：`<thinking>`/`<analysis>` 拒绝重试；开场元话语安全清理；正常正文不误伤；清理后空判失败；重试超限返回诊断错误。
编排：profile映射；最小上下文；超时fail-open；异常fail-open；并发与任务数生效；advice不泄露。
世界书：大量constant条目core被限预算；触发条目可召回；routed路径不二次注入；legacy fallback不膨胀。
集成：routed工作流节点注册；MemoryRead受routing控制。

## 12. 风险与回滚点

| 风险 | 缓解 |
|------|------|
| 改 main_agent.py 影响旧工作流 | routed packet 缺失走 legacy；保留 enable_agent_loop 旧路径 |
| 世界书裁剪误删关键设定 | 保留 core 优先级；trace 记录 dropped+reason 可审计 |
| 子 Agent 超时拖慢回合 | 默认 30s 超时 + fail-open；普通回合 0 子 Agent |
| 路由规则误判 | 纯规则可单测；reasons 字段可解释；fail-open 不阻断 |
| 测试依赖 API key | 全部 mock；真实 LLM 长对话留 Phase 3 显式开关 |

**回滚点**：所有改动以新节点 + routed 工作流隔离；旧工作流与旧 MainAgent legacy 路径不变。出问题时切回旧工作流即可。

## 13. Phase 2 / Phase 3 留项

- Phase 2：结构化记忆（story_facts/open_threads/scene_state 分区 + 幂等合并 + schema 校验 + rp-memory-curator 写入），复用 MVU 承载 relationship_state。
- Phase 3：20–40 回合真实 DeepSeek API 长对话回归，显式开关，不默认消耗成本。
