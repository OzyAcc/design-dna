"""Installer and package tests (operating-system level; no AI host is involved).

  python -m unittest discover -s hosts/tests -v

Every test runs against a throwaway home folder (DESIGN_DNA_INSTALL_HOME), so nothing outside it is touched.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hosts"))
import hostkit as hk  # noqa: E402


def cli(*args, home: Path, check=True) -> subprocess.CompletedProcess:
    env = dict(os.environ, DESIGN_DNA_INSTALL_HOME=str(home), PYTHONUTF8="1")
    r = subprocess.run([sys.executable, str(ROOT / "install.py"), *args], capture_output=True, text=True, env=env,
                       stdin=subprocess.DEVNULL, timeout=600)
    if check and r.returncode != 0:
        raise AssertionError(f"install.py {' '.join(args)} -> {r.returncode}\n{r.stdout}\n{r.stderr}")
    return r


class Registry(unittest.TestCase):
    def test_registry_is_complete(self):
        reg = hk.load_registry()
        ids = [h["id"] for h in reg["hosts"]]
        self.assertEqual(ids[0], "chatgpt", "ChatGPT comes first")
        for want in ("codex", "claude-code", "claude-apps", "cursor", "copilot", "gemini-cli", "windsurf", "cline",
                     "roo-code", "opencode", "instructions"):
            self.assertIn(want, ids)
        for h in reg["hosts"]:
            self.assertTrue(h["prerequisites"], h["id"])
            for s in h["surfaces"]:
                self.assertIn(s["kind"], ("skill-dir", "upload", "plugin", "instructions"), h["id"])
                if s["kind"] in ("upload", "instructions"):
                    self.assertIn(s["package"], hk.package_kinds(), h["id"])
            if any(s["kind"] == "skill-dir" for s in h["surfaces"]):
                self.assertTrue({"user", "project"} <= set(h["skill_dirs"]), h["id"])
                self.assertIn(h["skill_dirs"]["user"], h["reads"]["user"], f"{h['id']}: installs where it reads")
            for d in h["docs"]:
                self.assertIn(d["method"], reg["doc_methods"])
                self.assertTrue(d["url"].startswith("https://"))
            for st, t in h["testing"].items():
                self.assertIn(t["status"], reg["test_status"], f"{h['id']}.{st}")
                if t["status"] in ("verified", "partial"):
                    self.assertTrue(t.get("evidence"), f"{h['id']}.{st} needs evidence")

    def test_canonical_skill_meets_the_agent_skills_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = hk.load_registry()
            dest = Path(tmp) / hk.skill_name()
            hk.render_skill(hk.host(reg, "agents"), hk.surface_for(hk.host(reg, "agents")), dest)
            self.assertEqual(hk.validate_skill(dest), [])
            self.assertFalse((dest / "tests").exists(), "the acceptance suite stays in the repository")

    def test_generated_docs_are_current(self):
        r = cli("docs", "--check", home=Path(tempfile.gettempdir()), check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class SkillFolders(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="dna-home-"))

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_every_skill_folder_target_installs_where_its_host_reads(self):
        reg = hk.load_registry()
        for h in reg["hosts"]:
            if not any(s["kind"] == "skill-dir" for s in h["surfaces"]):
                continue
            with self.subTest(target=h["id"]):
                cli("install", "--target", h["id"], "--no-deps", home=self.home)
                dest = self.home / h["skill_dirs"]["user"][2:] / hk.skill_name()
                self.assertTrue((dest / "SKILL.md").is_file())
                self.assertTrue((dest / "scripts" / "dna.py").is_file())
                stamp = json.loads((dest / hk.STAMP).read_text(encoding="utf-8"))
                self.assertEqual((stamp["product"], stamp["host"]), (hk.PRODUCT, h["id"]))
                self.assertEqual(hk.validate_skill(dest), [])
                self.assertEqual((dest / "agents" / "openai.yaml").exists(), h.get("overlay") == "openai")

    def test_dry_run_writes_nothing(self):
        r = cli("install", "--target", "cursor,cline", "--dry-run", home=self.home)
        self.assertIn("create", r.stdout)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_project_scope(self):
        proj = self.home / "repo"
        proj.mkdir()
        cli("install", "--target", "copilot", "--scope", "project", "--project", str(proj), "--no-deps", home=self.home)
        self.assertTrue((proj / ".github" / "skills" / hk.skill_name() / "SKILL.md").is_file())

    def test_update_refreshes_unmodified_copies_and_protects_edited_ones(self):
        cli("install", "--target", "windsurf", "--no-deps", home=self.home)
        dest = self.home / ".codeium" / "windsurf" / "skills" / hk.skill_name()
        r = cli("update", "--no-deps", home=self.home)
        self.assertIn("replace", r.stdout)
        with open(dest / "SKILL.md", "a", encoding="utf-8") as f:
            f.write("\nlocal note\n")
        r = cli("update", "--target", "windsurf", "--no-deps", home=self.home, check=False)
        self.assertEqual(r.returncode, 2)
        self.assertIn("local changes", r.stderr)
        self.assertIn("local note", (dest / "SKILL.md").read_text(encoding="utf-8"))
        cli("update", "--target", "windsurf", "--no-deps", "--force", home=self.home)
        backups = list((self.home / "design-dna" / "backups").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertIn("local note", (backups[0] / "SKILL.md").read_text(encoding="utf-8"))
        self.assertNotIn("local note", (dest / "SKILL.md").read_text(encoding="utf-8"))

    def test_foreign_folders_are_never_overwritten_or_removed(self):
        dest = self.home / ".roo" / "skills" / hk.skill_name()
        dest.mkdir(parents=True)
        (dest / "mine.txt").write_text("keep", encoding="utf-8")
        self.assertEqual(cli("install", "--target", "roo-code", "--no-deps", home=self.home, check=False).returncode, 2)
        self.assertEqual(cli("uninstall", "--target", "roo-code", home=self.home, check=False).returncode, 2)
        self.assertEqual((dest / "mine.txt").read_text(encoding="utf-8"), "keep")
        cli("install", "--target", "roo-code", "--no-deps", "--force", home=self.home)
        backups = list((self.home / "design-dna" / "backups").iterdir())
        self.assertEqual((backups[0] / "mine.txt").read_text(encoding="utf-8"), "keep")

    def test_uninstall_removes_only_its_own_copy_and_keeps_templates(self):
        cli("install", "--target", "kiro,junie", "--no-deps", home=self.home)
        templates = self.home / "design-dna" / "templates" / "t1"
        templates.mkdir(parents=True)
        (templates / "passport.json").write_text("{}", encoding="utf-8")
        cli("uninstall", "--target", "kiro", "--dry-run", home=self.home)
        self.assertTrue((self.home / ".kiro" / "skills" / hk.skill_name()).exists())
        cli("uninstall", "--target", "kiro", home=self.home)
        self.assertFalse((self.home / ".kiro" / "skills" / hk.skill_name()).exists())
        self.assertTrue((self.home / ".junie" / "skills" / hk.skill_name()).exists())
        self.assertTrue((templates / "passport.json").exists())

    def test_doctor_reports_copies_and_duplicates(self):
        cli("install", "--target", "cursor,claude-code", "--no-deps", home=self.home)
        r = cli("doctor", "--target", "cursor", "--no-browser", "--json", home=self.home, check=False)
        d = json.loads(r.stdout)
        cursor = next(h for h in d["hosts"] if h["id"] == "cursor")
        self.assertEqual(len(cursor["visible_installs"]), 2)
        self.assertTrue(any("copies" in w for w in d["warnings"]))

    def test_legacy_wrapper_default_is_claude_code(self):
        if os.name == "nt" or not shutil.which("bash"):
            self.skipTest("bash wrapper")
        legacy = self.home / ".claude" / "skills" / hk.skill_name()
        legacy.mkdir(parents=True)
        (legacy / "SKILL.md").write_text("old install.sh copy", encoding="utf-8")
        env = dict(os.environ, DESIGN_DNA_INSTALL_HOME=str(self.home))
        r = subprocess.run(["bash", str(ROOT / "install.sh"), "--no-deps"], capture_output=True, text=True, env=env, timeout=600)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((legacy / hk.STAMP).exists())
        self.assertEqual(len(list((self.home / "design-dna" / "backups").iterdir())), 1)


class Packages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp(prefix="dna-pkg-"))
        cli("package", "--target", "all", "--out", str(cls.out), home=cls.out)
        cls.manifest = json.loads((cls.out / "packages.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def unzip(self, name) -> Path:
        d = self.out / ("x-" + name)
        if not d.exists():
            with zipfile.ZipFile(self.out / name) as z:
                z.extractall(d)
        return d

    def test_every_package_is_built_and_listed(self):
        self.assertEqual(set(self.manifest["packages"]), set(hk.package_kinds()))
        sums = (self.out / "SHA256SUMS").read_text(encoding="utf-8")
        for v in self.manifest["packages"].values():
            self.assertEqual(hk.sha256_file(self.out / v["file"]), v["sha256"])
            self.assertIn(v["file"], sums)
            self.assertLess(v["bytes"], 50 * 1024 * 1024)
            self.assertLess(v["files"], 500)

    def test_upload_zips_hold_one_valid_skill_folder(self):
        for pkg in ("chatgpt-skill", "claude-skill", "skill"):
            with self.subTest(pkg=pkg):
                v = self.manifest["packages"][pkg]
                self.assertEqual(v["top"], [hk.skill_name()])
                d = self.unzip(v["file"]) / hk.skill_name()
                self.assertEqual(hk.validate_skill(d), [])
        chatgpt = self.unzip(self.manifest["packages"]["chatgpt-skill"]["file"]) / hk.skill_name()
        self.assertIn("Running in a hosted sandbox", (chatgpt / "SKILL.md").read_text(encoding="utf-8"))
        self.assertTrue((chatgpt / "agents" / "openai.yaml").exists())
        generic = self.unzip(self.manifest["packages"]["skill"]["file"]) / hk.skill_name()
        self.assertNotIn("Running in a hosted sandbox", (generic / "SKILL.md").read_text(encoding="utf-8"))

    def test_plugin_and_extension_manifests(self):
        codex = self.unzip(self.manifest["packages"]["codex-plugin"]["file"]) / "design-dna-codex-plugin"
        market = json.loads((codex / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8"))
        path = market["plugins"][0]["source"]["path"]
        self.assertTrue(path.startswith("./") and path != "./")
        plugin = codex / path
        self.assertEqual(json.loads((plugin / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))["skills"], "./skills/")
        self.assertEqual(hk.validate_skill(plugin / "skills" / hk.skill_name()), [])
        agent = self.unzip(self.manifest["packages"]["agent-plugin"]["file"]) / "design-dna-agent-plugin"
        manifest = json.loads((agent / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["$schema"], "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json")
        self.assertFalse({"skills", "agents", "hooks"} & set(manifest), "Agent Plugins 1.0 has no component path fields")
        gem = self.unzip(self.manifest["packages"]["gemini-extension"]["file"]) / "design-dna-gemini-extension"
        self.assertEqual(json.loads((gem / "gemini-extension.json").read_text(encoding="utf-8"))["name"], "design-dna")
        self.assertEqual(hk.validate_skill(gem / "skills" / hk.skill_name()), [])

    def test_instruction_kit_is_labelled_and_fits(self):
        kit = self.unzip(self.manifest["packages"]["instructions-kit"]["file"]) / "design-dna-instructions-kit"
        text = (kit / "INSTRUCTIONS.md").read_text(encoding="utf-8")
        self.assertLessEqual(len(text), hk.INSTRUCTIONS_LIMIT)
        self.assertIn("Instruction-only mode", text)
        self.assertIn("Never use `measured`", text)
        self.assertTrue((kit / "knowledge" / "design-dna-skill.md").exists())


if __name__ == "__main__":
    unittest.main()
