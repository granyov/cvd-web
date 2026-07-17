"""Аутентификация и управление собственным паролем."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .auth import hash_password, new_token, utc_now, verify_password
from .db import DEFAULT_ADMIN_PASSWORDS, audit, connect, row_to_dict
from .web_core import COMMON_PASSWORDS, HTTPError, MIN_PASSWORD_LENGTH, Request


class AuthMixin:
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
            if user["role"] == "admin" and not user["must_change_password"] and password in DEFAULT_ADMIN_PASSWORDS:
                conn.execute(
                    "UPDATE users SET must_change_password = 1, updated_at = ? WHERE id = ?",
                    (now_dt.isoformat(), user["id"]),
                )
                audit(conn, user_id=user["id"], action="default_password_login", target_type="user", target_id=user["id"])
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

    def validate_new_password(self, password: str, *, email: str = "") -> None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise HTTPError(400, f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов")
        normalized = password.strip().lower()
        email_local = email.split("@", 1)[0].lower() if email else ""
        if normalized in COMMON_PASSWORDS or (email_local and normalized == email_local):
            raise HTTPError(400, "Пароль слишком предсказуемый")

