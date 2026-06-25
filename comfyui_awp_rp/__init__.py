"""
ComfyUI AWP RP Plugin - Agent Workflow Platform for Roleplay

A ComfyUI custom node pack that brings the Agent Workflow Platform's
RP capabilities into ComfyUI's node-based workflow system.

Features:
- Main Agent + Sub Agent architecture for RP workflow
- Multi-provider LLM routing (DeepSeek, OpenAI, GLM, custom)
- Short-term memory (session) and long-term memory (namespace isolated)
- Dynamic worldbook with version control
- BM25/keyword/hybrid retrieval
- SillyTavern V3 character card import
- Preset system for RP generation styles
- Agent profiles with specialized system prompts
- Variable state management (MVU infrastructure, runtime not yet supported)
"""

import json
import os

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]

# Web directory for custom JS widgets
WEB_DIRECTORY = os.path.join(os.path.dirname(__file__), "js")

# Plugin metadata
__version__ = "0.1.0"
__author__ = "AWP Team"


# ============ Backend API Routes for Settings Panel ============

def _register_routes():
    """Register API routes for the frontend settings panel.

    These routes let the ComfyUI web frontend read and write provider
    configuration (API keys, base URLs, models) without editing files.
    """
    try:
        import server  # type: ignore[import-not-found]
        from aiohttp import web  # type: ignore[import-not-found]

        prompt_server = server.PromptServer.instance

        @prompt_server.routes.get("/awp/providers")
        async def get_providers(_request):
            from .core.config import get_config
            config = get_config()
            result = {}
            for pid, pc in config.providers.items():
                result[pid] = {
                    "provider_id": pc.provider_id,
                    "base_url": pc.base_url,
                    "default_model": pc.default_model,
                    "has_key": bool(pc.api_key),
                }
            return web.json_response(result)

        @prompt_server.routes.post("/awp/providers")
        async def save_providers(request):
            data = await request.json()
            from .core.config import get_config
            config = get_config()
            for pid, pdata in data.items():
                if pid in config.providers:
                    if "api_key" in pdata and pdata["api_key"]:
                        config.providers[pid].api_key = pdata["api_key"]
                    if "base_url" in pdata and pdata["base_url"]:
                        config.providers[pid].base_url = pdata["base_url"]
                    if "default_model" in pdata and pdata["default_model"]:
                        config.providers[pid].default_model = pdata["default_model"]
                else:
                    # New provider
                    from .core.types import ProviderConfig
                    config.providers[pid] = ProviderConfig(
                        provider_id=pid,
                        api_key=pdata.get("api_key", ""),
                        base_url=pdata.get("base_url", ""),
                        default_model=pdata.get("default_model", ""),
                        models=[],
                    )
            config.save()
            return web.json_response({"status": "ok"})

        @prompt_server.routes.delete("/awp/providers/{provider_id}")
        async def delete_provider(request):
            provider_id = request.match_info["provider_id"]
            from .core.config import get_config
            config = get_config()
            if provider_id in config.providers:
                del config.providers[provider_id]
                config.save()
                return web.json_response({"status": "ok", "deleted": provider_id})
            return web.json_response({"status": "not_found"}, status=404)

    except Exception:
        pass  # Not running in ComfyUI context (safe for tests)


_register_routes()
