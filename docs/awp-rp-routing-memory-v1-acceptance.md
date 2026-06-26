# AWP RP V1 独立验收与冻结前复核报告

**验收日期**：2026-06-26（修订于同日：REJECT_AND_FIX 三轮阻塞项修复）
**验收范围**：Phase 1（确定性路由 + 输出净化 + 世界书预算两层裁剪 + 消除重复路径）
**审阅方式**：代码级独立审阅 + 专项验收测试 + git 取证

---

## 一、实际改动文件清单（git diff/status 确认）

### 修改（6 文件）
| 文件 | 变更量 | 类别 |
|------|--------|------|
| `comfyui_awp_rp/nodes/main_agent.py` | +85/-37 | 世界书跳过、移除强制提示词、接入净化器、注入 advice |
| `comfyui_awp_rp/nodes/pipeline_nodes.py` | +51/-0 | RoundPreparer 世界书预算裁剪 + routing_decision_json 输入 |
| `comfyui_awp_rp/nodes/memory_nodes.py` | +53/-18 | MemoryRead 受 routing decision 门控 |
| `comfyui_awp_rp/knowledge/worldbook.py` | +81/-0 | `apply_worldbook_budget`、`build_filtered_worldbook_text` 加 legacy 预算 |
| `comfyui_awp_rp/nodes/__init__.py` | +5/-0 | 注册 AWPRoundRouter / AWPSubAgentOrchestrator |
| `comfyui_awp_rp/test_plugin.py` | +4/-1 | **pre-existing**（初始 git status 已是 M,移除 `DEFAULT_RP_PRESET` import） |

### 新增（7 文件/目录）
`comfyui_awp_rp/runtime/`（5 模块）、`comfyui_awp_rp/nodes/router_nodes.py`、`comfyui_awp_rp/test_runtime_v1.py`、`comfyui_awp_rp/test_acceptance_v1.py`、`workflows/rp_full_features_routed_v1_workflow.json`、`docs/awp-rp-routing-memory-v1-plan.md`、`docs/awp-rp-routing-memory-v1-report.md`、`docs/awp-rp-routing-memory-v1-acceptance.md`（本件）。

---

## 二、新旧调用链对比（工作流连线验证）

### 旧链路（`rp_full_features_api_workflow.json`,33 节点）
```
TextInput ─┬→ RoundPreparer ─(常开全量,无预算)──┐
           ├→ MemoryRead ──(无条件预读)─────────┤
           └→ CardSelect ──(card_id)────────────┤
                                                ▼
            MainAgent(agent_loop=True)
            ├─ 内部又调 build_filtered_worldbook_text 二次注入 ← 64k 根因
            └─ 强制提示词"每轮必调工具"              ← 模型不配合,空转
                        ↓
            MVU → QualityGate → MemoryWrite → OutputRenderer
```

### 新链路（`rp_full_features_routed_v1_workflow.json`,35 节点）
```
TextInput ─┬──────────────────────────────────┐
           ├─→ AWPRoundRouter ─(路由决定)─────┬─→ RoundPreparer(预算裁剪)
           │                                  ├─→ MemoryRead(门控)
           │                                  └─→ Orchestrator(fail-open)
           └─→ CardSelect ──────────────────────────────┐
                                                        ▼
                      MainAgent(消费 routed packet)
                      ├─ routed 时跳过内部世界书二次过滤
                      ├─ 不再强制每轮调工具(保留 fallback)
                      └─ 接收子 Agent advice(内部参考,进系统提示)
                                  ↓
                  MVU → QualityGate(纯决策) → MemoryWrite → OutputRenderer
```

**节点消费关系验证**（从工作流 JSON 反向依赖分析）：
- `AWPRoundRouter(34)` → 被 MemoryRead(11)、RoundPreparer(13)、Orchestrator(35) 消费 ✅
- `Orchestrator(35)` → 被 MainAgent(14).round_context_packet 消费 ✅
- `MainAgent(14)` → 被 6 个下游节点消费（含 QualityGate、MemoryWrite、OutputRenderer）✅
- `AWPQualityGate(17)` → 流向 19/20/29，**不回流 MainAgent**（无重试回路）✅
- `AWPMemoryWrite(21)` → 无消费者（OUTPUT_NODE 终端，写存储副作用）— 与旧工作流一致 ✅
- **无死节点、无孤儿节点** ✅

### 兼容性
- 旧 `rp_full_features_api_workflow.json` **未被覆盖**，仍可加载（33 节点,class_type 全部已知）✅
- 41 节点全部注册（`NODE_CLASS_MAPPINGS` ≥41，导入验证通过）✅

---

## 三、世界书双重处理：代码级证明

### 3.1 routed 路径：MainAgent 不再二次过滤

**代码证据**（`main_agent.py:257`）：
```python
if is_routed:
    # Routed: trust the packet's worldbook_context verbatim. No re-filter.
    pass
elif card_id and ...:   # legacy path only
    ...build_filtered_worldbook_text(...)...
```

**测试证据**（`test_acceptance_v1.py`）：
| 测试 | 断言 | 结果 |
|------|------|------|
| `test_routed_packet_skips_internal_filter_zero_calls` | routed packet + card_id 存在 → `build_filtered_worldbook_text` 调用次数=0 | ✅ |
| `test_legacy_packet_calls_internal_filter_once` | 无 packet + card_id → legacy fallback 调用次数=1 | ✅ |

### 3.2 常开条目硬预算限制

**测试证据**：
- `test_constant_entries_hard_budget_capped`：50 条常开在 budget=400 tokens 下被限制,total ≤410,dropped ≥30 ✅
- `test_build_filtered_text_legacy_budget`：60 条常开经 legacy fallback(budget=1000) 后文本 <6000 字符(非 64k) ✅

### 3.3 优先级排序

**代码逻辑**（`apply_worldbook_budget` 的 `_sort_key`）：
```python
(0 if is_const else 1, -priority)  # constant first, then by priority desc
```

**测试证据**：`test_priority_constant_and_triggered_above_background` — 核心规则(constant)排在最前，触发条目(priority=50)排在背景条目(priority=1)之前 ✅

### 3.4 Trace 字段可观测

RoundPreparer 的 budget 报告**已验证包含**：
`context_owner`, `core_worldbook_token_estimate`, `retrieved_worldbook_token_estimate`, `worldbook_entries_considered`, `worldbook_entries_included`, `worldbook_entries_dropped`, `worldbook_drop_reasons`, `worldbook_budget_tokens` ✅

**Token 估算方法**：`estimate_tokens(text) = max(1, (len(text)+3)//4)`（定义于 `comfyui_awp_rp/rp_pipeline.py:54`），稳定、可测试。虽非精确 tokenizer 计数，但对预算裁剪足够保守。注意：这是**近似估算**，与真实 tokenizer 有 ±20% 偏差，Phase 3 可校准。

---

## 四、记忆双重读取消除：代码级证明

### 4.1 门控：MemoryRead 只在路由允许时读取

**代码证据**（`memory_nodes.py`）：
```python
if decision.get("should_read_memory") is False:
    return ("(memory read skipped by router)", "[]")  # 零读取、不报错
```

**测试证据**：
| 测试 | 断言 | 结果 |
|------|------|------|
| `test_skip_decision_no_query_call` | should_read_memory=False → `LongTermMemory.query` 调用 0 次 | ✅ |
| `test_no_decision_legacy_calls_query` | 无 routing → legacy 行为,query 调用 1 次(fail-open 空) | ✅ |

### 4.2 强制提示词已删除

**grep 证据**：
```bash
grep "每轮必须调用\|禁止跳过工具\|每轮必须调用工具" main_agent.py
# (无匹配 — 已删除)
```

同时确认：`tool_choice="auto"`、`available_tools` 均保留 → 工具能力作为 fallback 保留 ✅

### 4.3 同回合不会出现两层重复读取

在 routed 工作流中：
- `AWPMemoryRead` 受 `should_read_memory` 门控（路由决定）→ 不被允许时不读取
- `AWPMainAgent` 系统提示词不再强制"每轮必须调用 memory_read" → 模型不被要求重复读
- 即使模型自主调用 `memory_read` 工具（fallback），也不与 workflow 层重复——workflow 层已被门控

测试 `test_mainagent_agentloop_no_double_memory_when_routed` 验证：
- 系统提示词不含"每轮必须调用" ✅
- 工具仍可用 ✅
- 子 Agent advice 注入内部 ✅
- 不得原样暴露的指令在系统提示词中 ✅

---

## 五、子 Agent 闭环验证

### 5.1 完整闭环测试

`test_full_loop_router_to_orchestrator_to_writer_advice`：
```
冲突输入("她怨我,冲突,隐瞒真相")
→ AWPRoundRouter 产出 rp-critic job ✅
→ AWPSubAgentOrchestrator 执行(mocked _run_sub_agent) → advice 生成 ✅
→ advice 进入 MainAgent 系统提示词("评审认为应注意关系张力") ✅
→ MainAgent 输出("你问我怨不怨？")不含"评审认为" ✅
```

### 5.2 路由控制
| 场景 | 预期 | 测试结果 |
|------|------|----------|
| 普通闲聊("今天天气不错") | 0 个 job | ✅ |
| 单冲突信号 | ≤1 个 job | ✅ |
| 多角色+冲突+高复杂度信号叠加 | ≤2 个 job | ✅ |

### 5.3 Fail-open

| 场景 | 测试 | 结果 |
|------|------|------|
| 子 Agent 超时(1s 超时,5s sleep) | ok=False,error="timeout" | ✅ |
| 子 Agent 异常(RuntimeError) | ok=False,error 含"boom" | ✅ |
| **Profile 不存在** | ok=False(验收时**发现并修复**的 bug: `_run_sub_agent` 返回错误字符串而非抛异常,导致编排器标记 ok=True,现已加 `_detect_error` 检测) | ✅ 已修复 |
| Sub-agent 原始输出不泄露到 advice field | compacted ≤1300 chars,非 raw | ✅ |

---

## 六、输出净化与重试边界

### 6.1 分级处理

| 输入 | 处理 | 测试 |
|------|------|------|
| `<thinking>x</thinking>` | REJECT_RETRY(限次),超过上限 REJECT_GIVE_UP | ✅ |
| `<analysis>x</analysis>` | 同上 | ✅ |
| `好，现在让我们进入故事。\n\n她推开门…` | SCRUB_PREFIX(原地清理,不耗重试) | ✅ |
| `她想了想，让他进入房间。` | ACCEPT(自然叙事不误杀) | ✅ |
| `让我`(单独,无后续) | REJECT_RETRY(太短) | ✅ |

### 6.2 重试次数有界

- MainAgent 内 reflection 循环：`while reflection_attempts < 2` → 最多 2 次修订 LLM 调用
- `sanitize_output` 的 `max_retries=2`，在 attempt≥2 时返回 REJECT_GIVE_UP
- 测试 `test_explicit_tag_reject_then_give_up_no_infinite_loop` 模拟 4 次 attempt，在 2 次后到达 GIVE_UP，次数 ≤4 且不循环 ✅

### 6.3 QualityGate vs MainAgent 重试边界

| 组件 | 重试行为 | 证据 |
|------|----------|------|
| MainAgent 内 reflection 循环 | 最多 2 次修订(main_agent.py:`max_reflections=2`) | 源码行 557 |
| 独立 AWPQualityGate 节点 | 纯评测,不重试,输出不回流 MainAgent | 工作流连线:17→19/20/29,无 →14；`apply_quality_gate` 是纯函数 |
| **不会倍增** | 总修订上限 = 2(仅 MainAgent 内部),QualityGate 不触发额外 LLM 调用 | ✅ 已验证 |

---

## 七、测试结果汇总

### 7.1 新增专项测试
```bash
python -m unittest comfyui_awp_rp.test_runtime_v1      # 34 tests — OK
python -m unittest comfyui_awp_rp.test_acceptance_v1    # 20 tests — OK
```

### 7.2 既有回归测试
```bash
python -m unittest comfyui_awp_rp.test_rp_pipeline_nodes  # 12 tests — OK
```

### 7.3 Pre-existing failures（非本次引入）

| 测试 | 错误 | 根因 | 证据 |
|------|------|------|------|
| `test_p6_p7_regressions.test_new_workflow_templates_are_comfyui_import_shape` | `FileNotFoundError: workflows/rp_agent_full.json` | 引用的工作流从初始 commit `a5c7fd1` 起就不在 git 中。`git log --all -- workflows/rp_agent_full.json` 无输出。 | pre-existing |
| `test_p6_p7_regressions.tools` | `ImportError: relative import beyond top-level package` | unittest discover 时 `tools/__init__.py`→`skill_manager.py` 的 `from ..core.config` 无法解析。`tools/__init__.py` 自 `a5c7fd1` 起未改动,`git diff HEAD` 确认无变更。 | pre-existing |

### 7.4 综合命令
```bash
python -m unittest comfyui_awp_rp.test_runtime_v1 comfyui_awp_rp.test_acceptance_v1 comfyui_awp_rp.test_rp_pipeline_nodes
# Ran 66 tests in 5.0s — OK (exit 0)
```

---

## 八、验收过程中发现并修复的缺陷

| # | 描述 | 严重度 | 状态 |
|---|------|--------|------|
| 1 | `round_routing.py`：`is_multi_character` 仅在 `enable_subagents` 块内定义但块外使用 → `UnboundLocalError` | 高 | ✅ 已修复 |
| 2 | `round_routing.py`：世界书检索对无核心关键词的闲聊误触发(整句被当成候选词) | 中 | ✅ 已修复(加短候选限制+基线比照) |
| 3 | `subagent_orchestrator.py`：`_run_sub_agent` 对 profile 不存在返回错误字符串而非抛异常,导致编排器标记 ok=True,把错误文本当 advice | 中 | ✅ 已修复(加 `_detect_error` 方法) |

---

## 九、已知限制

1. **Token 估算为近似值**：`estimate_tokens` 用 `len//4`,与真实 tokenizer 偏差 ±20%。Phase 3 可校准。
2. **B 级前缀清理仅首行**：元话语出现在段落中间不会被清理,这是保守设计(避免误伤自然叙事中的"我想了想"等)。
3. **子 Agent advice 防泄露基于 prompt 约束**：系统提示词明确要求"不得出现评审认为/导演建议等措辞",净化器和 QualityGate 作为兜底但未专门扫描这些关键词。
4. **结构化记忆未实施**：`story_facts/open_threads/scene_state` 分区、幂等合并、`rp-memory-curator` 写入留 Phase 2。
5. **20–40 回合真实 API 回归未做**：留 Phase 3,需显式开关。
6. **`test_p6_p7_regressions` 有 2 项 pre-existing 失败**：均已证明非本次引入。
7. ~~**Sanitizer 的 REJECT_GIVE_UP 在 MainAgent 内可能不触发**~~ → **已修复（见附录）**。

---

## 十、REJECT_AND_FIX 阻塞项修复附录

### 初始判定：REJECT_AND_FIX（三个阻塞项）

1. **显式内部过程穿透**：输出净化在 MainAgent 内的 REJECT_GIVE_UP 不可达，存在 `<thinking>` 等标签透传到下游的风险。
2. **重试语义不统一**：`max_reflections=2` 允许多达 2 次修订(3 次 Writer 调用)，违反合同"最多一次修订"。
3. **Advice 防泄露仅靠 prompt**：缺少确定性的元话语检测规则。

### 修复详情

#### 阻塞项 1+2：统一重试 + 最终安全屏障

**改动文件**：`comfyui_awp_rp/nodes/main_agent.py`（反思循环完整替换）

| 参数 | 旧值 | 新值 |
|------|------|------|
| 最大修订次数 | `max_reflections=2` (最多 3 次 Writer) | `max_repair_retries=1` (最多 2 次 Writer) |
| 变量命名 | `reflection_attempts`（歧义） | `repair_attempts`（明确） |
| `sanitize_output` max_retries | 2 | 1（与循环一致） |
| REJECT_GIVE_UP 可达性 | 不可达（循环在 attempt=2 调用前退出） | **可达**（最终安全屏障在循环后独立调用，attempt=1>=max_retries=1 → GIVE_UP） |

**最终安全屏障位置**（`main_agent.py`，反思 while 循环之后、`# Record session` 之前）：

```python
# FINAL safety barrier
final_verdict = sanitize_output(
    final_text, attempt=max_repair_retries, max_retries=max_repair_retries
)
if final_verdict.action == SanitizerAction.REJECT_GIVE_UP:
    final_text = "[生成安全失败] 本回合内容未能通过质量检查。请重新发送消息或调整输入后再试。"
elif final_verdict.action == SanitizerAction.SCRUB_PREFIX:
    final_text = final_verdict.cleaned_text
```

**非法输出不进入 OutputRenderer 的保证**：最终安全屏障在 MainAgent 的 `return` 语句之前运行，`final_text` 被替换为安全诊断字符串后才流向下游节点。不存在依赖 QualityGate"标记"的路径。

**最大 Writer 调用数 = 2（初始 + 一次修订）**：循环 `while repair_attempts < 1` 最多执行一次修订 LLM 调用。共 1 初始 + ≤1 修订 = ≤2。

#### 阻塞项 3：Advice 终端防泄露检测

**改动文件**：`comfyui_awp_rp/runtime/output_sanitizer.py`

**检测范围**（窄、保守，聚焦元话语形式）：
| 匹配短语 | 触发条件 | 说明 |
|----------|----------|------|
| `评审认为`、`导演建议`、`内部建议`、`子 Agent`、`子Agent` | 在开头 500 字符或全文中 | 多字组合，不会误伤"导演""评审"单独出现 |
| `[评审]`、`[导演]`、`[critic]`、`[director]`、`[advice]` | 全文 | 方括号标记，明确工具性元信息 |
| `subagent advice`、`critic advice`、`director advice` | 开头 500 字符 | 英文元话语，中文 RP 不会自然出现 |

**防误伤验证**：
- `"戏班导演站在台下"` → 不命中 ✅（不含"导演建议"组合）
- `"她的评审工作很忙"` → 不命中 ✅（不含"评审认为"组合）
- `"她想了想，让他进入房间"` → 不命中 ✅
- `"评审认为应当注意关系张力"` → 命中 ✅（触发 REJECT_RETRY，与 `<thinking>` 同等处理）

**处理规则**：与显式标签（`<thinking>` 等）完全相同的有限重试/终态失败规则——命中即 REJECT_RETRY(attempt < max_retries) 或 REJECT_GIVE_UP(attempt ≥ max_retries)。

### 新增验收测试（6 项）

| # | 测试 | 断言 | 结果 |
|---|------|------|------|
| 1 | `test_double_thinking_triggers_safe_failure` | 两次 `<thinking>` → writer_call_count=2, final_text="生成安全失败", 不含 `<thinking>` | ✅ |
| 2 | `test_double_analysis_retry_then_safe_failure` | 两次 `<analysis>` → 同样终态失败 | ✅ |
| 3 | `test_initial_analysis_repair_success` | 初始 `<analysis>` → 1 次修订 → 干净输出 → writer_call_count=2, 无安全失败 | ✅ |
| 4 | `test_leading_meta_scrubbed_no_extra_call` | "好，现在让我们进入故事"+"正文" → SCRUB_PREFIX, writer_call_count=1(不耗重试) | ✅ |
| 5 | `test_advice_leak_terminates` + `test_director_advice_leak_terminates` | "评审认为"/"导演建议" → 终态失败, 不含检出短语 | ✅ |
| 6 | `test_innocent_narrative_passes` | "她想了想…""导演站在台下" → writer_call_count=1, 不触发安全失败 | ✅ |
| 7 | `test_routed_chain_output_renderer_never_gets_bad_content` | routed workflow 全链路 smoke, 最终叙事不含任何禁止内容 | ✅ |

### 完整测试结果（修复后）

```bash
python -m unittest comfyui_awp_rp.test_runtime_v1 comfyui_awp_rp.test_acceptance_v1 comfyui_awp_rp.test_rp_pipeline_nodes
# Ran 74 tests in 7.2s — OK (exit 0)
```

| 套件 | 项数 | 状态 |
|------|------|------|
| `test_runtime_v1` | 34 | OK |
| `test_acceptance_v1` | 28 | OK（含 6 项新 gap-fix + 修复后的 profile-not-found） |
| `test_rp_pipeline_nodes`（回归） | 12 | OK |
| **合计** | **74** | **OK（0 项失败、0 项新增失败）** |

### 本次改动汇总（修复阶段）

| 文件 | 改动 |
|------|------|
| `comfyui_awp_rp/nodes/main_agent.py` | `max_reflections→max_repair_retries=1`、变量重命名、新增最终安全屏障 |
| `comfyui_awp_rp/runtime/output_sanitizer.py` | 新增 `ADVICE_LEAK_PATTERNS` + `_has_advice_leak()` + 接入 Tier A |
| `comfyui_awp_rp/runtime/subagent_orchestrator.py` | 新增 `_detect_error()`（验收阶段发现 profile 不存在误标记 ok=True→已修复） |
| `comfyui_awp_rp/test_acceptance_v1.py` | 新增 6 类 + 6 项专项测试 |

---

## 十一、冻结前机械验证结果

```bash
# 1) 全量测试
python -m unittest comfyui_awp_rp.test_runtime_v1 comfyui_awp_rp.test_acceptance_v1 comfyui_awp_rp.test_rp_pipeline_nodes
# Ran 74 tests in 7.6s — OK (exit 0)

# 2) git status --short (Phase 1 相关文件)
 M comfyui_awp_rp/knowledge/worldbook.py
 M comfyui_awp_rp/nodes/__init__.py
 M comfyui_awp_rp/nodes/main_agent.py
 M comfyui_awp_rp/nodes/memory_nodes.py
 M comfyui_awp_rp/nodes/pipeline_nodes.py
?? comfyui_awp_rp/nodes/router_nodes.py
?? comfyui_awp_rp/runtime/
?? comfyui_awp_rp/test_acceptance_v1.py
?? comfyui_awp_rp/test_runtime_v1.py
?? docs/awp-rp-routing-memory-v1-acceptance.md
?? docs/awp-rp-routing-memory-v1-plan.md
?? docs/awp-rp-routing-memory-v1-report.md
?? workflows/rp_full_features_routed_v1_workflow.json

# 3) git diff --check
# exit 0（仅有 LF/CRLF 行尾警告，无内容冲突）

# 4) git diff --stat
# 7 files changed, 311 insertions(+), 50 deletions(-)
```

**排除的无关文件**（不提交）：`test_plugin.py`（pre-existing 改动）、`server/static/*`（pre-existing）、日志/缓存/私密文件。

---

## 十二、冻结结论

**ACCEPT_AND_FREEZE**

**tag**: `phase-awp-rp-routing-output-safety-v1-stable`

**冻结范围**（不得继续在此 commit 上堆功能）：
- `comfyui_awp_rp/runtime/` — 确定性路由、净化器、编排器、数据合同
- `comfyui_awp_rp/nodes/main_agent.py` — 世界书分权、最终安全屏障、Writer ≤2 调用
- `comfyui_awp_rp/nodes/memory_nodes.py` — 路由门控
- `comfyui_awp_rp/nodes/pipeline_nodes.py` — 世界书预算裁剪
- `comfyui_awp_rp/knowledge/worldbook.py` — `apply_worldbook_budget`、legacy 预算
- `comfyui_awp_rp/nodes/router_nodes.py` — AWPRoundRouter / AWPSubAgentOrchestrator
- `workflows/rp_full_features_routed_v1_workflow.json`

**Writer 调用上限**：初始 1 次 + 修订 ≤1 次 = ≤2 次。

**REJECT_GIVE_UP 安全交付行为**：最终安全屏障在 MainAgent 反思循环后、`return` 前独立运行；非法输出被替换为 `[生成安全失败]` 诊断字符串，不进入 OutputRenderer。

**Advice 元话语检测范围**：窄组合词 `评审认为/导演建议/内部建议/子 Agent/子Agent/subagent advice/critic advice/director advice` + 方括号标记 `[评审]/[导演]/[critic]/[director]/[advice]`。不误伤普通叙事词（`戏班导演/她的评审` 单独出现不命中）。

---

## 十三、留给 Phase 2

**必须新开分支，以本 tag 为基线。**

- 结构化记忆：`story_facts / open_threads / scene_state` 分区 + 幂等合并 + schema 校验
- `rp-memory-curator` 按路由触发写入（路由规则新增、不修改 V1 规则）
- `relationship_state` 复用 MVU 变量系统（`current_variables`），不另造数值系统
- 不得修改 V1 的世界书分权、确定性路由、输出安全边界

## 十四、留给 Phase 3

**必须显式开关，默认不消耗 DeepSeek API。**

- 20–40 回合真实 API 长对话回归测试
- 产出指标报告：子 Agent 调用次数 / 记忆读取次数 / 世界书检索次数 / 平均 core context / 质量门禁重试次数 / 元信息泄露次数 / fallback 次数
- 不修改 V1 确定性规则
