"""FastAPI application: /api routes, workspace authentication, and the built React frontend at every other path."""
from __future__ import annotations

import traceback

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from . import __version__, config, db
from .api import assets, auth, batches, products, runs, system, templates
from .errors import AppError

NOT_BUILT = """<!doctype html><meta charset="utf-8"><title>Design DNA</title>
<body style="font:16px/1.5 system-ui;background:#F6F2EA;color:#16130F;padding:48px">
<h1 style="font-family:Georgia,serif">Design DNA dashboard</h1>
<p>The API is running, but the web interface has not been built yet.</p>
<pre>cd dashboard/web &amp;&amp; npm ci &amp;&amp; npm run build</pre></body>"""


def create_app() -> FastAPI:
    s = config.get()
    conn = db.connect()
    try:
        db.migrate(conn)
    finally:
        conn.close()
    app = FastAPI(title="Design DNA dashboard", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        try:
            auth.check(request)
        except AppError as e:
            return JSONResponse(e.as_dict(), status_code=e.status)
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        return resp

    @app.exception_handler(AppError)
    async def app_error(request: Request, e: AppError):
        return JSONResponse(e.as_dict(), status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def bad_request(request: Request, e: RequestValidationError):
        return JSONResponse({"error": {"code": "invalid_request", "message": "the request is missing or has invalid fields",
                                       "detail": {"errors": [{"loc": list(x.get("loc", [])), "msg": x.get("msg")} for x in e.errors()][:20]}}},
                            status_code=422)

    @app.exception_handler(Exception)
    async def crash(request: Request, e: Exception):
        traceback.print_exc()
        return JSONResponse({"error": {"code": "server_error", "message": "something went wrong on the server",
                                       "detail": {"type": type(e).__name__}}}, status_code=500)

    for r in (auth.router, system.router, assets.router, templates.router, products.router, batches.router, runs.router):
        app.include_router(r, prefix="/api")

    dist = s.web_dist

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"error": {"code": "not_found", "message": "unknown API route"}}, status_code=404)
        if not (dist / "index.html").exists():
            return HTMLResponse(NOT_BUILT)
        if path:
            f = (dist / path).resolve()
            if dist.resolve() in f.parents and f.is_file():
                return FileResponse(f, headers={"Cache-Control": "public, max-age=31536000, immutable"} if "/assets/" in f.as_posix() else {})
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

    return app
