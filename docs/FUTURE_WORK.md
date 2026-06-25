# 未来工作 — 详细实现规格

> 本文档为每个未实现功能提供详细的实现规格，包括代码位置、参考实现、注意事项。
> 每个功能都有独立的「上下文快照」：下一个 AI 会话只需读对应章节即可开始实现。

---

## 上下文快照（给新 AI 会话）

在继续任何未实现功能前，请先了解：

1. 这是一个 **ComfyUI 自定义节点插件**，所有功能必须是 ComfyUI 节点或内部可调用的 Python 模块
2. 目录：`F:\12\语英\本体_ComfyUI\ComfyUI\custom_nodes\awp-demo-turn-lifecycle`
3. 核心架构见 `ARCHITECTURE.md`
4. 已完成功能见 `ROADMAP.md`
5. 参考仓库关键文件位置见 `REFERENCE_REPOS.md`
6. 代码模式见 `IMPLEMENTATION_GUIDE.md`

**关键约束**：
- 纯 Python，零外部依赖（除 LLM API）
- 新增 ComfyUI 节点需在 `nodes/__init__.py` 注册
- 新增 Tool 需在 `tools/builtin/__init__.py` 注册
- 新增 Skill 需在 `tools/skill_manager.py` 的 `_load_builtin_skills()` 添加
- 验证方法：`python -c "import py_compile; py_compile.compile('<file>', doraise=True)"`

---

## P5.1 — 剧情规划（Story Planning）

**来源**：oh-story-claudecode `CLAUDE.md` 的「剧情规划」章节

**目标**：每 N 轮（默认8轮）自动运行叙事理论分析，生成 `story_plan.md`

**实现位置**：

### 新文件: `tools/builtin/story_plan_tool.py`

```python
# 工具名称: story_plan_check
# 功能: 检查是否应该触发剧情规划
# 输入: current_turn (int), plan_interval (int, default=8)
# 输出: {should_plan: bool, reason: str}

# 工具名称: story_plan_execute  
# 功能: 执行一次剧情规划（委托给 sub-agent）
# 输入: session_id, story_state (dict)
# 输出: {plan: str, updated_state: dict}
```

### 新增 Skill: `story_planning`（在 skill_manager.py）

内容结构（来自 oh-story-claudecode STORY.md）：
- 价值转换检查（麦基场景检验）
- 布克模式定位（7种基本情节）
- 节拍定位（救猫咪15节拍，松散参考）
- 角色原型追踪（皮尔逊12原型）
- 伏笔审计
- 情感波浪线
- 信息不对称检查

### 修改: `nodes/main_agent.py`

在 agent loop 的 `record_session` 后增加剧情规划触发检查：

```python
# 伪代码
if should_plan_story_plan(gen_count, plan_interval):
    plan = delegate_to_sub_agent(profile="novel-context-agent", task="story planning...")
    metadata["story_plan"] = plan
```

**参考实现**：oh-story-claudecode `CLAUDE.md` 第 320-360 行（剧情规划章节）

**关键设计决策**：
- NSFW/氛围沉浸/日常温情场景豁免——这些场景的"停滞"是合法的
- 框架服务于故事，不强制映射
- PLANNING_INTERVAL 可动态调整（5-12轮）

---

## P5.2 — 注入规则（Injection Rules）

**来源**：oh-story-claudecode `handler.py` 的 `apply_injections()` + `mvu_server.js` 的 `/inject` 端点

**目标**：当变量达到特定值时，自动将相关世界书条目注入到下一轮上下文

**实现位置**：

### 新文件: `tools/builtin/injection_tool.py`

```python
# 工具名称: get_injections
# 功能: 从变量状态中提取注入关键词
# 输入: stat_data (dict), injection_rules (list)
# 输出: [{keyword, section, one_liner}, ...]
```

### 修改: `nodes/pipeline_nodes.py` AWPRoundPreparer

在 Step 1（变量驱动世界书匹配）之后增加 Step 1.5（注入规则匹配）：

```python
# 伪代码
if injection_rules:
    injections = get_injections(variables, injection_rules)
    for inj in injections:
        # 查找完整世界书条目正文
        full_entry = lookup_worldbook_full_text(inj.keyword, worldbook)
        sections.append(f"## Injection: {inj.keyword}\n{full_entry}")
```

**参考实现**：
- oh-story-claudecode `handler.py` `apply_injections()` 函数
- oh-story-claudecode `mvu_shared.js` `extractInjectionRulesFromScripts()` 函数
- oh-story-claudecode `mvu_server.js` `/inject` 端点

**注入规则格式**（来自 oh-story-claudecode）：
```json
{
  "source_path": "世界设定.性癖",
  "split_pattern": "[，、\\n]",
  "prefix": "性癖",
  "trigger_on": ["variable_update"]
}
```

---

## P5.3 — Action Options（行动选项）

**来源**：oh-story-claudecode `CLAUDE.md` 的「行动选项」章节

**目标**：每轮 AI 回复后附带 3 个可选行动按钮

**实现位置**：

### 修改: `nodes/main_agent.py` system prompt

在 agent loop 的 system prompt 末尾追加行动选项生成指令：

```
## 行动选项
每轮生成 3 个用户下一步行动选项，用 <options> 标签包裹：
- 紧密衔接前文，基于当前剧情自然延伸
- 3 个选项应引导不同走向（试探/主动/回避，温情/玩闹/对抗）
- 每个选项 15-40 字，写出具体动作或对白方向
- 选项前加 emoji（😏🥺😈🤔💀✨🔥😨）
- 负面选项最多 1 个，且在剧情上合理
- 颜色包裹：温情=#5a7a5a，挑衅=#b06a3d，对抗=#b0624a，试探=#5a8a9a
```

### 修改: `rp_pipeline.py`

在 `render_final_output()` 或 `build_director_prompt()` 中增加 `<options>` 解析：

```python
def extract_options(text: str) -> list[str]:
    """Extract <options> block from AI output."""
    match = re.search(r"<options>(.*?)</options>", text, re.DOTALL)
    if not match:
        return []
    return [line.strip() for line in match.group(1).split("\n") if line.strip()]
```

**参考实现**：oh-story-claudecode `CLAUDE.md` 第 517-528 行

---

## P5.4 — Token 预算管理

**来源**：oh-story-claudecode `short_term.py` 的 `get_context_for_prompt()`

**目标**：Agent loop 内根据 token 预算自动截断对话历史

**当前状态**：`estimate_tokens()` 使用 `len(text)//4`，但 agent loop 中未实际截断

**实现位置**：

### 修改: `nodes/main_agent.py`

在 agent loop 的每次迭代前检查 token 预算：

```python
MAX_CONTEXT_TOKENS = 8000  # 可配置

def _trim_messages(messages, max_tokens):
    """从最旧的消息开始截断，保留 system + 最新消息"""
    # 保留 system message
    # 从后往前保留 user/assistant/tool 消息直到预算用完
    # 如果超出预算，插入摘要消息
```

**关键考虑**：
- system prompt 通常占用 500-2000 tokens
- 每个 tool call + result 占用较多（返回完整 JSON）
- 需要在截断时保留关键上下文

---

## P5.5 — 子Agent 结果验证

**来源**：webnovel-writer `webnovel-write` Skill 的 Step 3（审查步骤）

**目标**：delegate_to_sub_agent 返回后，验证结果质量

**实现位置**：

### 修改: `tools/builtin/delegate_tool.py`

在 `_run_sub_agent()` 返回后增加验证步骤：

```python
# 伪代码
result = _run_sub_agent(...)
if profile.startswith("novel-reviewer"):
    # 验证审查结果是否包含必需的 dimension_results
    parsed = json.loads(result)
    assert "dimension_results" in parsed
    assert len(parsed["dimension_results"]) == 5
elif profile.startswith("novel-data-agent"):
    # 验证提取结果是否包含必需的 events/deltas
    ...
```

---

## P6.1 — 流式输出（SSE）

**目标**：支持 token-by-token 流式输出

**实现位置**：

### 修改: `core/llm_router.py`

增加 streaming 支持：

```python
def complete_stream(self, node_config, messages, tools=None):
    """流式调用 LLM，yield 每个 token"""
    # 使用 OpenAI 兼容 API 的 stream=True
    # yield {"token": "text", "finish_reason": None|"stop"|"tool_calls"}
```

### 修改: `nodes/main_agent.py`

Agent loop 中支持流式模式：

```python
if enable_streaming:
    for chunk in router.complete_stream(...):
        yield chunk
```

**注意**：ComfyUI 节点的 execute() 是同步的，流式输出需要不同的架构（generator-based 或 callback-based）。

---

## P6.2 — 并行工具调用

**目标**：Agent loop 中的多个 tool_call 并行执行

**当前状态**：`executor.execute_calls()` 是串行的 for 循环

**实现位置**：

### 修改: `tools/tool_executor.py`

```python
import concurrent.futures

def execute_calls_parallel(self, calls, max_workers=4):
    """并行执行多个 tool call"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(self.execute_call, call): call for call in calls}
        results = []
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    return results
```

**注意**：并行执行要求工具之间无依赖关系。如果工具 A 的输出是工具 B 的输入，必须串行。

---

## P7.1 — ChromaDB 向量存储

**目标**：用 ChromaDB 替代 TF-IDF 做真·语义检索

**实现位置**：

### 新文件: `retrieval/vector_store.py`

```python
# 依赖: pip install chromadb
# 可选依赖（用户未安装时退化为 TF-IDF）

class VectorStore:
    def __init__(self, persist_dir):
        import chromadb
        self.client = chromadb.PersistentClient(path=persist_dir)
    
    def index(self, documents, embeddings):
        # 批量化向量化 + 写入
    
    def search(self, query_embedding, top_k=5):
        # 余弦相似度检索
```

### 修改: `retrieval/embedding.py` EmbeddingRetriever

增加 ChromaDB 后端选项：

```python
class EmbeddingRetriever:
    def __init__(self, backend="tfidf"):
        if backend == "chromadb":
            self._store = VectorStore(...)
        else:
            self._vectorizer = TfidfVectorizer()
```

**Embedding 获取**：使用 LLM API 的 embedding 端点（如 OpenAI `text-embedding-3-small`），或本地模型。

---

## P7.2 — Story System Contracts

**来源**：webnovel-writer `story-system` 合同树

**目标**：实现 MASTER_SETTING → volume_NNN → chapter_NNN 三层合同体系

**实现位置**：

### 新文件: `core/story_contracts.py`

```python
class StoryContracts:
    """三层合同体系"""
    master: MasterSetting    # 世界观总设定
    volumes: dict[int, VolumeContract]  # 卷级合同
    chapters: dict[int, ChapterContract]  # 章级合同
    
    def resolve_runtime_contract(self, chapter_num):
        """合并三层合同为运行时合同"""
        # 优先级: chapter > volume > master
        # 返回: {directive, must_cover, forbidden, style, pacing}
```

**合同结构**（来自 webnovel-writer）：
```json
{
  "chapter_directive": {
    "goal": "本章目标",
    "time_anchor": "时间锚点",
    "chapter_span": "跨度",
    "chapter_end_open_question": "章末悬念"
  },
  "must_cover_nodes": ["CBN-1", "CPNs-2", "CEN-1"],
  "forbidden_zones": ["不可触及的话题"],
  "reasoning": {
    "style_priority": "风格优先级",
    "pacing_strategy": "节奏策略",
    "genre": "题材"
  }
}
```

### 修改: `nodes/pipeline_nodes.py` AWPRoundPreparer

集成合同解析：

```python
# 在 Step 1 前增加合同加载
contracts = StoryContracts(project_root)
runtime = contracts.resolve_runtime_contract(chapter_num)
# runtime 指导世界书匹配和上下文组装
```

---

## 实施建议

1. **先做 P5.x**：这些是叙事质量提升，直接可见效果
2. **P5.1-P5.3 可独立并行**：互相无依赖
3. **P6 依赖 P5 的部分基础设施**（如 token 管理）
4. **P7 为可选增强**：当前系统功能完整可用

每个功能的实现应遵循 4 步流程：
1. 阅读参考仓库的对应实现
2. 理解 AWP 现有代码模式（见 IMPLEMENTATION_GUIDE.md）
3. 写代码 → 语法检查 → 导入测试 → 功能测试
4. Git 提交，commit message 格式: `feat: Px.y — [功能描述]`
