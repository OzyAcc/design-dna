"""Asset intake routes for both roles: upload (multi-file), clipboard paste (same validation), links, page images."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel

from .. import config, db, intake, netfetch
from ..errors import AppError
from .deps import file_response, get_conn

router = APIRouter()


async def _read_limited(f: UploadFile) -> bytes:
    limit = config.get().max_upload_bytes
    chunks, total = [], 0
    while True:
        chunk = await f.read(1 << 20)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise AppError(f"{intake.safe_name(f.filename)} is larger than {limit / 1e6:.0f} MB", "too_large", 413)
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/assets/upload")
async def upload(files: list[UploadFile] = File(...), role: str = Form(...), source_kind: str = Form("upload"),
                 conn=Depends(get_conn)):
    if source_kind not in ("upload", "paste"):
        raise AppError("source_kind must be upload or paste", "bad_source")
    if len(files) > 20:
        raise AppError("add at most 20 files at a time", "too_many_files")
    out, errors = [], []
    for f in files:
        try:
            data = await _read_limited(f)
            out.append(intake.ingest(data, role=role, original_name=f.filename, source_kind=source_kind, conn=conn))
        except AppError as e:
            errors.append({"file": intake.safe_name(f.filename), "code": e.code, "message": e.message, "status": e.status})
    if not out and errors:
        raise AppError(errors[0]["message"], errors[0]["code"], errors[0]["status"], {"errors": errors})
    return {"assets": out, "errors": errors}


class LinkReq(BaseModel):
    url: str
    role: str


@router.post("/assets/link")
def link(body: LinkReq, conn=Depends(get_conn)):
    res = netfetch.resolve_link(body.url)
    if res["kind"] == "image":
        f = res["fetched"]
        name = f.url.split("?")[0].rstrip("/").split("/")[-1] or "linked-image"
        a = intake.ingest(f.data, role=body.role, original_name=name, source_kind="link", source_url=f.url, conn=conn,
                          provenance={"kind": "link", "requested_url": body.url, "final_url": f.url, "redirects": f.redirects,
                                      "content_type": f.content_type, "fetched_at": db.now()})
        return {"kind": "image", "asset": a}
    return res


class PageImageReq(BaseModel):
    url: str
    role: str
    page_url: str
    title: Optional[str] = None
    site_name: Optional[str] = None
    declared_by: Optional[str] = None
    alt: Optional[str] = None


@router.post("/assets/page-image")
def page_image(body: PageImageReq, conn=Depends(get_conn)):
    f = netfetch.fetch(body.url, accept="image/*")
    name = f.url.split("?")[0].rstrip("/").split("/")[-1] or "page-image"
    a = intake.ingest(f.data, role=body.role, original_name=name, source_kind="page_image", source_url=f.url, page_url=body.page_url,
                      conn=conn, provenance={"kind": "page_image", "page_url": body.page_url, "page_title": (body.title or "")[:200],
                                             "site_name": (body.site_name or "")[:120], "declared_by": body.declared_by, "alt": (body.alt or "")[:200],
                                             "image_url": f.url, "fetched_at": db.now(),
                                             "note": "an image the page declares; not a capture or recovery of the page's design"})
    return {"asset": a}


@router.get("/assets/{asset_id}")
def get(asset_id: str, conn=Depends(get_conn)):
    return intake.public(intake.get(conn, asset_id))


@router.get("/assets/{asset_id}/preview")
def preview(asset_id: str, conn=Depends(get_conn)):
    return file_response(intake.canonical_file(intake.get(conn, asset_id)))


@router.get("/assets/{asset_id}/thumb")
def thumb(asset_id: str, conn=Depends(get_conn)):
    return file_response(intake.thumb_path(intake.get(conn, asset_id)["sha256"]))


@router.get("/assets/{asset_id}/original")
def original(asset_id: str, conn=Depends(get_conn)):
    a = intake.get(conn, asset_id)
    return file_response(intake.original_file(a), a["original_name"], inline=False)
