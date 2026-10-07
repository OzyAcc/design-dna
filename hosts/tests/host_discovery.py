"""Host discovery checks: install Design DNA for a host into a throwaway home, then ask the host's own CLI what it
sees. No model is called and no account is needed; a CLI that is not on PATH is reported as `untested`.

  python hosts/tests/host_discovery.py [--hosts codex,gemini-cli,copilot,opencode,claude-code] [--out evidence.json]

Checks (each one installs with install.py, then reads the host's answer):
  codex        skill folder: `codex debug prompt-input` lists reverse-design (the model-visible skill list)
  codex        plugin: `codex plugin list` shows design-dna@design-dna-local installed; prompt-input lists it
  gemini-cli   skill folder: `gemini skills list`;  extension: `gemini extensions install` + `gemini skills list`
  copilot      skill folder: `copilot skill list`;  plugin: local marketplace + `copilot plugin list`
  opencode     skill folder: `opencode debug skill`
  claude-code  plugin route: `claude plugin validate` on the repository manifest (skill-folder discovery needs a
               signed-in session: see EVIDENCE.md)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = "reverse-design"


def sh(cmd, home: Path, cwd: Path, env=None, timeout=180) -> dict:
    e = dict(os.environ, HOME=str(home), USERPROFILE=str(home), DESIGN_DNA_INSTALL_HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
             CODEX_HOME=str(home / ".codex"), **(env or {}))
    try:
        r = subprocess.run(cmd, cwd=cwd, env=e, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        return {"cmd": " ".join(map(str, cmd)), "code": r.returncode, "out": (r.stdout + r.stderr)}
    except subprocess.TimeoutExpired:
        return {"cmd": " ".join(map(str, cmd)), "code": 124, "out": "timeout"}


def install(home, *args) -> dict:
    return sh([sys.executable, str(ROOT / "install.py"), "install", "--no-deps", *args], home, ROOT, timeout=600)


def check(name, steps, ok, detail) -> dict:
    return {"check": name, "status": "verified" if ok else "failed", "detail": detail,
            "steps": [{"cmd": s["cmd"], "code": s["code"], "out_tail": s["out"][-600:]} for s in steps]}


def version_of(exe) -> str:
    try:
        return subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60).stdout.strip().splitlines()[0]
    except (OSError, IndexError, subprocess.SubprocessError):
        return "?"


def codex(tmp: Path) -> list[dict]:
    out = []
    home = tmp / "codex"
    (home / ".codex").mkdir(parents=True)
    work = home / "work"
    work.mkdir()
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    s1 = install(home, "--target", "codex")
    s2 = sh(["codex", "debug", "prompt-input", "hello"], home, work)
    out.append(check("codex skill folder: listed in the model-visible prompt", [s1, s2],
                     s1["code"] == 0 and s2["code"] == 0 and f"- {SKILL}:" in s2["out"], f"~/.agents/skills/{SKILL}"))
    home = tmp / "codex-plugin"
    (home / ".codex").mkdir(parents=True)
    work = home / "work"
    work.mkdir()
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    s1 = install(home, "--target", "codex", "--method", "plugin")
    s2 = sh(["codex", "plugin", "list"], home, work)
    s3 = sh(["codex", "debug", "prompt-input", "hello"], home, work)
    out.append(check("codex plugin: installed from the local marketplace and listed in the prompt", [s1, s2, s3],
                     "design-dna@design-dna-local" in s2["out"] and "installed" in s2["out"] and f"design-dna:{SKILL}" in s3["out"],
                     "codex plugin marketplace add + codex plugin add design-dna@design-dna-local"))
    return out


def gemini(tmp: Path) -> list[dict]:
    out = []
    home = tmp / "gemini"
    home.mkdir()
    s1 = install(home, "--target", "gemini-cli")
    s2 = sh(["gemini", "skills", "list"], home, home)
    out.append(check("gemini-cli skill folder: gemini skills list", [s1, s2],
                     f"{SKILL} [Enabled]" in s2["out"] and ".gemini/skills" in s2["out"].replace("\\", "/"), f"~/.gemini/skills/{SKILL}"))
    home = tmp / "gemini-ext"
    home.mkdir()
    s0 = sh(["gemini", "extensions", "validate", "--help"], home, home)
    s1 = install(home, "--target", "gemini-cli", "--method", "extension", "--yes")
    s2 = sh(["gemini", "skills", "list"], home, home)
    s3 = sh([sys.executable, str(ROOT / "install.py"), "uninstall", "--target", "gemini-cli", "--method", "extension"], home, ROOT)
    s4 = sh(["gemini", "extensions", "list"], home, home)
    out.append(check("gemini-cli extension: installed, skill listed from the extension, uninstalled", [s0, s1, s2, s3, s4],
                     "installed successfully" in s1["out"] and f"extensions/design-dna/skills/{SKILL}" in s2["out"].replace("\\", "/")
                     and "No extensions installed" in s4["out"], "gemini extensions install <built folder> --consent (trust via --yes)"))
    return out


def copilot(tmp: Path) -> list[dict]:
    out = []
    home = tmp / "copilot"
    (home / "work").mkdir(parents=True)
    s1 = install(home, "--target", "copilot")
    s2 = sh(["copilot", "skill", "list"], home, home / "work")
    out.append(check("copilot skill folder: copilot skill list (Personal skills)", [s1, s2],
                     "Personal skills" in s2["out"] and SKILL in s2["out"], f"~/.copilot/skills/{SKILL}"))
    home = tmp / "copilot-plugin"
    (home / "work").mkdir(parents=True)
    s1 = install(home, "--target", "copilot", "--method", "plugin")
    s2 = sh(["copilot", "plugin", "list"], home, home / "work")
    s3 = sh(["copilot", "skill", "list"], home, home / "work")
    s4 = sh([sys.executable, str(ROOT / "install.py"), "uninstall", "--target", "copilot", "--method", "plugin"], home, ROOT)
    s5 = sh(["copilot", "plugin", "list"], home, home / "work")
    out.append(check("copilot plugin: local marketplace install, skill listed, uninstalled", [s1, s2, s3, s4, s5],
                     "design-dna@design-dna-local" in s2["out"] and SKILL in s3["out"] and "No plugins installed" in s5["out"],
                     "copilot plugin marketplace add + copilot plugin install design-dna@design-dna-local (Agent Plugins 1.0)"))
    return out


def opencode(tmp: Path) -> list[dict]:
    home = tmp / "opencode"
    work = home / "work"
    work.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    s1 = install(home, "--target", "opencode")
    s2 = sh(["opencode", "debug", "skill"], home, work)
    found = False
    try:
        data = json.loads(s2["out"][s2["out"].find("["):])
        found = any(x.get("name") == SKILL and ".config/opencode/skills" in x.get("location", "").replace("\\", "/") for x in data)
    except ValueError:
        pass
    return [check("opencode skill folder: opencode debug skill", [s1, s2], found, f"~/.config/opencode/skills/{SKILL}")]


def claude_code(tmp: Path) -> list[dict]:
    s = sh(["claude", "plugin", "validate", str(ROOT)], Path.home(), ROOT)
    return [check("claude-code plugin: claude plugin validate on the repository", [s], s["code"] == 0, ".claude-plugin/plugin.json + marketplace.json")]


HOSTS = {"codex": ("codex", codex), "gemini-cli": ("gemini", gemini), "copilot": ("copilot", copilot),
         "opencode": ("opencode", opencode), "claude-code": ("claude", claude_code)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hosts", default=",".join(HOSTS))
    ap.add_argument("--out")
    a = ap.parse_args()
    results = {}
    with tempfile.TemporaryDirectory(prefix="dna-hosts-") as tmp:
        for hid in a.hosts.split(","):
            exe, fn = HOSTS[hid]
            if not shutil.which(exe):
                results[hid] = {"cli": None, "checks": [{"check": f"{hid}: {exe} not on PATH", "status": "untested"}]}
                continue
            results[hid] = {"cli": version_of(exe), "checks": fn(Path(tmp))}
    for hid, r in results.items():
        for c in r["checks"]:
            print(f"[{c['status'].upper():8}] {hid:12} {c['check']}  ({r['cli']})")
    if a.out:
        Path(a.out).write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    return 1 if any(c["status"] == "failed" for r in results.values() for c in r["checks"]) else 0


if __name__ == "__main__":
    sys.exit(main())
