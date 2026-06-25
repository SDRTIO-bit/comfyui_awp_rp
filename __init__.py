"""
ComfyUI Custom Node: AWP RP Plugin

Agent Workflow Platform for Roleplay - ComfyUI integration.
This file bridges ComfyUI's custom node loader to the comfyui_awp_rp package.
"""

import os
import sys

# Ensure the plugin package is importable
_plugin_dir = os.path.dirname(os.path.abspath(__file__))
if _plugin_dir not in sys.path:
    sys.path.insert(0, _plugin_dir)

from comfyui_awp_rp import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]

WEB_DIRECTORY = os.path.join(_plugin_dir, "comfyui_awp_rp", "js")
