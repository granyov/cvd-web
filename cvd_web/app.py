from __future__ import annotations

import hashlib
import json
import mimetypes
import sqlite3
import re
import threading
import time
import traceback
from contextlib import contextmanager
from html import escape
from datetime import datetime, timedelta, timezone
from http import cookies
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from .auth import hash_password, new_token, utc_now, verify_password
from .config import Config
from .cvd_schema import validate_and_normalize_patient_data
from .db import (
    audit,
    connect,
    get_app_settings,
    get_app_settings_full,
    init_db,
    row_to_dict,
    rows_to_dicts,
    update_app_settings,
)
from .fhir import build_fhir_bundle
from .integration_import import KNOWN_PATHS, parse_clinical_import
from .inference_queue import InferenceQueue, InferenceQueueError
from .lmstudio import call_lm_studio
from .lmstudio_models import LMStudioManagementError, activate_lm_model, list_lm_models
from .privacy import deidentify_patient_data
from .quality import case_quality_summary, has_clinical_input, patient_data_changes, patient_data_hash
from .rate_limit import MemoryRateLimiter
from .reporting import build_html_report
from .text_structuring import TEXT_MAX_INPUT_CHARS, TEXT_STRUCTURING_VERSION, call_text_structuring
from .versions import APP_VERSION, MODEL_OUTPUT_SCHEMA_VERSION, MODEL_PROMPT_VERSION, PATIENT_SCHEMA_VERSION


SESSION_COOKIE = "cvd_session"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
MIN_PASSWORD_LENGTH = 15
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


class CVDApplication:
    def __init__(self, config: Config, *, start_batch_worker: bool = True):
        self.config = config
        init_db(config)
        self.template_dir = config.project_root / "cvd_web" / "templates"
        self.static_dir = config.project_root / "cvd_web" / "static"
        self.rate_limiter = MemoryRateLimiter()
        self.inference_queue = InferenceQueue()
        self.started_at = datetime.now(timezone.utc).replace(microsecond=0)
        self.batch_worker_event = threading.Event()
        self.recover_interrupted_batch_jobs()
        self.batch_worker_thread: threading.Thread | None = None
        if start_batch_worker:
            self.batch_worker_thread = threading.Thread(
                target=self.batch_worker_loop,
                name="cvd-batch-worker",
                daemon=True,
            )
            self.batch_worker_thread.start()

    def __call__(self, environ: dict[str, Any], start_response: Callable):
        request = Request(environ)
        try:
            status, headers, body = self.handle(request)
        except HTTPError as exc:
            status, headers, body = self.json_response({"error": exc.message}, exc.status, exc.headers)
        except Exception as exc:
            traceback.print_exc()
            status, headers, body = self.json_response(
                {"error": "Внутренняя ошибка сервера"},
                500,
            )

        start_response(status, headers)
        return [body]

    def handle(self, request: Request) -> tuple[str, list[tuple[str, str]], bytes]:
        self.cleanup_expired_sessions()

        if request.path.startswith("/static/"):
            return self.serve_static(request.path.removeprefix("/static/"))
        if request.path == "/healthz" and request.method == "GET":
            return self.json_response({"ok": True})

        user = self.current_user(request)

        if request.path == "/":
            return self.redirect("/app" if user else "/login")
        if request.path == "/login" and request.method == "GET":
            if user:
                return self.redirect("/app")
            return self.render("login.html", user=None, csrf_token="")
        if request.path == "/api/login" and request.method == "POST":
            self.verify_fetch_metadata(request)
            return self.login(request)

        if user is None:
            if request.path.startswith("/api/"):
                raise HTTPError(401, "Нужна авторизация")
            return self.redirect("/login")

        if request.method in UNSAFE_METHODS:
            self.verify_fetch_metadata(request)
            self.verify_csrf(request, user)

        if request.path == "/app" and request.method == "GET":
            return self.render("app.html", user=user, csrf_token=user["csrf_token"])
        if request.path == "/cases" and request.method == "GET":
            return self.render("cases.html", user=user, csrf_token=user["csrf_token"])
        if request.path == "/admin" and request.method == "GET":
            self.require_admin(user)
            return self.render("admin.html", user=user, csrf_token=user["csrf_token"])
        if match := re.fullmatch(r"/reports/(\d+)", request.path):
            if request.method == "GET":
                return self.view_html_report(user, int(match.group(1)))
        if request.path == "/api/logout" and request.method == "POST":
            return self.logout(request, user)
        if request.path == "/api/me" and request.method == "GET":
            return self.json_response({"user": self.public_user(user), "csrfToken": user["csrf_token"]})
        if request.path == "/api/me/password" and request.method == "POST":
            return self.change_own_password(request, user)
        if request.path == "/api/cases" and request.method == "GET":
            return self.list_cases(request, user)
        if request.path == "/api/cases" and request.method == "POST":
            return self.save_case(request, user)
        if request.path == "/api/library/summary" and request.method == "GET":
            return self.library_summary(user)
        if request.path == "/api/import/preview" and request.method == "POST":
            return self.preview_clinical_import(request, user)
        if request.path == "/api/imports" and request.method == "GET":
            return self.list_clinical_imports(request, user)
        if request.path == "/api/text-preparations" and request.method == "GET":
            return self.list_text_preparations(request, user)
        if match := re.fullmatch(r"/api/imports/(\d+)/applied", request.path):
            if request.method == "POST":
                return self.mark_clinical_import_applied(request, user, int(match.group(1)))
        if match := re.fullmatch(r"/api/cases/(\d+)", request.path):
            if request.method == "GET":
                return self.get_case(user, int(match.group(1)))
        if match := re.fullmatch(r"/api/cases/(\d+)/fhir", request.path):
            if request.method == "GET":
                return self.export_case_fhir(user, int(match.group(1)))
        if match := re.fullmatch(r"/api/cases/(\d+)/delete", request.path):
            if request.method == "POST":
                return self.delete_case(user, int(match.group(1)))
        if match := re.fullmatch(r"/api/cases/(\d+)/copy", request.path):
            if request.method == "POST":
                return self.copy_case(user, int(match.group(1)))
        if request.path == "/api/model/diagnose" and request.method == "POST":
            return self.diagnose(request, user)
        if request.path == "/api/model/structure-text" and request.method == "POST":
            return self.structure_text(request, user)
        if request.path == "/api/inference/status" and request.method == "GET":
            return self.inference_status(user)
        if request.path == "/api/reports/html" and request.method == "POST":
            return self.export_html_report(request, user)
        if request.path == "/api/requests" and request.method == "GET":
            return self.list_requests(request, user)
        if match := re.fullmatch(r"/api/requests/(\d+)", request.path):
            if request.method == "GET":
                return self.get_request_result(user, int(match.group(1)))
        if match := re.fullmatch(r"/api/requests/(\d+)/review", request.path):
            if request.method == "POST":
                return self.review_model_request(request, user, int(match.group(1)))
        if request.path == "/api/admin/users" and request.method == "GET":
            self.require_admin(user)
            return self.admin_list_users()
        if request.path == "/api/admin/users" and request.method == "POST":
            self.require_admin(user)
            return self.admin_create_user(request, user)
        if match := re.fullmatch(r"/api/admin/users/(\d+)/update", request.path):
            if request.method == "POST":
                self.require_admin(user)
                return self.admin_update_user(request, user, int(match.group(1)))
        if match := re.fullmatch(r"/api/admin/users/(\d+)/password", request.path):
            if request.method == "POST":
                self.require_admin(user)
                return self.admin_reset_password(request, user, int(match.group(1)))
        if request.path == "/api/admin/requests" and request.method == "GET":
            self.require_admin(user)
            return self.admin_list_requests(request)
        if request.path == "/api/admin/reviews" and request.method == "GET":
            self.require_admin(user)
            return self.admin_list_reviews(request)
        if request.path == "/api/admin/audit" and request.method == "GET":
            self.require_admin(user)
            return self.admin_list_audit(request)
        if request.path == "/api/admin/settings" and request.method == "GET":
            self.require_admin(user)
            return self.admin_get_settings()
        if request.path == "/api/admin/settings" and request.method == "POST":
            self.require_admin(user)
            return self.admin_update_settings(request, user)
        if request.path == "/api/admin/stats" and request.method == "GET":
            self.require_admin(user)
            return self.admin_stats()
        if request.path == "/api/admin/dashboard" and request.method == "GET":
            self.require_admin(user)
            return self.admin_dashboard()
        if request.path == "/api/admin/model-quality" and request.method == "GET":
            self.require_admin(user)
            return self.admin_model_quality()
        if request.path == "/api/admin/model-health" and request.method == "GET":
            self.require_admin(user)
            return self.admin_model_health()
        if request.path == "/api/admin/backups" and request.method == "GET":
            self.require_admin(user)
            return self.admin_list_backups()
        if request.path == "/api/admin/backups" and request.method == "POST":
            self.require_admin(user)
            return self.admin_create_backup(user)
        if match := re.fullmatch(r"/api/admin/backups/([A-Za-z0-9_.-]+)", request.path):
            if request.method == "GET":
                self.require_admin(user)
                return self.admin_download_backup(match.group(1))
        if request.path == "/api/admin/restore" and request.method == "POST":
            self.require_admin(user)
            return self.admin_restore_backup(request, user)
        if request.path == "/api/admin/ai-gateway/test" and request.method == "POST":
            self.require_admin(user)
            return self.admin_ai_gateway_test(request, user)
        if request.path == "/api/admin/models" and request.method == "GET":
            self.require_admin(user)
            return self.admin_models()
        if request.path == "/api/admin/models/activate" and request.method == "POST":
            self.require_admin(user)
            return self.admin_activate_model(request, user)
        if request.path == "/api/admin/quality" and request.method == "GET":
            self.require_admin(user)
            return self.admin_quality()
        if request.path == "/api/admin/gold-set" and request.method == "GET":
            self.require_admin(user)
            return self.admin_gold_set()
        if request.path == "/api/admin/gold-set" and request.method == "POST":
            self.require_admin(user)
            return self.admin_upsert_gold_case(request, user)
        if request.path == "/api/admin/gold-runs" and request.method == "GET":
            self.require_admin(user)
            return self.admin_gold_runs()
        if request.path == "/api/admin/gold-runs" and request.method == "POST":
            self.require_admin(user)
            return self.admin_create_gold_run(user)
        if request.path == "/api/admin/batch/cases" and request.method == "GET":
            self.require_admin(user)
            return self.admin_batch_cases()
        if request.path == "/api/admin/batch/jobs" and request.method == "GET":
            self.require_admin(user)
            return self.admin_batch_jobs()
        if request.path == "/api/admin/batch/jobs" and request.method == "POST":
            self.require_admin(user)
            return self.admin_create_batch_job(request, user)
        if match := re.fullmatch(r"/api/admin/batch/jobs/(\d+)", request.path):
            if request.method == "GET":
                self.require_admin(user)
                return self.admin_batch_job(int(match.group(1)))
        if match := re.fullmatch(r"/api/admin/batch/jobs/(\d+)/cancel", request.path):
            if request.method == "POST":
                self.require_admin(user)
                return self.admin_cancel_batch_job(user, int(match.group(1)))
        raise HTTPError(404, "Не найдено")

    def cleanup_expired_sessions(self) -> None:
        with connect(self.config.db_path) as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (utc_now(),))

    def current_user(self, request: Request) -> dict[str, Any] | None:
        morsel = request.cookies.get(SESSION_COOKIE)
        if not morsel:
            return None
        session_id = morsel.value
        with connect(self.config.db_path) as conn:
            row = conn.execute(
                """
                SELECT
                  u.id, u.email, u.full_name, u.role, u.is_active, u.must_change_password,
                  s.id AS session_id, s.csrf_token, s.expires_at
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.id = ? AND s.expires_at > ? AND u.is_active = 1
                """,
                (session_id, utc_now()),
            ).fetchone()
        return row_to_dict(row)

    def verify_csrf(self, request: Request, user: dict[str, Any]) -> None:
        supplied = request.header("X-CSRF-Token")
        if not supplied and request.environ.get("CONTENT_TYPE", "").startswith("application/x-www-form-urlencoded"):
            supplied = request.form().get("csrf_token", "")
        if not supplied or supplied != user["csrf_token"]:
            raise HTTPError(403, "CSRF token mismatch")

    def verify_fetch_metadata(self, request: Request) -> None:
        fetch_site = request.header("Sec-Fetch-Site").lower()
        if fetch_site == "cross-site":
            raise HTTPError(403, "Cross-site request blocked")

        origin = request.header("Origin")
        if origin and not self.same_origin(request, origin):
            raise HTTPError(403, "Недоверенный Origin")

        referer = request.header("Referer")
        if referer and not self.same_origin(request, referer):
            raise HTTPError(403, "Недоверенный Referer")

    def same_origin(self, request: Request, candidate: str) -> bool:
        parsed = urlsplit(candidate)
        if not parsed.scheme or not parsed.netloc:
            return False
        expected_scheme = request.environ.get("HTTP_X_FORWARDED_PROTO") or request.environ.get("wsgi.url_scheme", "http")
        expected_host = request.environ.get("HTTP_X_FORWARDED_HOST") or request.environ.get("HTTP_HOST")
        if not expected_host:
            server_name = request.environ.get("SERVER_NAME", "")
            server_port = request.environ.get("SERVER_PORT", "")
            expected_host = f"{server_name}:{server_port}" if server_port else server_name
        return parsed.scheme == expected_scheme and parsed.netloc == expected_host

    def require_admin(self, user: dict[str, Any]) -> None:
        if user.get("role") != "admin":
            raise HTTPError(403, "Нужны права администратора")

    def load_settings(self) -> dict[str, str]:
        with connect(self.config.db_path) as conn:
            return get_app_settings(conn)

    def setting_int(self, settings: dict[str, str], key: str, default: int) -> int:
        try:
            return int(settings.get(key, default))
        except (TypeError, ValueError):
            return default

    def setting_float(self, settings: dict[str, str], key: str, default: float) -> float:
        try:
            return float(str(settings.get(key, default)).replace(",", "."))
        except (TypeError, ValueError):
            return default

    def setting_bool(self, settings: dict[str, str], key: str, default: bool) -> bool:
        raw = settings.get(key)
        if raw is None:
            return default
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}

    def configure_inference_queue(self, settings: dict[str, str]) -> int:
        self.inference_queue.configure(
            max_concurrent=self.setting_int(settings, "lm_studio_max_concurrent", 1),
            queue_limit=self.setting_int(settings, "lm_studio_queue_limit", 64),
            per_user_limit=self.setting_int(settings, "lm_studio_per_user_limit", 2),
        )
        return self.setting_int(settings, "lm_studio_queue_timeout_seconds", 1800)

    def production_queue_status(self, settings: dict[str, str]) -> dict[str, Any]:
        backend = str(settings.get("inference_queue_backend") or "memory").strip().lower()
        if backend not in {"memory", "redis", "postgresql"}:
            backend = "memory"
        dsn_configured = bool(str(settings.get("inference_queue_dsn") or "").strip())
        external = backend in {"redis", "postgresql"}
        return {
            "backend": backend,
            "active_backend": "memory",
            "external_requested": external,
            "dsn_configured": dsn_configured,
            "production_ready": (not external),
            "status": "memory-active" if not external else "adapter-not-installed",
            "message": (
                "In-process queue active. Use a single backend process or configure an external adapter before multi-process deployment."
                if not external else
                "Redis/PostgreSQL backend is configured for rollout, but this build still uses the in-process queue adapter."
            ),
        }

    def inference_status(self, user: dict[str, Any]):
        settings = self.load_settings()
        self.configure_inference_queue(settings)
        return self.json_response({"queue": self.inference_queue.snapshot(user_id=user["id"])})

    def model_metrics(self, response_payload: dict[str, Any] | None, duration_ms: int) -> dict[str, Any]:
        raw = response_payload.get("raw", {}) if isinstance(response_payload, dict) else {}
        usage = raw.get("usage", {}) if isinstance(raw, dict) else {}
        choices = raw.get("choices", []) if isinstance(raw, dict) else []
        first_choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}

        def metric_int(key: str) -> int:
            try:
                return max(0, int(usage.get(key, 0)))
            except (TypeError, ValueError):
                return 0

        completion_tokens = metric_int("completion_tokens")
        seconds = duration_ms / 1000 if duration_ms > 0 else 0
        return {
            "prompt_tokens": metric_int("prompt_tokens"),
            "completion_tokens": completion_tokens,
            "total_tokens": metric_int("total_tokens"),
            "tokens_per_second": round(completion_tokens / seconds, 2) if seconds else 0,
            "finish_reason": str(first_choice.get("finish_reason") or "")[:80],
        }

    def public_settings(self, settings: dict[str, str]) -> dict[str, str]:
        return {key: value for key, value in settings.items() if key in PUBLIC_SETTING_KEYS}

    def query_int(self, request: Request, key: str, default: int, min_value: int, max_value: int) -> int:
        raw = request.query.get(key, [str(default)])[0]
        try:
            parsed = int(raw)
        except (TypeError, ValueError):
            return default
        return max(min_value, min(parsed, max_value))

    def ensure_request_size(self, request: Request, settings: dict[str, str] | None = None) -> None:
        settings = settings or self.load_settings()
        max_request_bytes = self.setting_int(settings, "max_request_bytes", self.config.max_request_bytes)
        if len(request.body()) > max_request_bytes:
            raise HTTPError(413, "Запрос слишком большой")

    def ai_gateway_headers(self, settings: dict[str, str]) -> dict[str, str]:
        name = str(settings.get("ai_gateway_auth_header_name") or "").strip()
        value = str(settings.get("ai_gateway_auth_header_value") or "").strip()
        if not name or not value:
            return {}
        if not re.fullmatch(r"[A-Za-z0-9!#$%&'*+.^_`|~-]{1,80}", name):
            raise HTTPError(400, "Некорректное имя auth-заголовка AI Gateway")
        blocked = {"host", "content-length", "content-type", "accept", "connection"}
        if name.lower() in blocked:
            raise HTTPError(400, "Этот auth-заголовок нельзя переопределять")
        return {name: value[:4000]}

    def ai_gateway_public_profile(self, settings: dict[str, str]) -> dict[str, Any]:
        profile = str(settings.get("ai_gateway_profile") or "local").strip().lower()
        return {
            "profile": profile,
            "api_url": settings.get("lm_studio_api_url") or self.config.lm_studio_api_url,
            "selected_model": settings.get("lm_studio_model") or self.config.lm_studio_model,
            "auth_header_configured": bool(str(settings.get("ai_gateway_auth_header_name") or "").strip() and str(settings.get("ai_gateway_auth_header_value") or "").strip()),
        }

    def enforce_rate_limit(self, key: str, *, limit: int, window_seconds: int, message: str) -> None:
        allowed, retry_after = self.rate_limiter.allow(key, limit=limit, window_seconds=window_seconds)
        if not allowed:
            raise HTTPError(429, f"{message}. Повторите через {retry_after} сек.", [("Retry-After", str(retry_after))])

    def normalized_patient_data(self, value: Any) -> dict[str, dict[str, Any]]:
        normalized, errors = validate_and_normalize_patient_data(value)
        if errors:
            preview = "; ".join(errors[:5])
            if len(errors) > 5:
                preview += f"; и еще {len(errors) - 5}"
            raise HTTPError(400, f"Некорректные данные пациента: {preview}")
        return normalized

    def validate_new_password(self, password: str, *, email: str = "") -> None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise HTTPError(400, f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов")
        normalized = password.strip().lower()
        email_local = email.split("@", 1)[0].lower() if email else ""
        if normalized in COMMON_PASSWORDS or (email_local and normalized == email_local):
            raise HTTPError(400, "Пароль слишком предсказуемый")

    def login(self, request: Request):
        data = request.json()
        email = str(data.get("email", "")).strip().lower()
        password = str(data.get("password", ""))
        if not email or not password:
            raise HTTPError(400, "Введите email и пароль")
        self.enforce_rate_limit(
            f"login:{request.ip_address}:{email[:160]}",
            limit=10,
            window_seconds=300,
            message="Слишком много попыток входа",
        )

        with connect(self.config.db_path) as conn:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            user = row_to_dict(row)
            if not user or not user["is_active"] or not verify_password(password, user["password_hash"]):
                audit(conn, user_id=user["id"] if user else None, action="login_failed", target_type="user", target_id=email)
                raise HTTPError(401, "Неверный email или пароль")

            session_id = new_token()
            csrf_token = new_token()
            now_dt = datetime.now(timezone.utc).replace(microsecond=0)
            expires_at = (now_dt + timedelta(days=self.config.session_days)).isoformat()
            conn.execute(
                """
                INSERT INTO sessions (id, user_id, csrf_token, created_at, expires_at, user_agent, ip_address)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, user["id"], csrf_token, now_dt.isoformat(), expires_at, request.user_agent, request.ip_address),
            )
            conn.execute("UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?", (now_dt.isoformat(), now_dt.isoformat(), user["id"]))
            audit(conn, user_id=user["id"], action="login_success", target_type="user", target_id=user["id"])

        headers = self.session_cookie_header(session_id)
        return self.json_response({"ok": True, "redirect": "/app"}, headers=headers)

    def logout(self, request: Request, user: dict[str, Any]):
        with connect(self.config.db_path) as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (user["session_id"],))
            audit(conn, user_id=user["id"], action="logout", target_type="user", target_id=user["id"])
        headers = self.clear_session_cookie_header()
        return self.json_response({"ok": True, "redirect": "/login"}, headers=headers)

    def change_own_password(self, request: Request, user: dict[str, Any]):
        data = request.json()
        current_password = str(data.get("current_password", ""))
        new_password = str(data.get("new_password", ""))
        self.validate_new_password(new_password, email=str(user.get("email", "")))
        with connect(self.config.db_path) as conn:
            row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
            if not row or not verify_password(current_password, row["password_hash"]):
                raise HTTPError(403, "Текущий пароль указан неверно")
            now = utc_now()
            conn.execute(
                "UPDATE users SET password_hash = ?, must_change_password = 0, updated_at = ? WHERE id = ?",
                (hash_password(new_password), now, user["id"]),
            )
            conn.execute("DELETE FROM sessions WHERE user_id = ? AND id <> ?", (user["id"], user["session_id"]))
            audit(conn, user_id=user["id"], action="own_password_change", target_type="user", target_id=user["id"])
        return self.json_response({"ok": True})

    def list_cases(self, request: Request, user: dict[str, Any]):
        query = str(request.query.get("q", [""])[0]).strip()[:200]
        analysis_filter = str(request.query.get("analysis", [""])[0]).strip().lower()
        allowed_filters = {"", "with", "without", "attention", "error", "ready", "incomplete", "critical", "stale", "reviewed"}
        if analysis_filter not in allowed_filters:
            raise HTTPError(400, "Некорректный фильтр результатов")
        limit = self.query_int(request, "limit", 100, 1, 200)
        offset = self.query_int(request, "offset", 0, 0, 1_000_000)
        escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        search = f"%{escaped_query}%"
        with connect(self.config.db_path) as conn:
            rows = conn.execute(
                """
                SELECT c.id, c.title, c.patient_id, c.data_json, c.created_at, c.updated_at,
                       (
                         SELECT r.id
                         FROM model_requests r
                         WHERE r.case_id = c.id AND r.user_id = c.user_id
                           AND r.status = 'success' AND r.parsed_output_json IS NOT NULL
                         ORDER BY r.created_at DESC, r.id DESC
                         LIMIT 1
                       ) AS latest_result_id,
                       (
                         SELECT r.input_data_hash
                         FROM model_requests r
                         WHERE r.case_id = c.id AND r.user_id = c.user_id
                           AND r.status = 'success' AND r.parsed_output_json IS NOT NULL
                         ORDER BY r.created_at DESC, r.id DESC
                         LIMIT 1
                       ) AS latest_result_input_hash,
                       (
                         SELECT COUNT(*)
                         FROM model_requests r
                         WHERE r.case_id = c.id AND r.user_id = c.user_id
                       ) AS analysis_count,
                       (
                         SELECT r.status
                         FROM model_requests r
                         WHERE r.case_id = c.id AND r.user_id = c.user_id
                         ORDER BY r.created_at DESC, r.id DESC
                         LIMIT 1
                       ) AS latest_request_status,
                       EXISTS (
                         SELECT 1 FROM model_request_reviews rv
                         JOIN model_requests rr ON rr.id = rv.model_request_id
                         WHERE rr.case_id = c.id AND rr.user_id = c.user_id
                       ) AS has_review
                FROM cases c
                WHERE c.user_id = ?
                  AND (? = '' OR c.title LIKE ? ESCAPE '\\' OR c.patient_id LIKE ? ESCAPE '\\'
                       OR CAST(c.id AS TEXT) LIKE ? ESCAPE '\\')
                ORDER BY c.updated_at DESC
                """,
                (user["id"], query, search, search, search),
            ).fetchall()
        items = []
        for item in rows_to_dicts(rows):
            data = json.loads(item.pop("data_json") or "{}")
            quality = case_quality_summary(data)
            current_hash = patient_data_hash(data)
            item["quality"] = quality
            item["current_data_hash"] = current_hash
            item["ai_result_stale"] = bool(item.get("latest_result_id") and item.get("latest_result_input_hash") and item.get("latest_result_input_hash") != current_hash)
            item["has_review"] = bool(item.get("has_review"))
            if self.case_matches_analysis_filter(item, analysis_filter):
                items.append(item)
        page_items = items[offset:offset + limit]
        return self.json_response({
            "cases": page_items,
            "total": len(items),
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(page_items) < len(items),
        })

    @staticmethod
    def case_matches_analysis_filter(item: dict[str, Any], analysis_filter: str) -> bool:
        if not analysis_filter:
            return True
        latest_result = bool(item.get("latest_result_id"))
        quality = item.get("quality") or {}
        if analysis_filter == "with":
            return latest_result
        if analysis_filter == "without":
            return not latest_result
        if analysis_filter == "attention":
            return bool(item.get("ai_result_stale") or item.get("latest_request_status") == "error" or quality.get("missing_required") or quality.get("critical_signals"))
        if analysis_filter == "error":
            return item.get("latest_request_status") == "error"
        if analysis_filter == "ready":
            return int(quality.get("readiness_percent") or 0) == 100 and not latest_result
        if analysis_filter == "incomplete":
            return int(quality.get("readiness_percent") or 0) < 100
        if analysis_filter == "critical":
            return int(quality.get("critical_signals") or 0) > 0
        if analysis_filter == "stale":
            return bool(item.get("ai_result_stale"))
        if analysis_filter == "reviewed":
            return bool(item.get("has_review"))
        return True

    def library_summary(self, user: dict[str, Any]):
        with connect(self.config.db_path) as conn:
            row = conn.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM cases WHERE user_id = ?) AS cases_total,
                  (SELECT COUNT(*) FROM model_requests WHERE user_id = ?) AS requests_total,
                  (SELECT COUNT(*) FROM model_requests WHERE user_id = ? AND status = 'success') AS requests_success,
                  (SELECT COUNT(*) FROM model_requests WHERE user_id = ? AND status = 'error') AS requests_error,
                  (SELECT COUNT(*) FROM data_imports WHERE user_id = ?) AS imports_total
                """,
                (user["id"], user["id"], user["id"], user["id"], user["id"]),
            ).fetchone()
        return self.json_response({"summary": row_to_dict(row)})

    def preview_clinical_import(self, request: Request, user: dict[str, Any]):
        self.ensure_request_size(request)
        self.enforce_rate_limit(
            f"clinical-import:{user['id']}",
            limit=60,
            window_seconds=3600,
            message="Слишком много импортов",
        )
        data = request.json()
        if not isinstance(data, dict):
            raise HTTPError(400, "Запрос импорта должен быть объектом")
        source_format = str(data.get("source_format") or "auto").strip().lower()[:40]
        filename = re.sub(r"[^\w. ()\[\]-]+", "_", str(data.get("filename") or "import").strip(), flags=re.UNICODE)[:200]
        payload = data.get("payload")
        try:
            result = parse_clinical_import(source_format, payload)
        except ValueError as exc:
            raise HTTPError(400, str(exc)) from exc

        canonical = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        content_sha256 = hashlib.sha256(str(canonical).encode("utf-8")).hexdigest()
        now = utc_now()
        with connect(self.config.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO data_imports
                  (user_id, source_format, mapping_version, filename, content_sha256, mapped_fields,
                   mapped_paths_json, warning_count, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'previewed', ?)
                """,
                (
                    user["id"],
                    result["source_format"],
                    result["mapping_version"],
                    filename,
                    content_sha256,
                    result["summary"]["mapped_fields"],
                    json.dumps([item["path"] for item in result["mappings"]], ensure_ascii=False),
                    result["summary"]["warnings"],
                    now,
                ),
            )
            import_id = int(cur.lastrowid)
            audit(
                conn,
                user_id=user["id"],
                action="clinical_import_preview",
                target_type="data_import",
                target_id=import_id,
                details={
                    "source_format": result["source_format"],
                    "mapping_version": result["mapping_version"],
                    "filename": filename,
                    "content_sha256": content_sha256,
                    "mapped_fields": result["summary"]["mapped_fields"],
                    "warning_count": result["summary"]["warnings"],
                },
            )
        result["import_id"] = import_id
        result["filename"] = filename
        return self.json_response(result)

    def mark_clinical_import_applied(self, request: Request, user: dict[str, Any], import_id: int):
        data = request.json()
        if not isinstance(data, dict):
            raise HTTPError(400, "Запрос применения импорта должен быть объектом")
        selected_paths = data.get("selected_paths") or []
        if not isinstance(selected_paths, list):
            raise HTTPError(400, "selected_paths должен быть массивом")
        selected_paths = list(dict.fromkeys(str(path) for path in selected_paths if str(path) in KNOWN_PATHS))
        case_id = data.get("case_id")
        if case_id not in (None, ""):
            try:
                case_id = int(case_id)
            except (TypeError, ValueError) as exc:
                raise HTTPError(400, "Некорректный case_id") from exc
        else:
            case_id = None

        with connect(self.config.db_path) as conn:
            row = conn.execute(
                "SELECT id, mapped_paths_json FROM data_imports WHERE id = ? AND user_id = ?",
                (import_id, user["id"]),
            ).fetchone()
            if not row:
                raise HTTPError(404, "Импорт не найден")
            mapped_paths = set(json.loads(row["mapped_paths_json"] or "[]"))
            selected_paths = [path for path in selected_paths if path in mapped_paths]
            if case_id is not None:
                case = conn.execute("SELECT id FROM cases WHERE id = ? AND user_id = ?", (case_id, user["id"])).fetchone()
                if not case:
                    raise HTTPError(404, "Кейс для импорта не найден")
            now = utc_now()
            conn.execute(
                """
                UPDATE data_imports
                SET status = 'applied', case_id = ?, selected_paths_json = ?, applied_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (case_id, json.dumps(selected_paths, ensure_ascii=False), now, import_id, user["id"]),
            )
            conn.execute(
                """
                UPDATE text_preparation_items
                SET status = 'applied', applied_at = ?, updated_at = ?
                WHERE import_id = ? AND user_id = ?
                """,
                (now, now, import_id, user["id"]),
            )
            audit(
                conn,
                user_id=user["id"],
                action="clinical_import_apply",
                target_type="data_import",
                target_id=import_id,
                details={"case_id": case_id, "selected_paths": selected_paths, "selected_count": len(selected_paths)},
            )
        return self.json_response({"ok": True, "import_id": import_id, "selected_count": len(selected_paths)})

    def list_clinical_imports(self, request: Request, user: dict[str, Any]):
        query = str(request.query.get("q", [""])[0]).strip()[:200]
        status_filter = str(request.query.get("status", [""])[0]).strip().lower()
        if status_filter not in {"", "previewed", "applied"}:
            raise HTTPError(400, "Некорректный фильтр статуса импорта")
        raw_case_id = str(request.query.get("case_id", [""])[0]).strip()
        if raw_case_id:
            try:
                case_id = int(raw_case_id)
            except ValueError as exc:
                raise HTTPError(400, "Некорректный case_id") from exc
        else:
            case_id = None
        limit = self.query_int(request, "limit", 50, 1, 200)
        offset = self.query_int(request, "offset", 0, 0, 1_000_000)
        escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        search = f"%{escaped_query}%"
        with connect(self.config.db_path) as conn:
            total = conn.execute(
                """
                SELECT COUNT(*)
                FROM data_imports d
                LEFT JOIN cases c ON c.id = d.case_id AND c.user_id = d.user_id
                WHERE d.user_id = ? AND (? = '' OR d.status = ?) AND (? IS NULL OR d.case_id = ?)
                  AND (? = '' OR d.filename LIKE ? ESCAPE '\\' OR d.source_format LIKE ? ESCAPE '\\'
                       OR c.title LIKE ? ESCAPE '\\' OR CAST(d.id AS TEXT) LIKE ? ESCAPE '\\')
                """,
                (
                    user["id"], status_filter, status_filter, case_id, case_id,
                    query, search, search, search, search,
                ),
            ).fetchone()[0]
            rows = conn.execute(
                """
                SELECT d.id, d.case_id, d.source_format, d.mapping_version, d.filename,
                       d.mapped_fields, d.warning_count, d.status, d.created_at, d.applied_at,
                       c.title AS case_title
                FROM data_imports d
                LEFT JOIN cases c ON c.id = d.case_id AND c.user_id = d.user_id
                WHERE d.user_id = ? AND (? = '' OR d.status = ?) AND (? IS NULL OR d.case_id = ?)
                  AND (? = '' OR d.filename LIKE ? ESCAPE '\\' OR d.source_format LIKE ? ESCAPE '\\'
                       OR c.title LIKE ? ESCAPE '\\' OR CAST(d.id AS TEXT) LIKE ? ESCAPE '\\')
                ORDER BY d.created_at DESC
                LIMIT ? OFFSET ?
                """,
                (
                    user["id"], status_filter, status_filter, case_id, case_id,
                    query, search, search, search, search,
                    limit, offset,
                ),
            ).fetchall()
        return self.json_response({
            "imports": rows_to_dicts(rows),
            "total": int(total),
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(rows) < int(total),
        })

    def list_text_preparations(self, request: Request, user: dict[str, Any]):
        query = str(request.query.get("q", [""])[0]).strip()[:200]
        status_filter = str(request.query.get("status", [""])[0]).strip().lower()
        if status_filter not in {"", "prepared", "applied", "archived"}:
            raise HTTPError(400, "Некорректный фильтр статуса AI-подготовки")
        limit = self.query_int(request, "limit", 50, 1, 200)
        offset = self.query_int(request, "offset", 0, 0, 1_000_000)
        escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        search = f"%{escaped_query}%"
        with connect(self.config.db_path) as conn:
            total = conn.execute(
                """
                SELECT COUNT(*)
                FROM text_preparation_items t
                LEFT JOIN data_imports d ON d.id = t.import_id AND d.user_id = t.user_id
                LEFT JOIN cases c ON c.id = d.case_id AND c.user_id = t.user_id
                WHERE t.user_id = ? AND (? = '' OR t.status = ?)
                  AND (? = '' OR t.source_label LIKE ? ESCAPE '\\'
                       OR t.corrected_text LIKE ? ESCAPE '\\'
                       OR c.title LIKE ? ESCAPE '\\'
                       OR CAST(t.id AS TEXT) LIKE ? ESCAPE '\\')
                """,
                (user["id"], status_filter, status_filter, query, search, search, search, search),
            ).fetchone()[0]
            rows = conn.execute(
                """
                SELECT t.id, t.data_preparation_request_id, t.import_id, t.status, t.source_label,
                       t.input_sha256, t.corrected_text, t.mappings_json, t.warnings_json,
                       t.mapped_fields, t.warning_count, t.created_at, t.updated_at, t.applied_at,
                       d.case_id, c.title AS case_title
                FROM text_preparation_items t
                LEFT JOIN data_imports d ON d.id = t.import_id AND d.user_id = t.user_id
                LEFT JOIN cases c ON c.id = d.case_id AND c.user_id = t.user_id
                WHERE t.user_id = ? AND (? = '' OR t.status = ?)
                  AND (? = '' OR t.source_label LIKE ? ESCAPE '\\'
                       OR t.corrected_text LIKE ? ESCAPE '\\'
                       OR c.title LIKE ? ESCAPE '\\'
                       OR CAST(t.id AS TEXT) LIKE ? ESCAPE '\\')
                ORDER BY t.created_at DESC
                LIMIT ? OFFSET ?
                """,
                (
                    user["id"], status_filter, status_filter, query, search, search, search, search,
                    limit, offset,
                ),
            ).fetchall()
        items = rows_to_dicts(rows)
        for item in items:
            item["mappings"] = json.loads(item.pop("mappings_json") or "[]")
            item["warnings"] = json.loads(item.pop("warnings_json") or "[]")
            text = item.get("corrected_text") or ""
            item["corrected_text_preview"] = text[:600]
        return self.json_response({
            "text_preparations": items,
            "total": int(total),
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(rows) < int(total),
        })

    def get_case(self, user: dict[str, Any], case_id: int):
        with connect(self.config.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM cases WHERE id = ? AND (user_id = ? OR ? = 'admin')",
                (case_id, user["id"], user["role"]),
            ).fetchone()
        case = row_to_dict(row)
        if not case:
            raise HTTPError(404, "Кейс не найден")
        case["data"] = json.loads(case.pop("data_json"))
        case["quality"] = case_quality_summary(case["data"])
        return self.json_response({"case": case})

    def save_case(self, request: Request, user: dict[str, Any]):
        self.ensure_request_size(request)
        data = request.json()
        patient_data = self.normalized_patient_data(data.get("patient_data"))
        case_id = data.get("case_id")
        title = str(data.get("title") or self.case_title(patient_data)).strip()[:200]
        patient_id = str(patient_data.get("GENERAL_INFO", {}).get("Patient_ID") or "").strip()[:120]
        now = utc_now()
        payload = json.dumps(patient_data, ensure_ascii=False)

        with connect(self.config.db_path) as conn:
            if case_id:
                row = conn.execute("SELECT id FROM cases WHERE id = ? AND user_id = ?", (case_id, user["id"])).fetchone()
                if not row:
                    raise HTTPError(404, "Кейс не найден")
                conn.execute(
                    """
                    UPDATE cases
                    SET title = ?, patient_id = ?, data_json = ?, updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (title, patient_id, payload, now, case_id, user["id"]),
                )
                saved_id = int(case_id)
                action = "case_update"
            else:
                cur = conn.execute(
                    """
                    INSERT INTO cases (user_id, title, patient_id, data_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (user["id"], title, patient_id, payload, now, now),
                )
                saved_id = int(cur.lastrowid)
                action = "case_create"
            audit(conn, user_id=user["id"], action=action, target_type="case", target_id=saved_id)

        return self.json_response({"ok": True, "case_id": saved_id, "title": title})

    def export_case_fhir(self, user: dict[str, Any], case_id: int):
        with connect(self.config.db_path) as conn:
            row = conn.execute(
                "SELECT id, title, data_json FROM cases WHERE id = ? AND (user_id = ? OR ? = 'admin')",
                (case_id, user["id"], user["role"]),
            ).fetchone()
        case = row_to_dict(row)
        if not case:
            raise HTTPError(404, "Кейс не найден")
        patient_data = json.loads(case["data_json"])
        bundle = build_fhir_bundle(patient_data, case_id=case_id, case_title=case["title"])
        return self.json_response(bundle, headers=[("Content-Disposition", f'attachment; filename="cvd_case_{case_id}_fhir.json"')])

    def delete_case(self, user: dict[str, Any], case_id: int):
        with connect(self.config.db_path) as conn:
            owned_case = conn.execute(
                "SELECT id FROM cases WHERE id = ? AND user_id = ?",
                (case_id, user["id"]),
            ).fetchone()
            if not owned_case:
                raise HTTPError(404, "Кейс не найден")
            active_batch = conn.execute(
                """
                SELECT 1
                FROM batch_job_items i
                JOIN batch_jobs j ON j.id = i.batch_job_id
                WHERE i.case_id = ? AND i.status IN ('pending', 'running')
                  AND j.status IN ('queued', 'running')
                LIMIT 1
                """,
                (case_id,),
            ).fetchone()
            if active_batch:
                raise HTTPError(409, "Кейс находится в активной пакетной обработке")
            cur = conn.execute("DELETE FROM cases WHERE id = ? AND user_id = ?", (case_id, user["id"]))
            if cur.rowcount == 0:
                raise HTTPError(404, "Кейс не найден")
            audit(conn, user_id=user["id"], action="case_delete", target_type="case", target_id=case_id)
        return self.json_response({"ok": True})

    def copy_case(self, user: dict[str, Any], case_id: int):
        with connect(self.config.db_path) as conn:
            row = conn.execute(
                "SELECT id, title, patient_id, data_json FROM cases WHERE id = ? AND user_id = ?",
                (case_id, user["id"]),
            ).fetchone()
            if not row:
                raise HTTPError(404, "Кейс не найден")
            try:
                patient_data = json.loads(row["data_json"])
            except json.JSONDecodeError as exc:
                raise HTTPError(409, "Данные исходного кейса повреждены") from exc
            patient_data["MODEL_OUTPUT"] = {}
            patient_data = self.normalized_patient_data(patient_data)
            now = utc_now()
            title = f"Копия: {row['title']}"[:200]
            cur = conn.execute(
                """
                INSERT INTO cases (user_id, title, patient_id, data_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user["id"],
                    title,
                    row["patient_id"],
                    json.dumps(patient_data, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            copied_id = int(cur.lastrowid)
            audit(
                conn,
                user_id=user["id"],
                action="case_copy",
                target_type="case",
                target_id=copied_id,
                details={"source_case_id": case_id},
            )
        return self.json_response({"ok": True, "case_id": copied_id, "title": title}, 201)

    def diagnose(self, request: Request, user: dict[str, Any]):
        settings = self.load_settings()
        self.ensure_request_size(request, settings)
        self.enforce_rate_limit(
            f"model:{user['id']}",
            limit=30,
            window_seconds=3600,
            message="Слишком много запросов к модели",
        )

        data = request.json()
        patient_data = self.normalized_patient_data(data.get("patient_data"))
        if not has_clinical_input(patient_data):
            raise HTTPError(400, "Добавьте данные пациента перед запуском AI-анализа")
        case_id = data.get("case_id")
        if case_id is not None:
            try:
                case_id = int(case_id)
            except (TypeError, ValueError):
                raise HTTPError(400, "Некорректный case_id")
        result = self.execute_model_request(
            user_id=user["id"],
            case_id=case_id,
            patient_data=patient_data,
            request_source="interactive",
            settings=settings,
        )
        if not result["ok"]:
            status = 429 if result.get("queue_error") else 502
            raise HTTPError(status, "Сервис AI временно недоступен. Подробности сохранены для администратора")
        return self.json_response(result)

    def export_html_report(self, request: Request, user: dict[str, Any]):
        settings = self.load_settings()
        self.ensure_request_size(request, settings)
        data = request.json()
        patient_data = self.normalized_patient_data(data.get("patient_data"))
        try:
            request_id = int(data.get("request_id"))
        except (TypeError, ValueError) as exc:
            raise HTTPError(400, "Некорректный request_id") from exc

        html = self.build_request_report(
            user,
            request_id,
            settings=settings,
            patient_data=patient_data,
            audit_action="html_report_export",
        )

        filename = f"cvd-report-{request_id}.html"
        return self.response(
            200,
            html.encode("utf-8"),
            [
                ("Content-Type", "text/html; charset=utf-8"),
                ("Content-Disposition", f'attachment; filename="{filename}"'),
                ("Cache-Control", "no-store"),
            ],
        )

    def view_html_report(self, user: dict[str, Any], request_id: int):
        html = self.build_request_report(
            user,
            request_id,
            settings=self.load_settings(),
            patient_data=None,
            audit_action="html_report_view",
        )
        return self.response(
            200,
            html.encode("utf-8"),
            [
                ("Content-Type", "text/html; charset=utf-8"),
                ("Content-Disposition", f'inline; filename="cvd-report-{request_id}.html"'),
                ("Cache-Control", "no-store"),
            ],
        )

    def build_request_report(
        self,
        user: dict[str, Any],
        request_id: int,
        *,
        settings: dict[str, str],
        patient_data: dict[str, Any] | None,
        audit_action: str,
    ) -> str:
        with connect(self.config.db_path) as conn:
            row = conn.execute(
                """
                SELECT r.id, r.user_id, r.case_id, r.status, r.parsed_output_json,
                       r.deidentified_input_json, r.duration_ms, r.created_at,
                       c.data_json AS case_data_json
                FROM model_requests r
                LEFT JOIN cases c ON c.id = r.case_id AND c.user_id = r.user_id
                WHERE r.id = ? AND (r.user_id = ? OR ? = 'admin')
                """,
                (request_id, user["id"], user["role"]),
            ).fetchone()
            if not row:
                raise HTTPError(404, "Результат анализа не найден")
            if row["status"] != "success" or not row["parsed_output_json"]:
                raise HTTPError(409, "Для отчёта нужен успешный структурированный результат")
            try:
                parsed_output = json.loads(row["parsed_output_json"])
                if patient_data is None:
                    case_data = json.loads(row["case_data_json"] or "{}")
                    patient_data = json.loads(row["deidentified_input_json"]) if row["deidentified_input_json"] else case_data
                    report_general = patient_data.setdefault("GENERAL_INFO", {})
                    case_general = case_data.get("GENERAL_INFO", {})
                    for key in ("Patient_ID", "Full_name"):
                        if case_general.get(key) not in (None, ""):
                            report_general[key] = case_general[key]
            except (json.JSONDecodeError, TypeError, AttributeError) as exc:
                raise HTTPError(409, "Сохранённые данные результата повреждены") from exc

            html = build_html_report(
                patient_data,
                parsed_output,
                {
                    "app_name": settings.get("app_name", "CVD Web"),
                    "organization_name": settings.get("organization_name", ""),
                    "generated_at": utc_now(),
                    "request_id": row["id"],
                    "duration_ms": row["duration_ms"],
                },
            )
            audit(
                conn,
                user_id=user["id"],
                action=audit_action,
                target_type="model_request",
                target_id=request_id,
                details={"case_id": row["case_id"]},
            )
        return html

    def execute_model_request(
        self,
        *,
        user_id: int,
        case_id: int | None,
        patient_data: dict[str, Any],
        request_source: str,
        settings: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        settings = settings or self.load_settings()
        lm_studio_api_url = settings.get("lm_studio_api_url") or self.config.lm_studio_api_url
        lm_studio_model = settings.get("lm_studio_model") or self.config.lm_studio_model
        timeout_seconds = self.setting_int(settings, "lm_studio_timeout_seconds", self.config.lm_studio_timeout_seconds)
        max_tokens = self.setting_int(settings, "lm_studio_max_tokens", self.config.lm_studio_max_tokens)
        temperature = self.setting_float(settings, "lm_studio_temperature", 0.2)
        structured_output = self.setting_bool(settings, "lm_studio_structured_output", True)
        deidentify_before_model = self.setting_bool(settings, "deidentify_before_model", True)
        queue_timeout_seconds = self.configure_inference_queue(settings)
        active_prompt_version = str(settings.get("active_prompt_version") or MODEL_PROMPT_VERSION).strip()[:120] or MODEL_PROMPT_VERSION
        active_prompt_template = str(settings.get("active_prompt_template") or "").strip()
        model_patient_data, phi_signals = deidentify_patient_data(patient_data) if deidentify_before_model else (patient_data, [])
        settings_snapshot = {
            "ai_gateway_profile": settings.get("ai_gateway_profile", "local"),
            "ai_gateway_auth_header_configured": bool(self.ai_gateway_headers(settings)),
            "lm_studio_api_url": lm_studio_api_url,
            "lm_studio_model": lm_studio_model,
            "lm_studio_timeout_seconds": timeout_seconds,
            "lm_studio_max_tokens": max_tokens,
            "lm_studio_temperature": temperature,
            "lm_studio_structured_output": structured_output,
            "deidentify_before_model": deidentify_before_model,
            "prompt_version": active_prompt_version,
            "patient_schema_version": PATIENT_SCHEMA_VERSION,
            "output_schema_version": MODEL_OUTPUT_SCHEMA_VERSION,
            "request_source": request_source,
            "lm_studio_max_concurrent": self.setting_int(settings, "lm_studio_max_concurrent", 1),
            "lm_studio_queue_timeout_seconds": queue_timeout_seconds,
        }
        request_json: dict[str, Any] | None = None
        response_payload: dict[str, Any] | None = None
        parsed: dict[str, Any] | None = None
        duration_ms = 0
        queue_wait_ms = 0
        queue_error = False
        input_data_hash = patient_data_hash(patient_data)
        status = "error"
        error = None
        try:
            queue_kind = "batch_diagnosis" if request_source == "batch" else "diagnosis"
            with self.inference_queue.acquire(
                user_id=user_id,
                kind=queue_kind,
                timeout_seconds=queue_timeout_seconds,
            ) as lease:
                queue_wait_ms = lease.wait_ms
                request_json, response_payload, parsed, duration_ms = call_lm_studio(
                    api_url=lm_studio_api_url,
                    model=lm_studio_model,
                    patient_data=model_patient_data,
                    timeout_seconds=timeout_seconds,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    prompt_template=active_prompt_template,
                    prompt_version=active_prompt_version,
                    structured_output=structured_output,
                    extra_headers=self.ai_gateway_headers(settings),
                )
            status = "success"
        except Exception as exc:
            queue_error = isinstance(exc, InferenceQueueError)
            queue_wait_ms = max(queue_wait_ms, int(getattr(exc, "wait_ms", 0) or 0))
            error = str(exc)[:4000]
            request_json = getattr(exc, "request_body", None) or request_json
            response_payload = getattr(exc, "response_payload", None) or response_payload
            duration_ms = max(duration_ms, int(getattr(exc, "duration_ms", 0) or 0))

        metrics = self.model_metrics(response_payload, duration_ms)
        with connect(self.config.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO model_requests
                  (user_id, case_id, status, api_url, model, request_json, response_json,
                   parsed_output_json, prompt_version, schema_version, output_schema_version,
                   settings_snapshot_json, deidentified_input_json, phi_signals_json,
                   error, duration_ms, prompt_tokens, completion_tokens, total_tokens,
                   tokens_per_second, finish_reason, request_source, queue_wait_ms, input_data_hash, input_patient_data_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    case_id,
                    status,
                    lm_studio_api_url,
                    lm_studio_model,
                    json.dumps(request_json or {"patient_data": model_patient_data}, ensure_ascii=False),
                    json.dumps(response_payload, ensure_ascii=False) if response_payload else None,
                    json.dumps(parsed, ensure_ascii=False) if parsed else None,
                    active_prompt_version,
                    PATIENT_SCHEMA_VERSION,
                    MODEL_OUTPUT_SCHEMA_VERSION,
                    json.dumps(settings_snapshot, ensure_ascii=False),
                    json.dumps(model_patient_data, ensure_ascii=False),
                    json.dumps(phi_signals, ensure_ascii=False),
                    error,
                    duration_ms,
                    metrics["prompt_tokens"],
                    metrics["completion_tokens"],
                    metrics["total_tokens"],
                    metrics["tokens_per_second"],
                    metrics["finish_reason"],
                    request_source,
                    queue_wait_ms,
                    input_data_hash,
                    json.dumps(patient_data, ensure_ascii=False),
                    utc_now(),
                ),
            )
            audit(
                conn,
                user_id=user_id,
                action="model_request",
                target_type="model_request",
                target_id=cur.lastrowid,
                details={
                    "status": status,
                    "case_id": case_id,
                    "phi_signals": len(phi_signals),
                    "prompt_version": active_prompt_version,
                    "completion_tokens": metrics["completion_tokens"],
                    "tokens_per_second": metrics["tokens_per_second"],
                    "request_source": request_source,
                    "queue_wait_ms": queue_wait_ms,
                },
            )
            request_id = int(cur.lastrowid)
        return {
            "ok": status == "success",
            "request_id": request_id,
            "response": response_payload,
            "parsed": parsed,
            "error": error,
            "duration_ms": duration_ms,
            "queue_wait_ms": queue_wait_ms,
            "queue_error": queue_error,
            "prompt_version": active_prompt_version,
            "schema_version": PATIENT_SCHEMA_VERSION,
            "output_schema_version": MODEL_OUTPUT_SCHEMA_VERSION,
            "phi_signals": phi_signals,
            **metrics,
        }

    def structure_text(self, request: Request, user: dict[str, Any]):
        settings = self.load_settings()
        self.ensure_request_size(request, settings)
        self.enforce_rate_limit(
            f"structure-text:{user['id']}",
            limit=30,
            window_seconds=3600,
            message="Слишком много запросов на подготовку данных",
        )
        data = request.json()
        source_text = str(data.get("text") or "").strip()
        if len(source_text) < 10:
            raise HTTPError(400, "Добавьте медицинский текст длиной не менее 10 символов")
        if len(source_text) > TEXT_MAX_INPUT_CHARS:
            raise HTTPError(413, f"Текст не должен превышать {TEXT_MAX_INPUT_CHARS:,} символов".replace(",", " "))

        api_url = settings.get("lm_studio_api_url") or self.config.lm_studio_api_url
        model = settings.get("text_structuring_model") or settings.get("lm_studio_model") or self.config.lm_studio_model
        timeout_seconds = self.setting_int(settings, "lm_studio_timeout_seconds", self.config.lm_studio_timeout_seconds)
        max_tokens = self.setting_int(settings, "lm_studio_max_tokens", self.config.lm_studio_max_tokens)
        queue_timeout_seconds = self.configure_inference_queue(settings)
        content_sha256 = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        response_payload: dict[str, Any] | None = None
        result: dict[str, Any] | None = None
        duration_ms = 0
        queue_wait_ms = 0
        queue_error = False
        error = None

        @contextmanager
        def queued_model_call():
            nonlocal queue_wait_ms
            with self.inference_queue.acquire(
                user_id=user["id"],
                kind="text_structuring",
                timeout_seconds=queue_timeout_seconds,
            ) as lease:
                queue_wait_ms += lease.wait_ms
                yield

        try:
            _, response_payload, result, duration_ms = call_text_structuring(
                api_url=api_url,
                model=model,
                text=source_text,
                timeout_seconds=timeout_seconds,
                max_tokens=max_tokens,
                call_guard=queued_model_call,
                extra_headers=self.ai_gateway_headers(settings),
            )
        except Exception as exc:
            queue_error = isinstance(exc, InferenceQueueError)
            queue_wait_ms = max(queue_wait_ms, int(getattr(exc, "wait_ms", 0) or 0))
            error = str(exc)[:4000]
            response_payload = getattr(exc, "response_payload", None) or response_payload
            duration_ms = int(getattr(exc, "duration_ms", 0) or 0)

        metrics = self.model_metrics(response_payload, duration_ms)
        chunk_count = max(1, int(response_payload.get("chunk_count") or 1)) if response_payload else 1
        failed_chunk_count = max(0, int(response_payload.get("failed_chunk_count") or 0)) if response_payload else 0
        with connect(self.config.db_path) as conn:
            prep_cur = conn.execute(
                """
                INSERT INTO data_preparation_requests
                  (user_id, status, model, input_sha256, chunk_count, mapped_fields, warning_count,
                   duration_ms, prompt_tokens, completion_tokens, total_tokens,
                   finish_reason, queue_wait_ms, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user["id"],
                    "success" if result is not None else "error",
                    model,
                    content_sha256,
                    chunk_count,
                    len(result["mappings"]) if result else 0,
                    len(result["warnings"]) if result else 0,
                    duration_ms,
                    metrics["prompt_tokens"],
                    metrics["completion_tokens"],
                    metrics["total_tokens"],
                    metrics["finish_reason"],
                    queue_wait_ms,
                    error,
                    utc_now(),
                ),
            )
            if result is not None:
                import_cur = conn.execute(
                    """
                    INSERT INTO data_imports
                      (user_id, case_id, source_format, mapping_version, filename, content_sha256,
                       mapped_fields, mapped_paths_json, warning_count, selected_paths_json, status, created_at)
                    VALUES (?, NULL, 'ai-text', ?, ?, ?, ?, ?, ?, '[]', 'previewed', ?)
                    """,
                    (
                        user["id"],
                        TEXT_STRUCTURING_VERSION,
                        "Свободный медицинский текст",
                        content_sha256,
                        len(result["mappings"]),
                        json.dumps([item["path"] for item in result["mappings"]], ensure_ascii=False),
                        len(result["warnings"]),
                        utc_now(),
                    ),
                )
                import_id = int(import_cur.lastrowid)
                now_text_item = utc_now()
                conn.execute(
                    """
                    INSERT INTO text_preparation_items
                      (data_preparation_request_id, import_id, user_id, status, source_label,
                       input_sha256, corrected_text, mappings_json, warnings_json,
                       mapped_fields, warning_count, created_at, updated_at)
                    VALUES (?, ?, ?, 'prepared', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        prep_cur.lastrowid,
                        import_id,
                        user["id"],
                        "Свободный медицинский текст",
                        content_sha256,
                        str(result.get("corrected_text") or "")[:20000],
                        json.dumps(result["mappings"], ensure_ascii=False),
                        json.dumps(result["warnings"], ensure_ascii=False),
                        len(result["mappings"]),
                        len(result["warnings"]),
                        now_text_item,
                        now_text_item,
                    ),
                )
            else:
                import_id = None
            audit(
                conn,
                user_id=user["id"],
                action="data_preparation",
                target_type="data_preparation_request",
                target_id=prep_cur.lastrowid,
                details={
                    "status": "success" if result is not None else "error",
                    "mapped_fields": len(result["mappings"]) if result else 0,
                    "chunk_count": chunk_count,
                    "duration_ms": duration_ms,
                    "queue_wait_ms": queue_wait_ms,
                    "failed_chunk_count": failed_chunk_count,
                },
            )

        if result is None:
            raise HTTPError(
                429 if queue_error else 502,
                "Сервис AI временно не смог подготовить данные. Подробности сохранены для администратора",
            )
        return self.json_response({
            "ok": True,
            "import_id": import_id,
            "source_format": "ai-text",
            "mapping_version": TEXT_STRUCTURING_VERSION,
            "filename": "AI-подготовка текста",
            "mappings": result["mappings"],
            "warnings": result["warnings"],
            "corrected_text": result["corrected_text"],
            "summary": {"mapped_fields": len(result["mappings"])},
            "chunk_count": chunk_count,
            "failed_chunk_count": failed_chunk_count,
            "duration_ms": duration_ms,
            "queue_wait_ms": queue_wait_ms,
            **metrics,
        })

    def list_requests(self, request: Request, user: dict[str, Any]):
        query = str(request.query.get("q", [""])[0]).strip()[:200]
        status_filter = str(request.query.get("status", [""])[0]).strip().lower()
        if status_filter not in {"", "success", "error"}:
            raise HTTPError(400, "Некорректный фильтр статуса результата")
        model_filter = str(request.query.get("model", [""])[0]).strip()[:200]
        review_filter = str(request.query.get("review", [""])[0]).strip().lower()
        if review_filter not in {"", "unreviewed", "useful", "partial", "wrong", "unsafe"}:
            raise HTTPError(400, "Некорректный фильтр экспертной оценки")
        red_flags_filter = str(request.query.get("red_flags", [""])[0]).strip().lower()
        if red_flags_filter not in {"", "with", "without"}:
            raise HTTPError(400, "Некорректный фильтр red flags")
        abstain_filter = str(request.query.get("abstain", [""])[0]).strip().lower()
        if abstain_filter not in {"", "yes", "no"}:
            raise HTTPError(400, "Некорректный фильтр отказа модели")
        raw_case_id = str(request.query.get("case_id", [""])[0]).strip()
        if raw_case_id:
            try:
                case_id = int(raw_case_id)
            except ValueError as exc:
                raise HTTPError(400, "Некорректный case_id") from exc
        else:
            case_id = None
        limit = self.query_int(request, "limit", 50, 1, 200)
        offset = self.query_int(request, "offset", 0, 0, 1_000_000)
        escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        search = f"%{escaped_query}%"
        with connect(self.config.db_path) as conn:
            rows = conn.execute(
                """
                SELECT r.id, r.case_id, r.status, r.model, r.error, r.duration_ms, r.created_at,
                       r.parsed_output_json, r.prompt_version, r.schema_version, r.output_schema_version,
                       r.phi_signals_json, r.prompt_tokens, r.completion_tokens, r.total_tokens,
                       r.tokens_per_second, r.finish_reason, r.request_source, r.input_data_hash,
                       r.input_patient_data_json, c.title AS case_title, c.patient_id, c.data_json AS case_data_json,
                       rv.rating AS review_rating, rv.issue_types_json AS review_issue_types_json,
                       rv.comment AS review_comment, rv.corrected_diagnosis AS review_corrected_diagnosis,
                       rv.corrected_icd10_json AS review_corrected_icd10_json
                FROM model_requests r
                LEFT JOIN cases c ON c.id = r.case_id AND c.user_id = r.user_id
                LEFT JOIN model_request_reviews rv
                  ON rv.model_request_id = r.id AND rv.reviewer_user_id = ?
                WHERE r.user_id = ? AND (? = '' OR r.status = ?)
                  AND (? = '' OR r.model = ?)
                  AND (? IS NULL OR r.case_id = ?)
                  AND (? = '' OR CAST(r.id AS TEXT) LIKE ? ESCAPE '\\'
                       OR c.title LIKE ? ESCAPE '\\' OR c.patient_id LIKE ? ESCAPE '\\'
                       OR r.parsed_output_json LIKE ? ESCAPE '\\')
                ORDER BY r.created_at DESC
                """,
                (
                    user["id"], user["id"], status_filter, status_filter, model_filter, model_filter, case_id, case_id,
                    query, search, search, search, search,
                ),
            ).fetchall()
            model_rows = conn.execute(
                "SELECT DISTINCT model FROM model_requests WHERE user_id = ? AND model <> '' ORDER BY model",
                (user["id"],),
            ).fetchall()
        items = self.serialize_request_rows(rows)
        filtered_items = [
            item for item in items
            if self.request_matches_result_filters(item, review_filter, red_flags_filter, abstain_filter)
        ]
        total = len(filtered_items)
        page_items = filtered_items[offset:offset + limit]
        return self.json_response({
            "requests": page_items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(page_items) < total,
            "filters": {"models": [row["model"] for row in model_rows]},
        })


    def request_matches_result_filters(
        self,
        item: dict[str, Any],
        review_filter: str,
        red_flags_filter: str,
        abstain_filter: str,
    ) -> bool:
        cds = (item.get("parsed_output") or {}).get("CDS_OUTPUT", {})
        red_flags = cds.get("red_flags") if isinstance(cds, dict) else []
        has_red_flags = bool(red_flags)
        abstained = bool(cds.get("model_should_abstain")) if isinstance(cds, dict) else False
        review = item.get("review")
        rating = review.get("rating") if isinstance(review, dict) else ""
        if review_filter == "unreviewed" and review:
            return False
        if review_filter and review_filter != "unreviewed" and rating != review_filter:
            return False
        if red_flags_filter == "with" and not has_red_flags:
            return False
        if red_flags_filter == "without" and has_red_flags:
            return False
        if abstain_filter == "yes" and not abstained:
            return False
        if abstain_filter == "no" and abstained:
            return False
        item["result_flags"] = {
            "red_flags_count": len(red_flags) if isinstance(red_flags, list) else 0,
            "model_should_abstain": abstained,
            "review_rating": rating or "",
        }
        return True

    def get_request_result(self, user: dict[str, Any], request_id: int):
        with connect(self.config.db_path) as conn:
            rows = conn.execute(
                """
                SELECT r.id, r.case_id, r.status, r.model, r.error, r.duration_ms, r.created_at,
                       r.parsed_output_json, r.prompt_version, r.schema_version, r.output_schema_version,
                       r.phi_signals_json, r.prompt_tokens, r.completion_tokens, r.total_tokens,
                       r.tokens_per_second, r.finish_reason, r.request_source, r.input_data_hash,
                       r.input_patient_data_json, c.title AS case_title, c.patient_id, c.data_json AS case_data_json,
                       rv.rating AS review_rating, rv.issue_types_json AS review_issue_types_json,
                       rv.comment AS review_comment, rv.corrected_diagnosis AS review_corrected_diagnosis,
                       rv.corrected_icd10_json AS review_corrected_icd10_json
                FROM model_requests r
                LEFT JOIN cases c ON c.id = r.case_id AND c.user_id = r.user_id
                LEFT JOIN model_request_reviews rv
                  ON rv.model_request_id = r.id AND rv.reviewer_user_id = ?
                WHERE r.id = ? AND r.user_id = ?
                """,
                (user["id"], request_id, user["id"]),
            ).fetchall()
        if not rows:
            raise HTTPError(404, "Результат анализа не найден")
        return self.json_response({"request": self.serialize_request_rows(rows)[0]})

    def serialize_request_rows(self, rows) -> list[dict[str, Any]]:
        items = rows_to_dicts(rows)
        for item in items:
            case_data_json = item.pop("case_data_json", None)
            input_patient_data_json = item.pop("input_patient_data_json", None)
            item["ai_result_stale"] = False
            item["ai_result_changes"] = []
            if case_data_json and item.get("input_data_hash"):
                try:
                    current_data = json.loads(case_data_json)
                    item["ai_result_stale"] = patient_data_hash(current_data) != item["input_data_hash"]
                    if item["ai_result_stale"] and input_patient_data_json:
                        item["ai_result_changes"] = patient_data_changes(json.loads(input_patient_data_json), current_data)
                except (json.JSONDecodeError, TypeError):
                    item["ai_result_stale"] = True
            item["parsed_output"] = json.loads(item.pop("parsed_output_json")) if item.get("parsed_output_json") else None
            item["phi_signals"] = json.loads(item.pop("phi_signals_json")) if item.get("phi_signals_json") else []
            review_rating = item.pop("review_rating")
            review_issue_types_json = item.pop("review_issue_types_json")
            review_comment = item.pop("review_comment")
            review_corrected_diagnosis = item.pop("review_corrected_diagnosis")
            review_corrected_icd10_json = item.pop("review_corrected_icd10_json")
            item["review"] = {
                "rating": review_rating,
                "issue_types": json.loads(review_issue_types_json) if review_issue_types_json else [],
                "comment": review_comment,
                "corrected_diagnosis": review_corrected_diagnosis,
                "corrected_icd10": json.loads(review_corrected_icd10_json) if review_corrected_icd10_json else [],
            } if review_rating else None
        return items

    def review_model_request(self, request: Request, user: dict[str, Any], request_id: int):
        data = request.json()
        rating = str(data.get("rating", "")).strip()
        if rating not in {"useful", "partial", "wrong", "unsafe"}:
            raise HTTPError(400, "Некорректная оценка")
        issue_types = data.get("issue_types") or []
        if not isinstance(issue_types, list):
            raise HTTPError(400, "issue_types должен быть списком")
        issue_types = [str(item).strip()[:80] for item in issue_types if str(item).strip()]
        corrected_diagnosis = str(data.get("corrected_diagnosis", "")).strip()[:2000]
        corrected_icd10 = data.get("corrected_icd10") or []
        if isinstance(corrected_icd10, str):
            corrected_icd10 = [item.strip().upper() for item in re.split(r"[,;]+", corrected_icd10) if item.strip()]
        if not isinstance(corrected_icd10, list):
            raise HTTPError(400, "corrected_icd10 должен быть списком")
        corrected_icd10 = [str(item).strip().upper()[:20] for item in corrected_icd10 if str(item).strip()]
        comment = str(data.get("comment", "")).strip()[:4000]
        now = utc_now()

        with connect(self.config.db_path) as conn:
            row = conn.execute(
                "SELECT id, case_id, user_id FROM model_requests WHERE id = ? AND (user_id = ? OR ? = 'admin')",
                (request_id, user["id"], user["role"]),
            ).fetchone()
            if not row:
                raise HTTPError(404, "Запрос модели не найден")
            conn.execute(
                """
                INSERT INTO model_request_reviews
                  (model_request_id, case_id, reviewer_user_id, rating, issue_types_json,
                   corrected_diagnosis, corrected_icd10_json, comment, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(model_request_id, reviewer_user_id) DO UPDATE SET
                  rating = excluded.rating,
                  issue_types_json = excluded.issue_types_json,
                  corrected_diagnosis = excluded.corrected_diagnosis,
                  corrected_icd10_json = excluded.corrected_icd10_json,
                  comment = excluded.comment,
                  updated_at = excluded.updated_at
                """,
                (
                    request_id,
                    row["case_id"],
                    user["id"],
                    rating,
                    json.dumps(issue_types, ensure_ascii=False),
                    corrected_diagnosis,
                    json.dumps(corrected_icd10, ensure_ascii=False),
                    comment,
                    now,
                    now,
                ),
            )
            audit(
                conn,
                user_id=user["id"],
                action="model_request_review",
                target_type="model_request",
                target_id=request_id,
                details={"rating": rating, "issue_types": issue_types},
            )
        return self.json_response({"ok": True})

    def admin_list_users(self):
        with connect(self.config.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, email, full_name, role, is_active, must_change_password,
                       created_at, updated_at, last_login_at
                FROM users
                ORDER BY created_at DESC
                """
            ).fetchall()
        return self.json_response({"users": rows_to_dicts(rows)})

    def admin_create_user(self, request: Request, admin: dict[str, Any]):
        data = request.json()
        email = str(data.get("email", "")).strip().lower()
        full_name = str(data.get("full_name", "")).strip()
        password = str(data.get("password", ""))
        role = str(data.get("role", "user")).strip()
        if not email or "@" not in email:
            raise HTTPError(400, "Некорректный email")
        if role not in {"admin", "user"}:
            raise HTTPError(400, "Некорректная роль")
        self.validate_new_password(password, email=email)
        now = utc_now()
        try:
            with connect(self.config.db_path) as conn:
                cur = conn.execute(
                    """
                    INSERT INTO users
                      (email, full_name, password_hash, role, is_active, must_change_password, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 1, 1, ?, ?)
                    """,
                    (email, full_name, hash_password(password), role, now, now),
                )
                audit(conn, user_id=admin["id"], action="user_create", target_type="user", target_id=cur.lastrowid, details={"email": email, "role": role})
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise HTTPError(409, "Пользователь с таким email уже существует")
            raise
        return self.json_response({"ok": True})

    def admin_update_user(self, request: Request, admin: dict[str, Any], user_id: int):
        data = request.json()
        role = str(data.get("role", "user")).strip()
        full_name = str(data.get("full_name", "")).strip()
        is_active = 1 if bool(data.get("is_active", True)) else 0
        if role not in {"admin", "user"}:
            raise HTTPError(400, "Некорректная роль")
        if user_id == admin["id"] and is_active == 0:
            raise HTTPError(400, "Нельзя отключить собственную учетную запись")

        with connect(self.config.db_path) as conn:
            existing = conn.execute("SELECT role, is_active FROM users WHERE id = ?", (user_id,)).fetchone()
            if not existing:
                raise HTTPError(404, "Пользователь не найден")
            removes_active_admin = existing["role"] == "admin" and existing["is_active"] == 1 and (role != "admin" or is_active == 0)
            if removes_active_admin:
                other_admins = conn.execute(
                    "SELECT COUNT(*) AS c FROM users WHERE id <> ? AND role = 'admin' AND is_active = 1",
                    (user_id,),
                ).fetchone()["c"]
                if other_admins == 0:
                    raise HTTPError(400, "Нельзя убрать последнего активного администратора")
            cur = conn.execute(
                "UPDATE users SET full_name = ?, role = ?, is_active = ?, updated_at = ? WHERE id = ?",
                (full_name, role, is_active, utc_now(), user_id),
            )
            audit(conn, user_id=admin["id"], action="user_update", target_type="user", target_id=user_id, details={"role": role, "is_active": is_active})
        return self.json_response({"ok": True})

    def admin_reset_password(self, request: Request, admin: dict[str, Any], user_id: int):
        data = request.json()
        password = str(data.get("password", ""))
        self.validate_new_password(password)
        with connect(self.config.db_path) as conn:
            cur = conn.execute(
                "UPDATE users SET password_hash = ?, must_change_password = 1, updated_at = ? WHERE id = ?",
                (hash_password(password), utc_now(), user_id),
            )
            if cur.rowcount == 0:
                raise HTTPError(404, "Пользователь не найден")
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            audit(conn, user_id=admin["id"], action="user_password_reset", target_type="user", target_id=user_id)
        return self.json_response({"ok": True})

    def admin_list_requests(self, request: Request):
        limit = self.query_int(request, "limit", 100, 1, 500)
        with connect(self.config.db_path) as conn:
            rows = conn.execute(
                """
                SELECT r.id, r.user_id, u.email, r.case_id, r.status, r.api_url, r.model,
                       r.error, r.duration_ms, r.created_at, r.parsed_output_json,
                       r.prompt_version, r.schema_version, r.output_schema_version, r.phi_signals_json,
                       r.prompt_tokens, r.completion_tokens, r.total_tokens,
                       r.tokens_per_second, r.finish_reason, r.request_source,
                       COUNT(rv.id) AS review_count
                FROM model_requests r
                JOIN users u ON u.id = r.user_id
                LEFT JOIN model_request_reviews rv ON rv.model_request_id = r.id
                GROUP BY r.id
                ORDER BY r.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        items = rows_to_dicts(rows)
        for item in items:
            item["parsed_output"] = json.loads(item.pop("parsed_output_json")) if item.get("parsed_output_json") else None
            item["phi_signals"] = json.loads(item.pop("phi_signals_json")) if item.get("phi_signals_json") else []
        return self.json_response({"requests": items})

    def admin_list_reviews(self, request: Request):
        limit = self.query_int(request, "limit", 100, 1, 500)
        with connect(self.config.db_path) as conn:
            rows = conn.execute(
                """
                SELECT rv.id, rv.model_request_id, rv.case_id, rv.rating, rv.issue_types_json,
                       rv.corrected_diagnosis, rv.corrected_icd10_json, rv.comment,
                       rv.created_at, rv.updated_at, u.email AS reviewer_email,
                       r.model, r.prompt_version
                FROM model_request_reviews rv
                JOIN users u ON u.id = rv.reviewer_user_id
                JOIN model_requests r ON r.id = rv.model_request_id
                ORDER BY rv.updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        items = rows_to_dicts(rows)
        for item in items:
            item["issue_types"] = json.loads(item.pop("issue_types_json")) if item.get("issue_types_json") else []
            item["corrected_icd10"] = json.loads(item.pop("corrected_icd10_json")) if item.get("corrected_icd10_json") else []
        return self.json_response({"reviews": items})

    def admin_list_audit(self, request: Request):
        limit = self.query_int(request, "limit", 100, 1, 500)
        with connect(self.config.db_path) as conn:
            rows = conn.execute(
                """
                SELECT a.id, a.user_id, u.email, a.action, a.target_type, a.target_id,
                       a.details_json, a.created_at
                FROM audit_log a
                LEFT JOIN users u ON u.id = a.user_id
                ORDER BY a.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        items = rows_to_dicts(rows)
        for item in items:
            item["details"] = json.loads(item.pop("details_json")) if item.get("details_json") else {}
        return self.json_response({"audit": items})


    def backup_dir(self) -> Path:
        path = self.config.db_path.parent / "backups"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def backup_path(self, filename: str) -> Path:
        if not re.fullmatch(r"cvd-[0-9TZ-]+\.sqlite3", filename):
            raise HTTPError(400, "Некорректное имя backup-файла")
        path = (self.backup_dir() / filename).resolve()
        if not str(path).startswith(str(self.backup_dir().resolve())) or not path.is_file():
            raise HTTPError(404, "Backup не найден")
        return path

    def admin_list_backups(self):
        backups = []
        for path in sorted(self.backup_dir().glob("cvd-*.sqlite3"), key=lambda item: item.stat().st_mtime, reverse=True):
            stat = path.stat()
            backups.append({"filename": path.name, "size_bytes": stat.st_size, "created_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()})
        return self.json_response({"backups": backups[:100]})

    def admin_create_backup(self, admin: dict[str, Any]):
        filename = f"cvd-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.sqlite3"
        target = self.backup_dir() / filename
        with sqlite3.connect(self.config.db_path) as source, sqlite3.connect(target) as dest:
            source.backup(dest)
        with connect(self.config.db_path) as conn:
            audit(conn, user_id=admin["id"], action="backup_create", target_type="backup", details={"filename": filename})
        return self.json_response({"ok": True, "backup": {"filename": filename, "size_bytes": target.stat().st_size}}, status=201)

    def admin_download_backup(self, filename: str):
        path = self.backup_path(filename)
        return self.response(200, path.read_bytes(), [
            ("Content-Type", "application/octet-stream"),
            ("Content-Disposition", f'attachment; filename="{path.name}"'),
        ])

    def admin_restore_backup(self, request: Request, admin: dict[str, Any]):
        data = request.json()
        filename = str(data.get("filename") or "").strip()
        source_path = self.backup_path(filename)
        with sqlite3.connect(source_path) as source:
            integrity = source.execute("PRAGMA quick_check").fetchone()[0]
            if integrity != "ok":
                raise HTTPError(400, f"Backup повреждён: {integrity}")
        safety_name = f"cvd-before-restore-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.sqlite3"
        safety_path = self.backup_dir() / safety_name
        with sqlite3.connect(self.config.db_path) as current, sqlite3.connect(safety_path) as safety:
            current.backup(safety)
        with sqlite3.connect(source_path) as source, sqlite3.connect(self.config.db_path) as dest:
            source.backup(dest)
        with connect(self.config.db_path) as conn:
            audit(conn, user_id=admin["id"], action="backup_restore", target_type="backup", details={"filename": filename, "safety_backup": safety_name})
        return self.json_response({"ok": True, "restored_from": filename, "safety_backup": safety_name})

    def admin_get_settings(self):
        with connect(self.config.db_path) as conn:
            items = get_app_settings_full(conn)
        return self.json_response({"settings": items})

    def admin_update_settings(self, request: Request, admin: dict[str, Any]):
        data = request.json()
        incoming = data.get("settings")
        if not isinstance(incoming, dict):
            raise HTTPError(400, "settings должен быть объектом")

        values = {
            "app_name": str(incoming.get("app_name", "")).strip()[:80],
            "organization_name": str(incoming.get("organization_name", "")).strip()[:120],
            "system_description": str(incoming.get("system_description", "")).strip()[:1000],
            "usage_notice": str(incoming.get("usage_notice", "")).strip()[:1000],
            "support_contact": str(incoming.get("support_contact", "")).strip()[:200],
            "default_theme": str(incoming.get("default_theme", "light")).strip(),
            "ai_gateway_profile": str(incoming.get("ai_gateway_profile", "local")).strip().lower(),
            "ai_gateway_auth_header_name": str(incoming.get("ai_gateway_auth_header_name", "")).strip()[:80],
            "ai_gateway_auth_header_value": str(incoming.get("ai_gateway_auth_header_value", "")).strip()[:4000],
            "lm_studio_api_url": str(incoming.get("lm_studio_api_url", "")).strip(),
            "lm_studio_model": str(incoming.get("lm_studio_model", "")).strip()[:160],
            "text_structuring_model": str(incoming.get("text_structuring_model", "")).strip()[:160],
            "lm_studio_timeout_seconds": str(incoming.get("lm_studio_timeout_seconds", "")).strip(),
            "lm_studio_max_tokens": str(incoming.get("lm_studio_max_tokens", "")).strip(),
            "lm_studio_temperature": str(incoming.get("lm_studio_temperature", "0.2")).strip(),
            "lm_studio_structured_output": "1" if str(incoming.get("lm_studio_structured_output", "1")).strip().lower() in {"1", "true", "yes", "on"} else "0",
            "lm_studio_max_concurrent": str(incoming.get("lm_studio_max_concurrent", "1")).strip(),
            "lm_studio_queue_limit": str(incoming.get("lm_studio_queue_limit", "64")).strip(),
            "lm_studio_per_user_limit": str(incoming.get("lm_studio_per_user_limit", "2")).strip(),
            "lm_studio_queue_timeout_seconds": str(incoming.get("lm_studio_queue_timeout_seconds", "1800")).strip(),
            "inference_queue_backend": str(incoming.get("inference_queue_backend", "memory")).strip().lower(),
            "inference_queue_dsn": str(incoming.get("inference_queue_dsn", "")).strip()[:1000],
            "deidentify_before_model": "1" if str(incoming.get("deidentify_before_model", "1")).strip().lower() in {"1", "true", "yes", "on"} else "0",
            "active_prompt_version": str(incoming.get("active_prompt_version", MODEL_PROMPT_VERSION)).strip()[:120],
            "active_prompt_template": str(incoming.get("active_prompt_template", "")).strip()[:12000],
            "max_request_bytes": str(incoming.get("max_request_bytes", "")).strip(),
        }

        if not values["app_name"]:
            raise HTTPError(400, "Название приложения не может быть пустым")
        if values["default_theme"] not in {"light", "dark"}:
            raise HTTPError(400, "Тема по умолчанию должна быть light или dark")
        if values["ai_gateway_profile"] not in {"local", "lan", "wsl2", "cloudflared"}:
            raise HTTPError(400, "AI Gateway профиль должен быть local, lan, wsl2 или cloudflared")
        if values["inference_queue_backend"] not in {"memory", "redis", "postgresql"}:
            raise HTTPError(400, "inference_queue_backend должен быть memory, redis или postgresql")
        if values["inference_queue_backend"] != "memory" and not values["inference_queue_dsn"]:
            raise HTTPError(400, "Для Redis/PostgreSQL очереди укажите inference_queue_dsn")
        self.ai_gateway_headers(values)
        if not values["lm_studio_api_url"].startswith(("http://", "https://")):
            raise HTTPError(400, "API URL должен начинаться с http:// или https://")
        if not values["lm_studio_model"]:
            raise HTTPError(400, "Имя модели не может быть пустым")
        if not values["active_prompt_version"]:
            raise HTTPError(400, "Версия prompt не может быть пустой")
        if "{{PATIENT_JSON}}" not in values["active_prompt_template"]:
            raise HTTPError(400, "Prompt template должен содержать {{PATIENT_JSON}}")

        ranges = {
            "lm_studio_timeout_seconds": (5, 1800),
            "lm_studio_max_tokens": (1024, 32768),
            "lm_studio_max_concurrent": (1, 8),
            "lm_studio_queue_limit": (1, 500),
            "lm_studio_per_user_limit": (1, 10),
            "lm_studio_queue_timeout_seconds": (30, 7200),
            "max_request_bytes": (1024, 20 * 1024 * 1024),
        }
        for key, (min_value, max_value) in ranges.items():
            try:
                parsed = int(values[key])
            except ValueError as exc:
                raise HTTPError(400, f"{key} должен быть целым числом") from exc
            if parsed < min_value or parsed > max_value:
                raise HTTPError(400, f"{key} должен быть в диапазоне {min_value}-{max_value}")
            values[key] = str(parsed)

        try:
            temperature = float(values["lm_studio_temperature"].replace(",", "."))
        except ValueError as exc:
            raise HTTPError(400, "lm_studio_temperature должен быть числом") from exc
        if temperature < 0 or temperature > 2:
            raise HTTPError(400, "lm_studio_temperature должен быть в диапазоне 0-2")
        values["lm_studio_temperature"] = str(temperature)

        with connect(self.config.db_path) as conn:
            update_app_settings(conn, values)
            audit(conn, user_id=admin["id"], action="settings_update", target_type="app_settings")
        self.configure_inference_queue(values)
        return self.json_response({"ok": True})

    def recover_interrupted_batch_jobs(self) -> None:
        with connect(self.config.db_path) as conn:
            conn.execute(
                "UPDATE batch_job_items SET status = 'pending', started_at = NULL WHERE status = 'running'"
            )
            conn.execute(
                "UPDATE batch_jobs SET status = 'queued', started_at = NULL WHERE status = 'running'"
            )

    def batch_worker_loop(self) -> None:
        while True:
            try:
                processed = self.process_next_batch_item()
            except Exception:
                traceback.print_exc()
                processed = False
            if not processed:
                self.batch_worker_event.wait(2.0)
                self.batch_worker_event.clear()

    def process_next_batch_item(self) -> bool:
        now = utc_now()
        with connect(self.config.db_path) as conn:
            item = conn.execute(
                """
                SELECT i.id, i.batch_job_id, i.case_id, c.user_id, c.data_json
                FROM batch_job_items i
                JOIN batch_jobs j ON j.id = i.batch_job_id
                JOIN cases c ON c.id = i.case_id
                WHERE i.status = 'pending' AND j.status IN ('queued', 'running')
                ORDER BY j.created_at, i.id
                LIMIT 1
                """
            ).fetchone()
            if not item:
                return False
            claimed = conn.execute(
                "UPDATE batch_job_items SET status = 'running', started_at = ? WHERE id = ? AND status = 'pending'",
                (now, item["id"]),
            )
            if claimed.rowcount == 0:
                return True
            conn.execute(
                "UPDATE batch_jobs SET status = 'running', started_at = COALESCE(started_at, ?) WHERE id = ? AND status = 'queued'",
                (now, item["batch_job_id"]),
            )
            item_data = row_to_dict(item)

        request_id = None
        error = None
        try:
            patient_data = json.loads(item_data["data_json"])
            result = self.execute_model_request(
                user_id=item_data["user_id"],
                case_id=item_data["case_id"],
                patient_data=patient_data,
                request_source="batch",
            )
            request_id = result["request_id"]
            item_status = "success" if result["ok"] else "error"
            error = result.get("error")
        except Exception as exc:
            item_status = "error"
            error = str(exc)[:4000]

        with connect(self.config.db_path) as conn:
            job_status = conn.execute(
                "SELECT status FROM batch_jobs WHERE id = ?",
                (item_data["batch_job_id"],),
            ).fetchone()
            if not job_status:
                return True
            conn.execute(
                """
                UPDATE batch_job_items
                SET status = ?, model_request_id = ?, error = ?, finished_at = ?
                WHERE id = ?
                """,
                (item_status, request_id, error, utc_now(), item_data["id"]),
            )
            counts = conn.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status IN ('success', 'error', 'cancelled') THEN 1 ELSE 0 END) AS completed,
                       SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success,
                       SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors,
                       SUM(CASE WHEN status IN ('pending', 'running') THEN 1 ELSE 0 END) AS remaining
                FROM batch_job_items WHERE batch_job_id = ?
                """,
                (item_data["batch_job_id"],),
            ).fetchone()
            completed = int(counts["completed"] or 0)
            success = int(counts["success"] or 0)
            errors = int(counts["errors"] or 0)
            remaining = int(counts["remaining"] or 0)
            if job_status["status"] == "cancelled":
                next_status = "cancelled"
                finished_at = utc_now()
            elif remaining:
                next_status = "running"
                finished_at = None
            else:
                next_status = "completed" if errors == 0 else "failed" if success == 0 else "partial"
                finished_at = utc_now()
            conn.execute(
                """
                UPDATE batch_jobs
                SET status = ?, completed_items = ?, success_items = ?, error_items = ?,
                    finished_at = COALESCE(?, finished_at)
                WHERE id = ?
                """,
                (next_status, completed, success, errors, finished_at, item_data["batch_job_id"]),
            )
        return True

    def admin_batch_cases(self):
        with connect(self.config.db_path) as conn:
            rows = conn.execute(
                """
                SELECT c.id, c.title, c.patient_id, c.updated_at, u.email,
                       (SELECT COUNT(*) FROM model_requests r WHERE r.case_id = c.id) AS request_count,
                       (SELECT COUNT(*) FROM model_requests r WHERE r.case_id = c.id AND r.status = 'success') AS success_count,
                       (SELECT MAX(r.created_at) FROM model_requests r WHERE r.case_id = c.id) AS last_request_at,
                       (SELECT COUNT(*)
                        FROM batch_job_items i
                        JOIN batch_jobs j ON j.id = i.batch_job_id
                        WHERE i.case_id = c.id AND i.status IN ('pending', 'running')
                          AND j.status IN ('queued', 'running')) AS active_job_count
                FROM cases c
                JOIN users u ON u.id = c.user_id
                ORDER BY c.updated_at DESC
                LIMIT 1000
                """
            ).fetchall()
        return self.json_response({"cases": rows_to_dicts(rows)})

    def admin_create_batch_job(self, request: Request, admin: dict[str, Any]):
        data = request.json()
        raw_ids = data.get("case_ids")
        if not isinstance(raw_ids, list):
            raise HTTPError(400, "case_ids должен быть списком")
        try:
            case_ids = list(dict.fromkeys(int(value) for value in raw_ids))
        except (TypeError, ValueError) as exc:
            raise HTTPError(400, "case_ids содержит некорректный ID") from exc
        if not case_ids:
            raise HTTPError(400, "Выберите хотя бы один кейс")
        if len(case_ids) > 100:
            raise HTTPError(400, "За один запуск можно обработать не более 100 кейсов")

        placeholders = ",".join("?" for _ in case_ids)
        with connect(self.config.db_path) as conn:
            existing = {
                row["id"]
                for row in conn.execute(f"SELECT id FROM cases WHERE id IN ({placeholders})", case_ids).fetchall()
            }
            missing = [case_id for case_id in case_ids if case_id not in existing]
            if missing:
                raise HTTPError(400, f"Кейсы не найдены: {', '.join(map(str, missing[:10]))}")
            active_rows = conn.execute(
                f"""
                SELECT DISTINCT i.case_id
                FROM batch_job_items i
                JOIN batch_jobs j ON j.id = i.batch_job_id
                WHERE i.case_id IN ({placeholders})
                  AND i.status IN ('pending', 'running')
                  AND j.status IN ('queued', 'running')
                """,
                case_ids,
            ).fetchall()
            active_ids = [row["case_id"] for row in active_rows]
            if active_ids:
                raise HTTPError(409, f"Кейсы уже находятся в очереди: {', '.join(map(str, active_ids[:10]))}")
            now = utc_now()
            cur = conn.execute(
                """
                INSERT INTO batch_jobs
                  (created_by_user_id, status, total_items, created_at)
                VALUES (?, 'queued', ?, ?)
                """,
                (admin["id"], len(case_ids), now),
            )
            job_id = int(cur.lastrowid)
            conn.executemany(
                "INSERT INTO batch_job_items (batch_job_id, case_id, status) VALUES (?, ?, 'pending')",
                [(job_id, case_id) for case_id in case_ids],
            )
            audit(
                conn,
                user_id=admin["id"],
                action="batch_job_create",
                target_type="batch_job",
                target_id=job_id,
                details={"case_ids": case_ids, "total_items": len(case_ids)},
            )
        self.batch_worker_event.set()
        return self.json_response({"ok": True, "job_id": job_id}, status=201)

    def admin_batch_jobs(self):
        with connect(self.config.db_path) as conn:
            rows = conn.execute(
                """
                SELECT j.*, u.email AS created_by_email
                FROM batch_jobs j
                LEFT JOIN users u ON u.id = j.created_by_user_id
                ORDER BY j.created_at DESC
                LIMIT 100
                """
            ).fetchall()
        return self.json_response({"jobs": [self.serialize_batch_job(row) for row in rows]})

    def admin_batch_job(self, job_id: int):
        with connect(self.config.db_path) as conn:
            job = conn.execute(
                """
                SELECT j.*, u.email AS created_by_email
                FROM batch_jobs j LEFT JOIN users u ON u.id = j.created_by_user_id
                WHERE j.id = ?
                """,
                (job_id,),
            ).fetchone()
            if not job:
                raise HTTPError(404, "Пакетное задание не найдено")
            items = conn.execute(
                """
                SELECT i.*, c.title, c.patient_id, u.email AS owner_email
                FROM batch_job_items i
                JOIN cases c ON c.id = i.case_id
                JOIN users u ON u.id = c.user_id
                WHERE i.batch_job_id = ?
                ORDER BY i.id
                """,
                (job_id,),
            ).fetchall()
        return self.json_response({"job": self.serialize_batch_job(job), "items": rows_to_dicts(items)})

    def serialize_batch_job(self, row) -> dict[str, Any]:
        item = row_to_dict(row)
        total = int(item.get("total_items") or 0)
        completed = int(item.get("completed_items") or 0)
        remaining = max(0, total - completed)
        started_at = self.parse_datetime(item.get("started_at") or item.get("created_at"))
        finished_at = self.parse_datetime(item.get("finished_at"))
        now = finished_at or datetime.now(timezone.utc)
        elapsed_seconds = max(0, round((now - started_at).total_seconds())) if started_at else 0
        avg_seconds_per_item = round(elapsed_seconds / completed, 1) if completed else 0
        eta_seconds = round(avg_seconds_per_item * remaining) if avg_seconds_per_item and item.get("status") in {"queued", "running"} else 0
        throughput_per_hour = round(completed * 3600 / elapsed_seconds, 1) if elapsed_seconds and completed else 0
        progress_percent = round(completed * 100 / total) if total else 0
        item["progress"] = {
            "progress_percent": progress_percent,
            "remaining_items": remaining,
            "elapsed_seconds": elapsed_seconds,
            "avg_seconds_per_item": avg_seconds_per_item,
            "eta_seconds": eta_seconds,
            "throughput_per_hour": throughput_per_hour,
        }
        return item

    def parse_datetime(self, value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def admin_cancel_batch_job(self, admin: dict[str, Any], job_id: int):
        with connect(self.config.db_path) as conn:
            job = conn.execute("SELECT status FROM batch_jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                raise HTTPError(404, "Пакетное задание не найдено")
            if job["status"] not in {"queued", "running"}:
                raise HTTPError(409, "Задание уже завершено")
            now = utc_now()
            conn.execute(
                "UPDATE batch_job_items SET status = 'cancelled', finished_at = ? WHERE batch_job_id = ? AND status = 'pending'",
                (now, job_id),
            )
            conn.execute(
                """
                UPDATE batch_jobs
                SET status = 'cancelled',
                    completed_items = (SELECT COUNT(*) FROM batch_job_items WHERE batch_job_id = ? AND status IN ('success', 'error', 'cancelled')),
                    success_items = (SELECT COUNT(*) FROM batch_job_items WHERE batch_job_id = ? AND status = 'success'),
                    error_items = (SELECT COUNT(*) FROM batch_job_items WHERE batch_job_id = ? AND status = 'error'),
                    finished_at = ?
                WHERE id = ?
                """,
                (job_id, job_id, job_id, now, job_id),
            )
            audit(conn, user_id=admin["id"], action="batch_job_cancel", target_type="batch_job", target_id=job_id)
        return self.json_response({"ok": True})

    def admin_dashboard(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        since_24h = (now - timedelta(hours=24)).isoformat()
        since_7d = (now - timedelta(days=7)).isoformat()
        settings = self.load_settings()
        self.configure_inference_queue(settings)
        with connect(self.config.db_path) as conn:
            users = row_to_dict(conn.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) AS active,
                       SUM(CASE WHEN role = 'admin' THEN 1 ELSE 0 END) AS admins,
                       SUM(CASE WHEN last_login_at >= ? THEN 1 ELSE 0 END) AS active_24h
                FROM users
                """,
                (since_24h,),
            ).fetchone())
            cases = row_to_dict(conn.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS created_24h,
                       SUM(CASE WHEN updated_at >= ? THEN 1 ELSE 0 END) AS updated_7d
                FROM cases
                """,
                (since_24h, since_7d),
            ).fetchone())
            model = row_to_dict(conn.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS requests_24h,
                       SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS requests_7d,
                       SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success,
                       SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors,
                       ROUND(AVG(CASE WHEN status = 'success' THEN duration_ms END)) AS avg_duration_ms,
                       ROUND(AVG(queue_wait_ms)) AS avg_queue_wait_ms,
                       MAX(queue_wait_ms) AS max_queue_wait_ms,
                       ROUND(AVG(CASE WHEN status = 'success' THEN tokens_per_second END), 2) AS avg_tokens_per_second,
                       SUM(total_tokens) AS total_tokens,
                       MAX(CASE WHEN status = 'success' THEN created_at END) AS last_success_at,
                       MAX(CASE WHEN status = 'error' THEN created_at END) AS last_error_at
                FROM model_requests
                """,
                (since_24h, since_7d),
            ).fetchone())
            durations = [
                row["duration_ms"]
                for row in conn.execute(
                    "SELECT duration_ms FROM model_requests WHERE status = 'success' AND created_at >= ? ORDER BY duration_ms",
                    (since_7d,),
                ).fetchall()
            ]
            imports = row_to_dict(conn.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status = 'applied' THEN 1 ELSE 0 END) AS applied,
                       SUM(warning_count) AS warnings
                FROM data_imports
                """
            ).fetchone())
            preparations = row_to_dict(conn.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success,
                       SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors,
                       SUM(mapped_fields) AS mapped_fields,
                       ROUND(AVG(queue_wait_ms)) AS avg_queue_wait_ms
                FROM data_preparation_requests
                """
            ).fetchone())
            reviews = row_to_dict(conn.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN rating = 'useful' THEN 1 ELSE 0 END) AS useful,
                       SUM(CASE WHEN rating = 'unsafe' THEN 1 ELSE 0 END) AS unsafe
                FROM model_request_reviews
                """
            ).fetchone())
            batch = row_to_dict(conn.execute(
                """
                SELECT COUNT(*) AS total_jobs,
                       SUM(CASE WHEN status IN ('queued', 'running') THEN 1 ELSE 0 END) AS active_jobs,
                       SUM(total_items) AS total_items,
                       SUM(success_items) AS success_items,
                       SUM(error_items) AS error_items
                FROM batch_jobs
                """
            ).fetchone())
            daily_rows = conn.execute(
                """
                SELECT substr(created_at, 1, 10) AS day,
                       COUNT(*) AS requests,
                       SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors
                FROM model_requests
                WHERE created_at >= ?
                GROUP BY substr(created_at, 1, 10)
                """,
                (since_7d,),
            ).fetchall()
            quality_rows = conn.execute("SELECT data_json FROM cases ORDER BY updated_at DESC LIMIT 1000").fetchall()
            integrity = conn.execute("PRAGMA quick_check").fetchone()[0]

        completeness = []
        readiness = []
        signal_count = 0
        for row in quality_rows:
            quality = case_quality_summary(json.loads(row["data_json"]))
            completeness.append(quality["completeness_percent"])
            readiness.append(quality["readiness_percent"])
            signal_count += len(quality["signals"])
        quality_summary = {
            "avg_completeness_percent": round(sum(completeness) / len(completeness)) if completeness else 0,
            "avg_readiness_percent": round(sum(readiness) / len(readiness)) if readiness else 0,
            "signals": signal_count,
        }
        model_total = int(model.get("total") or 0)
        model_success = int(model.get("success") or 0)
        model["success_rate_percent"] = round(model_success * 100 / model_total, 1) if model_total else 0
        p95_index = max(0, ((95 * len(durations) + 99) // 100) - 1) if durations else 0
        model["p95_duration_ms"] = durations[p95_index] if durations else 0
        daily_map = {row["day"]: row_to_dict(row) for row in daily_rows}
        daily = []
        for offset in range(6, -1, -1):
            day = (now - timedelta(days=offset)).date().isoformat()
            item = daily_map.get(day) or {"day": day, "requests": 0, "errors": 0}
            daily.append(item)
        try:
            db_size_bytes = self.config.db_path.stat().st_size
        except OSError:
            db_size_bytes = 0
        uptime_seconds = max(0, int((now - self.started_at).total_seconds()))
        return self.json_response({
            "generated_at": now.isoformat(),
            "users": users,
            "cases": cases,
            "model": model,
            "quality": quality_summary,
            "imports": imports,
            "preparations": preparations,
            "reviews": reviews,
            "batch": batch,
            "inference_queue": self.inference_queue.snapshot(),
            "production_queue": self.production_queue_status(settings),
            "daily": daily,
            "system": {
                "app_version": APP_VERSION,
                "uptime_seconds": uptime_seconds,
                "db_integrity": integrity,
                "db_size_bytes": db_size_bytes,
                "worker_running": bool(self.batch_worker_thread and self.batch_worker_thread.is_alive()),
            },
        })

    def admin_stats(self):
        settings = self.load_settings()
        with connect(self.config.db_path) as conn:
            stats = {
                "users": conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"],
                "active_users": conn.execute("SELECT COUNT(*) AS c FROM users WHERE is_active = 1").fetchone()["c"],
                "cases": conn.execute("SELECT COUNT(*) AS c FROM cases").fetchone()["c"],
                "model_requests": conn.execute("SELECT COUNT(*) AS c FROM model_requests").fetchone()["c"],
                "model_errors": conn.execute("SELECT COUNT(*) AS c FROM model_requests WHERE status = 'error'").fetchone()["c"],
                "lm_studio_api_url": settings.get("lm_studio_api_url", self.config.lm_studio_api_url),
                "lm_studio_model": settings.get("lm_studio_model", self.config.lm_studio_model),
                "app_name": settings.get("app_name", "CVD Web"),
                "default_theme": settings.get("default_theme", "light"),
            }
        return self.json_response({"stats": stats})

    def admin_model_health(self):
        settings = self.load_settings()
        api_url = settings.get("lm_studio_api_url") or self.config.lm_studio_api_url
        selected_model = settings.get("lm_studio_model") or self.config.lm_studio_model
        with connect(self.config.db_path) as conn:
            request_stats = row_to_dict(conn.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success,
                       SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors,
                       MAX(CASE WHEN status = 'success' THEN created_at END) AS last_success_at,
                       MAX(CASE WHEN status = 'error' THEN created_at END) AS last_error_at,
                       ROUND(AVG(CASE WHEN status = 'success' THEN duration_ms END)) AS avg_success_duration_ms
                FROM model_requests
                WHERE model = ?
                """,
                (selected_model,),
            ).fetchone())
        started = time.monotonic()
        try:
            catalog = list_lm_models(api_url, timeout_seconds=10, extra_headers=self.ai_gateway_headers(settings))
        except LMStudioManagementError as exc:
            latency_ms = int((time.monotonic() - started) * 1000)
            return self.json_response({
                "ok": False,
                "api_url": api_url,
                "selected_model": selected_model,
                "gateway": self.ai_gateway_public_profile(settings),
                "latency_ms": latency_ms,
                "error": str(exc),
                "request_stats": request_stats,
                "queue": self.inference_queue.snapshot(),
                "production_queue": self.production_queue_status(settings),
            })

        latency_ms = int((time.monotonic() - started) * 1000)
        models = catalog["models"]
        selected = next((item for item in models if item["id"] == selected_model), None)
        loaded_models = [
            item["id"]
            for item in models
            if item["state"] == "loaded"
        ]
        return self.json_response({
            "ok": bool(selected and selected["state"] == "loaded"),
            "api_url": api_url,
            "api_version": catalog["api_version"],
            "selected_model": selected_model,
            "gateway": self.ai_gateway_public_profile(settings),
            "selected_state": selected["state"] if selected else "not-found",
            "loaded_context_length": selected["loaded_context_length"] if selected else None,
            "max_context_length": selected["max_context_length"] if selected else None,
            "loaded_models": loaded_models,
            "latency_ms": latency_ms,
            "request_stats": request_stats,
            "queue": self.inference_queue.snapshot(),
            "production_queue": self.production_queue_status(settings),
        })

    def admin_models(self):
        settings = self.load_settings()
        api_url = settings.get("lm_studio_api_url") or self.config.lm_studio_api_url
        selected_model = settings.get("lm_studio_model") or self.config.lm_studio_model
        try:
            catalog = list_lm_models(api_url, timeout_seconds=15, extra_headers=self.ai_gateway_headers(settings))
        except LMStudioManagementError as exc:
            raise HTTPError(502, f"Не удалось получить модели LM Studio: {exc}") from exc
        return self.json_response({
            "api_url": api_url,
            "api_version": catalog["api_version"],
            "selected_model": selected_model,
            "gateway": self.ai_gateway_public_profile(settings),
            "models": catalog["models"],
        })

    def admin_activate_model(self, request: Request, admin: dict[str, Any]):
        settings = self.load_settings()
        self.ensure_request_size(request, settings)
        data = request.json()
        model_id = str(data.get("model") or "").strip()[:200]
        unload_previous = str(data.get("unload_previous", True)).strip().lower() in {"1", "true", "yes", "on"}
        api_url = settings.get("lm_studio_api_url") or self.config.lm_studio_api_url
        previous_model = settings.get("lm_studio_model") or self.config.lm_studio_model
        timeout_seconds = self.setting_int(settings, "lm_studio_timeout_seconds", self.config.lm_studio_timeout_seconds)
        try:
            result = activate_lm_model(
                api_url,
                model_id,
                previous_model_id=previous_model,
                unload_previous=unload_previous,
                timeout_seconds=timeout_seconds,
                extra_headers=self.ai_gateway_headers(settings),
            )
        except LMStudioManagementError as exc:
            raise HTTPError(502, str(exc)) from exc

        with connect(self.config.db_path) as conn:
            update_app_settings(conn, {"lm_studio_model": model_id})
            audit(
                conn,
                user_id=admin["id"],
                action="model_activate",
                target_type="app_settings",
                target_id=model_id,
                details={
                    "previous_model": previous_model,
                    "unload_previous": unload_previous,
                    "api_version": result["api_version"],
                    "unloaded_instances": result.get("unloaded_instances", []),
                },
            )
        return self.json_response({
            "ok": True,
            "selected_model": model_id,
            "selected": result["selected"],
            "api_version": result["api_version"],
            "warning": result.get("warning", ""),
        })

    def admin_ai_gateway_test(self, request: Request, admin: dict[str, Any]):
        settings = self.load_settings()
        self.ensure_request_size(request, settings)
        data = request.json() if request.body else {}
        api_url = str(data.get("api_url") or settings.get("lm_studio_api_url") or self.config.lm_studio_api_url).strip()
        selected_model = str(data.get("model") or settings.get("lm_studio_model") or self.config.lm_studio_model).strip()
        started = time.monotonic()
        try:
            catalog = list_lm_models(api_url, timeout_seconds=15, extra_headers=self.ai_gateway_headers(settings))
        except LMStudioManagementError as exc:
            latency_ms = int((time.monotonic() - started) * 1000)
            return self.json_response({
                "ok": False,
                "stage": "catalog",
                "latency_ms": latency_ms,
                "gateway": self.ai_gateway_public_profile({**settings, "lm_studio_api_url": api_url, "lm_studio_model": selected_model}),
                "error": str(exc),
            })
        latency_ms = int((time.monotonic() - started) * 1000)
        models = catalog.get("models", [])
        selected = next((item for item in models if item.get("id") == selected_model), None)
        loaded = [item.get("id") for item in models if item.get("state") == "loaded"]
        return self.json_response({
            "ok": bool(selected and selected.get("state") == "loaded"),
            "stage": "catalog",
            "api_version": catalog.get("api_version"),
            "latency_ms": latency_ms,
            "gateway": self.ai_gateway_public_profile({**settings, "lm_studio_api_url": api_url, "lm_studio_model": selected_model}),
            "selected_model": selected_model,
            "selected_state": selected.get("state") if selected else "not-found",
            "loaded_models": loaded,
            "models_count": len(models),
        })


    def admin_model_quality(self):
        with connect(self.config.db_path) as conn:
            request_rows = conn.execute(
                """
                SELECT id, case_id, model, status, duration_ms, tokens_per_second, total_tokens,
                       parsed_output_json, created_at
                FROM model_requests
                WHERE model <> ''
                ORDER BY created_at DESC, id DESC
                LIMIT 2000
                """
            ).fetchall()
            review_rows = conn.execute(
                """
                SELECT r.model, rv.rating, rv.issue_types_json, rv.created_at
                FROM model_request_reviews rv
                JOIN model_requests r ON r.id = rv.model_request_id
                WHERE r.model <> ''
                ORDER BY rv.created_at DESC
                LIMIT 2000
                """
            ).fetchall()
            gold_rows = conn.execute(
                """
                SELECT g.id, g.case_id, g.title, g.expected_diagnosis, g.expected_icd10_json,
                       g.expected_red_flags_json, g.expected_abstain, g.notes, g.created_at, g.updated_at,
                       c.patient_id, c.updated_at AS case_updated_at
                FROM gold_cases g
                JOIN cases c ON c.id = g.case_id
                ORDER BY g.updated_at DESC
                LIMIT 500
                """
            ).fetchall()

        per_model: dict[str, dict[str, Any]] = {}
        latest_gold_requests: dict[tuple[int, str], dict[str, Any]] = {}
        gold_case_ids = {row["case_id"] for row in gold_rows}
        comparable_cases: dict[int, set[str]] = {}
        for row in request_rows:
            item = row_to_dict(row)
            model_name = item.get("model") or "unknown"
            stats = per_model.setdefault(model_name, {
                "model": model_name,
                "requests": 0,
                "success": 0,
                "errors": 0,
                "durations": [],
                "tokens_per_second_values": [],
                "total_tokens": 0,
                "reviews": {"total": 0, "useful": 0, "partial": 0, "wrong": 0, "unsafe": 0},
                "gold_scores": [],
            })
            stats["requests"] += 1
            if item["status"] == "success":
                stats["success"] += 1
                if item.get("duration_ms"):
                    stats["durations"].append(int(item["duration_ms"]))
                if item.get("tokens_per_second"):
                    stats["tokens_per_second_values"].append(float(item["tokens_per_second"]))
                if item.get("case_id"):
                    comparable_cases.setdefault(int(item["case_id"]), set()).add(model_name)
            else:
                stats["errors"] += 1
            stats["total_tokens"] += int(item.get("total_tokens") or 0)
            if item.get("case_id") in gold_case_ids and item["status"] == "success" and item.get("parsed_output_json"):
                key = (int(item["case_id"]), model_name)
                latest_gold_requests.setdefault(key, item)

        for row in review_rows:
            model_name = row["model"] or "unknown"
            stats = per_model.setdefault(model_name, {
                "model": model_name, "requests": 0, "success": 0, "errors": 0, "durations": [],
                "tokens_per_second_values": [], "total_tokens": 0,
                "reviews": {"total": 0, "useful": 0, "partial": 0, "wrong": 0, "unsafe": 0},
                "gold_scores": [],
            })
            rating = row["rating"] if row["rating"] in {"useful", "partial", "wrong", "unsafe"} else "partial"
            stats["reviews"]["total"] += 1
            stats["reviews"][rating] += 1

        comparisons = []
        for row in gold_rows:
            base = row_to_dict(row)
            gold_item = {
                **base,
                "expected_icd10": json.loads(base.pop("expected_icd10_json") or "[]"),
                "expected_red_flags": json.loads(base.pop("expected_red_flags_json") or "[]"),
                "expected_abstain": bool(base["expected_abstain"]),
            }
            model_results = []
            for model_name in sorted(per_model):
                request_item = latest_gold_requests.get((int(gold_item["case_id"]), model_name))
                if not request_item:
                    continue
                parsed = json.loads(request_item.get("parsed_output_json") or "{}")
                evaluation = self.evaluate_gold_case(gold_item, parsed)
                per_model[model_name]["gold_scores"].append(evaluation["score_percent"])
                model_results.append({
                    "model": model_name,
                    "request_id": request_item["id"],
                    "created_at": request_item["created_at"],
                    "evaluation": evaluation,
                })
            if model_results:
                model_results.sort(key=lambda item: (-int(item["evaluation"].get("score_percent") or 0), item["model"]))
                comparisons.append({
                    "case_id": gold_item["case_id"],
                    "title": gold_item["title"],
                    "patient_id": gold_item.get("patient_id") or "",
                    "models": model_results,
                    "best_model": model_results[0]["model"],
                    "best_score_percent": model_results[0]["evaluation"]["score_percent"],
                })

        models = []
        for stats in per_model.values():
            durations = sorted(stats.pop("durations"))
            tps_values = stats.pop("tokens_per_second_values")
            gold_scores = stats.pop("gold_scores")
            total = stats["requests"]
            reviews = stats["reviews"]
            stats["success_rate_percent"] = round(stats["success"] * 100 / total, 1) if total else 0
            stats["avg_duration_ms"] = round(sum(durations) / len(durations)) if durations else 0
            p95_index = max(0, ((95 * len(durations) + 99) // 100) - 1) if durations else 0
            stats["p95_duration_ms"] = durations[p95_index] if durations else 0
            stats["avg_tokens_per_second"] = round(sum(tps_values) / len(tps_values), 2) if tps_values else 0
            stats["review_useful_rate_percent"] = round(reviews["useful"] * 100 / reviews["total"], 1) if reviews["total"] else 0
            stats["unsafe_rate_percent"] = round(reviews["unsafe"] * 100 / reviews["total"], 1) if reviews["total"] else 0
            stats["gold_cases_evaluated"] = len(gold_scores)
            stats["gold_avg_score_percent"] = round(sum(gold_scores) / len(gold_scores)) if gold_scores else 0
            models.append(stats)
        models.sort(key=lambda item: (-item["gold_avg_score_percent"], -item["review_useful_rate_percent"], item["model"]))

        review_totals = {"total": 0, "useful": 0, "partial": 0, "wrong": 0, "unsafe": 0}
        issue_counts: dict[str, int] = {}
        for row in review_rows:
            rating = row["rating"] if row["rating"] in review_totals else "partial"
            review_totals["total"] += 1
            review_totals[rating] += 1
            for issue in json.loads(row["issue_types_json"] or "[]"):
                issue_counts[str(issue)] = issue_counts.get(str(issue), 0) + 1

        multi_model_cases = sum(1 for models_for_case in comparable_cases.values() if len(models_for_case) > 1)
        return self.json_response({
            "summary": {
                "models": len(models),
                "gold_cases": len(gold_rows),
                "gold_comparisons": len(comparisons),
                "multi_model_cases": multi_model_cases,
                "reviews": review_totals["total"],
                "unsafe_reviews": review_totals["unsafe"],
            },
            "models": models,
            "comparisons": comparisons[:100],
            "reviews": {
                **review_totals,
                "useful_rate_percent": round(review_totals["useful"] * 100 / review_totals["total"], 1) if review_totals["total"] else 0,
                "issue_counts": sorted(
                    ({"issue": issue, "count": count} for issue, count in issue_counts.items()),
                    key=lambda item: (-item["count"], item["issue"]),
                )[:20],
            },
        })

    def admin_quality(self):
        with connect(self.config.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, title, patient_id, data_json, updated_at
                FROM cases
                ORDER BY updated_at DESC
                LIMIT 500
                """
            ).fetchall()
        cases = []
        total_completeness = 0
        total_readiness = 0
        signal_count = 0
        for row in rows:
            data = json.loads(row["data_json"])
            quality = case_quality_summary(data)
            total_completeness += quality["completeness_percent"]
            total_readiness += quality["readiness_percent"]
            signal_count += len(quality["signals"])
            cases.append({
                "id": row["id"],
                "title": row["title"],
                "patient_id": row["patient_id"],
                "updated_at": row["updated_at"],
                "quality": quality,
            })
        count = len(cases)
        summary = {
            "cases": count,
            "avg_completeness_percent": round(total_completeness / count) if count else 0,
            "avg_readiness_percent": round(total_readiness / count) if count else 0,
            "signals": signal_count,
        }
        return self.json_response({"summary": summary, "cases": cases})

    def admin_gold_set(self):
        with connect(self.config.db_path) as conn:
            rows = conn.execute(
                """
                SELECT
                  g.id, g.case_id, g.title, g.expected_diagnosis, g.expected_icd10_json,
                  g.expected_red_flags_json, g.expected_abstain, g.notes, g.created_at, g.updated_at,
                  c.patient_id, c.updated_at AS case_updated_at,
                  r.id AS latest_request_id, r.status AS latest_status, r.model AS latest_model,
                  r.prompt_version AS latest_prompt_version, r.output_schema_version AS latest_output_schema_version,
                  r.parsed_output_json AS latest_parsed_output_json, r.created_at AS latest_request_created_at
                FROM gold_cases g
                JOIN cases c ON c.id = g.case_id
                LEFT JOIN model_requests r ON r.id = (
                  SELECT mr.id
                  FROM model_requests mr
                  WHERE mr.case_id = g.case_id AND mr.status = 'success' AND mr.parsed_output_json IS NOT NULL
                  ORDER BY mr.created_at DESC, mr.id DESC
                  LIMIT 1
                )
                ORDER BY g.updated_at DESC
                LIMIT 500
                """
            ).fetchall()
        items = [self.serialize_gold_case(row) for row in rows]
        evaluated = [item for item in items if item["evaluation"]["status"] == "evaluated"]
        avg_score = round(sum(item["evaluation"]["score_percent"] for item in evaluated) / len(evaluated)) if evaluated else 0
        summary = {
            "gold_cases": len(items),
            "evaluated": len(evaluated),
            "avg_score_percent": avg_score,
            "icd10_hits": sum(1 for item in evaluated if item["evaluation"]["icd10_match"] is True),
            "red_flag_matches": sum(1 for item in evaluated if item["evaluation"]["red_flags_match"] is True),
            "abstain_matches": sum(1 for item in evaluated if item["evaluation"]["abstain_match"] is True),
        }
        return self.json_response({"summary": summary, "gold_cases": items})

    def admin_upsert_gold_case(self, request: Request, admin: dict[str, Any]):
        data = request.json()
        try:
            case_id = int(data.get("case_id"))
        except (TypeError, ValueError) as exc:
            raise HTTPError(400, "Некорректный case_id") from exc
        expected_diagnosis = str(data.get("expected_diagnosis", "")).strip()[:2000]
        expected_icd10 = self.normalized_text_list(data.get("expected_icd10"), upper=True, max_item_length=20)
        expected_red_flags = self.normalized_text_list(data.get("expected_red_flags"), max_item_length=240)
        expected_abstain = str(data.get("expected_abstain", "")).strip().lower() in {"1", "true", "yes", "on"}
        notes = str(data.get("notes", "")).strip()[:4000]
        now = utc_now()
        with connect(self.config.db_path) as conn:
            case = conn.execute("SELECT id, title FROM cases WHERE id = ?", (case_id,)).fetchone()
            if not case:
                raise HTTPError(404, "Кейс не найден")
            conn.execute(
                """
                INSERT INTO gold_cases
                  (case_id, title, expected_diagnosis, expected_icd10_json, expected_red_flags_json,
                   expected_abstain, notes, created_by_user_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                  title = excluded.title,
                  expected_diagnosis = excluded.expected_diagnosis,
                  expected_icd10_json = excluded.expected_icd10_json,
                  expected_red_flags_json = excluded.expected_red_flags_json,
                  expected_abstain = excluded.expected_abstain,
                  notes = excluded.notes,
                  updated_at = excluded.updated_at
                """,
                (
                    case_id,
                    case["title"],
                    expected_diagnosis,
                    json.dumps(expected_icd10, ensure_ascii=False),
                    json.dumps(expected_red_flags, ensure_ascii=False),
                    1 if expected_abstain else 0,
                    notes,
                    admin["id"],
                    now,
                    now,
                ),
            )
            audit(
                conn,
                user_id=admin["id"],
                action="gold_case_upsert",
                target_type="case",
                target_id=case_id,
                details={
                    "expected_icd10": expected_icd10,
                    "expected_red_flags": expected_red_flags,
                    "expected_abstain": expected_abstain,
                },
            )
        return self.json_response({"ok": True}, status=201)

    def admin_gold_runs(self):
        limit = 20
        with connect(self.config.db_path) as conn:
            run_rows = conn.execute(
                """
                SELECT gr.id, gr.created_by_user_id, u.email AS created_by_email, gr.status,
                       gr.total_items, gr.evaluated_items, gr.avg_score_percent,
                       gr.settings_snapshot_json, gr.created_at, gr.finished_at
                FROM gold_runs gr
                LEFT JOIN users u ON u.id = gr.created_by_user_id
                ORDER BY gr.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            run_ids = [row["id"] for row in run_rows]
            item_rows = []
            if run_ids:
                placeholders = ",".join("?" for _ in run_ids)
                item_rows = conn.execute(
                    f"""
                    SELECT
                      i.id, i.gold_run_id, i.gold_case_id, i.case_id, i.model_request_id,
                      i.status, i.score_percent, i.evaluation_json, i.created_at,
                      g.title, r.model, r.prompt_version
                    FROM gold_run_items i
                    JOIN gold_cases g ON g.id = i.gold_case_id
                    LEFT JOIN model_requests r ON r.id = i.model_request_id
                    WHERE i.gold_run_id IN ({placeholders})
                    ORDER BY i.gold_run_id DESC, i.score_percent ASC, i.id ASC
                    """,
                    run_ids,
                ).fetchall()
        runs = rows_to_dicts(run_rows)
        items_by_run: dict[int, list[dict[str, Any]]] = {run["id"]: [] for run in runs}
        for row in item_rows:
            item = row_to_dict(row)
            item["evaluation"] = json.loads(item.pop("evaluation_json") or "{}")
            items_by_run.setdefault(item["gold_run_id"], []).append(item)
        for run in runs:
            run["settings_snapshot"] = json.loads(run.pop("settings_snapshot_json") or "{}")
            run["items"] = items_by_run.get(run["id"], [])
        return self.json_response({"runs": runs})

    def admin_create_gold_run(self, admin: dict[str, Any]):
        settings = self.load_settings()
        settings_snapshot = {
            "lm_studio_model": settings.get("lm_studio_model") or self.config.lm_studio_model,
            "active_prompt_version": settings.get("active_prompt_version") or MODEL_PROMPT_VERSION,
            "patient_schema_version": PATIENT_SCHEMA_VERSION,
            "output_schema_version": MODEL_OUTPUT_SCHEMA_VERSION,
            "created_from": "latest_successful_results",
        }
        with connect(self.config.db_path) as conn:
            rows = conn.execute(
                """
                SELECT
                  g.id, g.case_id, g.title, g.expected_diagnosis, g.expected_icd10_json,
                  g.expected_red_flags_json, g.expected_abstain, g.notes, g.created_at, g.updated_at,
                  c.patient_id, c.updated_at AS case_updated_at,
                  r.id AS latest_request_id, r.status AS latest_status, r.model AS latest_model,
                  r.prompt_version AS latest_prompt_version, r.output_schema_version AS latest_output_schema_version,
                  r.parsed_output_json AS latest_parsed_output_json, r.created_at AS latest_request_created_at
                FROM gold_cases g
                JOIN cases c ON c.id = g.case_id
                LEFT JOIN model_requests r ON r.id = (
                  SELECT mr.id
                  FROM model_requests mr
                  WHERE mr.case_id = g.case_id AND mr.status = 'success' AND mr.parsed_output_json IS NOT NULL
                  ORDER BY mr.created_at DESC, mr.id DESC
                  LIMIT 1
                )
                ORDER BY g.updated_at DESC
                LIMIT 500
                """
            ).fetchall()
            items = [self.serialize_gold_case(row) for row in rows]
            evaluated = [item for item in items if item["evaluation"]["status"] == "evaluated"]
            avg_score = round(sum(item["evaluation"]["score_percent"] for item in evaluated) / len(evaluated)) if evaluated else 0
            now = utc_now()
            cur = conn.execute(
                """
                INSERT INTO gold_runs
                  (created_by_user_id, status, total_items, evaluated_items, avg_score_percent,
                   settings_snapshot_json, created_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    admin["id"],
                    "completed" if items else "empty",
                    len(items),
                    len(evaluated),
                    avg_score,
                    json.dumps(settings_snapshot, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            run_id = int(cur.lastrowid)
            conn.executemany(
                """
                INSERT INTO gold_run_items
                  (gold_run_id, gold_case_id, case_id, model_request_id, status,
                   score_percent, evaluation_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        item["id"],
                        item["case_id"],
                        item.get("latest_request_id"),
                        item["evaluation"]["status"],
                        item["evaluation"]["score_percent"],
                        json.dumps(item["evaluation"], ensure_ascii=False),
                        now,
                    )
                    for item in items
                ],
            )
            audit(
                conn,
                user_id=admin["id"],
                action="gold_run_create",
                target_type="gold_run",
                target_id=run_id,
                details={"total_items": len(items), "evaluated_items": len(evaluated), "avg_score_percent": avg_score},
            )
        return self.json_response({"ok": True, "run_id": run_id, "summary": {"total_items": len(items), "evaluated_items": len(evaluated), "avg_score_percent": avg_score}}, status=201)

    def normalized_text_list(self, value: Any, *, upper: bool = False, max_item_length: int = 120) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_items = re.split(r"[,;\n]+", value)
        elif isinstance(value, list):
            raw_items = value
        else:
            raise HTTPError(400, "Ожидался список или строка")
        items = []
        for item in raw_items:
            text = str(item).strip()
            if not text:
                continue
            if upper:
                text = text.upper()
            if text not in items:
                items.append(text[:max_item_length])
        return items[:50]

    def serialize_gold_case(self, row) -> dict[str, Any]:
        item = row_to_dict(row)
        item["expected_icd10"] = json.loads(item.pop("expected_icd10_json") or "[]")
        item["expected_red_flags"] = json.loads(item.pop("expected_red_flags_json") or "[]")
        item["expected_abstain"] = bool(item["expected_abstain"])
        parsed = json.loads(item.pop("latest_parsed_output_json")) if item.get("latest_parsed_output_json") else None
        item["evaluation"] = self.evaluate_gold_case(item, parsed)
        return item

    def evaluate_gold_case(self, item: dict[str, Any], parsed_output: dict[str, Any] | None) -> dict[str, Any]:
        if not parsed_output:
            return {
                "status": "pending",
                "score_percent": 0,
                "icd10_match": None,
                "red_flags_match": None,
                "abstain_match": None,
                "diagnosis_match": None,
                "actual_icd10": [],
                "actual_red_flags": [],
                "actual_abstain": None,
            }
        cds = parsed_output.get("CDS_OUTPUT", {}) if isinstance(parsed_output, dict) else {}
        model_output = parsed_output.get("MODEL_OUTPUT", {}) if isinstance(parsed_output, dict) else {}
        possible = cds.get("possible_diagnoses", []) if isinstance(cds, dict) else []
        actual_icd10 = set(
            str(code).upper()
            for code in (model_output.get("Model_ICD10_codes", []) if isinstance(model_output, dict) else [])
            if str(code).strip()
        )
        if isinstance(possible, list):
            for diagnosis in possible:
                if isinstance(diagnosis, dict):
                    actual_icd10.update(str(code).upper() for code in diagnosis.get("icd10_codes", []) if str(code).strip())
        actual_red_flags = cds.get("red_flags", []) if isinstance(cds, dict) else []
        if not isinstance(actual_red_flags, list):
            actual_red_flags = []
        actual_abstain = bool(cds.get("model_should_abstain")) if isinstance(cds, dict) else False
        summary_text = " ".join(
            str(value or "")
            for value in (
                cds.get("summary") if isinstance(cds, dict) else "",
                model_output.get("Final_model_diagnosis") if isinstance(model_output, dict) else "",
            )
        ).lower()

        expected_icd10 = set(item.get("expected_icd10") or [])
        expected_red_flags = [str(flag).strip().lower() for flag in item.get("expected_red_flags") or [] if str(flag).strip()]
        expected_diagnosis = str(item.get("expected_diagnosis") or "").strip().lower()
        icd10_match = bool(expected_icd10 & actual_icd10) if expected_icd10 else None
        if expected_red_flags:
            red_flags_text = " ".join(str(flag).lower() for flag in actual_red_flags)
            red_flags_match = all(flag in red_flags_text for flag in expected_red_flags)
        else:
            red_flags_match = len(actual_red_flags) == 0
        abstain_match = actual_abstain == bool(item.get("expected_abstain"))
        diagnosis_match = expected_diagnosis in summary_text if expected_diagnosis else None
        scored = [value for value in (icd10_match, red_flags_match, abstain_match, diagnosis_match) if value is not None]
        score_percent = round(sum(1 for value in scored if value) * 100 / len(scored)) if scored else 0
        return {
            "status": "evaluated",
            "score_percent": score_percent,
            "icd10_match": icd10_match,
            "red_flags_match": red_flags_match,
            "abstain_match": abstain_match,
            "diagnosis_match": diagnosis_match,
            "actual_icd10": sorted(actual_icd10),
            "actual_red_flags": actual_red_flags,
            "actual_abstain": actual_abstain,
        }

    def case_title(self, patient_data: dict[str, Any]) -> str:
        general = patient_data.get("GENERAL_INFO", {})
        patient_id = str(general.get("Patient_ID") or "").strip()
        full_name = str(general.get("Full_name") or "").strip()
        diagnosis = str(patient_data.get("FINAL_DIAGNOSES", {}).get("Main_cardiovascular_diagnosis_text") or "").strip()
        identity = " · ".join(item for item in (full_name, patient_id) if item)
        if identity and diagnosis:
            return f"{identity}: {diagnosis[:80]}"
        return identity or diagnosis[:100] or "Новый CVD-кейс"

    def public_user(self, user: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "role": user["role"],
            "must_change_password": bool(user["must_change_password"]),
        }

    def render(self, template_name: str, *, user: dict[str, Any] | None, csrf_token: str):
        template = (self.template_dir / template_name).read_text(encoding="utf-8")
        user_json = json.dumps(self.public_user(user) if user else None, ensure_ascii=False)
        settings = self.load_settings()
        template_settings = settings if template_name == "admin.html" else self.public_settings(settings)
        settings_json = json.dumps(template_settings, ensure_ascii=False)
        html = (
            template
            .replace("{{csrf_token}}", csrf_token)
            .replace("{{user_json}}", user_json.replace("</", "<\\/"))
            .replace("{{settings_json}}", settings_json.replace("</", "<\\/"))
            .replace("{{app_name}}", escape(settings.get("app_name", "CVD Web")))
            .replace("{{organization_name}}", escape(settings.get("organization_name", "")))
            .replace("{{system_description}}", escape(settings.get("system_description", "")))
            .replace("{{usage_notice}}", escape(settings.get("usage_notice", "")))
            .replace("{{default_theme}}", escape(settings.get("default_theme", "light")))
            .replace("{{app_version}}", APP_VERSION)
            .replace("{{patient_schema_version}}", PATIENT_SCHEMA_VERSION)
        )
        return self.html_response(html)

    def serve_static(self, relative_path: str):
        path = (self.static_dir / relative_path).resolve()
        if not str(path).startswith(str(self.static_dir.resolve())) or not path.is_file():
            raise HTTPError(404, "Статический файл не найден")
        content_type, _ = mimetypes.guess_type(str(path))
        body = path.read_bytes()
        return self.response(200, body, [("Content-Type", content_type or "application/octet-stream")])

    def session_cookie_header(self, session_id: str) -> list[tuple[str, str]]:
        parts = [
            f"{SESSION_COOKIE}={session_id}",
            "Path=/",
            "HttpOnly",
            "SameSite=Lax",
            f"Max-Age={self.config.session_days * 24 * 3600}",
        ]
        if self.config.cookie_secure:
            parts.append("Secure")
        return [("Set-Cookie", "; ".join(parts))]

    def clear_session_cookie_header(self) -> list[tuple[str, str]]:
        return [("Set-Cookie", f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")]

    def json_response(self, data: dict[str, Any], status: int = 200, headers: list[tuple[str, str]] | None = None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        response_headers = [("Content-Type", "application/json; charset=utf-8")]
        if headers:
            response_headers.extend(headers)
        return self.response(status, body, response_headers)

    def html_response(self, html: str, status: int = 200):
        return self.response(status, html.encode("utf-8"), [("Content-Type", "text/html; charset=utf-8")])

    def redirect(self, location: str):
        return self.response(302, b"", [("Location", location)])

    def response(self, status: int, body: bytes, headers: list[tuple[str, str]]):
        reason = {
            200: "OK",
            201: "Created",
            302: "Found",
            400: "Bad Request",
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not Found",
            409: "Conflict",
            413: "Payload Too Large",
            429: "Too Many Requests",
            500: "Internal Server Error",
            502: "Bad Gateway",
        }.get(status, "OK")
        security_headers = [
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "same-origin"),
            ("X-Frame-Options", "DENY"),
            ("Cross-Origin-Opener-Policy", "same-origin"),
            ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
            (
                "Content-Security-Policy",
                "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; "
                "form-action 'self'; img-src 'self' data:; "
                "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'",
            ),
        ]
        if self.config.cookie_secure:
            security_headers.append(("Strict-Transport-Security", "max-age=31536000; includeSubDomains"))
        full_headers = [("Content-Length", str(len(body))), *security_headers, *headers]
        return f"{status} {reason}", full_headers, body
