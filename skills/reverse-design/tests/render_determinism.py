"""Render one template many times, each in a fresh browser launch, and report every render that differs from
the first: how many pixels and where. Optionally repeat under extra Chromium flags to compare configurations.

  python render_determinism.py <template-dir> [--runs 30] [--config name=--flag1,--flag2 ...]

The template is copied to a scratch folder first (render caches and variants left out); nothing in the store
changes. Renders use pin_policy=migrate so that extra flags do not stop at renderer_drift.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import renderer_env  # noqa: E402
from compare_render import diff_where  # noqa: E402
from render_static import render  # noqa: E402


def run(scene, tdir, work, runs, extra) -> dict:
    base_args = list(renderer_env.BROWSER_ARGS)
    renderer_env.BROWSER_ARGS[:] = base_args + extra
    try:
        t0, first, diffs = time.time(), None, []
        for i in range(runs):
            png = render(scene, tdir, work / f"r{i}", pin_policy="migrate")["png"]
            px = np.asarray(Image.open(png).convert("RGBA"))
            if first is None:
                first = px
                continue
            n = int(np.count_nonzero(np.abs(px.astype(np.int16) - first.astype(np.int16)).max(axis=2)))
            if n:
                diffs.append({"run": i, "unequal_pixels": n, "where": diff_where(first, px, 4)})
        return {"runs": runs, "differing_runs": len(diffs), "diffs": diffs[:6], "seconds": round(time.time() - t0, 1)}
    finally:
        renderer_env.BROWSER_ARGS[:] = base_args


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("template")
    ap.add_argument("--runs", type=int, default=30)
    ap.add_argument("--config", action="append", default=[], help="name=--flag1,--flag2 (repeatable); 'current' always runs")
    a = ap.parse_args()
    configs = [("current", [])] + [(c.split("=", 1)[0], [f for f in c.split("=", 1)[1].split(",") if f]) for c in a.config]
    work = Path(tempfile.mkdtemp(prefix="dna-determinism-"))
    tdir = work / "template"
    shutil.copytree(a.template, tdir, ignore=shutil.ignore_patterns("renders", "variants", "exports"))
    scene = json.loads((tdir / "scene.json").read_text(encoding="utf-8"))
    results = {}
    for name, extra in configs:
        results[name] = r = run(scene, tdir, work / name, a.runs, extra)
        print(f"{name:28} {r['differing_runs']:3}/{r['runs'] - 1} renders differ from the first  ({r['seconds']} s)  {extra}", flush=True)
        for d in r["diffs"]:
            print(f"    run {d['run']}: {d['unequal_pixels']} px  {d['where']}", flush=True)
    print(json.dumps(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
