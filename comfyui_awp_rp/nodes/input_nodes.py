"""Source and display helper nodes for AWP RP workflows."""

import json


class AWPTextInput:
    """将输入的文本转为可连接的 STRING 输出。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "placeholder": "在这里输入玩家台词、动作或任意文本...",
                    },
                ),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("文本",)
    FUNCTION = "execute"
    CATEGORY = "AWP RP/输入"

    def execute(self, text: str):
        return (text,)


class AWPJsonInput:
    """验证 JSON 文本并向前传递。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "json_text": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "{}",
                        "placeholder": "输入 JSON...",
                    },
                ),
            },
            "optional": {
                "validate_json": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("JSON文本", "状态")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/输入"

    def execute(self, json_text: str, validate_json: bool = True):
        if validate_json:
            try:
                json.loads(json_text or "{}")
            except json.JSONDecodeError as exc:
                return (json_text, f"JSON error: {exc}")
        return (json_text, "OK")


class AWPTextOutput:
    """文本内容的终端显示节点。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "placeholder": "连接需要展示的文本...",
                        "forceInput": True,
                    },
                ),
            },
            "optional": {
                "label": ("STRING", {"default": "output"}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("文本",)
    FUNCTION = "execute"
    CATEGORY = "AWP RP/输出"
    OUTPUT_NODE = True

    def execute(self, text: str, label: str = "output"):
        return {
            "ui": {"text": [text], "label": [label]},
            "result": (text,),
        }


class AWPJsonOutput:
    """JSON 内容的终端显示节点。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "json_text": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "{}",
                        "placeholder": "连接需要展示的 JSON...",
                        "forceInput": True,
                    },
                ),
            },
            "optional": {
                "label": ("STRING", {"default": "json_output"}),
                "pretty": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("JSON文本", "状态")
    FUNCTION = "execute"
    CATEGORY = "AWP RP/输出"
    OUTPUT_NODE = True

    def execute(self, json_text: str, label: str = "json_output", pretty: bool = True):
        if not pretty:
            return {
                "ui": {"text": [json_text], "label": [label], "status": ["OK"]},
                "result": (json_text, "OK"),
            }
        try:
            parsed = json.loads(json_text or "{}")
        except json.JSONDecodeError as exc:
            status = f"JSON error: {exc}"
            return {
                "ui": {"text": [json_text], "label": [label], "status": [status]},
                "result": (json_text, status),
            }
        formatted = json.dumps(parsed, ensure_ascii=False, indent=2)
        return {
            "ui": {"text": [formatted], "label": [label], "status": ["OK"]},
            "result": (formatted, "OK"),
        }
