"""
AWP RP 10轮交互测试脚本
用 "桃花村的公媳" 角色卡，deepseek-v4-flash 模型
每轮：AI 生成 → 打印 → 用户输入回复 → 下一轮
"""
import json
import os
import sys
from pathlib import Path

# 把当前目录和父目录加入 path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

# 设置环境变量
os.environ.setdefault("RP_PROVIDER", "deepseek")
os.environ.setdefault("RP_MODEL", "deepseek-v4-flash")

from comfyui_awp_rp.card.import_card import CardImporter, load_card_json_from_file
from comfyui_awp_rp.core.config import initialize_config

# 初始化配置
initialize_config(
    providers={
        "deepseek": {
            "api_key": os.environ.get("DEEPSEEK_API_KEY", ""),
            "base_url": "https://api.deepseek.com/v1",
            "default_model": "deepseek-v4-flash",
        }
    },
    default_provider="deepseek",
)

# 加载角色卡
CARD_PATH = r"C:\Users\zhao\Downloads\桃花村的公媳.json"
card_json = load_card_json_from_file(CARD_PATH)
importer = CardImporter()
result = importer.import_card(card_json)

print(f"✅ 角色卡已加载: {result.manifest.name}")
print(f"   Worldbook entries: {result.manifest.worldbook_entry_count}")
print(f"   Greetings: {len(result.greetings)}")

# 构建 worldbook context
wb_parts = []
for g in result.greetings:
    wb_parts.append(f"## 角色卡: {result.manifest.name}")
    break  # 只取名字

# 从 character_book 提取世界设定
character_book = card_json.get("data", {}).get("character_book", {})
entries = character_book.get("entries", [])
for entry in entries:
    comment = entry.get("comment", "")
    content = entry.get("content", "")
    if content.strip():
        wb_parts.append(f"### {comment}" if comment else "### Entry")
        wb_parts.append(content[:500])  # 限制长度

worldbook_context = "\n\n".join(wb_parts[:8])  # 最多8条

# 取第一个 alternate greeting 作为开场
alternate_greetings = card_json.get("data", {}).get("alternate_greetings", [])
opening_scene = alternate_greetings[0] if alternate_greetings else card_json.get("data", {}).get("first_mes", "")

# 清理开场白中的变量更新和特殊标签
import re
opening_scene_clean = re.sub(r'<UpdateVariable>.*?</UpdateVariable>', '', opening_scene, flags=re.DOTALL)
opening_scene_clean = re.sub(r'<StatusPlaceHolderImpl/>', '', opening_scene_clean)
opening_scene_clean = re.sub(r'<SFW_IMG>.*?</SFW_IMG>', '', opening_scene_clean)
opening_scene_clean = re.sub(r'<NSFW_IMG>.*?</NSFW_IMG>', '', opening_scene_clean)
opening_scene_clean = re.sub(r'\n{3,}', '\n\n', opening_scene_clean).strip()

print(f"\n{'='*60}")
print("📖 开场场景:")
print(f"{'='*60}")
print(opening_scene_clean[:500])
print("...")
print(f"{'='*60}\n")

# --- 开始10轮对话 ---
from comfyui_awp_rp.nodes.main_agent import AWPMainAgent

agent = AWPMainAgent()
SESSION_ID = "rp-test-10turns"
current_variables = "{}"

# Turn 0: 发送开场场景（不作为用户输入，而是作为第一条 system 上下文的一部分）
# 实际做法：第1轮把开场场景当作 user_input 发送，让 AI 基于此场景开始叙述
print("🔄 第 0 轮: 发送开场场景...")
reply, ctx, meta_str, vars_str, changes = agent.execute(
    user_input=f"[系统设定] 以下是当前场景，请基于这个场景开始你的叙述，不要回复分析或说明，直接继续叙述故事:\n\n{opening_scene_clean}\n\n请根据这个场景，以叙事者的口吻继续描写接下来的情节发展。你扮演的是周语晴、马俊伟等NPC，不要替{{user}}(老马/公公)做决定。",
    session_id=SESSION_ID,
    provider="deepseek",
    model="deepseek-v4-flash",
    profile="rp-writer",
    context_mode="full_context",
    record_session=True,
    worldbook_context=worldbook_context,
    preset_id="rp-default-v1",
    temperature=0.85,
    max_tokens=2048,
    enable_agent_loop=False,
)

current_variables = vars_str if vars_str else current_variables
meta = json.loads(meta_str) if meta_str else {}
print(f"\n{'─'*50}")
print(f"🤖 AI 回复 (Turn 0):")
print(f"{'─'*50}")
print(reply)
print(f"{'─'*50}")
print(f"📊 Tokens: in={meta.get('token_usage',{}).get('input','?')} out={meta.get('token_usage',{}).get('output','?')}")
print()

# --- 第 1-10 轮 ---
for turn in range(1, 11):
    print(f"\n{'='*60}")
    print(f"🔄 第 {turn}/10 轮")
    print(f"{'='*60}")
    print("👤 请输入你的回复 (输入 'quit' 退出，输入 'skip' 跳过此轮):")
    user_reply = input("> ").strip()
    
    if user_reply.lower() == 'quit':
        print("👋 退出测试")
        break
    
    if user_reply.lower() == 'skip':
        print("⏭️ 跳过此轮")
        continue
    
    if not user_reply:
        print("⚠️ 空输入，跳过")
        continue
    
    print(f"\n⏳ 调用 LLM...")
    reply, ctx, meta_str, vars_str, changes = agent.execute(
        user_input=user_reply,
        session_id=SESSION_ID,
        provider="deepseek",
        model="deepseek-v4-flash",
        profile="rp-writer",
        context_mode="full_context",
        record_session=True,
        worldbook_context=worldbook_context,
        preset_id="rp-default-v1",
        temperature=0.85,
        max_tokens=2048,
        enable_agent_loop=False,
    )
    
    current_variables = vars_str if vars_str else current_variables
    meta = json.loads(meta_str) if meta_str else {}
    
    print(f"\n{'─'*50}")
    print(f"🤖 AI 回复 (Turn {turn}):")
    print(f"{'─'*50}")
    print(reply)
    print(f"{'─'*50}")
    print(f"📊 Tokens: in={meta.get('token_usage',{}).get('input','?')} out={meta.get('token_usage',{}).get('output','?')} | Turn: {meta.get('turn_index','?')}")
    print()

print(f"\n{'='*60}")
print("✅ 10轮测试完成!")
print(f"{'='*60}")
