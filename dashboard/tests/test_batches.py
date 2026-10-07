"""T09 main-page batch · T10 per-output copy survives reorder/reload · T11 precedence, explicit blanks, AI drafts
· T12 single-template entry · T13 Arabic glyphs/direction and long copy fit checks."""
from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

import support as S
from support import client, ok

_T: dict = {}


def three_templates():
    if "t" not in _T:
        base = S.base_template()
        c1 = S.copy_of(base["id"], "Botanical — copy A")
        c2 = S.copy_of(base["id"], "Botanical — copy B")
        _T["t"] = [base["version"], c1["current_version"], c2["current_version"]]
        _T["p"] = [S.product("Sage chair", (120, 140, 100)), S.product("Oak stool", (150, 110, 70))]
    return _T["t"], _T["p"]


def pair_of(m, product_id, template_id, vi=0):
    return next(p for p in m["pairs"] if p["product_id"] == product_id and p["template_id"] == template_id and p["variant_index"] == vi)


def slot(p, role):
    return next(s for s in p["slots"] if s["role"] == role)


class T09Batch(unittest.TestCase):
    def test_two_products_by_three_templates(self):
        vs, ps = three_templates()
        m = ok(client.post("/api/batches", json={"name": "Six outputs", "template_versions": [{"version_id": v["id"]} for v in vs],
                                                 "product_ids": [p["id"] for p in ps]}))
        self.assertEqual(m["counts"]["proposed"], 6)
        self.assertEqual(len({p["pair_id"] for p in m["pairs"]}), 6, "six distinct, stable pair ids")
        victim = m["pairs"][2]["pair_id"]
        m = ok(client.patch(f"/api/batches/{m['batch']['id']}/pairs/{victim}", json={"included": False}))
        self.assertEqual((m["counts"]["included"], m["counts"]["excluded"]), (5, 1))
        m = ok(client.post(f"/api/batches/{m['batch']['id']}/variants", json={"product_id": ps[0]["id"], "template_id": vs[0]["template_id"]}))
        self.assertEqual(m["counts"]["proposed"], 7, "an extra variant is its own output, never a silent multiplication")
        S.record("T09", {"pairs": 6, "after_exclusion": m["counts"]})


class T10PerOutputCopy(unittest.TestCase):
    def test_copy_stays_with_its_pair_through_reorder_and_reload(self):
        vs, ps = three_templates()
        m = ok(client.post("/api/batches", json={"template_versions": [{"version_id": v["id"]} for v in vs], "product_ids": [p["id"] for p in ps]}))
        bid = m["batch"]["id"]
        texts = {}
        for i, p in enumerate(m["pairs"]):
            hs = slot(p, "headline")
            val = f"Line {i}\nfor pair {i}"
            texts[p["pair_id"]] = val
            m = ok(client.patch(f"/api/batches/{bid}/pairs/{p['pair_id']}", json={"manual": {hs["slot_id"]: {"value": val}},
                                                                                     "instructions": f"pair {i} only"}))
        rev = m["batch"]["revision"]
        m = ok(client.patch(f"/api/batches/{bid}", json={"base_revision": rev, "changes": {"product_ids": [ps[1]["id"], ps[0]["id"]],
                                                                                         "template_versions": [{"template_id": v["template_id"], "version_id": v["id"]} for v in reversed(vs)]}}))
        m = ok(TestClient(S.create_app()).get(f"/api/batches/{bid}"))  # reload from a fresh server instance
        for p in m["pairs"]:
            self.assertEqual(slot(p, "headline")["value"], texts[p["pair_id"]])
            self.assertEqual(p["pair_instructions"], f"pair {list(texts).index(p['pair_id'])} only")
        drop = ok(client.patch(f"/api/batches/{bid}", json={"base_revision": m["batch"]["revision"], "changes": {"product_ids": [ps[0]["id"]]}}))
        self.assertEqual(drop["counts"]["proposed"], 3)
        back = ok(client.patch(f"/api/batches/{bid}", json={"base_revision": drop["batch"]["revision"], "changes": {"product_ids": [ps[0]["id"], ps[1]["id"]]}}))
        for p in back["pairs"]:
            self.assertEqual(slot(p, "headline")["value"], texts[p["pair_id"]], "content returns with a re-added pair")
        stale = client.patch(f"/api/batches/{bid}", json={"base_revision": 0, "changes": {"name": "x"}})
        self.assertEqual(stale.status_code, 409)
        S.record("T10", {"pairs": len(texts), "survived_reorder_reload_readd": True})


class T11Precedence(unittest.TestCase):
    def test_layers_blanks_and_ai_drafts(self):
        vs, ps = three_templates()
        m = ok(client.post("/api/batches", json={"template_versions": [{"version_id": vs[0]["id"]}, {"version_id": vs[1]["id"]}],
                                                 "product_ids": [p["id"] for p in ps]}))
        bid = m["batch"]["id"]
        p00 = pair_of(m, ps[0]["id"], vs[0]["template_id"])
        cta = slot(p00, "cta")
        self.assertEqual((cta["value"], cta["source"]), ("Shop now", "template default"))
        rev = m["batch"]["revision"]
        m = ok(client.patch(f"/api/batches/{bid}", json={"base_revision": rev, "changes": {"defaults": {"copy": {"cta": "See it", "headline": "Batch\nheadline"}}}}))
        self.assertEqual(slot(pair_of(m, ps[0]["id"], vs[0]["template_id"]), "cta")["source"], "batch default")
        m = ok(client.post(f"/api/batches/{bid}/apply", json={"scope": {"kind": "product", "product_id": ps[0]["id"]}, "copy": {"cta": "Sit down"}}))
        self.assertEqual(slot(pair_of(m, ps[0]["id"], vs[0]["template_id"]), "cta")["value"], "Sit down")
        self.assertEqual(slot(pair_of(m, ps[1]["id"], vs[0]["template_id"]), "cta")["value"], "See it", "other product keeps the batch default")
        m = ok(client.post(f"/api/batches/{bid}/apply", json={"scope": {"kind": "template", "template_id": vs[1]["template_id"]}, "copy": {"cta": "Look closer"}}))
        self.assertEqual(slot(pair_of(m, ps[0]["id"], vs[1]["template_id"]), "cta")["source"], "pair override")
        p00 = pair_of(m, ps[0]["id"], vs[0]["template_id"])
        m = ok(client.patch(f"/api/batches/{bid}/pairs/{p00['pair_id']}", json={"manual": {slot(p00, "cta")["slot_id"]: {"value": ""},
                                                                                           slot(p00, "headline")["slot_id"]: {"value": "Mine\nalone"}}}))
        p00 = pair_of(m, ps[0]["id"], vs[0]["template_id"])
        self.assertEqual((slot(p00, "cta")["value"], slot(p00, "cta")["hidden"]), ("", True), "an empty string is a deliberate value")
        m = ok(client.post(f"/api/batches/{bid}/apply", json={"scope": {"kind": "all"}, "copy": {"headline": "Later\nbatch value", "cta": "Later cta"}}))
        p00 = pair_of(m, ps[0]["id"], vs[0]["template_id"])
        self.assertEqual(slot(p00, "headline")["value"], "Mine\nalone", "manual text wins over later bulk values")
        self.assertEqual(slot(p00, "cta")["value"], "", "the explicit blank survives too")
        j = ok(client.post(f"/api/batches/{bid}/draft-copy", json={"pair_ids": [x["pair_id"] for x in m["pairs"]]}))
        S.drain()
        self.assertEqual(S.job(j["id"])["status"], "completed")
        m = ok(client.get(f"/api/batches/{bid}"))
        p00 = pair_of(m, ps[0]["id"], vs[0]["template_id"])
        h = slot(p00, "headline")
        self.assertEqual(h["value"], "Mine\nalone", "AI drafting never replaces manual text")
        self.assertTrue(h["ai_draft"]["mock"] and h["ai_draft"]["value"].startswith("[mock]"))
        m = ok(client.post(f"/api/batches/{bid}/pairs/{p00['pair_id']}/use-draft/{h['slot_id']}"))
        p00 = pair_of(m, ps[0]["id"], vs[0]["template_id"])
        self.assertEqual((slot(p00, "headline")["source"], slot(p00, "headline")["approved"]), ("AI draft", False))
        self.assertIn("AI draft not approved", " ".join(p00["problems"]))
        sub = client.post(f"/api/batches/{bid}/submit", json={"idempotency_key": "unapproved-ai"})
        self.assertEqual(sub.status_code, 409, "unapproved AI copy cannot be submitted")
        m = ok(client.post(f"/api/batches/{bid}/pairs/{p00['pair_id']}/approve/{h['slot_id']}"))
        self.assertTrue(slot(pair_of(m, ps[0]["id"], vs[0]["template_id"]), "headline")["approved"])
        S.record("T11", {"layers": ["template default", "batch default", "product override", "pair override", "manual"], "blank_survives": True,
                         "ai_draft_unapproved_blocks_submit": 409})


class T12SingleTemplate(unittest.TestCase):
    def test_single_template_entry_uses_the_same_composer(self):
        vs, ps = three_templates()
        m = ok(client.post("/api/batches", json={"template_versions": [{"version_id": vs[0]["id"]}], "product_ids": [p["id"] for p in ps]}))
        self.assertEqual(m["counts"]["proposed"], 2)
        self.assertEqual({p["template_id"] for p in m["pairs"]}, {vs[0]["template_id"]})
        S.record("T12", {"pairs": 2})


class T13LanguageAndFit(unittest.TestCase):
    def test_arabic_and_long_copy_get_real_checks(self):
        vs, ps = three_templates()
        m = ok(client.post("/api/batches", json={"template_versions": [{"version_id": vs[0]["id"]}], "product_ids": [ps[0]["id"]]}))
        bid, p = m["batch"]["id"], m["pairs"][0]
        hs = slot(p, "headline")["slot_id"]
        m = ok(client.patch(f"/api/batches/{bid}/pairs/{p['pair_id']}", json={"manual": {hs: {"value": "Carry the quiet confidence of a chair built\nfor every single day"}}}))
        j = ok(client.post(f"/api/batches/{bid}/pairs/{p['pair_id']}/preview"))
        S.drain()
        m = ok(client.get(f"/api/batches/{bid}"))
        p = m["pairs"][0]
        self.assertEqual(p["preview"]["status"], "overflow", S.job(j["id"]))
        self.assertIn("n-headline", p["preview"]["fit"]["overflow"])
        self.assertTrue(any("shorten" in o for o in p["preview"]["fit"]["options"]))
        self.assertTrue(any("does not fit" in x for x in p["problems"]), "an overflow blocks submission")
        fonts = ok(client.get("/api/fonts"))
        latin_only = next(f for f in fonts if f["names"]["family"].startswith("Liberation Sans"))
        amiri = next(f for f in fonts if "Amiri" in f["names"]["family"])
        ar = "مقعد من خشب البلوط\nلكل يوم"
        m = ok(client.patch(f"/api/batches/{bid}", json={"base_revision": m["batch"]["revision"], "changes": {"defaults": {"language": "ar", "arabic_font": latin_only["sha256"]}}}))
        m = ok(client.patch(f"/api/batches/{bid}/pairs/{p['pair_id']}", json={"manual": {hs: {"value": ar}}}))
        self.assertTrue(any("lacks glyphs" in x for x in m["pairs"][0]["problems"]), "no silent fallback font")
        m = ok(client.patch(f"/api/batches/{bid}", json={"base_revision": m["batch"]["revision"], "changes": {"defaults": {"arabic_font": amiri["sha256"]}}}))
        for k in ("kicker", "cta"):
            m = ok(client.patch(f"/api/batches/{bid}/pairs/{p['pair_id']}", json={"manual": {slot(p, k)["slot_id"]: {"value": "خصم" if k == "cta" else ""}}}))
        self.assertFalse(m["pairs"][0]["problems"], m["pairs"][0]["problems"])
        j = ok(client.post(f"/api/batches/{bid}/pairs/{p['pair_id']}/preview"))
        S.drain()
        p = ok(client.get(f"/api/batches/{bid}"))["pairs"][0]
        self.assertIn(p["preview"]["status"], ("fits", "fitted", "overflow"), S.job(j["id"]))
        run = None
        if p["preview"]["status"] != "overflow":
            run = ok(client.post(f"/api/batches/{bid}/submit", json={"idempotency_key": "arabic-1"}))
            S.drain()
            o = ok(client.get(f"/api/runs/{run['run_id']}"))["outputs"][0]
            self.assertEqual(o["status"], "completed", o.get("error"))
            self.assertEqual(o["language"], "ar")
        S.record("T13", {"long_copy": "overflow refused with options", "latin_font_for_arabic": "refused (lacks glyphs)",
                         "arabic_preview": p["preview"]["status"], "arabic_output": bool(run)})


if __name__ == "__main__":
    unittest.main()
