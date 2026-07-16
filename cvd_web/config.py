from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class Config:
    app_env: str
    project_root: Path
    db_path: Path
    host: str
    port: int
    cookie_secure: bool
    session_days: int
    admin_email: str
    admin_password: str
    lm_studio_api_url: str
    lm_studio_model: str
    lm_studio_timeout_seconds: int
    lm_studio_max_tokens: int
    lm_studio_temperature: float
    max_request_bytes: int

    @property
    def production_mode(self) -> bool:
        return self.app_env in {"prod", "production"}


def load_config() -> Config:
    db_path = Path(os.getenv("CVD_DB_PATH", PROJECT_ROOT / "data" / "cvd.sqlite3"))
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path

    return Config(
        app_env=os.getenv("CVD_ENV", "development").strip().lower() or "development",
        project_root=PROJECT_ROOT,
        db_path=db_path,
        host=os.getenv("CVD_HOST", "127.0.0.1"),
        port=_env_int("CVD_PORT", 8080),
        cookie_secure=_env_bool("CVD_COOKIE_SECURE", False),
        session_days=_env_int("CVD_SESSION_DAYS", 7),
        admin_email=os.getenv("CVD_ADMIN_EMAIL", "admin@example.local"),
        admin_password=os.getenv("CVD_ADMIN_PASSWORD", "admin12345"),
        lm_studio_api_url=os.getenv(
            "LM_STUDIO_API_URL",
            "http://127.0.0.1:1234/v1/chat/completions",
        ),
        lm_studio_model=os.getenv("LM_STUDIO_MODEL", "healtheart-cvd-engine"),
        lm_studio_timeout_seconds=_env_int("LM_STUDIO_TIMEOUT_SECONDS", 1200),
        lm_studio_max_tokens=_env_int("LM_STUDIO_MAX_TOKENS", 4096),
        lm_studio_temperature=float(os.getenv("LM_STUDIO_TEMPERATURE", "0.2").replace(",", ".")),
        max_request_bytes=_env_int("CVD_MAX_REQUEST_BYTES", 2 * 1024 * 1024),
    )
