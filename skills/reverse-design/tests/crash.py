"""One line for a crashed demonstration: the exception, plus why the engine refused when it says so.

A rejected transaction carries its conflicts and verification in DnaError.detail; the console line names the
failing checks so a CI log explains a crash without the evidence download.
"""
from __future__ import annotations

import json


def _failing(x, path, out):
    if isinstance(x, dict):
        if x.get("status") == "fail" and path:
            out.append(f"{path} " + json.dumps({k: v for k, v in x.items() if not isinstance(v, (dict, list))}, default=str)[:240])
        for k, v in x.items():
            _failing(v, f"{path}.{k}" if path else k, out)
    elif isinstance(x, list):
        for i, v in enumerate(x):
            _failing(v, f"{path}[{i}]", out)


def reason(e: BaseException, limit: int = 2000) -> str:
    line = f"{e.__class__.__name__}: {e}"
    detail = getattr(e, "detail", None)
    if not isinstance(detail, dict):
        return line
    parts = [f"code={getattr(e, 'code', None)}"]
    conflicts = [c for c in detail.get("conflicts") or [] if not (isinstance(c, dict) and c.get("verification") == "failed")]
    if conflicts:
        parts.append("conflicts=" + json.dumps(conflicts, default=str, ensure_ascii=False)[:600])
    failing = []
    _failing(detail.get("verification") or {}, "verification", failing)
    if failing:
        parts.append("failed: " + "; ".join(failing))
    return (line + " | " + " | ".join(parts))[:limit]
