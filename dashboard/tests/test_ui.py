"""T28 the built web app in a real browser: every page at 390 px and 1280 px without horizontal scrolling or script
errors, every visible control has an accessible name, and the main journeys work from the keyboard.

Needs the built frontend (cd dashboard/web && npm ci && npm run build) and Playwright's Chromium. Without a build the
test is skipped, unless DNA_REQUIRE_UI_TEST=1 (CI), where a missing build is a failure.
"""
from __future__ import annotations

import asyncio
import os
import re
import socket
import threading
import time
import unittest

import support as S
from support import client, ok

DIST = S.config.get().web_dist
REQUIRE = os.environ.get("DNA_REQUIRE_UI_TEST") == "1"

UNNAMED = """() => {
  const bad = [];
  const shown = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; };
  for (const el of document.querySelectorAll('input, select, textarea, button, a[href], [role=button], [tabindex]:not([tabindex="-1"])')) {
    if (!shown(el) || el.type === 'hidden') continue;
    let name = (el.getAttribute('aria-label') || '') + (el.getAttribute('title') || '');
    const ids = el.getAttribute('aria-labelledby');
    if (ids) name += ids.split(/\\s+/).map((i) => (document.getElementById(i) || {}).textContent || '').join(' ');
    if (el.labels) name += Array.from(el.labels).map((l) => l.textContent).join(' ');
    if (['BUTTON', 'A'].includes(el.tagName) || el.getAttribute('role') === 'button') name += el.textContent || '';
    if (el.tagName === 'INPUT' && ['submit', 'button'].includes(el.type)) name += el.value;
    name += Array.from(el.querySelectorAll('img[alt]')).map((i) => i.alt).join(' ');
    if (!name.trim()) bad.push(el.outerHTML.slice(0, 200));
  }
  return bad;
}"""


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Browser(unittest.TestCase):
    """The built app served by a real uvicorn server, driven by Playwright's Chromium."""

    @classmethod
    def start(cls, wrap=None):
        import uvicorn

        port = _free_port()
        cls.base = f"http://127.0.0.1:{port}"
        app = S.create_app()
        cls.server = uvicorn.Server(uvicorn.Config(wrap(app) if wrap else app, host="127.0.0.1", port=port, log_level="warning"))
        threading.Thread(target=cls.server.run, daemon=True).start()
        t = time.time()
        while not cls.server.started:
            if time.time() - t > 30:
                raise RuntimeError("the test server did not start")
            time.sleep(0.1)
        from playwright.sync_api import sync_playwright

        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.should_exit = True

    def open(self, width):
        page = self.browser.new_page(viewport={"width": width, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error" else None)
        return page, errors

    def settle(self, page):
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(300)


@unittest.skipUnless(REQUIRE or (DIST / "index.html").exists(), "the web app is not built (npm run build in dashboard/web)")
class T28Browser(_Browser):
    @classmethod
    def setUpClass(cls):
        base = S.base_template()
        cls.copy = S.copy_of(base["id"], "UI probe copy")
        p = S.product("UI chair", (120, 140, 100))
        m = ok(client.post("/api/batches", json={"name": "UI batch", "template_versions": [{"version_id": base["version"]["id"]}],
                                                 "product_ids": [p["id"]]}))
        pr = m["pairs"][0]
        hs = next(s for s in pr["slots"] if s["role"] == "headline")["slot_id"]
        ok(client.patch(f"/api/batches/{m['batch']['id']}/pairs/{pr['pair_id']}", json={"manual": {hs: {"value": "Built to\nlast years"}}}))
        run = ok(client.post(f"/api/batches/{m['batch']['id']}/submit", json={"idempotency_key": "ui-run"}))
        S.drain()
        cls.ids = {"template": base["id"], "copy": cls.copy["id"], "batch": m["batch"]["id"], "run": run["run_id"]}
        cls.start()

    def pages(self):
        i = self.ids
        return ["/templates", "/templates/new", f"/templates/new?id={i['template']}", f"/templates/{i['template']}", f"/templates/{i['copy']}",
                f"/templates/{i['copy']}/edit", "/generate", f"/generate?batch={i['batch']}", "/runs", f"/runs/{i['run']}", "/settings"]

    def test_pages_fit_have_named_controls_and_no_errors(self):
        report, problems = {}, []
        for width in (390, 1280):
            page, errors = self.open(width)
            for path in self.pages():
                page.goto(self.base + path)
                self.settle(page)
                if not page.locator("h1:visible, h2:visible").count():
                    problems.append(f"{width} {path}: no visible heading")
                sw = page.evaluate("document.documentElement.scrollWidth")
                if sw > width:
                    problems.append(f"{width} {path}: scrolls sideways ({sw}px)")
                unnamed = page.evaluate(UNNAMED)
                if unnamed:
                    problems.append(f"{width} {path}: controls without an accessible name: {unnamed[:4]}")
                report[f"{width} {path}"] = {"scroll_width": sw, "unnamed_controls": len(unnamed)}
            problems += [f"{width}: {e}" for e in errors]
            page.close()
        S.record("T28.pages", report)
        self.assertFalse(problems, "\n".join(problems))

    def test_keyboard_journeys(self):
        page, errors = self.open(1280)
        page.goto(self.base + "/templates")
        self.settle(page)
        page.keyboard.press("Tab")
        self.assertEqual(page.evaluate("document.activeElement.textContent"), "Skip to content")
        self.assertGreaterEqual(page.evaluate("document.activeElement.getBoundingClientRect().left"), 0, "the skip link is visible when focused")
        for _ in range(20):
            page.keyboard.press("Tab")
            if page.evaluate("document.activeElement.textContent.trim()") == "Generate":
                break
        else:
            self.fail("the Generate link is not reachable with Tab")
        ring = page.evaluate("(() => { const cs = getComputedStyle(document.activeElement); return cs.boxShadow + ' ' + cs.outlineStyle; })()")
        self.assertNotEqual(ring.strip(), "none none", "the focused link shows a focus indicator")
        page.keyboard.press("Enter")
        page.wait_for_url("**/generate")
        page.close()

        page, errors2 = self.open(390)
        page.goto(self.base + "/templates")
        self.settle(page)
        for _ in range(5):
            page.keyboard.press("Tab")
            if "Menu" in page.evaluate("document.activeElement.textContent"):
                break
        else:
            self.fail("the menu button is not reachable with Tab on a phone-width screen")
        page.keyboard.press("Enter")
        self.assertEqual(page.get_attribute("button[aria-controls=sidebar]", "aria-expanded"), "true")
        for _ in range(12):
            page.keyboard.press("Tab")
            if page.evaluate("document.activeElement.textContent.trim()") == "Results":
                break
        else:
            self.fail("the Results link is not reachable from the opened menu")
        page.keyboard.press("Enter")
        page.wait_for_url("**/runs")
        self.settle(page)
        self.assertFalse(page.locator("#sidebar").is_visible(), "the menu closes after navigating")
        page.close()
        self.assertFalse(errors + errors2, (errors + errors2)[:10])
        S.record("T28.keyboard", {"skip_link": True, "desktop_nav": "/generate", "phone_menu": "/runs"})


def _slow_marked_writes(app):
    """Hold any write whose body contains SLOW_MARK on the server for 3 s while other requests proceed (the server
    handles requests concurrently), so a client that sends a later write before the earlier one is answered loses it."""
    async def wrapped(scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("PATCH", "POST"):
            return await app(scope, receive, send)
        msgs, more = [], True
        while more:
            m = await receive()
            msgs.append(m)
            more = m.get("more_body", False)
        if SLOW_MARK.encode() in b"".join(m.get("body", b"") for m in msgs):
            await asyncio.sleep(3)
        it = iter(msgs)

        async def replay():
            return next(it, None) or await receive()
        return await app(scope, replay, send)
    return wrapped


SLOW_MARK = "Slow first"


@unittest.skipUnless(REQUIRE or (DIST / "index.html").exists(), "the web app is not built (npm run build in dashboard/web)")
class ComposerWrites(_Browser):
    """Audit D1 and D2 in the browser: what is generated is exactly what was on screen, and a submission whose answer
    was lost is recovered instead of repeated."""

    @classmethod
    def setUpClass(cls):
        cls.tpl = S.base_template()
        cls.product = S.product("Composer chair", (120, 140, 100))
        cls.start(_slow_marked_writes)

    def fresh_batch(self, name):
        m = ok(client.post("/api/batches", json={"name": name, "template_versions": [{"version_id": self.tpl["version"]["id"]}],
                                                 "product_ids": [self.product["id"]]}))
        pr = m["pairs"][0]
        hs = next(s for s in pr["slots"] if s["role"] == "headline")["slot_id"]
        ok(client.patch(f"/api/batches/{m['batch']['id']}/pairs/{pr['pair_id']}", json={"manual": {hs: {"value": "Saved\nheadline"}}}))
        return m["batch"]["id"], pr["pair_id"]

    def slot_value(self, bid, role):
        pr = ok(client.get(f"/api/batches/{bid}"))["pairs"][0]
        return next(s for s in pr["slots"] if s["role"] == role)["value"]

    def runs_of(self, bid):
        return [r["id"] for r in S.db.all_(S.db.connect(), "SELECT id FROM runs WHERE batch_id = ? ORDER BY created_at", (bid,))]

    def cancel_runs(self, bid):  # these runs only prove what was frozen; nothing needs rendering
        for rid in self.runs_of(bid):
            for o in ok(client.get(f"/api/runs/{rid}"))["outputs"]:
                if o["status"] == "queued":
                    ok(client.post(f"/api/outputs/{o['id']}/cancel"))

    def compose(self, bid):
        page, errors = self.open(1280)
        page.goto(f"{self.base}/generate?batch={bid}")
        page.wait_for_selector('textarea[aria-label="headline copy"]')
        self.settle(page)
        return page, errors

    def generate_button(self, page):
        return page.get_by_role("button", name=re.compile(r"^Generate \d+ output")).first

    def saved(self, page, timeout=15000):
        page.wait_for_selector("text=all changes saved", timeout=timeout)

    def test_generate_freezes_what_was_typed_even_before_it_was_saved(self):
        bid, _ = self.fresh_batch("type then generate")
        page, errors = self.compose(bid)
        typed = f"{SLOW_MARK}, typed\nbefore Generate"
        page.fill('textarea[aria-label="headline copy"]', typed)
        self.generate_button(page).click()  # within the 900 ms save delay; the server then takes 3 s to store the save
        page.wait_for_url("**/runs/*", timeout=30000)
        rid = page.url.rstrip("/").split("/")[-1]
        o = ok(client.get(f"/api/runs/{rid}"))["outputs"][0]
        frozen = next(s for s in o["inputs"]["slots"] if s["role"] == "headline")["value"]
        self.assertEqual(frozen, typed, "the run froze the copy that was on screen")
        self.cancel_runs(bid)
        page.close()
        self.assertFalse(errors, errors[:5])
        S.record("D1.type_then_generate", {"frozen": frozen})

    def test_leave_empty_inside_the_save_delay_stays_empty(self):
        bid, _ = self.fresh_batch("leave empty")
        page, errors = self.compose(bid)
        kicker = page.locator(".slot-field", has=page.locator('textarea[aria-label="kicker copy"]'))
        page.fill('textarea[aria-label="kicker copy"]', "Temporary kicker")
        kicker.get_by_role("button", name="Leave empty").click()
        page.wait_for_timeout(2500)  # well past the 900 ms delay of the typed edit
        self.saved(page)
        self.assertEqual(self.slot_value(bid, "kicker"), "", "the explicit choice wins over the earlier typing")
        self.assertEqual(page.input_value('textarea[aria-label="kicker copy"]'), "")
        page.close()
        self.assertFalse(errors, errors[:5])
        S.record("D1.leave_empty", {"server": "", "screen": ""})

    def test_a_slow_earlier_save_cannot_overwrite_a_later_one(self):
        bid, _ = self.fresh_batch("out of order")
        page, errors = self.compose(bid)
        sent = []
        page.on("request", lambda r: sent.append(r.post_data) if r.method == "PATCH" and "/pairs/" in r.url else None)
        page.fill('textarea[aria-label="headline copy"]', f"{SLOW_MARK}\nversion")
        page.wait_for_timeout(1500)  # its save has been sent; the server holds it for 3 s
        page.fill('textarea[aria-label="headline copy"]', "Second\nversion")
        self.saved(page, 20000)
        self.assertEqual(self.slot_value(bid, "headline"), "Second\nversion")
        self.assertEqual(page.input_value('textarea[aria-label="headline copy"]'), "Second\nversion")
        self.assertTrue(sent and "Second" in sent[-1], "the later value is the last one sent")
        page.close()
        self.assertFalse(errors, errors[:5])
        self.assertTrue(any(SLOW_MARK in (b or "") for b in sent), "the slow save was sent first")
        S.record("D1.out_of_order", {"server": "Second", "patches_sent": len(sent)})

    def test_a_failed_save_blocks_generation_and_survives_a_reload(self):
        bid, pid = self.fresh_batch("failed save")
        page, errors = self.compose(bid)
        submits = []
        page.on("request", lambda r: submits.append(r.url) if r.url.endswith("/submit") else None)
        page.route(re.compile(r".*/api/batches/[^/]+/pairs/[^/]+$"), lambda route: route.abort("failed") if route.request.method == "PATCH" else route.continue_())
        page.fill('textarea[aria-label="headline copy"]', "Kept in\nthis browser")
        page.wait_for_selector("text=change(s) not saved", timeout=15000)
        self.generate_button(page).click()
        page.wait_for_selector("text=Generating stopped", timeout=15000)
        self.assertIn("/generate", page.url)
        self.assertEqual(submits, [], "nothing was submitted from content the server never received")
        self.assertEqual(self.slot_value(bid, "headline"), "Saved\nheadline")
        page.unroute(re.compile(r".*/api/batches/[^/]+/pairs/[^/]+$"))
        page.reload()
        page.wait_for_selector('textarea[aria-label="headline copy"]')
        self.assertEqual(page.input_value('textarea[aria-label="headline copy"]'), "Kept in\nthis browser", "restored after the reload")
        self.saved(page)
        self.assertEqual(self.slot_value(bid, "headline"), "Kept in\nthis browser", "and saved once the server is reachable")
        keys = page.evaluate("Object.keys(localStorage).filter((k) => k.startsWith('dna.unsent.'))")
        self.assertEqual(keys, [], "the kept copy is removed only after the server acknowledged it")
        page.close()
        errors = [e for e in errors if "Failed to load resource" not in e and "ERR_FAILED" not in e]
        self.assertFalse(errors, errors[:5])
        S.record("D1.failed_save", {"submit_blocked": True, "restored_after_reload": True, "saved_after_reload": True})

    def test_a_lost_submit_response_is_recovered_not_repeated(self):
        bid, _ = self.fresh_batch("lost response")
        page, errors = self.compose(bid)
        submit_re = re.compile(r".*/api/batches/[^/]+/submit$")

        def lose_answer(route):
            route.fetch()  # the server receives it and creates the run ...
            route.abort("failed")  # ... and the browser never hears back

        page.route(submit_re, lose_answer)
        self.generate_button(page).click()
        page.wait_for_selector("text=could not be confirmed", timeout=30000)
        self.assertEqual(len(self.runs_of(bid)), 1)
        key = page.evaluate(f"localStorage.getItem('dna.submit.{bid}')")
        self.assertTrue(key, "the submission's identity is kept while its outcome is unknown")
        page.unroute(submit_re)
        self.generate_button(page).click()  # the user tries again
        page.wait_for_url("**/runs/*", timeout=30000)
        first = self.runs_of(bid)
        self.assertEqual(len(first), 1, "the retry returned the same run")
        self.assertTrue(page.url.endswith(first[0]))
        page.goto(f"{self.base}/generate?batch={bid}")
        page.wait_for_selector('textarea[aria-label="headline copy"]')
        page.route(submit_re, lose_answer)
        self.generate_button(page).click()
        page.wait_for_selector("text=could not be confirmed", timeout=30000)
        page.unroute(submit_re)
        runs = self.runs_of(bid)
        self.assertEqual(len(runs), 2, "a new click on Generate is a new run")
        page.reload()  # the page comes back without knowing what happened
        page.wait_for_selector("text=Your last submission was received", timeout=15000)
        self.assertEqual(page.get_attribute("a:has-text('Open that run')", "href"), f"/runs/{runs[1]}")
        self.assertIsNone(page.evaluate(f"localStorage.getItem('dna.submit.{bid}')"))
        self.generate_button(page).click()  # explicitly generating again
        page.wait_for_url("**/runs/*", timeout=30000)
        self.assertEqual(len(self.runs_of(bid)), 3)
        self.cancel_runs(bid)
        page.close()
        errors = [e for e in errors if "Failed to load resource" not in e and "ERR_FAILED" not in e]
        self.assertFalse(errors, errors[:5])
        S.record("D2.browser", {"lost_then_retried": "same run", "lost_then_reloaded": "recovered and shown", "new_generate": "new run"})

    # ---- found by the adversarial review of the fixes
    def lose_answer(self, route):
        route.fetch()
        route.abort("failed")

    def test_an_error_that_is_not_an_answer_keeps_the_submission_identity(self):
        bid, _ = self.fresh_batch("proxy error after a lost answer")
        page, errors = self.compose(bid)
        submit_re = re.compile(r".*/api/batches/[^/]+/submit$")
        page.route(submit_re, self.lose_answer)
        self.generate_button(page).click()
        page.wait_for_selector("text=could not be confirmed", timeout=30000)
        page.unroute(submit_re)
        page.route(submit_re, lambda route: route.fulfill(status=429, content_type="text/plain", body="Too many requests"))
        self.generate_button(page).click()  # a proxy answers, not the server: says nothing about the first attempt
        page.wait_for_timeout(1500)
        self.assertTrue(page.evaluate(f"localStorage.getItem('dna.submit.{bid}')"), "the identity is kept")
        page.unroute(submit_re)
        page.route(submit_re, lambda route: route.fulfill(status=200, content_type="text/html", body="<html>Sign in to the network</html>"))
        self.generate_button(page).click()  # a captive portal's page is not the server's answer either
        page.wait_for_selector("text=could not be confirmed", timeout=15000)
        self.assertIn("/generate", page.url)
        self.assertTrue(page.evaluate(f"localStorage.getItem('dna.submit.{bid}')"), "still kept")
        page.unroute(submit_re)
        self.generate_button(page).click()
        page.wait_for_url("**/runs/*", timeout=30000)
        self.assertEqual(len(self.runs_of(bid)), 1)
        self.cancel_runs(bid)
        page.close()
        S.record("D2.proxy_error", {"runs": 1})

    def test_a_second_tab_retries_the_same_submission(self):
        bid, _ = self.fresh_batch("two tabs")
        ctx = self.browser.new_context(viewport={"width": 1280, "height": 900})  # two tabs of one browser share its storage
        a, b = ctx.new_page(), ctx.new_page()
        for pg in (a, b):  # both open before the first tab submits
            pg.goto(f"{self.base}/generate?batch={bid}")
            pg.wait_for_selector('textarea[aria-label="headline copy"]')
        submit_re = re.compile(r".*/api/batches/[^/]+/submit$")
        a.route(submit_re, self.lose_answer)
        self.generate_button(a).click()
        a.wait_for_selector("text=could not be confirmed", timeout=30000)
        self.generate_button(b).click()
        b.wait_for_url("**/runs/*", timeout=30000)
        runs = self.runs_of(bid)
        self.assertEqual(len(runs), 1, "the other tab retried the same submission")
        self.assertTrue(b.url.endswith(runs[0]))
        self.cancel_runs(bid)
        ctx.close()
        S.record("D2.second_tab", {"runs": 1})

    def test_a_failed_choice_is_shown_as_it_is_and_never_replayed(self):
        bid, pid = self.fresh_batch("failed choice")
        page, _ = self.compose(bid)
        pair_re = re.compile(r".*/api/batches/[^/]+/pairs/[^/]+$")
        page.route(pair_re, lambda route: route.abort("failed") if route.request.method == "PATCH" and '"mode"' in (route.request.post_data or "") else route.continue_())
        page.select_option('select[aria-label="Mode"]', "creative")
        page.wait_for_timeout(1500)
        self.assertEqual(page.input_value('select[aria-label="Mode"]'), "", "the select shows what the server has")
        page.unroute(pair_re)
        self.generate_button(page).click()
        page.wait_for_url("**/runs/*", timeout=30000)
        o = ok(client.get(f"/api/runs/{self.runs_of(bid)[0]}"))["outputs"][0]
        self.assertEqual(o["mode"], "adapt", "a choice that failed on screen is never sent unseen (creative would be a paid request)")
        self.cancel_runs(bid)
        page.close()
        S.record("D1.failed_choice", {"mode": "adapt"})

    def test_a_lost_variant_answer_is_not_added_again(self):
        bid, _ = self.fresh_batch("lost variant")
        m = ok(client.get(f"/api/batches/{bid}"))  # a variant inherits the batch default, so it is ready to generate
        ok(client.patch(f"/api/batches/{bid}", json={"base_revision": m["batch"]["revision"], "changes": {"defaults": {"copy": {"headline": "Batch\nheadline"}}}}))
        page, _ = self.compose(bid)
        var_re = re.compile(r".*/api/batches/[^/]+/variants$")
        page.route(var_re, self.lose_answer)
        page.get_by_role("button", name="+ Variant").click()
        page.wait_for_selector("text=Not saved", timeout=15000)
        page.unroute(var_re)
        page.wait_for_function("document.querySelectorAll('article.out-card').length === 2", timeout=15000)  # reloaded: it exists
        self.generate_button(page).click()
        page.wait_for_url("**/runs/*", timeout=30000)
        self.assertEqual(len(ok(client.get(f"/api/batches/{bid}"))["pairs"]), 2, "the variant was not added a second time")
        self.assertEqual(len(ok(client.get(f"/api/runs/{self.runs_of(bid)[0]}"))["outputs"]), 2, "exactly the outputs on screen")
        self.cancel_runs(bid)
        page.close()
        S.record("D1.lost_variant", {"pairs": 2})

    def test_use_inherited_value_shows_the_value_that_will_be_used(self):
        bid, pid = self.fresh_batch("inherited")
        cta = next(x for x in ok(client.get(f"/api/batches/{bid}"))["pairs"][0]["slots"] if x["role"] == "cta")
        ok(client.patch(f"/api/batches/{bid}/pairs/{pid}", json={"manual": {cta["slot_id"]: {"value": "Shop now"}}}))  # same as the default
        page, _ = self.compose(bid)
        box = 'textarea[aria-label="cta copy"]'
        page.fill(box, "Shop now today")
        page.locator(".slot-field", has=page.locator(box)).get_by_role("button", name="Use inherited value").click()
        self.saved(page)
        page.wait_for_timeout(500)
        self.assertEqual(self.slot_value(bid, "cta"), "Shop now")
        self.assertEqual(page.input_value(box), "Shop now", "the box shows what will be generated")
        page.close()
        S.record("D1.inherited", {"screen": "Shop now"})

    def test_leaving_with_unsaved_changes_asks_first(self):
        bid, _ = self.fresh_batch("leave unsaved")
        page, _ = self.compose(bid)
        page.get_by_role("link", name="Change selection").click()  # nothing pending: leaves at once
        page.wait_for_url("**/templates", timeout=15000)
        page.go_back()  # history now has an in-app entry ahead of the composer
        page.wait_for_selector('textarea[aria-label="headline copy"]')
        pair_re = re.compile(r".*/api/batches/[^/]+/pairs/[^/]+$")
        page.route(pair_re, lambda route: route.abort("failed") if route.request.method == "PATCH" and "instructions" in (route.request.post_data or "") else route.continue_())
        page.get_by_label("Extra instructions for this output").fill("Warm morning light")
        page.locator("h1").click()  # blur: the save is sent and fails
        page.wait_for_selector("text=change(s) not saved", timeout=15000)
        answers = ["dismiss", "dismiss", "accept"]
        page.on("dialog", lambda d: d.dismiss() if answers.pop(0) == "dismiss" else d.accept())
        page.get_by_role("link", name="Change selection").click()
        page.wait_for_timeout(1500)
        self.assertIn("/generate", page.url, "declining keeps the page and its unsaved change")
        page.go_forward()  # the browser's Forward button is held the same way
        page.wait_for_timeout(1500)
        self.assertIn("/generate", page.url)
        self.assertTrue(page.locator("text=change(s) not saved").is_visible(), "still reported, not silently dropped")
        page.get_by_role("link", name="Change selection").click()
        page.wait_for_url("**/templates", timeout=15000)
        self.assertEqual(answers, [])
        page.close()
        S.record("D1.leave_unsaved", {"link": "asked", "forward_button": "asked"})

    def test_a_lost_retry_answer_does_not_make_a_second_revision(self):
        bid, _ = self.fresh_batch("lost retry")
        run = ok(client.post(f"/api/batches/{bid}/submit", json={"idempotency_key": f"lost-retry-{bid}"}))
        o = ok(client.get(f"/api/runs/{run['run_id']}"))["outputs"][0]
        ok(client.post(f"/api/outputs/{o['id']}/cancel"))
        page, _ = self.open(1280)
        page.goto(f"{self.base}/runs/{run['run_id']}")
        page.get_by_role("button", name="Review").click()
        retry_re = re.compile(r".*/api/outputs/[^/]+/retry$")
        page.route(retry_re, self.lose_answer)
        page.get_by_role("button", name="Retry this output").click()
        page.wait_for_timeout(2000)
        page.unroute(retry_re)
        page.get_by_role("button", name="Retry this output").click()
        page.wait_for_selector("text=already received", timeout=15000)
        kids = S.db.all_(S.db.connect(), "SELECT id FROM outputs WHERE parent_output_id = ?", (o["id"],))
        self.assertEqual(len(kids), 1, "one revision for one retry")
        self.cancel_runs(bid)
        page.close()
        S.record("D3.lost_retry", {"revisions": 2})


if __name__ == "__main__":
    unittest.main()
