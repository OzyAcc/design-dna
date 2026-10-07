"""Image intake for both input roles (inspiration and product): validate, preserve, normalise, record.

Original bytes are stored unchanged under their sha256 (immutable). A separate canonical sRGB PNG (EXIF orientation
applied, embedded ICC converted, first frame only) is the comparison and preview copy; a small thumbnail is made for
cards. The format is detected from the bytes, never from the file name. Animated images are labelled first-frame.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import unicodedata
from pathlib import Path

from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

from . import config, db
from .errors import AppError

FORMATS = {"PNG": (".png", "image/png"), "JPEG": (".jpg", "image/jpeg"), "MPO": (".jpg", "image/jpeg"),
           "WEBP": (".webp", "image/webp"), "TIFF": (".tif", "image/tiff"), "BMP": (".bmp", "image/bmp"),
           "GIF": (".gif", "image/gif")}
UNSUPPORTED_HINTS = {b"%PDF": "PDF documents", b"8BPS": "Photoshop (PSD) files", b"<svg": "SVG vector files",
                     b"<?xml": "SVG/XML files", b"PK\x03\x04": "ZIP archives (use Import bundle for .dnab files)"}
THUMB = 480
ROLES = ("inspiration", "product", "generated", "detail")


def safe_name(name: str | None, default="image") -> str:
    """Basename only, no control characters, bounded length (names are data, never paths)."""
    name = unicodedata.normalize("NFC", (name or "").replace("\\", "/").split("/")[-1])
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().strip(".")
    return (name or default)[:120]


def blob_path(sha: str, ext: str) -> Path:
    return config.get().blobs / sha[:2] / f"{sha}{ext}"


def preview_path(sha: str) -> Path:
    return config.get().previews / sha[:2] / f"{sha}.png"


def thumb_path(sha: str) -> Path:
    return config.get().previews / sha[:2] / f"{sha}.thumb.png"


def _write_once(p: Path, data: bytes) -> None:
    if p.exists():
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.part")
    tmp.write_bytes(data)
    os.replace(tmp, p)


def inspect_image(data: bytes) -> tuple[Image.Image, dict]:
    """Decode and validate. Raises AppError with an actionable message for anything unsupported."""
    s = config.get()
    if not data:
        raise AppError("the file is empty", "empty_file")
    if len(data) > s.max_upload_bytes:
        raise AppError(f"the file is {len(data) / 1e6:.1f} MB; the limit is {s.max_upload_bytes / 1e6:.0f} MB", "too_large", 413)
    head = data[:16].lstrip()
    for magic, what in UNSUPPORTED_HINTS.items():
        if head.startswith(magic):
            raise AppError(f"{what} have no adapter here; export the artwork as PNG or JPEG and add that", "unsupported_format", 415,
                           {"supported": sorted({v[0] for v in FORMATS.values()})})
    Image.MAX_IMAGE_PIXELS = s.max_pixels
    try:
        im = Image.open(io.BytesIO(data))
        fmt = im.format
        if fmt not in FORMATS:
            raise AppError(f"{fmt or 'this'} images are not supported; use PNG, JPEG, WebP, TIFF, BMP or GIF", "unsupported_format", 415)
        w, h = im.size
        if w * h > s.max_pixels:
            raise AppError(f"the image is {w}x{h} ({w * h / 1e6:.0f} MP); the limit is {s.max_pixels / 1e6:.0f} MP", "too_many_pixels", 413)
        if w < 8 or h < 8:
            raise AppError(f"the image is only {w}x{h} pixels", "too_small")
        im.load()
    except Image.DecompressionBombError:
        raise AppError("the image declares too many pixels to decode safely", "too_many_pixels", 413)
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as e:
        raise AppError("the file could not be decoded as an image", "decode_failed", 415, {"reason": str(e)[:200]})
    icc = im.info.get("icc_profile")
    try:
        icc_name = ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc))).strip() if icc else None
    except Exception:  # an unreadable profile is reported, never silently dropped
        icc_name = "unreadable embedded profile"
    exif = im.getexif()
    frames = getattr(im, "n_frames", 1)
    meta = {"format": fmt, "mode": im.mode, "header_width": w, "header_height": h, "frames": frames,
            "first_frame_only": frames > 1, "exif_orientation": exif.get(0x0112), "icc_profile": icc_name,
            "has_alpha": "A" in im.mode or "transparency" in im.info, "dpi": im.info.get("dpi")}
    return im, meta


def normalise(im: Image.Image) -> tuple[Image.Image, list[str]]:
    steps = []
    if getattr(im, "n_frames", 1) > 1:
        im.seek(0)
        steps.append("first frame only")
    if im.getexif().get(0x0112, 1) != 1:
        steps.append("EXIF orientation applied")
    im = ImageOps.exif_transpose(im)
    mode = "RGBA" if ("A" in im.mode or "transparency" in im.info) else "RGB"
    icc = im.info.get("icc_profile")
    if icc:
        try:
            im = ImageCms.profileToProfile(im.convert(mode), ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                                           ImageCms.createProfile("sRGB"), outputMode=mode)
            steps.append("embedded ICC converted to sRGB")
        except Exception:
            steps.append("embedded ICC could not be applied; pixel values kept (assumed sRGB)")
    else:
        steps.append("no ICC profile: assumed sRGB")
    return im.convert(mode), steps


def ingest(data: bytes, *, role: str, original_name: str | None, source_kind: str, source_url: str | None = None,
           page_url: str | None = None, provenance: dict | None = None, conn=None) -> dict:
    if role not in ROLES:
        raise AppError(f"unknown asset role {role!r}", "bad_role")
    im, meta = inspect_image(data)
    sha = hashlib.sha256(data).hexdigest()
    ext, mime = FORMATS[meta["format"]]
    _write_once(blob_path(sha, ext), data)
    norm, steps = normalise(im)
    meta.update(width=norm.width, height=norm.height, normalisation=steps)
    if not preview_path(sha).exists():
        buf = io.BytesIO()
        norm.save(buf, "PNG")
        _write_once(preview_path(sha), buf.getvalue())
    if not thumb_path(sha).exists():
        t = norm.copy()
        t.thumbnail((THUMB, THUMB))
        buf = io.BytesIO()
        t.save(buf, "PNG")
        _write_once(thumb_path(sha), buf.getvalue())
    rec = {"id": db.new_id("as"), "sha256": sha, "role": role, "original_name": safe_name(original_name, f"image{ext}"),
           "mime": mime, "ext": ext, "bytes": len(data), "width": norm.width, "height": norm.height, "source_kind": source_kind,
           "source_url": source_url, "page_url": page_url, "metadata": meta, "provenance": provenance or {"kind": source_kind},
           "created_at": db.now()}
    own = conn is None
    conn = conn or db.connect()
    try:
        db.insert(conn, "assets", rec)
    finally:
        if own:
            conn.close()
    return public(rec)


def public(rec: dict) -> dict:
    """What the browser sees: no filesystem paths."""
    keys = ("id", "sha256", "role", "original_name", "mime", "bytes", "width", "height", "source_kind", "source_url", "page_url",
            "metadata", "provenance", "created_at")
    out = {k: rec.get(k) for k in keys}
    out["preview_url"] = f"/api/assets/{rec['id']}/preview"
    out["thumb_url"] = f"/api/assets/{rec['id']}/thumb"
    out["original_url"] = f"/api/assets/{rec['id']}/original"
    return out


def get(conn, asset_id: str) -> dict:
    r = db.one(conn, "SELECT * FROM assets WHERE id = ?", (asset_id,))
    if not r:
        raise AppError(f"asset {asset_id!r} was not found", "not_found", 404)
    return r


def original_file(rec: dict) -> Path:
    return blob_path(rec["sha256"], rec["ext"])


def canonical_file(rec: dict) -> Path:
    return preview_path(rec["sha256"])
