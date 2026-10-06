"""Bounded, optional LangChain provider integrations shared by all review modes."""

from __future__ import annotations

import os
from importlib import import_module

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

DEFAULT_OPENAI_MODEL = "gpt-5-mini"
DEFAULT_OPENROUTER_MODEL = "openrouter/auto"
DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-8"
DEFAULT_OLLAMA_MODEL = "llama3.2"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODELS = {
    "openai": DEFAULT_OPENAI_MODEL,
    "openrouter": DEFAULT_OPENROUTER_MODEL,
    "anthropic": DEFAULT_ANTHROPIC_MODEL,
    "ollama": DEFAULT_OLLAMA_MODEL,
}


class AIProviderError(RuntimeError):
    """A safe, user-facing configuration or model execution failure."""


def resolve_model(provider: str, model: str | None) -> str:
    return (
        model
        or os.environ.get(f"{provider.upper()}_MODEL")
        or DEFAULT_MODELS.get(provider, "unknown")
    )


def provider_error(exc: Exception) -> AIProviderError:
    # SDK errors can contain authorization headers, request bodies or repository data.
    # Never propagate those details into a persisted report or a public API response.
    if isinstance(exc, AIProviderError):
        return exc
    return AIProviderError(
        f"Model request failed ({type(exc).__name__}). Check provider configuration, "
        "connectivity, model tool support and execution limits."
    )


def message_text(message: BaseMessage) -> str:
    return message.text


def create_chat_model(
    *,
    provider: str,
    model: str | None = None,
    timeout: float = 60,
    max_output_tokens: int = 900,
    ollama_url: str | None = None,
) -> BaseChatModel:
    provider = provider.lower()
    if provider not in DEFAULT_MODELS:
        raise AIProviderError(f"Unsupported AI provider: {provider}")
    if timeout <= 0 or max_output_tokens <= 0:
        raise AIProviderError("Model timeout and output token limit must be positive.")
    key = None
    if provider != "ollama":
        key_name = f"{provider.upper()}_API_KEY"
        key = os.environ.get(key_name)
        if not key:
            raise AIProviderError(f"{key_name} is not set.")
    integration = "openai" if provider == "openrouter" else provider
    try:
        module = import_module(f"langchain_{integration}")
    except ImportError as exc:
        raise AIProviderError(
            f"Install the provider integration: pip install 'github-repo-review-agent[{integration}]'."
        ) from exc
    resolved = resolve_model(provider, model)
    try:
        if provider == "ollama":
            return module.ChatOllama(
                model=resolved,
                base_url=ollama_url or os.environ.get("OLLAMA_BASE_URL") or DEFAULT_OLLAMA_URL,
                num_predict=max_output_tokens,
                client_kwargs={"timeout": timeout},
            )
        if provider == "anthropic":
            return module.ChatAnthropic(
                model=resolved,
                api_key=key,
                timeout=timeout,
                max_tokens=max_output_tokens,
                max_retries=0,
            )
        options = {}
        if provider == "openrouter":
            headers = {}
            for env_name, alias, header in (
                ("OPENROUTER_HTTP_REFERER", "OPENROUTER_SITE_URL", "HTTP-Referer"),
                ("OPENROUTER_APP_TITLE", "OPENROUTER_SITE_NAME", "X-Title"),
            ):
                value = os.environ.get(env_name) or os.environ.get(alias)
                if value:
                    headers[header] = value
            options = {"base_url": "https://openrouter.ai/api/v1", "default_headers": headers}
        else:
            options = {"use_responses_api": True}
        return module.ChatOpenAI(
            model=resolved,
            api_key=key,
            timeout=timeout,
            max_tokens=max_output_tokens,
            max_retries=0,
            **options,
        )
    except Exception as exc:
        raise provider_error(exc) from exc
