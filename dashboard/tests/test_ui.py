"""T28 the built web app in a real browser: every page at 390 px and 1280 px without horizontal scrolling or script
errors, every visible control has an accessible name, and the main journeys work from the keyboard.

Needs the built frontend (cd dashboard/web && npm ci && npm run build) and Playwright's Chromium. Without a build the
test is skipped, unless DNA_REQUIRE_UI_TEST=1 (CI), where a missing build is a failure.
"""
from __future__ import annotations

import os
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


@unittest.skipUnless(REQUIRE or (DIST / "index.html").exists(), "the web app is not built (npm run build in dashboard/web)")
class T28Browser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import uvicorn

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
        port = _free_port()
        cls.base = f"http://127.0.0.1:{port}"
        cls.server = uvicorn.Server(uvicorn.Config(S.create_app(), host="127.0.0.1", port=port, log_level="warning"))
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

    def pages(self):
        i = self.ids
        return ["/templates", "/templates/new", f"/templates/new?id={i['template']}", f"/templates/{i['template']}", f"/templates/{i['copy']}",
                f"/templates/{i['copy']}/edit", "/generate", f"/generate?batch={i['batch']}", "/runs", f"/runs/{i['run']}", "/settings"]

    def open(self, width):
        page = self.browser.new_page(viewport={"width": width, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error" else None)
        return page, errors

    def settle(self, page):
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(300)

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


if __name__ == "__main__":
    unittest.main()
