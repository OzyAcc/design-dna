"""Application errors: a machine-readable code, a plain-language message, details, and an HTTP status."""
from __future__ import annotations


class AppError(Exception):
    def __init__(self, message: str, code: str = "error", status: int = 400, detail: dict | None = None):
        super().__init__(message)
        self.message, self.code, self.status, self.detail = message, code, status, detail or {}

    def as_dict(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "detail": self.detail}}


def not_found(what: str, ident: str) -> AppError:
    return AppError(f"{what} {ident!r} was not found", "not_found", 404)


def conflict(message: str, code: str = "conflict", **detail) -> AppError:
    return AppError(message, code, 409, detail)
