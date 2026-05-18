"""LLM provider factory.

Pick a provider with the LLM_PROVIDER env var. Default = "openai".
Add a new provider = add one entry to PROVIDERS below.
"""

from __future__ import annotations

import os

from .base import (
    HistoryItem,
    LLMClient,
    PlanResult,
    PlannedCall,
    TextDeltaCallback,
    ToolSpec,
)
from .chat_completions_client import ChatCompletionsClient
from .openai_client import OpenAIResponsesClient


# Provider presets. Each entry tells the factory:
#   - which client class to use
#   - which env var holds the API key
#   - the default base_url (for chat-completions clients)
#   - the default model name
PROVIDERS: dict[str, dict] = {
    # OpenAI via the new Responses API.
    "openai": {
        "client": "responses",
        "api_key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
    },
    # OpenAI via the legacy Chat Completions endpoint (for users who
    # want the same code path as DeepSeek/Kimi/etc).
    "openai-chat": {
        "client": "chat",
        "api_key_env": "OPENAI_API_KEY",
        "base_url": None,
        "default_model": "gpt-4o-mini",
    },
    # DeepSeek — https://api-docs.deepseek.com/
    "deepseek": {
        "client": "chat",
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
    },
    # Moonshot (Kimi) — https://platform.moonshot.cn/
    "moonshot": {
        "client": "chat",
        "api_key_env": "MOONSHOT_API_KEY",
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k",
    },
    # Alibaba Qwen via the OpenAI-compatible mode.
    "qwen": {
        "client": "chat",
        "api_key_env": "DASHSCOPE_API_KEY",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
    },
}


def make_client() -> LLMClient:
    """Construct the LLM client selected by environment variables."""
    name = os.environ.get("LLM_PROVIDER", "openai").lower()
    if name not in PROVIDERS:
        raise ValueError(
            f"Unknown LLM_PROVIDER={name!r}. Valid: {list(PROVIDERS)}"
        )
    cfg = PROVIDERS[name]

    # Model can always be overridden by the generic LLM_MODEL env var.
    model = os.environ.get("LLM_MODEL", cfg["default_model"])

    if cfg["client"] == "responses":
        # OpenAI's own SDK auto-reads OPENAI_API_KEY; no extra wiring.
        return OpenAIResponsesClient(model=model)

    # Chat-completions providers need an explicit api_key + base_url.
    api_key = os.environ.get(cfg["api_key_env"])
    if not api_key:
        raise RuntimeError(
            f"Provider {name!r} requires env var {cfg['api_key_env']}"
        )
    return ChatCompletionsClient(
        api_key=api_key,
        base_url=cfg["base_url"],
        model=model,
    )


__all__ = [
    "HistoryItem", "LLMClient", "PlanResult", "PlannedCall",
    "TextDeltaCallback", "ToolSpec",
    "make_client", "PROVIDERS",
]
