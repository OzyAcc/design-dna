"""The job worker: a separate process (`python -m dna_dashboard worker`) running N claim loops.

Each job gets a heartbeat thread that extends its lease; a job whose worker dies is recovered by the next worker
(see jobs.recover). Handlers report stages through ctx.stage(...) and return (status, result). Engine conflicts become
needs_review with the engine's own options; engine crashes and provider failures become failed with their kind.
"""
from __future__ import annotations

import os
import shutil
import signal
import socket
import threading
import time
import traceback
from pathlib import Path

from . import config, db, jobs
from .engine import Cancelled, EngineCrash, EngineError
from .errors import AppError
from .providers import ProviderError

HANDLERS = {}


def handler(kind):
    def deco(fn):
        HANDLERS[kind] = fn
        return fn
    return deco


class Ctx:
    def __init__(self, job: dict, worker_id: str):
        self.job, self.worker_id = job, worker_id
        self.conn = db.connect()
        self.input = job["input"] or {}
        self.dir = config.get().jobs / job["id"]
        self.dir.mkdir(parents=True, exist_ok=True)
        self._last_cancel_check, self._cancel = 0.0, False

    @property
    def home(self) -> Path:
        """The job's private engine store. A re-run after a worker crash gets a fresh store; the interrupted
        attempt's store stays next to it as evidence."""
        n = int(self.job.get("attempts") or 1)
        return self.dir / ("home" if n <= 1 else f"home-attempt-{n}")

    def stage(self, name, message=None, data=None):
        if self.cancelled():
            raise Cancelled()
        jobs.set_stage(self.conn, self.job["id"], name, message, data)

    def log(self, message, level="info", data=None):
        jobs.event(self.conn, self.job["id"], message, stage=self.job.get("stage"), level=level, data=data)

    def cancelled(self) -> bool:
        if not self._cancel and time.monotonic() - self._last_cancel_check > 0.5:
            self._last_cancel_check = time.monotonic()
            self._cancel = jobs.cancel_requested(self.conn, self.job["id"])
        return self._cancel


def _heartbeat(job_id, worker_id, stop: threading.Event):
    s = config.get()
    conn = db.connect()
    try:
        while not stop.wait(max(5, s.lease_seconds / 3)):
            jobs.heartbeat(conn, job_id, worker_id, s.lease_seconds)
    finally:
        conn.close()


def execute(job: dict, worker_id: str) -> tuple[str, dict | None, dict | None]:
    fn = HANDLERS.get(job["kind"])
    if fn is None:
        return "failed", None, {"kind": "infrastructure", "message": f"no handler for job kind {job['kind']}"}
    ctx = Ctx(job, worker_id)
    stop = threading.Event()
    hb = threading.Thread(target=_heartbeat, args=(job["id"], worker_id, stop), daemon=True)
    hb.start()
    try:
        status, result = fn(ctx)
        return status, result, None
    except Cancelled:
        return "cancelled", None, {"kind": "cancelled", "message": "cancelled on request; completed files were kept"}
    except EngineError as e:
        return "needs_review", None, {"kind": "conflict", "code": e.code, "message": e.message, "detail": e.detail}
    except ProviderError as e:
        status = "needs_review" if e.kind in ("unknown_outcome", "refused") else "failed"
        return status, None, {"kind": "provider", "code": e.code, "message": e.message, "detail": e.detail}
    except EngineCrash as e:
        return "failed", None, {"kind": "infrastructure", "code": e.code, "message": e.message, "detail": e.detail}
    except AppError as e:
        return "failed", None, {"kind": "input", "code": e.code, "message": e.message, "detail": e.detail}
    except Exception as e:
        return "failed", None, {"kind": "infrastructure", "message": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-3000:]}
    finally:
        stop.set()
        ctx.conn.close()


def after_finish(job: dict, status: str, result, error) -> None:
    """Hooks that keep application records in step with job outcomes (outputs, template drafts)."""
    from . import hooks

    hooks.job_finished(job, status, result, error)


def recover() -> list[dict]:
    """Reclaim jobs whose worker died (expired lease) and bring outputs/templates in step with the new job state."""
    from . import hooks

    conn = db.connect()
    try:
        rec = jobs.recover(conn)
    finally:
        conn.close()
    for r in rec:
        j = r.pop("record")
        try:
            if r["action"] == "requeued":
                hooks.job_requeued(j)
            else:
                hooks.job_finished(j, j["status"], None, j.get("error"))
        except Exception:
            traceback.print_exc()
    return rec


def run_one(worker_id: str) -> bool:
    s = config.get()
    conn = db.connect()
    try:
        job = jobs.claim(conn, worker_id, s.lease_seconds)
    finally:
        conn.close()
    if not job:
        return False
    status, result, error = execute(job, worker_id)
    conn = db.connect()
    try:
        jobs.finish(conn, job["id"], worker_id, status, result, error)
    finally:
        conn.close()
    try:
        after_finish(job, status, result, error)
    except Exception:  # bookkeeping must not lose the job's own terminal state
        traceback.print_exc()
    if status == "completed" and not job["input"].get("keep_workdir"):
        shutil.rmtree(config.get().jobs / job["id"] / "scratch", ignore_errors=True)
    return True


def loop(worker_id: str, stop: threading.Event, poll=0.5):
    while not stop.is_set():
        try:
            if not run_one(worker_id):
                stop.wait(poll)
        except Exception:
            traceback.print_exc()
            stop.wait(2)


def main(threads: int | None = None, once=False) -> int:
    import importlib

    importlib.import_module(f"{__package__}.handlers")  # registers every job kind

    s = config.get()
    conn = db.connect()
    db.migrate(conn)
    conn.close()
    rec = recover()
    if rec:
        print(f"recovered {len(rec)} interrupted job(s): {rec}", flush=True)
    base = f"{socket.gethostname()}:{os.getpid()}"
    if once:
        while run_one(f"{base}:once"):
            pass
        return 0
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    ts = [threading.Thread(target=loop, args=(f"{base}:{i}", stop), daemon=True) for i in range(threads or s.worker_threads)]
    for t in ts:
        t.start()
    print(f"worker {base}: {len(ts)} thread(s), data {s.data_dir}", flush=True)
    last = time.time()
    while not stop.is_set():
        stop.wait(5)
        if time.time() - last > 60:  # another worker may have died: reclaim its expired leases
            recover()
            last = time.time()
    for t in ts:
        t.join(timeout=30)
    return 0
