"""Provider adapter contracts, error classification and paid-request bookkeeping.

A provider error says what happened in user terms: unauthorized, rate_limited, unavailable, unsupported, refused,
bad_request, or unknown_outcome (the request may have been processed: never resubmitted automatically).
Every remote request is recorded BEFORE it is sent (status `sending`), then marked received/failed/unknown.
"""
from __future__ import annotations

import time
from contextlib import contextmanager

from .. import db
from ..errors import AppError

KINDS = ("unconfigured", "unauthorized", "rate_limited", "unavailable", "unsupported", "refused", "bad_request", "unknown_outcome")


class ProviderError(AppError):
    def __init__(self, provider: str, kind: str, message: str, detail: dict | None = None):
        status = {"unconfigured": 412, "unauthorized": 401, "rate_limited": 429, "unsupported": 422, "refused": 422}.get(kind, 502)
        super().__init__(message, f"provider_{kind}", status, dict(detail or {}, provider=provider, kind=kind))
        self.provider, self.kind = provider, kind


class Provider:
    name = "provider"
    label = "Provider"
    capabilities: tuple[str, ...] = ()
    mock = False

    def configured(self) -> bool:
        raise NotImplementedError

    def health(self) -> dict:
        raise NotImplementedError

    def describe(self) -> dict:
        return {"name": self.name, "label": self.label, "capabilities": list(self.capabilities), "configured": self.configured(),
                "mock": self.mock}


_HEALTH: dict[str, dict] = {}


def cached_health(p: Provider, force=False) -> dict:
    h = _HEALTH.get(p.name)
    if force or not h or time.time() - h["_at"] > 300:
        try:
            h = p.health()
        except ProviderError as e:
            h = {"status": e.kind, "detail": e.message}
        h["_at"] = time.time()
        h["checked_at"] = db.now()
        _HEALTH[p.name] = h
    return {k: v for k, v in h.items() if k != "_at"}


@contextmanager
def tracked(provider: str, operation: str, model: str | None, job_id: str | None):
    """Record the request before sending; the handle's `done(request_id, detail)` marks it received."""
    rid = db.new_id("pq")
    conn = db.connect()
    try:
        db.insert(conn, "provider_requests", {"id": rid, "job_id": job_id, "provider": provider, "operation": operation, "model": model,
                                              "status": "sending", "started_at": db.now()})
    finally:
        conn.close()

    class Handle:
        id = rid
        request_id = None

        def done(self, request_id=None, detail=None):
            self.request_id = request_id
            _mark(rid, "received", request_id, detail)

    h = Handle()
    try:
        yield h
    except ProviderError as e:
        _mark(rid, "unknown" if e.kind == "unknown_outcome" else "failed", None, {"kind": e.kind, "message": e.message})
        raise
    except Exception as e:
        _mark(rid, "unknown", None, {"error": f"{type(e).__name__}: {str(e)[:300]}"})
        raise


def _mark(rid, status, request_id, detail):
    conn = db.connect()
    try:
        db.update(conn, "provider_requests", rid, {"status": status, "request_id": request_id, "detail": detail or {}, "finished_at": db.now()})
    finally:
        conn.close()
