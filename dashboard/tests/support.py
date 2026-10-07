"""Shared setup for the dashboard integration tests: an isolated data directory, the real engine, an in-process worker,
the TEST-ONLY mock providers (labelled mock; never a production path), a local web server for link tests, and cached
fixtures (one measured + accepted template) so the suite runs in minutes.

Evidence (key results of each scenario) is appended to $DNA_TEST_EVIDENCE/results.jsonl (default: a temp folder).
"""
from __future__ import annotations

import http.server
import io
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = Path(tempfile.mkdtemp(prefix="dna-dashboard-test-"))
EVIDENCE = Path(os.environ.get("DNA_TEST_EVIDENCE") or DATA / "evidence")
EVIDENCE.mkdir(parents=True, exist_ok=True)
os.environ.update(DNA_DATA_DIR=str(DATA), DNA_ENABLE_MOCK_PROVIDERS="1", DNA_LEASE_SECONDS="60")
for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DNA_AUTH_TOKEN", "DNA_FETCH_PROXY"):
    os.environ.pop(k, None)
sys.path[:0] = [str(HERE.parent / "server"), str(HERE)]

from fastapi.testclient import TestClient  # noqa: E402

from dna_dashboard import config, db, handlers, jobs, providers, worker  # noqa: E402,F401
from dna_dashboard.app import create_app  # noqa: E402

import fixtures  # noqa: E402

config.reset()
client = TestClient(create_app())

# re-exported for the test modules (handlers is imported so every job kind is registered with the worker)
__all__ = ["DATA", "EVIDENCE", "HERE", "client", "config", "create_app", "db", "fixtures", "handlers", "jobs", "providers", "worker",
           "record", "ok", "drain", "job", "upload", "base_template", "copy_of", "product", "serve", "png_bytes"]


def record(name: str, data) -> None:
    with open(EVIDENCE / "results.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"scenario": name, "at": db.now(), "data": data}, default=str, ensure_ascii=False) + "\n")


def ok(r, status=None):
    if status is not None:
        assert r.status_code == status, f"{r.status_code} != {status}: {r.text[:1500]}"
    elif r.status_code >= 400:
        raise AssertionError(f"HTTP {r.status_code}: {r.text[:2000]}")
    return r.json()


def drain(worker_id="test", timeout=900) -> None:
    t = time.time()
    while worker.run_one(worker_id):
        if time.time() - t > timeout:
            raise AssertionError("jobs did not finish in time")


def job(jid):
    return ok(client.get(f"/api/jobs/{jid}"))


def upload(data: bytes, role: str, name="image.png", kind="upload"):
    return ok(client.post("/api/assets/upload", files=[("files", (name, data, "application/octet-stream"))],
                          data={"role": role, "source_kind": kind}))


_CACHE: dict = {}


def base_template() -> dict:
    """A measured, reviewed, rebuilt and accepted template (version 1), built once per test process."""
    if "base" in _CACHE:
        return _CACHE["base"]
    png, els = fixtures.poster()
    a = upload(png, "inspiration", "poster.png")["assets"][0]
    t = ok(client.post("/api/templates", json={"asset_id": a["id"], "name": "Botanical Editorial"}))
    t = ok(client.patch(f"/api/templates/{t['id']}/draft", json={"base_revision": t["draft_revision"], "changes": {
        "passport": {"goal": {"value": "launch a product", "status": "user_supplied"}, "character": {"value": "calm editorial", "status": "user_supplied"},
                     "theme": {"value": "paper and ink", "status": "user_supplied"}, "usage": {"value": "4:5 social feed", "status": "user_supplied"},
                     "literal_message": {"value": "a durable product", "status": "user_supplied"},
                     "mechanism": {"value": "serif promise above a product photo", "status": "user_supplied"}},
        "draft": {"elements": els, "review_confirmed": True}}}))
    j = ok(client.post(f"/api/templates/{t['id']}/measure"))
    drain()
    measure = job(j["id"])
    assert measure["status"] in ("completed", "needs_review"), measure
    model = ok(client.get(f"/api/templates/{t['id']}/model?source=work"))
    slots = {s["role"]: s["id"] for s in model["scene"]["slots"]}
    t = ok(client.get(f"/api/templates/{t['id']}"))
    t = ok(client.put(f"/api/templates/{t['id']}/rules", json={"base_revision": t["draft_revision"], "review_confirmed": True,
                                                               "slots": [{"id": slots["headline"], "required": True, "max_lines": 2},
                                                                         {"id": slots["kicker"], "required": False},
                                                                         {"id": slots["cta"], "required": False, "max_chars": 24}],
                                                               "default_copy": {slots["cta"]: "Shop now"}}))
    j = ok(client.post(f"/api/templates/{t['id']}/rebuild", json={"mode": "editable"}))
    drain()
    rebuild = job(j["id"])
    st = ok(client.get(f"/api/templates/{t['id']}"))["draft"]["staged"]
    j = ok(client.post(f"/api/templates/{t['id']}/accept", json={"stage_id": st["stage_id"], "note": "test acceptance"}))
    drain()
    t = ok(client.get(f"/api/templates/{t['id']}"))
    _CACHE["base"] = {"id": t["id"], "template": t, "version": t["current_version"], "slots": slots, "measure": measure,
                      "rebuild": rebuild, "staged": st, "asset": a}
    record("fixture.base_template", {"measure": measure.get("result", {}).get("measure", {}).get("elements"),
                                     "staged": {k: st.get(k) for k in ("readiness", "verdict", "reproducibility")},
                                     "version": {k: t["current_version"][k] for k in ("number", "readiness", "eligibility")}})
    return _CACHE["base"]


def copy_of(tid, name) -> dict:
    r = ok(client.post(f"/api/templates/{tid}/copy", json={"name": name}))
    drain()
    return ok(client.get(f"/api/templates/{r['template']['id']}"))


def product(name, color=(150, 110, 70)) -> dict:
    a = upload(fixtures.product(color), "product", f"{name}.png")["assets"][0]
    return ok(client.post("/api/products", json={"name": name, "primary_asset_id": a["id"], "description": f"{name} in solid oak",
                                                 "facts": ["solid oak frame"], "instructions": ""}))


# ------------------------------------------------------------------ local web server for link tests
class _Handler(http.server.BaseHTTPRequestHandler):
    routes: dict = {}

    def do_GET(self):  # noqa: N802
        r = self.routes.get(self.path.split("?")[0])
        if r is None:
            self.send_response(404)
            self.end_headers()
            return
        status, ctype, body, headers = r
        self.send_response(status)
        if ctype:
            self.send_header("Content-Type", ctype)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def serve(routes: dict) -> str:
    _Handler.routes = routes
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}"


def png_bytes(w=64, h=48, color=(200, 30, 30)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()
