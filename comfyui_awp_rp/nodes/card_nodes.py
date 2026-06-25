"""
Card nodes for importing and selecting character cards.
"""

import json
from typing import Any

from ..card.import_card import CardImporter, load_card_json_from_file
from ..card.greeting import GreetingManager


class AWPCardImport:
    """导入 SillyTavern V3 角色卡。"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "optional": {
                "card_json": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": '粘贴 SillyTavern V3 角色卡 JSON...',
                }),
                "card_path": ("STRING", {
                    "default": "",
                    "placeholder": "或填写角色卡 .json / SillyTavern .png 文件路径",
                }),
            },
        }
    
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("角色卡ID", "角色卡信息", "状态")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/角色卡"
    OUTPUT_NODE = True
    
    def execute(self, card_json: str = "", card_path: str = ""):
        """Import a character card."""
        if not card_json.strip() and not card_path.strip():
            return ("", "", "Error: paste card_json or provide card_path")
        
        try:
            if card_path.strip():
                card_data = load_card_json_from_file(card_path)
            else:
                card_data = json.loads(card_json)
        except json.JSONDecodeError as e:
            return ("", "", f"Error parsing JSON: {e}")
        except Exception as e:
            return ("", "", f"Error loading card file: {e}")
        
        importer = CardImporter()
        
        try:
            result = importer.import_card(card_data)
            
            card_info = json.dumps({
                "card_id": result.card_id,
                "name": result.manifest.name,
                "description": result.manifest.description,
                "worldbook_entries": result.manifest.worldbook_entry_count,
                "greetings": len(result.greetings),
                "already_existed": result.already_existed,
            }, ensure_ascii=False, indent=2)
            
            status = "Imported successfully" if not result.already_existed else "Card already existed, updated"
            
            return (result.card_id, card_info, status)
            
        except Exception as e:
            return ("", "", f"Import error: {e}")


class AWPCardSelect:
    """按 ID 选择角色卡。"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "card_id": ("STRING", {
                    "default": "",
                    "placeholder": "角色卡ID",
                    "forceInput": True,
                }),
            },
        }
    
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("角色卡ID", "角色卡数据", "世界书JSON", "角色卡名称", "角色卡引用")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/角色卡"
    
    def execute(self, card_id: str):
        """Select a character card."""
        if not card_id:
            return ("", "{}", "[]", "", "{}")
        
        importer = CardImporter()
        card = importer.get_card(card_id)
        
        if not card:
            return ("", "{}", "[]", "", "{}")

        manifest = card.get("manifest", {})
        card_name = manifest.get("name") or card_id
        
        card_data = json.dumps({
            "card_id": card["card_id"],
            "manifest": manifest,
            "greetings": card["greetings"],
        }, ensure_ascii=False, indent=2)

        card_ref_json = json.dumps({
            "card_id": card_id,
            "card_name": card_name,
            "name": card_name,
            "worldbook_entry_count": manifest.get("worldbook_entry_count", 0),
            "default_greeting_id": manifest.get("default_greeting_id"),
        }, ensure_ascii=False, indent=2)
        
        worldbook_json = json.dumps(card.get("worldbook", []), ensure_ascii=False, indent=2)
        
        return (card_id, card_data, worldbook_json, card_name, card_ref_json)


class AWPGreeting:
    """从角色卡中选择并使用开场白。

    支持两种模式：
    - select（默认）：返回指定 greeting_id 的开场白文本，或自动选择最佳默认值。
    - list：返回所有开场白及其内容预览，供用户浏览选择。
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "card_id": ("STRING", {
                    "default": "",
                    "placeholder": "角色卡ID",
                    "forceInput": True,
                }),
                "mode": (["select", "list"], {"default": "select"}),
            },
            "optional": {
                "greeting_id": ("STRING", {
                    "default": "",
                    "placeholder": "开场白ID（留空自动选择最佳）",
                }),
            },
        }
    
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("开场白文本", "开场白信息", "开场白列表")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/角色卡"
    OUTPUT_NODE = True
    
    def execute(self, card_id: str, mode: str = "select", greeting_id: str = ""):
        """Select or list greetings."""
        if not card_id:
            return ("(No card selected)", "{}", "[]")
        
        manager = GreetingManager()
        greetings = manager.get_greetings(card_id)
        
        if not greetings:
            return ("(No greeting found)", "{}", "[]")
        
        # Always build the full list for the third output
        list_items = []
        for g in greetings:
            preview = g.content[:200] if g.content else ""
            if len(g.content) > 200:
                preview += "..."
            list_items.append({
                "greeting_id": g.greeting_id,
                "index": g.index,
                "label": g.label or f"Greeting {g.index}",
                "is_default": g.is_default,
                "length": len(g.content or ""),
                "preview": preview,
            })
        list_json = json.dumps(list_items, ensure_ascii=False, indent=2)
        
        # Build readable list text
        list_lines = []
        for item in list_items:
            tag = " [默认]" if item["is_default"] else ""
            list_lines.append(f"=== {item['greeting_id']}: {item['label']}{tag} ({item['length']}字) ===")
            list_lines.append(item["preview"])
            list_lines.append("")
        list_text = "\n".join(list_lines)
        
        if mode == "list":
            # List mode: return the list as primary output, plus auto-selected greeting
            greeting = manager.get_default_greeting(card_id)
            if greeting:
                greeting_info = json.dumps({
                    "greeting_id": greeting.greeting_id,
                    "index": greeting.index,
                    "label": greeting.label,
                    "is_default": greeting.is_default,
                }, ensure_ascii=False, indent=2)
                return (greeting.content, greeting_info, list_text)
            return ("", "{}", list_text)
        
        # Select mode
        if greeting_id:
            greeting = manager.get_greeting_by_id(card_id, greeting_id)
        else:
            greeting = manager.get_default_greeting(card_id)
        
        if not greeting:
            return ("(No greeting found)", "{}", list_text)
        
        greeting_info = json.dumps({
            "greeting_id": greeting.greeting_id,
            "index": greeting.index,
            "label": greeting.label,
            "is_default": greeting.is_default,
            "total_greetings": len(greetings),
        }, ensure_ascii=False, indent=2)
        
        return (greeting.content, greeting_info, list_text)
