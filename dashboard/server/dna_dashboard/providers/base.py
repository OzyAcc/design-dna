"""Provider adapter contracts, error classification and paid-request bookkeeping.

A provider error says what happened in user terms: unauthorized, rate_limited, unavailable, unsupported, refused,
bad_request, or unknown_outcome (the request may have been processed: never resubmitted automatically).
Every remote request is recorded BEFORE it is sent (status `sending`), then marked received/failed/unknown. A result
used by a job is then written to a durable checkpoint (status `stored`) before anything is built from it, so a job
recovered after a crash resumes from the stored result instead of paying for the same call again (`provider_call`).
This makes a resend impossible from this application's side; it cannot prove what a provider billed when the outcome
of a request is unknown, which is why such requests stop for review instead of being retried.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

from .. import config, db
from ..errors import AppError
from ..faults import crash_point

KINDS = ("unconfigured", "unauthorized", "rate_limited", "unavailable", "unsupported", "refused", "bad_request", "unknown_outcome")
# a gateway that timed out waiting for the provider says nothing about whether the provider finished (and billed) the request
GATEWAY_TIMEOUTS = (502, 504, 524)


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
def tracked(provider: str, operation: str, model: str | None, job_id: str | None, call_key: str | None = None):
    """Record the request before sending; the handle's `done(request_id, detail)` marks it received."""
    rid = db.new_id("pq")
    conn = db.connect()
    try:
        db.insert(conn, "provider_requests", {"id": rid, "job_id": job_id, "provider": provider, "operation": operation, "model": model,
                                              "status": "sending", "call_key": call_key, "started_at": db.now()})
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


# ------------------------------------------------------------------ durable result checkpoints
def checkpoint_valid(ck) -> bool:
    """A checkpoint is usable only if its file is inside the jobs folder and still has the recorded hash."""
    if not isinstance(ck, dict) or not ck.get("path"):
        return False
    try:
        p = Path(ck["path"]).resolve()
        return (config.get().jobs.resolve() in p.parents and p.is_file()
                and hashlib.sha256(p.read_bytes()).hexdigest() == ck.get("sha256"))
    except OSError:
        return False


def _write_durable(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    try:  # make the rename itself durable
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def provider_call(job_id: str, call_key: str, provider: str, operation: str, model: str | None, fn, kind: str = "json"):
    """Make one provider call for (job, call_key) at most once, resuming from its stored result after a crash.

    `fn(track)` performs the request and returns (result, meta); `kind` is "json" (a JSON value) or "bytes" (an image).
    A stored, intact result is returned without calling the provider (meta gets `resumed_from_checkpoint`). If an
    earlier attempt of this call reached the provider but left no usable result, nothing is sent: the step stops
    with unknown_outcome (the job goes to Needs review) and only an explicit, confirmed retry sends a new request.
    """
    conn = db.connect()
    try:
        prior = db.all_(conn, "SELECT * FROM provider_requests WHERE job_id = ? AND (call_key = ? OR call_key IS NULL) "
                              "ORDER BY started_at, id", (job_id, call_key))  # NULL: recorded before call keys existed
    finally:
        conn.close()
    for p in reversed(prior):
        if p["status"] == "stored" and checkpoint_valid(p.get("checkpoint")):
            env = json.loads(Path(p["checkpoint"]["path"]).read_bytes())
            result = base64.b64decode(env["result_b64"]) if env["kind"] == "bytes" else env["result"]
            return result, dict(env["meta"], resumed_from_checkpoint=p["id"])
    reached = [p for p in prior if p["status"] in ("sending", "received", "unknown", "stored")]
    if reached:
        raise ProviderError(provider, "unknown_outcome",
                            "an earlier attempt of this step reached the provider and its result is not available here; it was not "
                            "sent again. Retry explicitly to send a new (paid) request.",
                            {"provider_requests": [{"id": p["id"], "status": p["status"]} for p in reached]})
    with tracked(provider, operation, model, job_id, call_key) as tr:
        result, meta = fn(tr)
        crash_point("after_provider_receipt")
        env = {"kind": kind, "meta": meta, "call_key": call_key, "provider_request": tr.id, "stored_at": db.now()}
        if kind == "bytes":
            env["result_b64"] = base64.b64encode(result).decode()
        else:
            env["result"] = result
        data = json.dumps(env, ensure_ascii=False, default=str).encode("utf-8")
        path = config.get().jobs / job_id / "checkpoints" / f"{tr.id}.json"
        _write_durable(path, data)
        _store(tr.id, {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "kind": kind})
    crash_point("after_checkpoint")
    return result, meta


def _store(rid, checkpoint):
    conn = db.connect()
    try:
        with db.tx(conn):
            db.update(conn, "provider_requests", rid, {"status": "stored", "checkpoint": checkpoint})
    finally:
        conn.close()
