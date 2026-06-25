"""
Main Agent Node — The orchestrator for RP/novel workflows.

The main agent runs an agent loop: it can call tools (memory, worldbook,
retrieval, etc.), invoke skills, and delegate sub-tasks to sub-agents.
This is the "agent" path; the existing RP pipeline nodes
(InputParser → ContextAssembler → DialogueDirector) remain as the
"direct" path. Both paths coexist.
"""

import json
import re
from typing import Any

from ..core.llm_router import LlmRouter, create_default_router
from ..core.config import get_config, initialize_config
from ..core.types import LlmTokenUsage
from ..memory.short_term import AgentSessionManager
from ..profile.profile import ProfileManager
from ..preset.preset import PresetManager
from ..tools.registry import get_global_registry
from ..tools.skill_manager import SkillManager
from ..tools.tool_executor import ToolExecutor
from ..tools.tool_executor import should_parallelize


class AWPMainAgent:
    """主 Agent 节点 —— 编排 RP/小说工作流。"""

    @classmethod
    def INPUT_TYPES(cls):
        config = get_config()
        providers = list(config.providers.keys()) if config.providers else ["deepseek"]

        profile_manager = ProfileManager()
        profiles = [p["id"] for p in profile_manager.list_profiles()]

        skill_manager = SkillManager()
        skill_ids = skill_manager.list_skill_ids()

        # Get available tool names from the registry
        registry = get_global_registry()
        tool_names = registry.list_names()

        return {
            "required": {
                "user_input": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "输入玩家操作、对话或写作任务...",
                    "forceInput": True,
                }),
                "session_id": ("STRING", {
                    "default": "default",
                    "placeholder": "会话ID",
                    "forceInput": True,
                }),
            },
            "optional": {
                "provider": (providers, {"default": providers[0] if providers else "deepseek"}),
                "model": ("STRING", {"default": "deepseek-chat"}),
                "profile": (profiles, {"default": "rp-writer"}),
                "context_mode": (
                    ["full_context", "no_memory", "stateless_no_context"],
                    {"default": "full_context"},
                ),
                "record_session": ("BOOLEAN", {"default": True}),
                "worldbook_context": ("STRING", {"default": "", "forceInput": True}),
                "memory_context": ("STRING", {"default": "", "forceInput": True}),
                "preset_id": ("STRING", {"default": "rp-default-v1"}),
                "temperature": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.1}),
                "max_tokens": ("INT", {"default": 2048, "min": 100, "max": 8192}),
                # --- Agent loop parameters ---
                "enable_agent_loop": ("BOOLEAN", {
                    "default": False,
                    "label": "启用 Agent Loop（工具调用+子Agent派发）",
                }),
                "max_iterations": ("INT", {
                    "default": 5,
                    "min": 1,
                    "max": 20,
                    "label": "最大迭代次数",
                }),
                "tool_ids": ("STRING", {
                    "default": "",
                    "placeholder": "可用工具ID，逗号分隔（留空=全部）",
                    "label": "可用工具",
                }),
                "skill_ids": ("STRING", {
                    "default": "",
                    "placeholder": "技能ID，逗号分隔（留空=不注入技能）",
                    "label": "授予技能",
                }),
                # --- MVU variable state ---
                "current_variables": ("STRING", {
                    "default": "{}",
                    "forceInput": True,
                    "label": "当前变量状态（MVU）",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("回复", "会话上下文", "元数据", "更新后变量", "变更记录")
    FUNCTION = "execute"
    CATEGORY = "AWP RP"
    OUTPUT_NODE = True

    def execute(
        self,
        user_input: str,
        session_id: str,
        provider: str = "deepseek",
        model: str = "deepseek-chat",
        profile: str = "rp-writer",
        context_mode: str = "full_context",
        record_session: bool = True,
        worldbook_context: str = "",
        memory_context: str = "",
        preset_id: str = "rp-default-v1",
        temperature: float = 0.8,
        max_tokens: int = 2048,
        enable_agent_loop: bool = False,
        max_iterations: int = 5,
        tool_ids: str = "",
        skill_ids: str = "",
        current_variables: str = "{}",
    ):
        """Execute the main agent workflow.

        When ``enable_agent_loop`` is False (default), behaves as before:
        a single LLM call with assembled context. This preserves backward
        compatibility with existing workflows.

        When ``enable_agent_loop`` is True, runs a full agent loop:
        the LLM can call tools and delegate to sub-agents, iterating
        until it produces a final answer or hits max_iterations.
        """
        # Initialize router if needed
        config = get_config()
        if not config.providers:
            initialize_config(
                providers={
                    "deepseek": {
                        "api_key": "",
                        "base_url": "https://api.deepseek.com/v1",
                        "default_model": "deepseek-chat",
                    }
                },
                default_provider="deepseek",
            )
            config = get_config()

        router = create_default_router()

        # Get profile
        profile_manager = ProfileManager()
        agent_profile = profile_manager.get_profile(profile)

        if not agent_profile:
            return (
                f"Error: Profile '{profile}' not found",
                "{}",
                json.dumps({"error": "profile_not_found"}),
                current_variables,
                "{}",
            )

        # Resolve RP preset
        preset_manager = PresetManager()
        resolved_preset = preset_manager.resolve_preset(preset_id)
        preset_sections = resolved_preset.prompt_sections if resolved_preset else []

        # Load session context
        session_manager = AgentSessionManager()
        session_key = session_manager.create_key(
            tenant_id="default",
            workflow_instance_id="comfyui-rp",
            conversation_id=session_id,
            agent_node_id="main-agent",
        )

        history_turns, summary, truncated = session_manager.get_prompt_context(
            session_key,
            protected_tokens=500,
        )

        # Build system prompt
        system_prompt = agent_profile.foundational_system_prompt

        # Add preset sections
        preset_text = ""
        if preset_sections:
            preset_lines = [
                f"- {section.get('content', '')}"
                for section in sorted(
                    preset_sections,
                    key=lambda item: item.get("priority", 0),
                    reverse=True,
                )
                if section.get("content")
            ]
            if preset_lines:
                preset_text = "## RP Preset Rules\n" + "\n".join(preset_lines)

        # Add output contract
        contract_text = ""
        if resolved_preset and resolved_preset.output_contract:
            contract = resolved_preset.output_contract
            contract_lines = [
                f"mode: {contract.mode}",
                f"allow_extra_text: {contract.allow_extra_text}",
            ]
            if contract.forbidden_patterns:
                contract_lines.append("forbidden_patterns: " + ", ".join(contract.forbidden_patterns))
            contract_text = "## Output Contract\n" + "\n".join(contract_lines)

        # Add context (worldbook, memory, history) based on context_mode
        context_parts: list[str] = []
        if context_mode in ("full_context", "no_memory") and worldbook_context:
            context_parts.append(f"## World & Character Lore\n{worldbook_context}")

        if context_mode == "full_context" and memory_context:
            context_parts.append(f"## Long-term Memories\n{memory_context}")

        if context_mode == "full_context" and summary:
            context_parts.append(f"## Conversation Summary\n{summary}")

        if context_mode == "full_context" and history_turns:
            history_text = "\n\n".join([
                f"[Turn {t.turn_index}]\nUser: {t.input}\nAssistant: {t.assistant_output}"
                for t in history_turns[-5:]
            ])
            context_parts.append(f"## Recent Conversation\n{history_text}")

        context_text = "\n\n".join(context_parts) if context_parts else ""

        # Resolve skills (SkillManager always created for agent loop injection)
        skill_manager = SkillManager()
        skills_content = ""
        if skill_ids:
            sid_list = [s.strip() for s in skill_ids.split(",") if s.strip()]
            skills_content = skill_manager.resolve_skills_content(sid_list, "zh")

        # --- Build the full system message ---
        system_parts = [system_prompt]
        if preset_text:
            system_parts.append(preset_text)
        if contract_text:
            system_parts.append(contract_text)
        if skills_content:
            system_parts.append(skills_content)
        if context_text:
            system_parts.append(context_text)

        full_system = "\n\n".join(system_parts)

        # --- Agent loop path: always inject core agent skills ---
        if enable_agent_loop:
            agent_core_skills = skill_manager.resolve_skills_content(
                ["rp_thinking_flow", "hard_gates_full"], "zh"
            )
            if agent_core_skills:
                full_system = full_system + "\n\n" + agent_core_skills

        node_config = {
            "provider": provider,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # --- Choose execution path ---
        if not enable_agent_loop:
            # Legacy path: single LLM call (backward compatible)
            full_prompt = full_system + "\n\n" + f"## Current User Input\n{user_input}"
            try:
                text, token_usage, resolved_provider, resolved_model = router.complete_with_config(
                    node_config=node_config,
                    workflow_defaults=None,
                    prompt=full_prompt,
                )
            except Exception as e:
                return (
                    f"LLM Error: {str(e)}",
                    "{}",
                    json.dumps({"error": str(e)}),
                    "{}",
                    "{}",
                )

            should_record = bool(record_session and context_mode != "stateless_no_context")
            if should_record:
                session_manager.record_turn(
                    session_key,
                    input_data=user_input,
                    assistant_output=text,
                    model_config=node_config,
                    token_usage=token_usage,
                )

            metadata = {
                "provider": resolved_provider,
                "model": resolved_model,
                "profile": profile,
                "preset_id": preset_id,
                "context_mode": context_mode,
                "agent_loop": False,
                "token_usage": {"input": token_usage.input, "output": token_usage.output},
                "session_id": session_id,
                "turn_index": len(history_turns) + (1 if should_record else 0),
            }
            session_context = json.dumps({
                "session_id": session_id,
                "turn_count": len(history_turns) + (1 if should_record else 0),
            })
            return (text, session_context, json.dumps(metadata, ensure_ascii=False), current_variables, "{}")

        # --- Agent loop path ---
        registry = get_global_registry()

        # Filter tools by tool_ids parameter
        selected_tool_ids: list[str] | None = None
        if tool_ids:
            selected_tool_ids = [t.strip() for t in tool_ids.split(",") if t.strip()]

        # Available tools: all tools the agent is permitted to use
        available_tools = registry.get_for_permissions(
            permissions=None,  # No permission filtering at node level
            tool_ids=selected_tool_ids,
        )

        # Always include the delegate tool if agent loop is on
        delegate_tool = registry.get("delegate_to_sub_agent")
        if delegate_tool and (not selected_tool_ids or "delegate_to_sub_agent" in selected_tool_ids):
            if delegate_tool not in available_tools:
                available_tools.append(delegate_tool)

        llm_tools = registry.to_llm_definitions(available_tools) if available_tools else None
        executor = ToolExecutor(registry)

        # Build initial messages
        # Add a tool-usage引导 to the system message when tools are available
        loop_system = full_system
        if llm_tools:
            tool_names = [t.name for t in available_tools]
            loop_system = (
                full_system
                + "\n\n## 工具使用指引\n"
                + "你拥有以下工具可用：" + ", ".join(tool_names) + "\n"
                + "在回复前，请优先调用相关工具获取必要的上下文信息（如记忆、世界书、角色卡设定），"
                + "确保回复与既有设定和记忆一致。\n"
                + "如果需要专业审查、事实提取或参考书拆解，使用 delegate_to_sub_agent 委托子 Agent。\n"
                + "获取完所需信息后，再生成最终回复。不要跳过工具直接回答。"
            )

        # --- P5.3: Action Options instruction ---
        if profile == "rp-writer":
            loop_system += (
                "\n\n## 行动选项\n"
                + "每轮在回复末尾生成 3 个用户下一步行动选项，用 <options> 标签包裹。\n"
                + "格式：<options>\n<font color=\"#5a7a5a\">😏 选项一</font>\n"
                + "<font color=\"#b06a3d\">😈 选项二</font>\n"
                + "<font color=\"#5a8a9a\">🤔 选项三</font>\n</options>\n\n"
                + "选项规则：\n"
                + "- 紧密衔接前文，基于当前剧情自然延伸\n"
                + "- 3 个选项引导不同走向（试探/主动/回避，温情/玩闹/对抗）\n"
                + "- 每个选项 15-40 字，写具体动作或对白方向\n"
                + "- 选项前加 emoji（😏🥺😈🤔💀✨🔥😨）\n"
                + "- 颜色：温情=#5a7a5a 挑衅=#b06a3d 对抗=#b0624a 试探=#5a8a9a\n"
            )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": loop_system},
            {"role": "user", "content": user_input},
        ]

        # Agent loop
        iterations = 0
        final_text = ""
        total_input_tokens = 0
        total_output_tokens = 0
        tool_call_log: list[dict[str, Any]] = []
        last_result = None

        # --- P5.4: Token budget management ---
        MAX_CONTEXT_TOKENS = 8000
        PROTECTED_TOKENS = 1500  # Reserve for system prompt + output

        while iterations < max_iterations:
            iterations += 1

            # Trim messages if exceeding token budget
            estimated_ctx = sum(len(str(m.get("content", ""))) // 4 for m in messages)
            if estimated_ctx > MAX_CONTEXT_TOKENS - PROTECTED_TOKENS:
                # Keep system message + truncate from front (oldest non-system)
                system_msg = messages[0] if messages else None
                # Drop oldest messages until under budget, but keep last 3 exchanges
                while len(messages) > 7 and estimated_ctx > MAX_CONTEXT_TOKENS - PROTECTED_TOKENS:
                    # Skip system and first user
                    if messages[0]["role"] == "system":
                        del messages[1]  # Remove oldest non-system
                    else:
                        del messages[0]
                    estimated_ctx = sum(len(str(m.get("content", ""))) // 4 for m in messages)
                # Re-insert system if removed
                if system_msg and messages[0]["role"] != "system":
                    messages.insert(0, system_msg)

            try:
                result, resolved_provider, resolved_model = router.complete_with_tools(
                    node_config=node_config,
                    messages=messages,
                    tools=llm_tools,
                    tool_choice="auto" if llm_tools else None,
                )
            except Exception as exc:
                return (
                    f"LLM Error in agent loop (iteration {iterations}): {exc}",
                    "{}",
                    json.dumps({"error": str(exc), "iterations": iterations}),
                    current_variables,
                    "{}",
                )

            last_result = result
            total_input_tokens += result.token_usage.input
            total_output_tokens += result.token_usage.output

            # Append assistant message to conversation
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": result.text}
            if result.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in result.tool_calls
                ]
            messages.append(assistant_msg)

            if not result.has_tool_calls:
                # Agent is done
                final_text = result.text
                break

            # Execute tool calls
            for tc in result.tool_calls:
                tool_call_log.append({
                    "iteration": iterations,
                    "tool": tc.name,
                    "arguments": tc.arguments[:200] if tc.arguments else "",
                })

            tool_results = executor.execute_calls_parallel(result.tool_calls) if len(result.tool_calls) > 1 and should_parallelize(result.tool_calls) else executor.execute_calls(result.tool_calls)
            messages.extend(tool_results)
        else:
            # Reached max_iterations
            final_text = (last_result.text if last_result else "") + "\n\n[Agent reached max iterations]"

        # --- Agent self-reflection: quality check + auto-retry ---
        reflection_attempts = 0
        max_reflections = 2
        reflection_log: list[dict[str, Any]] = []

        while reflection_attempts < max_reflections:
            # Run deterministic quality gate on output
            from ..rp_pipeline import apply_quality_gate
            gate_result = apply_quality_gate(final_text)
            failed = [i for i in gate_result.get("issues", []) if i.get("severity") == "error"]

            if not failed:
                break  # Passed — accept

            reflection_attempts += 1
            failed_codes = [f.get("code") for f in failed]
            suggestion = "、".join(f.get("suggestion", "") for f in failed if f.get("suggestion"))

            reflection_log.append({
                "attempt": reflection_attempts,
                "failed_checks": failed_codes,
                "suggestion": suggestion,
            })

            # Build revision feedback and append as a new user message
            revision_prompt = (
                f"## 质量门禁未通过\n"
                f"失败项：{'、'.join(failed_codes)}\n"
                f"修订指引：{suggestion}\n\n"
                f"请修改以上回复，确保通过所有质量检查。只输出修订后的叙事文本，不要输出分析。"
            )
            messages.append({"role": "user", "content": revision_prompt})

            # One more LLM call to revise
            try:
                revise_result, _, _ = router.complete_with_tools(
                    node_config=node_config,
                    messages=messages,
                    tools=llm_tools,
                    tool_choice="auto" if llm_tools else None,
                )
                final_text = revise_result.text
                total_input_tokens += revise_result.token_usage.input
                total_output_tokens += revise_result.token_usage.output
            except Exception:
                break  # Revision failed — keep current text

        # Record session
        should_record = bool(record_session and context_mode != "stateless_no_context")
        if should_record:
            combined_usage = LlmTokenUsage(
                input=total_input_tokens,
                output=total_output_tokens,
            )
            session_manager.record_turn(
                session_key,
                input_data=user_input,
                assistant_output=final_text,
                model_config=node_config,
                token_usage=combined_usage,
            )

        # --- P5.1: Story planning hook ---
        story_plan_result: dict[str, Any] | None = None
        current_turn = len(history_turns) + (1 if should_record else 0)
        PLAN_INTERVAL = 8

        if enable_agent_loop and current_turn > 1 and current_turn % PLAN_INTERVAL == 0:
            try:
                # Build story planning context
                plan_context = f"Session: {session_id} (Turn {current_turn})\n"
                plan_context += f"Recent output summary: {final_text[:300]}...\n" if len(final_text) > 300 else f"Recent output: {final_text}\n"

                # Add NPC scan results if available
                npc_mentions = [tc for tc in tool_call_log if tc.get("tool") == "npc_activity_scan"]
                if npc_mentions:
                    plan_context += f"NPC activity scan performed: {len(npc_mentions)} times\n"

                plan_task = (
                    f"## 剧情规划分析 — 第 {current_turn} 轮\n\n"
                    "你是剧情导演。基于以下上下文完成叙事健康检查：\n\n"
                    f"{plan_context}\n\n"
                    "请分析：\n"
                    "1. 当前定位：故事处于什么阶段？\n"
                    "2. 价值转换：最近几轮的情感/关系变化？\n"
                    "3. 未落地伏笔：哪些线索需要回收？\n"
                    "4. 下阶段方向：接下来3-5轮的建议方向\n"
                    "5. 情感波浪线：当前情绪位置和走向\n"
                    "6. 节拍进度：当前处于什么叙事节拍？\n\n"
                    "输出一段结构化分析报告。框架服务于故事，不强制套用。"
                )

                from ..tools.builtin.delegate_tool import _run_sub_agent
                plan_output = _run_sub_agent(
                    profile_id="novel-context-agent",
                    task=plan_task,
                    context=plan_context,
                    max_iterations=2,
                )
                story_plan_result = {
                    "turn": current_turn,
                    "plan": plan_output[:1000],
                    "triggered": True,
                }
            except Exception:
                story_plan_result = {"triggered": False, "error": "Story planning sub-agent failed"}

        # --- MVU: Extract and execute variable commands from response ---
        updated_variables = current_variables
        changes_json = "{}"
        commands: list[Any] = []
        try:
            prev_data: dict[str, Any] = json.loads(current_variables) if current_variables.strip() else {}
        except json.JSONDecodeError:
            prev_data = {}
        if not isinstance(prev_data, dict):
            prev_data = {}

        if final_text:
            from ..mvu.engine import extract_commands, execute_commands
            commands = extract_commands(final_text)
            if commands:
                new_data, changes = execute_commands(prev_data, commands)
                updated_variables = json.dumps(new_data, ensure_ascii=False, indent=2)
                changes_json = json.dumps(changes, ensure_ascii=False, indent=2)

        metadata = {
            "provider": resolved_provider if last_result else provider,
            "model": resolved_model if last_result else model,
            "profile": profile,
            "preset_id": preset_id,
            "context_mode": context_mode,
            "agent_loop": True,
            "iterations": iterations,
            "tool_calls": tool_call_log,
            "tools_available": [t.name for t in available_tools] if available_tools else [],
            "token_usage": {"input": total_input_tokens, "output": total_output_tokens},
            "session_id": session_id,
            "turn_index": len(history_turns) + (1 if should_record else 0),
            "mvu_commands": len(commands),
            "reflection_attempts": reflection_attempts,
            "reflection_log": reflection_log,
            "story_plan": story_plan_result,
            "action_options": _extract_action_options(final_text) if final_text else [],
        }
        session_context = json.dumps({
            "session_id": session_id,
            "turn_count": len(history_turns) + (1 if should_record else 0),
        })
        return (final_text, session_context, json.dumps(metadata, ensure_ascii=False), updated_variables, changes_json)


def _extract_action_options(text: str) -> list[str]:
    """Extract <options> block from AI output and return list of option strings."""
    match = re.search(r"<options>(.*?)</options>", text, re.DOTALL)
    if not match:
        return []
    return [line.strip() for line in match.group(1).strip().split("\n") if line.strip()]
