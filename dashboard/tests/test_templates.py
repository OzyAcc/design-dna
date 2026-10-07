"""T04 drafts survive reload · T05 assisted/manual scan coverage · T06 staged rebuild · T07 inspector data · T08 copy/edit/restore
· T14 locked change · T20/T21 legacy pin + bound migration (dashboard level) · T22 fresh-process reproducibility · T25 bundle round trip."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import support as S
from support import client, ok
from dna_dashboard import config, enginelib as el, templates_svc as ts


class T04DraftReload(unittest.TestCase):
    def test_incomplete_draft_survives_a_new_app_instance(self):
        png, els = S.fixtures.poster()
        a = S.upload(png, "inspiration", "draft.png")["assets"][0]
        t = ok(client.post("/api/templates", json={"asset_id": a["id"], "name": "Unfinished scan"}))
        part = [dict(e, status="proposed" if e["type"] == "text" else "accepted") for e in els[:4]]
        t = ok(client.patch(f"/api/templates/{t['id']}/draft", json={"base_revision": t["draft_revision"], "changes": {
            "passport": {"goal": {"value": "seasonal launch", "status": "user_supplied"}, "character": {"value": "quiet", "status": "suggested"}},
            "draft": {"elements": part, "step": "scan"}}}))
        stale = client.patch(f"/api/templates/{t['id']}/draft", json={"base_revision": t["draft_revision"] - 1, "changes": {"draft": {"step": "rules"}}})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["error"]["code"], "stale_draft")
        fresh = TestClient(S.create_app())  # a restarted server reads the same database and files
        t2 = ok(fresh.get(f"/api/templates/{t['id']}"))
        self.assertEqual(t2["status"], "draft")
        self.assertEqual(t2["draft"]["elements"], part)
        self.assertEqual(t2["passport"]["character"]["status"], "suggested", "a suggestion stays labelled until accepted")
        self.assertEqual(t2["readiness"], "scan_in_progress")
        cov = ok(fresh.get(f"/api/templates/{t['id']}/model?source=work"))["scene"]["scan"]["coverage"]
        self.assertEqual(cov["responsive_system"]["status"], "unknown")
        self.assertNotIn("typography", cov, "an unscanned category is absent, never a pass")
        S.record("T04", {"draft_restored": True, "stale_refused": 409})


class T05Scan(unittest.TestCase):
    def test_manual_scan_measures_every_category_and_labels_unknowns(self):
        base = S.base_template()
        m = ok(client.get(f"/api/templates/{base['id']}/model?source=current"))
        cov = m["scene"]["scan"]["coverage"]
        cats, facets = m["constants"]["categories"], m["constants"]["facets"]
        self.assertEqual(sorted(cov), sorted(cats), "all 16 categories have a result")
        for cat, need in facets.items():
            if cov[cat]["status"] != "not_applicable":
                self.assertTrue(set(need) <= set(cov[cat].get("facets", {})), cat)
        self.assertEqual(cov["typography"]["facets"]["font_identity"]["status"], "unknown", "a matching candidate is not identity")
        self.assertNotEqual(cov["message_mechanism"]["status"], "measured")
        ev = {e["evidence_id"]: e for e in m["evidence"]}
        for cat, e in cov.items():
            for f in [e] + list((e.get("facets") or {}).values()):
                if f["status"] in ("measured", "observed"):
                    self.assertTrue(f.get("evidence_ids"), cat)
                    for i in f["evidence_ids"]:
                        self.assertIn(i, ev, f"{cat} cites a missing evidence record {i}")
        self.assertEqual(ev["ev-app-transcription"]["method"], "manual_observation")
        text_nodes = [n for n in m["scene"]["nodes"] if n["type"] == "text"]
        self.assertTrue(all(n["provenance"]["font.size"]["status"] == "measured" for n in text_nodes))
        # evidence validation catches a missing fact
        scene = json.loads(json.dumps(m["scene"]))
        tdir = ts.version_dir(ts.version(S.db.connect(), base["version"]["id"]))
        full = el.read_json(tdir / "scene.json")
        full["scan"]["coverage"]["color"]["evidence_ids"] = ["ev-does-not-exist"]
        rep = el.check_scene(full, tdir)
        self.assertFalse(rep["valid"])
        self.assertTrue(any("ev-does-not-exist" in e for e in rep["errors"]))
        S.record("T05", {"categories": len(cov), "unknown": [c for c, e in cov.items() if e["status"] == "unknown"], "text_nodes": len(text_nodes),
                         "scene_nodes": len(scene["nodes"])})

    def test_assisted_scan_with_mock_proposals_is_labelled(self):
        png, _ = S.fixtures.poster()
        a = S.upload(png, "inspiration", "assist.png")["assets"][0]
        t = ok(client.post("/api/templates", json={"asset_id": a["id"], "name": "Assisted"}))
        j = ok(client.post(f"/api/templates/{t['id']}/analyze", json={}))
        S.drain()
        self.assertEqual(S.job(j["id"])["status"], "completed")
        t = ok(client.get(f"/api/templates/{t['id']}"))
        self.assertTrue(t["draft"]["analysis_meta"]["mock"])
        self.assertTrue(all(e["status"] == "proposed" and e["source"] == "mock" for e in t["draft"]["elements"]))
        self.assertEqual(t["passport"]["goal"]["status"], "suggested")
        r = client.post(f"/api/templates/{t['id']}/measure")
        self.assertEqual(r.status_code, 409, "unreviewed proposals are never measured as findings")
        self.assertEqual(r.json()["error"]["code"], "unreviewed_proposals")
        S.record("T05.assisted", {"proposals": len(t["draft"]["elements"]), "labelled_mock": True, "unreviewed_refused": 409})


class T06Rebuild(unittest.TestCase):
    def test_staged_rebuild_never_overwrites_an_approved_version(self):
        base = S.base_template()
        st = base["staged"]
        self.assertIn(st["readiness"], ("partial_baseline", "editable_close", "exact_pixels"))
        self.assertEqual(st["reproducibility"]["status"], "pass", "fresh-process re-render is identical (T22)")
        for k in ("side_by_side", "overlay_50", "diff_heatmap"):
            self.assertEqual(client.get(f"/api/templates/{base['id']}/files/stage:{st['stage_id']}/{st['artifacts'][k]}").status_code, 200)
        v1 = base["version"]
        conn = S.db.connect()
        sha_before = Path(ts.version(conn, v1["id"])["bundle_path"]).read_bytes()
        j = ok(client.post(f"/api/templates/{base['id']}/rebuild", json={"mode": "exact"}))
        S.drain()
        st2 = ok(client.get(f"/api/templates/{base['id']}"))
        self.assertNotEqual(st2["draft"]["staged"]["stage_id"], st["stage_id"])
        self.assertEqual(st2["draft"]["staged"]["verdict"]["profile"], "exact_pixels")
        self.assertEqual([v["number"] for v in st2["versions"]], [1], "a staged rebuild creates no version")
        self.assertEqual(Path(ts.version(conn, v1["id"])["bundle_path"]).read_bytes(), sha_before)
        stale = client.post(f"/api/templates/{base['id']}/accept", json={"stage_id": st["stage_id"]})
        self.assertEqual(stale.status_code, 409)
        S.record("T06", {"readiness": st["readiness"], "verdict": st["verdict"]["status"], "exact_rerun": st2["draft"]["staged"]["verdict"]["status"],
                         "job": S.job(j["id"])["status"]})


class T07Inspector(unittest.TestCase):
    def test_inspector_payload(self):
        base = S.base_template()
        m = ok(client.get(f"/api/templates/{base['id']}/model?source=current"))
        s = m["scene"]
        self.assertTrue(any(n["type"] == "text" and n["content"] for n in s["nodes"]))
        self.assertTrue(any(t["type"] == "color" for t in s["tokens"].values()))
        self.assertTrue(s["slots"] and all({"id", "role", "node", "type"} <= set(x) for x in s["slots"]))
        self.assertEqual(m["passport"]["goal"]["status"], "user_supplied")
        self.assertIn("baseline", m["artifacts"])
        d = ok(client.get(f"/api/templates/{base['id']}"))
        self.assertEqual(d["versions"][0]["number"], 1)
        self.assertTrue(d["current_version"]["eligibility"]["adapt"]["eligible"])
        S.record("T07", {"nodes": len(s["nodes"]), "tokens": sorted(s["tokens"]), "slots": [x["id"] for x in s["slots"]]})


class T08CopyEditRestore(unittest.TestCase):
    def test_copy_has_its_own_identity_and_parent_stays_unchanged(self):
        base = S.base_template()
        conn = S.db.connect()
        pv = ts.version(conn, base["version"]["id"])
        parent_bundle = Path(pv["bundle_path"]).read_bytes()
        parent_model = el.model_hash(el.read_json(ts.work_tdir(ts.get(conn, base["id"])) / "scene.json"))
        c = S.copy_of(base["id"], "Botanical — green accent")
        self.assertEqual(c["role"], "copy")
        self.assertEqual(c["lineage"]["parent"]["id"], base["id"])
        self.assertEqual(c["draft"]["copy_check"]["reproduces_approved_baseline"]["status"], "pass")
        self.assertNotEqual(c["engine_id"], base["template"]["engine_id"])
        comp = ok(client.post(f"/api/templates/{c['id']}/compile", json={"text": "make the accent #2E5A44"}))
        self.assertTrue(comp["scope"]["ok"])
        self.assertIn("tokens.fill.accent.value", [x["path"] for x in comp["scope"]["changes"]])
        ok(client.post(f"/api/templates/{c['id']}/edit", json={"ops": comp["ops"], "base_revision": comp["base_revision"], "intent": "green accent"}))
        S.drain()
        d = ok(client.get(f"/api/templates/{c['id']}/design"))
        self.assertEqual(d["head"], comp["base_revision"] + 1)
        self.assertEqual(d["edits"][-1]["outside_influence"], 0)
        self.assertEqual(client.get(f"/api/templates/{c['id']}/head.png?rev={d['head']}").status_code, 200)
        ok(client.post(f"/api/templates/{c['id']}/save-version", json={"note": "green"}))
        S.drain()
        c2 = ok(client.get(f"/api/templates/{c['id']}"))
        self.assertEqual([v["number"] for v in c2["versions"]], [2, 1])
        self.assertNotEqual(c2["versions"][0]["scene_sha256"], c2["versions"][1]["scene_sha256"])
        ok(client.post(f"/api/templates/{c['id']}/restore", json={"version_id": c2["versions"][1]["id"]}))
        S.drain()
        c3 = ok(client.get(f"/api/templates/{c['id']}"))
        self.assertEqual([v["number"] for v in c3["versions"]], [3, 2, 1], "restore adds a head; history is not rewritten")
        self.assertEqual(c3["versions"][0]["scene_sha256"], c3["versions"][2]["scene_sha256"])
        self.assertEqual(Path(pv["bundle_path"]).read_bytes(), parent_bundle, "parent bundle unchanged")
        self.assertEqual(el.model_hash(el.read_json(ts.work_tdir(ts.get(conn, base["id"])) / "scene.json")), parent_model, "parent model unchanged")
        self.assertEqual(client.post(f"/api/templates/{base['id']}/edit", json={"ops": comp["ops"], "base_revision": 0}).status_code, 400,
                         "originals are read-only")
        S.record("T08", {"copy": c["id"], "versions": [v["number"] for v in c3["versions"]], "edit_outside_influence": 0})


class T14Locks(unittest.TestCase):
    def test_locked_change_is_refused_and_head_kept(self):
        base = S.base_template()
        c = S.copy_of(base["id"], "Locked layout")
        comp = ok(client.post(f"/api/templates/{c['id']}/compile", json={"text": "lock layout"}))
        ok(client.post(f"/api/templates/{c['id']}/edit", json={"ops": comp["ops"], "base_revision": comp["base_revision"], "intent": "lock layout"}))
        S.drain()
        head = ok(client.get(f"/api/templates/{c['id']}/design"))["head"]
        comp = ok(client.post(f"/api/templates/{c['id']}/compile", json={"text": "move the headline up 10px"}))
        self.assertFalse(comp["scope"]["ok"])
        self.assertTrue(any("lock" in json.dumps(x) for x in comp["scope"]["conflicts"]))
        j = ok(client.post(f"/api/templates/{c['id']}/edit", json={"ops": comp["ops"], "base_revision": comp["base_revision"], "intent": "move"}))
        S.drain()
        r = S.job(j["id"])
        self.assertEqual(r["status"], "needs_review")
        self.assertEqual(r["error"]["kind"], "conflict")
        self.assertEqual(ok(client.get(f"/api/templates/{c['id']}/design"))["head"], head)
        unsupported = client.post(f"/api/templates/{c['id']}/compile", json={"text": "give it a bevel and emboss please"})
        self.assertEqual(unsupported.status_code, 400)
        S.record("T14", {"refused": r["error"]["code"], "head_kept": head})


class T20T21Migration(unittest.TestCase):
    def test_legacy_pin_blocks_generation_until_a_bound_migration(self):
        base = S.base_template()
        c = S.copy_of(base["id"], "Legacy pin probe")
        conn = S.db.connect()
        t = ts.get(conn, c["id"])
        pp_path = ts.work_tdir(t) / "passport.json"
        pp = el.read_json(pp_path)
        pp["render_pin"].pop("text_rendering")  # what a pin written before 2.1.0 looks like
        el.write_json(pp_path, pp)
        ok(client.post(f"/api/templates/{c['id']}/save-version", json={"note": "legacy pin"}))
        S.drain()
        v = ok(client.get(f"/api/templates/{c['id']}"))["current_version"]
        self.assertIsNone(v["baseline"]["pin"]["text_rendering"])
        p = S.product("Legacy chair")
        b = ok(client.post("/api/batches", json={"template_versions": [{"version_id": v["id"]}], "product_ids": [p["id"]]}))
        pid = b["pairs"][0]["pair_id"]
        ok(client.patch(f"/api/batches/{b['batch']['id']}/pairs/{pid}", json={"manual": {base["slots"]["headline"]: {"value": "Built for\nthe long run"}}}))
        run = ok(client.post(f"/api/batches/{b['batch']['id']}/submit", json={"idempotency_key": "legacy-1"}))
        S.drain()
        o = ok(client.get(f"/api/runs/{run['run_id']}"))["outputs"][0]
        self.assertEqual(o["status"], "needs_review")
        self.assertEqual(o["error"]["kind"], "renderer_drift")
        self.assertFalse(any(f["kind"] == "png" for f in o["files"]), "no output without a preservation check")
        r = ok(client.post(f"/api/templates/{c['id']}/migrations", json={}))
        S.drain()
        mig = ok(client.get(f"/api/templates/{c['id']}/migrations"))[0]
        self.assertEqual(mig["data"]["status"], "migration_required")
        self.assertTrue(any(h["field"] == "text_rendering" and h.get("legacy_pin") for h in mig["data"]["pin_check"]["hard"]))
        wrong = client.post(f"/api/templates/{c['id']}/migrations/{r['migration_id']}/confirm", json={"preview_id": "mp-0000000000000000"})
        self.assertEqual(wrong.status_code, 409)
        ok(client.post(f"/api/templates/{c['id']}/migrations/{r['migration_id']}/confirm", json={"preview_id": mig["preview_id"]}))
        S.drain()
        c2 = ok(client.get(f"/api/templates/{c['id']}"))
        nv = c2["current_version"]
        self.assertEqual(nv["created_from"], "migration")
        self.assertTrue(nv["baseline"]["pin"]["text_rendering"])
        self.assertEqual(nv["acceptance"]["preview_id"], mig["preview_id"])
        retry = ok(client.post(f"/api/outputs/{o['id']}/retry", json={"idempotency_key": "legacy-retry"}))
        S.drain()
        o2 = ok(client.get(f"/api/outputs/{retry['output_id']}"))
        self.assertEqual(o2["status"], "needs_review", "a retry keeps its frozen (legacy) version: migration makes a NEW version")
        S.record("T20_T21", {"refused_kind": o["error"]["kind"], "preview": mig["preview_id"], "migrated_version": nv["number"],
                             "retry_keeps_frozen_version": o2["template_version_id"] == o["template_version_id"]})


class T25Bundles(unittest.TestCase):
    def test_clean_store_round_trip(self):
        base = S.base_template()
        r = client.get(base["version"]["download_url"])
        self.assertEqual(r.status_code, 200)
        other = Path(tempfile.mkdtemp(prefix="dna-clean-store-"))
        old_env, old_settings = os.environ["DNA_DATA_DIR"], config.get()
        os.environ["DNA_DATA_DIR"] = str(other)
        config.reset()
        try:
            c2 = TestClient(S.create_app())
            self.assertEqual(ok(c2.get("/api/templates"))["templates"], [])
            imp = ok(c2.post("/api/templates/import", files=[("file", ("botanical.dnab", r.content, "application/zip"))]))
            S.drain()
            t = ok(c2.get(f"/api/templates/{imp['template']['id']}"))
            v = t["current_version"]
            self.assertEqual(v["created_from"], "import")
            self.assertEqual(v["readiness"], base["version"]["readiness"])
            self.assertEqual(v["scene_sha256"], base["version"]["scene_sha256"], "same model after a clean-store import")
            self.assertEqual([s["id"] for s in v["slots"]], [s["id"] for s in base["version"]["slots"]])
            self.assertEqual(t["name"], "Botanical Editorial")
            a = ok(c2.post("/api/assets/upload", files=[("files", ("p.png", S.fixtures.product(), "image/png"))], data={"role": "product"}))["assets"][0]
            prod = ok(c2.post("/api/products", json={"name": "Imported chair", "primary_asset_id": a["id"]}))
            b = ok(c2.post("/api/batches", json={"template_versions": [{"version_id": v["id"]}], "product_ids": [prod["id"]]}))
            pid = b["pairs"][0]["pair_id"]
            ok(c2.patch(f"/api/batches/{b['batch']['id']}/pairs/{pid}", json={"manual": {base["slots"]["headline"]: {"value": "Same chair\nnew home"}}}))
            run = ok(c2.post(f"/api/batches/{b['batch']['id']}/submit", json={"idempotency_key": "rt-1"}))
            S.drain()
            o = ok(c2.get(f"/api/runs/{run['run_id']}"))["outputs"][0]
            self.assertEqual(o["status"], "completed", o.get("error"))
            self.assertTrue(o["checks"]["approved_baseline_reproduced"], "the imported baseline reproduces in the new store")
            S.record("T25", {"imported_readiness": v["readiness"], "reproduced": o["checks"]["approved_baseline_reproduced"],
                             "verification": o["checks"]["verification_status"]})
        finally:
            os.environ["DNA_DATA_DIR"] = old_env
            config.reset(old_settings)
            shutil.rmtree(other, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
