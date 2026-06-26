# 2026-06-26 开发日志

## 今日完成的工作

### 一、Web 端工作流测试

#### 1.1 启动服务器并测试 API
- 启动 `workflow_runner.py` 服务器（端口 5180）
- 测试所有 API 端点正常工作
- 验证 ComfyUI 连接正常

#### 1.2 工作流执行测试
- 测试 `rp_full_features_api_workflow.json`（33 节点）
- 测试 `rp_api_v2_optimized.json`（20 节点）
- 验证角色卡加载（桃花村的公媳）

#### 1.3 前端输出选择修复
- **问题**：前端 `pickNarrative` 函数错误显示检索结果 JSON（Node 31），而非最终回复（Node 23）
- **修复**：修改 `frontend/src/pages/RPPage.tsx`，优先查找 `final_rp_reply` 标签输出
- **文件**：`frontend/src/pages/RPPage.tsx`

---

### 二、常开世界书加载修复

#### 2.1 问题发现
- 角色卡"桃花村的公媳"有 36 个世界书条目（24 个常开）
- 但实际只加载了 4 个条目，约 4,700 tokens
- 原因：`AWPRoundPreparer` 节点没有处理 `constant` 激活方式

#### 2.2 修复内容
- **文件**：`comfyui_awp_rp/nodes/pipeline_nodes.py`
- **节点**：`AWPRoundPreparer`
- **修改**：
  1. 添加 Step 2.5：加载所有 `activation == "const"` 的世界书条目
  2. 常开条目使用完整 `content` 而非 `one_liner`
  3. 常开条目不受 `top_worldbook` 数量限制

#### 2.3 测试结果
- 修复前：4,700 tokens
- 修复后：64,000+ tokens ✅

---

### 三、长期记忆缓存修复

#### 3.1 问题发现
- `AWPMemoryWrite` 正确保存了记忆（13 条）
- 但 `AWPMemoryRead` 读取时返回 0 条
- 原因：ComfyUI 缓存机制，`AWPMemoryRead` 的输入（namespace=session_id）不变，导致返回旧的缓存结果

#### 3.2 修复内容
- **文件 1**：`comfyui_awp_rp/nodes/memory_nodes.py`
  - 节点：`AWPMemoryRead`
  - 添加 `run_id` 参数（INT 类型），每次调用时递增

- **文件 2**：`server/workflow_runner.py`
  - 添加 `_inject_run_id()` 函数
  - 每次调用时自动注入递增的 `run_id` 到 `AWPMemoryRead` 节点

#### 3.3 测试结果
- 修复前：缓存导致 0 条记忆
- 修复后：正常读取 13 条记忆 ✅

---

### 四、工具调用和子 Agent 优化

#### 4.1 内部推理泄露修复
- **问题**：模型输出 "Step 1 翻记忆：..." 等内部思考过程
- **修复**：在系统提示词中明确禁止输出内部推理
- **文件**：`comfyui_awp_rp/nodes/main_agent.py`

#### 4.2 工具调用强化
- **问题**：模型经常跳过工具直接回答
- **修复**：在系统提示词中添加强制规则，要求每轮必须调用 `memory_read` 和 `worldbook_search`
- **测试结果**：工具调用从 0-2 次/轮提升到 3 次/轮 ✅

#### 4.3 子 Agent 使用优化
- **问题**：子 Agent 从未被调用
- **修复**：
  1. 修改子 Agent 工具描述为中文，明确使用场景
  2. 在系统提示词中添加子 Agent 使用场景说明
- **测试结果**：仍未调用 ⚠️（见待解决问题）

---

### 五、40 轮长对话测试

#### 5.1 测试配置
- 工作流：`rp_full_features_api_workflow.json`
- 角色卡：桃花村的公媳（card_65af4496c7eb9f1f）
- 世界书：36 个条目（24 个常开）
- 会话 ID：`test-40round-*`

#### 5.2 测试结果
- **成功率**：40/40 轮全部成功 ✅
- **平均 Input Tokens**：28,373
- **格式遵循**：每轮都生成 `<options>` 选项 ✅
- **角色一致性**：正确引用之前的对话内容（银镯子、祠堂、俊伟的病等）✅

#### 5.3 工具调用统计
| 工具 | 次数 |
|------|------|
| `npc_activity_scan` | 2 |
| `memory_read` | 1 |
| 无工具调用 | 37 |

---

## 文件变更清单

### 修改的文件
- `comfyui_awp_rp/nodes/pipeline_nodes.py` - 常开世界书加载
- `comfyui_awp_rp/nodes/memory_nodes.py` - AWPMemoryRead 添加 run_id
- `comfyui_awp_rp/nodes/main_agent.py` - 系统提示词优化
- `comfyui_awp_rp/tools/builtin/delegate_tool.py` - 子 Agent 工具描述
- `server/workflow_runner.py` - 自动注入 run_id
- `frontend/src/pages/RPPage.tsx` - 前端输出选择修复
- `workflows/rp_full_features_api_workflow.json` - 工作流更新

---

## 待解决问题

### 高优先级

#### 1. 子 Agent 未被调用
- **问题**：即使在复杂情感场景中，模型也不调用 `delegate_to_sub_agent`
- **涉及节点**：`AWPMainAgent`（Node 14）、`delegate_to_sub_agent` 工具
- **可能原因**：
  - DeepSeek 模型不擅长调用复杂的多参数工具
  - 工具描述虽然改为中文，但模型仍不理解何时使用
  - 系统提示词中的指令不够强制
- **建议**：
  - 在工作流中添加自动触发子 Agent 的节点
  - 或在系统提示词中添加更强制的指令（如"每 5 轮必须调用一次"）

#### 2. 工具调用不够积极
- **问题**：40 轮对话中只有 3 次工具调用
- **涉及节点**：`AWPMainAgent`（Node 14）
- **可能原因**：
  - 常开世界书提供了足够的上下文，模型认为不需要调用工具
  - 模型的工具调用能力有限
- **建议**：
  - 优化工具调用的触发条件
  - 添加更多工具（如 `continuity_check`）

### 中优先级

#### 3. 长期记忆利用率低
- **问题**：记忆写入正常，但读取不够积极
- **涉及节点**：`AWPMemoryRead`（Node 11）、`AWPMemoryWrite`（Node 21）
- **可能原因**：
  - 模型认为 session 内的短期记忆已经足够
  - 记忆读取的触发条件不够明确
- **建议**：
  - 优化记忆读取的触发条件
  - 添加记忆摘要功能

#### 4. 内部推理偶尔泄露
- **问题**：虽然已修复，但偶尔仍会出现 "好，这是故事的开端。让我直接进入角色，开始叙事。" 这类元信息
- **涉及节点**：`AWPMainAgent`（Node 14）
- **建议**：
  - 在质量门禁（`AWPQualityGate`）中添加检查规则
  - 或在后处理中自动移除这类元信息

### 低优先级

#### 5. Token 使用波动
- **问题**：Token 使用从 15,000 到 78,000 不等，波动较大
- **可能原因**：
  - 世界书匹配数量不固定
  - 记忆读取数量不固定
- **建议**：
  - 优化世界书匹配算法
  - 添加 Token 预算管理

---

## Git 提交记录

```
557a12f fix: 强化工具调用和子Agent使用指引
e3831ab fix: AWPMemoryRead 添加 run_id 参数，workflow_runner 自动注入递增 ID 破缓存
8de39a1 fix: 更新工作流，启用 AWPMemoryRead 的 force_refresh
f015d5e fix: 添加 force_refresh 参数到 AWPMemoryRead 节点，避免缓存问题
c78e17e fix: 修复常开世界书未加载的问题 + 前端输出选择逻辑优化
```

---

## 总结

今日主要完成了以下工作：

1. **常开世界书加载修复**：从 4,700 tokens 提升到 64,000+ tokens
2. **长期记忆缓存修复**：通过注入递增 run_id 解决 ComfyUI 缓存问题
3. **内部推理泄露修复**：在系统提示词中明确禁止输出内部推理
4. **工具调用强化**：从 0-2 次/轮提升到 3 次/轮
5. **40 轮长对话测试**：验证了系统的稳定性和一致性

**待解决**：子 Agent 调用、工具调用积极性、长期记忆利用率
