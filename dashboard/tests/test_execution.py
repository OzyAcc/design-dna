"""T15 concurrent jobs · T16 frozen template version · T17 deterministic adaptation checks · T18 creative generation
· T19 missing keys and provider failures · T23 partial failure, scoped retry, cancel · T24 worker crash and restart
· T26 output and ZIP export."""
from __future__ import annotations

import hashlib
import io
import json
import os
import signal
import subprocess
import sys
import threading
import time
import unittest
import zipfile
from pathlib import Path

from PIL import Image

import fixtures
import support as S
from support import client, ok

_T: dict = {}


def setup_shared():
    if "v" not in _T:
        base = S.base_template()
        _T["v"] = base["version"]
        _T["slots"] = base["slots"]
        _T["p"] = [S.product("Sage chair", (120, 140, 100)), S.product("Oak stool", (150, 110, 70))]
    return _T["v"], _T["p"]


def batch(version, products, mode="adapt", headline="Built to\nlast years", name=None):
    m = ok(client.post("/api/batches", json={"name": name or f"{mode} batch", "template_versions": [{"version_id": version["id"]}],
                                             "product_ids": [p["id"] for p in products]}))
    bid = m["batch"]["id"]
    if mode != "adapt":
        m = ok(client.patch(f"/api/batches/{bid}", json={"base_revision": m["batch"]["revision"], "changes": {"defaults": {"mode": mode}}}))
    for p in m["pairs"]:
        hs = next(s for s in p["slots"] if s["role"] == "headline")["slot_id"]
        m = ok(client.patch(f"/api/batches/{bid}/pairs/{p['pair_id']}", json={"manual": {hs: {"value": headline}}}))
    return m


def submit(m, key):
    return ok(client.post(f"/api/batches/{m['batch']['id']}/submit", json={"idempotency_key": key}))


def run(rid):
    return ok(client.get(f"/api/runs/{rid}"))


def pixel(png_path_or_bytes, xy):
    data = png_path_or_bytes if isinstance(png_path_or_bytes, bytes) else Path(png_path_or_bytes).read_bytes()
    with Image.open(io.BytesIO(data)) as im:
        return im.convert("RGB").getpixel(xy)


def close(a, b, tol=24):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def output_file(o, kind):
    i = next(i for i, f in enumerate(o["files"]) if f["kind"] == kind)
    r = client.get(o["files"][i]["url"])
    assert r.status_code == 200, r.text[:300]
    return r


class T15Concurrency(unittest.TestCase):
    def test_two_workers_run_two_outputs_in_isolated_stores(self):
        v, ps = setup_shared()
        m = batch(v, ps)
        r = submit(m, "t15-concurrent")
        conn = S.db.connect()
        jids = [o["job_id"] for o in run(r["run_id"])["outputs"]]
        barrier = threading.Barrier(2)
        errors, spans = [], {}

        def go(i):
            try:
                barrier.wait()
                t0 = time.monotonic()
                S.worker.run_one(f"t15-w{i}")
                spans[i] = (t0, time.monotonic())
            except Exception as e:  # surfaced below
                errors.append(e)

        ts = [threading.Thread(target=go, args=(i,)) for i in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(900)
        self.assertFalse(errors, errors)
        js = [S.db.one(conn, "SELECT * FROM jobs WHERE id = ?", (j,)) for j in jids]
        self.assertEqual([j["status"] for j in js], ["completed", "completed"], [j["error"] for j in js])
        owners = {e["message"].split(" ")[2] for j in jids for e in S.jobs.events(conn, j) if e["message"].startswith("started by")}
        self.assertEqual(owners, {"t15-w0", "t15-w1"}, "each job was claimed by a different worker")
        overlap = min(e for _, e in spans.values()) - max(s for s, _ in spans.values())
        self.assertGreater(overlap, 1.0, "the two jobs ran at the same time")
        homes = [S.config.get().jobs / j / "home" for j in jids]
        self.assertTrue(all(h.is_dir() for h in homes))
        self.assertNotEqual(*homes)
        outs = run(r["run_id"])["outputs"]
        a, b = (output_file(o, "png").content for o in outs)
        self.assertNotEqual(hashlib.sha256(a).digest(), hashlib.sha256(b).digest(), "two products, two different results")
        _T["adapt_run"] = r["run_id"]
        S.record("T15", {"jobs": jids, "workers": sorted(owners), "overlap_seconds": round(overlap, 1), "homes": [str(h) for h in homes]})


class T16FrozenVersion(unittest.TestCase):
    def test_edit_after_submit_does_not_change_the_run(self):
        v, ps = setup_shared()
        base = S.base_template()
        c = S.copy_of(base["id"], "Frozen probe")
        v1 = c["current_version"]
        m = batch(v1, ps[:1])
        r = submit(m, "t16-frozen")
        conn = S.db.connect()
        oj = run(r["run_id"])["outputs"][0]["job_id"]
        conn.execute("UPDATE jobs SET status = 'held' WHERE id = ?", (oj,))  # the queue is busy: this output has not started yet
        conn.commit()
        comp = ok(client.post(f"/api/templates/{c['id']}/compile", json={"text": "make the accent #2E5A44"}))
        ok(client.post(f"/api/templates/{c['id']}/edit", json={"ops": comp["ops"], "base_revision": comp["base_revision"], "intent": "green accent"}))
        S.drain()
        ok(client.post(f"/api/templates/{c['id']}/save-version", json={"note": "green accent after submit"}))
        S.drain()
        c2 = ok(client.get(f"/api/templates/{c['id']}"))
        self.assertEqual(c2["current_version"]["number"], 2)
        conn.execute("UPDATE jobs SET status = 'queued' WHERE id = ?", (oj,))
        conn.commit()
        S.drain()
        o = run(r["run_id"])["outputs"][0]
        self.assertEqual(o["status"], "completed", o.get("error"))
        self.assertEqual(o["template_version_id"], v1["id"])
        self.assertEqual(o["provenance"]["template_bundle_sha256"], v1["bundle_sha256"])
        accent = pixel(output_file(o, "png").content, (120, 64))
        self.assertTrue(close(accent, fixtures.ACCENT), f"the run used version 1's crimson accent, got {accent}")
        m2 = ok(client.get(f"/api/batches/{m['batch']['id']}"))
        self.assertEqual(m2["pairs"][0]["template_version_id"], v1["id"], "the batch keeps the version it was composed with")
        S.record("T16", {"run_version": v1["number"], "template_now": 2, "accent_in_output": accent})


class T17Adaptation(unittest.TestCase):
    def test_deterministic_checks_files_and_provenance(self):
        v, ps = setup_shared()
        if "adapt_run" not in _T:
            m = batch(v, ps)
            _T["adapt_run"] = submit(m, "t17-adapt")["run_id"]
            S.drain()
        outs = run(_T["adapt_run"])["outputs"]
        o = next(x for x in outs if x["product_id"] == ps[0]["id"])
        self.assertEqual(o["status"], "completed", o.get("error"))
        ch = o["checks"]
        self.assertEqual(ch["verification_status"], "pass", ch)
        self.assertEqual(ch["model_changes"]["status"], "pass")
        self.assertFalse(ch["model_changes"]["unexplained"])
        vis = ch["visual_changes"]
        self.assertTrue(vis["compared_against"].startswith("approved template baseline"), vis)
        self.assertEqual((vis["status"], vis["outside_influence"]), ("pass", 0), vis)
        self.assertTrue(vis["inside_influence"] > 0, "the copy and photo changes are visible inside their declared influence")
        self.assertTrue(ch["approved_baseline_reproduced"], "the pinned re-render reproduces the approved baseline before the edit")
        self.assertEqual(ch["svg"]["roundtrip"], "pass")
        kinds = [f["kind"] for f in o["files"]]
        for k in ("png", "svg", "svg_manifest", "evidence"):
            self.assertIn(k, kinds)
        png = next(f for f in o["files"] if f["kind"] == "png")
        self.assertEqual(png["name"], "sage-chair--botanical-editorial--en--v1.png")
        self.assertEqual((png["width"], png["height"]), (800, 1000))
        data = output_file(o, "png").content
        self.assertEqual(hashlib.sha256(data).hexdigest(), png["sha256"])
        self.assertTrue(close(pixel(data, (400, 570)), (120, 140, 100), 40), "the product photo fills the image slot")
        self.assertTrue(close(pixel(data, (120, 64)), fixtures.ACCENT), "the template's accent is preserved")
        svg = output_file(o, "svg")
        self.assertIn("sandbox", svg.headers.get("content-security-policy", ""))
        self.assertIn("<svg", svg.text[:500])
        prov = o["provenance"]
        self.assertEqual(prov["path"], "adapt")
        self.assertEqual(prov["template_bundle_sha256"], v["bundle_sha256"])
        self.assertIsNone(prov["generated"])
        cta = next(s for s in o["inputs"]["slots"] if s["role"] == "cta")
        self.assertEqual((cta["value"], cta["source"]), ("Shop now", "template default"))
        S.record("T17", {"output": o["id"], "verification": ch["verification_status"], "outside_influence_vs_baseline": 0,
                         "svg_roundtrip": ch["svg"]["roundtrip"], "files": [f["name"] for f in o["files"]]})


class T18Creative(unittest.TestCase):
    def test_creative_and_creative_slot_are_labelled_generated(self):
        v, ps = setup_shared()
        m = batch(v, ps, mode="creative")
        bid = m["batch"]["id"]
        slot_pair = next(p for p in m["pairs"] if p["product_id"] == ps[1]["id"])
        m = ok(client.patch(f"/api/batches/{bid}/pairs/{slot_pair['pair_id']}", json={"mode": "creative_slot"}))
        self.assertTrue(all(any("no pixel preservation" in w for w in p["warnings"]) for p in m["pairs"]))
        r = submit(m, "t18-creative")
        S.drain()
        outs = {o["mode"]: o for o in run(r["run_id"])["outputs"]}
        cr, sl = outs["creative"], outs["creative_slot"]
        self.assertEqual(cr["status"], "completed", cr.get("error"))
        self.assertEqual(cr["provenance"]["kind"], "generated")
        self.assertTrue(cr["provenance"]["mock"])
        self.assertTrue(cr["checks"]["preservation"].startswith("not_applicable"))
        self.assertEqual(cr["checks"]["editability"], "none: a single raster image")
        self.assertTrue(cr["limitations"][0].startswith("MOCK PROVIDER"))
        self.assertIn("Do not add any text", cr["provenance"]["prompt"])
        self.assertEqual([f["kind"] for f in cr["files"]], ["png"])
        reqs = ok(client.get(f"/api/outputs/{cr['id']}"))["provider_requests"]
        self.assertEqual([(q["provider"], q["status"]) for q in reqs], [("mock", "received")])
        self.assertEqual(sl["status"], "completed", sl.get("error"))
        self.assertEqual(sl["provenance"]["generated"]["provider"], "mock")
        self.assertTrue(any("generated by an AI provider" in x for x in sl["limitations"]))
        self.assertEqual(sl["checks"]["verification_status"], "pass")
        home = S.config.get().jobs / sl["job_id"] / "home"
        recorded = [p for p in home.rglob("*.json") if '"source": "generated"' in p.read_text(encoding="utf-8", errors="ignore")]
        self.assertTrue(recorded, "the engine store records the slot image as generated, not supplied")
        S.record("T18", {"creative": {"status": cr["status"], "preservation": cr["checks"]["preservation"], "mock": True},
                         "creative_slot": {"status": sl["status"], "engine_records_generated": [str(p.relative_to(home)) for p in recorded][:3]}})


class T19ProvidersMissingOrFailing(unittest.TestCase):
    def test_missing_keys_disable_only_dependent_actions(self):
        v, ps = setup_shared()
        os.environ["DNA_ENABLE_MOCK_PROVIDERS"] = "0"
        S.config.reset()
        try:
            prov = ok(client.get("/api/providers"))
            self.assertEqual({p["name"]: p["health"]["status"] for p in prov}, {"anthropic": "unconfigured", "openai": "unconfigured"})
            base = S.base_template()
            r = client.post(f"/api/templates/{base['id']}/analyze", json={})
            self.assertEqual(r.status_code, 412, r.text)
            self.assertEqual(r.json()["error"]["detail"]["env"], "ANTHROPIC_API_KEY")
            m = batch(v, ps[:1], mode="creative")
            self.assertTrue(any("no image generation provider" in x for x in m["pairs"][0]["problems"]))
            bad = client.post(f"/api/batches/{m['batch']['id']}/submit", json={"idempotency_key": "t19-creative"})
            self.assertEqual((bad.status_code, bad.json()["error"]["code"]), (409, "preflight_failed"))
            m = ok(client.patch(f"/api/batches/{m['batch']['id']}", json={"base_revision": m["batch"]["revision"],
                                                                           "changes": {"defaults": {"mode": "adapt"}}}))
            self.assertEqual(m["counts"]["blocked"], 0, "editable adaptation needs no provider key")
        finally:
            os.environ["DNA_ENABLE_MOCK_PROVIDERS"] = "1"
            S.config.reset()
        S.record("T19.missing", {"analyze": 412, "creative_submit": "409 preflight_failed", "adapt_without_keys": "ready"})

    def test_provider_failures_are_classified(self):
        v, ps = setup_shared()
        seen = {}
        for kind, want in (("unauthorized", "failed"), ("rate_limited", "failed"), ("refused", "needs_review")):
            m = batch(v, ps[:1], mode="creative", name=f"fail {kind}")
            r = submit(m, f"t19-{kind}")
            S.providers.set_mock_failure(kind)
            try:
                S.drain()
            finally:
                S.providers.set_mock_failure(None)
            o = run(r["run_id"])["outputs"][0]
            self.assertEqual(o["status"], want, o)
            self.assertEqual((o["error"]["kind"], o["error"]["code"]), ("provider", f"provider_{kind}"))
            self.assertFalse(o["files"])
            reqs = ok(client.get(f"/api/outputs/{o['id']}"))["provider_requests"]
            self.assertEqual([q["status"] for q in reqs], ["failed"])
            seen[kind] = (o["status"], o["error"]["message"])
        S.record("T19.failures", seen)


class T22BaselineNotReproduced(unittest.TestCase):
    def test_a_non_reproducing_render_is_a_named_refusal_with_evidence(self):
        """Audit A2. The engine's own check is covered by engine T36 and by real occurrences under load; this test feeds the
        refusal it produces (a re-render 3 px off the approved baseline) through the dashboard's handling of it."""
        import shutil
        import tempfile
        from types import SimpleNamespace

        from dna_dashboard import templates_svc as ts
        from dna_dashboard.engine import EngineError
        from dna_dashboard.handlers import output_jobs

        v, ps = setup_shared()
        r = submit(batch(v, ps[:1], name="baseline not reproduced"), "t22-repro")
        o = run(r["run_id"])["outputs"][0]
        conn = S.db.connect()
        S.jobs.request_cancel(conn, o["job_id"])  # this probe drives the handler's refusal path directly
        orow = S.db.one(conn, "SELECT * FROM outputs WHERE id = ?", (o["id"],))
        ver = ts.version(conn, o["template_version_id"])
        rel = ver["summary"]["baseline"]["approved"]["path"]
        home = Path(tempfile.mkdtemp(dir=S.DATA))
        approved = home / "templates" / ver["engine_id"] / rel
        approved.parent.mkdir(parents=True)
        shutil.copyfile(ts.version_dir(ver) / rel, approved)
        im = Image.open(approved).convert("RGBA")
        for xy in ((62, 905), (63, 905), (63, 906)):  # the pixels and size of the difference seen in this environment
            px = im.getpixel(xy)
            im.putpixel(xy, (px[0] ^ 32, px[1], px[2], px[3]))
        rerender = home / "base-render.png"
        im.save(rerender)
        err = EngineError({"code": "verification_failed", "message": "verification failed",
                           "detail": {"conflicts": [{"verification": "failed", "detail": "see verification"}],
                                      "verification": {"status": "fail", "renders": {"base": str(rerender)},
                                                       "approved_baseline": {"path": rel, "pinned_re_render_reproduces_it": False}}}})
        odir = S.config.get().outputs / o["id"]
        odir.mkdir(parents=True, exist_ok=True)
        status, _ = output_jobs._refused(SimpleNamespace(home=home, conn=conn), orow, odir, err, None)
        self.assertEqual(status, "needs_review")
        o = ok(client.get(f"/api/outputs/{o['id']}"))
        self.assertEqual((o["status"], o["error"]["kind"]), ("needs_review", "baseline_not_reproduced"))
        self.assertEqual(o["error"]["baseline_reproduction"]["unequal_pixels"], 3)
        self.assertEqual(o["error"]["baseline_reproduction"]["box"], [62, 905, 2, 2])
        self.assertIn("no tolerance was applied", o["error"]["message"])
        names = {f["name"] for f in o["files"]}
        self.assertTrue({"refused/approved-baseline.png", "refused/baseline-re-render.png"} <= names, names)
        self.assertEqual(client.post(f"/api/outputs/{o['id']}/review", json={"state": "approved"}).status_code, 409)
        rt = ok(client.post(f"/api/outputs/{o['id']}/retry", json={"idempotency_key": "t22-retry"}))
        S.drain()
        self.assertEqual(ok(client.get(f"/api/outputs/{rt['output_id']}"))["status"], "completed", "a retry renders again; no paid request involved")
        S.record("T22.dashboard", {"refusal": o["error"]["kind"], "evidence": sorted(names), "retry": "completed"})


class T23PartialFailureRetryCancel(unittest.TestCase):
    def test_unknown_outcome_needs_confirmation_and_retry_is_a_new_revision(self):
        v, ps = setup_shared()
        m = batch(v, ps, mode="creative", name="partial failure")
        r = submit(m, "t23-partial")
        self.assertTrue(submit(m, "t23-partial")["duplicate"], "the same submission is not repeated")
        S.providers.set_mock_failure("unknown_outcome")
        try:
            self.assertTrue(S.worker.run_one("t23"))
        finally:
            S.providers.set_mock_failure(None)
        S.drain()
        rr = run(r["run_id"])
        self.assertEqual(rr["counts"], {"needs_review": 1, "completed": 1})
        self.assertEqual(rr["status"], "needs_review")
        bad = next(o for o in rr["outputs"] if o["status"] == "needs_review")
        good = next(o for o in rr["outputs"] if o["status"] == "completed")
        self.assertEqual(ok(client.get(f"/api/outputs/{bad['id']}"))["provider_requests"][0]["status"], "unknown")
        nope = client.post(f"/api/outputs/{bad['id']}/review", json={"state": "approved"})
        self.assertEqual(nope.status_code, 409, "a failed candidate cannot be approved")
        blind = client.post(f"/api/outputs/{bad['id']}/retry", json={"idempotency_key": "t23-retry-1"})
        self.assertEqual((blind.status_code, blind.json()["error"]["code"]), (409, "confirm_paid_retry"))
        rt = ok(client.post(f"/api/outputs/{bad['id']}/retry", json={"idempotency_key": "t23-retry-1", "confirm_new_paid_request": True}))
        again = ok(client.post(f"/api/outputs/{bad['id']}/retry", json={"idempotency_key": "t23-retry-1", "confirm_new_paid_request": True}))
        self.assertEqual((again["duplicate"], again["output_id"]), (True, rt["output_id"]), "a repeated click is not a second paid request")
        S.drain()
        o2 = ok(client.get(f"/api/outputs/{rt['output_id']}"))
        self.assertEqual((o2["status"], o2["revision"], o2["parent_output_id"]), ("completed", 2, bad["id"]))
        self.assertEqual([x["status"] for x in o2["revisions"]], ["needs_review", "completed"], "the first attempt is kept")
        self.assertEqual(run(r["run_id"])["status"], "completed")
        ok(client.post(f"/api/outputs/{good['id']}/review", json={"state": "approved"}))
        S.record("T23.unknown_outcome", {"blind_retry": 409, "confirmed_retry": o2["status"], "revisions": o2["revisions"]})

    def test_scoped_copy_revision_and_cancel(self):
        v, ps = setup_shared()
        if "adapt_run" not in _T:
            _T["adapt_run"] = submit(batch(v, ps), "t23-adapt")["run_id"]
            S.drain()
        o = next(x for x in run(_T["adapt_run"])["outputs"] if x["product_id"] == ps[1]["id"])
        cta = next(s for s in o["inputs"]["slots"] if s["role"] == "cta")
        head = next(s for s in o["inputs"]["slots"] if s["role"] == "headline")
        req = client.post(f"/api/outputs/{o['id']}/retry", json={"idempotency_key": "t23-empty", "copy": {head["slot_id"]: ""}})
        self.assertEqual((req.status_code, req.json()["error"]["code"]), (400, "required_slot"))
        rt = ok(client.post(f"/api/outputs/{o['id']}/retry", json={"idempotency_key": "t23-cta", "copy": {cta["slot_id"]: "Take a seat"}}))
        self.assertEqual(rt["changed"], [cta["slot_id"]])
        S.drain()
        o2 = ok(client.get(f"/api/outputs/{rt['output_id']}"))
        self.assertEqual(o2["status"], "completed", o2.get("error"))
        self.assertEqual(next(s for s in o2["inputs"]["slots"] if s["role"] == "cta")["value"], "Take a seat")
        self.assertEqual(next(s for s in o2["inputs"]["slots"] if s["role"] == "headline")["value"], head["value"], "only the revised slot changed")
        self.assertTrue(o2["files"][0]["name"].endswith("--v2.png"))
        self.assertEqual(ok(client.get(f"/api/outputs/{o['id']}"))["status"], "completed", "revision 1 is kept")
        m = batch(v, ps, name="cancel probe")
        r = submit(m, "t23-cancel")
        outs = run(r["run_id"])["outputs"]
        c = ok(client.post(f"/api/outputs/{outs[1]['id']}/cancel"))
        self.assertEqual(c["status"], "cancelled")
        S.drain()
        rr = run(r["run_id"])
        st = {x["id"]: x["status"] for x in rr["outputs"]}
        self.assertEqual((st[outs[0]["id"]], st[outs[1]["id"]]), ("completed", "cancelled"), "completed work is kept")
        self.assertTrue(next(x for x in rr["outputs"] if x["id"] == outs[0]["id"])["files"])
        S.record("T23.revision_cancel", {"copy_revision": o2["revision"], "changed": rt["changed"], "cancelled_queued": True})


class _Worker:
    """A real worker process (python -m dna_dashboard worker) that the test can kill like a crash."""

    def __init__(self, **env):
        e = dict(os.environ, DNA_LEASE_SECONDS="6", DNA_WORKER_THREADS="1", PYTHONPATH=str(S.HERE.parent / "server"), **env)
        self.p = subprocess.Popen([sys.executable, "-m", "dna_dashboard", "worker"], cwd=str(S.HERE.parent / "server"), env=e,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def kill(self):
        self.p.send_signal(signal.SIGKILL)
        self.p.wait(30)

    def stop(self):
        if self.p.poll() is None:
            self.p.terminate()
            self.p.wait(60)


def wait_for(fn, timeout=300, every=0.2, what="condition"):
    t = time.time()
    while time.time() - t < timeout:
        v = fn()
        if v:
            return v
        time.sleep(every)
    raise AssertionError(f"timed out waiting for {what}")


def engine_children(job_id):
    """Engine processes still working inside this job's directory (an orphan would show up here)."""
    found = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            if "engine_runner" in (d / "cmdline").read_bytes().decode(errors="ignore") and job_id in (d / "environ").read_bytes().decode(errors="ignore"):
                found.append(int(d.name))
        except OSError:
            pass
    return found


class T24CrashAndRestart(unittest.TestCase):
    def setUp(self):
        self.conn = S.db.connect()

    def jobrow(self, jid):
        return S.db.one(self.conn, "SELECT * FROM jobs WHERE id = ?", (jid,))

    def wait_lease_expired(self, jid):
        wait_for(lambda: (self.jobrow(jid)["lease_expires"] or 0) < time.time(), 60, 0.5, "the dead worker's lease to expire")

    def test_engine_job_is_requeued_and_completes_in_a_fresh_store(self):
        v, ps = setup_shared()
        r = submit(batch(v, ps[:1], name="crash during render"), "t24-engine")
        o = run(r["run_id"])["outputs"][0]
        jid = o["job_id"]
        w = _Worker()
        try:
            wait_for(lambda: self.jobrow(jid)["stage"] == "transaction", what="the worker to reach the render transaction")
            time.sleep(1.0)
            w.kill()
        finally:
            w.stop()
        self.assertEqual(self.jobrow(jid)["status"], "running", "the database still shows the dead worker's claim")
        wait_for(lambda: not engine_children(jid), 15, 0.5, "orphaned engine steps to stop with their worker")
        self.wait_lease_expired(jid)
        rec = S.worker.recover()
        self.assertIn({"job": jid, "action": "requeued"}, rec)
        self.assertEqual(ok(client.get(f"/api/outputs/{o['id']}"))["status"], "queued")
        S.drain()
        j = self.jobrow(jid)
        self.assertEqual((j["status"], j["attempts"]), ("completed", 2), j["error"])
        self.assertTrue((S.config.get().jobs / jid / "home-attempt-2").is_dir(), "the re-run used a fresh store")
        self.assertTrue((S.config.get().jobs / jid / "home").is_dir(), "the interrupted attempt's store is kept as evidence")
        o = ok(client.get(f"/api/outputs/{o['id']}"))
        self.assertEqual((o["status"], o["checks"]["verification_status"]), ("completed", "pass"))
        self.assertTrue(any("re-queued after the worker stopped" in e["message"] for e in o["events"]))
        S.record("T24.engine", {"recover": rec, "attempts": j["attempts"], "output": o["status"]})

    def test_paid_request_in_flight_is_never_resent(self):
        v, ps = setup_shared()
        r = submit(batch(v, ps[:1], mode="creative", name="crash during paid request"), "t24-paid")
        o = run(r["run_id"])["outputs"][0]
        jid = o["job_id"]
        w = _Worker(DNA_MOCK_DELAY_SECONDS="120")
        try:
            wait_for(lambda: S.db.one(self.conn, "SELECT id FROM provider_requests WHERE job_id = ? AND status = 'sending'", (jid,)),
                     what="the provider request to be in flight")
            w.kill()
        finally:
            w.stop()
        self.wait_lease_expired(jid)
        rec = S.worker.recover()
        self.assertIn({"job": jid, "action": "needs_review"}, rec)
        o = ok(client.get(f"/api/outputs/{o['id']}"))
        self.assertEqual((o["status"], o["error"]["kind"]), ("needs_review", "interrupted"))
        self.assertEqual([q["status"] for q in o["provider_requests"]], ["unknown"])
        S.drain()
        self.assertEqual(S.db.one(self.conn, "SELECT COUNT(*) AS n FROM provider_requests WHERE job_id = ?", (jid,))["n"], 1,
                         "nothing was resent automatically")
        blind = client.post(f"/api/outputs/{o['id']}/retry", json={"idempotency_key": "t24-paid-retry"})
        self.assertEqual(blind.json()["error"]["code"], "confirm_paid_retry")
        rt = ok(client.post(f"/api/outputs/{o['id']}/retry", json={"idempotency_key": "t24-paid-retry", "confirm_new_paid_request": True}))
        S.drain()
        self.assertEqual(ok(client.get(f"/api/outputs/{rt['output_id']}"))["status"], "completed")
        S.record("T24.paid", {"recover": rec, "provider_request": "unknown", "explicit_retry": "completed"})

    def test_cancel_stops_a_running_render(self):
        v, ps = setup_shared()
        r = submit(batch(v, ps[:1], name="cancel while rendering"), "t24-cancel")
        o = run(r["run_id"])["outputs"][0]
        jid = o["job_id"]
        w = _Worker()
        try:
            wait_for(lambda: self.jobrow(jid)["stage"] == "transaction", what="the render transaction")
            c = ok(client.post(f"/api/outputs/{o['id']}/cancel"))
            self.assertEqual((c["status"], c["cancel_requested"]), ("running", 1))
            wait_for(lambda: self.jobrow(jid)["status"] == "cancelled", 120, 0.3, "the worker to stop the step")
            self.assertIsNone(w.p.poll(), "the worker itself keeps running")
        finally:
            w.stop()
        wait_for(lambda: not engine_children(jid), 15, 0.5, "the engine step to stop")
        o = ok(client.get(f"/api/outputs/{o['id']}"))
        self.assertEqual(o["status"], "cancelled")
        S.record("T24.cancel_running", {"job": jid, "status": "cancelled"})


class T26Exports(unittest.TestCase):
    def test_zip_manifest_and_single_downloads(self):
        v, ps = setup_shared()
        if "adapt_run" not in _T:
            _T["adapt_run"] = submit(batch(v, ps), "t26-adapt")["run_id"]
            S.drain()
        rid = _T["adapt_run"]
        secret = "sk-test-NEVER-EXPORT-" + hashlib.sha256(rid.encode()).hexdigest()[:12]
        ok(client.put("/api/providers/credentials", json={"name": "OPENAI_API_KEY", "value": secret}))
        try:
            sfile = S.config.get().data_dir / "secrets.json"
            self.assertEqual(oct(sfile.stat().st_mode & 0o777), "0o600")
            r = client.post(f"/api/runs/{rid}/zip", json={})
            self.assertEqual(r.status_code, 200, r.text[:500])
            listing = client.get(f"/api/runs/{rid}").text
        finally:
            ok(client.put("/api/providers/credentials", json={"name": "OPENAI_API_KEY", "value": None}))
        self.assertNotIn(secret.encode(), r.content)
        self.assertNotIn(secret, listing)
        self.assertIn("attachment", r.headers["content-disposition"])
        z = zipfile.ZipFile(io.BytesIO(r.content))
        names = z.namelist()
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("manifest.json", names)
        self.assertIn("MANIFEST.txt", names)
        self.assertFalse([n for n in names if n.startswith("/") or ".." in n or "secrets" in n or n.endswith(".db")])
        man = json.loads(z.read("manifest.json"))
        outs = {o["id"]: o for o in run(rid)["outputs"]}
        latest = {}
        for o in outs.values():
            if o["status"] == "completed" and (o["pair_id"] not in latest or o["revision"] > latest[o["pair_id"]]["revision"]):
                latest[o["pair_id"]] = o
        self.assertEqual({e["output_id"] for e in man["outputs"]}, {o["id"] for o in latest.values()}, "the latest completed revision per output")
        for e in man["outputs"]:
            o = outs[e["output_id"]]
            for f, arc in zip([f for f in o["files"]], e["archive_paths"]):
                self.assertEqual(hashlib.sha256(z.read(arc)).hexdigest(), f["sha256"], arc)
            self.assertTrue(e["copy"] and e["checks"])
        txt = z.read("MANIFEST.txt").decode()
        self.assertIn("Design DNA export", txt)
        pick = next(iter(latest.values()))
        r1 = client.post(f"/api/runs/{rid}/zip", json={"output_ids": [pick["id"]], "include_evidence": False})
        z1 = zipfile.ZipFile(io.BytesIO(r1.content))
        self.assertFalse([n for n in z1.namelist() if "evidence" in n])
        other = client.post(f"/api/runs/{rid}/zip", json={"output_ids": ["op_not_in_this_run"]})
        self.assertEqual((other.status_code, other.json()["error"]["code"]), (400, "bad_selection"))
        i = next(i for i, f in enumerate(pick["files"]) if f["kind"] == "png")
        d = client.get(f"{pick['files'][i]['url']}?download=1")
        self.assertIn("attachment", d.headers["content-disposition"])
        self.assertIn(pick["files"][i]["name"], d.headers["content-disposition"])
        S.record("T26", {"zip_members": names, "outputs": len(man["outputs"]), "secret_absent": True})


if __name__ == "__main__":
    unittest.main()
