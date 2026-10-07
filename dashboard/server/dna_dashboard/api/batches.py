"""Batch composer routes: selection, defaults, per-output editors, bulk apply, AI drafts, previews and submission."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from .. import batches, db, jobs
from ..errors import AppError
from .deps import file_response, get_conn

router = APIRouter()


class BatchReq(BaseModel):
    name: Optional[str] = None
    template_versions: list[dict] = []
    product_ids: list[str] = []
    defaults: Optional[dict] = None


@router.get("/batches")
def list_batches(conn=Depends(get_conn)):
    return [batches.public(b) for b in db.all_(conn, "SELECT * FROM batches ORDER BY updated_at DESC LIMIT 50")]


@router.post("/batches")
def create(body: BatchReq, conn=Depends(get_conn)):
    tv = []
    from .. import templates_svc as ts

    for x in body.template_versions:
        v = ts.version(conn, x["version_id"])
        tv.append({"template_id": v["template_id"], "version_id": v["id"]})
    b = batches.create(conn, body.name or "Untitled batch", tv, body.product_ids, body.defaults)
    return batches.matrix(conn, b["id"])


@router.get("/batches/{bid}")
def get(bid: str, conn=Depends(get_conn)):
    return batches.matrix(conn, bid)


class UpdateReq(BaseModel):
    base_revision: int
    changes: dict[str, Any]


@router.patch("/batches/{bid}")
def update(bid: str, body: UpdateReq, conn=Depends(get_conn)):
    batches.update(conn, bid, body.base_revision, body.changes)
    return batches.matrix(conn, bid)


@router.patch("/batches/{bid}/pairs/{pid}")
def set_pair(bid: str, pid: str, body: dict[str, Any], conn=Depends(get_conn)):
    batches.set_pair(conn, bid, pid, body)
    return batches.matrix(conn, bid)


class BulkReq(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    scope: dict
    copy_values: Optional[dict[str, Optional[str]]] = Field(None, alias="copy")
    instructions: Optional[str] = None


@router.post("/batches/{bid}/apply")
def bulk(bid: str, body: BulkReq, conn=Depends(get_conn)):
    batches.bulk_apply(conn, bid, body.scope, body.copy_values, body.instructions)
    return batches.matrix(conn, bid)


class VariantReq(BaseModel):
    product_id: str
    template_id: str


@router.post("/batches/{bid}/variants")
def add_variant(bid: str, body: VariantReq, conn=Depends(get_conn)):
    batches.add_variant(conn, bid, body.product_id, body.template_id)
    return batches.matrix(conn, bid)


@router.post("/batches/{bid}/pairs/{pid}/use-draft/{slot_id}")
def use_draft(bid: str, pid: str, slot_id: str, conn=Depends(get_conn)):
    batches.use_ai_draft(conn, bid, pid, slot_id)
    return batches.matrix(conn, bid)


@router.post("/batches/{bid}/pairs/{pid}/approve/{slot_id}")
def approve(bid: str, pid: str, slot_id: str, conn=Depends(get_conn)):
    batches.approve_slot(conn, bid, pid, slot_id)
    return batches.matrix(conn, bid)


class MapReq(BaseModel):
    mapping: dict[str, Optional[str]] = {}


@router.post("/batches/{bid}/pairs/{pid}/confirm-version")
def confirm_version(bid: str, pid: str, body: MapReq, conn=Depends(get_conn)):
    batches.confirm_version(conn, bid, pid, body.mapping)
    return batches.matrix(conn, bid)


@router.post("/batches/{bid}/pairs/{pid}/preview")
def preview(bid: str, pid: str, conn=Depends(get_conn)):
    b = batches.get(conn, bid)
    p = batches.get_pair(conn, bid, pid)
    r = batches.resolve(conn, b, p)
    if r["mode"] == "creative":
        raise AppError("creative generation has no deterministic preview; its result is reviewed after generation", "no_preview")
    if r.get("image") and not r["image"].get("asset_id"):
        raise AppError("the product has no primary image", "no_image")
    j = jobs.enqueue(conn, "pair.preview", {"batch_id": bid, "pair_id": pid, "inputs_hash": r["inputs_hash"]}, priority=2,
                     idempotency_key=f"preview:{pid}:{r['inputs_hash']}:{db.now()[:16]}", batch_id=bid)
    return jobs.public(j)


@router.get("/batches/{bid}/pairs/{pid}/preview.png")
def preview_png(bid: str, pid: str, conn=Depends(get_conn)) -> FileResponse:
    p = batches.get_pair(conn, bid, pid)
    png = (p.get("preview") or {}).get("png")
    if not png:
        raise AppError("no preview has been rendered for this output", "missing_file", 404)
    return file_response(png)


class DraftReq(BaseModel):
    pair_ids: list[str]
    slot_ids: Optional[list[str]] = None


@router.post("/batches/{bid}/draft-copy")
def draft_copy(bid: str, body: DraftReq, conn=Depends(get_conn)):
    from ..providers import for_capability

    for_capability("copy")
    if not body.pair_ids:
        raise AppError("choose the outputs to draft copy for", "nothing_selected")
    for pid in body.pair_ids:
        batches.get_pair(conn, bid, pid)
    return jobs.public(jobs.enqueue(conn, "batch.draft_copy", {"batch_id": bid, "pair_ids": body.pair_ids, "slot_ids": body.slot_ids},
                                    priority=3, batch_id=bid))


class SubmitReq(BaseModel):
    idempotency_key: str
    name: Optional[str] = None


@router.post("/batches/{bid}/submit")
def submit(bid: str, body: SubmitReq, conn=Depends(get_conn)):
    return batches.submit(conn, bid, body.idempotency_key, body.name)
