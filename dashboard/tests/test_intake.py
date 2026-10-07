"""T01 fresh workspace · T02 upload / paste / direct link for both roles · T03 web page image picker · T27 protections."""
from __future__ import annotations

import hashlib
import io
import struct
import unittest
import zlib
import zipfile

from PIL import Image

import support as S
from support import client, ok


class T01FreshWorkspace(unittest.TestCase):
    def test_empty_library_and_creation_paths(self):
        lib = ok(client.get("/api/templates?archived=0&q=zzzz-no-such"))
        self.assertEqual(lib["templates"], [])
        self.assertIn("collections", lib["facets"])
        home = client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn("text/html", home.headers["content-type"])
        self.assertEqual(ok(client.get("/api/health"))["ok"], True)
        S.record("T01", {"empty_library": True, "home_status": home.status_code})


class T02Intake(unittest.TestCase):
    def test_upload_both_roles_keeps_original_bytes(self):
        data = S.png_bytes(80, 60)
        a = S.upload(data, "inspiration", "ref.png")["assets"][0]
        p = S.upload(data, "product", "prod.png")["assets"][0]
        self.assertNotEqual(a["id"], p["id"])
        self.assertEqual((a["role"], p["role"]), ("inspiration", "product"))
        self.assertEqual(a["sha256"], hashlib.sha256(data).hexdigest())
        orig = client.get(a["original_url"])
        self.assertEqual(orig.content, data, "original bytes are preserved byte for byte")
        prev = Image.open(io.BytesIO(client.get(a["preview_url"]).content))
        self.assertEqual(prev.size, (80, 60))
        S.record("T02.upload", {"sha_matches": True, "roles": [a["role"], p["role"]]})

    def test_paste_and_exif_orientation_and_first_frame(self):
        im = Image.new("RGB", (80, 48), (20, 120, 60))
        ex = im.getexif()
        ex[0x0112] = 6
        buf = io.BytesIO()
        im.save(buf, "JPEG", exif=ex.tobytes())
        a = S.upload(buf.getvalue(), "inspiration", "rotated.jpg", kind="paste")["assets"][0]
        self.assertEqual(a["source_kind"], "paste")
        self.assertEqual((a["width"], a["height"]), (48, 80), "canonical copy is oriented")
        self.assertEqual(a["metadata"]["exif_orientation"], 6)
        self.assertEqual(client.get(a["original_url"]).content, buf.getvalue(), "original keeps its EXIF bytes")
        frames = [Image.new("RGB", (40, 40), c) for c in ((255, 0, 0), (0, 0, 255))]
        g = io.BytesIO()
        frames[0].save(g, "GIF", save_all=True, append_images=frames[1:])
        gi = S.upload(g.getvalue(), "product", "anim.gif")["assets"][0]
        self.assertTrue(gi["metadata"]["first_frame_only"])
        S.record("T02.orientation", {"canonical": [a["width"], a["height"]], "gif_first_frame": gi["metadata"]["first_frame_only"]})

    def test_direct_image_link_both_roles(self):
        data = S.png_bytes(90, 70, (10, 10, 200))
        base = S.serve({"/img.png": (200, "image/png", data, None), "/go": (302, None, b"", {"Location": "/img.png"})})
        S.config.get().fetch_allow_private = True
        try:
            for role in ("inspiration", "product"):
                r = ok(client.post("/api/assets/link", json={"url": base + "/go", "role": role}))
                self.assertEqual(r["kind"], "image")
                self.assertEqual(r["asset"]["sha256"], hashlib.sha256(data).hexdigest())
                self.assertEqual(r["asset"]["role"], role)
                self.assertEqual(r["asset"]["provenance"]["redirects"], [base + "/img.png"])
        finally:
            S.config.get().fetch_allow_private = False
        S.record("T02.link", {"redirect_followed_and_recorded": True})


class T03PagePicker(unittest.TestCase):
    def test_page_candidates_are_real_declared_images(self):
        big, small = S.png_bytes(300, 200, (0, 160, 0)), S.png_bytes(120, 120, (160, 0, 0))
        html = (b'<html><head><title>Oak chairs</title><meta property="og:image" content="/big.png">'
                b'<meta property="og:site_name" content="Example Studio"></head><body><img src="/small.png" alt="chair">'
                b'<img src="/pixel.png" width="1" height="1"><img src="/missing.png"><script>document.write("<img src=/x.png>")</script></body></html>')
        base = S.serve({"/page.html": (200, "text/html; charset=utf-8", html, None), "/big.png": (200, "image/png", big, None),
                        "/small.png": (200, "image/png", small, None), "/empty.html": (200, "text/html", b"<html><body>hi</body></html>", None)})
        S.config.get().fetch_allow_private = True
        try:
            r = ok(client.post("/api/assets/link", json={"url": base + "/page.html", "role": "inspiration"}))
            self.assertEqual(r["kind"], "page")
            urls = [c["url"] for c in r["candidates"]]
            self.assertEqual(urls[0], base + "/big.png", "declared og:image first")
            self.assertIn(base + "/small.png", urls)
            self.assertNotIn(base + "/pixel.png", urls, "declared tracking pixels are skipped")
            self.assertNotIn(base + "/x.png", urls, "script output is never executed")
            bad = next(c for c in r["candidates"] if c["url"].endswith("/missing.png"))
            self.assertFalse(bad["ok"])
            pick = ok(client.post("/api/assets/page-image", json={"url": urls[0], "role": "inspiration", "page_url": r["page_url"],
                                                                 "title": r["title"], "site_name": r["site_name"], "declared_by": "og:image"}))
            a = pick["asset"]
            self.assertEqual(a["sha256"], hashlib.sha256(big).hexdigest())
            self.assertEqual(a["provenance"]["page_title"], "Oak chairs")
            self.assertIn("not a capture", a["provenance"]["note"])
            empty = ok(client.post("/api/assets/link", json={"url": base + "/empty.html", "role": "product"}))
            self.assertTrue(empty.get("error"), "a page without images gives an actionable error")
        finally:
            S.config.get().fetch_allow_private = False
        S.record("T03", {"candidates": urls, "empty_page_error": empty["error"]})


def _bomb_png(w=60000, h=60000) -> bytes:
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(b"\x00" * 100)) + chunk(b"IEND", b"")


class T27Protections(unittest.TestCase):
    def test_invalid_oversized_and_bomb_images(self):
        r = client.post("/api/assets/upload", files=[("files", ("doc.pdf", b"%PDF-1.7 fake", "application/pdf"))], data={"role": "inspiration"})
        self.assertEqual(r.status_code, 415)
        self.assertEqual(r.json()["error"]["code"], "unsupported_format")
        r = client.post("/api/assets/upload", files=[("files", ("x.png", b"not an image at all", "image/png"))], data={"role": "product"})
        self.assertEqual(r.json()["error"]["code"], "decode_failed")
        r = client.post("/api/assets/upload", files=[("files", ("bomb.png", _bomb_png(), "image/png"))], data={"role": "product"})
        self.assertEqual(r.status_code, 413)
        old = S.config.get().max_upload_bytes
        S.config.get().max_upload_bytes = 1000
        try:
            r = client.post("/api/assets/upload", files=[("files", ("big.png", S.png_bytes(400, 400) + b"\0" * 2000, "image/png"))], data={"role": "product"})
            self.assertEqual(r.status_code, 413)
        finally:
            S.config.get().max_upload_bytes = old
        S.record("T27.images", {"pdf": 415, "bomb": 413, "oversized": 413})

    def test_private_destinations_and_schemes_refused(self):
        S.config.get().fetch_allow_private = False
        base = S.serve({"/img.png": (200, "image/png", S.png_bytes(), None)})
        for url, code in ((base + "/img.png", "private_destination"), ("http://169.254.169.254/latest/meta-data", "private_destination"),
                          ("http://[::1]:8765/api/health", "private_destination"), ("file:///etc/passwd", "bad_url"),
                          ("ftp://example.com/x.png", "bad_url"), ("http://user:pass@example.com/x.png", "bad_url")):
            r = client.post("/api/assets/link", json={"url": url, "role": "product"})
            self.assertGreaterEqual(r.status_code, 400, url)
            self.assertEqual(r.json()["error"]["code"], code, url)
        S.record("T27.links", {"refused": True})

    def test_unsafe_bundles_and_paths(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("manifest.json", "{}")
            z.writestr("template/../../escape.txt", "x")
        r = client.post("/api/templates/import", files=[("file", ("evil.dnab", buf.getvalue(), "application/zip"))])
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"]["code"], "unsafe_bundle")
        r = client.post("/api/templates/import", files=[("file", ("x.dnab", b"PK\x03\x04broken", "application/zip"))])
        self.assertEqual(r.json()["error"]["code"], "not_a_bundle")
        base = S.base_template()
        for rel in ("../../app.db", "..%2F..%2Fapp.db", "source/../../../secrets.json", "passport.json/../../x.png"):
            r = client.get(f"/api/templates/{base['id']}/files/work/{rel}")
            self.assertIn(r.status_code, (400, 404), rel)
        self.assertEqual(client.get(f"/api/templates/{base['id']}/files/work/source/canonical.png").status_code, 200)
        S.record("T27.bundles_paths", {"unsafe_bundle": 422, "traversal": "refused"})

    def test_workspace_authentication(self):
        from fastapi.testclient import TestClient

        from dna_dashboard import __main__ as cli

        s = S.config.get()
        s.auth_token = "a-long-workspace-token"
        try:
            c = TestClient(S.create_app())
            self.assertEqual(c.get("/api/health").status_code, 200)
            self.assertEqual(c.get("/api/auth/status").json(), {"required": True, "authenticated": False})
            self.assertEqual(c.get("/api/templates").status_code, 401)
            self.assertEqual(c.get("/api/templates", headers={"Authorization": "Bearer wrong"}).status_code, 401)
            self.assertEqual(c.get("/api/templates", headers={"Authorization": f"Bearer {s.auth_token}"}).status_code, 200)
            self.assertEqual(c.post("/api/auth/login", json={"token": "wrong"}).status_code, 401)
            self.assertEqual(c.post("/api/auth/login", json={"token": s.auth_token}).status_code, 200)
            self.assertEqual(c.get("/api/templates").status_code, 200, "the session cookie authenticates reads")
            r = c.post("/api/collections", json={"name": "Auth probe"})
            self.assertEqual((r.status_code, r.json()["error"]["code"]), (403, "csrf"), "a cookie-authenticated write needs the request header")
            self.assertEqual(c.post("/api/collections", json={"name": "Auth probe"}, headers={"X-DNA-Request": "1"}).status_code, 200)
            c.post("/api/auth/logout")
            self.assertEqual(c.get("/api/templates").status_code, 401)
            s.host = "0.0.0.0"
            cli._guard_bind(s)  # with a token, a public bind is allowed
            s.auth_token = None
            with self.assertRaises(SystemExit):
                cli._guard_bind(s)  # without one it refuses to start
        finally:
            s.auth_token, s.host = None, "127.0.0.1"
        S.record("T27.auth", {"no_token": 401, "bearer": 200, "cookie_write_without_header": 403, "public_bind_without_token": "refused"})


if __name__ == "__main__":
    unittest.main()
