"""
AWP RP 单轮测试 —— 通过 session 状态文件实现多轮对话
用法: python test_rp_turn.py <turn_number> <user_input>
  turn_number=0: 发送开场场景
  turn_number>=1: 发送用户回复
"""
import json, os, sys, re
from pathlib import Path

# Fix Windows console encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("RP_PROVIDER", "deepseek")
os.environ.setdefault("RP_MODEL", "deepseek-v4-flash")

from comfyui_awp_rp.card.import_card import load_card_json_from_file
from comfyui_awp_rp.core.config import initialize_config, get_config

# 初始化
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

STATE_FILE = Path(__file__).parent / ".rp_test_state.json"
CARD_PATH = r"C:\Users\zhao\Downloads\桃花村的公媳.json"
SESSION_ID = "rp-test-10turns"

# 加载角色卡（首次）
def get_worldbook_context():
    card_json = load_card_json_from_file(CARD_PATH)
    name = card_json.get('data',{}).get('name','桃花村的公媳')
    wb_parts = [f"## 角色卡: {name}"]
    character_book = card_json.get("data", {}).get("character_book", {})
    entries = character_book.get("entries", [])
    
    # Separate constant (always-active) entries from triggered entries
    const_entries = []
    triggered_entries = []
    for entry in entries:
        if entry.get('disable', False):
            continue
        content = entry.get('content', '').strip()
        if not content:
            continue
        comment = entry.get('comment', '')
        keys = entry.get('keys', [])
        is_const = entry.get('constant', False)
        if is_const:
            const_entries.append((comment, content, keys))
        else:
            triggered_entries.append((comment, content, keys))
    
    # Include ALL entries - full content, no truncation
    if const_entries:
        wb_parts.append("### 常开设定（始终生效）")
        for comment, content, keys in const_entries:
            header = f"#### {comment}" if comment else "#### Entry"
            wb_parts.append(f"{header}\n{content}")
    
    if triggered_entries:
        wb_parts.append("### 触发型设定（关键词匹配生效）")
        for comment, content, keys in triggered_entries:
            header = f"#### {comment}" if comment else "#### Entry"
            key_info = f" (触发词: {', '.join(keys)})" if keys else ""
            wb_parts.append(f"{header}{key_info}\n{content}")
    
    return "\n\n".join(wb_parts)

def get_opening_scene():
    card_json = load_card_json_from_file(CARD_PATH)
    alt = card_json.get("data", {}).get("alternate_greetings", [])
    scene = alt[0] if alt else card_json.get("data", {}).get("first_mes", "")
    scene = re.sub(r'<UpdateVariable>.*?</UpdateVariable>', '', scene, flags=re.DOTALL)
    scene = re.sub(r'<StatusPlaceHolderImpl/>', '', scene)
    scene = re.sub(r'<SFW_IMG>.*?</SFW_IMG>', '', scene)
    scene = re.sub(r'<NSFW_IMG>.*?</NSFW_IMG>', '', scene)
    return re.sub(r'\n{3,}', '\n\n', scene).strip()

from comfyui_awp_rp.nodes.main_agent import AWPMainAgent
agent = AWPMainAgent()

# 读取或创建状态
if STATE_FILE.exists():
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
else:
    state = {"turn": 0, "last_reply": "", "session_id": SESSION_ID}

turn = int(sys.argv[1]) if len(sys.argv) > 1 else (state["turn"] + 1)
user_input = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""

# Fallback: read from .rp_user_input.txt if no CLI args
INPUT_FILE = Path(__file__).parent / ".rp_user_input.txt"
if not user_input and INPUT_FILE.exists():
    user_input = INPUT_FILE.read_text(encoding="utf-8").strip()

if turn == 0:
    user_input = f"[场景设定] 以下是当前故事的场景背景，请基于这个场景开始你的叙述。不要回复分析或说明，直接以第三人称叙事者的口吻继续描写故事:\n\n{get_opening_scene()}\n\n请基于此场景，以第三人称叙事继续描写情节发展。注意：{{user}}(老马/马大山，公公)是玩家，不要替玩家做决定或控制玩家的言行。你负责描写其他NPC(周语晴、马俊伟)和环境。"
elif not user_input:
    print("用法: python test_rp_turn.py <turn> <你的回复>")
    sys.exit(1)

worldbook_context = get_worldbook_context()

print(f"\n[Turn {turn}] Calling deepseek-v4-flash...", flush=True)
print(f"[Input] {user_input[:100]}...", flush=True)

reply, ctx, meta_str, vars_str, changes = agent.execute(
    user_input=user_input,
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

meta = json.loads(meta_str) if meta_str else {}
print(f"\n{'─'*60}")
print(f"[AI Turn {turn}]:")
print(f"{'─'*60}")
print(reply)
print(f"{'─'*60}")
print(f"[Tokens] in={meta.get('token_usage',{}).get('input','?')} out={meta.get('token_usage',{}).get('output','?')}")
print()

# Save state
state = {
    "turn": turn,
    "last_reply": reply,
    "session_id": SESSION_ID,
}
STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[State] Saved to {STATE_FILE}")
