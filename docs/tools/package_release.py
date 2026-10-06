"""Build the release ZIP: the repository files + sample template bundles + real acceptance evidence.

  python docs/tools/package_release.py <acceptance-run-dir> [--version 2.0.0] [--out dist]

Contents:
  design-dna-<version>/                 every file git would commit (tracked + untracked, minus ignored/excluded)
  design-dna-<version>/samples/templates/*.dnab   bundles exported from the run's store (fonts by reference, no font binaries)
  design-dna-<version>/samples/acceptance/        report.md/json + selected per-test evidence folders
The build refuses if the acceptance report has a failure, or if a term from DNA_BLOCKED_TERMS appears in any text file.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_TEMPLATES = ("editorial-product-spotlight", "editorial-measured", "product-grid-six-up")
EVIDENCE = ("t01-synthetic-measured", "t02-unfamiliar-flattened", "t04-headline-only", "t08-arabic-mixed",
            "t15-keep-everything-else", "t16-explicit-lock-conflict", "t18-token-isolation", "t19-image-replacement",
            "t20-bundle-roundtrip", "t21-renderer-drift", "t22-svg-export")
MAX_FILE = 4_000_000
# Comma-separated private terms (client or project names) that must never ship; kept out of the source on purpose.
BLOCKED_TERMS = [t.strip().lower() for t in os.environ.get("DNA_BLOCKED_TERMS", "").split(",") if t.strip()]
TEXT = {".md", ".py", ".json", ".txt", ".yml", ".yaml", ".ps1", ".sh", ".svg", ".html", ".css"}


def repo_entries(ref: str | None) -> list[tuple[str, bytes]]:
    """(path, bytes) for every published file: a commit/tag (`--ref`, reproducible) or the working tree."""
    if ref:
        names = subprocess.run(["git", "ls-tree", "-r", "--name-only", ref], cwd=ROOT, capture_output=True, text=True,
                               check=True).stdout.splitlines()
        return [(n, subprocess.run(["git", "show", f"{ref}:{n}"], cwd=ROOT, capture_output=True, check=True).stdout)
                for n in names if n]
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.splitlines()
    return [(f, (ROOT / f).read_bytes()) for f in out if f and not f.startswith("dist/") and (ROOT / f).is_file()]


def find_store(run: Path, tid: str) -> Path:
    """The run's template store (T20 moves the original store aside to prove portability)."""
    for name in ("store", "store-removed", "store-fresh"):
        if (run / name / "templates" / tid / "passport.json").exists():
            return run / name
    raise SystemExit(f"template {tid} not found in any store of {run}")


def scan_terms(name: str, data: bytes) -> None:
    if Path(name).suffix.lower() not in TEXT:
        return
    low = data.decode("utf-8", "ignore").lower()
    hits = [t for t in BLOCKED_TERMS if t and t in low]
    if hits:
        raise SystemExit(f"refusing to package {name}: contains {hits}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run")
    ap.add_argument("--version", default="2.0.0")
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--ref", help="package this git commit/tag instead of the working tree (reproducible releases)")
    a = ap.parse_args()
    run = Path(a.run)
    rep = json.loads((run / "report.json").read_text(encoding="utf-8"))
    failed = [r["id"] for r in rep["results"] if r["status"] not in ("pass", "unverified")]
    if failed:
        raise SystemExit(f"acceptance run {rep['run']} has failures {failed}; not packaging")
    top = f"design-dna-{a.version}"
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    zpath = out / f"{top}.zip"
    if zpath.exists():
        raise SystemExit(f"{zpath} exists; refusing to overwrite")

    stage = run / "_release_bundles"
    stage.mkdir(exist_ok=True)
    bundles = []
    for tid in SAMPLE_TEMPLATES:
        env = dict(os.environ, DESIGN_DNA_HOME=str(find_store(run, tid)))
        r = subprocess.run([sys.executable, str(ROOT / "skills/reverse-design/scripts/bundle.py"), "export", tid,
                            "--to", str(stage), "--fonts", "reference"], env=env, capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"bundle export failed for {tid}: {r.stdout}{r.stderr}")
        bundles.append(Path(json.loads(r.stdout)["bundle"]))

    n = 0
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        def put(arc: str, data: bytes):
            nonlocal n
            scan_terms(arc, data)
            info = zipfile.ZipInfo(f"{top}/{arc}", (2026, 1, 1, 0, 0, 0))
            info.compress_type, info.external_attr = zipfile.ZIP_DEFLATED, 0o644 << 16
            z.writestr(info, data)
            n += 1

        add = lambda src, arc: put(arc, Path(src).read_bytes())
        for name, data in repo_entries(a.ref):
            put(name, data)
        for b in bundles:
            add(b, f"samples/templates/{b.name}")
        for f in ("report.md", "report.json"):
            add(run / f, f"samples/acceptance/{f}")
        for d in EVIDENCE:
            for f in sorted((run / d).rglob("*")):
                if f.is_file() and f.stat().st_size <= MAX_FILE:
                    add(f, f"samples/acceptance/{d}/{f.relative_to(run / d).as_posix()}")
        for tid in ("product-grid-six-up", "editorial-measured"):
            ev = find_store(run, tid) / "templates" / tid / "evidence"
            for f in ("annotated.png", "scan_report.md", "evidence.json"):
                if (ev / f).exists():
                    add(ev / f, f"samples/scans/{tid}/{f}")
        put("samples/README.md", SAMPLES_README.format(run=rep["run"], passed=rep["passed"], total=rep["total"],
                                                       unverified=rep["unverified"]).encode())
    print(json.dumps({"zip": str(zpath), "files": n, "bytes": zpath.stat().st_size, "run": rep["run"]}, indent=2))
    return 0


SAMPLES_README = """# Samples

Everything here comes from acceptance run `{run}`: **{passed}/{total} passed, {unverified} entry unverified by design**.
All artwork is synthetic (generated fixtures); no third-party or client material.

| Folder | Contents |
|---|---|
| `templates/` | Template bundles (`.dnab`) exported from the run's store with `fonts=reference`: no font binaries. Import with `python skills/reverse-design/scripts/bundle.py import <file>`; the fonts resolve by sha256 from your font folders, or pass `--font-dir` (a Windows run used Windows system fonts; a portable run used `skills/reverse-design/tests/fonts`, see `acceptance/report.json` → `setup.fonts`). Validation tells you which font is missing if one does not resolve. |
| `acceptance/report.md` | The actual acceptance report, grouped by kind. `report.json` has every assertion. |
| `acceptance/t01-…` | Measured rebuild: comparison panel (`compare/`: side-by-side, overlay, heatmap, region crops, `report.json`) and `scores.json` against hidden ground truth |
| `acceptance/t02-…` | Unfamiliar flattened JPEG: annotated scan and the honest partial result |
| `acceptance/t04-…`, `t15-…`, `t18-…`, `t19-…` | Verified edits: before/after renders, transactions with model-change and visual-change reports |
| `acceptance/t16-…` | Lock conflicts and pixel locks |
| `acceptance/t20-…`, `t21-…`, `t22-…` | Bundle round-trip, renderer drift + migration, SVG export with manifest and round-trip result |
| `scans/<template>/` | Scan outputs: annotated reference, `scan_report.md` (16 categories + facets + unresolved), evidence records |
"""


if __name__ == "__main__":
    sys.exit(main())
