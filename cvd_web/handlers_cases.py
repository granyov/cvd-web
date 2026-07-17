"""CRUD кейсов, архив и FHIR-экспорт."""
from __future__ import annotations

import json
from typing import Any

from .auth import utc_now
from .db import audit, connect, row_to_dict, rows_to_dicts
from .demo import DEMO_CASE_TITLE, demo_case_payload
from .fhir import build_fhir_bundle
from .quality import case_quality_summary, patient_data_hash
from .web_core import HTTPError, Request


class CasesMixin:
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

    def create_demo_case(self, user: dict[str, Any]):
        patient_data = self.normalized_patient_data(demo_case_payload())
        now = utc_now()
        payload = json.dumps(patient_data, ensure_ascii=False)
        patient_id = str(patient_data.get("GENERAL_INFO", {}).get("Patient_ID") or "").strip()[:120]
        with connect(self.config.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO cases (user_id, title, patient_id, data_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user["id"], DEMO_CASE_TITLE, patient_id, payload, now, now),
            )
            saved_id = int(cur.lastrowid)
            audit(conn, user_id=user["id"], action="case_create_demo", target_type="case", target_id=saved_id)
        return self.json_response({"ok": True, "case_id": saved_id, "title": DEMO_CASE_TITLE}, 201)

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

    def case_title(self, patient_data: dict[str, Any]) -> str:
        general = patient_data.get("GENERAL_INFO", {})
        patient_id = str(general.get("Patient_ID") or "").strip()
        full_name = str(general.get("Full_name") or "").strip()
        diagnosis = str(patient_data.get("FINAL_DIAGNOSES", {}).get("Main_cardiovascular_diagnosis_text") or "").strip()
        identity = " · ".join(item for item in (full_name, patient_id) if item)
        if identity and diagnosis:
            return f"{identity}: {diagnosis[:80]}"
        return identity or diagnosis[:100] or "Новый CVD-кейс"

