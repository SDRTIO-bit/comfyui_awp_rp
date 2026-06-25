"""
LLM Router - Routes completion requests to the correct provider adapter.

Supports multiple providers (DeepSeek, OpenAI, OpenRouter, etc.) with
a unified interface. Each provider uses OpenAI-compatible API format.
"""

import json
import time
from typing import Any, Callable, Optional
from dataclasses import dataclass

import requests

from .types import (
    LlmCompletionInput,
    LlmCompletionResult,
    LlmTokenUsage,
    LlmToolCall,
    LlmToolDefinition,
    ProviderConfig,
    ResolvedModelRequest,
)
from .config import get_config


class LlmProviderTimeoutError(Exception):
    """Raised when an LLM provider request times out."""
    pass


class LlmAdapter:
    """Base adapter for LLM providers."""
    
    def __init__(self, provider_id: str, api_key: str, base_url: str):
        self.provider_id = provider_id
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
    
    def complete(self, input: LlmCompletionInput) -> LlmCompletionResult:
        """Complete a prompt using the provider's API."""
        raise NotImplementedError
    
    def _make_request(
        self,
        model: str,
        prompt: str,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout_ms: Optional[int] = None,
        response_format: Optional[str] = None,
        tools: Optional[list[LlmToolDefinition]] = None,
        tool_choice: Optional[str] = None,
    ) -> dict[str, Any]:
        """Make an OpenAI-compatible API request."""
        url = f"{self.base_url}/chat/completions"
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        
        messages = [
            {"role": "user", "content": prompt}
        ]
        
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        
        if temperature is not None:
            payload["temperature"] = temperature
        if top_p is not None:
            payload["top_p"] = top_p
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}
        
        # Function calling support
        if tools:
            payload["tools"] = [tool.to_openai_format() for tool in tools]
        if tool_choice:
            if tool_choice == "none":
                payload["tool_choice"] = "none"
            elif tool_choice == "auto":
                payload["tool_choice"] = "auto"
            else:
                # Specific tool name
                payload["tool_choice"] = {
                    "type": "function",
                    "function": {"name": tool_choice},
                }
        
        timeout_sec = (timeout_ms or 60000) / 1000
        
        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=timeout_sec,
            )
            response.raise_for_status()
            return response.json()
        except requests.Timeout:
            raise LlmProviderTimeoutError()
        except requests.RequestException as e:
            raise RuntimeError(f"LLM provider request failed: {e}")


class OpenAICompatibleAdapter(LlmAdapter):
    """Adapter for OpenAI-compatible APIs (DeepSeek, OpenRouter, etc.)."""
    
    def complete(self, input: LlmCompletionInput) -> LlmCompletionResult:
        """Complete a prompt using OpenAI-compatible API."""
        start_time = time.time()
        
        response_data = self._make_request(
            model=input.model,
            prompt=input.prompt,
            temperature=input.temperature,
            top_p=input.top_p,
            max_tokens=input.max_tokens,
            timeout_ms=input.timeout_ms,
            tools=input.tools,
            tool_choice=input.tool_choice,
        )
        
        latency_ms = int((time.time() - start_time) * 1000)
        
        # Parse response
        choices = response_data.get("choices", [])
        if not choices:
            raise RuntimeError("No choices in LLM response")
        
        choice = choices[0]
        message = choice.get("message", {})
        text = message.get("content", "") or ""
        usage = response_data.get("usage", {})
        
        token_usage = LlmTokenUsage(
            input=usage.get("prompt_tokens", 0),
            output=usage.get("completion_tokens", 0),
            cached_input=usage.get("prompt_cache_hit_tokens"),
        )
        
        # Parse tool calls from response
        tool_calls: list[LlmToolCall] = []
        raw_tool_calls = message.get("tool_calls", [])
        if raw_tool_calls:
            for tc in raw_tool_calls:
                function = tc.get("function", {})
                tool_calls.append(LlmToolCall(
                    id=tc.get("id", ""),
                    name=function.get("name", ""),
                    arguments=function.get("arguments", ""),
                ))
        
        return LlmCompletionResult(
            text=text,
            token_usage=token_usage,
            finish_reason=choice.get("finish_reason"),
            provider_request_id=response_data.get("id"),
            tool_calls=tool_calls,
        )


class ProviderRegistry:
    """Registry for LLM providers."""
    
    def __init__(self, default_provider_id: str = "deepseek"):
        self._providers: dict[str, ProviderConfig] = {}
        self._default_provider_id = default_provider_id
        self._adapters: dict[str, LlmAdapter] = {}
    
    def register(self, config: ProviderConfig) -> None:
        """Register a provider configuration."""
        if config.provider_id in self._providers:
            raise ValueError(f"Provider '{config.provider_id}' already registered")
        self._providers[config.provider_id] = config
    
    def get(self, provider_id: str) -> ProviderConfig:
        """Get a provider configuration by ID."""
        if provider_id not in self._providers:
            available = ", ".join(self._providers.keys()) or "(none)"
            raise ValueError(f"Unknown provider '{provider_id}'. Available: {available}")
        return self._providers[provider_id]
    
    def get_default(self) -> ProviderConfig:
        """Get the default provider configuration."""
        return self.get(self._default_provider_id)
    
    def create_adapter(self, provider_id: str) -> LlmAdapter:
        """Create an adapter for a provider."""
        if provider_id in self._adapters:
            return self._adapters[provider_id]
        
        config = self.get(provider_id)
        adapter = OpenAICompatibleAdapter(
            provider_id=config.provider_id,
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self._adapters[provider_id] = adapter
        return adapter
    
    def create_default_adapter(self) -> LlmAdapter:
        """Create an adapter for the default provider."""
        return self.create_adapter(self._default_provider_id)
    
    @property
    def default_provider_id(self) -> str:
        return self._default_provider_id
    
    def list_providers(self) -> list[str]:
        """List all registered provider IDs."""
        return list(self._providers.keys())


class LlmRouter:
    """Routes LLM completion requests to the appropriate provider."""
    
    def __init__(self, registry: ProviderRegistry):
        self._registry = registry
        self._adapters: dict[str, LlmAdapter] = {}
    
    @property
    def provider_registry(self) -> ProviderRegistry:
        return self._registry
    
    def _get_adapter(self, provider_id: str) -> LlmAdapter:
        """Get or create an adapter for a provider."""
        if provider_id not in self._adapters:
            self._adapters[provider_id] = self._registry.create_adapter(provider_id)
        return self._adapters[provider_id]
    
    def resolve_config(
        self,
        node_config: Optional[dict[str, Any]] = None,
        workflow_defaults: Optional[dict[str, Any]] = None,
    ) -> ResolvedModelRequest:
        """Resolve effective model configuration."""
        node_config = node_config or {}
        workflow_defaults = workflow_defaults or {}
        
        # Determine provider
        provider_id = (
            node_config.get("provider") or
            workflow_defaults.get("provider") or
            self._registry.default_provider_id
        )
        
        # Get provider config
        provider_config = self._registry.get(provider_id)
        
        # Determine model
        model = (
            node_config.get("model") or
            workflow_defaults.get("model") or
            provider_config.default_model
        )
        
        return ResolvedModelRequest(
            provider_id=provider_id,
            model=model,
            temperature=node_config.get("temperature") or workflow_defaults.get("temperature"),
            top_p=node_config.get("top_p") or workflow_defaults.get("top_p"),
            max_tokens=node_config.get("max_tokens") or workflow_defaults.get("max_tokens"),
            timeout_ms=node_config.get("timeout_ms") or workflow_defaults.get("timeout_ms"),
            response_format=node_config.get("response_format") or workflow_defaults.get("response_format"),
        )
    
    def complete(
        self,
        request: ResolvedModelRequest,
        prompt: str,
    ) -> tuple[str, LlmTokenUsage]:
        """Complete a prompt through the appropriate provider."""
        adapter = self._get_adapter(request.provider_id)
        
        input = LlmCompletionInput(
            model=request.model,
            prompt=prompt,
            temperature=request.temperature,
            top_p=request.top_p,
            max_tokens=request.max_tokens,
            timeout_ms=request.timeout_ms,
        )
        
        result = adapter.complete(input)
        return result.text, result.token_usage
    
    def complete_with_config(
        self,
        node_config: Optional[dict[str, Any]],
        workflow_defaults: Optional[dict[str, Any]],
        prompt: str,
    ) -> tuple[str, LlmTokenUsage, str, str]:
        """Complete using node-level and workflow-level config resolution.
        
        Returns: (text, token_usage, provider_id, model)
        """
        request = self.resolve_config(node_config, workflow_defaults)
        text, token_usage = self.complete(request, prompt)
        return text, token_usage, request.provider_id, request.model
    
    def complete_with_tools(
        self,
        node_config: Optional[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: Optional[list[LlmToolDefinition]] = None,
        tool_choice: Optional[str] = None,
    ) -> tuple[LlmCompletionResult, str, str]:
        """Complete with function calling support.

        Supports multi-turn conversations via the messages list. When the LLM
        requests tool calls, the caller executes the tools, appends the results
        as ``{"role": "tool", ...}`` messages, and calls this method again.

        Args:
            node_config: Provider/model/temperature overrides.
            messages: Full conversation history as OpenAI message dicts.
            tools: Optional list of tool definitions for function calling.
            tool_choice: "auto", "none", or a specific tool name.

        Returns:
            (completion_result, provider_id, model)
        """
        request = self.resolve_config(node_config, None)
        adapter = self._get_adapter(request.provider_id)

        # Build a single API call using the messages list directly
        url = f"{adapter.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {adapter.api_key}",
        }
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}
        if tools:
            payload["tools"] = [tool.to_openai_format() for tool in tools]
        if tool_choice:
            if tool_choice == "none":
                payload["tool_choice"] = "none"
            elif tool_choice == "auto":
                payload["tool_choice"] = "auto"
            else:
                payload["tool_choice"] = {
                    "type": "function",
                    "function": {"name": tool_choice},
                }

        timeout_sec = (request.timeout_ms or 60000) / 1000
        try:
            response = requests.post(
                url, headers=headers, json=payload, timeout=timeout_sec,
            )
            response.raise_for_status()
            response_data = response.json()
        except requests.Timeout:
            raise LlmProviderTimeoutError()
        except requests.RequestException as e:
            raise RuntimeError(f"LLM provider request failed: {e}")

        choices = response_data.get("choices", [])
        if not choices:
            raise RuntimeError("No choices in LLM response")

        choice = choices[0]
        message = choice.get("message", {})
        text = message.get("content", "") or ""
        usage = response_data.get("usage", {})

        token_usage = LlmTokenUsage(
            input=usage.get("prompt_tokens", 0),
            output=usage.get("completion_tokens", 0),
            cached_input=usage.get("prompt_cache_hit_tokens"),
        )

        tool_calls: list[LlmToolCall] = []
        raw_tool_calls = message.get("tool_calls", [])
        if raw_tool_calls:
            for tc in raw_tool_calls:
                function = tc.get("function", {})
                tool_calls.append(LlmToolCall(
                    id=tc.get("id", ""),
                    name=function.get("name", ""),
                    arguments=function.get("arguments", ""),
                ))

        result = LlmCompletionResult(
            text=text,
            token_usage=token_usage,
            finish_reason=choice.get("finish_reason"),
            provider_request_id=response_data.get("id"),
            tool_calls=tool_calls,
        )
        return result, request.provider_id, request.model

    # --- P6.1: Streaming support ---

    def complete_stream(
        self,
        node_config: Optional[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: Optional[list[LlmToolDefinition]] = None,
    ):
        """Stream completion tokens via generator.

        Yields dicts: {"token": str, "finish_reason": str|None}
        Tools are supported but tool_calls are accumulated and yielded at end.

        Note: ComfyUI nodes are synchronous, so this is primarily for use
        by external consumers (e.g., WebSocket server, web frontend).
        Internal agent loop uses complete_with_tools() for sync execution.
        """
        request = self.resolve_config(node_config, None)
        adapter = self._get_adapter(request.provider_id)

        payload = {
            "model": request.model,
            "messages": messages,
            "temperature": request.temperature or 0.7,
            "top_p": request.top_p or 1.0,
            "max_tokens": request.max_tokens or 2048,
            "stream": True,
        }
        if tools:
            payload["tools"] = [t.to_openai_format() for t in tools]
            payload["tool_choice"] = "auto"
        if request.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}

        try:
            url = f"{adapter.base_url}/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {adapter.api_key}",
            }
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                stream=True,
                timeout=request.timeout_ms / 1000 if request.timeout_ms else 120,
            )
            response.raise_for_status()

            accumulated_text = ""
            accumulated_tool_calls: list[dict] = []
            finish_reason = None

            for line in response.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                choices = chunk.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                content = delta.get("content", "")
                tc_delta = delta.get("tool_calls", [])

                if content:
                    accumulated_text += content
                    yield {"token": content, "finish_reason": None}

                if tc_delta:
                    for tc in tc_delta:
                        idx = tc.get("index", 0)
                        while len(accumulated_tool_calls) <= idx:
                            accumulated_tool_calls.append({"id": "", "name": "", "arguments": ""})
                        if "id" in tc:
                            accumulated_tool_calls[idx]["id"] = tc["id"]
                        if tc.get("function", {}).get("name"):
                            accumulated_tool_calls[idx]["name"] = tc["function"]["name"]
                        if tc.get("function", {}).get("arguments"):
                            accumulated_tool_calls[idx]["arguments"] += tc["function"]["arguments"]

                finish_reason = choices[0].get("finish_reason")
                if finish_reason:
                    yield {"token": "", "finish_reason": finish_reason, "tool_calls": accumulated_tool_calls if accumulated_tool_calls else None}

        except Exception as e:
            yield {
                "token": f"[Stream Error: {e}]",
                "finish_reason": "error",
                "provider_id": request.provider_id,
                "model": request.model,
                "error": str(e),
            }


def create_default_router() -> LlmRouter:
    """Create a router with providers from global config."""
    config = get_config()
    registry = ProviderRegistry(default_provider_id=config.default_provider_id)
    
    for provider_id, provider_config in config.providers.items():
        registry.register(provider_config)
    
    return LlmRouter(registry)
