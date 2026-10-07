"""Shared request dependencies: a database connection per request and safe file responses."""
from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi.responses import FileResponse

from .. import db
from ..errors import AppError

SAFE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
              ".bmp": "image/bmp", ".tif": "image/tiff", ".tiff": "image/tiff", ".svg": "image/svg+xml", ".json": "application/json",
              ".md": "text/markdown; charset=utf-8", ".dnab": "application/zip", ".zip": "application/zip"}


def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def file_response(path: Path, download_name: str | None = None, inline=True) -> FileResponse:
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise AppError("that file does not exist (it may not have been produced)", "missing_file", 404)
    ctype = SAFE_TYPES.get(p.suffix.lower()) or mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=60"}
    if p.suffix.lower() == ".svg":
        headers["Content-Security-Policy"] = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:; sandbox"
    disp = "inline" if inline else "attachment"
    if download_name or not inline:
        safe = "".join(c for c in (download_name or p.name) if c.isalnum() or c in "._-@ ")[:150] or "download"
        headers["Content-Disposition"] = f'{disp}; filename="{safe}"'
    return FileResponse(p, media_type=ctype, headers=headers)


def under(base: Path, rel: str) -> Path:
    """Resolve a client-supplied relative path strictly inside base (no traversal, no absolute paths)."""
    if not rel or rel.startswith(("/", "\\")) or ".." in rel.replace("\\", "/").split("/") or ":" in rel:
        raise AppError("invalid file path", "bad_path", 400)
    b = Path(base).resolve()
    p = (b / rel).resolve()
    if b not in p.parents:
        raise AppError("invalid file path", "bad_path", 400)
    if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".svg", ".json", ".md"):
        raise AppError("that file type is not served", "bad_path", 400)
    return p
