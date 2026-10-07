"""Reproducible screenshots of the dashboard journey for the user guide (docs/images/dashboard/).

    python dashboard/tests/screenshots.py [out_dir]

Builds a fresh, isolated workspace with the synthetic fixtures (a measured, rebuilt and accepted template, an edited
copy, three products, one batch and its finished run) through the same API the browser uses, then serves the built
web app and captures each page. No provider keys are used and the mock providers are switched OFF before the server
starts, so nothing in the pictures is mock output. Needs the built web app (npm run build in dashboard/web).
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import support as S
from support import client, ok

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "docs" / "images" / "dashboard")


def build_workspace() -> dict:
    base = S.base_template()
    copy = S.copy_of(base["id"], "Botanical Editorial — forest accent")
    comp = ok(client.post(f"/api/templates/{copy['id']}/compile", json={"text": "make the accent #2E5A44"}))
    ok(client.post(f"/api/templates/{copy['id']}/edit", json={"ops": comp["ops"], "base_revision": comp["base_revision"],
                                                              "intent": "forest green accent"}))
    S.drain()
    ok(client.post(f"/api/templates/{copy['id']}/save-version", json={"note": "forest green accent"}))
    S.drain()
    comp = ok(client.post(f"/api/templates/{copy['id']}/compile", json={"text": "make the kicker #2E5A44"}))
    ok(client.post(f"/api/templates/{copy['id']}/edit", json={"ops": comp["ops"], "base_revision": comp["base_revision"],
                                                              "intent": "kicker in the accent colour"}))
    S.drain()
    copy = ok(client.get(f"/api/templates/{copy['id']}"))
    products = [S.product("Sage lounge chair", (120, 140, 100)), S.product("Oak stool", (150, 110, 70)),
                S.product("Clay side table", (176, 112, 84))]
    copy_text = {"Sage lounge chair": ("Sit softly\nevery day", "SPRING EDIT"), "Oak stool": ("Solid oak\nbuilt well", "NEW SEASON"),
                 "Clay side table": ("Warm clay\nquiet form", "JUST IN")}
    m = ok(client.post("/api/batches", json={"name": "Spring furniture launch",
                                             "template_versions": [{"version_id": base["version"]["id"]}, {"version_id": copy["current_version"]["id"]}],
                                             "product_ids": [p["id"] for p in products]}))
    bid = m["batch"]["id"]
    names = {p["id"]: p["name"] for p in products}
    for p in m["pairs"]:
        head, kick = copy_text[names[p["product_id"]]]
        sl = {s["role"]: s["slot_id"] for s in p["slots"]}
        m = ok(client.patch(f"/api/batches/{bid}/pairs/{p['pair_id']}", json={"manual": {sl["headline"]: {"value": head},
                                                                                         sl["kicker"]: {"value": kick}}}))
    for p in m["pairs"][:2]:
        ok(client.post(f"/api/batches/{bid}/pairs/{p['pair_id']}/preview"))
    S.drain()
    run = ok(client.post(f"/api/batches/{bid}/submit", json={"idempotency_key": "screenshots-run"}))
    S.drain()
    outs = ok(client.get(f"/api/runs/{run['run_id']}"))["outputs"]
    for o in outs[:2]:
        ok(client.post(f"/api/outputs/{o['id']}/review", json={"state": "approved"}))
    # a second batch left as a draft, so the composer shows work in progress
    m2 = ok(client.post("/api/batches", json={"name": "Autumn catalogue (draft)", "template_versions": [{"version_id": base["version"]["id"]}],
                                              "product_ids": [products[0]["id"], products[1]["id"]]}))
    return {"base": base["id"], "copy": copy["id"], "batch": bid, "draft_batch": m2["batch"]["id"], "run": run["run_id"]}


def serve():
    import socket

    import uvicorn

    os.environ["DNA_ENABLE_MOCK_PROVIDERS"] = "0"
    S.config.reset()
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    server = uvicorn.Server(uvicorn.Config(S.create_app(), host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.1)
    return f"http://127.0.0.1:{port}", server


def shoot(base_url: str, ids: dict) -> list[str]:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    shots = []

    def cap(page, name, full=False):
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(700)
        p = OUT / f"{name}.png"
        page.screenshot(path=str(p), full_page=full)
        shots.append(p.name)

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page(viewport={"width": 1440, "height": 960})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{base_url}/templates")
        cap(page, "01-library")
        page.goto(f"{base_url}/templates/new")
        cap(page, "02-new-template")
        page.goto(f"{base_url}/templates/new?id={ids['base']}")
        for step, name in (("Scan", "03-scan-review"), ("Rules", "04-slot-rules"), ("Rebuild", "05-rebuild-compare")):
            page.locator("ol.steps").get_by_role("button", name=step, exact=False).first.click()
            cap(page, name, full=True)
        page.goto(f"{base_url}/templates/{ids['base']}")
        cap(page, "06-template-inspector", full=True)
        page.goto(f"{base_url}/templates/{ids['copy']}/edit")
        cap(page, "07-copy-editor", full=True)
        page.goto(f"{base_url}/generate?batch={ids['batch']}")
        cap(page, "08-batch-composer")
        page.goto(f"{base_url}/runs/{ids['run']}")
        cap(page, "09-results", full=True)
        page.goto(f"{base_url}/settings")
        cap(page, "10-settings", full=True)
        phone = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        phone.on("pageerror", lambda e: errors.append(str(e)))
        phone.goto(f"{base_url}/templates")
        cap(phone, "11-phone-library")
        phone.goto(f"{base_url}/generate?batch={ids['batch']}")
        cap(phone, "12-phone-composer")
        b.close()
    if errors:
        raise SystemExit(f"page errors while capturing: {errors[:5]}")
    return shots


if __name__ == "__main__":
    ids = build_workspace()
    url, server = serve()
    try:
        names = shoot(url, ids)
    finally:
        server.should_exit = True
    print(f"{len(names)} screenshots in {OUT}: {', '.join(names)}")
