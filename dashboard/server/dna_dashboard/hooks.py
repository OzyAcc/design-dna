"""Keep application records consistent with job outcomes the handlers could not record themselves
(a handler that raised, a cancelled or recovered job)."""
from __future__ import annotations

from . import db


def job_finished(job: dict, status: str, result, error) -> None:
    conn = db.connect()
    try:
        if job.get("output_id"):
            o = db.one(conn, "SELECT status FROM outputs WHERE id = ?", (job["output_id"],))
            if o and o["status"] in ("queued", "running"):
                with db.tx(conn):
                    db.update(conn, "outputs", job["output_id"], {"status": status, "error": error, "updated_at": db.now()})
        if job["kind"].startswith("template.") and job.get("template_id"):
            t = db.one(conn, "SELECT draft, draft_revision FROM templates WHERE id = ?", (job["template_id"],))
            if t:
                d = dict(t["draft"] or {})
                if status in ("failed", "needs_review", "cancelled"):
                    d["last_job_problem"] = {"job_id": job["id"], "kind": job["kind"], "status": status, "error": error,
                                             "result": result, "at": db.now()}
                else:
                    d.pop("last_job_problem", None)
                with db.tx(conn):
                    db.update(conn, "templates", job["template_id"], {"draft": d, "draft_revision": t["draft_revision"] + 1})
    finally:
        conn.close()


def job_requeued(job: dict) -> None:
    """A job re-queued after its worker stopped: its output waits again (no files were promised)."""
    if not job.get("output_id"):
        return
    conn = db.connect()
    try:
        o = db.one(conn, "SELECT status FROM outputs WHERE id = ?", (job["output_id"],))
        if o and o["status"] == "running":
            with db.tx(conn):
                db.update(conn, "outputs", job["output_id"], {"status": "queued", "updated_at": db.now()})
    finally:
        conn.close()
