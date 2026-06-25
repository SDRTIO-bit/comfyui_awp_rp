# 给下一个 AI 会话的上下文

> **如果你是新启动的 AI 会话，先读这个文件。** 它包含了继续 AWP RP 项目开发所需的全部上下文。

---

## 1. 我是谁，我在哪

- **项目**: AWP RP — ComfyUI 自定义节点插件，用于角色扮演(RP)和长篇小说创作
- **路径**: `F:\12\语英\本体_ComfyUI\ComfyUI\custom_nodes\awp-demo-turn-lifecycle`
- **Python 包**: `comfyui_awp_rp`
- **平台**: Windows, Python 3.10+, ComfyUI 环境
- **核心约束**: 纯 Python 节点插件，零外部依赖（除 LLM API）

---

## 2. 已经做了什么（2026-06-25 完成 P0-P4）

一个完整的 RP 引擎，包含：

- **39 个 ComfyUI 节点**：Agent、管线、MVU、会话、记忆、检索、世界书、角色卡、预设、项目/大纲、IO
- **15 个 Skills**：角色扮演、叙事理论、硬性门禁、NPC 活性、仙侠/爽点/反套路写作
- **11 个 Tools**：记忆读写、世界书读写、检索、角色卡、连续性检查、NPC 扫描、子Agent 派发
- **MVU 变量系统**：命令解析+执行+验证+审计+世界书匹配（~1200行引擎）
- **质量门禁**：7 维度文本检查（格式/玩家代理权/知识泄露/散文风格/情感用词/AI 写作痕迹/网文套话）
- **Agent Loop**：工具调用 + 子Agent 派发 + 自我反思（最多2次重试）+ MVU 变量更新
- **3 种检索策略**：BM25 / TF-IDF 语义 / 混合

全部变更记录在 `docs/ROADMAP.md`。

---

## 3. 快速入门 — 读这些文件

```
docs/ROADMAP.md              ← 全局地图（已完成 vs 待办）
docs/FUTURE_WORK.md           ← 每个待办功能的详细实现规格
docs/REFERENCE_REPOS.md       ← 三个参考仓库的借鉴摘要和源码位置
docs/IMPLEMENTATION_GUIDE.md  ← 代码模式模板（新增节点/Tool/Skill/检索策略）
ARCHITECTURE.md               ← 完整架构文档（420行，建议通读）
```

---

## 4. 如果用户说「继续」— 按这个顺序做

### 优先级排序（P5 → P6 → P7）

```
P5.1 剧情规划 (每8轮 STORY.md 分析)          ← 最推荐，叙事质量提升
P5.2 注入规则 (变量→世界书自动注入)          ← 与 P5.1 独立
P5.3 Action Options (每轮3个行动选项)        ← 与 P5.1/5.2 独立
P5.4 Token 预算管理 (agent loop 内截断)      ← 先做 P5.4 再做 P6
P5.5 子Agent 结果验证 (delegate后审查)       ← 小改动
──
P6.1 流式输出 (SSE)                          ← 中等工作量
P6.2 并行工具调用                             ← 依赖 P5.4
P6.3 Author's Note 注入点                     ← 小改动
P6.4 卡结构检测                               ← 依赖角色卡数据格式
──
P7.1 ChromaDB 向量存储                        ← 大工作量，需要新依赖
P7.2 Story System Contracts                   ← 需要理解 webnovel-writer
P7.3 工作流模板库                             ← 与代码无关
P7.4 Web 前端                                 ← 最大工作量
```

**P5.1-P5.3 可以并行做**，它们互不依赖。

---

## 5. 关键文件位置速查

| 要做什么 | 改哪个文件 |
|----------|-----------|
| 增加一个节点 | 新建 `nodes/xxx.py` + 修改 `nodes/__init__.py` |
| 增加一个工具 | 新建 `tools/builtin/xxx.py` + 修改 `tools/builtin/__init__.py` |
| 增加一个技能 | 修改 `tools/skill_manager.py` 的 `_load_builtin_skills()` |
| 修改 Agent 行为 | 修改 `nodes/main_agent.py` |
| 修改管线行为 | 修改 `nodes/pipeline_nodes.py` 或 `rp_pipeline.py` |
| 修改质量门禁 | 修改 `rp_pipeline.py` 的 `apply_quality_gate()` |
| 增加检索策略 | 修改 `nodes/retriever_node.py` + 新建 `retrieval/xxx.py` |
| 修改 MVU 引擎 | 修改 `mvu/engine.py` |
| 修改 LLM 调用 | 修改 `core/llm_router.py` |
| 修改数据类型 | 修改 `core/types.py` |

---

## 6. 验证流程（每次改动后必做）

```bash
# 1. 语法检查
python -c "import py_compile; py_compile.compile(r'<改动的文件完整路径>', doraise=True); print('OK')"

# 2. 导入测试（验证节点注册）
python -c "import sys; sys.path.insert(0, r'<项目根目录>'); from comfyui_awp_rp.nodes import NODE_CLASS_MAPPINGS; print(len(NODE_CLASS_MAPPINGS))"

# 3. 功能测试（写临时脚本，参考 test_rp_pipeline_nodes.py）

# 4. MVU 引擎自测
python mvu/engine.py
```

---

## 7. Git 提交格式

```
feat: Px.y — [英文功能描述]

[中文详细说明，列出改动的文件和功能点]

Verification: [验证结果摘要]
```

示例：
```
feat: P5.1 — Story planning every N turns

- tools/builtin/story_plan_tool.py: story_plan_check + story_plan_execute
- skill_manager.py: story_planning skill with 6-dimension analysis
- main_agent.py: trigger story planning after record_session

Verification: 3/3 syntax passes, 2/2 functional tests pass, 41 nodes registered
```

---

## 8. 参考仓库的关键文件

如果实现某个功能时需要看参考实现：

| 功能 | 参考文件 | 路径 |
|------|---------|------|
| 剧情规划 | CLAUDE.md 剧情规划章节 | `F:\game\AIRP_ClaudeCode-master\AIRP_ClaudeCode-master\CLAUDE.md` (第320-360行) |
| 注入规则 | handler.py apply_injections() | `F:\game\AIRP_ClaudeCode-master\AIRP_ClaudeCode-master\skills\handler.py` |
| 行动选项 | CLAUDE.md 行动选项章节 | 同上 CLAUDE.md (第517-528行) |
| 合同系统 | webnovel.py story-system | `F:\zhao\webnovel-writer\webnovel-writer\scripts\webnovel.py` |
| 写作参考 | anti-ai-guide.md 等 | `F:\zhao\webnovel-writer\webnovel-writer\skills\webnovel-write\references\` |

---

## 9. 技术债务（如果要修的话）

| 问题 | 位置 | 优先级 |
|------|------|--------|
| Token 估计粗糙（`len(text)//4`） | `rp_pipeline.py` `estimate_tokens()` | 低 |
| 中文分词依赖 jieba（不可用时退化为2-gram） | `retrieval/tokenizer.py` | 低 |
| Skill 内容硬编码（应迁移到 JSON 文件） | `tools/skill_manager.py` | 低 |
| Agent loop 工具串行执行 | `nodes/main_agent.py` | P6.2 |
| 无流式输出 | `nodes/main_agent.py` + `core/llm_router.py` | P6.1 |

---

## 10. 不要做的事情

- ❌ 不要引入 `as any` / `@ts-ignore` 等类型抑制
- ❌ 不要删除现有测试来"通过"
- ❌ 不要在没有读 `IMPLEMENTATION_GUIDE.md` 的情况下新增节点
- ❌ 不要破坏 ComfyUI 节点签名（RETURN_TYPES 必须与 return 元组对齐）
- ❌ 不要假设 jieba 或 ChromaDB 已安装（用 try/except 做优雅降级）
- ❌ 不要在 `nodes/` 下的文件之间相互导入
