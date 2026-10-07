"""Design DNA host kit: the host registry, host packages and the installer (Python standard library only).

One canonical skill (skills/reverse-design) and one engine. Everything host-specific is generated here from
hosts/registry/*.json and the small overlays in hosts/overlays/: skill folders for hosts that read SKILL.md from
disk, upload zips for hosted surfaces, plugin/extension folders for host package managers, and an
instruction-only kit for assistants that cannot run code.

Installed copies carry a stamp (.design-dna-install.json) listing every file's sha256. Update and uninstall touch a
folder only when the stamp says Design DNA put it there and its files are unchanged; anything else needs --force
and is moved to a backup folder first, never deleted.
"""
from __future__ import annotations

import datetime as _dt
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_DIR = ROOT / "hosts" / "registry"
OVERLAYS = ROOT / "hosts" / "overlays"
PRODUCT = "design-dna"
STAMP = ".design-dna-install.json"
ZIP_TIME = (2026, 1, 1, 0, 0, 0)
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class HostError(Exception):
    """A refusal with a reason the user can act on."""


# ------------------------------------------------------------------ registry
def load_registry() -> dict:
    reg = json.loads((REGISTRY_DIR / "_common.json").read_text(encoding="utf-8"))
    hosts = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(REGISTRY_DIR.glob("*.json")) if p.name != "_common.json"]
    reg["hosts"] = sorted(hosts, key=lambda h: h["order"])
    ids = [h["id"] for h in reg["hosts"]] + [a for h in reg["hosts"] for a in h.get("aliases", [])]
    if len(ids) != len(set(ids)):
        raise HostError(f"duplicate host id or alias in {REGISTRY_DIR}")
    for h in reg["hosts"]:
        for s in h["surfaces"]:
            if s["capability"] not in reg["capability_classes"]:
                raise HostError(f"{h['id']}/{s['id']}: unknown capability {s['capability']!r}")
        missing = [st for st in reg["test_stages"] if st not in h["testing"]]
        if missing:
            raise HostError(f"{h['id']}: testing lacks {missing}")
    return reg


def host(reg, hid) -> dict:
    for h in reg["hosts"]:
        if hid == h["id"] or hid in h.get("aliases", []):
            return h
    raise HostError(f"unknown target {hid!r}; known: {', '.join(h['id'] for h in reg['hosts'])}")


def version() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def commit() -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10)
        dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"], capture_output=True, text=True, timeout=10).stdout.strip()
        return (r.stdout.strip() + ("-dirty" if dirty else "")) if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


# ------------------------------------------------------------------ paths
def home() -> Path:
    """The user's home; DESIGN_DNA_INSTALL_HOME redirects every host path (used by the installer tests)."""
    return Path(os.environ.get("DESIGN_DNA_INSTALL_HOME") or Path.home())


def store() -> Path:
    if os.environ.get("DESIGN_DNA_INSTALL_HOME"):
        return home() / "design-dna"
    return Path(os.environ.get("DESIGN_DNA_HOME") or Path.home() / "design-dna")


def expand(p: str) -> Path:
    return home() / p[2:] if p.startswith("~/") else Path(p)


def skill_dir(h, scope="user", project=None) -> Path:
    if "skill_dirs" not in h:
        raise HostError(f"{h['id']} has no skill folder; it installs by {', '.join(sorted({s['kind'] for s in h['surfaces']}))}")
    if scope == "project":
        if not project:
            raise HostError("--scope project needs --project <folder>")
        return Path(project).resolve() / h["skill_dirs"]["project"] / skill_name()
    return expand(h["skill_dirs"]["user"]) / skill_name()


def skill_name() -> str:
    return load_registry()["skill"]["name"]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------ the canonical skill, rendered for a host
def skill_source(reg=None) -> Path:
    reg = reg or load_registry()
    return ROOT / reg["skill"]["source"]


def source_files(reg=None) -> list[tuple[str, Path]]:
    reg = reg or load_registry()
    src = skill_source(reg)
    out = []
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src).as_posix()
        parts = rel.split("/")
        if p.is_dir() or any(fnmatch.fnmatch(part, pat) for part in parts for pat in reg["skill"]["exclude"]):
            continue
        out.append((rel, p))
    return out


def frontmatter(text: str) -> tuple[dict, str]:
    """The SKILL.md frontmatter as {key: str | dict} (the flat subset the Agent Skills spec uses) and the body."""
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)$", text, re.S)
    if not m:
        raise HostError("SKILL.md has no YAML frontmatter")
    meta, cur = {}, None
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")) and cur:
            k, _, v = line.strip().partition(":")
            meta[cur][k.strip()] = v.strip().strip('"\'')
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if v == "":
            meta[k], cur = {}, k
        else:
            meta[k], cur = (v[1:-1] if len(v) > 1 and v[0] == v[-1] and v[0] in "\"'" else v), None
    return meta, m.group(2)


def host_notes(h, surface) -> str:
    """Environment notes appended to SKILL.md for surfaces whose runtime differs from a local agent."""
    f = OVERLAYS / "notes" / f"{surface['capability']}.md"
    return f.read_text(encoding="utf-8").strip() if f.exists() else ""


def render_skill(h, surface, dest: Path) -> list[str]:
    """Write the skill for one host surface into dest (which must not exist). Returns the relative file list."""
    reg = load_registry()
    dest.mkdir(parents=True)
    written = []
    for rel, p in source_files(reg):
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if rel == "SKILL.md":
            text = p.read_text(encoding="utf-8")
            notes = host_notes(h, surface)
            if notes:
                text = text.rstrip() + "\n\n" + notes + "\n"
            out.write_text(text, encoding="utf-8", newline="\n")
        else:
            shutil.copy2(p, out)
        written.append(rel)
    for rel in overlay_files(h):
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(fill(OVERLAYS / h["overlay"] / rel), encoding="utf-8", newline="\n")
        written.append(rel)
    return sorted(written)


def overlay_files(h) -> list[str]:
    if not h.get("overlay"):
        return []
    base = OVERLAYS / h["overlay"]
    return sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file())


def fill(template: Path) -> str:
    meta, _ = frontmatter((skill_source() / "SKILL.md").read_text(encoding="utf-8"))
    return (template.read_text(encoding="utf-8").replace("{{VERSION}}", version()).replace("{{SKILL}}", meta["name"])
            .replace("{{DESCRIPTION}}", json.dumps(meta["description"])[1:-1]))


def validate_skill(folder: Path) -> list[str]:
    """The Agent Skills rules this package must meet in every host (spec: agentskills.io/specification)."""
    errors = []
    sk = folder / "SKILL.md"
    if not sk.exists():
        return [f"{folder}: no SKILL.md"]
    try:
        meta, body = frontmatter(sk.read_text(encoding="utf-8"))
    except HostError as e:
        return [str(e)]
    name, desc = meta.get("name", ""), meta.get("description", "")
    if not isinstance(name, str) or not (1 <= len(name) <= 64) or not NAME_RE.match(name):
        errors.append(f"name {name!r}: 1-64 lowercase letters, digits and single hyphens")
    if name != folder.name:
        errors.append(f"name {name!r} must match its folder {folder.name!r}")
    if not isinstance(desc, str) or not (1 <= len(desc) <= 1024):
        errors.append(f"description must be 1-1024 characters (has {len(desc) if isinstance(desc, str) else 'none'})")
    if "compatibility" in meta and not (1 <= len(meta["compatibility"]) <= 500):
        errors.append("compatibility must be 1-500 characters")
    if "metadata" in meta and not isinstance(meta["metadata"], dict):
        errors.append("metadata must be a mapping")
    if not body.strip():
        errors.append("SKILL.md has no instructions")
    for p in folder.rglob("*"):
        if p.suffix == ".pyc" or p.name == "__pycache__":
            errors.append(f"build residue in package: {p.relative_to(folder)}")
    return errors


# ------------------------------------------------------------------ stamps
def stamp_write(dest: Path, h, surface, files):
    data = {"product": PRODUCT, "skill": dest.name, "version": version(), "commit": commit(), "host": h["id"],
            "surface": surface["id"], "installed_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "source": str(ROOT), "files": {rel: sha256_file(dest / rel) for rel in files}}
    (dest / STAMP).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def stamp_read(dest: Path) -> dict | None:
    try:
        d = json.loads((dest / STAMP).read_text(encoding="utf-8"))
        return d if d.get("product") == PRODUCT else None
    except (OSError, ValueError):
        return None


def local_changes(dest: Path, st: dict) -> list[str]:
    """Files edited, removed or added since the stamped install (caches ignored)."""
    changed = [rel for rel, h in st["files"].items() if not (dest / rel).is_file() or sha256_file(dest / rel) != h]
    for p in dest.rglob("*"):
        rel = p.relative_to(dest).as_posix()
        if p.is_file() and rel != STAMP and rel not in st["files"] and "__pycache__" not in rel and not rel.endswith(".pyc"):
            changed.append(rel + " (added)")
    return sorted(changed)


def backup(dest: Path, label: str, dry_run: bool) -> Path:
    b = store() / "backups" / f"{label}-{dest.name}-{_dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    if not dry_run:
        b.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dest), str(b))
    return b


# ------------------------------------------------------------------ skill-folder install / update / uninstall
def install_skill_dir(h, surface, dest: Path, dry_run=False, force=False) -> dict:
    actions = []
    if dest.exists():
        st = stamp_read(dest)
        if st:
            changes = local_changes(dest, st)
            if changes and not force:
                raise HostError(f"{dest} has local changes ({', '.join(changes[:5])}{' …' if len(changes) > 5 else ''}); "
                                "re-run with --force to move it to a backup and reinstall")
            if changes:
                actions.append(f"backup modified copy -> {backup(dest, h['id'], True)}")
            actions.append(f"replace {dest} (installed {st.get('version')} @ {st.get('commit')})")
        else:
            if not force:
                raise HostError(f"{dest} exists and was not installed by Design DNA; re-run with --force to move it to a backup")
            actions.append(f"backup foreign folder -> {backup(dest, h['id'], True)}")
    else:
        actions.append(f"create {dest}")
    if dry_run:
        return {"host": h["id"], "surface": surface["id"], "dest": str(dest), "dry_run": True, "actions": actions}
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".dna-", dir=dest.parent)) / dest.name
    files = render_skill(h, surface, tmp)
    errors = validate_skill(tmp)
    if errors:
        shutil.rmtree(tmp.parent, ignore_errors=True)
        raise HostError(f"generated skill is invalid: {errors}")
    stamp_write(tmp, h, surface, files)
    moved = None
    if dest.exists():
        st = stamp_read(dest)
        if st and not local_changes(dest, st):
            old = dest.with_name(dest.name + ".old-" + _dt.datetime.now().strftime("%H%M%S%f"))
            os.replace(dest, old)
            shutil.rmtree(old, ignore_errors=True)
        else:
            moved = backup(dest, h["id"], False)
    os.replace(tmp, dest)
    shutil.rmtree(tmp.parent, ignore_errors=True)
    return {"host": h["id"], "surface": surface["id"], "dest": str(dest), "files": len(files), "version": version(),
            "backup": str(moved) if moved else None, "actions": actions}


def uninstall_skill_dir(h, dest: Path, dry_run=False, force=False) -> dict:
    if not dest.exists():
        return {"host": h["id"], "dest": str(dest), "actions": ["nothing installed here"]}
    st = stamp_read(dest)
    if not st:
        if not force:
            raise HostError(f"{dest} was not installed by Design DNA; refusing to remove it (--force moves it to a backup)")
        return {"host": h["id"], "dest": str(dest), "actions": [f"backup foreign folder -> {backup(dest, h['id'], dry_run)}"]}
    changes = local_changes(dest, st)
    if changes and not force:
        raise HostError(f"{dest} has local changes ({', '.join(changes[:5])}); --force moves it to a backup instead")
    if changes:
        return {"host": h["id"], "dest": str(dest), "actions": [f"backup modified copy -> {backup(dest, h['id'], dry_run)}"]}
    if not dry_run:
        shutil.rmtree(dest)
    return {"host": h["id"], "dest": str(dest), "actions": [f"remove {dest}"], "dry_run": dry_run}


# ------------------------------------------------------------------ packages
def package_kinds() -> dict:
    """package id -> (file name, builder, host id used for rendering)."""
    return {
        "chatgpt-skill": ("design-dna-chatgpt-skill.zip", build_skill_zip, "chatgpt"),
        "claude-skill": ("design-dna-claude-skill.zip", build_skill_zip, "claude-apps"),
        "skill": ("design-dna-skill.zip", build_skill_zip, "agents"),
        "codex-plugin": ("design-dna-codex-plugin.zip", build_tree_zip, "codex"),
        "agent-plugin": ("design-dna-agent-plugin.zip", build_tree_zip, "copilot"),
        "gemini-extension": ("design-dna-gemini-extension.zip", build_tree_zip, "gemini-cli"),
        "instructions-kit": ("design-dna-instructions-kit.zip", build_tree_zip, "instructions"),
    }


def surface_for(h, package=None) -> dict:
    for s in h["surfaces"]:
        if package and s.get("package") == package:
            return s
    return next((s for s in h["surfaces"] if s.get("default")), h["surfaces"][0])


def zip_dir(folder: Path, zpath: Path, top: str):
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                info = zipfile.ZipInfo(f"{top}/{p.relative_to(folder).as_posix()}", ZIP_TIME)
                info.compress_type, info.external_attr = zipfile.ZIP_DEFLATED, 0o644 << 16
                z.writestr(info, p.read_bytes())


def build_skill_zip(pkg, out: Path, work: Path) -> Path:
    reg = load_registry()
    fname, _, hid = package_kinds()[pkg]
    h = host(reg, hid)
    folder = work / skill_name()
    render_skill(h, surface_for(h, pkg), folder)
    errors = validate_skill(folder)
    if errors:
        raise HostError(f"{pkg}: {errors}")
    zip_dir(folder, out / fname, skill_name())
    return out / fname


def build_tree(pkg, dest: Path) -> Path:
    """Build an unzipped plugin, extension or kit at dest. Returns the folder to hand to the host (or to zip)."""
    reg = load_registry()
    h = host(reg, package_kinds()[pkg][2] if pkg in package_kinds() else {"copilot-marketplace": "copilot"}[pkg])
    s = surface_for(h, "agent-plugin" if pkg == "copilot-marketplace" else pkg)
    if pkg == "codex-plugin":
        plugin = dest / "plugins" / PRODUCT
        render_skill(h, s, plugin / "skills" / skill_name())
        (plugin / ".codex-plugin").mkdir(parents=True)
        (plugin / ".codex-plugin" / "plugin.json").write_text(fill(OVERLAYS / "packages" / "codex-plugin.json"), encoding="utf-8")
        (dest / ".agents" / "plugins").mkdir(parents=True)
        (dest / ".agents" / "plugins" / "marketplace.json").write_text(fill(OVERLAYS / "packages" / "codex-marketplace.json"), encoding="utf-8")
        return dest
    if pkg == "agent-plugin":
        render_skill(h, s, dest / "skills" / skill_name())
        (dest / "plugin.json").write_text(fill(OVERLAYS / "packages" / "agent-plugin.json"), encoding="utf-8")
        return dest
    if pkg == "copilot-marketplace":  # the agent plugin inside a local marketplace (installer only)
        build_tree("agent-plugin", dest / "plugins" / PRODUCT)
        (dest / ".github" / "plugin").mkdir(parents=True)
        (dest / ".github" / "plugin" / "marketplace.json").write_text(fill(OVERLAYS / "packages" / "copilot-marketplace.json"), encoding="utf-8")
        return dest
    if pkg == "gemini-extension":
        render_skill(h, s, dest / "skills" / skill_name())
        (dest / "gemini-extension.json").write_text(fill(OVERLAYS / "packages" / "gemini-extension.json"), encoding="utf-8")
        return dest
    if pkg == "instructions-kit":
        return build_instructions_kit(dest)
    raise HostError(f"no tree builder for {pkg}")


def build_tree_zip(pkg, out: Path, work: Path) -> Path:
    fname = package_kinds()[pkg][0]
    tree = build_tree(pkg, work / pkg)
    for sk in tree.rglob("SKILL.md"):
        errors = validate_skill(sk.parent)
        if errors:
            raise HostError(f"{pkg}: {errors}")
    zip_dir(tree, out / fname, fname[:-4])
    return out / fname


INSTRUCTIONS_LIMIT = 8000


def build_instructions_kit(dest: Path) -> Path:
    src = skill_source()
    kit = OVERLAYS / "instructions"
    dest.mkdir(parents=True)
    text = (kit / "INSTRUCTIONS.md").read_text(encoding="utf-8").replace("{{VERSION}}", version())
    if len(text) > INSTRUCTIONS_LIMIT:
        raise HostError(f"INSTRUCTIONS.md is {len(text)} characters; custom GPT instructions hold {INSTRUCTIONS_LIMIT}")
    (dest / "INSTRUCTIONS.md").write_text(text, encoding="utf-8", newline="\n")
    (dest / "README.md").write_text((kit / "README.md").read_text(encoding="utf-8").replace("{{VERSION}}", version()), encoding="utf-8", newline="\n")
    know = dest / "knowledge"
    know.mkdir()
    shutil.copy2(src / "SKILL.md", know / "design-dna-skill.md")
    for p in sorted((src / "references").glob("*.md")):
        shutil.copy2(p, know / f"design-dna-{p.name}")
    for p in sorted((src / "schemas").glob("*.json")):
        shutil.copy2(p, know / f"design-dna-{p.name}")
    return dest


def build_packages(ids, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    built = {}
    with tempfile.TemporaryDirectory() as tmp:
        for pkg in ids:
            fname, builder, _ = package_kinds()[pkg]
            if (out / fname).exists():
                (out / fname).unlink()
            work = Path(tmp) / pkg
            work.mkdir()
            p = builder(pkg, out, work)
            with zipfile.ZipFile(p) as z:
                names = z.namelist()
            built[pkg] = {"file": p.name, "bytes": p.stat().st_size, "sha256": sha256_file(p), "files": len(names),
                          "top": sorted({n.split("/")[0] for n in names})}
    manifest = {"product": PRODUCT, "version": version(), "commit": commit(), "packages": built}
    (out / "packages.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (out / "SHA256SUMS").write_text("".join(f"{v['sha256']}  {v['file']}\n" for v in built.values()), encoding="utf-8")
    return manifest


# ------------------------------------------------------------------ host package managers
def which(cmd) -> str | None:
    return shutil.which(cmd)


def run(cmd, dry_run, env=None, interactive=False) -> dict:
    """Run a command. Interactive runs share the terminal so the host CLI can ask its own questions."""
    if dry_run:
        return {"cmd": cmd, "dry_run": True}
    full_env = dict(os.environ, **(env or {}))
    if interactive:
        return {"cmd": cmd, "code": subprocess.run(cmd, env=full_env).returncode, "out": "(interactive)"}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL, env=full_env)
    except subprocess.TimeoutExpired:
        return {"cmd": cmd, "code": 124, "out": "timed out: the command is probably waiting for an answer; run it in a terminal"}
    return {"cmd": cmd, "code": r.returncode, "out": (r.stdout + r.stderr).strip()[-2000:]}


def install_plugin(h, method, dry_run=False, assume_yes=False) -> dict:
    """Codex plugin, Copilot plugin, Gemini extension or Claude Code plugin through the host's own CLI."""
    hid = h["id"]
    if hid == "claude-code":
        cmds = [["claude", "plugin", "marketplace", "add", str(ROOT)], ["claude", "plugin", "install", f"{PRODUCT}@{PRODUCT}"]]
        return host_cli(h, "claude", cmds, dry_run, None, assume_yes=assume_yes)
    pkg = {"codex": "codex-plugin", "copilot": "copilot-marketplace", "gemini-cli": "gemini-extension"}.get(hid)
    if not pkg:
        raise HostError(f"{hid} has no plugin or extension method; use the skill folder")
    folder = store() / "hosts" / {"codex-plugin": "codex-marketplace", "copilot-marketplace": "copilot-marketplace",
                                  "gemini-extension": "gemini-extension/design-dna"}[pkg]
    actions = [f"build {pkg} at {folder}"]
    if not dry_run:
        if folder.exists():
            shutil.rmtree(folder)
        folder.parent.mkdir(parents=True, exist_ok=True)
        build_tree(pkg, folder)
    if hid == "codex":
        cmds = [["codex", "plugin", "marketplace", "add", str(folder)], ["codex", "plugin", "add", f"{PRODUCT}@{PRODUCT}-local"]]
        return host_cli(h, "codex", cmds, dry_run, actions, assume_yes=assume_yes)
    if hid == "copilot":
        cmds = [["copilot", "plugin", "marketplace", "add", str(folder)], ["copilot", "plugin", "install", f"{PRODUCT}@{PRODUCT}-local"]]
        return host_cli(h, "copilot", cmds, dry_run, actions, assume_yes=assume_yes)
    # Gemini CLI asks whether to trust a local extension folder, separately from --consent. In a terminal the user
    # answers it; unattended runs need --yes, which trusts only this command's run (GEMINI_CLI_TRUST_WORKSPACE).
    return host_cli(h, "gemini", [["gemini", "extensions", "install", str(folder), "--consent"]], dry_run, actions,
                    env={"GEMINI_CLI_TRUST_WORKSPACE": "true"} if assume_yes else None, prompts=not assume_yes, assume_yes=assume_yes)


def uninstall_plugin(h, dry_run=False) -> dict:
    cmds = {"claude-code": ("claude", [["claude", "plugin", "uninstall", f"{PRODUCT}@{PRODUCT}"]]),
            "codex": ("codex", [["codex", "plugin", "remove", f"{PRODUCT}@{PRODUCT}-local"], ["codex", "plugin", "marketplace", "remove", f"{PRODUCT}-local"]]),
            "copilot": ("copilot", [["copilot", "plugin", "uninstall", PRODUCT], ["copilot", "plugin", "marketplace", "remove", f"{PRODUCT}-local"]]),
            "gemini-cli": ("gemini", [["gemini", "extensions", "uninstall", PRODUCT]])}.get(h["id"])
    if not cmds:
        raise HostError(f"{h['id']} has no plugin or extension method")
    res = host_cli(h, cmds[0], cmds[1], dry_run, None)
    built = store() / "hosts" / {"codex": "codex-marketplace", "copilot": "copilot-marketplace", "gemini-cli": "gemini-extension"}.get(h["id"], "-")
    if res.get("status") in ("ok", "dry_run") and built.exists():
        res["actions"].append(f"remove the folder it was built in: {built}")
        if not dry_run:
            shutil.rmtree(built)
    return res


def host_cli(h, exe, cmds, dry_run, actions, env=None, prompts=False, assume_yes=False) -> dict:
    """prompts: the host CLI asks a question this installer must not answer on the user's behalf without --yes."""
    res = {"host": h["id"], "method": "plugin", "actions": list(actions or []), "commands": [" ".join(c) for c in cmds]}
    if not which(exe):
        res["status"] = "manual"
        res["note"] = f"{exe} is not on PATH: run the commands above yourself once it is installed"
        return res
    interactive = sys.stdin.isatty() and not assume_yes
    if prompts and not interactive and not dry_run:
        res["status"] = "manual"
        res["note"] = f"{exe} asks a confirmation question here: run the commands above in a terminal, or re-run with --yes"
        return res
    res["results"] = []
    for c in cmds:
        r = run(c, dry_run, env, interactive)
        res["results"].append(r)
        if r.get("code") not in (None, 0):
            break
    res["status"] = "dry_run" if dry_run else ("ok" if all(r.get("code") == 0 for r in res["results"]) else "failed")
    return res


# ------------------------------------------------------------------ diagnosis
def requirement_names() -> list[str]:
    names = []
    for line in (ROOT / load_registry()["skill"]["python_requirements"]).read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line and not line.startswith("-"):
            names.append(re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0])
    return names


def python_check() -> dict:
    from importlib.metadata import PackageNotFoundError, version as pv

    pkgs = {}
    for n in requirement_names():
        try:
            pkgs[n] = pv(n)
        except PackageNotFoundError:
            pkgs[n] = None
    return {"python": sys.version.split()[0], "python_ok": sys.version_info >= (3, 10), "packages": pkgs,
            "missing": [k for k, v in pkgs.items() if v is None]}


def renderer_check() -> str:
    try:
        r = subprocess.run([sys.executable, str(skill_source() / "scripts" / "capabilities.py")], capture_output=True, text=True, timeout=180)
        return json.loads(r.stdout).get("renderer") or "unavailable"
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return f"unavailable: {e.__class__.__name__}"


def installs_visible_to(h, project=None) -> list[dict]:
    seen = []
    dirs = [expand(d) for d in h.get("reads", {}).get("user", [])]
    if project:
        dirs += [Path(project).resolve() / d for d in h.get("reads", {}).get("project", [])]
    for d in dirs:
        dest = d / skill_name()
        if dest.exists():
            st = stamp_read(dest)
            seen.append({"path": str(dest), "design_dna": bool(st), "version": st and st.get("version"),
                         "commit": st and st.get("commit"), "installed_for": st and st.get("host"),
                         "local_changes": local_changes(dest, st) if st else None})
    return seen


def detect(h) -> dict:
    d = h.get("detect", {})
    return {"paths": [p for p in d.get("paths", []) if expand(p).exists()], "commands": [c for c in d.get("commands", []) if which(c)]}


def doctor(targets, project=None, browser=True) -> dict:
    reg = load_registry()
    py = python_check()
    st = store()
    try:
        st.mkdir(parents=True, exist_ok=True)
        probe = st / ".write-test"
        probe.write_text("ok")
        probe.unlink()
        store_ok = True
    except OSError:
        store_ok = False
    errors, warnings, hosts = [], [], []
    if not py["python_ok"]:
        errors.append(f"Python {py['python']} is older than 3.10")
    if py["missing"]:
        errors.append(f"missing Python packages: {', '.join(py['missing'])} (python -m pip install -r requirements.txt)")
    rend = renderer_check() if browser and not py["missing"] else "not checked"
    if browser and str(rend).startswith("unavailable"):
        warnings.append("no Chromium could be launched: rendering, font fitting and verified edits will not work "
                        "(install Chrome or run: python -m playwright install chromium)")
    if not store_ok:
        errors.append(f"template store {st} is not writable")
    src_ver, src_commit = version(), commit()
    for h in reg["hosts"]:
        if targets and h["id"] not in targets:
            continue
        vis = installs_visible_to(h, project)
        det = detect(h)
        if not targets and not vis and not det["paths"] and not det["commands"]:
            continue
        ours = [v for v in vis if v["design_dna"]]
        if len(vis) > 1:
            warnings.append(f"{h['id']}: {len(vis)} copies of {skill_name()} are visible ({', '.join(v['path'] for v in vis)}); "
                            "the host picks one by its precedence rules: keep one")
        for v in ours:
            if v["local_changes"]:
                errors.append(f"{h['id']}: {v['path']} has local changes: {', '.join(v['local_changes'][:5])}")
            elif v["version"] != src_ver:
                warnings.append(f"{h['id']}: {v['path']} is version {v['version']}; this checkout is {src_ver} (python install.py update)")
        for v in vis:
            if not v["design_dna"]:
                warnings.append(f"{h['id']}: {v['path']} was not installed by this installer (no stamp)")
        hosts.append({"id": h["id"], "name": h["name"], "detected": det, "visible_installs": vis})
    return {"ok": not errors, "errors": errors, "warnings": warnings, "source": {"version": src_ver, "commit": src_commit, "path": str(ROOT)},
            "python": py, "renderer": rend, "store": {"path": str(st), "writable": store_ok}, "hosts": hosts}


def pip_install(dry_run) -> dict:
    cmd = [sys.executable, "-m", "pip", "install", "-r", str(ROOT / load_registry()["skill"]["python_requirements"])]
    return run(cmd, dry_run)
