"""zh-CN 译文字典。

仅用于前端显示层汉化。所有 key（英文字段名/combo 值/菜单项）均为
内部协议标识，绝不可被中文替代；中文仅作为 value 用于显示。

维护规则：
- WIDGET_LABELS: 节点 INPUT_TYPES 字段名 -> 中文显示标签
- COMBO_VALUES:  combo 字段名 -> {英文候选值 -> 中文显示}。同名字段跨
  节点候选值不同时，中文译文必须全局唯一，否则反转（中文->英文）会冲突。
- MENU_LABELS:   ComfyUI 核心菜单/搜索框英文项 -> 中文
"""

# 节点参数面板字段名 -> 中文标签（widget.label 用）
WIDGET_LABELS = {
    # 通用
    "text": "文本", "json_text": "JSON 文本", "validate_json": "验证 JSON",
    "label": "标签", "pretty": "美化输出", "status": "状态", "content": "内容",
    "title": "标题", "name": "名称", "category": "分类", "limit": "数量上限",
    "priority": "优先级", "tags": "标签", "tags_any": "标签匹配",
    "type_filter": "类型过滤", "query": "查询", "operation": "操作",
    "data": "数据", "context": "上下文", "model": "模型", "provider": "供应商",
    "temperature": "温度", "max_tokens": "最大 Token 数", "profile": "档案",
    "strategy": "检索策略", "min_score": "最低分数", "filter_tags": "过滤标签",
    "filter_type": "过滤类型", "importance": "重要度", "entity_ids": "实体 ID",
    "memory_type": "记忆类型", "summary": "摘要", "clear_session": "清除会话",
    "include_history": "包含对话历史", "dry_run": "试运行", "reply": "回复",
    "reply_rules": "回复规则", "task": "任务", "session_id": "会话 ID",
    # 角色卡
    "card_id": "角色卡 ID", "card_json": "角色卡 JSON", "card_path": "角色卡路径",
    "greeting_id": "开场白 ID", "greeting_content": "开场白内容",
    "greeting_label": "开场白标签", "manifest_json": "清单 JSON",
    # 记忆
    "namespace": "命名空间", "memory_id": "记忆 ID",
    "resource_ref": "资源引用", "entry_id": "条目 ID", "query_tags": "查询标签",
    # 世界书
    "worldbook_json": "世界书 JSON", "worldbook_context": "世界书上下文",
    "enabled_only": "仅启用", "documents_json": "文档 JSON",
    # 管线
    "user_input": "玩家输入", "known_entities_json": "已知实体 JSON",
    "parsed_input_json": "解析结果 JSON", "character_profile_json": "角色档案 JSON",
    "scene_state_json": "场景状态 JSON", "worldbook_context_json": "世界书上下文 JSON",
    "memory_context": "记忆上下文", "memory_context_json": "记忆上下文 JSON",
    "preset_sections_json": "预设片段 JSON", "target_tokens": "目标 Token 数",
    "context_bundle_json": "上下文包 JSON", "context_json": "上下文 JSON",
    "context_mode": "上下文模式", "critic_review_json": "审查 JSON",
    "character_id": "角色 ID", "scene_id": "场景 ID",
    "quality_decision_json": "质量决策 JSON",
    "candidate_state_patch": "候选状态补丁",
    "candidate_memory_patch": "候选记忆补丁",
    "allow_commit_when_accepted": "接受时允许提交",
    "side_effect_decision_json": "副作用决策 JSON",
    # 预设
    "preset_id": "预设 ID", "rule_section": "规则分类", "rule_id": "规则 ID",
    "rule_content": "规则内容", "rule_priority": "规则优先级",
    "contract_json": "输出合约 JSON",
    # Agent
    "enable_agent_loop": "启用 Agent Loop（工具调用+子Agent派发）",
    "max_iterations": "最大迭代次数", "tool_ids": "可用工具",
    "skill_ids": "授予技能", "record_session": "记录会话",
    # 项目
    "project_id": "项目 ID", "project_type": "项目类型",
    "snapshot_type": "快照类型", "snapshot_id": "快照 ID",
    "narrative": "正文", "quality_json": "质量 JSON",
    "memory_candidates_json": "记忆候选 JSON", "node_id": "节点 ID",
    "node_type": "节点类型", "parent_id": "父节点 ID",
    "order_index": "排序索引", "snapshot_limit": "快照数量",
    # 技能
    "skill_id": "技能 ID", "label_zh": "中文名称", "label_en": "英文名称",
    "content_zh": "中文内容", "content_en": "英文内容",
    # 世界书激活（注意：activation 的候选值已是中文，见 COMBO_VALUES 注释）
    "activation": "激活方式", "mode": "模式",
    # MVU
    "ai_response": "AI 回复文本", "current_variables": "当前变量状态",
    "variables": "变量 JSON", "worldbook_index": "世界书索引 JSON",
    "enable_worldbook_match": "变量驱动世界书匹配",
    "enable_validation": "Schema 验证", "top_n_matches": "最多匹配条目数",
    "top_worldbook": "世界书匹配数", "var_diff": "上轮变量变更",
    "authors_note": "Author's Note", "character_note": "角色备注",
    "injection_rules_json": "注入规则 JSON", "project_root": "项目根目录",
    "chapter_num": "剧情合约章节号", "story_genre": "剧情合约类型",
    "from_index": "起始轮次", "vector_persist_dir": "向量持久化目录",
}

# combo 字段名 -> {英文候选值 -> 中文显示}
# 同名字段跨节点候选值不同时，中文译文必须全局唯一。
# 注意：AWPWorldbook.activation 的候选值已是中文（"常开"等），不在此处翻译，
# 反射逻辑会检测候选值含中文并整体跳过该 combo。
COMBO_VALUES = {
    "project_type": {"rp": "角色扮演", "novel": "小说", "all": "全部"},
    "snapshot_type": {"turn": "回合", "chapter": "章节", "manual": "手动"},
    "operation": {
        "list": "列表", "get": "获取", "add": "添加", "update": "更新",
        "delete": "删除", "view": "查看", "reroll_last": "重 Roll 最近一轮",
        "delete_from": "回退到指定轮", "query": "查询",
        "update_manifest": "更新角色清单", "update_greeting": "更新开场白",
        "add_greeting": "新增开场白", "add_rule": "新增规则",
        "remove_rule": "删除规则", "update_contract": "更新输出合约",
        "set_activation": "设置激活方式",
    },
    "node_type": {
        "volume": "卷", "chapter": "章节", "plot_point": "情节点",
        "foreshadow": "伏笔", "all": "全部",
    },
    "status": {
        "planned": "计划中", "writing": "写作中", "done": "已完成",
        "abandoned": "已放弃", "all": "全部",
    },
    "mode": {"select": "选择", "list": "列表"},
    "context_mode": {
        "full_context": "完整上下文", "no_memory": "无记忆",
        "stateless_no_context": "无状态（无上下文）",
    },
    "strategy": {
        "keyword": "关键词", "bm25": "BM25", "hybrid": "混合检索",
        "embedding": "向量嵌入", "hybrid_semantic": "混合语义",
    },
    "rule_section": {
        "coreRules": "核心规则", "styleRules": "风格规则",
        "additionalInstructions": "附加指令",
    },
}

# ComfyUI 核心菜单/搜索框英文项 -> 中文（尽力汉化用，可能随版本变化）
MENU_LABELS = {
    "Add Node": "添加节点", "Search": "搜索", "Search nodes": "搜索节点",
    "Save": "保存", "Load": "加载", "Refresh": "刷新", "Clear": "清空",
    "Clone": "克隆", "Remove": "删除", "Mute": "静音", "Bypass": "绕过",
    "Title": "标题", "Properties": "属性", "Help": "帮助", "Mode": "模式",
}
