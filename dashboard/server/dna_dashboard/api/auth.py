"""Workspace authentication. When DNA_AUTH_TOKEN is set, every /api route (except health and login) requires either
`Authorization: Bearer <token>` or the session cookie set by /api/auth/login. Cookie-authenticated writes also need the
X-DNA-Request header (a CSRF guard: other sites cannot set custom headers on cross-site requests)."""
from __future__ import annotations

import hashlib
import hmac

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from .. import config
from ..errors import AppError

router = APIRouter()
COOKIE = "dna_session"
PUBLIC = ("/api/health", "/api/auth/login", "/api/auth/status", "/api/auth/logout")


def session_value(token: str) -> str:
    return hmac.new(token.encode(), b"design-dna-session-v1", hashlib.sha256).hexdigest()


def check(request: Request) -> None:
    token = config.get().auth_token
    path = request.url.path
    if not token or not path.startswith("/api") or path in PUBLIC:
        return
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer ") and hmac.compare_digest(auth[7:].strip(), token):
        return
    cookie = request.cookies.get(COOKIE)
    if cookie and hmac.compare_digest(cookie, session_value(token)):
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-dna-request") != "1":
            raise AppError("missing request header", "csrf", 403)
        return
    raise AppError("sign in to this workspace first", "unauthorized", 401)


class Login(BaseModel):
    token: str


@router.post("/auth/login")
def login(body: Login, request: Request, response: Response):
    token = config.get().auth_token
    if not token:
        return {"authenticated": True, "required": False}
    if not hmac.compare_digest(body.token.strip(), token):
        raise AppError("that access token is not correct", "unauthorized", 401)
    response.set_cookie(COOKIE, session_value(token), httponly=True, samesite="strict", secure=request.url.scheme == "https",
                        max_age=60 * 60 * 24 * 30, path="/")
    return {"authenticated": True, "required": True}


@router.post("/auth/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"authenticated": False}


@router.get("/auth/status")
def status(request: Request):
    token = config.get().auth_token
    if not token:
        return {"required": False, "authenticated": True}
    auth = request.headers.get("authorization", "")
    ok = (auth.lower().startswith("bearer ") and hmac.compare_digest(auth[7:].strip(), token)) or \
        hmac.compare_digest(request.cookies.get(COOKIE) or "", session_value(token))
    return {"required": True, "authenticated": bool(ok)}
