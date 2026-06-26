# 待解决问题清单

**创建日期**：2026-06-26
**状态**：待处理

---

## 项目背景

### 项目概述
本项目是 ComfyUI 的自定义节点包 **AWP RP**（AI Writing Partner - Role Play），用于角色扮演（RP）和小说/长篇小说工作流。项目通过 ComfyUI 的节点系统实现 AI 驱动的交互式叙事。

### 核心架构
```
用户输入 → AWPMainAgent → 工具调用 → 生成回复
                ↓
        AWPRoundPreparer（回合预处理）
                ↓
        AWPMemoryRead/Write（长期记忆）
                ↓
        AWPWorldbook（世界书系统）
```

### 关键节点说明

| 节点 | 文件 | 功能 |
|------|------|------|
| `AWPMainAgent` | `comfyui_awp_rp/nodes/main_agent.py` | 主 Agent，负责生成回复、调用工具、管理 Agent Loop |
| `AWPRoundPreparer` | `comfyui_awp_rp/nodes/pipeline_nodes.py` | 回合预处理，组装上下文（世界书匹配、记忆召回、变量清单） |
| `AWPMemoryRead` | `comfyui_awp_rp/nodes/memory_nodes.py` | 从长期存储中读取记忆 |
| `AWPMemoryWrite` | `comfyui_awp_rp/nodes/memory_nodes.py` | 写入记忆到长期存储 |
| `AWPQualityGate` | `comfyui_awp_rp/nodes/pipeline_nodes.py` | 质量门禁，检查回复质量 |
| `AWPTextOutput` | `comfyui_awp_rp/nodes/input_nodes.py` | 最终回复输出（Node 23） |

### 工具系统

主 Agent 拥有以下工具：
- `memory_read` - 读取长期记忆
- `worldbook_search` - 搜索世界书
- `retrieval_search` - 检索搜索
- `card_get` - 获取角色卡
- `continuity_check` - 连续性检查
- `npc_activity_scan` - NPC 活动扫描
- `delegate_to_sub_agent` - 委托给子 Agent

### 子 Agent 系统

子 Agent 使用专用 Profile 处理特定任务：
- `rp-critic` - RP 评审，检查世界观一致性、角色一致性
- `rp-director` - RP 导演，创建场景计划
- `rp-memory-curator` - 记忆管理，提取关键事件
- `novel-reviewer` - 小说评审
- `novel-deconstruction` - 小说解构

### 当前测试环境

- **工作流**：`rp_full_features_api_workflow.json`（33 节点）
- **角色卡**：桃花村的公媳（card_65af4496c7eb9f1f）
- **世界书**：36 个条目（24 个常开，12 个选择性）
- **LLM 提供商**：DeepSeek（deepseek-chat）
- **测试轮次**：40 轮长对话

### 已解决的问题

1. **常开世界书加载**：从 4,700 tokens 提升到 64,000+ tokens
2. **长期记忆缓存**：通过注入递增 run_id 解决 ComfyUI 缓存问题
3. **内部推理泄露**：在系统提示词中明确禁止输出内部推理
4. **工具调用强化**：从 0-2 次/轮提升到 3 次/轮

---

## 问题 1：子 Agent 未被调用

### 问题描述
即使在复杂情感场景中，模型也不调用 `delegate_to_sub_agent` 工具。40 轮对话测试中，子 Agent 调用次数为 0。

### 涉及节点
- `AWPMainAgent`（Node 14）- 主 Agent 节点
- `delegate_to_sub_agent` 工具 - 子 Agent 委托工具

### 涉及文件
- `comfyui_awp_rp/nodes/main_agent.py` - 系统提示词
- `comfyui_awp_rp/tools/builtin/delegate_tool.py` - 子 Agent 工具定义

### 可能原因
1. **模型能力限制**：DeepSeek 可能不擅长调用复杂的多参数工具
2. **工具描述不清晰**：虽然已改为中文，但模型仍不理解何时使用
3. **系统提示词不够强制**：当前只是建议使用，没有强制要求

### 复现步骤
1. 启动服务器：`python server/workflow_runner.py --port 5180`
2. 使用工作流：`rp_full_features_api_workflow.json`
3. 使用角色卡：桃花村的公媳（card_65af4496c7eb9f1f）
4. 发送涉及角色内心世界的问题，如："语晴，你怨我吗？"
5. 检查工具调用日志，确认是否调用了 `delegate_to_sub_agent`

### 建议修复方案
1. **方案 A**：在工作流中添加自动触发子 Agent 的节点
   - 在 `AWPMainAgent` 之后添加一个判断节点
   - 当满足特定条件（如情感冲突、复杂情节）时自动调用子 Agent

2. **方案 B**：在系统提示词中添加更强制的指令
   - 例如："每 5 轮必须调用一次子 Agent 进行深度分析"
   - 或者："当用户提出涉及角色内心世界的问题时，必须调用子 Agent"

3. **方案 C**：优化子 Agent 工具的参数设计
   - 简化参数，只保留 `profile` 和 `task`
   - 让模型更容易理解和调用

---

## 问题 2：工具调用不够积极

### 问题描述
40 轮对话中只有 3 次工具调用（memory_read: 1, npc_activity_scan: 2），大部分时候模型直接用上下文生成回复。

### 涉及节点
- `AWPMainAgent`（Node 14）- 主 Agent 节点

### 涉及文件
- `comfyui_awp_rp/nodes/main_agent.py` - 系统提示词

### 可能原因
1. **常开世界书提供了足够的上下文**：64,000+ tokens 的世界书让模型认为不需要调用工具
2. **模型的工具调用能力有限**：DeepSeek 可能不擅长判断何时需要调用工具
3. **工具调用的触发条件不明确**：系统提示词中只是建议使用，没有明确的触发条件

### 复现步骤
1. 启动服务器：`python server/workflow_runner.py --port 5180`
2. 使用工作流：`rp_full_features_api_workflow.json`
3. 使用角色卡：桃花村的公媳（card_65af4496c7eb9f1f）
4. 进行 40 轮对话
5. 统计工具调用次数

### 建议修复方案
1. **方案 A**：优化系统提示词
   - 明确规定每轮必须调用的工具
   - 添加工具调用的触发条件

2. **方案 B**：添加更多工具
   - 添加 `continuity_check` 工具
   - 添加 `npc_activity_scan` 工具的更明确描述

3. **方案 C**：优化工具调用的奖励机制
   - 在质量门禁中添加工具调用的检查
   - 如果没有调用工具，自动重试

---

## 问题 3：长期记忆利用率低

### 问题描述
记忆写入正常（每轮都保存），但读取不够积极。模型主要依赖 session 内的短期记忆（AWPRoundPreparer 组装的上下文）。

### 涉及节点
- `AWPMemoryRead`（Node 11）- 记忆读取节点
- `AWPMemoryWrite`（Node 21）- 记忆写入节点
- `AWPRoundPreparer`（Node 13）- 回合预处理节点

### 涉及文件
- `comfyui_awp_rp/nodes/memory_nodes.py` - 记忆节点
- `comfyui_awp_rp/nodes/pipeline_nodes.py` - 管线节点

### 可能原因
1. **短期记忆已经足够**：AWPRoundPreparer 组装的上下文已经包含了足够的信息
2. **记忆读取的触发条件不明确**：系统提示词中只是建议使用，没有明确的触发条件
3. **记忆质量不高**：保存的记忆可能不够关键，模型认为不需要读取

### 复现步骤
1. 启动服务器：`python server/workflow_runner.py --port 5180`
2. 使用工作流：`rp_full_features_api_workflow.json`
3. 使用角色卡：桃花村的公媳（card_65af4496c7eb9f1f）
4. 进行 40 轮对话
5. 检查记忆读取次数和内容

### 建议修复方案
1. **方案 A**：优化记忆读取的触发条件
   - 在系统提示词中明确规定何时必须读取记忆
   - 例如："当用户提到之前发生的事情时，必须读取记忆"

2. **方案 B**：添加记忆摘要功能
   - 定期对记忆进行摘要，提取关键信息
   - 在回合预处理中自动加载记忆摘要

3. **方案 C**：优化记忆写入质量
   - 只保存关键事件、关系变化和状态变化
   - 添加记忆重要性评分

---

## 问题 4：内部推理偶尔泄露

### 问题描述
虽然已修复大部分内部推理泄露，但偶尔仍会出现 "好，这是故事的开端。让我直接进入角色，开始叙事。" 这类元信息。

### 涉及节点
- `AWPMainAgent`（Node 14）- 主 Agent 节点
- `AWPQualityGate`（Node 17）- 质量门禁节点

### 涉及文件
- `comfyui_awp_rp/nodes/main_agent.py` - 系统提示词
- `comfyui_awp_rp/rp_pipeline.py` - 质量门禁逻辑

### 可能原因
1. **系统提示词不够严格**：虽然已禁止输出内部推理，但模型偶尔仍会输出
2. **质量门禁没有检查这类元信息**：当前的质量门禁主要检查格式和内容，没有检查元信息

### 复现步骤
1. 启动服务器：`python server/workflow_runner.py --port 5180`
2. 使用工作流：`rp_full_features_api_workflow.json`
3. 使用角色卡：桃花村的公媳（card_65af4496c7eb9f1f）
4. 进行多轮对话
5. 检查回复中是否包含元信息

### 建议修复方案
1. **方案 A**：在质量门禁中添加检查规则
   - 检查回复中是否包含 "Step"、"翻记忆"、"看盘面" 等关键词
   - 如果包含，自动重试

2. **方案 B**：在后处理中自动移除元信息
   - 使用正则表达式移除开头的元信息
   - 保留叙事文本和选项

3. **方案 C**：优化系统提示词
   - 更明确地禁止输出任何元信息
   - 添加示例，展示正确的回复格式

---

## 优先级排序

| 优先级 | 问题 | 影响 |
|--------|------|------|
| 高 | 子 Agent 未被调用 | 无法进行深度分析和审查 |
| 高 | 工具调用不够积极 | 长对话中可能出现记忆混乱 |
| 中 | 长期记忆利用率低 | 长对话中可能忘记重要事件 |
| 低 | 内部推理偶尔泄露 | 影响用户体验 |

---

## 联系人

如有问题，请联系开发团队。
