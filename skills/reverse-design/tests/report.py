"""Acceptance report writer: report.json + report.md (pass / fail / unverified kept separate)."""
import json

from common import write_json


KIND = {1: "reconstruction", 2: "honest partial result", 3: "identity guard", 4: "preservation", 5: "preservation", 6: "preservation",
        7: "expected rejection", 8: "adaptation", 9: "reflow", 10: "determinism", 11: "persistence", 12: "expected rejection",
        13: "expected rejection", 14: "expected rejection", 15: "preservation", 16: "expected rejection", 17: "expected rejection",
        18: "preservation", 19: "preservation", 20: "portability", 21: "renderer integrity", 22: "export integrity",
        23: "unverified integration"}
INPUTS = {1: "flattened PNG + the supplied original product photo, vector logo and candidate font files",
          2: "flattened JPEG drawn by another rasterizer; the operator reads the captions and the 3x2 grid shape"}


def write_report(ROOT, RUN, RESULTS, setup_info):
    passed = sum(r["status"] == "pass" for r in RESULTS)
    unverified = [r for r in RESULTS if r["status"] == "unverified"]
    rep = {"run": RUN, "root": str(ROOT), "passed": passed, "total": len(RESULTS) - len(unverified), "unverified": len(unverified),
           "setup": setup_info, "results": RESULTS}
    write_json(ROOT / "report.json", rep)
    L = [f"# Design DNA acceptance run {RUN}", "",
         f"**{passed}/{len(RESULTS) - len(unverified)} demonstrations passed; {len(unverified)} capability marked UNVERIFIED.** "
         f"Store: `{ROOT / 'store'}`", "",
         "| # | Demonstration | Result |", "|---|---|---|"]
    L[-2:] = ["| # | Demonstration | Kind | Result |", "|---|---|---|---|"]
    L += [f"| {r['id']} | {r['title']} | {KIND.get(r['id'], 'audit regression')} | {r['status'].upper()} |" for r in sorted(RESULTS, key=lambda r: r["id"])]
    kinds = {}
    for r in RESULTS:
        kinds.setdefault(KIND.get(r["id"], "audit regression"), []).append(r["status"])
    L += ["", "Results by kind (a pass is not an exact recovery unless its kind says reconstruction):", ""]
    L += [f"- **{k}**: {v.count('pass')}/{len(v)} pass" + (f", {v.count('unverified')} unverified" if 'unverified' in v else "") for k, v in sorted(kinds.items())]
    for r in sorted(RESULTS, key=lambda r: r["id"]):
        L += ["", f"## T{r['id']:02d} — {r['title']} ({r['status']})", ""]
        L += [f"- {'✅' if v is True else '❌'} {k}" + ("" if v is True else f" → `{json.dumps(v, default=str)[:300]}`") for k, v in r["checks"].items()]
        if r["status"] == "unverified":
            L.append("- ⚪ UNVERIFIED — not exercised in this environment (see note)")
        if r["id"] in INPUTS:
            L.append(f"- inputs: {INPUTS[r['id']]}")
        if r["notes"]:
            L.append(f"- note: {r['notes']}")
        L += [f"- artifact: `{a}`" for a in r["artifacts"]]
    (ROOT / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"\n{passed}/{len(RESULTS) - len(unverified)} passed, {len(unverified)} unverified -> {ROOT / 'report.md'}")
