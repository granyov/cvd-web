"""WSGI-приложение CVD Web: маршрутизация и ядро; обработчики доменов в handlers_*."""
from __future__ import annotations

import json
import mimetypes
import re
import threading
import traceback
from html import escape
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlsplit

from .auth import utc_now
from .config import Config
from .cvd_schema import validate_and_normalize_patient_data
from .db import connect, get_app_settings, init_db, row_to_dict
from .inference_queue import InferenceQueue
from .rate_limit import MemoryRateLimiter
from .versions import APP_VERSION, PATIENT_SCHEMA_VERSION
from .handlers_admin import AdminMixin
from .handlers_ai import AiMixin
from .handlers_auth import AuthMixin
from .handlers_cases import CasesMixin
from .handlers_import_export import ImportExportMixin
from .web_core import HTTPError, PASSWORD_CHANGE_ALLOWED_PATHS, PUBLIC_SETTING_KEYS, Request, SESSION_COOKIE, UNSAFE_METHODS


class CVDApplication(AuthMixin, CasesMixin, ImportExportMixin, AiMixin, AdminMixin):
    def __init__(self, config: Config, *, start_batch_worker: bool = True):
        self.config = config
        init_db(config)
        self.template_dir = config.project_root / "cvd_web" / "templates"
        self.static_dir = config.project_root / "cvd_web" / "static"
        self.rate_limiter = MemoryRateLimiter()
        self.inference_queue = InferenceQueue()
        self.started_at = datetime.now(timezone.utc).replace(microsecond=0)
        self.batch_worker_event = threading.Event()
        self.inference_worker_event = threading.Event()
        self.recover_interrupted_inference_jobs()
        self.recover_interrupted_text_preparation_jobs()
        self.recover_interrupted_batch_jobs()
        self.batch_worker_thread: threading.Thread | None = None
        self.inference_worker_thread: threading.Thread | None = None
        if start_batch_worker:
            self.inference_worker_thread = threading.Thread(
                target=self.inference_worker_loop,
                name="cvd-inference-worker",
                daemon=True,
            )
            self.inference_worker_thread.start()
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
        if request.path == "/readyz" and request.method == "GET":
            return self.readiness_response()

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

        if user["must_change_password"] and request.path not in PASSWORD_CHANGE_ALLOWED_PATHS:
            if request.path.startswith("/api/"):
                raise HTTPError(403, "Сначала смените пароль по умолчанию")
            return self.redirect("/app")

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
        if request.path == "/api/cases/demo" and request.method == "POST":
            return self.create_demo_case(user)
        if request.path == "/api/library/summary" and request.method == "GET":
            return self.library_summary(user)
        if request.path == "/api/import/preview" and request.method == "POST":
            return self.preview_clinical_import(request, user)
        if request.path == "/api/import/pdf-text" and request.method == "POST":
            return self.import_pdf_text(request, user)
        if request.path == "/api/imports" and request.method == "GET":
            return self.list_clinical_imports(request, user)
        if request.path == "/api/text-preparations" and request.method == "GET":
            return self.list_text_preparations(request, user)
        if request.path == "/api/ai/jobs" and request.method == "GET":
            return self.list_ai_jobs(user)
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
        if request.path == "/api/model/diagnose/jobs" and request.method == "POST":
            return self.create_diagnosis_job(request, user)
        if match := re.fullmatch(r"/api/model/diagnose/jobs/(\d+)", request.path):
            if request.method == "GET":
                return self.get_diagnosis_job(user, int(match.group(1)))
        if request.path == "/api/model/structure-text/jobs" and request.method == "POST":
            return self.create_text_preparation_job(request, user)
        if match := re.fullmatch(r"/api/model/structure-text/jobs/(\d+)", request.path):
            if request.method == "GET":
                return self.get_text_preparation_job(user, int(match.group(1)))
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
        if request.path == "/api/admin/security-audit" and request.method == "GET":
            self.require_admin(user)
            return self.admin_security_audit()
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
        if request.path == "/api/admin/gold-set/export.csv" and request.method == "GET":
            self.require_admin(user)
            return self.admin_gold_set_export_csv()
        if request.path == "/api/admin/gold-set/report.html" and request.method == "GET":
            self.require_admin(user)
            return self.admin_gold_set_report_html()
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
        rate_limit_backend = str(settings.get("rate_limit_backend") or "memory").strip().lower()
        if rate_limit_backend not in {"memory", "redis", "postgresql"}:
            rate_limit_backend = "memory"
        rate_limit_dsn_configured = bool(str(settings.get("rate_limit_dsn") or "").strip())
        rate_limit_external = rate_limit_backend in {"redis", "postgresql"}
        worker_mode = str(settings.get("inference_worker_mode") or "in_process").strip().lower()
        if worker_mode not in {"in_process", "external"}:
            worker_mode = "in_process"

        queue_adapter_active = False
        rate_limit_adapter_active = False
        external_worker_active = False
        production_ready = (
            external
            and dsn_configured
            and queue_adapter_active
            and rate_limit_external
            and rate_limit_dsn_configured
            and rate_limit_adapter_active
            and worker_mode == "external"
            and external_worker_active
        )
        if not self.config.production_mode and not external and not rate_limit_external and worker_mode == "in_process":
            production_ready = True
        blockers = []
        if self.config.production_mode:
            if not external:
                blockers.append("queue-backend-memory")
            elif not dsn_configured:
                blockers.append("queue-dsn-missing")
            elif not queue_adapter_active:
                blockers.append("queue-adapter-not-active")
            if not rate_limit_external:
                blockers.append("rate-limit-memory")
            elif not rate_limit_dsn_configured:
                blockers.append("rate-limit-dsn-missing")
            elif not rate_limit_adapter_active:
                blockers.append("rate-limit-adapter-not-active")
            if worker_mode != "external":
                blockers.append("worker-in-process")
            elif not external_worker_active:
                blockers.append("external-worker-not-active")
        return {
            "backend": backend,
            "active_backend": "memory",
            "external_requested": external,
            "dsn_configured": dsn_configured,
            "queue_adapter_active": queue_adapter_active,
            "rate_limit_backend": rate_limit_backend,
            "active_rate_limit_backend": "memory",
            "rate_limit_external_requested": rate_limit_external,
            "rate_limit_dsn_configured": rate_limit_dsn_configured,
            "rate_limit_adapter_active": rate_limit_adapter_active,
            "worker_mode": worker_mode,
            "active_worker_mode": "in_process",
            "external_worker_active": external_worker_active,
            "production_ready": production_ready,
            "blockers": blockers,
            "status": "development-memory-active" if production_ready and not self.config.production_mode else "production-ready" if production_ready else "production-blocked",
            "message": (
                "In-process queue/rate limit are acceptable for development or single-process controlled evaluation only."
                if production_ready and not self.config.production_mode else
                "Production readiness requires active external queue, external rate limit and separate worker adapters."
            ),
        }

    def readiness_response(self):
        checks: dict[str, Any] = {
            "database": {"ok": False},
            "templates": {"ok": self.template_dir.is_dir()},
            "static": {"ok": self.static_dir.is_dir()},
            "security": {
                "ok": True,
                "production_mode": self.config.production_mode,
                "cookie_secure": self.config.cookie_secure,
            },
            "runtime": {"ok": True},
        }
        status = 200
        try:
            with connect(self.config.db_path) as conn:
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                checks["database"] = {
                    "ok": integrity == "ok" and user_count > 0,
                    "integrity": integrity,
                    "user_count": user_count,
                }
        except Exception as exc:
            checks["database"] = {"ok": False, "error": exc.__class__.__name__}

        if self.config.production_mode and not self.config.cookie_secure:
            checks["security"] = {
                **checks["security"],
                "ok": False,
                "message": "CVD_COOKIE_SECURE=1 is required for production readiness.",
            }
        if self.config.production_mode:
            settings = self.load_settings()
            queue_status = self.production_queue_status(settings)
            checks["runtime"] = {
                "ok": queue_status["production_ready"],
                "queue": queue_status,
                "rate_limit_backend": queue_status["rate_limit_backend"],
                "worker_mode": queue_status["worker_mode"],
                "blockers": queue_status["blockers"],
                "message": "Active external queue, rate-limit and worker adapters are required before production readiness.",
            }

        ok = all(bool(item.get("ok")) for item in checks.values())
        if not ok:
            status = 503
        return self.json_response({"ok": ok, "checks": checks}, status=status)

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
            503: "Service Unavailable",
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

