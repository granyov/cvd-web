"""AI-инференс: очередь, задания, история запросов и оценки."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import re
import traceback
from contextlib import contextmanager
from typing import Any

from .auth import utc_now
from .db import audit, connect, row_to_dict, rows_to_dicts, update_app_settings
from .inference_queue import InferenceQueueError
from .lmstudio import LMStudioError, call_lm_studio, estimate_prompt_tokens
from .lmstudio_models import LMStudioManagementError, list_lm_models
from .privacy import deidentify_patient_data
from .quality import has_clinical_input, patient_data_changes, patient_data_hash
from .text_structuring import TEXT_MAX_INPUT_CHARS, TEXT_STRUCTURING_VERSION, call_text_structuring
from .versions import MODEL_OUTPUT_SCHEMA_VERSION, MODEL_PROMPT_VERSION, PATIENT_SCHEMA_VERSION
from .web_core import HTTPError, Request


class AiMixin:
    def inference_status(self, user: dict[str, Any]):
        settings = self.load_settings()
        self.configure_inference_queue(settings)
        return self.json_response({"queue": self.inference_queue.snapshot(user_id=user["id"])})

    def case_context_usage(self, patient_data: dict[str, Any], settings: dict[str, str]) -> dict[str, Any]:
        """Оценка объёма случая относительно контекста модели."""
        estimate = estimate_prompt_tokens(patient_data, settings.get("active_prompt_template") or None)
        context_limit = self.setting_int(settings, "lm_studio_context_tokens", 0)
        reserve = self.setting_int(settings, "lm_studio_max_tokens", 1536)
        # Ответу модели тоже нужно место в контексте, поэтому вычитаем max_tokens.
        available = max(0, context_limit - reserve) if context_limit else 0
        return {
            "estimated_tokens": estimate,
            "context_tokens": context_limit,
            "available_tokens": available,
            "fits": not available or estimate <= available,
        }

    def refresh_context_tokens(self, settings: dict[str, str]) -> int | None:
        """Перечитывает контекст загруженной модели у LM Studio.

        Возвращает None, если проверить не удалось: тогда задание пропускаем,
        чтобы врач получил настоящую ошибку сервиса, а не выдуманный отказ.
        """
        api_url = settings.get("lm_studio_api_url") or self.config.lm_studio_api_url
        selected_model = settings.get("lm_studio_model") or self.config.lm_studio_model
        try:
            catalog = list_lm_models(api_url, timeout_seconds=10, extra_headers=self.ai_gateway_headers(settings))
        except LMStudioManagementError:
            return None
        selected = next((item for item in catalog["models"] if item["id"] == selected_model), None)
        context = selected.get("loaded_context_length") if selected else None
        if not context:
            return None
        with connect(self.config.db_path) as conn:
            update_app_settings(conn, {"lm_studio_context_tokens": str(int(context))})
        return int(context)

    def ensure_case_fits_context(self, patient_data: dict[str, Any], settings: dict[str, str]) -> None:
        usage = self.case_context_usage(patient_data, settings)
        if usage["fits"]:
            return
        # Сохранённый контекст мог устареть: модель могли перезагрузить с другим размером.
        # Отказываем только по свежему, подтверждённому значению.
        refreshed = self.refresh_context_tokens(settings)
        if refreshed is None:
            return
        usage = self.case_context_usage(patient_data, {**settings, "lm_studio_context_tokens": str(refreshed)})
        if usage["fits"]:
            return
        raise HTTPError(
            413,
            "Случай слишком большой для текущей модели: примерно "
            f"{usage['estimated_tokens']} токенов при доступных {usage['available_tokens']}. "
            "Сократите объёмные текстовые поля (анамнез, описания исследований) "
            "или попросите администратора увеличить контекст модели.",
        )

    def user_friendly_ai_error(self, message: str | None) -> str:
        """Техническая ошибка -> действие для врача.

        Порядок проверок важен: LM Studio часто возвращает в теле ошибки эхо
        исходного запроса, поэтому специфичные признаки (контекст, ресурсы,
        сеть) проверяются до общих упоминаний JSON и схемы.
        """
        text = str(message or "").strip()
        # Эхо тела запроса не должно влиять на классификацию и попадать в UI.
        head = re.split(r"Request body|\"messages\"|PATIENT_JSON", text, maxsplit=1)[0]
        lowered = head.lower()
        if not text:
            return "AI-задание завершилось без результата. Повторите запрос или сообщите администратору."
        context_markers = ("context the overflows", "context length", "context window", "too many tokens", "maximum context", "context_length_exceeded")
        if any(marker in lowered for marker in context_markers) or ("token" in lowered and "not enough" in lowered):
            return (
                "Случай слишком большой для текущей модели: данные не помещаются в её контекст. "
                "Повтор не поможет — сократите объёмные текстовые поля (анамнез, описания исследований) "
                "или попросите администратора увеличить контекст модели."
            )
        if "524" in lowered or "cloudflare" in lowered:
            return (
                "Сервис CVD Engine не успел вернуть ответ через защищённый канал. "
                "Повторите запрос; если повторяется — сообщите администратору."
            )
        if "timeout" in lowered or "timed out" in lowered or "не ответ" in lowered:
            return "Модель отвечает слишком долго. Повторите позже или в менее загруженное время."
        if "memory" in lowered or "ресурс" in lowered or "insufficient" in lowered:
            return "Сервису CVD Engine не хватило ресурсов для этой модели. Сообщите администратору."
        if "connection" in lowered or "connect" in lowered or "unreachable" in lowered or "refused" in lowered:
            return "Сервис CVD Engine сейчас недоступен. Повторите запрос через минуту; если не помогает — сообщите администратору."
        if "очеред" in lowered or "queue" in lowered:
            return "Очередь AI сейчас занята. Дождитесь выполнения предыдущих заданий."
        if "json" in lowered or "schema" in lowered or "структур" in lowered or "parse" in lowered:
            return "Ответ модели не удалось привести к ожидаемой структуре. Данные сохранены, запрос можно повторить."
        return head.strip()[:300] or "AI-задание завершилось ошибкой. Повторите запрос или сообщите администратору."

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

    def ai_gateway_headers(self, settings: dict[str, str]) -> dict[str, str]:
        entries = self.ai_gateway_header_entries(settings)
        headers: dict[str, str] = {}
        original_names_by_lower: dict[str, str] = {}
        for entry in entries:
            name = entry["name"]
            lower_name = name.lower()
            previous_name = original_names_by_lower.get(lower_name)
            if previous_name:
                headers.pop(previous_name, None)
            original_names_by_lower[lower_name] = name
            headers[name] = entry["value"]
        return headers

    def ai_gateway_header_entries(self, settings: dict[str, str]) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        raw_json = str(settings.get("ai_gateway_headers_json") or "").strip()
        if raw_json:
            try:
                decoded = json.loads(raw_json)
            except json.JSONDecodeError as exc:
                raise HTTPError(400, "ai_gateway_headers_json должен быть корректным JSON") from exc
            if not isinstance(decoded, list):
                raise HTTPError(400, "ai_gateway_headers_json должен быть списком")
            if len(decoded) > 12:
                raise HTTPError(400, "AI Gateway поддерживает не более 12 дополнительных заголовков")
            for item in decoded:
                if not isinstance(item, dict):
                    raise HTTPError(400, "Каждый auth-заголовок AI Gateway должен быть объектом")
                name = str(item.get("name") or "").strip()
                value = str(item.get("value") or "").strip()
                if not name and not value:
                    continue
                if not name or not value:
                    raise HTTPError(400, "У каждого auth-заголовка AI Gateway должны быть name и value")
                self.validate_ai_gateway_header_name(name)
                entries.append({"name": name[:80], "value": value[:4000]})
            return entries
        name = str(settings.get("ai_gateway_auth_header_name") or "").strip()
        value = str(settings.get("ai_gateway_auth_header_value") or "").strip()
        if not name or not value:
            return []
        self.validate_ai_gateway_header_name(name)
        return [{"name": name[:80], "value": value[:4000]}]

    def validate_ai_gateway_header_name(self, name: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9!#$%&'*+.^_`|~-]{1,80}", name):
            raise HTTPError(400, "Некорректное имя auth-заголовка AI Gateway")
        blocked = {"host", "content-length", "content-type", "accept", "connection"}
        if name.lower() in blocked:
            raise HTTPError(400, "Этот auth-заголовок нельзя переопределять")

    def ai_gateway_public_profile(self, settings: dict[str, str]) -> dict[str, Any]:
        profile = str(settings.get("ai_gateway_profile") or "local").strip().lower()
        header_entries = self.ai_gateway_header_entries(settings)
        return {
            "profile": profile,
            "api_url": settings.get("lm_studio_api_url") or self.config.lm_studio_api_url,
            "selected_model": settings.get("lm_studio_model") or self.config.lm_studio_model,
            "auth_header_configured": bool(header_entries),
            "auth_header_count": len(header_entries),
            "auth_header_names": [entry["name"] for entry in header_entries],
        }

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

    def parse_diagnosis_payload(self, request: Request, user: dict[str, Any], settings: dict[str, str]) -> tuple[dict[str, Any], int | None]:
        self.ensure_request_size(request, settings)
        data = request.json()
        patient_data = self.normalized_patient_data(data.get("patient_data"))
        if not has_clinical_input(patient_data):
            raise HTTPError(400, "Добавьте данные пациента перед запуском AI-анализа")
        case_id = data.get("case_id")
        if case_id is not None:
            try:
                case_id = int(case_id)
            except (TypeError, ValueError) as exc:
                raise HTTPError(400, "Некорректный case_id") from exc
            with connect(self.config.db_path) as conn:
                case_exists = conn.execute(
                    "SELECT 1 FROM cases WHERE id = ? AND (user_id = ? OR ? = 'admin')",
                    (case_id, user["id"], user["role"]),
                ).fetchone()
            if not case_exists:
                raise HTTPError(404, "Кейс не найден")
        return patient_data, case_id

    def active_ai_job_count(self, conn: sqlite3.Connection, user_id: int) -> int:
        diagnosis_count = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM inference_jobs
            WHERE user_id = ? AND status IN ('queued', 'running')
            """,
            (user_id,),
        ).fetchone()["c"]
        text_count = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM text_preparation_jobs
            WHERE user_id = ? AND status IN ('queued', 'running')
            """,
            (user_id,),
        ).fetchone()["c"]
        return int(diagnosis_count or 0) + int(text_count or 0)

    def enforce_user_ai_job_limit(self, conn: sqlite3.Connection, user_id: int, settings: dict[str, str]) -> None:
        per_user_limit = self.setting_int(settings, "lm_studio_per_user_limit", 2)
        outstanding = self.active_ai_job_count(conn, user_id)
        if outstanding >= per_user_limit:
            raise HTTPError(
                429,
                f"У пользователя уже есть {outstanding} AI-задания в очереди или выполнении. Дождитесь результата.",
            )

    def create_diagnosis_job(self, request: Request, user: dict[str, Any]):
        settings = self.load_settings()
        self.enforce_rate_limit(
            f"model:{user['id']}",
            limit=30,
            window_seconds=3600,
            message="Слишком много запросов к модели",
        )
        patient_data, case_id = self.parse_diagnosis_payload(request, user, settings)
        self.ensure_case_fits_context(patient_data, settings)
        now = utc_now()
        with connect(self.config.db_path) as conn:
            self.enforce_user_ai_job_limit(conn, user["id"], settings)
            cur = conn.execute(
                """
                INSERT INTO inference_jobs
                  (user_id, case_id, status, request_json, created_at)
                VALUES (?, ?, 'queued', ?, ?)
                """,
                (
                    user["id"],
                    case_id,
                    json.dumps({"patient_data": patient_data}, ensure_ascii=False),
                    now,
                ),
            )
            job_id = int(cur.lastrowid)
            audit(
                conn,
                user_id=user["id"],
                action="inference_job_create",
                target_type="inference_job",
                target_id=job_id,
                details={"case_id": case_id},
            )
        self.inference_worker_event.set()
        return self.json_response({"ok": True, "job_id": job_id, "status": "queued"}, status=201)

    def model_request_payload(self, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        getter = row.get if isinstance(row, dict) else lambda key, default=None: row[key] if key in row.keys() else default
        parsed_output = None
        response_payload = None
        try:
            parsed_output = json.loads(getter("parsed_output_json") or "null")
        except (TypeError, json.JSONDecodeError):
            parsed_output = None
        try:
            response_payload = json.loads(getter("response_json") or "null")
        except (TypeError, json.JSONDecodeError):
            response_payload = None
        return {
            "ok": getter("status") == "success",
            "request_id": getter("id"),
            "response": response_payload,
            "parsed": parsed_output,
            "error": getter("error"),
            "user_error": self.user_friendly_ai_error(getter("error")),
            "duration_ms": getter("duration_ms") or 0,
            "queue_wait_ms": getter("queue_wait_ms") or 0,
            "prompt_tokens": getter("prompt_tokens") or 0,
            "completion_tokens": getter("completion_tokens") or 0,
            "total_tokens": getter("total_tokens") or 0,
            "tokens_per_second": getter("tokens_per_second") or 0,
            "finish_reason": getter("finish_reason") or "",
            "prompt_version": getter("prompt_version") or "",
            "schema_version": getter("schema_version") or "",
            "output_schema_version": getter("output_schema_version") or "",
        }

    def get_diagnosis_job(self, user: dict[str, Any], job_id: int):
        with connect(self.config.db_path) as conn:
            job = conn.execute(
                """
                SELECT *
                FROM inference_jobs
                WHERE id = ? AND (user_id = ? OR ? = 'admin')
                """,
                (job_id, user["id"], user["role"]),
            ).fetchone()
            if not job:
                raise HTTPError(404, "AI-задание не найдено")
            request_row = None
            if job["model_request_id"]:
                request_row = conn.execute(
                    "SELECT * FROM model_requests WHERE id = ?",
                    (job["model_request_id"],),
                ).fetchone()
        payload = {
            "ok": True,
            "job": {
                "id": job["id"],
                "status": job["status"],
                "case_id": job["case_id"],
                "model_request_id": job["model_request_id"],
                "error": job["error"],
                "user_error": self.user_friendly_ai_error(job["error"]),
                "created_at": job["created_at"],
                "started_at": job["started_at"],
                "finished_at": job["finished_at"],
            },
        }
        if request_row:
            payload["result"] = self.model_request_payload(request_row)
        return self.json_response(payload)

    def parse_structure_text_payload(self, request: Request, settings: dict[str, str]) -> str:
        self.ensure_request_size(request, settings)
        data = request.json()
        source_text = str(data.get("text") or "").strip()
        if len(source_text) < 10:
            raise HTTPError(400, "Добавьте медицинский текст длиной не менее 10 символов")
        if len(source_text) > TEXT_MAX_INPUT_CHARS:
            raise HTTPError(413, f"Текст не должен превышать {TEXT_MAX_INPUT_CHARS:,} символов".replace(",", " "))
        return source_text

    def execute_text_preparation(
        self,
        *,
        user: dict[str, Any],
        source_text: str,
        settings: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        settings = settings or self.load_settings()
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
            if isinstance(exc, LMStudioError) and not queue_error and isinstance(response_payload, dict):
                result = {
                    "corrected_text": source_text[:20000],
                    "mappings": [],
                    "warnings": [
                        "AI не вернул пригодную структуру полей CVD. Исходный текст сохранён для ручной проверки.",
                        error,
                    ],
                }

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
            data_preparation_request_id = int(prep_cur.lastrowid)
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
                        data_preparation_request_id,
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
                target_id=data_preparation_request_id,
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
            return {
                "ok": False,
                "data_preparation_request_id": data_preparation_request_id,
                "import_id": import_id,
                "error": error,
                "queue_error": queue_error,
                "duration_ms": duration_ms,
                "queue_wait_ms": queue_wait_ms,
                "chunk_count": chunk_count,
                "failed_chunk_count": failed_chunk_count,
                **metrics,
            }
        return {
            "ok": True,
            "data_preparation_request_id": data_preparation_request_id,
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
        }

    def create_text_preparation_job(self, request: Request, user: dict[str, Any]):
        settings = self.load_settings()
        self.enforce_rate_limit(
            f"structure-text:{user['id']}",
            limit=30,
            window_seconds=3600,
            message="Слишком много запросов на подготовку данных",
        )
        source_text = self.parse_structure_text_payload(request, settings)
        content_sha256 = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        now = utc_now()
        with connect(self.config.db_path) as conn:
            self.enforce_user_ai_job_limit(conn, user["id"], settings)
            cur = conn.execute(
                """
                INSERT INTO text_preparation_jobs
                  (user_id, status, request_json, input_sha256, created_at)
                VALUES (?, 'queued', ?, ?, ?)
                """,
                (
                    user["id"],
                    json.dumps({"text": source_text}, ensure_ascii=False),
                    content_sha256,
                    now,
                ),
            )
            job_id = int(cur.lastrowid)
            audit(
                conn,
                user_id=user["id"],
                action="text_preparation_job_create",
                target_type="text_preparation_job",
                target_id=job_id,
                details={"input_sha256": content_sha256, "chars": len(source_text)},
            )
        self.inference_worker_event.set()
        return self.json_response({"ok": True, "job_id": job_id, "status": "queued"}, status=201)

    def text_preparation_job_payload(self, row: sqlite3.Row | dict[str, Any], *, include_result: bool = True) -> dict[str, Any]:
        getter = row.get if isinstance(row, dict) else lambda key, default=None: row[key] if key in row.keys() else default
        result = None
        if include_result and getter("result_json"):
            try:
                result = json.loads(getter("result_json") or "null")
            except (TypeError, json.JSONDecodeError):
                result = None
        text_preview = ""
        try:
            request_data = json.loads(getter("request_json") or "{}")
            text_preview = str(request_data.get("text_preview") or request_data.get("text") or "").strip()[:120]
        except (TypeError, json.JSONDecodeError):
            text_preview = ""
        payload: dict[str, Any] = {
            "id": getter("id"),
            "status": getter("status"),
            "data_preparation_request_id": getter("data_preparation_request_id"),
            "import_id": getter("import_id"),
            "error": getter("error"),
            "user_error": self.user_friendly_ai_error(getter("error")),
            "input_sha256": getter("input_sha256"),
            "text_preview": text_preview,
            "created_at": getter("created_at"),
            "started_at": getter("started_at"),
            "finished_at": getter("finished_at"),
        }
        if result is not None:
            payload["result"] = result
        return payload

    def get_text_preparation_job(self, user: dict[str, Any], job_id: int):
        with connect(self.config.db_path) as conn:
            job = conn.execute(
                """
                SELECT *
                FROM text_preparation_jobs
                WHERE id = ? AND (user_id = ? OR ? = 'admin')
                """,
                (job_id, user["id"], user["role"]),
            ).fetchone()
        if not job:
            raise HTTPError(404, "AI-задача подготовки текста не найдена")
        return self.json_response({"ok": True, "job": self.text_preparation_job_payload(job)})

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

    def list_ai_jobs(self, user: dict[str, Any]):
        with connect(self.config.db_path) as conn:
            rows = conn.execute(
                """
                SELECT type, id, status, created_at, started_at, finished_at, error,
                       case_id, model_request_id, input_sha256, data_preparation_request_id,
                       import_id, request_json, result_json, case_title, patient_id,
                       created_by_user_id, created_by_email, created_by_name
                FROM (
                  SELECT 'diagnosis' AS type, j.id, j.status, j.created_at, j.started_at, j.finished_at, j.error,
                         j.case_id, j.model_request_id, NULL AS input_sha256, NULL AS data_preparation_request_id,
                         NULL AS import_id, j.request_json, NULL AS result_json,
                         c.title AS case_title, c.patient_id,
                         u.id AS created_by_user_id, u.email AS created_by_email, u.full_name AS created_by_name
                  FROM inference_jobs j
                  JOIN users u ON u.id = j.user_id
                  LEFT JOIN cases c ON c.id = j.case_id AND c.user_id = j.user_id
                  WHERE j.user_id = ? OR ? = 'admin'
                  UNION ALL
                  SELECT 'text_preparation' AS type, j.id, j.status, j.created_at, j.started_at, j.finished_at, j.error,
                         NULL AS case_id, NULL AS model_request_id, j.input_sha256, j.data_preparation_request_id,
                         j.import_id, j.request_json, j.result_json,
                         NULL AS case_title, NULL AS patient_id,
                         u.id AS created_by_user_id, u.email AS created_by_email, u.full_name AS created_by_name
                  FROM text_preparation_jobs j
                  JOIN users u ON u.id = j.user_id
                  WHERE j.user_id = ? OR ? = 'admin'
                )
                WHERE status IN ('queued', 'running', 'success', 'error')
                ORDER BY
                  CASE WHEN status IN ('queued', 'running') THEN 0 ELSE 1 END,
                  CASE WHEN status IN ('queued', 'running') THEN created_at ELSE NULL END ASC,
                  CASE WHEN status NOT IN ('queued', 'running') THEN COALESCE(finished_at, created_at) ELSE NULL END DESC,
                  type,
                  id
                LIMIT 20
                """,
                (user["id"], user["role"], user["id"], user["role"]),
            ).fetchall()
            queued_order = conn.execute(
                """
                SELECT type, id
                FROM (
                  SELECT 'diagnosis' AS type, id, created_at FROM inference_jobs WHERE status = 'queued'
                  UNION ALL
                  SELECT 'text_preparation' AS type, id, created_at FROM text_preparation_jobs WHERE status = 'queued'
                )
                ORDER BY created_at, type, id
                """,
            ).fetchall()
        positions = {(row["type"], row["id"]): index + 1 for index, row in enumerate(queued_order)}
        jobs: list[dict[str, Any]] = []
        for row in rows:
            item = row_to_dict(row)
            job: dict[str, Any] = {
                "type": item["type"],
                "id": item["id"],
                "status": item["status"],
                "created_at": item["created_at"],
                "started_at": item["started_at"],
                "finished_at": item["finished_at"],
                "error": item["error"],
                "user_error": self.user_friendly_ai_error(item["error"]),
                "position": positions.get((item["type"], item["id"]), 0),
                "queue_ahead": max(0, positions.get((item["type"], item["id"]), 0) - 1),
                "created_by": {
                    "id": item.get("created_by_user_id"),
                    "email": item.get("created_by_email") or "",
                    "name": item.get("created_by_name") or "",
                },
            }
            if item["type"] == "diagnosis":
                job.update({
                    "case_id": item["case_id"],
                    "model_request_id": item["model_request_id"],
                    "case_title": item.get("case_title") or "",
                    "patient_id": item.get("patient_id") or "",
                })
            else:
                job.update(self.text_preparation_job_payload(item, include_result=False))
                job["type"] = "text_preparation"
                job["created_by"] = {
                    "id": item.get("created_by_user_id"),
                    "email": item.get("created_by_email") or "",
                    "name": item.get("created_by_name") or "",
                }
                job["position"] = positions.get((item["type"], item["id"]), 0)
                job["queue_ahead"] = max(0, job["position"] - 1)
            jobs.append(job)
        active_jobs = [item for item in jobs if item["status"] in {"queued", "running"}]
        return self.json_response({
            "ok": True,
            "jobs": jobs,
            "active_count": len(active_jobs),
            "queued_count": sum(1 for item in active_jobs if item["status"] == "queued"),
            "running_count": sum(1 for item in active_jobs if item["status"] == "running"),
        })

    def cancel_ai_job(self, user: dict[str, Any], job_type: str, job_id: int):
        job_map = {
            "diagnosis": ("inference_jobs", "inference_job_cancel"),
            "text_preparation": ("text_preparation_jobs", "text_preparation_job_cancel"),
        }
        if job_type not in job_map:
            raise HTTPError(404, "AI-задание не найдено")
        table, action = job_map[job_type]
        now = utc_now()
        with connect(self.config.db_path) as conn:
            row = conn.execute(
                f"SELECT id, user_id, status, request_json FROM {table} WHERE id = ? AND (user_id = ? OR ? = 'admin')",
                (job_id, user["id"], user["role"]),
            ).fetchone()
            if not row:
                raise HTTPError(404, "AI-задание не найдено")
            if row["status"] != "queued":
                if row["status"] == "running":
                    raise HTTPError(409, "Задание уже выполняется. Дождитесь результата или ошибки.")
                raise HTTPError(409, "Это AI-задание уже завершено.")
            request_json = row["request_json"]
            if table == "text_preparation_jobs":
                try:
                    source_text = str(json.loads(request_json or "{}").get("text") or "")
                    request_json = json.dumps({"text_preview": source_text[:120]}, ensure_ascii=False)
                except (TypeError, json.JSONDecodeError):
                    pass
                conn.execute(
                    f"""
                    UPDATE {table}
                    SET status = 'cancelled', error = NULL, request_json = ?, finished_at = ?
                    WHERE id = ? AND status = 'queued'
                    """,
                    (request_json, now, job_id),
                )
            else:
                conn.execute(
                    f"""
                    UPDATE {table}
                    SET status = 'cancelled', error = NULL, finished_at = ?
                    WHERE id = ? AND status = 'queued'
                    """,
                    (now, job_id),
                )
            audit(
                conn,
                user_id=user["id"],
                action=action,
                target_type=job_type,
                target_id=job_id,
                details={"cancelled_by": user["email"]},
            )
        return self.json_response({"ok": True, "status": "cancelled"})

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
        self.enforce_rate_limit(
            f"structure-text:{user['id']}",
            limit=30,
            window_seconds=3600,
            message="Слишком много запросов на подготовку данных",
        )
        source_text = self.parse_structure_text_payload(request, settings)
        result = self.execute_text_preparation(user=user, source_text=source_text, settings=settings)
        if not result["ok"]:
            raise HTTPError(
                429 if result.get("queue_error") else 502,
                "Сервис AI временно не смог подготовить данные. Подробности сохранены для администратора",
            )
        return self.json_response(result)

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
                       rv.corrected_icd10_json AS review_corrected_icd10_json,
                       rv.created_at AS review_created_at, rv.updated_at AS review_updated_at
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
                       rv.corrected_icd10_json AS review_corrected_icd10_json,
                       rv.created_at AS review_created_at, rv.updated_at AS review_updated_at
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
            review_created_at = item.pop("review_created_at")
            review_updated_at = item.pop("review_updated_at")
            item["review"] = {
                "rating": review_rating,
                "issue_types": json.loads(review_issue_types_json) if review_issue_types_json else [],
                "comment": review_comment,
                "corrected_diagnosis": review_corrected_diagnosis,
                "corrected_icd10": json.loads(review_corrected_icd10_json) if review_corrected_icd10_json else [],
                "created_at": review_created_at,
                "updated_at": review_updated_at,
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

    def recover_interrupted_inference_jobs(self) -> None:
        with connect(self.config.db_path) as conn:
            conn.execute(
                "UPDATE inference_jobs SET status = 'queued', started_at = NULL WHERE status = 'running'"
            )

    def recover_interrupted_text_preparation_jobs(self) -> None:
        with connect(self.config.db_path) as conn:
            conn.execute(
                "UPDATE text_preparation_jobs SET status = 'queued', started_at = NULL WHERE status = 'running'"
            )

    def inference_worker_loop(self) -> None:
        while True:
            try:
                processed = self.process_next_inference_job()
            except Exception:
                traceback.print_exc()
                processed = False
            if not processed:
                self.inference_worker_event.wait(2.0)
                self.inference_worker_event.clear()

    def process_next_inference_job(self) -> bool:
        now = utc_now()
        with connect(self.config.db_path) as conn:
            job = conn.execute(
                """
                SELECT job_type, id, user_id, case_id, request_json
                FROM (
                  SELECT 'diagnosis' AS job_type, id, user_id, case_id, request_json, created_at
                  FROM inference_jobs
                  WHERE status = 'queued'
                  UNION ALL
                  SELECT 'text_preparation' AS job_type, id, user_id, NULL AS case_id, request_json, created_at
                  FROM text_preparation_jobs
                  WHERE status = 'queued'
                )
                ORDER BY created_at, job_type, id
                LIMIT 1
                """
            ).fetchone()
            if not job:
                return False
            if job["job_type"] == "diagnosis":
                claimed = conn.execute(
                    "UPDATE inference_jobs SET status = 'running', started_at = ? WHERE id = ? AND status = 'queued'",
                    (now, job["id"]),
                )
            else:
                claimed = conn.execute(
                    "UPDATE text_preparation_jobs SET status = 'running', started_at = ? WHERE id = ? AND status = 'queued'",
                    (now, job["id"]),
                )
            if claimed.rowcount == 0:
                return True
            job_data = row_to_dict(job)

        if job_data["job_type"] == "text_preparation":
            return self.process_text_preparation_job(job_data)
        return self.process_diagnosis_job(job_data)

    def process_diagnosis_job(self, job_data: dict[str, Any]) -> bool:
        request_id = None
        item_status = "error"
        error = None
        try:
            payload = json.loads(job_data["request_json"])
            patient_data = self.normalized_patient_data(payload.get("patient_data"))
            result = self.execute_model_request(
                user_id=job_data["user_id"],
                case_id=job_data["case_id"],
                patient_data=patient_data,
                request_source="queued_interactive",
            )
            request_id = result["request_id"]
            item_status = "success" if result["ok"] else "error"
            error = result.get("error")
        except Exception as exc:
            error = str(exc)[:4000]

        with connect(self.config.db_path) as conn:
            conn.execute(
                """
                UPDATE inference_jobs
                SET status = ?, model_request_id = ?, error = ?, finished_at = ?
                WHERE id = ?
                """,
                (item_status, request_id, error, utc_now(), job_data["id"]),
            )
            audit(
                conn,
                user_id=job_data["user_id"],
                action="inference_job_finish",
                target_type="inference_job",
                target_id=job_data["id"],
                details={"status": item_status, "model_request_id": request_id, "error": bool(error)},
            )
        return True

    def process_text_preparation_job(self, job_data: dict[str, Any]) -> bool:
        item_status = "error"
        error = None
        data_preparation_request_id = None
        import_id = None
        result_json = None
        source_text = ""
        try:
            payload = json.loads(job_data["request_json"])
            source_text = str(payload.get("text") or "").strip()
            if len(source_text) < 10:
                raise ValueError("Некорректное задание подготовки текста")
            result = self.execute_text_preparation(
                user={"id": job_data["user_id"], "role": "user"},
                source_text=source_text,
            )
            data_preparation_request_id = result.get("data_preparation_request_id")
            import_id = result.get("import_id")
            item_status = "success" if result.get("ok") else "error"
            error = result.get("error")
            if result.get("ok"):
                result_json = json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            error = str(exc)[:4000]

        request_preview_json = json.dumps({"text_preview": source_text[:120]}, ensure_ascii=False) if source_text else job_data.get("request_json") or "{}"
        with connect(self.config.db_path) as conn:
            conn.execute(
                """
                UPDATE text_preparation_jobs
                SET status = ?, data_preparation_request_id = ?, import_id = ?, result_json = ?, error = ?,
                    request_json = ?, finished_at = ?
                WHERE id = ?
                """,
                (
                    item_status,
                    data_preparation_request_id,
                    import_id,
                    result_json,
                    error,
                    request_preview_json,
                    utc_now(),
                    job_data["id"],
                ),
            )
            audit(
                conn,
                user_id=job_data["user_id"],
                action="text_preparation_job_finish",
                target_type="text_preparation_job",
                target_id=job_data["id"],
                details={
                    "status": item_status,
                    "data_preparation_request_id": data_preparation_request_id,
                    "import_id": import_id,
                    "error": bool(error),
                },
            )
        return True
