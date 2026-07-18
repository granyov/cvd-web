"""Импорт клинических документов и HTML-отчёты."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .auth import utc_now
from .db import audit, connect, rows_to_dicts
from .integration_import import KNOWN_PATHS, parse_clinical_import
from .pdf_text import PDFTextError, extract_pdf_text
from .reporting import build_html_report
from .web_core import HTTPError, Request


class ImportExportMixin:
    def import_pdf_text(self, request: Request, user: dict[str, Any]):
        self.ensure_request_size(request)
        self.enforce_rate_limit(
            f"pdf-import:{user['id']}",
            limit=60,
            window_seconds=3600,
            message="Слишком много PDF-импортов",
        )
        raw = request.body()
        if not raw:
            raise HTTPError(400, "Пустой файл")
        try:
            result = extract_pdf_text(raw)
        except PDFTextError as exc:
            raise HTTPError(400, str(exc)) from exc
        if not result["has_text_layer"]:
            raise HTTPError(
                422,
                "В PDF не найден текстовый слой — похоже, это скан. "
                "Скопируйте текст из документа вручную или используйте OCR, затем вставьте его в AI-подготовку.",
            )
        with connect(self.config.db_path) as conn:
            audit(
                conn,
                user_id=user["id"],
                action="pdf_text_extract",
                target_type="import",
                target_id="",
                details={"pages": result["pages"], "chars": len(result["text"]), "bytes": len(raw)},
            )
        return self.json_response({"ok": True, "text": result["text"], "pages": result["pages"]})

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

