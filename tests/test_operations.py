from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cvd_web.app import CVDApplication
from cvd_web.auth import hash_password, utc_now
from cvd_web.db import connect
from cvd_web.lmstudio import LMStudioError
from cvd_web.text_structuring import (
    MAX_MAPPINGS_PER_CHUNK,
    TEXT_STRUCTURING_SCHEMA,
    build_structuring_request,
    call_text_structuring,
    merge_structuring_results,
    normalize_structuring_output,
    split_clinical_text,
)
from test_core import call_wsgi, make_test_config


class OperationsTests(unittest.TestCase):
    def test_text_structuring_schema_is_bounded(self):
        schema = TEXT_STRUCTURING_SCHEMA["schema"]
        # Потолок должен вмещать типовой протокол: при 14 молча терялись лабораторные
        # показатели и список терапии, которые идут в конце записи.
        self.assertEqual(schema["properties"]["mappings"]["maxItems"], MAX_MAPPINGS_PER_CHUNK)
        self.assertGreaterEqual(MAX_MAPPINGS_PER_CHUNK, 25)
        self.assertEqual(schema["properties"]["corrected_text"]["maxLength"], 600)
        request = build_structuring_request("Бисопролол 5 мг утром", model="test", max_tokens=1536)
        prompt = request["messages"][1]["content"]
        self.assertIn("CURRENT_MEDICATIONS.Beta_blockers [text]", prompt)
        self.assertIn("не заменяй препарат на yes/no", prompt)
        self.assertIn("включая лабораторные показатели и текущую терапию", prompt)
        self.assertIn(f"Максимум {MAX_MAPPINGS_PER_CHUNK} mappings", prompt)

    def test_text_structuring_chunks_and_merges_results(self):
        source = "Первое предложение с данными. Второе предложение с данными. Третье предложение."
        chunks = split_clinical_text(source, max_chars=45)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 45 for chunk in chunks))

        merged = merge_structuring_results([
            {
                "corrected_text": "Часть один.",
                "mappings": [{
                    "path": "GENERAL_INFO.Age",
                    "value": 61,
                    "confidence": "high",
                    "source_conflict": False,
                    "sources": [{"label": "61 год"}],
                }],
                "warnings": [],
            },
            {
                "corrected_text": "Часть два.",
                "mappings": [{
                    "path": "GENERAL_INFO.Age",
                    "value": 62,
                    "confidence": "high",
                    "source_conflict": False,
                    "sources": [{"label": "62 года"}],
                }],
                "warnings": [],
            },
        ])
        self.assertEqual(len(merged["mappings"]), 1)
        self.assertTrue(merged["mappings"][0]["source_conflict"])
        self.assertEqual(merged["mappings"][0]["confidence"], "low")
        self.assertTrue(any("разные значения" in warning for warning in merged["warnings"]))

    def test_long_text_is_processed_in_multiple_model_calls(self):
        def response(summary: str, path: str, value: str):
            content = json.dumps({
                "mappings": [{"path": path, "value": value, "confidence": "high", "evidence": summary}],
                "corrected_text": summary,
                "warnings": [],
            }, ensure_ascii=False)
            return (
                {
                    "choices": [{"finish_reason": "stop", "message": {"content": content}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
                },
                content,
                1000,
            )

        long_text = "А" * 2500
        with patch(
            "cvd_web.text_structuring.call_json_lm_studio",
            side_effect=[
                response("Пациент 61 года.", "GENERAL_INFO.Age", "61"),
                response("ЧСС 90 в минуту.", "PHYSICAL_EXAM.Heart_rate_bpm", "90"),
            ],
        ) as model_call:
            request, payload, result, duration = call_text_structuring(
                api_url="http://127.0.0.1:1234/v1/chat/completions",
                model="test-model",
                text=long_text,
                timeout_seconds=10,
                max_tokens=1536,
            )
        self.assertEqual(model_call.call_count, 2)
        self.assertEqual(request["chunk_count"], 2)
        self.assertEqual(payload["chunk_count"], 2)
        self.assertEqual(payload["raw"]["usage"]["completion_tokens"], 100)
        self.assertEqual(duration, 2000)
        self.assertEqual(len(result["mappings"]), 2)

    def test_text_structuring_retries_a_chunk_only_once(self):
        raw_response = {
            "choices": [{"finish_reason": "length", "message": {"content": '{"mappings": ['}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 1024, "total_tokens": 1124},
        }
        with patch(
            "cvd_web.text_structuring.call_json_lm_studio",
            return_value=(raw_response, '{"mappings": [', 1000),
        ) as model_call:
            with self.assertRaises(LMStudioError) as context:
                call_text_structuring(
                    api_url="http://127.0.0.1:1234/v1/chat/completions",
                    model="test-model",
                    text="А" * 1400,
                    timeout_seconds=300,
                    max_tokens=1536,
                )
        self.assertEqual(model_call.call_count, 3)
        self.assertEqual(context.exception.response_payload["attempt_count"], 3)
        self.assertEqual(context.exception.response_payload["failed_chunk_count"], 1)

    def test_text_structuring_returns_warned_partial_result(self):
        success_content = json.dumps({
            "mappings": [{
                "path": "GENERAL_INFO.Age",
                "value": "61",
                "confidence": "high",
                "evidence": "61 год",
            }],
            "corrected_text": "Пациент 61 года.",
            "warnings": [],
        }, ensure_ascii=False)
        success = (
            {
                "choices": [{"finish_reason": "stop", "message": {"content": success_content}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            },
            success_content,
            1000,
        )
        truncated = (
            {
                "choices": [{"finish_reason": "length", "message": {"content": '{"mappings": ['}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 1024, "total_tokens": 1124},
            },
            '{"mappings": [',
            1000,
        )
        with patch(
            "cvd_web.text_structuring.call_json_lm_studio",
            side_effect=[success, truncated, truncated, truncated],
        ) as model_call:
            _, payload, result, _ = call_text_structuring(
                api_url="http://127.0.0.1:1234/v1/chat/completions",
                model="test-model",
                text="А" * 2500,
                timeout_seconds=300,
                max_tokens=1536,
            )
        self.assertEqual(model_call.call_count, 4)
        self.assertEqual(payload["raw"]["choices"][0]["finish_reason"], "partial")
        self.assertEqual(payload["failed_chunk_count"], 1)
        self.assertEqual(len(result["mappings"]), 1)
        self.assertTrue(any("проверьте результат" in warning for warning in result["warnings"]))

    def test_truncated_text_structuring_response_is_rejected(self):
        raw_response = {
            "choices": [{"finish_reason": "length", "message": {"content": '{"mappings": ['}}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 1536, "total_tokens": 2036},
        }
        with patch(
            "cvd_web.text_structuring.call_json_lm_studio",
            return_value=(raw_response, '{"mappings": [', 3200),
        ):
            with self.assertRaises(LMStudioError) as context:
                call_text_structuring(
                    api_url="http://127.0.0.1:1234/v1/chat/completions",
                    model="medgemma-27b-text-it",
                    text="Пациент жалуется на сердцебиение и слабость.",
                    timeout_seconds=10,
                    max_tokens=1536,
                )
        self.assertIn("обрезан", str(context.exception))
        self.assertEqual(context.exception.response_payload["raw"]["choices"][0]["finish_reason"], "length")

    def test_text_structuring_format_error_returns_manual_review_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = CVDApplication(make_test_config(Path(tmp) / "cvd.sqlite3"), start_batch_worker=False)
            cookie, csrf = self.login(app)
            response_payload = {
                "raw": {
                    "choices": [{"finish_reason": "length"}],
                    "usage": {"prompt_tokens": 500, "completion_tokens": 1536, "total_tokens": 2036},
                },
                "content": '{"mappings": [',
            }
            error = LMStudioError(
                "AI-разбор текста обрезан",
                3200,
                response_payload=response_payload,
            )
            with patch("cvd_web.handlers_ai.call_text_structuring", side_effect=error):
                status, _, body = call_wsgi(
                    app,
                    "/api/model/structure-text",
                    method="POST",
                    cookie=cookie,
                    csrf=csrf,
                    body={"text": "Пациент жалуется на сердцебиение и слабость."},
                )
            self.assertTrue(status.startswith("200"), body)
            preview = json.loads(body.decode("utf-8"))
            self.assertEqual(preview["mappings"], [])
            self.assertIn("ручной проверки", " ".join(preview["warnings"]))
            self.assertIn("Пациент жалуется", preview["corrected_text"])
            with connect(app.config.db_path) as conn:
                stored = conn.execute("SELECT * FROM data_preparation_requests").fetchone()
                text_item = conn.execute("SELECT * FROM text_preparation_items").fetchone()
            self.assertEqual(stored["status"], "success")
            self.assertEqual(stored["finish_reason"], "length")
            self.assertEqual(stored["completion_tokens"], 1536)
            self.assertEqual(text_item["mapped_fields"], 0)
            self.assertGreaterEqual(text_item["warning_count"], 1)

    def test_truncated_response_is_stored_as_error_with_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = CVDApplication(make_test_config(Path(tmp) / "cvd.sqlite3"), start_batch_worker=False)
            response_payload = {
                "raw": {
                    "usage": {"prompt_tokens": 100, "completion_tokens": 768, "total_tokens": 868},
                    "choices": [{"finish_reason": "length"}],
                },
                "content": '{"CDS_OUTPUT": {',
            }
            error = LMStudioError(
                "Ответ обрезан",
                2000,
                request_body={"model": "test", "max_tokens": 768},
                response_payload=response_payload,
            )
            with patch("cvd_web.handlers_ai.call_lm_studio", side_effect=error):
                result = app.execute_model_request(
                    user_id=1,
                    case_id=None,
                    patient_data={"GENERAL_INFO": {"Patient_ID": "TEST"}},
                    request_source="interactive",
                )
            self.assertFalse(result["ok"])
            self.assertEqual(result["finish_reason"], "length")
            self.assertEqual(result["completion_tokens"], 768)
            with connect(app.config.db_path) as conn:
                stored = conn.execute("SELECT * FROM model_requests WHERE id = ?", (result["request_id"],)).fetchone()
            self.assertEqual(stored["status"], "error")
            self.assertEqual(stored["finish_reason"], "length")
            self.assertIsNone(stored["parsed_output_json"])
            self.assertIsNotNone(stored["response_json"])

    def login(self, app: CVDApplication) -> tuple[str, str]:
        status, headers, body = call_wsgi(
            app,
            "/api/login",
            method="POST",
            body={"email": "admin@test.local", "password": "Test-admin-strong-password-2026"},
        )
        self.assertTrue(status.startswith("200"), body)
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        _, _, body = call_wsgi(app, "/api/me", cookie=cookie)
        csrf = json.loads(body.decode("utf-8"))["csrfToken"]
        return cookie, csrf

    def save_case(self, app: CVDApplication, cookie: str, csrf: str, case_id: str) -> int:
        status, _, body = call_wsgi(
            app,
            "/api/cases",
            method="POST",
            cookie=cookie,
            csrf=csrf,
            body={
                "patient_data": {
                    "GENERAL_INFO": {"Patient_ID": case_id, "Age": 61},
                    "COMPLAINTS": {"Main_complaint": "Одышка при нагрузке"},
                }
            },
        )
        self.assertTrue(status.startswith("200"), body)
        return json.loads(body.decode("utf-8"))["case_id"]

    def test_structuring_output_is_allowlisted_and_validated(self):
        result = normalize_structuring_output({
            "corrected_text": "АД 148/92 мм рт. ст.",
            "mappings": [
                {"path": "PHYSICAL_EXAM.Blood_pressure_right_systolic_mmHg", "value": "148", "confidence": "high", "evidence": "АД 148/92"},
                {"path": "PHYSICAL_EXAM.SpO2_room_air_percent", "value": "140", "confidence": "high", "evidence": "ошибка"},
                {"path": "MODEL_OUTPUT.Final_model_diagnosis", "value": "АГ", "confidence": "high", "evidence": ""},
                {"path": "UNKNOWN.field", "value": "x", "confidence": "medium", "evidence": ""},
            ],
            "warnings": [],
        })
        self.assertEqual(len(result["mappings"]), 1)
        self.assertEqual(result["mappings"][0]["value"], 148)
        self.assertTrue(any("выше допустимого" in warning for warning in result["warnings"]))
        self.assertTrue(any("неизвестное поле" in warning for warning in result["warnings"]))

    def test_ai_structuring_drops_identifiers_unknown_and_low_confidence_values(self):
        result = normalize_structuring_output({
            "corrected_text": "Пациент 61 года.",
            "mappings": [
                {"path": "GENERAL_INFO.Patient_ID", "value": "61", "confidence": "high", "evidence": "61 год"},
                {"path": "GENERAL_INFO.Full_name", "value": "unknown", "confidence": "high", "evidence": ""},
                {"path": "GENERAL_INFO.Sex", "value": "male", "confidence": "low", "evidence": "Пациент"},
                {"path": "COMPLAINTS.Main_complaint", "value": "unknown", "confidence": "high", "evidence": ""},
                {"path": "RISK_FACTORS.Hypertension", "value": "yes", "confidence": "medium", "evidence": "Пульс 92"},
                {"path": "GENERAL_INFO.Age", "value": "61", "confidence": "high", "evidence": "61 год"},
            ],
            "warnings": [],
        })
        self.assertEqual([item["path"] for item in result["mappings"]], ["GENERAL_INFO.Age"])
        self.assertTrue(any("GENERAL_INFO.Patient_ID" in warning for warning in result["warnings"]))
        self.assertTrue(any("GENERAL_INFO.Full_name" in warning for warning in result["warnings"]))
        self.assertTrue(any("GENERAL_INFO.Sex" in warning for warning in result["warnings"]))
        self.assertTrue(any("отсутствия данных" in warning for warning in result["warnings"]))
        self.assertTrue(any("высокой уверенности" in warning for warning in result["warnings"]))

    def test_ai_structuring_corrects_known_medication_class(self):
        result = normalize_structuring_output({
            "corrected_text": "Принимает бисопролол 5 мг утром.",
            "mappings": [{
                "path": "CURRENT_MEDICATIONS.Antiplatelets",
                "value": "бисопролол 5 мг утром",
                "confidence": "high",
                "evidence": "Принимает бисопролол",
            }],
            "warnings": [],
        })
        self.assertEqual(len(result["mappings"]), 1)
        self.assertEqual(result["mappings"][0]["path"], "CURRENT_MEDICATIONS.Beta_blockers")
        self.assertTrue(any("подтверждённый класс" in warning for warning in result["warnings"]))

    def test_batch_processing_dashboard_and_text_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = CVDApplication(make_test_config(Path(tmp) / "cvd.sqlite3"), start_batch_worker=False)
            cookie, csrf = self.login(app)
            case_ids = [
                self.save_case(app, cookie, csrf, "BATCH_1"),
                self.save_case(app, cookie, csrf, "BATCH_2"),
            ]

            status, _, body = call_wsgi(
                app,
                "/api/admin/batch/jobs",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={"case_ids": case_ids},
            )
            self.assertTrue(status.startswith("201"), body)
            job_id = json.loads(body.decode("utf-8"))["job_id"]

            status, _, body = call_wsgi(
                app,
                "/api/admin/batch/jobs",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={"case_ids": [case_ids[0]]},
            )
            self.assertTrue(status.startswith("409"), body)
            status, _, body = call_wsgi(
                app,
                f"/api/cases/{case_ids[0]}/delete",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={},
            )
            self.assertTrue(status.startswith("409"), body)

            model_response = {
                "raw": {
                    "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
                    "choices": [{"finish_reason": "stop"}],
                },
                "content": "{}",
            }
            parsed = {"CDS_OUTPUT": {"summary": "Тестовый результат"}}
            with patch("cvd_web.handlers_ai.call_lm_studio", return_value=({}, model_response, parsed, 1000)):
                self.assertTrue(app.process_next_batch_item())
                self.assertTrue(app.process_next_batch_item())
                self.assertFalse(app.process_next_batch_item())

            status, _, body = call_wsgi(app, f"/api/admin/batch/jobs/{job_id}", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            job = json.loads(body.decode("utf-8"))["job"]
            self.assertEqual(job["status"], "completed")
            self.assertEqual(job["success_items"], 2)
            self.assertEqual(job["progress"]["progress_percent"], 100)
            self.assertEqual(job["progress"]["remaining_items"], 0)

            structuring_result = {
                "corrected_text": "Пациент 61 года. Жалуется на одышку.",
                "mappings": [{
                    "path": "GENERAL_INFO.Age",
                    "value": 61,
                    "confidence": "high",
                    "source_conflict": False,
                    "sources": [{"label": "61 года"}],
                }],
                "warnings": [],
            }
            with patch(
                "cvd_web.handlers_ai.call_text_structuring",
                return_value=({}, model_response, structuring_result, 800),
            ):
                status, _, body = call_wsgi(
                    app,
                    "/api/model/structure-text",
                    method="POST",
                    cookie=cookie,
                    csrf=csrf,
                    body={"text": "пациэнт 61 год жалуеться на одышку"},
                )
            self.assertTrue(status.startswith("200"), body)
            preview = json.loads(body.decode("utf-8"))
            self.assertEqual(preview["source_format"], "ai-text")
            self.assertEqual(preview["mappings"][0]["path"], "GENERAL_INFO.Age")

            status, _, body = call_wsgi(app, "/api/text-preparations", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            preparations = json.loads(body.decode("utf-8"))["text_preparations"]
            self.assertEqual(preparations[0]["status"], "prepared")
            self.assertEqual(preparations[0]["mappings"][0]["path"], "GENERAL_INFO.Age")
            self.assertIn("Пациент 61 года", preparations[0]["corrected_text_preview"])

            status, _, body = call_wsgi(app, "/api/admin/dashboard", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            dashboard = json.loads(body.decode("utf-8"))
            self.assertEqual(dashboard["model"]["total"], 2)
            self.assertEqual(dashboard["model"]["success_rate_percent"], 100.0)
            self.assertEqual(dashboard["batch"]["success_items"], 2)
            self.assertEqual(dashboard["preparations"]["success"], 1)
            self.assertEqual(dashboard["system"]["db_integrity"], "ok")

            with connect(app.config.db_path) as conn:
                sources = [row["request_source"] for row in conn.execute("SELECT request_source FROM model_requests")]
                preparation = conn.execute("SELECT * FROM data_preparation_requests").fetchone()
                text_item = conn.execute("SELECT * FROM text_preparation_items").fetchone()
            self.assertEqual(sources, ["batch", "batch"])
            self.assertEqual(len(preparation["input_sha256"]), 64)
            self.assertEqual(preparation["chunk_count"], 1)
            self.assertEqual(preparation["finish_reason"], "stop")
            self.assertEqual(text_item["mapped_fields"], 1)
            self.assertEqual(text_item["status"], "prepared")
            self.assertNotIn("пациэнт", preparation.keys())

    def test_persistent_inference_jobs_process_ten_cardiologists(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = CVDApplication(make_test_config(Path(tmp) / "cvd.sqlite3"), start_batch_worker=False)
            now = utc_now()
            with connect(app.config.db_path) as conn:
                for index in range(10):
                    conn.execute(
                        """
                        INSERT INTO users
                          (email, full_name, password_hash, role, is_active, must_change_password, created_at, updated_at)
                        VALUES (?, ?, ?, 'user', 1, 0, ?, ?)
                        """,
                        (
                            f"cardio{index}@test.local",
                            f"Cardiologist {index}",
                            hash_password("Cardio-password-2026!"),
                            now,
                            now,
                        ),
                    )

            sessions: list[tuple[str, str]] = []
            for index in range(10):
                status, headers, body = call_wsgi(
                    app,
                    "/api/login",
                    method="POST",
                    body={"email": f"cardio{index}@test.local", "password": "Cardio-password-2026!"},
                )
                self.assertTrue(status.startswith("200"), body)
                cookie = headers["Set-Cookie"].split(";", 1)[0]
                _, _, body = call_wsgi(app, "/api/me", cookie=cookie)
                sessions.append((cookie, json.loads(body.decode("utf-8"))["csrfToken"]))

            job_ids: list[int] = []
            for index, (cookie, csrf) in enumerate(sessions):
                status, _, body = call_wsgi(
                    app,
                    "/api/model/diagnose/jobs",
                    method="POST",
                    cookie=cookie,
                    csrf=csrf,
                    body={
                        "patient_data": {
                            "GENERAL_INFO": {"Patient_ID": f"P-{index}", "Age": 60 + index},
                            "COMPLAINTS": {"Main_complaint": "Одышка при нагрузке"},
                        }
                    },
                )
                self.assertTrue(status.startswith("201"), body)
                job_ids.append(json.loads(body.decode("utf-8"))["job_id"])

            parsed = {
                "CDS_OUTPUT": {
                    "summary": "Стабильный тестовый ответ.",
                    "possible_diagnoses": [],
                    "red_flags": [],
                    "missing_data": [],
                    "recommended_next_data": [],
                    "limitations": [],
                    "model_should_abstain": True,
                },
                "MODEL_OUTPUT": {"Final_model_diagnosis": "Тест"},
            }

            def model_response(**kwargs):
                return (
                    {"model": kwargs["model"]},
                    {
                        "raw": {
                            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                            "choices": [{"finish_reason": "stop"}],
                        },
                        "content": "{}",
                    },
                    parsed,
                    100,
                )

            with patch("cvd_web.handlers_ai.call_lm_studio", side_effect=model_response) as model_call:
                processed = 0
                while app.process_next_inference_job():
                    processed += 1
            self.assertEqual(processed, 10)
            self.assertEqual(model_call.call_count, 10)

            for job_id, (cookie, _) in zip(job_ids, sessions):
                status, _, body = call_wsgi(app, f"/api/model/diagnose/jobs/{job_id}", cookie=cookie)
                self.assertTrue(status.startswith("200"), body)
                payload = json.loads(body.decode("utf-8"))
                self.assertEqual(payload["job"]["status"], "success")
                self.assertTrue(payload["result"]["ok"])
                self.assertIsNotNone(payload["result"]["request_id"])

    def test_text_preparation_jobs_are_persistent_and_fifo_with_diagnosis(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = CVDApplication(make_test_config(Path(tmp) / "cvd.sqlite3"), start_batch_worker=False)
            cookie, csrf = self.login(app)

            status, _, body = call_wsgi(
                app,
                "/api/model/diagnose/jobs",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={
                    "patient_data": {
                        "GENERAL_INFO": {"Patient_ID": "FIFO-1", "Age": 63},
                        "COMPLAINTS": {"Main_complaint": "Одышка при нагрузке"},
                    }
                },
            )
            self.assertTrue(status.startswith("201"), body)
            diagnosis_job_id = json.loads(body.decode("utf-8"))["job_id"]

            status, _, body = call_wsgi(
                app,
                "/api/model/structure-text/jobs",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={"text": "Пациент 63 лет жалуется на одышку при нагрузке."},
            )
            self.assertTrue(status.startswith("201"), body)
            text_job_id = json.loads(body.decode("utf-8"))["job_id"]

            status, _, body = call_wsgi(app, "/api/ai/jobs", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            jobs = json.loads(body.decode("utf-8"))["jobs"]
            active_order = [(job["type"], job["id"]) for job in jobs if job["status"] == "queued"]
            self.assertEqual(active_order[:2], [("diagnosis", diagnosis_job_id), ("text_preparation", text_job_id)])
            queued = {(job["type"], job["id"]): job["position"] for job in jobs if job["status"] == "queued"}
            self.assertEqual(queued[("diagnosis", diagnosis_job_id)], 1)
            self.assertEqual(queued[("text_preparation", text_job_id)], 2)

            parsed = {
                "CDS_OUTPUT": {
                    "summary": "Диагностический ответ.",
                    "possible_diagnoses": [],
                    "red_flags": [],
                    "missing_data": [],
                    "recommended_next_data": [],
                    "limitations": [],
                    "model_should_abstain": True,
                },
                "MODEL_OUTPUT": {"Final_model_diagnosis": "Тест"},
            }
            structuring_result = {
                "corrected_text": "Пациент 63 лет жалуется на одышку при нагрузке.",
                "mappings": [{
                    "path": "GENERAL_INFO.Age",
                    "value": 63,
                    "confidence": "high",
                    "source_conflict": False,
                    "sources": [{"label": "63 лет"}],
                }],
                "warnings": [],
            }
            processing_order: list[str] = []

            def model_response(**kwargs):
                processing_order.append("diagnosis")
                return (
                    {"model": kwargs["model"]},
                    {"raw": {"usage": {}, "choices": [{"finish_reason": "stop"}]}, "content": "{}"},
                    parsed,
                    100,
                )

            def text_response(**kwargs):
                processing_order.append("text")
                return (
                    {},
                    {"raw": {"usage": {}, "choices": [{"finish_reason": "stop"}]}, "content": "{}"},
                    structuring_result,
                    100,
                )

            with patch("cvd_web.handlers_ai.call_lm_studio", side_effect=model_response), patch(
                "cvd_web.handlers_ai.call_text_structuring",
                side_effect=text_response,
            ):
                self.assertTrue(app.process_next_inference_job())
                self.assertTrue(app.process_next_inference_job())
                self.assertFalse(app.process_next_inference_job())
            self.assertEqual(processing_order, ["diagnosis", "text"])

            status, _, body = call_wsgi(app, f"/api/model/structure-text/jobs/{text_job_id}", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            payload = json.loads(body.decode("utf-8"))
            self.assertEqual(payload["job"]["status"], "success")
            self.assertEqual(payload["job"]["result"]["source_format"], "ai-text")
            self.assertEqual(payload["job"]["result"]["mappings"][0]["path"], "GENERAL_INFO.Age")
            self.assertEqual(payload["job"]["text_preview"], "Пациент 63 лет жалуется на одышку при нагрузке.")

            with connect(app.config.db_path) as conn:
                stored_job = conn.execute(
                    "SELECT request_json FROM text_preparation_jobs WHERE id = ?",
                    (text_job_id,),
                ).fetchone()
            stored_request = json.loads(stored_job["request_json"])
            self.assertNotIn("text", stored_request)
            self.assertEqual(stored_request["text_preview"], "Пациент 63 лет жалуется на одышку при нагрузке.")

            status, _, body = call_wsgi(app, "/api/ai/jobs", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            jobs_payload = json.loads(body.decode("utf-8"))
            self.assertEqual(jobs_payload["active_count"], 0)
            finished = {(job["type"], job["id"]): job["status"] for job in jobs_payload["jobs"]}
            self.assertEqual(finished[("diagnosis", diagnosis_job_id)], "success")
            self.assertEqual(finished[("text_preparation", text_job_id)], "success")


if __name__ == "__main__":
    unittest.main()
