"""Client side of the engine adapter: run engine operations and measurement tools in isolated subprocesses.

Every call names its store explicitly (DESIGN_DNA_HOME = a template workspace or a job's private store). The web and
worker processes never change their own environment, so concurrent jobs cannot share engine state. Commands are fixed
argument arrays; user text only ever travels as JSON on stdin or as a single argv element, never through a shell.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from . import config
from .errors import AppError

RUNNER = Path(__file__).resolve().with_name("engine_runner.py")
MARK = "@@DNA_RESULT@@"
TOOLS = {"measure.py", "sample_colors.py", "font_candidates.py", "fit_text.py", "annotate_scan.py", "validate_model.py",
         "render_static.py", "capabilities.py"}


class EngineError(AppError):
    """The engine refused or reported a conflict (a design outcome, not an infrastructure failure)."""

    def __init__(self, err: dict):
        super().__init__(err.get("message", "engine error"), err.get("code", "engine_error"), 409, err.get("detail") or {})
        self.engine = err


class EngineCrash(AppError):
    """The engine process failed (infrastructure): missing browser, crash, timeout."""

    def __init__(self, message, detail=None):
        super().__init__(message, "engine_failure", 500, detail or {})


class Cancelled(Exception):
    pass


def _env(home: Path) -> dict:
    s = config.get()
    env = dict(os.environ)
    env.update(DESIGN_DNA_HOME=str(home), DNA_ENGINE_DIR=str(s.engine_dir), PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               DNA_PARENT_PID=str(os.getpid()))
    env.pop("PYTHONPATH", None)
    return env


def _run(argv, home: Path, stdin: str, timeout: float, cancel=None, cwd=None):
    home.mkdir(parents=True, exist_ok=True)
    p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         env=_env(home), cwd=str(cwd or home), encoding="utf-8")
    start, pending = time.monotonic(), stdin
    while True:  # communicate() drains both pipes; short timeouts let cancellation and the deadline interrupt it
        try:
            out, err = p.communicate(pending, timeout=0.5)
            return p.returncode, out, err
        except subprocess.TimeoutExpired:
            pending = None
        if cancel and cancel():
            p.kill()
            p.communicate()
            raise Cancelled()
        if time.monotonic() - start > timeout:
            p.kill()
            p.communicate()
            raise EngineCrash(f"engine step exceeded {int(timeout)} s and was stopped", {"argv": argv[1:3]})


def call(op: str, request: dict, home: Path, timeout: float = 900, cancel=None) -> dict:
    """Run one engine operation via engine_runner.py; returns its result or raises EngineError/EngineCrash."""
    s = config.get()
    code, out, err = _run([s.python, str(RUNNER), op], Path(home), json.dumps(request, ensure_ascii=False, default=str), timeout, cancel)
    line = next((x for x in reversed(out.splitlines()) if x.startswith(MARK)), None)
    if line is None:
        raise EngineCrash(f"engine operation {op} produced no result (exit {code})", {"stderr": err[-2000:], "stdout": out[-1000:]})
    res = json.loads(line[len(MARK):])
    if res.get("ok"):
        return res["result"]
    if res.get("engine_error"):
        raise EngineError(res["engine_error"])
    c = res.get("crash", {})
    raise EngineCrash(f"engine operation {op} failed: {c.get('type')}: {c.get('message', '')[:300]}", c)


def tool(script: str, args: list[str], home: Path, timeout: float = 600, cancel=None) -> dict | str:
    """Run a measurement/validation script with a fixed argument array. JSON stdout is parsed when present."""
    if script not in TOOLS:
        raise ValueError(f"not an allowed engine tool: {script}")
    s = config.get()
    argv = [s.python, str(s.engine_dir / script), *[str(a) for a in args]]
    code, out, err = _run(argv, Path(home), "", timeout, cancel)
    if code != 0:
        try:
            parsed = json.loads(out[out.index("{"):]) if "{" in out else None
        except ValueError:
            parsed = None
        if isinstance(parsed, dict) and parsed.get("status") == "error":
            raise EngineError(parsed)
        raise EngineCrash(f"{script} failed (exit {code})", {"stderr": err[-2000:], "stdout": out[-1500:]})
    if "{" in out:
        try:
            return json.loads(out[out.index("{"):])
        except ValueError:
            pass
    return out


def engine_dir(home: Path, engine_id: str) -> Path:
    return Path(home) / "templates" / engine_id


_CAPS = {"at": 0, "value": None}


def capabilities(force=False) -> dict:
    """The engine's own capability report (cached for 10 minutes); runs in an empty scratch store."""
    if force or not _CAPS["value"] or time.time() - _CAPS["at"] > 600:
        home = config.get().jobs / "_capabilities"
        try:
            _CAPS["value"] = call("capabilities", {}, home, timeout=240)
        except AppError as e:
            _CAPS["value"] = {"error": e.message, "detail": e.detail}
        _CAPS["at"] = time.time()
    return _CAPS["value"]


def python_info() -> dict:
    return {"python": sys.version.split()[0], "executable": config.get().python, "engine_dir": str(config.get().engine_dir)}
