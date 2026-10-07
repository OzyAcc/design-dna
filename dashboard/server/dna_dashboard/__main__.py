"""Command line: python -m dna_dashboard <serve | worker | all | migrate | check>

  serve    the web app + API (uvicorn) on DNA_HOST:DNA_PORT (default 127.0.0.1:8765)
  worker   the job worker (separate process; run one or more)
  all      both: the worker as a child process, the web app in this one (local convenience)
  migrate  create/upgrade the database schema and exit
  check    print the runtime report (engine capabilities, renderer, providers, data directory) and exit
"""
from __future__ import annotations

import json
import subprocess
import sys


def _guard_bind(s):
    if not s.is_loopback() and not s.auth_token:
        sys.exit(f"refusing to listen on {s.host} without DNA_AUTH_TOKEN: a non-local address needs workspace authentication")


def serve():
    import uvicorn

    from . import config
    from .app import create_app

    s = config.get()
    _guard_bind(s)
    print(f"Design DNA dashboard on http://{s.host}:{s.port}  (data: {s.data_dir})", flush=True)
    uvicorn.run(create_app(), host=s.host, port=s.port, log_level="info")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "all"
    from . import config, db

    if cmd == "migrate":
        conn = db.connect()
        print(f"applied {db.migrate(conn)} migration(s) -> {config.get().db_path}")
        return 0
    if cmd == "worker":
        from .worker import main as worker_main

        return worker_main(once="--once" in argv)
    if cmd == "serve":
        serve()
        return 0
    if cmd == "all":
        conn = db.connect()
        db.migrate(conn)
        conn.close()
        w = subprocess.Popen([sys.executable, "-m", "dna_dashboard", "worker"])
        try:
            serve()
        finally:
            w.terminate()
            w.wait(timeout=60)
        return 0
    if cmd == "check":
        from . import engine
        from .providers import all_providers, cached_health

        s = config.get()
        print(json.dumps({"data_dir": str(s.data_dir), "engine": engine.capabilities(force=True), "python": engine.python_info(),
                          "providers": [dict(p.describe(), health=cached_health(p, force=True)) for p in all_providers()]},
                         indent=2, default=str))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
