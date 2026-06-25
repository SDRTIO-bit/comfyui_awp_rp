"""
AWP RP 单轮测试 —— card_id 自动加载世界书并智能过滤
用法: python test_rp_turn.py <turn_number>
  turn=0: 发送开场场景，自动导入角色卡
  turn>=1: 发送 .rp_user_input.txt 中的用户回复
"""
import json, os, sys, re
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("RP_PROVIDER", "deepseek")
os.environ.setdefault("RP_MODEL", "deepseek-v4-flash")

from comfyui_awp_rp.card.import_card import CardImporter, load_card_json_from_file
from comfyui_awp_rp.core.config import initialize_config

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
SESSION_ID = "rp-test-smart-wb"

def import_card(card_path: str) -> str:
    """Import card and return card_id."""
    card_json = load_card_json_from_file(card_path)
    importer = CardImporter()
    result = importer.import_card(card_json)
    print(f"[Card] Imported: {result.manifest.name} (id={result.card_id})")
    print(f"[Card] Worldbook entries: {result.manifest.worldbook_entry_count}")
    return result.card_id

def get_opening_scene(card_path: str) -> str:
    card_json = load_card_json_from_file(card_path)
    alt = card_json.get("data", {}).get("alternate_greetings", [])
    scene = alt[0] if alt else card_json.get("data", {}).get("first_mes", "")
    scene = re.sub(r'<UpdateVariable>.*?</UpdateVariable>', '', scene, flags=re.DOTALL)
    scene = re.sub(r'<StatusPlaceHolderImpl/>', '', scene)
    scene = re.sub(r'<SFW_IMG>.*?</SFW_IMG>', '', scene)
    scene = re.sub(r'<NSFW_IMG>.*?</NSFW_IMG>', '', scene)
    return re.sub(r'\n{3,}', '\n\n', scene).strip()

from comfyui_awp_rp.nodes.main_agent import AWPMainAgent
agent = AWPMainAgent()

# Read or init state
if STATE_FILE.exists():
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
else:
    state = {"turn": 0, "last_reply": "", "session_id": SESSION_ID, "card_id": ""}

turn = int(sys.argv[1]) if len(sys.argv) > 1 else (state["turn"] + 1)
card_id = state.get("card_id", "")

# Fallback: read from .rp_user_input.txt
INPUT_FILE = Path(__file__).parent / ".rp_user_input.txt"
user_input = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
if not user_input and INPUT_FILE.exists():
    user_input = INPUT_FILE.read_text(encoding="utf-8").strip()

if turn == 0:
    card_id = import_card(CARD_PATH)
    opening = get_opening_scene(CARD_PATH)
    user_input = f"[场景设定] 以下是当前故事的场景背景，请基于这个场景开始你的叙述。不要回复分析或说明，直接以第三人称叙事者的口吻继续描写故事:\n\n{opening}\n\n请基于此场景，以第三人称叙事继续描写情节发展。注意：{{user}}(老马/马大山，公公)是玩家，不要替玩家做决定或控制玩家的言行。你负责描写其他NPC(周语晴、马俊伟)和环境。"
elif not user_input:
    print("用法: python test_rp_turn.py <turn> [<input>]")
    sys.exit(1)

print(f"\n[Turn {turn}] Calling deepseek-v4-flash (card_id={card_id[:16]}...)...", flush=True)
print(f"[Input] {user_input[:100]}...", flush=True)

reply, ctx, meta_str, vars_str, changes = agent.execute(
    user_input=user_input,
    session_id=SESSION_ID,
    provider="deepseek",
    model="deepseek-v4-flash",
    profile="rp-writer",
    context_mode="full_context",
    record_session=True,
    card_id=card_id,
    worldbook_context="",  # Let card_id handle worldbook filtering
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

# Persist state
state = {
    "turn": turn,
    "last_reply": reply,
    "session_id": SESSION_ID,
    "card_id": card_id,
}
STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
