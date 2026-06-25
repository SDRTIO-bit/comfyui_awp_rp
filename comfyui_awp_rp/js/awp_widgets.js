// AWP RP Plugin - 前端扩展
// 1. 汉化节点参数显示名
// 2. ComfyUI 设置面板：配置 LLM 供应商

const AWP_I18N_MAP = {
    "text": "文本", "json_text": "JSON文本", "validate_json": "验证JSON",
    "label": "标签", "pretty": "美化", "status": "状态", "content": "内容",
    "title": "标题", "name": "名称", "category": "分类", "limit": "数量上限",
    "priority": "优先级", "tags": "标签", "tags_any": "标签匹配",
    "type_filter": "类型过滤", "query": "查询", "operation": "操作",
    "data": "数据", "context": "上下文", "model": "模型", "provider": "供应商",
    "temperature": "温度", "max_tokens": "最大Token数", "profile": "档案",
    "strategy": "策略", "min_score": "最低分数", "filter_tags": "过滤标签",
    "filter_type": "过滤类型", "importance": "重要度", "entity_ids": "实体ID",
    "memory_type": "记忆类型", "summary": "摘要", "clear_session": "清除会话",
    "include_history": "包含历史", "dry_run": "试运行", "reply": "回复",
    "reply_rules": "回复规则", "task": "任务", "session_id": "会话ID",
    "card_id": "角色卡ID", "card_json": "角色卡JSON", "card_path": "角色卡路径",
    "greeting_id": "开场白ID", "greeting_content": "开场白内容",
    "greeting_label": "开场白标签", "manifest_json": "清单JSON",
    "namespace": "命名空间", "memory_id": "记忆ID",
    "resource_ref": "资源引用", "entry_id": "条目ID", "query_tags": "查询标签",
    "worldbook_json": "世界书JSON", "worldbook_context": "世界书上下文",
    "enabled_only": "仅启用", "documents_json": "文档JSON",
    "user_input": "玩家输入", "known_entities_json": "已知实体JSON",
    "parsed_input_json": "解析结果JSON", "character_profile_json": "角色档案JSON",
    "scene_state_json": "场景状态JSON", "worldbook_context_json": "世界书上下文JSON",
    "memory_context": "记忆上下文", "memory_context_json": "记忆上下文JSON",
    "preset_sections_json": "预设片段JSON", "target_tokens": "目标Token数",
    "context_bundle_json": "上下文包JSON", "context_json": "上下文JSON",
    "context_mode": "上下文模式", "critic_review_json": "审查JSON",
    "character_id": "角色ID", "scene_id": "场景ID",
    "quality_decision_json": "质量决策JSON",
    "candidate_state_patch": "候选状态补丁",
    "candidate_memory_patch": "候选记忆补丁",
    "allow_commit_when_accepted": "允许提交",
    "side_effect_decision_json": "副作用决策JSON",
    "preset_id": "预设ID", "rule_section": "规则分类", "rule_id": "规则ID",
    "rule_content": "规则内容", "rule_priority": "规则优先级",
    "contract_json": "合约JSON", "enable_agent_loop": "启用Agent循环",
    "max_iterations": "最大迭代次数", "tool_ids": "可用工具",
    "skill_ids": "授予技能", "record_session": "记录会话",
    "project_id": "项目ID", "project_type": "项目类型",
    "snapshot_type": "快照类型", "snapshot_id": "快照ID",
    "narrative": "正文", "quality_json": "质量JSON",
    "memory_candidates_json": "记忆候选JSON", "node_id": "节点ID",
    "node_type": "节点类型", "parent_id": "父节点ID",
    "order_index": "排序索引", "snapshot_limit": "快照数量",
    "skill_id": "技能ID", "label_zh": "中文名称", "label_en": "英文名称",
    "content_zh": "中文内容", "content_en": "英文内容",
    "activation": "激活方式", "mode": "模式",
    // 补充条目
    "ai_response": "AI回复文本", "current_variables": "当前变量状态",
    "variables": "变量JSON", "worldbook_index": "世界书索引JSON", 
    "enable_worldbook_match": "变量驱动世界书匹配",
    "enable_validation": "Schema验证", "top_n_matches": "最多匹配条目数",
    "top_worldbook": "世界书匹配数", "var_diff": "上轮变量变更",
    "authors_note": "Author's Note", "character_note": "角色备注",
    "injection_rules_json": "注入规则JSON", "project_root": "项目根目录",
    "chapter_num": "剧情合约章节号", "story_genre": "剧情合约类型",
    "from_index": "起始轮次", "vector_persist_dir": "向量持久化目录",
};

const AWP_INPUT_PORT_MAP = {
    "user_input": "玩家输入", "session_id": "会话ID", "card_id": "角色卡ID",
    "card_json": "角色卡JSON", "card_path": "角色卡路径",
    "namespace": "命名空间", "memory_id": "记忆ID",
    "resource_ref": "资源引用", "query": "查询",
    "documents_json": "文档JSON", "task": "任务", "context": "上下文",
    "data": "数据", "project_id": "项目ID", "summary": "摘要",
    "parsed_input_json": "解析结果JSON",
    "character_profile_json": "角色档案JSON",
    "scene_state_json": "场景状态JSON",
    "worldbook_context_json": "世界书上下文JSON",
    "worldbook_context": "世界书上下文", "memory_context": "记忆上下文",
    "memory_context_json": "记忆上下文JSON",
    "preset_sections_json": "预设片段JSON", "preset_id": "预设ID",
    "context_bundle_json": "上下文包JSON", "reply": "回复",
    "critic_review_json": "审查JSON",
    "quality_decision_json": "质量决策JSON",
    "candidate_state_patch": "候选状态补丁",
    "candidate_memory_patch": "候选记忆补丁",
    "side_effect_decision_json": "副作用决策JSON",
    "narrative": "正文", "context_json": "上下文JSON",
    "quality_json": "质量JSON", "memory_candidates_json": "记忆候选JSON",
    "tags_any": "标签匹配", "type_filter": "类型过滤",
    "greeting_id": "开场白ID", "worldbook_json": "世界书JSON",
    "json_text": "JSON文本", "text": "文本",
    // 补充
    "ai_response": "AI回复文本", "current_variables": "当前变量状态",
    "variables": "变量JSON", "worldbook_index": "世界书索引JSON",
    "var_diff": "上轮变量变更", "authors_note": "Author's Note",
    "character_note": "角色备注", "injection_rules_json": "注入规则JSON",
    "project_root": "项目根目录", "known_entities_json": "已知实体JSON",
    "manifest_json": "清单JSON", "greeting_content": "开场白内容",
    "skill_id": "技能ID", "skill_ids": "授予技能",
};

// ============ Combo（下拉选项）翻译映射 ============
// key: 内部英文值（传给 Python） → value: 前端显示中文
const AWP_COMBO_MAP = {
    "project_type": { "rp": "角色扮演", "novel": "小说" },
    "snapshot_type": { "turn": "回合", "chapter": "章节", "manual": "手动" },
    "operation": {
        "list": "列表", "get": "获取", "add": "添加", "update": "更新", "delete": "删除",
        "view": "查看", "reroll_last": "重Roll最近一轮", "delete_from": "回退到指定轮",
        "query": "查询", "update_manifest": "更新角色清单", "update_greeting": "更新开场白",
        "add_greeting": "新增开场白", "add_rule": "新增规则", "remove_rule": "删除规则",
        "update_contract": "更新输出合约", "set_activation": "设置激活方式",
    },
    "node_type": { "volume": "卷", "chapter": "章节", "plot_point": "情节点", "foreshadow": "伏笔", "all": "全部" },
    "status": { "planned": "计划中", "writing": "写作中", "done": "已完成", "abandoned": "已放弃", "all": "全部" },
    "mode": { "select": "选择", "list": "列表" },
    "context_mode": { "full_context": "完整上下文", "no_memory": "无记忆", "stateless_no_context": "无状态（无上下文）" },
    "strategy": { "keyword": "关键词", "bm25": "BM25", "hybrid": "混合检索", "embedding": "向量嵌入", "hybrid_semantic": "混合语义" },
    "rule_section": { "coreRules": "核心规则", "styleRules": "风格规则", "additionalInstructions": "附加指令" },
    "check_type": { "all": "全部检查", "format": "格式检查", "player_agency": "玩家代理", "knowledge_leak": "知识泄露" },
    "narrative_pacing": { "slow": "慢节奏", "normal": "正常", "fast": "快节奏" },
    "decision": { "silent": "静默推进", "bg_mention": "背景提及", "intervene": "主动介入" },
};

// ============ 汉化扩展（widget 标签 + combo 选项 + input port 标签） ============
app.registerExtension({
    name: "awp.rp.i18n",
    nodeCreated(node) {
        if (!node.comfyClass || !node.comfyClass.startsWith("AWP")) return;
        if (node.widgets) {
            for (const widget of node.widgets) {
                // 1. 翻译 widget 显示标签
                const zhLabel = AWP_I18N_MAP[widget.name];
                if (zhLabel) widget.label = zhLabel;

                // 2. 翻译 combo 下拉选项显示值（保持内部值为英文）
                if ((widget.type === "combo" || widget.options?.values) && widget.options?.values?.length) {
                    const transMap = AWP_COMBO_MAP[widget.name];
                    if (transMap) {
                        const originalValues = widget.options.values.slice();
                        const reverseMap = {};
                        const translatedValues = originalValues.map(function (v) {
                            const t = transMap[v] || v;
                            reverseMap[t] = v;
                            return t;
                        });

                        // 替换显示值
                        widget.options.values = translatedValues;

                        // 拦截 callback：选择中文选项后，内部值保持英文
                        const origCallback = widget.callback;
                        widget.callback = function (displayValue) {
                            const engValue = reverseMap[displayValue] || displayValue;
                            // 静默修正内部值为英文 key
                            this.value = engValue;
                            if (origCallback) origCallback.call(this, engValue);
                        };
                    }
                }
            }
        }
        if (node.inputs) {
            for (const input of node.inputs) {
                const zh = AWP_INPUT_PORT_MAP[input.name];
                if (zh) input.label = zh;
            }
        }
    },
});

// ============ 供应商设置面板 ============
const PROVIDER_SETTINGS = [
    { id: "deepseek", label: "DeepSeek", baseUrl: "https://api.deepseek.com/v1", model: "deepseek-chat" },
    { id: "openai", label: "OpenAI", baseUrl: "https://api.openai.com/v1", model: "gpt-4.1-mini" },
    { id: "glm", label: "智谱 GLM", baseUrl: "https://open.bigmodel.cn/api/paas/v4", model: "glm-4-flash" },
];

async function awpFetchProviders() {
    try {
        const r = await fetch("/awp/providers");
        return await r.json();
    } catch (e) {
        return {};
    }
}

async function awpSaveProvider(pid, data) {
    try {
        const body = {};
        body[pid] = data;
        await fetch("/awp/providers", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
    } catch (e) {
        console.warn("[AWP] 配置保存失败:", e);
    }
}

async function awpDeleteProvider(pid) {
    try {
        await fetch("/awp/providers/" + pid, { method: "DELETE" });
    } catch (e) {
        console.warn("[AWP] 删除失败:", e);
    }
}

app.registerExtension({
    name: "awp.rp.settings",
    async setup() {
        if (!app.ui || !app.ui.settings) {
            setTimeout(function () {
                var ext = app.extensions.find(function (e) { return e.name === "awp.rp.settings"; });
                if (ext && ext.setup) ext.setup();
            }, 500);
            return;
        }

        var providers = await awpFetchProviders();

        for (var i = 0; i < PROVIDER_SETTINGS.length; i++) {
            var pdef = PROVIDER_SETTINGS[i];
            var existing = providers[pdef.id] || {};

            app.ui.settings.addSetting({
                id: "AWP." + pdef.id + ".Enabled",
                name: pdef.label + " — 启用",
                type: "boolean",
                defaultValue: !!(existing.has_key || existing.base_url),
                onChange: function (pid) {
                    return async function (value) {
                        if (!value) await awpDeleteProvider(pid);
                    };
                }(pdef.id),
            });

            app.ui.settings.addSetting({
                id: "AWP." + pdef.id + ".Key",
                name: pdef.label + " — API Key",
                type: "text",
                defaultValue: "",
                attrs: { placeholder: "sk-... (留空不修改)" },
                onChange: function (pid, baseUrl, model) {
                    return async function (value) {
                        if (value) {
                            await awpSaveProvider(pid, {
                                api_key: value,
                                base_url: baseUrl,
                                default_model: model,
                            });
                        }
                    };
                }(pdef.id, pdef.baseUrl, pdef.model),
            });

            app.ui.settings.addSetting({
                id: "AWP." + pdef.id + ".URL",
                name: pdef.label + " — 接口地址",
                type: "text",
                defaultValue: existing.base_url || pdef.baseUrl,
                onChange: function (pid) {
                    return async function (value) {
                        if (value) await awpSaveProvider(pid, { base_url: value });
                    };
                }(pdef.id),
            });

            app.ui.settings.addSetting({
                id: "AWP." + pdef.id + ".Model",
                name: pdef.label + " — 默认模型",
                type: "text",
                defaultValue: existing.default_model || pdef.model,
                onChange: function (pid) {
                    return async function (value) {
                        if (value) await awpSaveProvider(pid, { default_model: value });
                    };
                }(pdef.id),
            });
        }

        // 自定义供应商
        app.ui.settings.addSetting({
            id: "AWP.Custom.ID",
            name: "自定义供应商 — ID (小写英文)",
            type: "text",
            defaultValue: "",
            attrs: { placeholder: "例如: groq, together" },
        });

        app.ui.settings.addSetting({
            id: "AWP.Custom.Key",
            name: "自定义供应商 — API Key",
            type: "text",
            defaultValue: "",
            attrs: { placeholder: "sk-..." },
        });

        app.ui.settings.addSetting({
            id: "AWP.Custom.URL",
            name: "自定义供应商 — 接口地址",
            type: "text",
            defaultValue: "",
            attrs: { placeholder: "https://api.example.com/v1" },
        });

        app.ui.settings.addSetting({
            id: "AWP.Custom.Model",
            name: "自定义供应商 — 模型名",
            type: "text",
            defaultValue: "",
            attrs: { placeholder: "model-name" },
        });

        app.ui.settings.addSetting({
            id: "AWP.Custom.Add",
            name: "点击注册自定义供应商 (填好上方4项后点击)",
            type: "boolean",
            defaultValue: false,
            onChange: async function () {
                var idEl = document.getElementById("AWP.Custom.ID");
                var keyEl = document.getElementById("AWP.Custom.Key");
                var urlEl = document.getElementById("AWP.Custom.URL");
                var modelEl = document.getElementById("AWP.Custom.Model");
                if (!idEl || !keyEl || !urlEl || !modelEl) return;
                var pid = idEl.value.trim().toLowerCase();
                var key = keyEl.value.trim();
                var url = urlEl.value.trim();
                var model = modelEl.value.trim();
                if (!pid || !key || !url) {
                    alert("请填写：ID、API Key 和接口地址");
                    return;
                }
                await awpSaveProvider(pid, { api_key: key, base_url: url, default_model: model || "" });
                alert("供应商 \"" + pid + "\" 已保存。重启 ComfyUI 后生效。");
                idEl.value = "";
                keyEl.value = "";
                urlEl.value = "";
                modelEl.value = "";
                document.getElementById("AWP.Custom.Add").checked = false;
            },
        });
    },
});

console.log("[AWP RP] 扩展已加载 (汉化 + 设置面板)");
