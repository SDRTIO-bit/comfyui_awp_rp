// AWP RP Plugin - 前端扩展
// 1. 汉化节点参数显示名 / combo 显示值 / 输入端口标签（显示层）
//    内部协议（字段名、枚举保存值、端口 id、连线）保持英文原样。
// 2. ComfyUI 设置面板：配置 LLM 供应商

// ============ 兜底映射表 ============
// 当 /awp/i18n 端点不可用（离线 / 启动早期 / 非 ComfyUI 环境）时使用。
// 与 Python 端 labels_zh.py 保持精简同步。
var AWP_FALLBACK = {
    widgetLabels: {
        "text": "文本", "json_text": "JSON 文本", "validate_json": "验证 JSON",
        "label": "标签", "pretty": "美化输出", "status": "状态", "content": "内容",
        "title": "标题", "name": "名称", "category": "分类", "limit": "数量上限",
        "priority": "优先级", "tags": "标签", "tags_any": "标签匹配",
        "type_filter": "类型过滤", "query": "查询", "operation": "操作",
        "data": "数据", "context": "上下文", "model": "模型", "provider": "供应商",
        "temperature": "温度", "max_tokens": "最大 Token 数", "profile": "档案",
        "strategy": "检索策略", "session_id": "会话 ID", "card_id": "角色卡 ID",
        "user_input": "玩家输入", "current_variables": "当前变量状态",
        "worldbook_context": "世界书上下文", "memory_context": "记忆上下文",
        "preset_id": "预设 ID", "context_mode": "上下文模式"
    },
    combos: {
        "context_mode": { "full_context": "完整上下文", "no_memory": "无记忆", "stateless_no_context": "无状态（无上下文）" },
        "strategy": { "keyword": "关键词", "bm25": "BM25", "hybrid": "混合检索", "embedding": "向量嵌入", "hybrid_semantic": "混合语义" },
        "operation": { "list": "列表", "get": "获取", "add": "添加", "update": "更新", "delete": "删除", "view": "查看", "query": "查询" }
    },
    portLabels: {
        "user_input": "玩家输入", "session_id": "会话 ID", "card_id": "角色卡 ID",
        "worldbook_context": "世界书上下文", "memory_context": "记忆上下文",
        "current_variables": "当前变量状态", "documents_json": "文档 JSON",
        "worldbook_json": "世界书 JSON", "result": "结果", "output": "输出",
        "metadata": "元数据"
    },
    menuLabels: {}
};

// ============ 运行时 i18n 清单（fetch 后填充，失败用兜底表） ============
var AWP_I18N = null;

async function awpLoadI18n() {
    try {
        var r = await fetch("/awp/i18n");
        if (!r.ok) throw new Error("HTTP " + r.status);
        AWP_I18N = await r.json();
    } catch (e) {
        console.warn("[AWP] i18n 清单加载失败，使用兜底表:", e);
        AWP_I18N = AWP_FALLBACK;
    }
}

function awpGet(field) {
    // 若清单已加载则用之，否则用兜底表
    var src = AWP_I18N || AWP_FALLBACK;
    return src[field] || {};
}

// ============ 汉化扩展：widget 标签 + combo 显示值 + 输入端口标签 ============
app.registerExtension({
    name: "awp.rp.i18n",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        // 节点创建前确保清单已加载（首次加载触发一次 fetch）
        if (!AWP_I18N) {
            await awpLoadI18n();
        }
    },
    nodeCreated(node) {
        if (!node.comfyClass || !node.comfyClass.startsWith("AWP")) return;

        // widget 标签 + combo 显示值
        if (node.widgets) {
            var widgetLabels = awpGet("widgetLabels");
            var combos = awpGet("combos");
            for (var i = 0; i < node.widgets.length; i++) {
                var widget = node.widgets[i];

                // 1. 翻译 widget 显示标签（不动 widget.name）
                var zhLabel = widgetLabels[widget.name];
                if (zhLabel) widget.label = zhLabel;

                // 2. 翻译 combo 下拉选项显示值（保持内部值为英文）
                if ((widget.type === "combo" || (widget.options && widget.options.values)) &&
                    widget.options && widget.options.values && widget.options.values.length) {
                    var transMap = combos[widget.name];
                    if (transMap) {
                        var originalValues = widget.options.values.slice();
                        var reverseMap = {};
                        var translatedValues = originalValues.map(function (v) {
                            // 候选值已是中文则不翻译（如 worldbook.activation），保持原样
                            var t = transMap[v] || v;
                            reverseMap[t] = v;
                            return t;
                        });

                        // 替换显示值
                        widget.options.values = translatedValues;

                        // 拦截 callback：选择中文选项后，内部值保持英文 key
                        var origCallback = widget.callback;
                        widget.callback = function (displayValue) {
                            var engValue = reverseMap[displayValue] || displayValue;
                            this.value = engValue;            // 内部值保持英文
                            if (origCallback) origCallback.call(this, engValue);
                        };
                    }
                }
            }
        }

        // 输入端口标签（不动 input.name / handle id）
        if (node.inputs) {
            var portLabels = awpGet("portLabels");
            for (var j = 0; j < node.inputs.length; j++) {
                var input = node.inputs[j];
                var zh = portLabels[input.name];
                if (zh) input.label = zh;
            }
        }
    },
});


// ============ 核心菜单尽力汉化（脆弱层，失败静默回退英文） ============
// ComfyUI 核心渲染的搜索框 placeholder、部分右键菜单项等不在 nodeCreated
// 覆盖范围，用 DOM 文本替换尽力汉化。随 ComfyUI 版本可能失效，包 try/catch。
(function awpMenuI18n() {
    function hasCJK(s) { return /[一-鿿]/.test(s); }

    function translateMenuLabels() {
        var menuLabels = awpGet("menuLabels");
        if (!menuLabels) return;
        try {
            // 搜索框 placeholder
            var searchInputs = document.querySelectorAll(
                'input[placeholder], .litegraph input, .comfy-vue input[placeholder]'
            );
            for (var i = 0; i < searchInputs.length; i++) {
                var el = searchInputs[i];
                var p = el.getAttribute("placeholder");
                if (p && menuLabels[p]) el.setAttribute("placeholder", menuLabels[p]);
            }

            // 右键菜单 / 节点库列表项文本
            var candidates = document.querySelectorAll(
                '.litecontextmenu .menu-entry, .context-menu .menu-entry, .comfy-vue .context-menu-item'
            );
            for (var j = 0; j < candidates.length; j++) {
                var item = candidates[j];
                var txt = (item.textContent || "").trim();
                // 仅翻译整段匹配且不含中文的英文菜单项
                if (txt && !hasCJK(txt) && menuLabels[txt]) {
                    item.textContent = menuLabels[txt];
                }
            }
        } catch (e) {
            // 静默回退：菜单保持英文，不影响功能
        }
    }

    // 菜单是动态生成的，用 MutationObserver 监听 DOM 变化重译
    try {
        var observer = new MutationObserver(function () { translateMenuLabels(); });
        observer.observe(document.body, { childList: true, subtree: true });
        // 首次也译一次
        document.addEventListener("DOMContentLoaded", translateMenuLabels);
        setTimeout(translateMenuLabels, 1000);
    } catch (e) {
        console.warn("[AWP] 菜单汉化补丁初始化失败:", e);
    }
})();

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
