export const createExecutors = async (context) => ({
  rpInputParser: async ({ node, inputs }) => {
    const text = String(inputs.text ?? "");
    if (!text.trim()) {
      return {
        outputs: {
          parsed: {
            speech: "",
            action: "",
            intent: "",
            emotion: "",
            entities: [],
            triggers: [],
          },
        },
        metadata: { pluginId: "awp.rp-core" },
      };
    }

    const result = await context.executeAgent({
      nodeId: node.id,
      config: {
        systemPrompt: String(node.config.parseRules ?? "分析玩家输入，提取结构化信息。"),
        skills: [],
        plugins: [],
        outputType: "json",
      },
      inputs: { text },
    });

    try {
      const parsed = JSON.parse(result.text);
      return {
        outputs: {
          parsed: {
            speech: String(parsed.speech ?? ""),
            action: String(parsed.action ?? ""),
            intent: String(parsed.intent ?? ""),
            emotion: String(parsed.emotion ?? ""),
            entities: Array.isArray(parsed.entities) ? parsed.entities.map(String) : [],
            triggers: Array.isArray(parsed.triggers) ? parsed.triggers.map(String) : [],
          },
        },
        metadata: { ...result.metadata, pluginId: "awp.rp-core" },
      };
    } catch {
      return {
        outputs: {
          parsed: {
            speech: text,
            action: "",
            intent: "",
            emotion: "",
            entities: [],
            triggers: [],
          },
        },
        metadata: { pluginId: "awp.rp-core", parseFallback: true },
      };
    }
  },

  rpContextAssembler: async ({ node, inputs }) => {
    const template = String(
      node.config.assemblyTemplate ??
        "{character}\n\n{scene}\n\n{worldbook}\n\n{memory}\n\n{parsed}",
    );

    const formatValue = (key, value) => {
      if (value === undefined || value === null || value === "") return `[${key} 暂未提供]`;
      if (typeof value === "object") return JSON.stringify(value, null, 2);
      return String(value);
    };

    const context = template
      .replace(/\{character\}/g, formatValue("角色卡", inputs.character))
      .replace(/\{scene\}/g, formatValue("场景", inputs.scene))
      .replace(/\{worldbook\}/g, formatValue("世界书", inputs.worldbook))
      .replace(/\{memory\}/g, formatValue("记忆", inputs.memory))
      .replace(/\{parsed\}/g, formatValue("解析输入", inputs.parsed));

    const maxTokens = Number(node.config.maxTokens ?? 2000);
    const truncated =
      context.length > maxTokens * 4
        ? context.slice(0, maxTokens * 4) + "\n\n[上下文已截断]"
        : context;

    return {
      outputs: { context: truncated },
      metadata: {
        pluginId: "awp.rp-core",
        contextLength: context.length,
        truncated: context.length > maxTokens * 4,
      },
    };
  },

  worldbookSearch: async ({ node, inputs }) => {
    const entries = await context.readWorldbook();
    const query = String(inputs.query ?? node.config.query ?? "");
    const results = context.rankEntries(query, entries, Number(node.config.limit ?? 4));

    return {
      outputs: {
        results: context.serializeEntries(results),
      },
      metadata: {
        pluginId: "awp.rp-core",
        matchedWorldbookIds: results.map((entry) => entry.id),
        matchedWorldbookTitles: results.map((entry) => entry.title),
        views: [
          {
            id: "worldbook_hits",
            kind: "entry-list",
            title: "命中世界书条目",
            items: results.map((entry) => ({
              id: entry.id,
              title: entry.title,
              summary: String(entry.content ?? "").slice(0, 120),
              tags: entry.tags,
            })),
          },
          {
            id: "search_stats",
            kind: "stats",
            title: "检索统计",
            pairs: [
              { label: "检索词", value: query || "(空)" },
              { label: "命中数", value: results.length },
              { label: "条目总数", value: entries.length },
            ],
          },
        ],
      },
    };
  },

  memoryRecall: async ({ node, inputs }) => {
    const entries = await context.readMemories();
    const query = String(inputs.query ?? node.config.query ?? "");
    const results = context.rankEntries(query, entries, Number(node.config.limit ?? 4));

    return {
      outputs: {
        memories: context.serializeEntries(results),
      },
      metadata: {
        pluginId: "awp.rp-core",
        matchedMemoryIds: results.map((entry) => entry.id),
        matchedMemoryTitles: results.map((entry) => entry.title),
        views: [
          {
            id: "memory_hits",
            kind: "entry-list",
            title: "命中记忆条目",
            items: results.map((entry) => ({
              id: entry.id,
              title: entry.title,
              summary: String(entry.content ?? "").slice(0, 120),
              tags: entry.tags,
            })),
          },
          {
            id: "memory_stats",
            kind: "stats",
            title: "检索统计",
            pairs: [
              { label: "检索词", value: query || "(空)" },
              { label: "命中数", value: results.length },
              { label: "记忆总数", value: entries.length },
            ],
          },
        ],
      },
    };
  },

  rpCharacterCard: async ({ node, inputs }) => ({
    outputs: {
      profile: {
        name: node.config.name,
        persona: node.config.persona,
        voice: node.config.voice,
        boundaries: node.config.boundaries,
        seed: inputs.seed,
      },
    },
    metadata: { pluginId: "awp.rp-core" },
  }),

  rpSceneState: async ({ node, inputs }) => ({
    outputs: {
      state: {
        location: node.config.location,
        mood: node.config.mood,
        stakes: node.config.stakes,
        setup: inputs.setup,
        lore: inputs.lore,
      },
    },
    metadata: { pluginId: "awp.rp-core" },
  }),

  rpDialogueDirector: async ({ node, inputs }) => {
    const result = await context.executeAgent({
      nodeId: node.id,
      config: {
        systemPrompt: [
          "你是 RP 角色扮演对话导演。",
          "必须根据 character、scene、player、memory 输入生成沉浸式中文 RP 回复。",
          "只扮演 NPC 和环境，不替玩家决定行动。",
          "优先遵守角色卡、人设边界、世界书事实和记忆库中的既有关系。",
          String(node.config.replyRules ?? ""),
        ].join("\n"),
        skills: Array.isArray(node.config.skills)
          ? node.config.skills.map(String)
          : ["rp_persona", "rp_player_agency", "rp_continuity", "rp_slow_burn"],
        plugins: Array.isArray(node.config.plugins)
          ? node.config.plugins.map(String)
          : ["worldbook_read", "rp_memory_read"],
        outputType: "draft",
      },
      inputs,
    });

    return {
      outputs: { reply: result.text },
      metadata: { ...result.metadata, pluginId: "awp.rp-core" },
    };
  },

  rpMemoryWrite: async ({ node, inputs }) => {
    const reply = String(inputs.reply ?? "");
    const notes = String(inputs.notes ?? "");
    const parsed = inputs.parsed;
    const memoryTypes = Array.isArray(node.config.memoryTypes)
      ? node.config.memoryTypes.map(String)
      : ["relationship", "preference", "promise", "lore", "hook"];

    if (!reply.trim() && !notes.trim()) {
      return {
        outputs: { candidates: [] },
        metadata: { pluginId: "awp.rp-core", emptyInput: true },
      };
    }

    const result = await context.executeAgent({
      nodeId: node.id,
      config: {
        systemPrompt: [
          "你是 RP 记忆管理助手。分析本轮角色扮演对话，提取值得写入长期记忆的内容。",
          "",
          `启用的记忆类型：${memoryTypes.join("、")}`,
          "",
          "类型说明：",
          "- relationship: 角色之间的关系变化（信任度、亲密感、敌意等）",
          "- preference: 玩家表现出的偏好、习惯或风格",
          "- promise: 角色做出的承诺或约定",
          "- lore: 新揭示的世界观设定或角色背景",
          "- hook: 未解决的伏笔或悬念",
          "",
          "输出格式：严格的 JSON 数组，每个元素包含 type、title、content、tags、priority(1-5)。",
          `最多输出 ${Number(node.config.maxCandidates ?? 5)} 条。`,
          "如果本轮没有值得记录的变化，输出空数组 []。",
        ].join("\n"),
        skills: [],
        plugins: [],
        outputType: "json",
      },
      inputs: {
        reply,
        notes,
        parsed: parsed ? JSON.stringify(parsed) : "",
      },
    });

    try {
      const candidates = JSON.parse(result.text);
      const filtered = (Array.isArray(candidates) ? candidates : [])
        .filter((c) => c && typeof c === "object" && memoryTypes.includes(String(c.type ?? "")))
        .slice(0, Number(node.config.maxCandidates ?? 5))
        .map((c) => ({
          type: String(c.type ?? "lore"),
          title: String(c.title ?? "").slice(0, 120),
          content: String(c.content ?? "").slice(0, 500),
          tags: Array.isArray(c.tags) ? c.tags.map(String) : [],
          priority: Math.max(1, Math.min(5, Number(c.priority ?? 3))),
        }));

      return {
        outputs: { candidates: filtered },
        metadata: {
          ...result.metadata,
          pluginId: "awp.rp-core",
          candidateCount: filtered.length,
        },
      };
    } catch {
      return {
        outputs: { candidates: [] },
        metadata: { pluginId: "awp.rp-core", parseError: true },
      };
    }
  },

  rpContinuityCheck: async ({ node, inputs }) => {
    const result = await context.executeAgent({
      nodeId: node.id,
      config: {
        model: "mock-pro",
        systemPrompt: `检查 RP 草稿是否保持人设、场景事实、关系连续性和玩家行动权。严格度：${String(
          node.config.strictness ?? "medium",
        )}`,
        skills: Array.isArray(node.config.skills)
          ? node.config.skills.map(String)
          : ["rp_player_agency", "rp_continuity"],
        plugins: [],
        outputType: "analysis",
      },
      inputs,
    });

    return {
      outputs: { notes: result.text },
      metadata: { ...result.metadata, pluginId: "awp.rp-core" },
    };
  },
});
