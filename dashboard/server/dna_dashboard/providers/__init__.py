"""Provider registry: which configured adapter serves each capability (analysis, copy, image_generation).

Real adapters: Claude (Anthropic API) for analysis and copy drafts; OpenAI GPT Image for image generation. A missing
key disables only the dependent actions; intake, drafts, manual scanning, editing and deterministic rendering keep
working. The mock provider is available only when DNA_ENABLE_MOCK_PROVIDERS=1 (tests), and is labelled everywhere.
"""
from __future__ import annotations

from .. import config
from .anthropic_provider import AnthropicProvider
from .base import Provider, ProviderError, cached_health, checkpoint_valid, provider_call, tracked
from .mock import MockProvider
from .openai_provider import OpenAIImageProvider

__all__ = ["Provider", "ProviderError", "cached_health", "checkpoint_valid", "provider_call", "tracked", "all_providers", "for_capability",
           "set_mock_failure"]

_MOCK_FAIL: dict[str, str | None] = {"value": None}


def all_providers() -> list[Provider]:
    ps: list[Provider] = [AnthropicProvider(), OpenAIImageProvider()]
    if config.get().enable_mock_providers:
        ps.append(MockProvider(_MOCK_FAIL["value"]))
    return ps


def for_capability(cap: str, preferred: str | None = None) -> Provider:
    """The provider that will serve `cap`. A requested provider wins; otherwise the first configured real one;
    the mock only when enabled and nothing real is configured. Raises ProviderError(unconfigured) with a setup path."""
    ps = [p for p in all_providers() if cap in p.capabilities]
    if preferred:
        p = next((p for p in ps if p.name == preferred), None)
        if p is None:
            raise ProviderError(preferred, "unsupported", f"{preferred} cannot perform {cap}")
        if not p.configured():
            raise ProviderError(p.name, "unconfigured", f"{p.label} is not configured", {"setup": "/settings"})
        return p
    real = [p for p in ps if not p.mock and p.configured()]
    if real:
        return real[0]
    mock = [p for p in ps if p.mock]
    if mock:
        return mock[0]
    need = {"analysis": "ANTHROPIC_API_KEY", "copy": "ANTHROPIC_API_KEY", "image_generation": "OPENAI_API_KEY"}[cap]
    raise ProviderError(ps[0].name if ps else cap, "unconfigured",
                        f"no provider is configured for {cap.replace('_', ' ')}: add {need} in Settings or the environment",
                        {"setup": "/settings", "env": need})


def set_mock_failure(kind: str | None) -> None:
    """Tests only: make the mock provider fail with a given error kind."""
    _MOCK_FAIL["value"] = kind
