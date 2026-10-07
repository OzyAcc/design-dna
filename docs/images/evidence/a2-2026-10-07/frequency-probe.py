"""A2 frequency probe: N fresh-process renders of an approved baseline scene, idle vs under CPU load.

    python frequency-probe.py <DESIGN_DNA_HOME> <template id> <N> <out dir>
"""
import json, multiprocessing, os, subprocess, sys, time
from pathlib import Path
import numpy as np
from PIL import Image
HOME = Path(sys.argv[1]); TID = sys.argv[2]; N = int(sys.argv[3]); OUT = Path(sys.argv[4])
ENGINE = Path(__file__).resolve().parents[4] / "skills" / "reverse-design" / "scripts"
tdir = HOME / "templates" / TID
ab = np.asarray(Image.open(tdir / "baseline/rev-0000/baseline.png").convert("RGBA")).astype(int)
env = dict(os.environ, DESIGN_DNA_HOME=str(HOME))
def burn(stop):
    while not stop.is_set():
        sum(i * i for i in range(20000))
res = {}
for mode in ("idle", "loaded"):
    stop = multiprocessing.Event(); procs = []
    if mode == "loaded":
        procs = [multiprocessing.Process(target=burn, args=(stop,)) for _ in range(os.cpu_count() * 2)]
        for p in procs: p.start()
    rows = []
    for i in range(N):
        od = OUT / f"{mode}-{i:02d}"
        t = time.time()
        r = subprocess.run([sys.executable, str(ENGINE / "render_static.py"), TID, "--scene", str(tdir / "scene.json"), "--out", str(od),
                            "--formats", "png", "--name", "render"], capture_output=True, text=True, env=env)
        png = od / "render.png"
        if not png.exists():
            rows.append({"run": i, "error": (r.stdout + r.stderr)[-300:]}); continue
        d = np.abs(np.asarray(Image.open(png).convert("RGBA")).astype(int) - ab).max(axis=2)
        ys, xs = np.nonzero(d)
        rows.append({"run": i, "unequal_px": int((d > 0).sum()), "max_err": int(d.max()), "seconds": round(time.time() - t, 1),
                     "where": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())] if len(xs) else None})
        print(mode, rows[-1], flush=True)
    stop.set()
    for p in procs: p.join()
    res[mode] = rows
(OUT / "results.json").write_text(json.dumps(res, indent=1))
for mode, rows in res.items():
    bad = [r for r in rows if r.get("unequal_px")]
    print(f"{mode}: {len(bad)}/{len(rows)} renders differ from the approved baseline", [(r["run"], r["unequal_px"], r["where"]) for r in bad])
