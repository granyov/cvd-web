"""Админка: пользователи, настройки, дашборды, batch, gold set, backup."""
from __future__ import annotations

import hashlib
import csv
import json
import sqlite3
import re
import time
import traceback
from contextlib import closing
from html import escape
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Any

from .auth import hash_password, utc_now, verify_password
from .db import DEFAULT_ADMIN_PASSWORDS, audit, connect, get_app_settings, get_app_settings_full, row_to_dict, rows_to_dicts, update_app_settings
from .lmstudio_models import LMStudioManagementError, activate_lm_model, list_lm_models
from .quality import case_quality_summary
from .versions import APP_VERSION, MODEL_OUTPUT_SCHEMA_VERSION, MODEL_PROMPT_VERSION, PATIENT_SCHEMA_VERSION
from .web_core import HTTPError, Request


class AdminMixin:
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

    def sanitize_setting_for_audit(self, key: str, value: Any) -> Any:
        text = str(value or "")
        lowered = key.lower()
        if key == "ai_gateway_headers_json":
            try:
                headers = json.loads(text or "[]")
            except json.JSONDecodeError:
                return {"configured": bool(text), "valid_json": False}
            names = [str(item.get("name") or "") for item in headers if isinstance(item, dict) and item.get("name")]
            return {"configured": bool(names), "count": len(names), "names": names}
        if any(marker in lowered for marker in ("password", "secret", "token", "dsn", "header_value")):
            return {"configured": bool(text), "length": len(text)}
        if key == "active_prompt_template" or len(text) > 180:
            return {"length": len(text), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
        return text

    def sanitized_settings_diff(self, before: dict[str, str], after: dict[str, str]) -> list[dict[str, Any]]:
        changed = []
        for key in sorted(after):
            if str(before.get(key, "")) == str(after.get(key, "")):
                continue
            changed.append({
                "key": key,
                "old": self.sanitize_setting_for_audit(key, before.get(key, "")),
                "new": self.sanitize_setting_for_audit(key, after.get(key, "")),
            })
        return changed[:100]

    def admin_security_audit(self):
        settings = self.load_settings()
        runtime = self.production_queue_status(settings)
        with connect(self.config.db_path) as conn:
            user_counts = row_to_dict(conn.execute(
                """
                SELECT
                  COUNT(*) AS total,
                  SUM(CASE WHEN role = 'admin' AND is_active = 1 THEN 1 ELSE 0 END) AS active_admins,
                  SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) AS active_users
                FROM users
                """
            ).fetchone())
            admin_hash_rows = conn.execute(
                "SELECT password_hash FROM users WHERE role = 'admin' AND is_active = 1"
            ).fetchall()
            audit_count = conn.execute("SELECT COUNT(*) AS c FROM audit_log").fetchone()["c"]
        backup_dir = self.config.db_path.parent / "backups"
        checks = []

        def add_check(key: str, ok: bool, severity: str, message: str) -> None:
            checks.append({"key": key, "ok": ok, "severity": severity if not ok else "ok", "message": message})

        add_check(
            "production_env",
            self.config.production_mode,
            "warning",
            "CVD_ENV не production; допустимо для local/controlled, но не для публичного VPS.",
        )
        add_check(
            "secure_cookie",
            (not self.config.production_mode) or self.config.cookie_secure,
            "critical",
            "В production требуется CVD_COOKIE_SECURE=1.",
        )
        add_check(
            "admin_email",
            self.config.admin_email.lower().strip() != "admin@example.local",
            "warning",
            "Задайте CVD_ADMIN_EMAIL вместо значения по умолчанию.",
        )
        add_check(
            "default_admin_password",
            not any(
                verify_password(default_password, row["password_hash"])
                for row in admin_hash_rows
                for default_password in DEFAULT_ADMIN_PASSWORDS
            ),
            "critical",
            "Активный администратор не должен использовать пароль по умолчанию.",
        )
        add_check(
            "active_admin",
            int(user_counts.get("active_admins") or 0) >= 1,
            "critical",
            "Должен быть хотя бы один активный администратор.",
        )
        add_check(
            "deidentify_before_model",
            str(settings.get("deidentify_before_model") or "1") == "1",
            "warning",
            "Деидентификация перед отправкой в модель должна быть включена.",
        )
        try:
            self.ai_gateway_header_entries(settings)
            gateway_headers_ok = True
            gateway_headers_message = (
                "Cloudflare Access headers опциональны. Для публичного cloudflared tunnel оставьте список headers пустым."
            )
        except HTTPError as exc:
            gateway_headers_ok = False
            gateway_headers_message = str(exc)
        add_check(
            "cloudflared_access_headers",
            gateway_headers_ok,
            "warning",
            gateway_headers_message,
        )
        add_check(
            "production_runtime",
            (not self.config.production_mode) or runtime["production_ready"],
            "critical",
            f"Production runtime не готов: {', '.join(runtime['blockers']) or runtime['status']}.",
        )
        add_check(
            "backup_directory",
            backup_dir.exists(),
            "warning",
            "Создайте хотя бы один backup и проверьте права на каталог backups.",
        )
        add_check(
            "audit_log",
            int(audit_count or 0) > 0,
            "warning",
            "Журнал аудита должен регулярно пополняться административными событиями.",
        )
        failed = [item for item in checks if not item["ok"]]
        return self.json_response({
            "ok": not any(item["severity"] == "critical" for item in failed),
            "generated_at": utc_now(),
            "checks": checks,
            "summary": {
                "total": len(checks),
                "failed": len(failed),
                "critical": sum(1 for item in failed if item["severity"] == "critical"),
                "warnings": sum(1 for item in failed if item["severity"] == "warning"),
            },
            "runtime": runtime,
            "users": user_counts,
        })

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
        with closing(sqlite3.connect(self.config.db_path)) as source, closing(sqlite3.connect(target)) as dest:
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
        with closing(sqlite3.connect(source_path)) as source:
            integrity = source.execute("PRAGMA quick_check").fetchone()[0]
            if integrity != "ok":
                raise HTTPError(400, f"Backup повреждён: {integrity}")
        safety_name = f"cvd-before-restore-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.sqlite3"
        safety_path = self.backup_dir() / safety_name
        with closing(sqlite3.connect(self.config.db_path)) as current, closing(sqlite3.connect(safety_path)) as safety:
            current.backup(safety)
        with closing(sqlite3.connect(source_path)) as source, closing(sqlite3.connect(self.config.db_path)) as dest:
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
            "ai_gateway_headers_json": str(incoming.get("ai_gateway_headers_json", "")).strip(),
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
            "rate_limit_backend": str(incoming.get("rate_limit_backend", "memory")).strip().lower(),
            "rate_limit_dsn": str(incoming.get("rate_limit_dsn", "")).strip()[:1000],
            "inference_worker_mode": str(incoming.get("inference_worker_mode", "in_process")).strip().lower(),
            "deidentify_before_model": "1" if str(incoming.get("deidentify_before_model", "1")).strip().lower() in {"1", "true", "yes", "on"} else "0",
            "active_prompt_version": str(incoming.get("active_prompt_version", MODEL_PROMPT_VERSION)).strip()[:120],
            "active_prompt_template": str(incoming.get("active_prompt_template", "")).strip()[:12000],
            "gold_min_score_percent": str(incoming.get("gold_min_score_percent", "80")).strip(),
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
        if values["rate_limit_backend"] not in {"memory", "redis", "postgresql"}:
            raise HTTPError(400, "rate_limit_backend должен быть memory, redis или postgresql")
        if values["rate_limit_backend"] != "memory" and not values["rate_limit_dsn"]:
            raise HTTPError(400, "Для Redis/PostgreSQL rate limiter укажите rate_limit_dsn")
        if values["inference_worker_mode"] not in {"in_process", "external"}:
            raise HTTPError(400, "inference_worker_mode должен быть in_process или external")
        header_entries = self.ai_gateway_header_entries(values)
        values["ai_gateway_headers_json"] = json.dumps(header_entries, ensure_ascii=False)
        if header_entries:
            values["ai_gateway_auth_header_name"] = header_entries[0]["name"]
            values["ai_gateway_auth_header_value"] = header_entries[0]["value"]
        else:
            values["ai_gateway_auth_header_name"] = ""
            values["ai_gateway_auth_header_value"] = ""
        if not values["lm_studio_api_url"].startswith(("http://", "https://")):
            raise HTTPError(400, "API URL должен начинаться с http:// или https://")
        if not values["lm_studio_model"]:
            raise HTTPError(400, "Имя модели не может быть пустым")
        if not values["active_prompt_version"]:
            raise HTTPError(400, "Версия prompt не может быть пустой")
        if "{{PATIENT_JSON}}" not in values["active_prompt_template"]:
            raise HTTPError(400, "Prompt template должен содержать {{PATIENT_JSON}}")

        ranges = {
            "lm_studio_timeout_seconds": (5, 7200),
            "lm_studio_max_tokens": (1024, 32768),
            "lm_studio_max_concurrent": (1, 8),
            "lm_studio_queue_limit": (1, 500),
            "lm_studio_per_user_limit": (1, 10),
            "lm_studio_queue_timeout_seconds": (30, 21600),
            "gold_min_score_percent": (0, 100),
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
            before_settings = get_app_settings(conn)
            update_app_settings(conn, values)
            changed = self.sanitized_settings_diff(before_settings, values)
            audit(
                conn,
                user_id=admin["id"],
                action="settings_update",
                target_type="app_settings",
                details={"changed": changed},
            )
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
        # Запоминаем реальный контекст загруженной модели: по нему проверяем объём
        # случая до отправки, чтобы врач не ждал минуту ради ошибки переполнения.
        loaded_context = selected.get("loaded_context_length") if selected else None
        if loaded_context:
            with connect(self.config.db_path) as conn:
                update_app_settings(conn, {"lm_studio_context_tokens": str(int(loaded_context))})
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
        test_settings = {**settings, "lm_studio_api_url": api_url, "lm_studio_model": selected_model}
        if "ai_gateway_headers_json" in data:
            test_settings["ai_gateway_headers_json"] = str(data.get("ai_gateway_headers_json") or "").strip()
            test_settings["ai_gateway_auth_header_name"] = ""
            test_settings["ai_gateway_auth_header_value"] = ""
        try:
            extra_headers = self.ai_gateway_headers(test_settings)
        except HTTPError as exc:
            return self.json_response({
                "ok": False,
                "stage": "headers",
                "latency_ms": 0,
                "gateway": {
                    "profile": str(test_settings.get("ai_gateway_profile") or "local").strip().lower(),
                    "api_url": api_url,
                    "selected_model": selected_model,
                    "auth_header_configured": False,
                    "auth_header_count": 0,
                    "auth_header_names": [],
                },
                "error": str(exc),
            }, 400)
        started = time.monotonic()
        try:
            catalog = list_lm_models(api_url, timeout_seconds=15, extra_headers=extra_headers)
        except LMStudioManagementError as exc:
            latency_ms = int((time.monotonic() - started) * 1000)
            return self.json_response({
                "ok": False,
                "stage": "catalog",
                "latency_ms": latency_ms,
                "gateway": self.ai_gateway_public_profile(test_settings),
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
            "gateway": self.ai_gateway_public_profile(test_settings),
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
                       g.expected_red_flags_json, g.expected_missing_data_json, g.expected_abstain,
                       g.severity, g.notes, g.created_at, g.updated_at,
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

    def gold_gate_threshold(self, settings: dict[str, str] | None = None) -> int:
        settings = settings or self.load_settings()
        return self.setting_int(settings, "gold_min_score_percent", 80)

    def gold_set_payload(self) -> dict[str, Any]:
        settings = self.load_settings()
        with connect(self.config.db_path) as conn:
            rows = conn.execute(
                """
                SELECT
                  g.id, g.case_id, g.title, g.expected_diagnosis, g.expected_icd10_json,
                  g.expected_red_flags_json, g.expected_missing_data_json, g.expected_abstain,
                  g.severity, g.notes, g.created_at, g.updated_at,
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
        summary = self.gold_set_summary(items, min_score_percent=self.gold_gate_threshold(settings))
        return {"summary": summary, "gold_cases": items}

    def gold_set_summary(self, items: list[dict[str, Any]], *, min_score_percent: int) -> dict[str, Any]:
        evaluated = [item for item in items if item["evaluation"]["status"] == "evaluated"]
        avg_score = round(sum(item["evaluation"]["score_percent"] for item in evaluated) / len(evaluated)) if evaluated else 0
        severity_counts: dict[str, int] = {}
        failed_high_severity = 0
        for item in items:
            severity = str(item.get("severity") or "medium")
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
            if severity in {"high", "critical"} and item["evaluation"]["status"] == "evaluated" and item["evaluation"]["score_percent"] < min_score_percent:
                failed_high_severity += 1
        gate_reasons = []
        if not items:
            gate_reasons.append("gold-set-empty")
        if len(evaluated) < len(items):
            gate_reasons.append("not-all-cases-evaluated")
        if avg_score < min_score_percent:
            gate_reasons.append("avg-score-below-threshold")
        if failed_high_severity:
            gate_reasons.append("high-severity-failures")
        summary = {
            "gold_cases": len(items),
            "evaluated": len(evaluated),
            "avg_score_percent": avg_score,
            # min_score_percent исторически хранит порог допуска, а не минимальный балл:
            # оставлен для совместимости со старыми записями прогонов.
            "min_score_percent": min_score_percent,
            "score_threshold_percent": min_score_percent,
            "worst_score_percent": (
                min(item["evaluation"]["score_percent"] for item in evaluated) if evaluated else 0
            ),
            "release_gate_ok": not gate_reasons,
            "release_gate_reasons": gate_reasons,
            "severity_counts": severity_counts,
            "failed_high_severity": failed_high_severity,
            "icd10_hits": sum(1 for item in evaluated if item["evaluation"]["icd10_match"] is True),
            "red_flag_matches": sum(1 for item in evaluated if item["evaluation"]["red_flags_match"] is True),
            "missing_data_matches": sum(1 for item in evaluated if item["evaluation"]["missing_data_match"] is True),
            "abstain_matches": sum(1 for item in evaluated if item["evaluation"]["abstain_match"] is True),
        }
        return summary

    def admin_gold_set(self):
        return self.json_response(self.gold_set_payload())

    def admin_gold_set_export_csv(self):
        payload = self.gold_set_payload()
        output = StringIO()
        fieldnames = [
            "gold_id",
            "case_id",
            "title",
            "patient_id",
            "severity",
            "latest_request_id",
            "latest_model",
            "score_percent",
            "status",
            "icd10_match",
            "red_flags_match",
            "missing_data_match",
            "abstain_match",
            "diagnosis_match",
            "expected_icd10",
            "expected_red_flags",
            "expected_missing_data",
            "expected_abstain",
            "expected_diagnosis",
            "notes",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for item in payload["gold_cases"]:
            evaluation = item["evaluation"]
            writer.writerow({
                "gold_id": item["id"],
                "case_id": item["case_id"],
                "title": item["title"],
                "patient_id": item.get("patient_id") or "",
                "severity": item.get("severity") or "medium",
                "latest_request_id": item.get("latest_request_id") or "",
                "latest_model": item.get("latest_model") or "",
                "score_percent": evaluation.get("score_percent", 0),
                "status": evaluation.get("status", ""),
                "icd10_match": evaluation.get("icd10_match"),
                "red_flags_match": evaluation.get("red_flags_match"),
                "missing_data_match": evaluation.get("missing_data_match"),
                "abstain_match": evaluation.get("abstain_match"),
                "diagnosis_match": evaluation.get("diagnosis_match"),
                "expected_icd10": "; ".join(item.get("expected_icd10") or []),
                "expected_red_flags": "; ".join(item.get("expected_red_flags") or []),
                "expected_missing_data": "; ".join(item.get("expected_missing_data") or []),
                "expected_abstain": item.get("expected_abstain"),
                "expected_diagnosis": item.get("expected_diagnosis") or "",
                "notes": item.get("notes") or "",
            })
        return self.response(200, output.getvalue().encode("utf-8"), [
            ("Content-Type", "text/csv; charset=utf-8"),
            ("Content-Disposition", 'attachment; filename="cvd-gold-set.csv"'),
        ])

    def admin_gold_set_report_html(self):
        payload = self.gold_set_payload()
        summary = payload["summary"]
        gate = "PASS" if summary["release_gate_ok"] else "BLOCKED"
        rows = []
        for item in payload["gold_cases"]:
            evaluation = item["evaluation"]
            rows.append(
                "<tr>"
                f"<td>{escape(str(item['case_id']))}</td>"
                f"<td>{escape(item['title'])}</td>"
                f"<td>{escape(str(item.get('severity') or 'medium'))}</td>"
                f"<td>{escape(str(evaluation.get('score_percent', 0)))}%</td>"
                f"<td>{escape(str(evaluation.get('status') or ''))}</td>"
                f"<td>{escape(str(item.get('latest_model') or ''))}</td>"
                f"<td>{escape('; '.join(item.get('expected_icd10') or []))}</td>"
                "</tr>"
            )
        html = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>CVD Gold Set validation report</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, sans-serif; margin: 32px; color: #111827; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 18px; }}
    th, td {{ border: 1px solid #d1d5db; padding: 8px 10px; text-align: left; vertical-align: top; }}
    th {{ background: #f3f4f6; }}
    .summary {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }}
    .pill {{ border: 1px solid #d1d5db; border-radius: 999px; padding: 4px 10px; background: #f9fafb; }}
    .pass {{ color: #047857; border-color: #a7f3d0; background: #ecfdf5; }}
    .blocked {{ color: #b45309; border-color: #fde68a; background: #fffbeb; }}
  </style>
</head>
<body>
  <h1>CVD Gold Set validation report</h1>
  <p>Generated: {escape(utc_now())}</p>
  <div class="summary">
    <span class="pill {'pass' if summary['release_gate_ok'] else 'blocked'}">Gate: {gate}</span>
    <span class="pill">Cases: {summary['gold_cases']}</span>
    <span class="pill">Evaluated: {summary['evaluated']}</span>
    <span class="pill">Average score: {summary['avg_score_percent']}%</span>
    <span class="pill">Threshold: {summary['min_score_percent']}%</span>
    <span class="pill">Reasons: {escape(', '.join(summary['release_gate_reasons']) or 'none')}</span>
  </div>
  <table>
    <thead><tr><th>Case ID</th><th>Title</th><th>Severity</th><th>Score</th><th>Status</th><th>Model</th><th>Expected ICD-10</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</body>
</html>"""
        return self.response(200, html.encode("utf-8"), [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Disposition", 'inline; filename="cvd-gold-set-report.html"'),
        ])

    def admin_upsert_gold_case(self, request: Request, admin: dict[str, Any]):
        data = request.json()
        try:
            case_id = int(data.get("case_id"))
        except (TypeError, ValueError) as exc:
            raise HTTPError(400, "Некорректный case_id") from exc
        expected_diagnosis = str(data.get("expected_diagnosis", "")).strip()[:2000]
        expected_icd10 = self.normalized_text_list(data.get("expected_icd10"), upper=True, max_item_length=20)
        expected_red_flags = self.normalized_text_list(data.get("expected_red_flags"), max_item_length=240)
        expected_missing_data = self.normalized_text_list(data.get("expected_missing_data"), max_item_length=240)
        expected_abstain = str(data.get("expected_abstain", "")).strip().lower() in {"1", "true", "yes", "on"}
        severity = str(data.get("severity", "medium")).strip().lower()
        if severity not in {"low", "medium", "high", "critical"}:
            raise HTTPError(400, "severity должен быть low, medium, high или critical")
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
                   expected_missing_data_json, expected_abstain, severity, notes, created_by_user_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                  title = excluded.title,
                  expected_diagnosis = excluded.expected_diagnosis,
                  expected_icd10_json = excluded.expected_icd10_json,
                  expected_red_flags_json = excluded.expected_red_flags_json,
                  expected_missing_data_json = excluded.expected_missing_data_json,
                  expected_abstain = excluded.expected_abstain,
                  severity = excluded.severity,
                  notes = excluded.notes,
                  updated_at = excluded.updated_at
                """,
                (
                    case_id,
                    case["title"],
                    expected_diagnosis,
                    json.dumps(expected_icd10, ensure_ascii=False),
                    json.dumps(expected_red_flags, ensure_ascii=False),
                    json.dumps(expected_missing_data, ensure_ascii=False),
                    1 if expected_abstain else 0,
                    severity,
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
                    "expected_missing_data": expected_missing_data,
                    "expected_abstain": expected_abstain,
                    "severity": severity,
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
            "gold_min_score_percent": self.gold_gate_threshold(settings),
            "created_from": "latest_successful_results",
        }
        with connect(self.config.db_path) as conn:
            rows = conn.execute(
                """
                SELECT
                  g.id, g.case_id, g.title, g.expected_diagnosis, g.expected_icd10_json,
                  g.expected_red_flags_json, g.expected_missing_data_json, g.expected_abstain,
                  g.severity, g.notes, g.created_at, g.updated_at,
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
            summary = self.gold_set_summary(items, min_score_percent=self.gold_gate_threshold(settings))
            avg_score = summary["avg_score_percent"]
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
                details={
                    "total_items": len(items),
                    "evaluated_items": len(evaluated),
                    "avg_score_percent": avg_score,
                    "release_gate_ok": summary["release_gate_ok"],
                    "release_gate_reasons": summary["release_gate_reasons"],
                },
            )
        return self.json_response({
            "ok": True,
            "run_id": run_id,
            "summary": {
                "total_items": len(items),
                "evaluated_items": len(evaluated),
                "avg_score_percent": avg_score,
                "min_score_percent": summary["min_score_percent"],
                "release_gate_ok": summary["release_gate_ok"],
                "release_gate_reasons": summary["release_gate_reasons"],
            },
        }, status=201)

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
        item["expected_missing_data"] = json.loads(item.pop("expected_missing_data_json") or "[]")
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
                "missing_data_match": None,
                "abstain_match": None,
                "diagnosis_match": None,
                "actual_icd10": [],
                "actual_red_flags": [],
                "actual_missing_data": [],
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
        actual_missing_data = cds.get("missing_data", []) if isinstance(cds, dict) else []
        if not isinstance(actual_missing_data, list):
            actual_missing_data = []
        if isinstance(possible, list):
            for diagnosis in possible:
                if isinstance(diagnosis, dict) and isinstance(diagnosis.get("missing_data"), list):
                    actual_missing_data.extend(diagnosis.get("missing_data", []))
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
        expected_missing_data = [str(value).strip().lower() for value in item.get("expected_missing_data") or [] if str(value).strip()]
        expected_diagnosis = str(item.get("expected_diagnosis") or "").strip().lower()
        icd10_match = bool(expected_icd10 & actual_icd10) if expected_icd10 else None
        if expected_red_flags:
            red_flags_text = " ".join(str(flag).lower() for flag in actual_red_flags)
            red_flags_match = all(flag in red_flags_text for flag in expected_red_flags)
        else:
            red_flags_match = len(actual_red_flags) == 0
        if expected_missing_data:
            missing_data_text = " ".join(str(value).lower() for value in actual_missing_data)
            missing_data_match = all(value in missing_data_text for value in expected_missing_data)
        else:
            missing_data_match = None
        abstain_match = actual_abstain == bool(item.get("expected_abstain"))
        diagnosis_match = expected_diagnosis in summary_text if expected_diagnosis else None
        scored = [value for value in (icd10_match, red_flags_match, missing_data_match, abstain_match, diagnosis_match) if value is not None]
        score_percent = round(sum(1 for value in scored if value) * 100 / len(scored)) if scored else 0
        return {
            "status": "evaluated",
            "score_percent": score_percent,
            "icd10_match": icd10_match,
            "red_flags_match": red_flags_match,
            "missing_data_match": missing_data_match,
            "abstain_match": abstain_match,
            "diagnosis_match": diagnosis_match,
            "actual_icd10": sorted(actual_icd10),
            "actual_red_flags": actual_red_flags,
            "actual_missing_data": actual_missing_data,
            "actual_abstain": actual_abstain,
        }

