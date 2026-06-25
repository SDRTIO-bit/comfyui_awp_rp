"""Test script for AWP RP Plugin."""
import sys
import os

# Add parent directory to path
plugin_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(plugin_dir)
sys.path.insert(0, parent_dir)

print("=" * 60)
print("AWP RP Plugin Test")
print("=" * 60)

# Test 1: Import
print("\n[1] Testing import...")
try:
    from comfyui_awp_rp import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
    print(f"    OK - {len(NODE_CLASS_MAPPINGS)} nodes loaded")
except Exception as e:
    print(f"    FAILED: {e}")
    sys.exit(1)

# Test 2: Check each node
print("\n[2] Testing node definitions...")
errors = []
for name, cls in NODE_CLASS_MAPPINGS.items():
    try:
        inputs = cls.INPUT_TYPES()
        required = len(inputs.get("required", {}))
        optional = len(inputs.get("optional", {}))
        print(f"    {name}: OK ({required} required, {optional} optional)")
    except Exception as e:
        errors.append(f"{name}: {e}")
        print(f"    {name}: ERROR - {e}")

if errors:
    print(f"\n    ERRORS: {len(errors)}")
    for err in errors:
        print(f"      - {err}")
else:
    print("\n    All nodes OK!")

# Test 3: Test core modules
print("\n[3] Testing core modules...")
try:
    from comfyui_awp_rp.core.config import get_config, Config
    config = get_config()
    print(f"    Config: data_dir = {config.data_dir}")
except Exception as e:
    print(f"    Config ERROR: {e}")

try:
    from comfyui_awp_rp.core.store import SQLiteStore
    print("    SQLiteStore: OK")
except Exception as e:
    print(f"    SQLiteStore ERROR: {e}")

try:
    from comfyui_awp_rp.core.llm_router import LlmRouter, ProviderRegistry
    print("    LlmRouter: OK")
except Exception as e:
    print(f"    LlmRouter ERROR: {e}")

# Test 4: Test memory modules
print("\n[4] Testing memory modules...")
try:
    from comfyui_awp_rp.memory.short_term import ShortTermMemory, AgentSessionManager
    print("    ShortTermMemory: OK")
except Exception as e:
    print(f"    ShortTermMemory ERROR: {e}")

try:
    from comfyui_awp_rp.memory.long_term import LongTermMemory
    print("    LongTermMemory: OK")
except Exception as e:
    print(f"    LongTermMemory ERROR: {e}")

# Test 5: Test retrieval modules
print("\n[5] Testing retrieval modules...")
try:
    from comfyui_awp_rp.retrieval.tokenizer import tokenize, tokenize_chinese
    tokens = tokenize("测试中文分词")
    print(f"    Tokenizer: OK (tokens: {tokens})")
except Exception as e:
    print(f"    Tokenizer ERROR: {e}")

try:
    from comfyui_awp_rp.retrieval.bm25 import BM25Scorer
    print("    BM25Scorer: OK")
except Exception as e:
    print(f"    BM25Scorer ERROR: {e}")

# Test 6: Test card modules
print("\n[6] Testing card modules...")
try:
    from comfyui_awp_rp.card.import_card import CardImporter, SillyTavernV3Parser
    print("    CardImporter: OK")
except Exception as e:
    print(f"    CardImporter ERROR: {e}")

try:
    from comfyui_awp_rp.card.variable import VariableStateManager
    print("    VariableStateManager: OK")
except Exception as e:
    print(f"    VariableStateManager ERROR: {e}")

# Test 7: Test preset and profile
print("\n[7] Testing preset and profile...")
try:
    from comfyui_awp_rp.preset.preset import PresetManager, DEFAULT_RP_PRESET
    manager = PresetManager()
    presets = manager.list_presets()
    print(f"    PresetManager: OK ({len(presets)} presets)")
except Exception as e:
    print(f"    PresetManager ERROR: {e}")

try:
    from comfyui_awp_rp.profile.profile import ProfileManager
    manager = ProfileManager()
    profiles = manager.list_profiles()
    print(f"    ProfileManager: OK ({len(profiles)} profiles)")
    for p in profiles:
        print(f"      - {p['id']}: {p['label']}")
except Exception as e:
    print(f"    ProfileManager ERROR: {e}")

print("\n" + "=" * 60)
print("Test completed!")
print("=" * 60)
