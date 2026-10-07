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
from pathlib import Path

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

    def screenshot(self, page, filename):
        if os.environ.get("DNA_UI_SCREENSHOTS"):
            folder = Path(os.environ["DNA_UI_SCREENSHOTS"])
            folder.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(folder / filename), full_page=True)

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
                if path in ("/templates", "/templates/new"):
                    name = "library" if path == "/templates" else "intake"
                    self.screenshot(page, f"{name}-{width}.png")
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

    def test_library_views_filters_theme_and_selection(self):
        page, errors = self.open(1280)
        page.goto(self.base + "/templates")
        self.settle(page)
        page.get_by_role("button", name="List view", exact=True).click()
        self.assertTrue(page.locator(".cards.list-view").is_visible())
        page.set_viewport_size({"width": 768, "height": 900})
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 768, "list view fits a tablet")
        page.set_viewport_size({"width": 1280, "height": 900})
        page.reload()
        self.settle(page)
        self.assertEqual(page.get_by_role("button", name="List view", exact=True).get_attribute("aria-pressed"), "true")
        page.get_by_role("button", name="Switch to dark theme", exact=True).click()
        self.assertEqual(page.locator("html").get_attribute("data-theme"), "dark")
        self.screenshot(page, "library-dark-1280.png")
        page.reload()
        self.settle(page)
        self.assertEqual(page.locator("html").get_attribute("data-theme"), "dark")
        page.get_by_role("button", name="Switch to light theme", exact=True).click()
        page.get_by_role("button", name="Filters", exact=True).click()
        page.get_by_role("combobox", name="Original or copy", exact=True).select_option("copy")
        self.settle(page)
        self.assertGreater(page.locator(".tcard").count(), 0)
        self.assertTrue(all("Editable copy" in x for x in page.locator(".tcard-specs").all_text_contents()))
        page.get_by_role("button", name="Clear filters", exact=True).click()
        self.settle(page)
        page.locator(".tcard input[type=checkbox]:enabled").first.check()
        dock = page.get_by_role("region", name="Selected templates", exact=True)
        self.assertTrue(dock.is_visible())
        dock.get_by_role("button", name="Create batch", exact=True).click()
        self.assertTrue(page.locator(".composer").evaluate("el => el.open"))
        dock.get_by_role("button", name="Clear", exact=True).click()
        self.assertFalse(dock.is_visible())
        self.assertFalse(errors, errors[:10])
        S.record("T28.library_refresh", {"view_persists": True, "theme_persists": True, "copy_filter": True, "selection_dock": True})
        page.close()

    def test_command_search_navigation_escape_and_focus(self):
        page, errors = self.open(1280)
        page.goto(self.base + "/templates")
        self.settle(page)
        trigger = page.get_by_role("button", name="Search pages and templates", exact=True)
        trigger.click()
        dialog = page.get_by_role("dialog", name="Find your next step", exact=True)
        self.assertTrue(dialog.is_visible())
        page.keyboard.press("Escape")
        self.assertFalse(dialog.is_visible())
        self.assertTrue(trigger.evaluate("el => el === document.activeElement"))
        page.keyboard.press("Control+k")
        self.assertTrue(dialog.is_visible())
        dialog.get_by_role("searchbox", name="Search pages and templates", exact=True).fill("Results")
        page.keyboard.press("Enter")
        page.wait_for_url("**/runs")
        self.settle(page)
        self.assertFalse(dialog.is_visible())
        self.assertFalse(errors, errors[:10])
        S.record("T28.command", {"shortcut": True, "navigation": "/runs", "escape": True, "focus_restored": True})
        page.close()

    def test_product_drawer_traps_focus_and_escape_restores_trigger(self):
        page, errors = self.open(390)
        page.goto(self.base + "/templates")
        self.settle(page)
        page.locator(".composer summary").click()
        trigger = page.get_by_role("button", name="Add product", exact=True)
        trigger.click()
        dialog = page.get_by_role("dialog", name="Add a product", exact=True)
        self.assertTrue(dialog.is_visible())
        dialog.get_by_label("Name", exact=True).fill("Keyboard product input")
        for _ in range(20):
            page.keyboard.press("Tab")
            self.assertTrue(page.evaluate("!!document.activeElement.closest('dialog')"), "focus stays inside the product drawer")
        page.keyboard.press("Escape")
        self.assertFalse(dialog.is_visible())
        self.assertTrue(trigger.evaluate("el => el === document.activeElement"))
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
        self.assertFalse(errors, errors[:10])
        S.record("T28.product_drawer", {"native_modal": True, "focus_contained": True, "escape": True, "focus_restored": True})
        page.close()


if __name__ == "__main__":
    unittest.main()
