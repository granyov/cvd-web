"""Smoke-сценарии ключевых пользовательских потоков поверх WSGI-приложения.

Каждый тест проходит целый путь пользователя (логин → действия → результат),
чтобы ловить регрессии маршрутизации, шаблонов и API-контрактов без браузера.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from cvd_web.app import CVDApplication
from cvd_web.auth import utc_now
from cvd_web.db import connect
from cvd_web.lmstudio_models import LMStudioManagementError

from test_core import call_wsgi, make_test_config


def login(app: CVDApplication) -> tuple[str, str]:
    status, headers, body = call_wsgi(
        app,
        "/api/login",
        method="POST",
        body={"email": "admin@test.local", "password": "Test-admin-strong-password-2026"},
    )
    assert status.startswith("200"), body
    cookie = headers["Set-Cookie"].split(";", 1)[0]
    status, _, body = call_wsgi(app, "/api/me", cookie=cookie)
    assert status.startswith("200"), body
    csrf = json.loads(body.decode("utf-8"))["csrfToken"]
    return cookie, csrf


class SmokeTests(unittest.TestCase):

    def make_app(self, tmp: str) -> CVDApplication:
        return CVDApplication(make_test_config(Path(tmp) / "cvd.sqlite3"), start_batch_worker=False)

    def test_login_page_and_workspace_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp)
            status, _, body = call_wsgi(app, "/login")
            self.assertTrue(status.startswith("200"), body)
            self.assertIn(b"CVD", body)

            cookie, _ = login(app)
            status, _, body = call_wsgi(app, "/app", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            page = body.decode("utf-8")
            for element_id in (
                "caseForm", "saveCaseButton", "diagnoseButton", "draftBanner",
                "recentCases", "aiErrorCard", "retryDiagnoseButton", "demoCaseButton",
                "passwordForcedNotice",
            ):
                self.assertIn(f'id="{element_id}"', page)

            status, _, body = call_wsgi(app, "/cases", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            status, _, body = call_wsgi(app, "/admin", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            self.assertIn("Аудит безопасности", body.decode("utf-8"))

    def test_case_lifecycle_save_list_get_copy_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp)
            cookie, csrf = login(app)

            status, _, body = call_wsgi(
                app,
                "/api/cases",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={
                    "case_id": None,
                    "patient_data": {
                        "GENERAL_INFO": {"Patient_ID": "SMOKE-1", "Age": 61, "Sex": "male"},
                        "COMPLAINTS": {"Main_complaint": "Одышка при нагрузке"},
                    },
                },
            )
            self.assertTrue(status.startswith("200"), body)
            case_id = json.loads(body.decode("utf-8"))["case_id"]

            status, _, body = call_wsgi(app, "/api/cases?limit=5", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            cases = json.loads(body.decode("utf-8"))["cases"]
            self.assertTrue(any(item["id"] == case_id for item in cases))
            listed = next(item for item in cases if item["id"] == case_id)
            self.assertIn("quality", listed)

            status, _, body = call_wsgi(app, f"/api/cases/{case_id}", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            case = json.loads(body.decode("utf-8"))["case"]
            self.assertEqual(case["data"]["GENERAL_INFO"]["Patient_ID"], "SMOKE-1")

            status, _, body = call_wsgi(app, f"/api/cases/{case_id}/copy", method="POST", cookie=cookie, csrf=csrf, body={})
            self.assertTrue(status.startswith("200") or status.startswith("201"), body)

            status, _, body = call_wsgi(app, f"/api/cases/{case_id}/delete", method="POST", cookie=cookie, csrf=csrf, body={})
            self.assertTrue(status.startswith("200"), body)

    def test_demo_case_endpoint_creates_valid_full_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp)
            cookie, csrf = login(app)

            status, _, body = call_wsgi(app, "/api/cases/demo", method="POST", cookie=cookie, csrf=csrf, body={})
            self.assertTrue(status.startswith("201"), body)
            case_id = json.loads(body.decode("utf-8"))["case_id"]

            status, _, body = call_wsgi(app, f"/api/cases/{case_id}", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            data = json.loads(body.decode("utf-8"))["case"]["data"]
            self.assertEqual(data["GENERAL_INFO"]["Patient_ID"], "DEMO_CVD_001")
            self.assertEqual(data["FINAL_DIAGNOSES"]["ICD10_codes"], ["I20.8", "I10", "E11.9", "E78.5"])
            self.assertTrue(data["ECHOCARDIOGRAPHY"]["LVEF_percent"])

            status, _, body = call_wsgi(app, f"/api/cases/{case_id}/fhir", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            bundle = json.loads(body.decode("utf-8"))
            self.assertEqual(bundle.get("resourceType"), "Bundle")

    def test_archive_search_and_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp)
            cookie, csrf = login(app)
            call_wsgi(app, "/api/cases/demo", method="POST", cookie=cookie, csrf=csrf, body={})

            status, _, body = call_wsgi(app, "/api/cases?q=DEMO_CVD", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            self.assertEqual(json.loads(body.decode("utf-8"))["total"], 1)

            status, _, body = call_wsgi(app, "/api/cases?q=NO_SUCH_CASE", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            self.assertEqual(json.loads(body.decode("utf-8"))["total"], 0)

            status, _, body = call_wsgi(app, "/api/cases?analysis=without", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            self.assertEqual(json.loads(body.decode("utf-8"))["total"], 1)

    def test_worklist_and_ai_job_cancel_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp)
            cookie, csrf = login(app)
            patient_data = {
                "GENERAL_INFO": {"Patient_ID": "WL-1", "Age": 58, "Sex": "male"},
                "COMPLAINTS": {"Main_complaint": "Одышка при нагрузке"},
                "PHYSICAL_EXAM": {"Blood_pressure_right_systolic_mmHg": 134, "Heart_rate_bpm": 76},
                "FINAL_DIAGNOSES": {"Main_cardiovascular_diagnosis_text": "АГ?"},
            }
            status, _, body = call_wsgi(
                app,
                "/api/cases",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={"patient_data": patient_data},
            )
            self.assertTrue(status.startswith("200"), body)
            case_id = json.loads(body.decode("utf-8"))["case_id"]

            status, _, body = call_wsgi(app, "/api/worklist", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            stages = {item["key"]: item for item in json.loads(body.decode("utf-8"))["stages"]}
            self.assertGreaterEqual(stages["in_progress"]["count"], 1)
            listed = next(item for item in stages["in_progress"]["items"] if item["id"] == case_id)
            self.assertEqual(listed["workflow"]["bucket"], "in_progress")

            status, _, body = call_wsgi(
                app,
                "/api/model/diagnose/jobs",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={"case_id": case_id, "patient_data": patient_data},
            )
            self.assertTrue(status.startswith("201"), body)
            job_id = json.loads(body.decode("utf-8"))["job_id"]

            status, _, body = call_wsgi(app, "/api/cases?analysis=waiting_ai", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            waiting = json.loads(body.decode("utf-8"))["cases"]
            self.assertEqual([item["id"] for item in waiting], [case_id])
            self.assertEqual(waiting[0]["workflow"]["key"], "ai_queued")

            status, _, body = call_wsgi(app, "/api/ai/jobs", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            jobs = json.loads(body.decode("utf-8"))["jobs"]
            self.assertEqual(jobs[0]["id"], job_id)
            self.assertEqual(jobs[0]["position"], 1)
            self.assertEqual(jobs[0]["queue_ahead"], 0)
            self.assertEqual(jobs[0]["case_id"], case_id)

            status, _, body = call_wsgi(
                app,
                f"/api/ai/jobs/diagnosis/{job_id}/cancel",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={},
            )
            self.assertTrue(status.startswith("200"), body)

            status, _, body = call_wsgi(app, f"/api/model/diagnose/jobs/{job_id}", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            self.assertEqual(json.loads(body.decode("utf-8"))["job"]["status"], "cancelled")
            self.assertIn("защищённый канал", app.user_friendly_ai_error("HTTP 524 from Cloudflare tunnel"))

    def test_oversized_case_is_rejected_before_it_reaches_the_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp)
            cookie, csrf = login(app)
            # Контекст обычно проставляет health-check по реальной загруженной модели.
            with connect(Path(tmp) / "cvd.sqlite3") as conn:
                conn.execute(
                    "UPDATE app_settings SET value = '8192' WHERE key = 'lm_studio_context_tokens'"
                )
                conn.execute(
                    "UPDATE app_settings SET value = '4096' WHERE key = 'lm_studio_max_tokens'"
                )

            filler = "детальное описание клинической картины с уточнениями и динамикой. " * 60
            oversized = {
                "GENERAL_INFO": {"Patient_ID": "OVERFLOW-1", "Age": 70, "Sex": "male"},
                "COMPLAINTS": {"Main_complaint": filler[:3900], "Onset_context": filler[:3900]},
                "PAST_EVENTS": {"Prior_MI": filler[:3900], "Other_major_diseases": filler[:3900]},
                "ECG_AND_BP_MONITORING": {"Resting_ECG_summary": filler[:3900]},
            }
            # Контекст подтверждается у LM Studio: отказываем только по свежему значению.
            confirmed_catalog = {
                "api_version": "v1",
                "models": [{
                    "id": "healtheart-cvd-engine",
                    "state": "loaded",
                    "loaded_context_length": 8192,
                    "max_context_length": 131072,
                }],
            }
            with patch("cvd_web.handlers_ai.list_lm_models", return_value=confirmed_catalog):
                status, _, body = call_wsgi(
                    app,
                    "/api/model/diagnose/jobs",
                    method="POST",
                    cookie=cookie,
                    csrf=csrf,
                    body={"patient_data": oversized},
                )
            # 413, а не молчаливое ожидание минуты ради ошибки переполнения от модели.
            self.assertTrue(status.startswith("413"), body)
            message = json.loads(body.decode("utf-8"))["error"]
            self.assertIn("слишком большой", message)
            self.assertIn("токенов", message)

            compact = {
                "GENERAL_INFO": {"Patient_ID": "FITS-1", "Age": 61, "Sex": "male"},
                "COMPLAINTS": {"Main_complaint": "Одышка при нагрузке"},
            }
            status, _, body = call_wsgi(
                app,
                "/api/model/diagnose/jobs",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={"patient_data": compact},
            )
            self.assertTrue(status.startswith("201"), body)

    def test_stale_context_setting_does_not_block_a_reloaded_model(self):
        # Модель перезагрузили с большим контекстом: сохранённое значение устарело,
        # и отказывать по нему нельзя — иначе врач не сможет запустить валидный случай.
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp)
            cookie, csrf = login(app)
            with connect(Path(tmp) / "cvd.sqlite3") as conn:
                conn.execute("UPDATE app_settings SET value = '8192' WHERE key = 'lm_studio_context_tokens'")
                conn.execute("UPDATE app_settings SET value = '4096' WHERE key = 'lm_studio_max_tokens'")

            filler = "детальное описание клинической картины с уточнениями и динамикой. " * 60
            case = {
                "GENERAL_INFO": {"Patient_ID": "RELOADED-1", "Age": 66, "Sex": "female"},
                "COMPLAINTS": {"Main_complaint": filler[:3900], "Onset_context": filler[:3900]},
                "PAST_EVENTS": {"Prior_MI": filler[:3900]},
            }
            reloaded_catalog = {
                "api_version": "v1",
                "models": [{
                    "id": "healtheart-cvd-engine",
                    "state": "loaded",
                    "loaded_context_length": 32768,
                    "max_context_length": 131072,
                }],
            }
            with patch("cvd_web.handlers_ai.list_lm_models", return_value=reloaded_catalog):
                status, _, body = call_wsgi(
                    app,
                    "/api/model/diagnose/jobs",
                    method="POST",
                    cookie=cookie,
                    csrf=csrf,
                    body={"patient_data": case},
                )
            self.assertTrue(status.startswith("201"), body)
            # Свежий контекст сохраняется, чтобы следующая проверка была мгновенной.
            with connect(Path(tmp) / "cvd.sqlite3") as conn:
                stored = conn.execute(
                    "SELECT value FROM app_settings WHERE key = 'lm_studio_context_tokens'"
                ).fetchone()["value"]
            self.assertEqual(stored, "32768")

    def test_unreachable_model_does_not_produce_an_invented_size_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp)
            cookie, csrf = login(app)
            with connect(Path(tmp) / "cvd.sqlite3") as conn:
                conn.execute("UPDATE app_settings SET value = '8192' WHERE key = 'lm_studio_context_tokens'")

            filler = "описание " * 900
            case = {"GENERAL_INFO": {"Patient_ID": "OFFLINE-1"}, "COMPLAINTS": {"Main_complaint": filler[:3900], "Onset_context": filler[:3900]}}
            with patch(
                "cvd_web.handlers_ai.list_lm_models",
                side_effect=LMStudioManagementError("connection refused"),
            ):
                status, _, body = call_wsgi(
                    app,
                    "/api/model/diagnose/jobs",
                    method="POST",
                    cookie=cookie,
                    csrf=csrf,
                    body={"patient_data": case},
                )
            # Проверить размер нечем — пропускаем, врач увидит настоящую ошибку сервиса.
            self.assertTrue(status.startswith("201"), body)

    def test_ai_error_messages_are_actionable_for_the_doctor(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp)

            # LM Studio возвращает эхо запроса вместе с ошибкой контекста: раньше это
            # классифицировалось как «ответ не удалось структурировать» и врач повторял запрос впустую.
            overflow = (
                'LM Studio HTTP 400: {"error":"Trying to keep the first 10847 tokens when context the '
                'overflows. However, the model is loaded with context length of only 4096 tokens, which '
                'is not enough. Try to load the model with a larger context length, or provide a shorter '
                'input. Request body was: {\\"model\\":\\"medgemma\\",\\"messages\\":[{\\"role\\":\\"user\\"}]}"}'
            )
            message = app.user_friendly_ai_error(overflow)
            self.assertIn("не помещаются в её контекст", message)
            # Реальная формулировка LM Studio при переполнении отличается от кавычек выше.
            real_stream_error = (
                "LM Studio stream вернул ошибку: The number of tokens to keep from the initial "
                "prompt is greater than the context length (n_keep: 8539>= n_ctx: 8192). "
                "Try to load the model with a larger context length, or provide a shorter input."
            )
            self.assertIn("не помещаются в её контекст", app.user_friendly_ai_error(real_stream_error))
            self.assertIn("Повтор не поможет", message)
            self.assertNotIn("структур", message)
            self.assertNotIn("messages", message)
            self.assertLessEqual(len(message), 400)

            # Технические имена сервисов не должны утекать врачу.
            for raw in (
                "LM Studio недоступен: [Errno 61] Connection refused",
                "LM Studio не смогла загрузить модель: insufficient system resources",
            ):
                friendly = app.user_friendly_ai_error(raw)
                self.assertNotIn("LM Studio", friendly)
                self.assertIn("CVD Engine", friendly)

            # Неизвестная ошибка не вываливает сырой ответ модели целиком.
            noisy = "Something exploded. Request body was: " + ("x" * 5000)
            self.assertLessEqual(len(app.user_friendly_ai_error(noisy)), 300)

    def test_mis_export_carries_the_conclusion_to_the_hospital_system(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp)
            cookie, csrf = login(app)

            status, _, body = call_wsgi(app, "/api/cases/demo", method="POST", cookie=cookie, csrf=csrf, body={})
            self.assertTrue(status.startswith("201"), body)
            case_id = json.loads(body.decode("utf-8"))["case_id"]

            parsed_output = {
                "CDS_OUTPUT": {
                    "summary": "Стабильная стенокардия напряжения.",
                    "possible_diagnoses": [
                        {
                            "name": "ИБС: стабильная стенокардия II ФК",
                            "icd10_codes": ["I20.8"],
                            "confidence": "high",
                            "supporting_findings": ["типичная боль", "положительный тредмил-тест"],
                        }
                    ],
                    "red_flags": ["ЛПНП выше целевого"],
                    "missing_data": ["динамика тропонина"],
                    "recommended_next_data": [],
                    "limitations": [],
                    "model_should_abstain": False,
                },
                "MODEL_OUTPUT": {
                    "Final_model_diagnosis": "ИБС: стабильная стенокардия напряжения II ФК",
                    "Model_ICD10_codes": ["I20.8", "I10"],
                    "Model_treatment_recommendations": "Антиагрегантная терапия, контроль АД.",
                    "Model_rehabilitation_recommendations": "Отказ от курения, аэробные нагрузки.",
                },
            }
            with connect(Path(tmp) / "cvd.sqlite3") as conn:
                cur = conn.execute(
                    """
                    INSERT INTO model_requests
                      (user_id, case_id, status, api_url, model, request_json, parsed_output_json, created_at)
                    VALUES (1, ?, 'success', 'demo://local', 'demo', '{}', ?, ?)
                    """,
                    (case_id, json.dumps(parsed_output, ensure_ascii=False), utc_now()),
                )
                request_id = cur.lastrowid

            # A: текст для вставки в протокол МИС.
            status, _, body = call_wsgi(app, f"/api/reports/{request_id}/mis-text", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            text = json.loads(body.decode("utf-8"))["text"]
            self.assertIn("ДИАГНОЗ ВРАЧА:", text)
            self.assertIn("ИБС: стабильная стенокардия напряжения II ФК", text)
            self.assertIn("ЧЕРНОВИК AI:", text)
            self.assertIn("МКБ-10: I20.8, I10", text)
            self.assertIn("Антиагрегантная терапия", text)
            self.assertIn("Требует проверки врачом", text)

            # C: FHIR-выгрузка теперь несёт заключение, а не только анкету.
            status, _, body = call_wsgi(app, f"/api/cases/{case_id}/fhir", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            bundle = json.loads(body.decode("utf-8"))
            resources = {item["resource"]["resourceType"]: item["resource"] for item in bundle["entry"]}
            self.assertIn("DiagnosticReport", resources)
            self.assertIn("ClinicalImpression", resources)
            self.assertIn("CarePlan", resources)
            report = resources["DiagnosticReport"]
            self.assertEqual(report["status"], "final")
            self.assertIn("стенокардия", report["conclusion"])
            codes = [coding["code"] for coding in report["conclusionCode"][0]["coding"]]
            self.assertEqual(codes, ["I20.8", "I10"])
            self.assertEqual(report["conclusionCode"][0]["coding"][0]["system"], "http://hl7.org/fhir/sid/icd-10")
            # Диагноз врача остаётся подтверждённым Condition, черновик AI — отдельно.
            self.assertEqual(
                resources["Condition"]["verificationStatus"]["coding"][0]["code"], "confirmed"
            )
            self.assertEqual(resources["CarePlan"]["intent"], "proposal")

    def test_fhir_export_without_result_stays_backward_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp)
            cookie, csrf = login(app)
            status, _, body = call_wsgi(app, "/api/cases/demo", method="POST", cookie=cookie, csrf=csrf, body={})
            case_id = json.loads(body.decode("utf-8"))["case_id"]

            status, _, body = call_wsgi(app, f"/api/cases/{case_id}/fhir", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            bundle = json.loads(body.decode("utf-8"))
            types = {item["resource"]["resourceType"] for item in bundle["entry"]}
            self.assertEqual(bundle["resourceType"], "Bundle")
            self.assertIn("Patient", types)
            self.assertIn("Composition", types)
            self.assertNotIn("DiagnosticReport", types)

    def test_admin_dashboard_and_security_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp)
            cookie, _ = login(app)

            status, _, body = call_wsgi(app, "/api/admin/dashboard", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            dashboard = json.loads(body.decode("utf-8"))
            self.assertIn("system", dashboard)

            status, _, body = call_wsgi(app, "/api/admin/security-audit", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            checks = {item["key"]: item for item in json.loads(body.decode("utf-8"))["checks"]}
            self.assertTrue(checks["default_admin_password"]["ok"])

    def test_logout_invalidates_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(tmp)
            cookie, csrf = login(app)

            status, _, body = call_wsgi(app, "/api/logout", method="POST", cookie=cookie, csrf=csrf, body={})
            self.assertTrue(status.startswith("200"), body)

            status, _, body = call_wsgi(app, "/api/cases", cookie=cookie)
            self.assertTrue(status.startswith("401"), body)


if __name__ == "__main__":
    unittest.main()
