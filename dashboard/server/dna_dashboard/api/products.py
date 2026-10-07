"""Product inputs: the tray shared by the library, template detail and the batch composer (not an inventory)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import db, intake
from ..errors import AppError, not_found
from .deps import get_conn

router = APIRouter()


def public(conn, p: dict) -> dict:
    out = dict(p)
    out["primary_asset"] = intake.public(intake.get(conn, p["primary_asset_id"])) if p.get("primary_asset_id") else None
    out["detail_assets"] = [intake.public(intake.get(conn, a)) for a in p.get("detail_asset_ids") or []]
    return out


class ProductReq(BaseModel):
    name: Optional[str] = None
    primary_asset_id: Optional[str] = None
    detail_asset_ids: Optional[list[str]] = None
    description: Optional[str] = None
    facts: Optional[list[str]] = None
    instructions: Optional[str] = None


def _check_assets(conn, body: ProductReq):
    for aid in ([body.primary_asset_id] if body.primary_asset_id else []) + (body.detail_asset_ids or []):
        a = intake.get(conn, aid)
        if a["role"] not in ("product", "detail"):
            raise AppError("product images must be added as product inputs (not as inspiration)", "wrong_role")


@router.get("/products")
def list_products(archived: int = 0, conn=Depends(get_conn)):
    rows = db.all_(conn, "SELECT * FROM products WHERE (archived_at IS NOT NULL) = ? ORDER BY updated_at DESC", (1 if archived else 0,))
    return [public(conn, p) for p in rows]


@router.post("/products")
def create(body: ProductReq, conn=Depends(get_conn)):
    _check_assets(conn, body)
    pid = db.new_id("pr")
    db.insert(conn, "products", {"id": pid, "name": (body.name or "Untitled product").strip()[:120], "primary_asset_id": body.primary_asset_id,
                                 "detail_asset_ids": body.detail_asset_ids or [], "description": (body.description or "")[:4000],
                                 "facts": [f.strip()[:300] for f in body.facts or [] if f and f.strip()][:30],
                                 "instructions": (body.instructions or "")[:4000], "created_at": db.now(), "updated_at": db.now()})
    return public(conn, db.one(conn, "SELECT * FROM products WHERE id = ?", (pid,)))


@router.patch("/products/{pid}")
def update(pid: str, body: ProductReq, conn=Depends(get_conn)):
    p = db.one(conn, "SELECT * FROM products WHERE id = ?", (pid,))
    if not p:
        raise not_found("product", pid)
    _check_assets(conn, body)
    upd = {k: v for k, v in body.model_dump().items() if v is not None}
    if "facts" in upd:
        upd["facts"] = [f.strip()[:300] for f in upd["facts"] if f and f.strip()][:30]
    upd["updated_at"] = db.now()
    with db.tx(conn):
        db.update(conn, "products", pid, upd)
    return public(conn, db.one(conn, "SELECT * FROM products WHERE id = ?", (pid,)))


@router.post("/products/{pid}/archive")
def archive(pid: str, conn=Depends(get_conn)):
    with db.tx(conn):
        db.update(conn, "products", pid, {"archived_at": db.now()})
    return {"archived": pid}
