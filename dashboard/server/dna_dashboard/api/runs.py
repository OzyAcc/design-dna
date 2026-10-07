"""Runs and outputs: review, scoped retry (new output revisions), cancellation, downloads and ZIP exports."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from .. import config, db, exports, jobs
from ..errors import AppError, conflict, not_found
from .deps import file_response, get_conn

router = APIRouter()


def public_output(o: dict) -> dict:
    out = {k: o.get(k) for k in ("id", "run_id", "pair_id", "revision", "parent_output_id", "product_id", "template_id", "template_version_id",
                                 "mode", "language", "status", "review_state", "checks", "limitations", "error", "created_at", "updated_at", "job_id")}
    out["inputs"] = o["inputs"]
    out["provenance"] = o.get("provenance")
    out["files"] = [{k: f.get(k) for k in ("kind", "name", "sha256", "bytes", "width", "height")} | {"url": f"/api/outputs/{o['id']}/files/{i}"}
                    for i, f in enumerate(o.get("files") or [])]
    return out


def run_summary(conn, r: dict) -> dict:
    outs = db.all_(conn, "SELECT * FROM outputs WHERE run_id = ? ORDER BY created_at", (r["id"],))
    latest = {}
    for o in outs:
        cur = latest.get(o["pair_id"])
        if not cur or o["revision"] > cur["revision"]:
            latest[o["pair_id"]] = o
    counts = {}
    for o in latest.values():
        counts[o["status"]] = counts.get(o["status"], 0) + 1
    active = any(s in counts for s in ("queued", "running"))
    status = "running" if active else ("needs_review" if counts.get("needs_review") or counts.get("failed") else "completed")
    if not active and counts and set(counts) == {"cancelled"}:
        status = "cancelled"
    return {"id": r["id"], "batch_id": r["batch_id"], "name": r["name"], "created_at": r["created_at"], "status": status, "counts": counts,
            "outputs": len(latest)}


@router.get("/runs")
def list_runs(conn=Depends(get_conn)):
    return [run_summary(conn, r) for r in db.all_(conn, "SELECT * FROM runs ORDER BY created_at DESC LIMIT 200")]


@router.get("/runs/{rid}")
def get_run(rid: str, conn=Depends(get_conn)):
    r = db.one(conn, "SELECT * FROM runs WHERE id = ?", (rid,))
    if not r:
        raise not_found("run", rid)
    outs = db.all_(conn, "SELECT * FROM outputs WHERE run_id = ? ORDER BY created_at", (rid,))
    return dict(run_summary(conn, r), outputs=[public_output(o) for o in outs], snapshot_submitted_at=(r["snapshot"] or {}).get("submitted_at"))


@router.get("/outputs/{oid}")
def get_output(oid: str, conn=Depends(get_conn)):
    o = db.one(conn, "SELECT * FROM outputs WHERE id = ?", (oid,))
    if not o:
        raise not_found("output", oid)
    out = public_output(o)
    out["revisions"] = [{"id": x["id"], "revision": x["revision"], "status": x["status"]}
                        for x in db.all_(conn, "SELECT id, revision, status FROM outputs WHERE run_id = ? AND pair_id = ? ORDER BY revision",
                                         (o["run_id"], o["pair_id"]))]
    if o.get("job_id"):
        out["events"] = jobs.events(conn, o["job_id"])
        out["provider_requests"] = db.all_(conn, "SELECT id, provider, operation, model, status, request_id, started_at, finished_at "
                                                 "FROM provider_requests WHERE job_id = ?", (o["job_id"],))
    return out


@router.get("/outputs/{oid}/files/{index}")
def output_file(oid: str, index: int, download: int = 0, conn=Depends(get_conn)):
    o = db.one(conn, "SELECT * FROM outputs WHERE id = ?", (oid,))
    if not o:
        raise not_found("output", oid)
    files = o.get("files") or []
    if not 0 <= index < len(files):
        raise AppError("no such file", "missing_file", 404)
    from pathlib import Path

    p = Path(files[index]["path"]).resolve()
    if config.get().outputs.resolve() not in p.parents:
        raise AppError("no such file", "missing_file", 404)
    return file_response(p, Path(files[index]["name"]).name, inline=not download)


class ReviewReq(BaseModel):
    state: str
    confirm_text: bool = False


@router.post("/outputs/{oid}/review")
def review(oid: str, body: ReviewReq, conn=Depends(get_conn)):
    if body.state not in ("approved", "rejected", "unreviewed"):
        raise AppError("state must be approved, rejected or unreviewed", "bad_state")
    o = db.one(conn, "SELECT * FROM outputs WHERE id = ?", (oid,))
    if not o:
        raise not_found("output", oid)
    if body.state == "approved" and o["status"] != "completed":
        raise conflict("only a completed output can be approved; refused or failed candidates stay review artifacts", "not_approvable")
    text = (o.get("checks") or {}).get("text") or {}
    if body.state == "approved" and text.get("policy") == "in_image" and not body.confirm_text:
        raise conflict("the image model drew this output's text: confirm it matches the approved copy before approving", "confirm_text",
                       requested=text.get("requested"))
    with db.tx(conn):
        db.update(conn, "outputs", oid, {"review_state": body.state, "updated_at": db.now()})
    return public_output(db.one(conn, "SELECT * FROM outputs WHERE id = ?", (oid,)))


class RetryReq(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    copy_values: Optional[dict[str, Optional[str]]] = Field(None, alias="copy")
    instructions: Optional[list[str]] = None
    confirm_new_paid_request: bool = False
    idempotency_key: str


@router.post("/outputs/{oid}/retry")
def retry(oid: str, body: RetryReq, conn=Depends(get_conn)):
    """A scoped retry or a regeneration with revised copy: a NEW output revision with its own job. The original is kept.
    If the previous attempt's paid provider request has an unknown outcome, sending again needs explicit confirmation."""
    o = db.one(conn, "SELECT * FROM outputs WHERE id = ?", (oid,))
    if not o:
        raise not_found("output", oid)
    if o["status"] in ("queued", "running"):
        raise conflict("this output is still being generated", "still_running")
    dup = db.one(conn, "SELECT id FROM jobs WHERE idempotency_key = ?", (f"retry:{body.idempotency_key}",))
    if dup:
        x = db.one(conn, "SELECT id FROM outputs WHERE job_id = ?", (dup["id"],))
        return {"output_id": x["id"] if x else None, "duplicate": True}
    child = db.one(conn, "SELECT id FROM outputs WHERE parent_output_id = ? AND status IN ('queued', 'running')", (oid,))
    if child:  # e.g. a retry whose answer was lost: never a second paid request for one intent
        raise conflict("a retry of this output is already queued or running", "retry_in_progress", output_id=child["id"])
    job = db.one(conn, "SELECT * FROM jobs WHERE id = ?", (o["job_id"],)) if o.get("job_id") else None
    jobs.guard_paid_retry(conn, job, body.confirm_new_paid_request, delivered=o["status"] == "completed")
    inputs = dict(o["inputs"])
    changed = []
    from ..handlers.output_jobs import copy_used

    if body.copy_values and not copy_used(o):
        raise AppError("this output generates imagery only, so revised copy would not be used: choose a text policy in the composer "
                       "and generate it again", "copy_not_used")
    if body.copy_values:
        slots = []
        for e in inputs["slots"]:
            e = dict(e)
            if e["slot_id"] in body.copy_values:
                v = body.copy_values[e["slot_id"]]
                if e["locked"]:
                    raise AppError(f"{e['role']} is locked by the template", "locked_slot")
                if v is not None and v != e["value"]:
                    e.update(value=v, source="manual (revision)", hidden=(v == "" and not e["required"]))
                    if v == "" and e["required"]:
                        raise AppError(f"{e['role']} is required and cannot be empty", "required_slot")
                    changed.append(e["slot_id"])
            slots.append(e)
        inputs["slots"] = slots
    if body.instructions is not None:
        inputs["instructions"] = body.instructions
        changed.append("instructions")
    rev = conn.execute("SELECT MAX(revision) FROM outputs WHERE run_id = ? AND pair_id = ?", (o["run_id"], o["pair_id"])).fetchone()[0] + 1
    nid = db.new_id("op")
    with db.tx(conn):
        db.insert(conn, "outputs", {"id": nid, "run_id": o["run_id"], "pair_id": o["pair_id"], "revision": rev, "parent_output_id": o["id"],
                                    "product_id": o["product_id"], "template_id": o["template_id"], "template_version_id": o["template_version_id"],
                                    "mode": o["mode"], "language": o["language"], "inputs": dict(inputs, revised=changed), "status": "queued",
                                    "created_at": db.now(), "updated_at": db.now()})
        j = jobs.enqueue(conn, "output.generate", {"output_id": nid}, idempotency_key=f"retry:{body.idempotency_key}", run_id=o["run_id"],
                         output_id=nid, priority=4)
        db.update(conn, "outputs", nid, {"job_id": j["id"]})
    return {"output_id": nid, "revision": rev, "changed": changed, "duplicate": False}


@router.post("/outputs/{oid}/cancel")
def cancel_output(oid: str, conn=Depends(get_conn)):
    o = db.one(conn, "SELECT * FROM outputs WHERE id = ?", (oid,))
    if not o or not o.get("job_id"):
        raise not_found("output", oid)
    j = jobs.request_cancel(conn, o["job_id"])
    if j["status"] == "cancelled":
        with db.tx(conn):
            db.update(conn, "outputs", oid, {"status": "cancelled", "updated_at": db.now()})
    return jobs.public(j)


@router.post("/runs/{rid}/cancel")
def cancel_run(rid: str, conn=Depends(get_conn)):
    out = []
    for o in db.all_(conn, "SELECT * FROM outputs WHERE run_id = ? AND status IN ('queued', 'running')", (rid,)):
        j = jobs.request_cancel(conn, o["job_id"])
        if j["status"] == "cancelled":
            with db.tx(conn):
                db.update(conn, "outputs", o["id"], {"status": "cancelled", "updated_at": db.now()})
        out.append({"output_id": o["id"], "job": j["status"]})
    return {"cancelled": out}


class ZipReq(BaseModel):
    output_ids: Optional[list[str]] = None
    include_evidence: bool = True


@router.post("/runs/{rid}/zip")
def run_zip(rid: str, body: ZipReq, conn=Depends(get_conn)):
    r = db.one(conn, "SELECT * FROM runs WHERE id = ?", (rid,))
    if not r:
        raise not_found("run", rid)
    if body.output_ids:
        ids = body.output_ids
        bad = [i for i in ids if not db.one(conn, "SELECT id FROM outputs WHERE id = ? AND run_id = ?", (i, rid))]
        if bad:
            raise AppError("some outputs are not part of this run", "bad_selection", 400, {"outputs": bad})
    else:
        latest = {}
        for o in db.all_(conn, "SELECT * FROM outputs WHERE run_id = ? ORDER BY revision", (rid,)):
            latest[o["pair_id"]] = o
        ids = [o["id"] for o in latest.values() if o["status"] == "completed"]
        if not ids:
            raise AppError("no completed outputs to download yet", "nothing_completed")
    data, name = exports.build_zip(conn, ids, body.include_evidence, label=f"{rid}")
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"',
                                                                  "X-Content-Type-Options": "nosniff"})
