"""Jobs (status, events, cancel), runtime capabilities, providers, credentials and the font library."""
from __future__ import annotations

import hashlib
from typing import Optional

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel

from .. import __version__, config, db, engine, jobs
from .. import enginelib as el
from ..errors import AppError
from ..providers import all_providers, cached_health
from .deps import get_conn

router = APIRouter()


@router.get("/health")
def health():
    return {"ok": True, "version": __version__}


@router.get("/jobs/{jid}")
def job(jid: str, after: int = 0, conn=Depends(get_conn)):
    j = jobs.get(conn, jid)
    return dict(jobs.public(j), events=jobs.events(conn, jid, after))


@router.post("/jobs/{jid}/cancel")
def cancel(jid: str, conn=Depends(get_conn)):
    return jobs.public(jobs.request_cancel(conn, jid))


@router.get("/jobs")
def recent_jobs(status: str = "", conn=Depends(get_conn)):
    if status:
        rows = db.all_(conn, "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT 100", (status,))
    else:
        rows = db.all_(conn, "SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100")
    return [jobs.public(j) for j in rows]


@router.get("/runtime")
def runtime(refresh: int = 0, conn=Depends(get_conn)):
    s = config.get()
    caps = engine.capabilities(force=bool(refresh))
    last = db.one(conn, "SELECT MAX(started_at) AS t FROM jobs WHERE lease_owner IS NOT NULL OR started_at IS NOT NULL")
    queued = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'queued'").fetchone()[0]
    running = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'running'").fetchone()[0]
    return {"version": __version__, "engine": caps, "python": engine.python_info(), "data_dir": str(s.data_dir),
            "auth_required": bool(s.auth_token), "bind": f"{s.host}:{s.port}", "mock_providers_enabled": s.enable_mock_providers,
            "queue": {"queued": queued, "running": running, "last_started": last["t"] if last else None},
            "limits": {"upload_mb": s.max_upload_bytes // 1_000_000, "megapixels": s.max_pixels // 1_000_000,
                       "link_timeout_s": s.fetch_timeout, "link_mb": s.fetch_max_bytes // 1_000_000},
            "adapters": {"raster_intake": "implemented", "web_page_image_picker": "implemented (declared images only)",
                         "pdf_psd_figma_ai_motion_3d": "unavailable: no adapter", "background_removal": "unavailable: no adapter",
                         "ocr": "unavailable: transcriptions are reviewed by a person (optionally proposed by Claude)"}}


@router.get("/providers")
def providers(check: int = 0):
    out = []
    for p in all_providers():
        d = p.describe()
        d["health"] = cached_health(p, force=bool(check)) if (check or p.configured()) else {"status": "unconfigured",
                                                                                             "detail": "no key configured"}
        out.append(d)
    return out


class SecretReq(BaseModel):
    name: str
    value: Optional[str] = None


@router.put("/providers/credentials")
def set_secret(body: SecretReq):
    s = config.get()
    if body.name not in config.SECRET_KEYS:
        raise AppError("unknown credential", "bad_secret")
    if s.secret_source(body.name) == "environment":
        raise AppError("this key comes from the server environment; change it there", "env_secret")
    s.save_secret(body.name, (body.value or "").strip() or None)
    from ..providers import base

    base._HEALTH.clear()
    return {"name": body.name, "configured": bool(s.secret(body.name)), "source": s.secret_source(body.name)}


HELP_IMAGES = {"how-it-works.png", "case-inspiration-to-template.png", "case-template-adaptation.png", "case-soft-form.png",
               "change-one-thing.png", "every-claim-has-a-source.png", "same-browser-same-pixels.png", "take-your-template-anywhere.png",
               "use-it-in-your-ai-tool.png"}


@router.get("/help/{name}")
def help_image(name: str):
    """The repository's explainer illustrations (concepts, not screenshots or measured templates)."""
    from .deps import file_response

    if name not in HELP_IMAGES:
        raise AppError("unknown help image", "not_found", 404)
    return file_response(config.REPO_ROOT / "docs" / "images" / name)


@router.get("/fonts")
def fonts():
    return [{k: f[k] for k in ("sha256", "names", "weight", "source")} for f in el.font_library()]


@router.post("/fonts")
async def upload_font(file: UploadFile = File(...)):
    data = await file.read(20 * 1024 * 1024 + 1)
    if len(data) > 20 * 1024 * 1024:
        raise AppError("font files are limited to 20 MB", "too_large", 413)
    if data[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        raise AppError("only TrueType (.ttf) or OpenType (.otf) font files are accepted", "bad_font", 415)
    sha = hashlib.sha256(data).hexdigest()
    ext = ".otf" if data[:4] == b"OTTO" else ".ttf"
    dst = config.get().fonts / f"{sha[:16]}{ext}"
    if not dst.exists():
        tmp = dst.with_suffix(".part")
        tmp.write_bytes(data)
        try:
            names = el.font_names(tmp)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise AppError("the font file could not be read", "bad_font", 415)
        tmp.rename(dst)
    else:
        names = el.font_names(dst)
    return {"sha256": sha, "names": names, "note": "check the font's licence before sharing bundles that embed it"}
