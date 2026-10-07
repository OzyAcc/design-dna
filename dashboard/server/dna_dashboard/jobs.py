"""Durable job queue in SQLite: idempotent submission, leases with heartbeats, per-workspace locks, real stage events,
cancellation and restart recovery.

States: queued -> running -> completed | needs_review | failed | cancelled.
`needs_review` = the work ran but produced a conflict, a refused check or an unknown provider outcome that a person
must look at; `failed` = infrastructure or provider failure. Nothing here invents progress: events are written by the
handlers at the moment each stage starts or ends.
"""
from __future__ import annotations

import time

from . import db
from .errors import AppError, conflict

TERMINAL = ("completed", "needs_review", "failed", "cancelled")


def enqueue(conn, kind: str, payload: dict, *, lock_key=None, idempotency_key=None, priority=5, max_attempts=1,
            template_id=None, run_id=None, output_id=None, batch_id=None) -> dict:
    if idempotency_key:
        prev = db.one(conn, "SELECT * FROM jobs WHERE idempotency_key = ?", (idempotency_key,))
        if prev:
            return prev
    jid = db.new_id("jb")
    db.insert(conn, "jobs", {"id": jid, "kind": kind, "status": "queued", "lock_key": lock_key, "priority": priority, "input": payload,
                             "idempotency_key": idempotency_key, "max_attempts": max_attempts, "template_id": template_id,
                             "run_id": run_id, "output_id": output_id, "batch_id": batch_id, "created_at": db.now()})
    event(conn, jid, "queued", stage="queued")
    return db.one(conn, "SELECT * FROM jobs WHERE id = ?", (jid,))


def event(conn, job_id, message, stage=None, level="info", data=None) -> None:
    conn.execute("INSERT INTO job_events (job_id, at, stage, level, message, data) VALUES (?, ?, ?, ?, ?, ?)",
                 (job_id, db.now(), stage, level, message, db.dumps(data) if data is not None else None))


def get(conn, job_id) -> dict:
    j = db.one(conn, "SELECT * FROM jobs WHERE id = ?", (job_id,))
    if not j:
        raise AppError(f"job {job_id!r} was not found", "not_found", 404)
    return j


def events(conn, job_id, after=0) -> list[dict]:
    return db.all_(conn, "SELECT * FROM job_events WHERE job_id = ? AND id > ? ORDER BY id", (job_id, after))


def claim(conn, worker_id: str, lease_seconds: int) -> dict | None:
    """Atomically take the next runnable job (priority, then age), skipping locks held by running jobs."""
    with db.tx(conn):
        j = db.one(conn, """SELECT * FROM jobs WHERE status = 'queued' AND cancel_requested = 0 AND (lock_key IS NULL OR lock_key NOT IN
                             (SELECT lock_key FROM jobs WHERE status = 'running' AND lock_key IS NOT NULL))
                             ORDER BY priority, created_at LIMIT 1""")
        if not j:
            return None
        conn.execute("""UPDATE jobs SET status = 'running', lease_owner = ?, lease_expires = ?, attempts = attempts + 1,
                        started_at = COALESCE(started_at, ?) WHERE id = ? AND status = 'queued'""",
                     (worker_id, time.time() + lease_seconds, db.now(), j["id"]))
        event(conn, j["id"], f"started by {worker_id} (attempt {j['attempts'] + 1})", stage="running")
    return get(conn, j["id"])


def heartbeat(conn, job_id, worker_id, lease_seconds) -> bool:
    cur = conn.execute("UPDATE jobs SET lease_expires = ? WHERE id = ? AND lease_owner = ? AND status = 'running'",
                       (time.time() + lease_seconds, job_id, worker_id))
    return cur.rowcount == 1


def cancel_requested(conn, job_id) -> bool:
    r = conn.execute("SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return bool(r and r[0])


def set_stage(conn, job_id, stage, message=None, data=None) -> None:
    conn.execute("UPDATE jobs SET stage = ? WHERE id = ?", (stage, job_id))
    event(conn, job_id, message or stage, stage=stage, data=data)


def finish(conn, job_id, worker_id, status, result=None, error=None) -> None:
    assert status in TERMINAL
    with db.tx(conn):
        cur = conn.execute("""UPDATE jobs SET status = ?, result = ?, error = ?, finished_at = ?, lease_owner = NULL, lease_expires = NULL
                              WHERE id = ? AND (lease_owner = ? OR ? IS NULL)""",
                           (status, db.dumps(result) if result is not None else None, db.dumps(error) if error is not None else None,
                            db.now(), job_id, worker_id, worker_id))
        if cur.rowcount:
            event(conn, job_id, {"completed": "completed", "needs_review": "needs review", "failed": "failed",
                                 "cancelled": "cancelled"}[status], stage=status, level="error" if status == "failed" else "info",
                  data=error)


def request_cancel(conn, job_id) -> dict:
    with db.tx(conn):
        j = get(conn, job_id)
        if j["status"] == "queued":
            conn.execute("UPDATE jobs SET status = 'cancelled', cancel_requested = 1, finished_at = ? WHERE id = ?", (db.now(), job_id))
            event(conn, job_id, "cancelled before it started", stage="cancelled")
        elif j["status"] == "running":
            conn.execute("UPDATE jobs SET cancel_requested = 1 WHERE id = ?", (job_id,))
            event(conn, job_id, "cancellation requested; the current step will be stopped", stage=j["stage"])
    return get(conn, job_id)


def recover(conn) -> list[dict]:
    """Jobs whose worker vanished (lease expired). A job is re-queued only if re-running it cannot repeat a paid provider
    request: every request it made must have its result stored in an intact checkpoint (the re-run resumes from it). A
    request still in flight, or answered but not stored, has an outcome this application cannot use, so the job goes to
    needs_review and only an explicit, confirmed retry can send a new request."""
    from .providers.base import checkpoint_valid

    out = []
    with db.tx(conn):
        stale = db.all_(conn, "SELECT * FROM jobs WHERE status = 'running' AND lease_expires < ?", (time.time(),))
        for j in stale:
            reqs = db.all_(conn, "SELECT * FROM provider_requests WHERE job_id = ?", (j["id"],))
            for p in reqs:
                if p["status"] == "sending":
                    db.update(conn, "provider_requests", p["id"], {"status": "unknown", "finished_at": db.now(),
                                                                   "detail": {"note": "worker stopped while this request was in flight"}})
                    p["status"] = "unknown"
            unusable = [p for p in reqs if p["status"] in ("unknown", "received")
                        or (p["status"] == "stored" and not checkpoint_valid(p.get("checkpoint")))]
            if unusable:
                st = {p["status"] for p in unusable}
                msg = ("the worker stopped while a paid provider request was in flight; its outcome is unknown, " if "unknown" in st
                       else "the worker stopped after a paid provider request was answered but before its result was stored; "
                       if "received" in st else "the stored result of a paid provider request is missing or damaged; ")
                conn.execute("UPDATE jobs SET status = 'needs_review', finished_at = ?, lease_owner = NULL, error = ? WHERE id = ?",
                             (db.now(), db.dumps({"kind": "interrupted", "message": msg + "so it was not sent again. Retry explicitly to "
                                                  "send a new request.", "provider_requests": [p["id"] for p in unusable]}), j["id"]))
                event(conn, j["id"], "interrupted with a provider result that cannot be used: not resent", stage="needs_review", level="warning")
                out.append({"job": j["id"], "action": "needs_review"})
            elif j["cancel_requested"]:
                conn.execute("UPDATE jobs SET status = 'cancelled', finished_at = ?, lease_owner = NULL WHERE id = ?", (db.now(), j["id"]))
                event(conn, j["id"], "cancelled (worker stopped)", stage="cancelled")
                out.append({"job": j["id"], "action": "cancelled"})
            elif j["attempts"] >= j["max_attempts"] + 2:
                conn.execute("UPDATE jobs SET status = 'failed', finished_at = ?, lease_owner = NULL, error = ? WHERE id = ?",
                             (db.now(), db.dumps({"kind": "infrastructure", "message": "the worker stopped repeatedly during this job"}), j["id"]))
                event(conn, j["id"], "failed after repeated worker interruptions", stage="failed", level="error")
                out.append({"job": j["id"], "action": "failed"})
            else:
                stored = sum(1 for p in reqs if p["status"] == "stored")
                conn.execute("UPDATE jobs SET status = 'queued', lease_owner = NULL, lease_expires = NULL WHERE id = ?", (j["id"],))
                event(conn, j["id"], "re-queued after the worker stopped" + (f" (resumes from {stored} stored provider result(s); nothing is "
                                                                             "requested again)" if stored else " (no provider request was made)"),
                      stage="queued", level="warning")
                out.append({"job": j["id"], "action": "requeued"})
    for o in out:
        o["record"] = get(conn, o["job"])
    return out


UNSETTLED = ("sending", "unknown", "received", "stored")


def guard_paid_retry(conn, job: dict | None, confirmed: bool, delivered: bool | None = None) -> None:
    """Before an explicit retry: if the earlier attempt's provider request may have been billed (in flight or unknown,
    answered but not stored, or stored but never delivered), sending a new one needs `confirm_new_paid_request`.
    `delivered` says whether that attempt's result reached the user (default: its job completed)."""
    if not job or confirmed:
        return
    if delivered is None:
        delivered = job["status"] == "completed"
    reqs = db.all_(conn, "SELECT * FROM provider_requests WHERE job_id = ?", (job["id"],))
    # answered or stored: billed, and lost only if the attempt did not deliver (a completed output from before results
    # were stored has `received` requests)
    paid = [u for u in reqs if u["status"] in ("sending", "unknown") or (u["status"] in ("received", "stored") and not delivered)]
    if paid:
        raise conflict("the previous attempt already reached the provider (its request may have been billed) and its result was not "
                       "delivered. Confirm to send a new paid request.", "confirm_paid_retry",
                       provider_requests=[{k: u[k] for k in ("id", "provider", "operation", "status", "request_id")} for u in paid])


def latest(conn, kind: str, **scope) -> dict | None:
    (col, val), = scope.items()
    assert col in ("template_id", "batch_id")
    return db.one(conn, f"SELECT * FROM jobs WHERE kind = ? AND {col} = ? ORDER BY created_at DESC, rowid DESC LIMIT 1", (kind, val))


def public(j: dict) -> dict:
    keys = ("id", "kind", "status", "stage", "attempts", "result", "error", "template_id", "run_id", "output_id", "batch_id",
            "created_at", "started_at", "finished_at", "cancel_requested")
    return {k: j.get(k) for k in keys}
