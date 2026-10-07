"""OpenAI Images adapter (GPT Image models via the official `openai` SDK, images.edit with reference images).

Used for creative reference generation and for generated slot imagery. The output is a synthesized image: its
provenance (provider, model, request id, prompt, inputs) is recorded, and no pixel-preservation or editability claim
is ever derived from it. SDK automatic retries are off; a request whose outcome is unknown is never resent blindly.
"""
from __future__ import annotations

import base64
import io

from .. import config
from .base import GATEWAY_TIMEOUTS, Provider, ProviderError


def _client(key):
    import openai

    return openai.OpenAI(api_key=key, max_retries=0, timeout=600.0)


def _classify(e) -> ProviderError:
    import openai

    n = "openai"
    if isinstance(e, openai.AuthenticationError):
        return ProviderError(n, "unauthorized", "the OpenAI API key was rejected; check it in Settings")
    if isinstance(e, openai.PermissionDeniedError):
        return ProviderError(n, "unauthorized", "this OpenAI key may not use the configured image model (organisation verification may be required)")
    if isinstance(e, openai.RateLimitError):
        return ProviderError(n, "rate_limited", "OpenAI rate limit or quota reached; try again later")
    if isinstance(e, openai.NotFoundError):
        return ProviderError(n, "unsupported", "the configured image model is not available to this key")
    if isinstance(e, (openai.APITimeoutError, openai.APIConnectionError)):
        return ProviderError(n, "unknown_outcome", "the connection to OpenAI failed before a response arrived; the image may or may "
                                                   "not have been generated (and billed)", {"error": type(e).__name__})
    if isinstance(e, openai.BadRequestError):
        msg = str(e)
        kind = "refused" if "moderation" in msg.lower() or "safety" in msg.lower() else "bad_request"
        return ProviderError(n, kind, "OpenAI refused the image request" if kind == "refused" else "OpenAI rejected the request",
                             {"message": msg[:500]})
    if isinstance(e, openai.APIStatusError) and e.status_code in GATEWAY_TIMEOUTS:
        return ProviderError(n, "unknown_outcome", f"OpenAI's gateway timed out (HTTP {e.status_code}); the image may still have been "
                                                   "generated (and billed)", {"status": e.status_code})
    if isinstance(e, openai.APIStatusError):
        return ProviderError(n, "unavailable" if e.status_code >= 500 else "bad_request", f"OpenAI API error {e.status_code}",
                             {"message": str(e)[:400]})
    return ProviderError(n, "unknown_outcome", f"unexpected error talking to OpenAI: {type(e).__name__}")


def request_size(w: int, h: int) -> str:
    """A size the GPT Image 2 family accepts (edges divisible by 16, ratio within 1:3..3:1, <= 3840x2160) that keeps the
    template's aspect ratio as closely as possible. The returned image keeps its real size; nothing is resampled."""
    ratio = max(1 / 3, min(3, w / h))
    long_edge = 1536
    if ratio >= 1:
        W, H = long_edge, long_edge / ratio
    else:
        W, H = long_edge * ratio, long_edge
    W, H = max(16, round(W / 16) * 16), max(16, round(H / 16) * 16)
    return f"{W}x{H}"


class OpenAIImageProvider(Provider):
    name = "openai"
    label = "OpenAI Images (GPT Image)"
    capabilities = ("image_generation",)

    def __init__(self):
        s = config.get()
        self.key = s.secret("OPENAI_API_KEY")
        self.model = s.image_model

    def configured(self) -> bool:
        return bool(self.key)

    def describe(self) -> dict:
        return dict(super().describe(), models={"image": self.model}, key_source=config.get().secret_source("OPENAI_API_KEY"))

    def health(self) -> dict:
        if not self.key:
            return {"status": "unconfigured", "detail": "set OPENAI_API_KEY (environment) or add the key in Settings"}
        try:
            m = _client(self.key).models.retrieve(self.model)
            return {"status": "configured", "detail": f"{m.id} available", "model": m.id}
        except Exception as e:
            pe = _classify(e)
            return {"status": pe.kind, "detail": pe.message}

    def generate(self, images: list[tuple[str, bytes, str]], prompt: str, size: str, track, quality="high") -> tuple[bytes, dict]:
        if not self.key:
            raise ProviderError(self.name, "unconfigured", "no OpenAI API key is configured")
        import openai

        files = [(name, io.BytesIO(data), mime) for name, data, mime in images]
        try:
            raw = _client(self.key).images.with_raw_response.edit(image=files, prompt=prompt, model=self.model, size=size,
                                                                quality=quality, output_format="png", n=1)
            resp = raw.parse()
            request_id = raw.headers.get("x-request-id")
        except openai.APIError as e:
            raise _classify(e)
        if not resp.data or not resp.data[0].b64_json:
            track.done(request_id, {"model": self.model, "empty": True})
            raise ProviderError(self.name, "bad_request", "OpenAI returned no image", {"request_id": request_id})
        png = base64.b64decode(resp.data[0].b64_json)
        usage = resp.usage.model_dump() if getattr(resp, "usage", None) else None
        track.done(request_id, {"model": self.model, "size": size, "usage": usage})
        return png, {"provider": self.name, "model": self.model, "request_id": request_id, "size_requested": size,
                     "revised_prompt": getattr(resp.data[0], "revised_prompt", None), "usage": usage}
