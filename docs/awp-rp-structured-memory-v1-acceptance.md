# AWP RP Phase 2 结构化记忆 — 独立验收报告

**验收日期**：2026-06-26
**范围**：Phase 2（结构化记忆分区 + curator 路由触发 + 读写闭环）
**分支**：`phase-2-structured-memory`（派生自 `phase-awp-rp-routing-output-safety-v1-stable`）

---

## 一、基线取证

```bash
git merge-base HEAD phase-awp-rp-routing-output-safety-v1-stable
# 382e72a323b3920a15e009795c76baea40941644  ← matches stable tag

git log --oneline phase-awp-rp-routing-output-safety-v1-stable..HEAD
# (empty — no commits diverged; all changes in working tree)

git branch --show-current
# phase-2-structured-memory

git status --short
# Modified tracked: memory/__init__.py, main_agent.py, router_nodes.py,
#   round_contracts.py, round_routing.py (5 Phase 2 files)
# Untracked new: memory/structured.py, test_phase2_structured_memory.py (2 files)
# Pre-existing dirty (excluded): test_plugin.py, server/static/index.html,
#   docs/awp-rp-routing-memory-v1-acceptance.md (Phase 1 provenance appendix)
# Logs/junk (excluded): *.log, diff.txt, taohua_card.json, etc.
```

**结论**：分支正确派生自 V1 stable tag，无提交分歧。`test_plugin.py` 未携带（pre-existing dirty，非 Phase 2 改动）。

## 二、实际改动文件

| 文件 | 变更 | 说明 |
|------|------|------|
| `comfyui_awp_rp/memory/structured.py` | **新增** (430行) | 结构化记忆核心：数据类、验证、StructuredMemoryManager、幂等合并 |
| `comfyui_awp_rp/runtime/round_contracts.py` | 修改 (+10行) | RoundRoutingDecision/RoundContextPacket 加 `should_curate_memory`、`memory_curation_trigger`、`structured_memories` |
| `comfyui_awp_rp/runtime/round_routing.py` | 修改 (+39行) | Phase 2 curator 触发规则（V1 规则**之后**新增块，不修改 V1） |
| `comfyui_awp_rp/nodes/main_agent.py` | 修改 (+80行) | `_run_memory_curator` 方法 + 调用点（MVU 之后、return 之前）+ structured_memories 注入上下文 |
| `comfyui_awp_rp/nodes/router_nodes.py` | 修改 (+10行) | 透传 curator 字段到 RoundContextPacket + 结构化记忆查询注入 packet |
| `comfyui_awp_rp/memory/__init__.py` | 修改 (+22行) | 导出结构化类型 |
| `comfyui_awp_rp/test_phase2_structured_memory.py` | **新增** (490行, 27项) | 验收测试套件 |

## 三、闭合链路：写入→持久化→查询→上下文→Writer

### 写入侧（回合 T=N）

```
MainAgent.execute()  (Writer 生成回复 → MVU 提取变量 → 最终安全屏障)
  │
  ├─ if routed_packet.should_curate_memory:
  │    _run_memory_curator()
  │      ├─ 构建最小上下文（当前回合 user_input + writer_output + variable_changes）
  │      ├─ _run_sub_agent(profile_id="rp-memory-curator", ...) → JSON 输出
  │      ├─ 去除 markdown 外框，解析 JSON
  │      ├─ validate_story_fact / validate_open_thread / validate_scene_state
  │      └─ StructuredMemoryManager.ingest_curator_candidates()
  │           └─ 按 kind 路由到 write_story_fact / write_open_thread / write_scene_state
  │                └─ LongTermMemory (SQLite, namespace=session_id 隔离)
  │
  └─ metadata["memory_curation"] = {triggered, written, updated, rejected, errors}
```

### 读取侧（回合 T=N+1）

```
AWPRoundRouter  (路由决策)
  │
  ▼
AWPSubAgentOrchestrator.execute()
  │
  ├─ StructuredMemoryManager()  (默认 store, file-backed)
  │   ├─ query_story_facts(namespace, limit=30)
  │   │    └─ 与 user_input 子串匹配(2-3字窗口) + entity_id 匹配
  │   ├─ query_open_threads(namespace, status="open")
  │   └─ get_scene_state(namespace) → singleton
  │
  ├─ 注入 RoundContextPacket.structured_memories
  │    {"story_facts": [...], "open_threads": [...], "scene_state": {...}}
  │
  ▼
AWPMainAgent.execute()
  │
  ├─ 解析 routed_packet.structured_memories
  ├─ 格式化注入 context_parts:
  │    ## Story Facts
  │    - [1] 玩家答应三日后前往镇北旧宅
  │    ## Open Threads
  │    - [open] 玉佩来源之谜
  │    ## Current Scene
  │    地点:镇北旧宅 时间:黄昏 在场:语晴 氛围:沉默
  │
  └─ full_system 中包含结构化记忆 → Writer 生成回复时可见
```

### 闭合检测试（`test_write_then_read_in_subsequent_turn`）

```
T1: ingest_curator_candidates(session_id, [fact+thread], turn=1)
T2: Orchestrator.query → packet.structured_memories
    断言: story_facts 含 "三日", open_threads 含 "玉佩" ✅
T3: MainAgent(mock LLM) → 捕获 system prompt
    断言: system prompt 含 "三日" + "玉佩" (Writer 上下文可见) ✅
    断言: 输出不含 "story_fact" / "open_thread" / "curator" / "fact_key" ✅
```

### 不会与旧扁平 LongTermMemory 双重读取

- 旧扁平记忆：通过 `AWPMemoryRead` 节点读取 → `memory_context` 字段 → `## Long-term Memories` 分区
- 新结构化记忆：通过 Orchestrator 查询 → `structured_memories` 字段 → `## Story Facts` / `## Open Threads` 分区
- **两个独立分区,不同 prompt section,内容不重叠**。结构化记忆是新类型(`story_fact`/`open_thread`/`scene_state`),旧扁平记忆仍为旧类型(`event`/`relationship-change`)。

### Token 预算

- 结构化记忆无独立硬预算（当前不在 RoundPreparer 的 token 预算计算内）
- `story_facts` 最多 5 条(每条约 50 tokens) = ~250 tokens
- `open_threads` 最多 5 条(每条约 30 tokens) = ~150 tokens
- `scene_state` 1 条(约 40 tokens)
- 合计约 440 tokens,相对于 4000+ token 总预算,injection 轻量
- **限制**：无独立可控 `structured_memory_budget_tokens` 参数

## 四、Schema、幂等、迁移、隔离、Fail-open

### 4.1 幂等合并

| 分区 | 幂等键 | 合并规则 |
|------|--------|----------|
| `story_facts` | `fact_key = MD5(normalize(summary) + sorted entity_ids)` | confidence = max(old, new); importance = max(old, new); tags = union; evidence_turn = max(old, new) |
| `open_threads` | `thread_key = MD5(normalize(topic) + sorted entity_ids)` | 仅更新 status: open→resolved(设置 resolved_turn); 已 resolved 不再回退为 open |
| `scene_state` | singleton per namespace | 始终覆盖,不累积 |

测试证明：`test_write_story_fact_idempotent`（二次写→不重复）、`test_fact_confidence_takes_max`、`test_fact_not_duplicated_across_turns`、`test_ingest_duplicate_facts_updated_not_duplicated`。

### 4.2 数据隔离

- namespace = session_id（与现有 LongTermMemory 一致）
- 每个 session 独立,`PRIMARY KEY (namespace, id)` 保证不串卡
- 测试用 `_uniq(ns)` 生成唯一 namespace 避免跨测试污染

### 4.3 持久化

- `StructuredMemoryManager` 默认使用 `get_store()` → `awp.db`（file-backed SQLite）
- 写入跨进程/重启持久化——与现有 LongTermMemory 共享同一存储层
- **测试中配置了 temp-file store**（`_new_mgr()` 用 `SQLiteStore(temp_path)`），验证了 temp store 的读写
- 闭合链路测试用默认 store（file-backed），验证了真实持久化

### 4.4 迁移

- **不需要迁移**。使用现有 `MemoryRecord` 的 `type` 列区分是新结构化分区还是旧扁平 event
- 旧扁平 event（`type="event"` 等）不受影响,仍可读
- 新结构化分区用新 type 值（`story_fact`, `open_thread`, `scene_state`），不会污染旧数据
- 结构化字段缺失时 `from_dict` 返回默认值（空列表/None）

### 4.5 Fail-open

| 场景 | 行为 |
|------|------|
| curator LLM 错误 | `_detect_error` 检测 → ok=False,不写入 |
| curator JSON 解析失败 | 捕获 `JSONDecodeError` → 返回 `{triggered:True, error:...}` |
| 单条 candidate 校验失败 | 拒绝该条,继续处理其余 → 记录到 `rejected`+`errors` |
| 结构化存储查询异常 | `try/except` → `structured_memories` 为空,不阻断上下文组装 |
| 旧 session 无结构化数据 | 查询返回空 → `structured_memories` 字段均为空/None |
| schema 损坏（type 值意外） | `validate_*` 返回 ok=False → 拒绝该条 |
| namespace 不存在 | 查询返回空列表/None → fail-open |

### 4.6 禁止存储内容

结构化记忆**不**存储：完整 RP 正文、思维过程、原始工具结果、子 Agent 原始输出、curator 原始自由文本。每条仅存储 summary（≤300 字）+ 元数据键。

## 五、Curator 触发、成本与写入边界

### 5.1 触发规则

| 触发条件 | 实现 |
|----------|------|
| 关键词信号 | 22 个关键词(冲突/怨/背叛/秘密/承诺/第一次/突然…) |
| 周期性 | `turn_index > 0 && turn_index % 3 == 0`（第 3/6/9…回合） |
| 场景切换 | `hit_scene` 标志（"第二天/离开/前往…"） |
| 普通闲聊 | **不触发**（测试: `test_chitchat_does_not_trigger`） |

注意:`turn_index` 基准从 1 开始（第 1 回合为 1）。`turn_index % 3 == 0` 在第 3 回合首次触发,不是第 0/1 回合。

### 5.2 curator 触发误触发测试

| 输入 | 预期 | 结果 |
|------|------|------|
| "今天天气不错" | 不触发 | ✅ |
| "突然下雨了，我去收衣服" | 触发("突然"信号) | ⚠️ 轻度误触发(非重大剧情但 curator 运行无害,fail-open 若无实质事件则不写入) |
| "这是一场重大冲突，她隐瞒了真相" | 触发 | ✅ |
| "她答应了我的请求" | 触发("答应"信号) | ✅ |
| "第二天，她离开了" | 触发(场景切换) | ✅ |

### 5.3 成本

- curator 消耗**一次额外的 LLM 调用**（`_run_sub_agent` → DeepSeek API）
- 不占子 Agent 配额（不属于 `subagent_jobs`）
- 在 metadata 中独立记录：`memory_curation.{triggered, written, updated, rejected, errors}`
- curator 超时/异常 fail-open,不阻断 Writer
- **无独立最大调用预算**（限制：总回合数 = 隐式上限,每 3 回合 + 信号触发）

### 5.4 与 AWPMemoryWrite 的边界

- `AWPMemoryWrite`（工作流节点）：写入旧扁平 event,由工作流连线控制
- curator 写入：通过 `_run_memory_curator` → `StructuredMemoryManager` **程序化**写入,不走工作流连线
- 同一事件**可能双写**（旧扁平 + 新结构化）——当前无去重机制。这可能导致同一事实在 `## Long-term Memories` 和 `## Story Facts` 两个分区出现。

### 5.5 Schema 验证

curator JSON 输出每条经 `validate_story_fact` / `validate_open_thread` / `validate_scene_state` 校验：
- 必填字段缺失 → 拒绝
- 未知 kind → 拒绝
- entityIds 为空 → 拒绝
- summary 过长 → 截断到 300 字
- 校验失败**只拒绝该条**,不阻断整批

## 六、Relationship_state：明确延期（方案 B）

**本期未实现 `relationship_state` 的结构化持久化。**

- `RoundContextPacket.relationship_state` 字段存在,但仅从 MVU `current_variables` 透传（Phase 1 既有行为）
- 未新增关系数值系统
- 未将 MVU 变量投影为结构化关系状态
- "建议通过 MVU 路径扩展"是设计方向,不是实施成果

**当前 Phase 2 冻结范围限于 `story_facts / open_threads / scene_state`。`relationship_state` 属于 Phase 2B。**

## 七、V1 不变量回归

### 7.1 代码级验证

`round_routing.py` 的 curator 触发规则**物理隔离在 V1 子 Agent 路由块之后**（注释 `# ── Phase 2: Memory curator trigger` 标记边界）。V1 的 `rp-critic` / `rp-director` 触发逻辑未触碰。

`main_agent.py` 的 curator 调用点在 MVU 提取之后、最终安全屏障之后——不影响 V1 的 Writer 调用、sanitizer、或 QualityGate 行为。

### 7.2 测试验证

全量 V1 回归（`test_runtime_v1` 34 项 + `test_acceptance_v1` 28 项 + `test_rp_pipeline_nodes` 12 项）全部通过。

curator disabled 时（未触发或 `enable_agent_loop=False`）：
- `should_read_memory` / `should_search_worldbook` / `subagent_jobs` / 预算字段与 V1 保持一致
- 普通闲聊仍不派子 Agent
- 世界书 routed/legacy 分权不变
- `build_filtered_worldbook_text` 二次注入仍被 routed packet 禁止
- Writer 仍最多初始 1 次 + 修订 1 次 = 总 2 次
- `<thinking>` / `<analysis>` / advice 元话语的最终安全屏障仍有效

### 7.3 curator 失败不阻断 Writer

测试 `test_curator_fail_does_not_block_writer`：`should_curate_memory=True` 但 `_run_sub_agent` 调用真实 LLM 失败 → `_detect_error` 返回 ok=False → curation_log 记录 error → MainAgent 正常返回。✅

## 八、工作流连线

Phase 2 **不需要修改工作流 JSON**。curator 在 MainAgent 内部程序化执行（`_run_memory_curator` 方法）,结构化记忆查询在 Orchestrator 内部执行,均不依赖工作流连线。

`rp_full_features_routed_v1_workflow.json` 保持不变。Phase 2 节点/模块在运行时自动激活（当 `enable_agent_loop=True` + `should_curate_memory=True` 时）。

**离线 workflow smoke**：`test_routed_chain_data_flows_end_to_end`（Phase 1 验收测试）仍通过。Phase 2 新增的 `test_full_p2_pipeline_mock` 覆盖 Router→Orchestrator→MainAgent(curator) 全链路。

## 九、测试命令与结果

```bash
# Phase 2 专项测试
python -m unittest comfyui_awp_rp.test_phase2_structured_memory -v
# Ran 27 tests — OK (exit 0)

# 全量(Phase 1 + Phase 2 + 回归)
python -m unittest comfyui_awp_rp.test_runtime_v1 \
  comfyui_awp_rp.test_acceptance_v1 \
  comfyui_awp_rp.test_phase2_structured_memory \
  comfyui_awp_rp.test_rp_pipeline_nodes -v
# Ran 101 tests — OK (exit 0)
```

| 套件 | 项数 | 状态 |
|------|------|------|
| `test_runtime_v1` (Phase 1 V1) | 34 | OK |
| `test_acceptance_v1` (Phase 1 验收) | 28 | OK |
| `test_phase2_structured_memory` (Phase 2) | 27 | OK |
| `test_rp_pipeline_nodes` (既有回归) | 12 | OK |
| **合计** | **101** | **OK（0 失败）** |

## 十、已知限制

1. **结构化记忆无独立硬 token 预算**。当前注入约 440 tokens,无 `structured_memory_budget_tokens` 参数。
2. **curator 无独立最大调用预算**。每 3 回合 + 信号触发,无轮次级上限。
3. **"突然"关键词轻度误触发**。"突然下雨了"触发 curator,curator 输出无实质事件 → 无明显副作用但多一次 LLM 调用。
4. **story_facts 匹配依赖 2-3 字子串滑动窗口**——精度有限,可能遗漏相关事实或匹配噪声。
5. **`relationship_state` 明确延期**到 Phase 2B。当前仅从 MVU 透传。
6. **同一事件可能被 curator 和 AWPMemoryWrite 双写**（旧扁平 + 新结构化分区）。无跨分区去重。
7. **`scene_state` 单例 upsert 不保留历史快照**。场景切换后旧场景信息丢失。
8. **结构化事实查询 token 成本未纳入 RoundPreparer 预算报告**。

## 十一、最终建议

**PENDING_ACCEPTANCE**

理由：

- **闭合链路已补全**——结构化记忆的写入(curator)和读取(Orchestrator→MainAgent)均实现并通过端到端测试。
- **V1 不变量全部保持**——101 项测试零回归。
- **幂等/Schema/隔离/Fail-open 行为正确**——测试覆盖。
- **`relationship_state` 明确延期**——不冒充已完成能力。

**冻结条件**：
- `relationship_state` 明确标注为 Phase 2B 延期项,不纳入本期 freeze scope。
- 已知限制(预算/curator 调用上限/双写)为 Phase 2B 或 Phase 3 可选改进项。
- **不要 commit/tag/freeze**——本报告供评审方决策。

**若接受本范围(task_facts + open_threads + scene_state 写入+读取+curator 路由,不含 relationship_state),可升级为 `ACCEPT_AND_FREEZE`。**
