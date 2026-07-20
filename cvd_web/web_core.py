"""Общий HTTP-фундамент приложения: константы, ошибки и разбор запроса."""
from __future__ import annotations

import json
from http import cookies
from typing import Any
from urllib.parse import parse_qs


SESSION_COOKIE = "cvd_session"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
MIN_PASSWORD_LENGTH = 15
PASSWORD_CHANGE_ALLOWED_PATHS = {"/app", "/api/logout", "/api/me", "/api/me/password"}
COMMON_PASSWORDS = {
    "admin12345",
    "password",
    "password123",
    "qwerty12345",
    "change-this-long-password",
    "changeme",
    "letmein",
    "welcome",
}
PUBLIC_SETTING_KEYS = {
    "app_name",
    "organization_name",
    "system_description",
    "usage_notice",
    "support_contact",
    "default_theme",
    # Нужны рабочему месту, чтобы предупредить о переполнении контекста до отправки.
    "lm_studio_context_tokens",
    "lm_studio_max_tokens",
}


class HTTPError(Exception):
    def __init__(self, status: int, message: str, headers: list[tuple[str, str]] | None = None):
        self.status = status
        self.message = message
        self.headers = headers or []
        super().__init__(message)


class Request:
    def __init__(self, environ: dict[str, Any]):
        self.environ = environ
        self.method = environ.get("REQUEST_METHOD", "GET").upper()
        self.path = environ.get("PATH_INFO", "/") or "/"
        self.query = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
        self._body: bytes | None = None
        self._json: Any = None
        self.cookies = cookies.SimpleCookie(environ.get("HTTP_COOKIE", ""))

    @property
    def user_agent(self) -> str:
        return self.environ.get("HTTP_USER_AGENT", "")[:500]

    @property
    def ip_address(self) -> str:
        forwarded = self.environ.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()[:100]
        return self.environ.get("REMOTE_ADDR", "")[:100]

    def body(self) -> bytes:
        if self._body is None:
            length = int(self.environ.get("CONTENT_LENGTH") or "0")
            self._body = self.environ["wsgi.input"].read(length) if length else b""
        return self._body

    def json(self) -> Any:
        if self._json is not None:
            return self._json
        raw = self.body()
        if not raw:
            self._json = {}
            return self._json
        try:
            self._json = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise HTTPError(400, "Некорректный JSON") from exc
        return self._json

    def form(self) -> dict[str, str]:
        raw = self.body().decode("utf-8", errors="replace")
        parsed = parse_qs(raw, keep_blank_values=True)
        return {key: values[-1] if values else "" for key, values in parsed.items()}

    def header(self, name: str) -> str:
        key = "HTTP_" + name.upper().replace("-", "_")
        return self.environ.get(key, "")
