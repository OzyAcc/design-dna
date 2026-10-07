"""Configuration from environment variables (see dashboard/.env.example). Secrets stay server-side.

Provider keys come from the environment first, then from <data>/secrets.json (written by the Settings page,
file mode 0600). Keys are never returned to the browser; only whether they are configured.
"""
from __future__ import annotations

import ipaddress
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENGINE = REPO_ROOT / "skills" / "reverse-design" / "scripts"
VENDORED_FONTS = REPO_ROOT / "skills" / "reverse-design" / "tests" / "fonts"
WEB_DIST = REPO_ROOT / "dashboard" / "web" / "dist"

SECRET_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")


def _bool(v: str | None, default=False) -> bool:
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    data_dir: Path
    host: str
    port: int
    auth_token: str | None
    engine_dir: Path
    python: str
    font_dirs: list[Path]
    analysis_model: str
    copy_model: str
    image_model: str
    enable_mock_providers: bool
    fetch_allow_private: bool
    fetch_proxy: str | None
    max_upload_bytes: int
    max_pixels: int
    fetch_timeout: float
    fetch_max_bytes: int
    worker_threads: int
    lease_seconds: int
    web_dist: Path
    secrets: dict = field(default_factory=dict)

    # ------------------------------------------------------------ derived paths
    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def blobs(self) -> Path:
        return self.data_dir / "blobs"

    @property
    def previews(self) -> Path:
        return self.data_dir / "previews"

    @property
    def templates(self) -> Path:
        return self.data_dir / "templates"

    @property
    def jobs(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def outputs(self) -> Path:
        return self.data_dir / "outputs"

    @property
    def exports(self) -> Path:
        return self.data_dir / "exports"

    @property
    def fonts(self) -> Path:
        return self.data_dir / "fonts"

    @property
    def secrets_path(self) -> Path:
        return self.data_dir / "secrets.json"

    def secret(self, name: str) -> str | None:
        return os.environ.get(name) or self.secrets.get(name) or None

    def secret_source(self, name: str) -> str | None:
        if os.environ.get(name):
            return "environment"
        if self.secrets.get(name):
            return "settings"
        return None

    def save_secret(self, name: str, value: str | None) -> None:
        if name not in SECRET_KEYS:
            raise ValueError(f"unknown secret {name}")
        data = dict(self.secrets)
        if value:
            data[name] = value
        else:
            data.pop(name, None)
        tmp = self.secrets_path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, self.secrets_path)
        self.secrets = data

    def is_loopback(self) -> bool:
        try:
            return ipaddress.ip_address(self.host).is_loopback
        except ValueError:
            return self.host == "localhost"

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.blobs, self.previews, self.templates, self.jobs, self.outputs, self.exports, self.fonts):
            p.mkdir(parents=True, exist_ok=True)


def load() -> Settings:
    data = Path(os.environ.get("DNA_DATA_DIR") or Path.home() / "design-dna-dashboard").expanduser().resolve()
    extra = [Path(p).expanduser() for p in os.environ.get("DNA_FONT_DIRS", "").split(os.pathsep) if p.strip()]
    s = Settings(
        data_dir=data,
        host=os.environ.get("DNA_HOST", "127.0.0.1"),
        port=_int("DNA_PORT", 8765),
        auth_token=os.environ.get("DNA_AUTH_TOKEN") or None,
        engine_dir=Path(os.environ.get("DNA_ENGINE_DIR") or DEFAULT_ENGINE).resolve(),
        python=os.environ.get("DNA_PYTHON") or sys.executable,
        font_dirs=[data / "fonts", *extra] + ([VENDORED_FONTS] if _bool(os.environ.get("DNA_USE_VENDORED_FONTS"), True) else []),
        analysis_model=os.environ.get("DNA_ANALYSIS_MODEL", "claude-opus-5-5"),
        copy_model=os.environ.get("DNA_COPY_MODEL", "claude-opus-5-5"),
        image_model=os.environ.get("DNA_IMAGE_MODEL", "gpt-image-2"),
        enable_mock_providers=_bool(os.environ.get("DNA_ENABLE_MOCK_PROVIDERS")),
        fetch_allow_private=_bool(os.environ.get("DNA_FETCH_ALLOW_PRIVATE")),
        fetch_proxy=os.environ.get("DNA_FETCH_PROXY") or None,
        max_upload_bytes=_int("DNA_MAX_UPLOAD_MB", 25) * 1024 * 1024,
        max_pixels=_int("DNA_MAX_MEGAPIXELS", 40) * 1_000_000,
        fetch_timeout=float(os.environ.get("DNA_FETCH_TIMEOUT", "12")),
        fetch_max_bytes=_int("DNA_FETCH_MAX_MB", 15) * 1024 * 1024,
        worker_threads=max(1, _int("DNA_WORKER_THREADS", 2)),
        lease_seconds=max(30, _int("DNA_LEASE_SECONDS", 180)),
        web_dist=Path(os.environ.get("DNA_WEB_DIST") or WEB_DIST),
    )
    s.ensure_dirs()
    if s.secrets_path.exists():
        try:
            s.secrets = json.loads(s.secrets_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            s.secrets = {}
    return s


_SETTINGS: Settings | None = None


def get() -> Settings:
    global _SETTINGS
    if _SETTINGS is None:
        _SETTINGS = load()
    return _SETTINGS


def reset(new: Settings | None = None) -> None:
    """Tests: reload settings after changing the environment."""
    global _SETTINGS
    _SETTINGS = new
