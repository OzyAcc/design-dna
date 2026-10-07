"""TEST-ONLY providers. Enabled solely by DNA_ENABLE_MOCK_PROVIDERS=1; every result carries mock=true and the UI shows
a warning banner. They exist so the integration tests can exercise the job system without paid requests; they are
never a production success path.

The mock analysis does real, simple pixel work (connected ink regions on the canonical image) so the downstream
measurement tools receive plausible regions; it labels everything as mock proposals.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .base import Provider, ProviderError


class MockProvider(Provider):
    name = "mock"
    label = "Mock provider (tests only)"
    capabilities = ("analysis", "copy", "image_generation")
    mock = True

    def __init__(self, fail: str | None = None):
        self.fail = fail

    def configured(self) -> bool:
        return True

    def health(self) -> dict:
        return {"status": "configured", "detail": "mock provider for tests: results are labelled mock"}

    def analyze(self, png: bytes, brief: dict, track):
        if self.fail:
            raise ProviderError(self.name, self.fail, f"mock failure: {self.fail}")
        im = np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).astype(int)
        H, W = im.shape[:2]
        bg = np.median(np.concatenate([im[0], im[-1], im[:, 0], im[:, -1]]), axis=0)
        ink = np.abs(im - bg).max(axis=2) > 40
        rows = ink.any(axis=1)
        bands, start = [], None
        for y, v in enumerate(list(rows) + [False]):
            if v and start is None:
                start = y
            elif not v and start is not None:
                if y - start > 4:
                    bands.append((start, y))
                start = None
        elements = [{"key": "bg", "type": "background", "role": "background", "bbox": [0, 0, W, H], "text": "", "align": "left",
                     "slot": False, "confidence": "low", "note": "mock"}]
        for i, (y0, y1) in enumerate(bands[:6]):
            cols = np.nonzero(ink[y0:y1].any(axis=0))[0]
            x0, x1 = int(cols.min()), int(cols.max()) + 1
            elements.append({"key": f"e{i + 1}", "type": "text" if (y1 - y0) < 0.12 * H else "image",
                             "role": "headline" if i == 0 else ("body" if (y1 - y0) < 0.12 * H else "product"),
                             "bbox": [max(0, x0 - 4), max(0, y0 - 4), min(W, x1 + 4) - max(0, x0 - 4), min(H, y1 + 4) - max(0, y0 - 4)],
                             "text": "", "align": "left", "slot": True, "confidence": "low", "note": "mock band"})
        track.done("mock-request", {"mock": True})
        return ({"suggested_name": "Mock template", "elements": elements,
                 "palette": [{"role": "background.base", "sample_box": [4, 4, 24, 24], "hex_hint": "", "note": "mock"}],
                 "composition": {"grid": "mock", "spacing": "mock", "alignment": "mock", "whitespace": "mock"},
                 "image_treatment": "mock", "depth": "mock", "surface": "mock", "lighting": "mock", "hierarchy": [e["key"] for e in elements[1:]],
                 "communication": {"goal": "mock goal", "literal_message": "mock", "takeaway": "mock", "cta": "",
                                   "word_image_relationship": "none",
                                   "mechanisms": [{"chain": ["mock visible choice", "mock attention", "mock takeaway", "mock action"],
                                                   "competing": [], "confidence": "low"}]},
                 "character_theme": "mock", "usage_context": "mock", "uncertainties": ["mock provider: nothing here is real analysis"]},
                {"provider": "mock", "model": "mock", "request_id": "mock-request", "mock": True})

    def draft_copy(self, request: dict, track):
        if self.fail:
            raise ProviderError(self.name, self.fail, f"mock failure: {self.fail}")
        drafts = []
        for o in request.get("outputs", []):
            for sl in o.get("slots", []):
                drafts.append({"pair_id": o["pair_id"], "slot_id": sl["slot_id"],
                               "text": f"[mock] {o['product']['name']} {sl['role']}"[: sl.get("max_chars") or 60], "note": "mock draft"})
        track.done("mock-copy", {"mock": True})
        return {"drafts": drafts}, {"provider": "mock", "model": "mock", "request_id": "mock-copy", "mock": True}

    def generate(self, images, prompt, size, track, quality="high"):
        if self.fail:
            raise ProviderError(self.name, self.fail, f"mock failure: {self.fail}")
        w, h = (int(v) for v in size.split("x"))
        base = Image.open(io.BytesIO(images[-1][1])).convert("RGB").resize((w, h)).filter(ImageFilter.GaussianBlur(3))
        d = ImageDraw.Draw(base)
        d.rectangle([0, 0, w, 36], fill="#C8102E")
        d.text((10, 10), "MOCK GENERATION - TEST ONLY", fill="white")
        buf = io.BytesIO()
        base.save(buf, "PNG")
        track.done("mock-image", {"mock": True})
        return buf.getvalue(), {"provider": "mock", "model": "mock", "request_id": "mock-image", "size_requested": size, "mock": True}
