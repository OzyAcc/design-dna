"""Bounded server-side link fetching: direct image links, and real candidate images declared on a public web page.

Protections: http/https only, no credentials in URLs, every DNS answer must be a public address (private, loopback,
link-local, shared, reserved and multicast ranges are refused), the TCP connection is pinned to the validated address
(no DNS rebinding between check and connect), every redirect is re-validated (at most 5), and time and size are
limited. When an outbound proxy is configured (DNA_FETCH_PROXY) the proxy resolves the name; the destination is still
validated first, and that residual limitation is documented. Page HTML is parsed as data: nothing is executed, and only
images the page itself declares are offered. This imports an image from a page; it is not a capture of the page.
"""
from __future__ import annotations

import base64
import http.client
import io
import ipaddress
import json
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit

from . import config
from .errors import AppError

UA = "DesignDNA-Dashboard/0.1 (image import; +https://github.com/OzyAcc/design-dna)"
MAX_REDIRECTS = 5
MAX_CANDIDATES = 40
PREVIEW_CANDIDATES = 12
SHARED = ipaddress.ip_network("100.64.0.0/10")


@dataclass
class Fetched:
    url: str
    status: int
    content_type: str
    data: bytes
    redirects: list


def _public(ip: str) -> bool:
    a = ipaddress.ip_address(ip)
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped:
        a = a.ipv4_mapped
    if a.is_loopback or a.is_private or a.is_link_local or a.is_multicast or a.is_reserved or a.is_unspecified:
        return False
    if isinstance(a, ipaddress.IPv4Address) and a in SHARED:
        return False
    return a.is_global


def validate_url(url: str) -> tuple[str, str, int, str]:
    if not isinstance(url, str) or len(url) > 4096:
        raise AppError("that is not a usable link", "bad_url")
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise AppError("only http and https links can be imported", "bad_url", detail={"scheme": parts.scheme})
    if parts.username or parts.password:
        raise AppError("links with embedded credentials are refused", "bad_url")
    if not parts.hostname:
        raise AppError("the link has no host name", "bad_url")
    host = parts.hostname.encode("idna").decode("ascii")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    return parts.scheme, host, port, path


def resolve_public(host: str, port: int) -> list[str]:
    allow = config.get().fetch_allow_private
    try:
        ipaddress.ip_address(host)
        ips = [host]
    except ValueError:
        try:
            ips = sorted({ai[4][0] for ai in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
        except socket.gaierror:
            raise AppError(f"the host {host!r} could not be resolved", "dns_failed", 502)
    bad = [ip for ip in ips if not _public(ip)]
    if bad and not allow:
        raise AppError("the link points to a private or local network address; only public sites can be fetched",
                       "private_destination", 403, {"host": host, "addresses": bad})
    return ips


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, ip, port, timeout):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, ip, port, timeout, context):
        super().__init__(host, port, timeout=timeout, context=context)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _connection(scheme, host, port, ip, timeout):
    ctx = ssl.create_default_context()
    proxy = config.get().fetch_proxy
    if proxy:
        p = urlsplit(proxy)
        headers = {}
        if p.username:
            cred = base64.b64encode(f"{unquote(p.username)}:{unquote(p.password or '')}".encode()).decode()
            headers["Proxy-Authorization"] = f"Basic {cred}"
        cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
        kw = {"context": ctx} if scheme == "https" else {}
        c = cls(p.hostname, p.port or 80, timeout=timeout, **kw)
        c.set_tunnel(host, port, headers=headers)
        return c
    if scheme == "https":
        return _PinnedHTTPS(host, ip, port, timeout, ctx)
    return _PinnedHTTP(host, ip, port, timeout)


def fetch(url: str, max_bytes: int | None = None, accept="image/*,text/html;q=0.8,*/*;q=0.1") -> Fetched:
    s = config.get()
    max_bytes = max_bytes or s.fetch_max_bytes
    deadline = time.monotonic() + s.fetch_timeout
    redirects = []
    for _ in range(MAX_REDIRECTS + 1):
        scheme, host, port, path = validate_url(url)
        ip = resolve_public(host, port)[0]
        left = deadline - time.monotonic()
        if left <= 0:
            raise AppError("the link took too long to respond", "timeout", 504)
        conn = _connection(scheme, host, port, ip, min(left, s.fetch_timeout))
        try:
            conn.request("GET", path, headers={"Host": host if port in (80, 443) else f"{host}:{port}", "User-Agent": UA,
                                               "Accept": accept, "Accept-Encoding": "identity"})
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308):
                loc = resp.getheader("Location")
                if not loc:
                    raise AppError("the link redirected without a destination", "bad_redirect", 502)
                url = urljoin(url, loc)
                redirects.append(url)
                continue
            if resp.status != 200:
                raise AppError(f"the link answered HTTP {resp.status}", "http_error", 502, {"status": resp.status})
            declared = resp.getheader("Content-Length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise AppError(f"the linked file is larger than {max_bytes / 1e6:.0f} MB", "too_large", 413)
            chunks, total = [], 0
            while True:
                if time.monotonic() > deadline:
                    raise AppError("the link took too long to download", "timeout", 504)
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise AppError(f"the linked file is larger than {max_bytes / 1e6:.0f} MB", "too_large", 413)
                chunks.append(chunk)
            ctype = (resp.getheader("Content-Type") or "").split(";")[0].strip().lower()
            return Fetched(url, resp.status, ctype, b"".join(chunks), redirects)
        except (OSError, http.client.HTTPException) as e:
            if isinstance(e, AppError):
                raise
            raise AppError("the link could not be fetched", "fetch_failed", 502, {"reason": f"{type(e).__name__}: {str(e)[:160]}"})
        finally:
            conn.close()
    raise AppError("the link redirected too many times", "too_many_redirects", 502)


# ------------------------------------------------------------------ page image candidates
class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta, self.imgs, self.title, self.canonical, self.jsonld, self._in_title, self._in_ld = {}, [], "", None, [], False, False
        self._buf = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key in ("og:image", "og:image:secure_url", "og:image:url", "twitter:image", "twitter:image:src", "og:title",
                       "og:site_name", "og:image:alt", "og:image:width", "og:image:height") and a.get("content"):
                self.meta.setdefault(key, a["content"])
        elif tag == "link" and "image_src" in a.get("rel", "").lower() and a.get("href"):
            self.meta.setdefault("image_src", a["href"])
        elif tag == "link" and a.get("rel", "").lower() == "canonical" and a.get("href"):
            self.canonical = a["href"]
        elif tag in ("img", "source"):
            src = a.get("src") or a.get("data-src") or ""
            srcset = a.get("srcset") or a.get("data-srcset") or ""
            best = _largest_from_srcset(srcset) or src
            if best:
                self.imgs.append({"url": best, "alt": a.get("alt", "")[:200], "width": _num(a.get("width")), "height": _num(a.get("height"))})
        elif tag == "title":
            self._in_title = True
        elif tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._in_ld, self._buf = True, []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "script" and self._in_ld:
            self._in_ld = False
            self.jsonld.append("".join(self._buf))

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._in_ld:
            self._buf.append(data)


def _num(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _largest_from_srcset(srcset: str):
    best, best_w = None, -1
    for part in srcset.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        w = 0
        if len(bits) > 1 and bits[1][:-1].replace(".", "").isdigit():
            w = float(bits[1][:-1]) * (1000 if bits[1].endswith("x") else 1)
        if w > best_w:
            best, best_w = bits[0], w
    return best


def _ld_images(blobs):
    out = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "image":
                    for x in (v if isinstance(v, list) else [v]):
                        if isinstance(x, str):
                            out.append(x)
                        elif isinstance(x, dict) and isinstance(x.get("url"), str):
                            out.append(x["url"])
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    for b in blobs:
        try:
            walk(json.loads(b))
        except ValueError:
            continue
    return out


def page_candidates(page: Fetched) -> dict:
    p = _PageParser()
    p.feed(page.data.decode("utf-8", errors="replace")[:3_000_000])
    found, seen = [], set()

    def add(u, declared_by, alt="", w=None, h=None):
        if not u or u.startswith("data:") or len(found) >= MAX_CANDIDATES:
            return
        full = urljoin(page.url, u.strip())
        if urlsplit(full).scheme not in ("http", "https") or full in seen or full.lower().split("?")[0].endswith(".svg"):
            return
        if w is not None and h is not None and (w < 48 or h < 48):
            return  # declared as a tiny icon or tracking pixel
        seen.add(full)
        found.append({"url": full, "declared_by": declared_by, "alt": alt, "declared_width": w, "declared_height": h})

    for key in ("og:image:secure_url", "og:image", "og:image:url", "twitter:image", "twitter:image:src", "image_src"):
        add(p.meta.get(key), key, p.meta.get("og:image:alt", ""), _num(p.meta.get("og:image:width")), _num(p.meta.get("og:image:height")))
    for u in _ld_images(p.jsonld):
        add(u, "json-ld")
    for im in p.imgs:
        add(im["url"], "img", im["alt"], im["width"], im["height"])
    return {"page_url": page.url, "title": (p.meta.get("og:title") or p.title or "").strip()[:200],
            "site_name": p.meta.get("og:site_name", "")[:120], "canonical": p.canonical, "candidates": found}


def _thumb(c):
    from PIL import Image

    try:
        f = fetch(c["url"], accept="image/*")
        im = Image.open(io.BytesIO(f.data))
        w, h = im.size
        im.seek(0)
        im = im.convert("RGB")
        im.thumbnail((240, 240))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=80)
        return dict(c, ok=True, width=w, height=h, bytes=len(f.data), thumb="data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode())
    except AppError as e:
        return dict(c, ok=False, reason=e.message)
    except Exception as e:  # undecodable image: reported, never invented
        return dict(c, ok=False, reason=f"not a decodable image ({type(e).__name__})")


def resolve_link(url: str) -> dict:
    """A direct image link -> {'kind': 'image', fetched}; a web page -> {'kind': 'page', candidates with real thumbnails}."""
    f = fetch(url)
    if f.content_type.startswith("image/") or (not f.content_type.startswith("text/html") and f.data[:4] in (b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"GIF8", b"RIFF")):
        return {"kind": "image", "fetched": f}
    if not f.content_type.startswith(("text/html", "application/xhtml")):
        raise AppError(f"the link returned {f.content_type or 'an unknown type'}, which is neither an image nor a web page",
                       "unsupported_link", 415)
    info = page_candidates(f)
    with ThreadPoolExecutor(max_workers=4) as ex:
        previews = list(ex.map(_thumb, info["candidates"][:PREVIEW_CANDIDATES]))
    info["candidates"] = previews + [dict(c, ok=None, reason="not previewed") for c in info["candidates"][PREVIEW_CANDIDATES:]]
    usable = [c for c in previews if c.get("ok")]
    if not usable:
        info["error"] = ("no usable image was found on this page (login-protected pages and script-built pages cannot be read); "
                         "paste a direct image link or upload the file instead")
    return {"kind": "page", **info}
