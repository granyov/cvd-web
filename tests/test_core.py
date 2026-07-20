from __future__ import annotations

import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from cvd_web.app import CVDApplication
from cvd_web.auth import hash_password, utc_now, verify_password
from cvd_web.config import Config, PROJECT_ROOT
from cvd_web.db import connect
from cvd_web.lmstudio import (
    LM_STUDIO_USER_AGENT,
    LMStudioError,
    build_chat_request,
    call_json_lm_studio,
    call_lm_studio,
    extract_json_from_text,
    lm_studio_http_error_message,
    normalize_model_output,
)
from cvd_web.lmstudio_models import activate_lm_model, list_lm_models
from cvd_web.migrations import migration_status, run_migrations
from cvd_web.privacy import deidentify_patient_data
from cvd_web.quality import case_quality_summary, has_clinical_input, patient_data_changes, patient_data_hash
from cvd_web.rate_limit import MemoryRateLimiter
from cvd_web.reporting import build_html_report


def make_test_config(db_path: Path) -> Config:
    return Config(
        app_env="test",
        project_root=PROJECT_ROOT,
        db_path=db_path,
        host="127.0.0.1",
        port=0,
        cookie_secure=False,
        session_days=7,
        admin_email="admin@test.local",
        admin_password="Test-admin-strong-password-2026",
        lm_studio_api_url="http://127.0.0.1:1234/v1/chat/completions",
        lm_studio_model="healtheart-cvd-engine",
        lm_studio_timeout_seconds=5,
        lm_studio_max_tokens=1536,
        lm_studio_temperature=0.2,
        max_request_bytes=1024 * 1024,
    )


def call_wsgi(
    app: CVDApplication,
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    cookie: str = "",
    csrf: str = "",
    headers: dict[str, str] | None = None,
):
    raw = b""
    if body is not None:
        raw = json.dumps(body).encode("utf-8")
    parsed_url = urlsplit(path)
    path_info = parsed_url.path
    query_string = parsed_url.query
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path_info or path,
        "QUERY_STRING": query_string or "",
        "CONTENT_LENGTH": str(len(raw)),
        "CONTENT_TYPE": "application/json",
        "wsgi.input": BytesIO(raw),
        "HTTP_COOKIE": cookie,
        "HTTP_X_CSRF_TOKEN": csrf,
        "HTTP_HOST": "127.0.0.1",
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.url_scheme": "http",
    }
    for key, value in (headers or {}).items():
        environ["HTTP_" + key.upper().replace("-", "_")] = value
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    response_body = b"".join(app(environ, start_response))
    return captured["status"], dict(captured["headers"]), response_body


class CoreTests(unittest.TestCase):

    def test_clinical_quality_rules_and_hash_ignore_model_output(self):
        patient_data = {
            "GENERAL_INFO": {"Patient_ID": "Q-1", "Age": 78, "Sex": "female"},
            "COMPLAINTS": {"Main_complaint": "Боль в груди и одышка"},
            "PHYSICAL_EXAM": {
                "Blood_pressure_right_systolic_mmHg": 88,
                "Blood_pressure_right_diastolic_mmHg": 55,
                "Heart_rate_bpm": 128,
                "SpO2_room_air_percent": 89,
            },
            "ECG_AND_BP_MONITORING": {},
            "ECHOCARDIOGRAPHY": {"LVEF_percent": 35},
            "LABS_CARDIAC_MARKERS": {"Troponin_ng_L": 1.2},
            "FINAL_DIAGNOSES": {"Main_cardiovascular_diagnosis_text": "ОКС?"},
            "MODEL_OUTPUT": {"Final_model_diagnosis": "old"},
        }
        quality = case_quality_summary(patient_data)
        titles = {signal["title"] for signal in quality["signals"]}
        self.assertIn("Боль в груди без ЭКГ", titles)
        self.assertIn("Низкая SpO2 + тахикардия", titles)
        self.assertGreaterEqual(quality["critical_signals"], 3)
        without_model_change = dict(patient_data)
        without_model_change["MODEL_OUTPUT"] = {"Final_model_diagnosis": "new"}
        self.assertEqual(patient_data_hash(patient_data), patient_data_hash(without_model_change))
        changed_clinical_data = dict(patient_data)
        changed_clinical_data["GENERAL_INFO"] = {**patient_data["GENERAL_INFO"], "Age": 79}
        self.assertNotEqual(patient_data_hash(patient_data), patient_data_hash(changed_clinical_data))
        self.assertFalse(has_clinical_input({"MODEL_OUTPUT": {"Final_model_diagnosis": "old"}}))
        self.assertTrue(has_clinical_input({"GENERAL_INFO": {"Patient_ID": "Q-2"}}))
        changes = patient_data_changes({"GENERAL_INFO": {"Age": 70}}, {"GENERAL_INFO": {"Age": 71, "Sex": "female"}})
        self.assertEqual([item["path"] for item in changes], ["GENERAL_INFO.Sex", "GENERAL_INFO.Age"])
        self.assertEqual(changes[1]["kind"], "changed")

    def test_empty_ai_gateway_headers_json_clears_legacy_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = CVDApplication(make_test_config(Path(tmp) / "cvd.sqlite3"), start_batch_worker=False)
            settings = {
                "ai_gateway_headers_json": "[]",
                "ai_gateway_auth_header_name": "Authorization",
                "ai_gateway_auth_header_value": "Bearer stale-token",
            }
            self.assertEqual(app.ai_gateway_headers(settings), {})

            legacy_settings = {
                "ai_gateway_headers_json": "",
                "ai_gateway_auth_header_name": "Authorization",
                "ai_gateway_auth_header_value": "Bearer legacy-token",
            }
            self.assertEqual(app.ai_gateway_headers(legacy_settings), {"Authorization": "Bearer legacy-token"})


    def test_case_ai_freshness_workflow_filters_stale_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = CVDApplication(make_test_config(Path(tmp) / "cvd.sqlite3"), start_batch_worker=False)
            status, headers, body = call_wsgi(
                app,
                "/api/login",
                method="POST",
                body={"email": "admin@test.local", "password": "Test-admin-strong-password-2026"},
            )
            self.assertTrue(status.startswith("200"), body)
            cookie = headers["Set-Cookie"].split(";", 1)[0]
            status, _, body = call_wsgi(app, "/api/me", cookie=cookie)
            csrf = json.loads(body.decode("utf-8"))["csrfToken"]
            patient_data = {
                "GENERAL_INFO": {"Patient_ID": "E2E-1", "Age": 62, "Sex": "male"},
                "COMPLAINTS": {"Main_complaint": "Боль в груди"},
                "PHYSICAL_EXAM": {"Blood_pressure_right_systolic_mmHg": 145, "Heart_rate_bpm": 82},
                "ECG_AND_BP_MONITORING": {"Resting_ECG_summary": "Синусовый ритм"},
                "FINAL_DIAGNOSES": {"Main_cardiovascular_diagnosis_text": "ИБС?"},
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

            parsed = {
                "CDS_OUTPUT": {
                    "summary": "Проверить ишемический генез симптомов.",
                    "possible_diagnoses": [],
                    "red_flags": [],
                    "missing_data": [],
                    "recommended_next_data": [],
                    "limitations": [],
                    "model_should_abstain": False,
                },
                "MODEL_OUTPUT": {"Final_model_diagnosis": "ИБС под вопросом", "Model_ICD10_codes": ["I25.9"]},
            }
            with patch("cvd_web.handlers_ai.call_lm_studio", return_value=({"messages": []}, {"choices": []}, parsed, 1200)):
                status, _, body = call_wsgi(
                    app,
                    "/api/model/diagnose",
                    method="POST",
                    cookie=cookie,
                    csrf=csrf,
                    body={"case_id": case_id, "patient_data": patient_data},
                )
            self.assertTrue(status.startswith("200"), body)
            request_id = json.loads(body.decode("utf-8"))["request_id"]

            status, _, body = call_wsgi(app, "/api/cases?analysis=with", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            item = json.loads(body.decode("utf-8"))["cases"][0]
            self.assertEqual(item["latest_result_id"], request_id)
            self.assertFalse(item["ai_result_stale"])
            status, _, body = call_wsgi(app, f"/api/requests/{request_id}", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            self.assertFalse(json.loads(body.decode("utf-8"))["request"]["ai_result_stale"])

            changed_data = dict(patient_data)
            changed_data["PHYSICAL_EXAM"] = {**patient_data["PHYSICAL_EXAM"], "Heart_rate_bpm": 96}
            status, _, body = call_wsgi(
                app,
                "/api/cases",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={"case_id": case_id, "patient_data": changed_data},
            )
            self.assertTrue(status.startswith("200"), body)
            status, _, body = call_wsgi(app, "/api/cases?analysis=stale", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            stale_cases = json.loads(body.decode("utf-8"))["cases"]
            self.assertEqual([item["id"] for item in stale_cases], [case_id])
            self.assertTrue(stale_cases[0]["ai_result_stale"])
            status, _, body = call_wsgi(app, f"/api/requests/{request_id}", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            request = json.loads(body.decode("utf-8"))["request"]
            self.assertTrue(request["ai_result_stale"])
            self.assertEqual(request["ai_result_changes"][0]["path"], "PHYSICAL_EXAM.Heart_rate_bpm")
            self.assertEqual(request["ai_result_changes"][0]["before"], 82)
            self.assertEqual(request["ai_result_changes"][0]["after"], 96)

    def test_lm_studio_memory_error_is_user_friendly(self):
        message = lm_studio_http_error_message(
            400,
            json.dumps({"error": {"message": "Failed due to insufficient system resources; requires approximately 18 GB"}}),
        )
        self.assertIn("недостаточно памяти", message)
        self.assertIn("меньшую модель", message)
        self.assertNotIn("approximately", message)

    def test_html_report_escapes_patient_and_model_content(self):
        report = build_html_report(
            {"GENERAL_INFO": {"Patient_ID": "CASE-1", "Full_name": "<script>alert(1)</script>"}},
            {
                "CDS_OUTPUT": {
                    "summary": "Результат <опасный>",
                    "possible_diagnoses": [],
                    "red_flags": [],
                    "missing_data": [],
                    "recommended_next_data": [],
                    "limitations": [],
                    "model_should_abstain": False,
                },
                "MODEL_OUTPUT": {
                    "Final_model_diagnosis": "Диагноз <тег>",
                    "Model_ICD10_codes": ["I10"],
                    "Model_treatment_recommendations": "Контроль АД до целевых значений.",
                    "Model_rehabilitation_recommendations": "Отказ от курения, аэробные нагрузки.",
                },
            },
            {"request_id": 7, "model": "medgemma-4b-it"},
        )
        self.assertIn("onclick=\"window.print()\"", report)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", report)
        self.assertNotIn("<script>alert(1)</script>", report)
        self.assertIn("Результат &lt;опасный&gt;", report)
        self.assertIn("Черновик рекомендаций", report)
        self.assertIn("Тактика ведения", report)
        self.assertIn("Контроль АД до целевых значений.", report)
        self.assertIn("Отказ от курения", report)

    def test_html_report_is_a_printable_document(self):
        report = build_html_report(
            {
                "GENERAL_INFO": {"Patient_ID": "CVD-77", "Full_name": "Демо Пациент", "Age": 62, "Sex": "male"},
                "FINAL_DIAGNOSES": {
                    "Main_cardiovascular_diagnosis_text": "ИБС: стабильная стенокардия II ФК",
                    "ICD10_codes": ["I20.8", "I10"],
                },
            },
            {
                "CDS_OUTPUT": {
                    "summary": "Клиническая картина стабильной стенокардии.",
                    "possible_diagnoses": [
                        {"name": "ИБС", "icd10_codes": ["I20.8"], "confidence": "high", "supporting_findings": ["боль"]}
                    ],
                    "red_flags": [],
                    "missing_data": [],
                    "recommended_next_data": [],
                    "limitations": [],
                    "model_should_abstain": False,
                },
                "MODEL_OUTPUT": {
                    "Final_model_diagnosis": "ИБС: стабильная стенокардия напряжения II ФК",
                    "Model_ICD10_codes": ["I20.8", "I10"],
                    "Model_treatment_recommendations": "Контроль АД.",
                    "Model_rehabilitation_recommendations": "Отказ от курения.",
                },
            },
            {
                "request_id": 12,
                "case_id": 5,
                "generated_at": "2026-07-18T22:52:15+00:00",
                "doctor_name": "Иванов И.И.",
                "organization_name": "Health Heart",
            },
        )
        # Заключение идёт до обоснования: врач видит главное первым.
        self.assertLess(report.index("Заключение</h2>"), report.index("Обоснование AI"))
        self.assertIn("Диагноз врача", report)
        self.assertIn("ИБС: стабильная стенокардия II ФК", report)
        self.assertIn("Черновик AI", report)
        self.assertIn("ИБС: стабильная стенокардия напряжения II ФК", report)
        # Человеческая дата вместо ISO.
        self.assertIn("18 июля 2026, 22:52", report)
        self.assertNotIn("2026-07-18T22:52:15", report)
        # Подпись врача и колонтитул для печати.
        self.assertIn("Иванов И.И.", report)
        self.assertIn("Подпись", report)
        self.assertIn("running-head", report)
        self.assertIn("@page", report)
        self.assertIn("hide-appendix", report)
        # Исходные данные — приложением, с новой страницы.
        self.assertIn("Приложение: исходные данные пациента", report)
        self.assertIn("break-before:page", report)
        self.assertIn("Кейс №5", report)

    def test_exports_do_not_duplicate_icd_codes_from_the_diagnosis_text(self):
        # Промпт просит модель дописывать коды в конец заключения, а отчёт и текст
        # для МИС печатают их отдельной строкой — хвост нужно срезать.
        from cvd_web.reporting import build_mis_text

        patient_data = {
            "GENERAL_INFO": {"Patient_ID": "CVD-90"},
            "FINAL_DIAGNOSES": {"Main_cardiovascular_diagnosis_text": "ИБС", "ICD10_codes": ["I20.8"]},
        }
        parsed_output = {
            "CDS_OUTPUT": {
                "summary": "Сводка",
                "possible_diagnoses": [],
                "red_flags": [],
                "missing_data": [],
                "recommended_next_data": [],
                "limitations": [],
                "model_should_abstain": False,
            },
            "MODEL_OUTPUT": {
                "Final_model_diagnosis": "ИБС: стабильная стенокардия II ФК. ХБП C2. МКБ-10: I20.8, I10, N18.3",
                "Model_ICD10_codes": ["I20.8", "I10", "N18.3"],
                "Model_treatment_recommendations": "",
                "Model_rehabilitation_recommendations": "",
            },
        }

        text = build_mis_text(patient_data, parsed_output, {"request_id": 5})
        self.assertIn("ХБП C2.", text)
        self.assertEqual(text.count("I20.8, I10, N18.3"), 1)
        self.assertIn("МКБ-10: I20.8, I10, N18.3", text)

        report = build_html_report(patient_data, parsed_output, {"request_id": 5})
        self.assertIn("ХБП C2.", report)
        self.assertNotIn("МКБ-10: I20.8, I10, N18.3", report)

    def test_html_report_falls_back_to_leading_ai_diagnosis_and_marks_abstain(self):
        report = build_html_report(
            {"GENERAL_INFO": {"Patient_ID": "CVD-78"}},
            {
                "CDS_OUTPUT": {
                    "summary": "Данных недостаточно.",
                    "possible_diagnoses": [],
                    "red_flags": [],
                    "missing_data": [],
                    "recommended_next_data": [],
                    "limitations": [],
                    "model_should_abstain": True,
                },
                "MODEL_OUTPUT": {
                    "Final_model_diagnosis": "",
                    "Model_ICD10_codes": [],
                    "Model_treatment_recommendations": "",
                    "Model_rehabilitation_recommendations": "",
                },
            },
            {"request_id": 13},
        )
        self.assertIn("AI воздержался от заключения", report)
        self.assertIn("Рабочий диагноз врача не заполнен", report)

    def test_html_report_omits_recommendations_when_model_did_not_provide_them(self):
        report = build_html_report(
            {"GENERAL_INFO": {"Patient_ID": "CASE-2"}},
            {
                "CDS_OUTPUT": {
                    "summary": "Сводка",
                    "possible_diagnoses": [],
                    "red_flags": [],
                    "missing_data": [],
                    "recommended_next_data": [],
                    "limitations": [],
                    "model_should_abstain": False,
                },
                "MODEL_OUTPUT": {
                    "Final_model_diagnosis": "Диагноз",
                    "Model_ICD10_codes": [],
                    "Model_treatment_recommendations": "",
                    "Model_rehabilitation_recommendations": "",
                },
            },
            {"request_id": 8},
        )
        self.assertNotIn("Черновик рекомендаций", report)

    def test_lm_studio_v1_catalog_and_activation(self):
        initial = {
            "models": [
                {
                    "type": "llm",
                    "key": "medgemma-4b-it",
                    "display_name": "MedGemma 4B",
                    "params_string": "4B",
                    "quantization": "Q4_K_S",
                    "loaded_instances": [{"id": "medgemma-4b-it", "config": {"context_length": 8192}}],
                },
                {
                    "type": "llm",
                    "key": "old-model",
                    "loaded_instances": [{"id": "old-model-instance", "load_config": {"context_length": 4096}}],
                },
            ]
        }
        refreshed = {
            "models": [
                {
                    "type": "llm",
                    "key": "medgemma-4b-it",
                    "loaded_instances": [{"id": "medgemma-4b-it", "load_config": {"context_length": 8192}}],
                },
                {"type": "llm", "key": "old-model", "loaded_instances": []},
            ]
        }
        with patch("cvd_web.lmstudio_models._request_json", return_value=initial) as request_json:
            catalog = list_lm_models(
                "http://127.0.0.1:1234/v1/chat/completions",
                extra_headers={"Authorization": "Bearer tunnel-token"},
            )
        self.assertEqual(request_json.call_args.kwargs["extra_headers"], {"Authorization": "Bearer tunnel-token"})
        self.assertEqual(catalog["api_version"], "v1")
        self.assertEqual(catalog["models"][0]["loaded_context_length"], 8192)

        with patch("cvd_web.lmstudio_models._request_json", side_effect=[initial, {}, refreshed]) as request_json:
            result = activate_lm_model(
                "http://127.0.0.1:1234/v1/chat/completions",
                "medgemma-4b-it",
                previous_model_id="old-model",
            )
        self.assertEqual(result["selected"]["state"], "loaded")
        self.assertEqual(result["unloaded_instances"], ["old-model-instance"])
        self.assertIn("/api/v1/models/unload", request_json.call_args_list[1].args[0])

    def test_model_activation_unloads_unexpected_active_model_before_loading_selected(self):
        initial = {
            "models": [
                {"type": "llm", "key": "medgemma-4b-it", "loaded_instances": []},
                {
                    "type": "llm",
                    "key": "medgemma-27b-text-it",
                    "loaded_instances": [{"id": "medgemma-27b-text-it", "config": {"context_length": 3500}}],
                },
            ]
        }
        refreshed = {
            "models": [
                {
                    "type": "llm",
                    "key": "medgemma-4b-it",
                    "loaded_instances": [{"id": "medgemma-4b-it", "config": {"context_length": 8192}}],
                },
                {"type": "llm", "key": "medgemma-27b-text-it", "loaded_instances": []},
            ]
        }
        with patch("cvd_web.lmstudio_models._request_json", side_effect=[initial, {}, {}, refreshed]) as request_json:
            result = activate_lm_model(
                "http://127.0.0.1:1234/v1/chat/completions",
                "medgemma-4b-it",
                previous_model_id="medgemma-4b-it",
            )
        self.assertEqual(result["unloaded_instances"], ["medgemma-27b-text-it"])
        self.assertIn("/api/v1/models/unload", request_json.call_args_list[1].args[0])
        self.assertIn("/api/v1/models/load", request_json.call_args_list[2].args[0])

    def test_password_hash_verify(self):
        encoded = hash_password("secret-password")
        self.assertTrue(verify_password("secret-password", encoded))
        self.assertFalse(verify_password("other-password", encoded))

    def test_extract_json_from_markdown_response(self):
        parsed = extract_json_from_text('text before ```json\n{"MODEL_OUTPUT":{"Model_ICD10_codes":["I10"]}}\n``` after')
        self.assertEqual(parsed["MODEL_OUTPUT"]["Model_ICD10_codes"], ["I10"])

    def test_structured_request_and_output_normalization(self):
        request = build_chat_request(
            {"GENERAL_INFO": {"Patient_ID": "SYNTH_1"}},
            "medgemma-27b-text-it-mlx",
            1024,
            temperature=0.1,
        )
        self.assertEqual(request["response_format"]["type"], "json_schema")
        self.assertEqual(request["stream"], True)
        self.assertEqual(request["stream_options"], {"include_usage": True})
        response_schema = request["response_format"]["json_schema"]["schema"]
        self.assertEqual(response_schema["required"], ["CDS_OUTPUT", "MODEL_OUTPUT"])
        self.assertEqual(
            response_schema["properties"]["CDS_OUTPUT"]["properties"]["possible_diagnoses"]["maxItems"],
            3,
        )
        self.assertEqual(
            response_schema["properties"]["MODEL_OUTPUT"]["required"],
            [
                "Final_model_diagnosis",
                "Model_ICD10_codes",
                "Model_treatment_recommendations",
                "Model_rehabilitation_recommendations",
            ],
        )
        prompt = request["messages"][1]["content"]
        self.assertIn("SYNTH_1", prompt)
        self.assertIn("Model_treatment_recommendations", prompt)
        self.assertNotIn("{{PATIENT_JSON}}", prompt)
        self.assertNotIn("{{PROMPT_VERSION}}", prompt)
        self.assertNotIn(
            "response_format",
            build_chat_request({}, "model", 128, structured_output=False),
        )

        normalized = normalize_model_output({
            "CDS_OUTPUT": {
                "summary": "Тестовый ответ",
                "possible_diagnoses": [
                    {
                        "name": "Диагноз",
                        "icd10_codes": ["i10", "bad-code"],
                        "confidence": "unexpected",
                        "supporting_findings": ["Факт"],
                        "against_findings": [],
                        "missing_data": [],
                    }
                ],
                "red_flags": [],
                "missing_data": [],
                "recommended_next_data": [],
                "limitations": [],
                "model_should_abstain": False,
            },
            "MODEL_OUTPUT": {
                "Final_model_diagnosis": "Диагноз",
                "Model_ICD10_codes": ["i10", "bad-code"],
                "Model_treatment_recommendations": "Антиагрегантная терапия, контроль АД до целевых значений.",
                "Model_rehabilitation_recommendations": "Регулярная физическая активность, отказ от курения.",
            },
        })
        self.assertEqual(normalized["CDS_OUTPUT"]["possible_diagnoses"][0]["icd10_codes"], ["I10"])
        self.assertEqual(normalized["CDS_OUTPUT"]["possible_diagnoses"][0]["confidence"], "medium")
        self.assertEqual(normalized["MODEL_OUTPUT"]["Model_ICD10_codes"], ["I10"])
        self.assertIn("Антиагрегантная", normalized["MODEL_OUTPUT"]["Model_treatment_recommendations"])
        self.assertIn("физическая активность", normalized["MODEL_OUTPUT"]["Model_rehabilitation_recommendations"])

    def test_truncated_model_response_is_rejected_with_diagnostics(self):
        raw_response = {
            "choices": [{"finish_reason": "length", "message": {"content": '{"CDS_OUTPUT": {'}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 768, "total_tokens": 868},
        }
        with patch(
            "cvd_web.lmstudio.call_json_lm_studio",
            return_value=(raw_response, '{"CDS_OUTPUT": {', 2500),
        ):
            with self.assertRaises(LMStudioError) as context:
                call_lm_studio(
                    api_url="http://127.0.0.1:1234/v1/chat/completions",
                    model="medgemma-4b-it",
                    patient_data={"GENERAL_INFO": {"Patient_ID": "TEST"}},
                    timeout_seconds=10,
                    max_tokens=768,
                )
        self.assertIn("max_tokens=768", str(context.exception))
        self.assertEqual(context.exception.duration_ms, 2500)
        self.assertEqual(context.exception.response_payload["raw"]["choices"][0]["finish_reason"], "length")
        self.assertEqual(context.exception.request_body["max_tokens"], 768)

    def test_lm_studio_http_requests_send_user_agent(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode("utf-8")

        request_body = {
            "model": "medgemma-4b-it",
            "messages": [{"role": "user", "content": "ok"}],
        }
        with patch("cvd_web.lmstudio.urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
            call_json_lm_studio(
                api_url="https://api-cvd.granyov.com/v1/chat/completions",
                request_body=request_body,
                timeout_seconds=5,
            )
            request = urlopen.call_args.args[0]
            headers = {key.lower(): value for key, value in request.header_items()}
            self.assertEqual(headers["user-agent"], LM_STUDIO_USER_AGENT)

            call_json_lm_studio(
                api_url="https://api-cvd.granyov.com/v1/chat/completions",
                request_body=request_body,
                timeout_seconds=5,
                extra_headers={"User-Agent": "CVD-Web/override"},
            )
            request = urlopen.call_args.args[0]
            headers = {key.lower(): value for key, value in request.header_items()}
            self.assertEqual(headers["user-agent"], "CVD-Web/override")

    def test_lm_studio_streaming_response_is_collected(self):
        class FakeStreamResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def __iter__(self):
                lines = [
                    {"id": "stream-1", "model": "medgemma", "choices": [{"delta": {"role": "assistant"}}]},
                    {"choices": [{"delta": {"content": "{\"CDS_OUTPUT\":"}}]},
                    {
                        "choices": [{"delta": {"content": "{\"summary\":\"ok\"}}"}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
                    },
                ]
                for item in lines:
                    yield f"data: {json.dumps(item)}\n\n".encode("utf-8")
                yield b"data: [DONE]\n\n"

        request_body = {
            "model": "medgemma",
            "messages": [{"role": "user", "content": "ok"}],
            "stream": True,
        }
        with patch("cvd_web.lmstudio.urllib.request.urlopen", return_value=FakeStreamResponse()) as urlopen:
            response_json, content, _ = call_json_lm_studio(
                api_url="https://api-cvd.granyov.com/v1/chat/completions",
                request_body=request_body,
                timeout_seconds=5,
            )
        request = urlopen.call_args.args[0]
        headers = {key.lower(): value for key, value in request.header_items()}
        sent_body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(headers["accept"], "text/event-stream")
        self.assertEqual(sent_body["stream_options"], {"include_usage": True})
        self.assertEqual(content, "{\"CDS_OUTPUT\":{\"summary\":\"ok\"}}")
        self.assertEqual(response_json["choices"][0]["finish_reason"], "stop")
        self.assertEqual(response_json["choices"][0]["message"]["content"], content)
        self.assertEqual(response_json["usage"]["completion_tokens"], 2)
        self.assertEqual(response_json["stream_chunk_count"], 3)

    def test_lm_studio_streaming_falls_back_to_plain_json(self):
        class FakePlainJsonResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def __iter__(self):
                yield json.dumps({
                    "choices": [{"message": {"content": "{\"CDS_OUTPUT\":{\"summary\":\"plain\"}}"}}],
                    "usage": {"completion_tokens": 1},
                }).encode("utf-8")

        with patch("cvd_web.lmstudio.urllib.request.urlopen", return_value=FakePlainJsonResponse()):
            response_json, content, _ = call_json_lm_studio(
                api_url="https://api-cvd.granyov.com/v1/chat/completions",
                request_body={"model": "plain", "messages": [], "stream": True},
                timeout_seconds=5,
            )
        self.assertEqual(content, "{\"CDS_OUTPUT\":{\"summary\":\"plain\"}}")
        self.assertEqual(response_json["usage"]["completion_tokens"], 1)

    def test_direct_patient_identifiers_are_deidentified(self):
        cleaned, signals = deidentify_patient_data({
            "GENERAL_INFO": {
                "Patient_ID": "CASE_17",
                "Full_name": "Тестов Тест Тестович",
            }
        })
        self.assertEqual(cleaned["GENERAL_INFO"]["Patient_ID"], "[CASE_ID]")
        self.assertEqual(cleaned["GENERAL_INFO"]["Full_name"], "[PATIENT_NAME]")
        self.assertIn({"kind": "patient_id", "path": "GENERAL_INFO.Patient_ID"}, signals)
        self.assertIn({"kind": "patient_name", "path": "GENERAL_INFO.Full_name"}, signals)

    def test_login_csrf_and_case_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = CVDApplication(make_test_config(Path(tmp) / "cvd.sqlite3"), start_batch_worker=False)

            status, _, body = call_wsgi(app, "/healthz")
            self.assertTrue(status.startswith("200"), body)
            self.assertEqual(json.loads(body.decode("utf-8"))["ok"], True)
            status, _, body = call_wsgi(app, "/readyz")
            self.assertTrue(status.startswith("200"), body)
            readiness = json.loads(body.decode("utf-8"))
            self.assertTrue(readiness["ok"])
            self.assertTrue(readiness["checks"]["database"]["ok"])
            self.assertFalse(readiness["checks"]["security"]["production_mode"])
            _, health_headers, _ = call_wsgi(app, "/healthz")
            self.assertIn("Content-Security-Policy", health_headers)
            self.assertEqual(health_headers["X-Frame-Options"], "DENY")

            status, _, body = call_wsgi(app, "/login")
            login_html = body.decode("utf-8")
            self.assertTrue(status.startswith("200"), body)
            self.assertNotIn("lm_studio_api_url", login_html)
            self.assertNotIn("127.0.0.1:1234", login_html)

            status, headers, body = call_wsgi(
                app,
                "/api/login",
                method="POST",
                body={"email": "admin@test.local", "password": "Test-admin-strong-password-2026"},
            )
            self.assertTrue(status.startswith("200"), body)
            cookie = headers["Set-Cookie"].split(";", 1)[0]

            status, _, body = call_wsgi(app, "/api/me", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            csrf = json.loads(body.decode("utf-8"))["csrfToken"]

            status, _, body = call_wsgi(
                app,
                "/api/model/diagnose",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={"patient_data": {"GENERAL_INFO": {"Patient_ID": None}}},
            )
            self.assertTrue(status.startswith("400"), body)
            self.assertIn("Добавьте данные пациента", body.decode("utf-8"))
            with connect(app.config.db_path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM model_requests").fetchone()[0], 0)

            status, _, body = call_wsgi(app, "/app", cookie=cookie)
            app_html = body.decode("utf-8")
            self.assertTrue(status.startswith("200"), body)
            self.assertNotIn("lm_studio_api_url", app_html)
            self.assertNotIn("127.0.0.1:1234", app_html)
            self.assertNotIn("LM Studio", app_html)
            self.assertNotIn("MedGemma", app_html)
            self.assertIn("Кейсы и история", app_html)
            self.assertNotIn("tab-history", app_html)

            status, _, body = call_wsgi(app, "/cases", cookie=cookie)
            cases_html = body.decode("utf-8")
            self.assertTrue(status.startswith("200"), body)
            self.assertIn("Медицинский архив", cases_html)
            self.assertIn("/static/js/cases.js", cases_html)

            status, _, body = call_wsgi(app, "/api/admin/requests?limit=abc", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)

            status, _, body = call_wsgi(
                app,
                "/api/admin/users/1/update",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={"full_name": "Only Admin", "role": "user", "is_active": True},
            )
            self.assertTrue(status.startswith("400"), body)

            patient_data = {"GENERAL_INFO": {"Patient_ID": "CASE_1"}, "FINAL_DIAGNOSES": {}}
            status, _, body = call_wsgi(
                app,
                "/api/cases",
                method="POST",
                cookie=cookie,
                body={"patient_data": patient_data},
            )
            self.assertTrue(status.startswith("403"), body)

            status, _, body = call_wsgi(
                app,
                "/api/cases",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={"patient_data": patient_data},
                headers={"Sec-Fetch-Site": "cross-site"},
            )
            self.assertTrue(status.startswith("403"), body)

            status, _, body = call_wsgi(
                app,
                "/api/cases",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={"patient_data": patient_data},
                headers={"Origin": "http://127.0.0.1"},
            )
            self.assertTrue(status.startswith("200"), body)
            self.assertEqual(json.loads(body.decode("utf-8"))["case_id"], 1)

            status, _, body = call_wsgi(
                app,
                "/api/cases",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={"patient_data": {"GENERAL_INFO": {"Unknown": "x"}}},
            )
            self.assertTrue(status.startswith("400"), body)
            self.assertIn("Неизвестное поле", body.decode("utf-8"))

            status, _, body = call_wsgi(
                app,
                "/api/cases",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={"patient_data": {"FINAL_DIAGNOSES": {"ICD10_codes": "I10; bad-code"}}},
            )
            self.assertTrue(status.startswith("400"), body)
            self.assertIn("некорректный код", body.decode("utf-8"))

            status, _, body = call_wsgi(
                app,
                "/api/cases",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={
                    "patient_data": {
                        "GENERAL_INFO": {
                            "Patient_ID": "CASE_2",
                            "Full_name": "Тестов Тест Тестович",
                            "Age": "64,5",
                        },
                        "FINAL_DIAGNOSES": {"ICD10_codes": "i10; i25.1"},
                    }
                },
            )
            self.assertTrue(status.startswith("200"), body)
            self.assertIn("Тестов Тест Тестович", json.loads(body.decode("utf-8"))["title"])
            with connect(app.config.db_path) as conn:
                row = conn.execute("SELECT data_json FROM cases WHERE id = 2").fetchone()
            stored = json.loads(row["data_json"])
            self.assertEqual(stored["GENERAL_INFO"]["Age"], 64.5)
            self.assertEqual(stored["GENERAL_INFO"]["Full_name"], "Тестов Тест Тестович")
            self.assertEqual(stored["FINAL_DIAGNOSES"]["ICD10_codes"], ["I10", "I25.1"])

            status, _, body = call_wsgi(app, "/api/cases?limit=1", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            paged_cases = json.loads(body.decode("utf-8"))
            self.assertEqual(paged_cases["total"], 2)
            self.assertTrue(paged_cases["has_more"])

            status, _, body = call_wsgi(app, "/api/cases?q=CASE_2&limit=1", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            case_search = json.loads(body.decode("utf-8"))
            self.assertEqual(case_search["total"], 1)
            self.assertFalse(case_search["has_more"])
            self.assertIsNone(case_search["cases"][0]["latest_result_id"])

            status, _, body = call_wsgi(app, "/api/cases/2/fhir", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            bundle = json.loads(body.decode("utf-8"))
            self.assertEqual(bundle["resourceType"], "Bundle")
            resource_types = {entry["resource"]["resourceType"] for entry in bundle["entry"]}
            self.assertIn("Patient", resource_types)
            self.assertIn("Condition", resource_types)
            patient = next(entry["resource"] for entry in bundle["entry"] if entry["resource"]["resourceType"] == "Patient")
            self.assertEqual(patient["name"][0]["text"], "Тестов Тест Тестович")

            status, _, body = call_wsgi(
                app,
                "/api/import/preview",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={"source_format": "fhir", "filename": "case.fhir.json", "payload": bundle},
            )
            self.assertTrue(status.startswith("200"), body)
            import_preview = json.loads(body.decode("utf-8"))
            self.assertEqual(import_preview["source_format"], "fhir-r4")
            self.assertTrue(import_preview["mapping_version"].startswith("cvd-import-map-"))
            self.assertGreater(import_preview["summary"]["mapped_fields"], 0)
            selected_path = import_preview["mappings"][0]["path"]

            status, _, body = call_wsgi(
                app,
                f"/api/imports/{import_preview['import_id']}/applied",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={"case_id": 2, "selected_paths": [selected_path, "UNKNOWN.field"]},
            )
            self.assertTrue(status.startswith("200"), body)
            self.assertEqual(json.loads(body.decode("utf-8"))["selected_count"], 1)

            status, _, body = call_wsgi(app, "/api/imports", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            imports = json.loads(body.decode("utf-8"))["imports"]
            self.assertEqual(imports[0]["status"], "applied")
            self.assertEqual(imports[0]["source_format"], "fhir-r4")
            with connect(app.config.db_path) as conn:
                import_columns = {row["name"] for row in conn.execute("PRAGMA table_info(data_imports)").fetchall()}
                stored_import = conn.execute("SELECT * FROM data_imports WHERE id = ?", (import_preview["import_id"],)).fetchone()
            self.assertNotIn("raw_content", import_columns)
            self.assertIn("mapping_version", import_columns)
            self.assertIn("mapped_paths_json", import_columns)
            self.assertEqual(len(stored_import["content_sha256"]), 64)
            self.assertIn(selected_path, json.loads(stored_import["mapped_paths_json"]))

            status, _, body = call_wsgi(app, "/api/admin/quality", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            quality = json.loads(body.decode("utf-8"))
            self.assertGreaterEqual(quality["summary"]["cases"], 1)
            self.assertIn("avg_completeness_percent", quality["summary"])

            status, _, body = call_wsgi(app, "/api/admin/settings", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            settings = {item["key"]: item["value"] for item in json.loads(body.decode("utf-8"))["settings"]}
            self.assertIn("ai_gateway_profile", settings)
            self.assertIn("ai_gateway_headers_json", settings)
            self.assertIn("ai_gateway_auth_header_name", settings)
            self.assertIn("ai_gateway_auth_header_value", settings)
            self.assertIn("lm_studio_temperature", settings)
            self.assertIn("lm_studio_structured_output", settings)
            self.assertEqual(settings["lm_studio_max_concurrent"], "1")
            self.assertEqual(settings["lm_studio_queue_limit"], "64")
            self.assertEqual(settings["lm_studio_per_user_limit"], "2")
            self.assertEqual(settings["inference_queue_backend"], "memory")
            self.assertIn("inference_queue_dsn", settings)
            self.assertEqual(settings["rate_limit_backend"], "memory")
            self.assertIn("rate_limit_dsn", settings)
            self.assertEqual(settings["inference_worker_mode"], "in_process")
            self.assertIn("text_structuring_model", settings)
            self.assertIn("deidentify_before_model", settings)
            self.assertIn("active_prompt_version", settings)
            self.assertIn("active_prompt_template", settings)
            self.assertEqual(settings["gold_min_score_percent"], "80")
            self.assertIn("{{PATIENT_JSON}}", settings["active_prompt_template"])

            updated_settings = dict(settings)
            updated_settings["ai_gateway_profile"] = "cloudflared"
            updated_settings["ai_gateway_headers_json"] = json.dumps([
                {"name": "User-Agent", "value": "CVD-Web/0.9"},
                {"name": "CF-Access-Client-Id", "value": "client-id"},
                {"name": "CF-Access-Client-Secret", "value": "client-secret"},
            ])
            updated_settings["active_prompt_version"] = "test-prompt-v2"
            updated_settings["active_prompt_template"] = "Clinical prompt\n{{PATIENT_JSON}}"
            updated_settings["gold_min_score_percent"] = "80"
            updated_settings["inference_queue_backend"] = "redis"
            updated_settings["inference_queue_dsn"] = "redis://localhost:6379/0"
            updated_settings["rate_limit_backend"] = "redis"
            updated_settings["rate_limit_dsn"] = "redis://localhost:6379/1"
            updated_settings["inference_worker_mode"] = "external"
            status, _, body = call_wsgi(
                app,
                "/api/admin/settings",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={"settings": updated_settings},
            )
            self.assertTrue(status.startswith("200"), body)

            status, _, body = call_wsgi(app, "/api/admin/security-audit", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            security_audit = json.loads(body.decode("utf-8"))
            security_checks = {item["key"]: item for item in security_audit["checks"]}
            self.assertTrue(security_checks["default_admin_password"]["ok"])
            self.assertTrue(security_checks["cloudflared_access_headers"]["ok"])

            status, _, body = call_wsgi(app, "/api/admin/audit?limit=10", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            audit_items = json.loads(body.decode("utf-8"))["audit"]
            settings_audit = next(item for item in audit_items if item["action"] == "settings_update")
            details_text = json.dumps(settings_audit["details"], ensure_ascii=False)
            self.assertNotIn("client-secret", details_text)
            self.assertNotIn("redis://localhost:6379", details_text)
            changed_by_key = {item["key"]: item for item in settings_audit["details"]["changed"]}
            self.assertEqual(changed_by_key["ai_gateway_headers_json"]["new"]["count"], 3)
            self.assertEqual(changed_by_key["rate_limit_dsn"]["new"]["configured"], True)

            status, _, body = call_wsgi(app, "/api/admin/dashboard", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            production_queue = json.loads(body.decode("utf-8"))["production_queue"]
            self.assertEqual(production_queue["backend"], "redis")
            self.assertEqual(production_queue["active_backend"], "memory")
            self.assertEqual(production_queue["rate_limit_backend"], "redis")
            self.assertEqual(production_queue["worker_mode"], "external")
            self.assertFalse(production_queue["production_ready"])

            with patch("cvd_web.handlers_admin.list_lm_models", return_value={"api_version": "v1", "models": [{"id": "healtheart-cvd-engine", "state": "loaded", "loaded_context_length": 8192}]}) as list_models:
                status, _, body = call_wsgi(
                    app,
                    "/api/admin/ai-gateway/test",
                    method="POST",
                    cookie=cookie,
                    csrf=csrf,
                    body={"api_url": "https://cvd-ai.example.com/v1/chat/completions", "model": "healtheart-cvd-engine"},
                )
            self.assertTrue(status.startswith("200"), body)
            gateway_test = json.loads(body.decode("utf-8"))
            self.assertTrue(gateway_test["ok"])
            self.assertEqual(gateway_test["gateway"]["profile"], "cloudflared")
            self.assertEqual(gateway_test["gateway"]["auth_header_count"], 3)
            self.assertEqual(list_models.call_args.kwargs["extra_headers"], {
                "User-Agent": "CVD-Web/0.9",
                "CF-Access-Client-Id": "client-id",
                "CF-Access-Client-Secret": "client-secret",
            })

            invalid_queue_settings = dict(updated_settings)
            invalid_queue_settings["inference_queue_backend"] = "postgresql"
            invalid_queue_settings["inference_queue_dsn"] = ""
            status, _, body = call_wsgi(
                app,
                "/api/admin/settings",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={"settings": invalid_queue_settings},
            )
            self.assertTrue(status.startswith("400"), body)

            invalid_rate_limit_settings = dict(updated_settings)
            invalid_rate_limit_settings["rate_limit_backend"] = "postgresql"
            invalid_rate_limit_settings["rate_limit_dsn"] = ""
            status, _, body = call_wsgi(
                app,
                "/api/admin/settings",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={"settings": invalid_rate_limit_settings},
            )
            self.assertTrue(status.startswith("400"), body)

            invalid_settings = dict(updated_settings)
            invalid_settings["active_prompt_template"] = "Clinical prompt without placeholder"
            status, _, body = call_wsgi(
                app,
                "/api/admin/settings",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={"settings": invalid_settings},
            )
            self.assertTrue(status.startswith("400"), body)
            self.assertIn("{{PATIENT_JSON}}", body.decode("utf-8"))

            with connect(app.config.db_path) as conn:
                columns = {row["name"] for row in conn.execute("PRAGMA table_info(model_requests)").fetchall()}
                schema_migrations = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
            self.assertIn("prompt_version", columns)
            self.assertIn("settings_snapshot_json", columns)
            self.assertIn("completion_tokens", columns)
            self.assertIn("tokens_per_second", columns)
            self.assertIn("finish_reason", columns)
            self.assertIn("queue_wait_ms", columns)
            self.assertIn("input_data_hash", columns)
            self.assertGreaterEqual(schema_migrations, 1)

            status, _, body = call_wsgi(app, "/api/inference/status", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            queue = json.loads(body.decode("utf-8"))["queue"]
            self.assertEqual(queue["max_concurrent"], 1)
            self.assertEqual(queue["user"]["state"], "idle")

            parsed_output = {
                "CDS_OUTPUT": {
                    "summary": "Вероятна артериальная гипертензия, требуется верификация.",
                    "possible_diagnoses": [
                        {
                            "name": "Артериальная гипертензия",
                            "icd10_codes": ["I10"],
                            "confidence": "medium",
                            "supporting_findings": ["АД повышено"],
                            "against_findings": [],
                            "missing_data": ["Суточный профиль АД"],
                        }
                    ],
                    "red_flags": [],
                    "missing_data": [],
                    "recommended_next_data": [],
                    "limitations": [],
                    "model_should_abstain": False,
                },
                "MODEL_OUTPUT": {"Final_model_diagnosis": "АГ", "Model_ICD10_codes": ["I10"]},
            }
            with connect(app.config.db_path) as conn:
                cur = conn.execute(
                    """
                    INSERT INTO model_requests
                      (user_id, case_id, status, api_url, model, request_json, response_json,
                       parsed_output_json, prompt_version, schema_version, output_schema_version,
                       settings_snapshot_json, deidentified_input_json, phi_signals_json,
                       error, duration_ms, created_at)
                    VALUES (?, ?, 'success', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                    """,
                    (
                        1,
                        2,
                        "http://127.0.0.1:1234/v1/chat/completions",
                        "healtheart-cvd-engine",
                        json.dumps({"messages": []}, ensure_ascii=False),
                        json.dumps({"choices": []}, ensure_ascii=False),
                        json.dumps(parsed_output, ensure_ascii=False),
                        "test-prompt-v2",
                        "patient-schema-test",
                        "output-schema-test",
                        json.dumps({"active_prompt_version": "test-prompt-v2"}, ensure_ascii=False),
                        json.dumps(patient_data, ensure_ascii=False),
                        json.dumps([], ensure_ascii=False),
                        42,
                        utc_now(),
                    ),
                )
                request_id = cur.lastrowid

            status, report_headers, body = call_wsgi(
                app,
                "/api/reports/html",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={"request_id": request_id, "patient_data": patient_data},
            )
            self.assertTrue(status.startswith("200"), body)
            self.assertEqual(report_headers["Content-Type"], "text/html; charset=utf-8")
            self.assertIn(f"cvd-report-{request_id}.html", report_headers["Content-Disposition"])
            self.assertIn("Печать / Сохранить PDF", body.decode("utf-8"))
            self.assertNotIn("healtheart-cvd-engine", body.decode("utf-8"))
            self.assertNotIn("LM Studio", body.decode("utf-8"))

            status, report_headers, body = call_wsgi(app, f"/reports/{request_id}", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            self.assertTrue(report_headers["Content-Disposition"].startswith("inline;"))
            self.assertIn("Тестов Тест Тестович", body.decode("utf-8"))
            self.assertNotIn("healtheart-cvd-engine", body.decode("utf-8"))

            status, _, body = call_wsgi(app, "/api/cases?q=CASE_2&limit=1", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            case_search = json.loads(body.decode("utf-8"))
            self.assertEqual(case_search["cases"][0]["latest_result_id"], request_id)
            self.assertEqual(case_search["cases"][0]["analysis_count"], 1)

            status, _, body = call_wsgi(app, "/api/cases?analysis=with", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            self.assertEqual([item["id"] for item in json.loads(body.decode("utf-8"))["cases"]], [2])

            status, _, body = call_wsgi(
                app,
                f"/api/requests?status=success&case_id=2&q={request_id}&limit=1",
                cookie=cookie,
            )
            self.assertTrue(status.startswith("200"), body)
            request_search = json.loads(body.decode("utf-8"))
            self.assertEqual(request_search["total"], 1)
            self.assertEqual(request_search["requests"][0]["case_title"], "Тестов Тест Тестович · CASE_2")

            status, _, body = call_wsgi(app, f"/api/requests/{request_id}", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            self.assertEqual(json.loads(body.decode("utf-8"))["request"]["id"], request_id)

            status, _, body = call_wsgi(app, "/api/library/summary", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            library_summary = json.loads(body.decode("utf-8"))["summary"]
            self.assertEqual(library_summary["cases_total"], 2)
            self.assertEqual(library_summary["requests_success"], 1)

            status, _, body = call_wsgi(app, "/api/admin/backups", method="POST", cookie=cookie, csrf=csrf, body={})
            self.assertTrue(status.startswith("201"), body)
            backup = json.loads(body.decode("utf-8"))["backup"]
            self.assertTrue(backup["filename"].startswith("cvd-"))
            status, backup_headers, backup_body = call_wsgi(app, f"/api/admin/backups/{backup['filename']}", cookie=cookie)
            self.assertTrue(status.startswith("200"), backup_body)
            self.assertEqual(backup_headers["Content-Type"], "application/octet-stream")
            self.assertGreater(len(backup_body), 100)
            status, _, body = call_wsgi(app, "/api/admin/backups", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            self.assertEqual(json.loads(body.decode("utf-8"))["backups"][0]["filename"], backup["filename"])
            status, _, body = call_wsgi(app, "/api/admin/restore", method="POST", cookie=cookie, csrf=csrf, body={"filename": backup["filename"]})
            self.assertTrue(status.startswith("200"), body)
            self.assertIn("safety_backup", json.loads(body.decode("utf-8")))

            status, _, body = call_wsgi(
                app,
                "/api/cases/2/copy",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={},
            )
            self.assertTrue(status.startswith("201"), body)
            copied_case_id = json.loads(body.decode("utf-8"))["case_id"]
            status, _, body = call_wsgi(app, f"/api/cases/{copied_case_id}", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            copied_case = json.loads(body.decode("utf-8"))["case"]
            self.assertTrue(copied_case["title"].startswith("Копия:"))
            self.assertTrue(all(value is None for value in copied_case["data"]["MODEL_OUTPUT"].values()))

            now = utc_now()
            with connect(app.config.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO users
                      (email, full_name, password_hash, role, is_active, must_change_password, created_at, updated_at)
                    VALUES (?, ?, ?, 'user', 1, 0, ?, ?)
                    """,
                    ("doctor@test.local", "Doctor", hash_password("User-password-2026!"), now, now),
                )
            status, user_headers, body = call_wsgi(
                app,
                "/api/login",
                method="POST",
                body={"email": "doctor@test.local", "password": "User-password-2026!"},
            )
            self.assertTrue(status.startswith("200"), body)
            user_cookie = user_headers["Set-Cookie"].split(";", 1)[0]
            _, _, body = call_wsgi(app, "/api/me", cookie=user_cookie)
            user_csrf = json.loads(body.decode("utf-8"))["csrfToken"]
            status, _, _ = call_wsgi(app, f"/reports/{request_id}", cookie=user_cookie)
            self.assertTrue(status.startswith("404"))
            status, _, _ = call_wsgi(
                app,
                "/api/cases/2/copy",
                method="POST",
                cookie=user_cookie,
                csrf=user_csrf,
                body={},
            )
            self.assertTrue(status.startswith("404"))

            status, _, body = call_wsgi(
                app,
                f"/api/requests/{request_id}/review",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={
                    "rating": "partial",
                    "issue_types": ["missing_data"],
                    "corrected_diagnosis": "Требуется подтверждение диагноза",
                    "corrected_icd10": ["I10"],
                    "comment": "Нужно больше данных.",
                },
            )
            self.assertTrue(status.startswith("200"), body)

            status, _, body = call_wsgi(app, "/api/requests", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            requests = json.loads(body.decode("utf-8"))["requests"]
            reviewed = next(item for item in requests if item["id"] == request_id)
            self.assertEqual(reviewed["review"]["rating"], "partial")
            self.assertEqual(reviewed["review"]["corrected_icd10"], ["I10"])
            self.assertEqual(reviewed["result_flags"]["review_rating"], "partial")

            status, _, body = call_wsgi(
                app,
                "/api/requests?model=healtheart-cvd-engine&review=partial&red_flags=without&abstain=no",
                cookie=cookie,
            )
            self.assertTrue(status.startswith("200"), body)
            filtered = json.loads(body.decode("utf-8"))
            self.assertEqual(filtered["total"], 1)
            self.assertEqual(filtered["requests"][0]["id"], request_id)
            self.assertEqual(filtered["filters"]["models"], ["healtheart-cvd-engine"])

            status, _, body = call_wsgi(app, "/api/requests?review=unsafe", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            self.assertEqual(json.loads(body.decode("utf-8"))["total"], 0)

            status, _, body = call_wsgi(app, "/api/requests?red_flags=bad", cookie=cookie)
            self.assertTrue(status.startswith("400"), body)

            status, _, body = call_wsgi(
                app,
                "/api/admin/gold-set",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={
                    "case_id": 2,
                    "expected_diagnosis": "артериальная гипертензия",
                    "expected_icd10": "I10",
                    "expected_red_flags": "",
                    "expected_missing_data": "Суточный профиль АД",
                    "severity": "high",
                    "expected_abstain": False,
                    "notes": "Базовый эталон",
                },
            )
            self.assertTrue(status.startswith("201"), body)

            status, _, body = call_wsgi(app, "/api/admin/gold-set", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            gold_set = json.loads(body.decode("utf-8"))
            self.assertEqual(gold_set["summary"]["gold_cases"], 1)
            self.assertEqual(gold_set["summary"]["evaluated"], 1)
            self.assertEqual(gold_set["summary"]["min_score_percent"], 80)
            self.assertTrue(gold_set["summary"]["release_gate_ok"])
            self.assertEqual(gold_set["gold_cases"][0]["evaluation"]["icd10_match"], True)
            self.assertEqual(gold_set["gold_cases"][0]["evaluation"]["missing_data_match"], True)
            self.assertEqual(gold_set["gold_cases"][0]["evaluation"]["abstain_match"], True)
            self.assertEqual(gold_set["gold_cases"][0]["severity"], "high")

            status, _, body = call_wsgi(app, "/api/admin/gold-runs", method="POST", cookie=cookie, csrf=csrf, body={})
            self.assertTrue(status.startswith("201"), body)
            gold_run = json.loads(body.decode("utf-8"))
            self.assertEqual(gold_run["summary"]["total_items"], 1)
            self.assertEqual(gold_run["summary"]["evaluated_items"], 1)
            self.assertTrue(gold_run["summary"]["release_gate_ok"])

            status, csv_headers, csv_body = call_wsgi(app, "/api/admin/gold-set/export.csv", cookie=cookie)
            self.assertTrue(status.startswith("200"), csv_body)
            self.assertEqual(csv_headers["Content-Type"], "text/csv; charset=utf-8")
            self.assertIn("gold_id,case_id,title", csv_body.decode("utf-8"))

            status, html_headers, html_body = call_wsgi(app, "/api/admin/gold-set/report.html", cookie=cookie)
            self.assertTrue(status.startswith("200"), html_body)
            self.assertEqual(html_headers["Content-Type"], "text/html; charset=utf-8")
            self.assertIn("Gate: PASS", html_body.decode("utf-8"))

            status, _, body = call_wsgi(app, "/api/admin/gold-runs", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            gold_runs = json.loads(body.decode("utf-8"))["runs"]
            self.assertEqual(gold_runs[0]["id"], gold_run["run_id"])
            self.assertEqual(gold_runs[0]["items"][0]["model_request_id"], request_id)
            self.assertEqual(gold_runs[0]["items"][0]["evaluation"]["icd10_match"], True)

            alt_output = {
                "CDS_OUTPUT": {
                    "summary": "Данных недостаточно, требуется очная оценка.",
                    "possible_diagnoses": [],
                    "red_flags": ["нестабильность"],
                    "missing_data": [],
                    "recommended_next_data": [],
                    "limitations": [],
                    "model_should_abstain": True,
                },
                "MODEL_OUTPUT": {"Final_model_diagnosis": "Неясно", "Model_ICD10_codes": []},
            }
            with connect(app.config.db_path) as conn:
                alt_cur = conn.execute(
                    """
                    INSERT INTO model_requests
                      (user_id, case_id, status, api_url, model, request_json, response_json,
                       parsed_output_json, prompt_version, schema_version, output_schema_version,
                       settings_snapshot_json, deidentified_input_json, phi_signals_json,
                       error, duration_ms, tokens_per_second, total_tokens, created_at)
                    VALUES (?, ?, 'success', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
                    """,
                    (
                        1,
                        2,
                        "http://127.0.0.1:1234/v1/chat/completions",
                        "alt-cvd-model",
                        json.dumps({"messages": []}, ensure_ascii=False),
                        json.dumps({"choices": []}, ensure_ascii=False),
                        json.dumps(alt_output, ensure_ascii=False),
                        "test-prompt-v2",
                        "patient-schema-test",
                        "output-schema-test",
                        json.dumps({"active_prompt_version": "test-prompt-v2"}, ensure_ascii=False),
                        json.dumps(patient_data, ensure_ascii=False),
                        json.dumps([], ensure_ascii=False),
                        84,
                        12.5,
                        100,
                        utc_now(),
                    ),
                )
                alt_request_id = alt_cur.lastrowid

            status, _, body = call_wsgi(
                app,
                f"/api/requests/{alt_request_id}/review",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={
                    "rating": "unsafe",
                    "issue_types": ["unsafe_reasoning"],
                    "corrected_diagnosis": "АГ",
                    "corrected_icd10": ["I10"],
                    "comment": "Модель необоснованно отказалась.",
                },
            )
            self.assertTrue(status.startswith("200"), body)

            status, _, body = call_wsgi(app, "/api/admin/model-quality", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            model_quality = json.loads(body.decode("utf-8"))
            self.assertEqual(model_quality["summary"]["models"], 2)
            self.assertEqual(model_quality["summary"]["gold_comparisons"], 1)
            self.assertEqual(model_quality["summary"]["unsafe_reviews"], 1)
            comparison = model_quality["comparisons"][0]
            self.assertEqual(comparison["case_id"], 2)
            self.assertEqual({item["model"] for item in comparison["models"]}, {"healtheart-cvd-engine", "alt-cvd-model"})
            self.assertEqual(comparison["best_model"], "healtheart-cvd-engine")
            review_dashboard = model_quality["reviews"]
            self.assertEqual(review_dashboard["issue_counts"][0]["issue"], "missing_data")

            status, _, body = call_wsgi(app, "/api/admin/gold-set", method="POST", cookie=cookie, csrf=csrf, body={"case_id": 999})
            self.assertTrue(status.startswith("404"), body)

            status, _, body = call_wsgi(app, "/api/admin/reviews", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            reviews = json.loads(body.decode("utf-8"))["reviews"]
            request_review = next(item for item in reviews if item["model_request_id"] == request_id)
            self.assertEqual(request_review["issue_types"], ["missing_data"])

            status, _, body = call_wsgi(app, "/api/admin/audit?limit=abc", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            audit_items = json.loads(body.decode("utf-8"))["audit"]
            self.assertGreaterEqual(len(audit_items), 1)

            status, _, body = call_wsgi(
                app,
                "/api/me/password",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={"current_password": "Test-admin-strong-password-2026", "new_password": "too-short"},
            )
            self.assertTrue(status.startswith("400"), body)

            status, _, body = call_wsgi(
                app,
                "/api/me/password",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={"current_password": "Test-admin-strong-password-2026", "new_password": "Long-enough-password-2026"},
            )
            self.assertTrue(status.startswith("200"), body)

    def test_prompt_template_migration_updates_stale_default_but_keeps_custom(self):
        from cvd_web.lmstudio import USER_PROMPT_TEMPLATE

        legacy_template = (
            "You are a clinical decision support component working only with synthetic or de-identified"
            " cardiovascular data.\nPATIENT_JSON:\n{{PATIENT_JSON}}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cvd.sqlite3"
            CVDApplication(make_test_config(db_path), start_batch_worker=False)
            with connect(db_path) as conn:
                conn.execute("DELETE FROM schema_migrations WHERE id = '0014_prompt_v5_treatment_recommendations'")
                conn.execute(
                    "UPDATE app_settings SET value = ? WHERE key = 'active_prompt_template'",
                    (legacy_template,),
                )
            CVDApplication(make_test_config(db_path), start_batch_worker=False)
            with connect(db_path) as conn:
                value = conn.execute(
                    "SELECT value FROM app_settings WHERE key = 'active_prompt_template'"
                ).fetchone()["value"]
            self.assertEqual(value, USER_PROMPT_TEMPLATE)

        custom_template = "Мой собственный шаблон.\n{{PATIENT_JSON}}\n"
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "custom.sqlite3"
            CVDApplication(make_test_config(db_path), start_batch_worker=False)
            with connect(db_path) as conn:
                conn.execute("DELETE FROM schema_migrations WHERE id = '0014_prompt_v5_treatment_recommendations'")
                conn.execute(
                    "UPDATE app_settings SET value = ? WHERE key = 'active_prompt_template'",
                    (custom_template,),
                )
            CVDApplication(make_test_config(db_path), start_batch_worker=False)
            with connect(db_path) as conn:
                value = conn.execute(
                    "SELECT value FROM app_settings WHERE key = 'active_prompt_template'"
                ).fetchone()["value"]
            self.assertEqual(value, custom_template)

    def test_prompt_version_follows_the_migrated_template(self):
        # Миграция 0014 обновляла шаблон, но не версию: реальные анализы на промпте v5
        # сохранялись с меткой v4, и дашборд качества сравнивал версии по ложной метке.
        from cvd_web.lmstudio import USER_PROMPT_TEMPLATE
        from cvd_web.versions import MODEL_PROMPT_VERSION

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cvd.sqlite3"
            CVDApplication(make_test_config(db_path), start_batch_worker=False)
            with connect(db_path) as conn:
                conn.execute("DELETE FROM schema_migrations WHERE id = '0015_active_prompt_version_follows_template'")
                conn.execute("UPDATE app_settings SET value = 'cvd-cds-prompt-v4' WHERE key = 'active_prompt_version'")
                conn.execute(
                    "UPDATE app_settings SET value = ? WHERE key = 'active_prompt_template'",
                    (USER_PROMPT_TEMPLATE,),
                )
            CVDApplication(make_test_config(db_path), start_batch_worker=False)
            with connect(db_path) as conn:
                version = conn.execute(
                    "SELECT value FROM app_settings WHERE key = 'active_prompt_version'"
                ).fetchone()["value"]
            self.assertEqual(version, MODEL_PROMPT_VERSION)

        # Кастомную версию администратора не трогаем.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "custom.sqlite3"
            CVDApplication(make_test_config(db_path), start_batch_worker=False)
            with connect(db_path) as conn:
                conn.execute("DELETE FROM schema_migrations WHERE id = '0015_active_prompt_version_follows_template'")
                conn.execute("UPDATE app_settings SET value = 'clinic-prompt-2026' WHERE key = 'active_prompt_version'")
            CVDApplication(make_test_config(db_path), start_batch_worker=False)
            with connect(db_path) as conn:
                version = conn.execute(
                    "SELECT value FROM app_settings WHERE key = 'active_prompt_version'"
                ).fetchone()["value"]
            self.assertEqual(version, "clinic-prompt-2026")

    def test_default_admin_password_forces_change_before_other_apis(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_test_config(Path(tmp) / "cvd.sqlite3")
            config = Config(**{**config.__dict__, "admin_password": "admin12345"})
            app = CVDApplication(config, start_batch_worker=False)

            status, headers, body = call_wsgi(
                app,
                "/api/login",
                method="POST",
                body={"email": "admin@test.local", "password": "admin12345"},
            )
            self.assertTrue(status.startswith("200"), body)
            cookie = headers["Set-Cookie"].split(";", 1)[0]

            status, _, body = call_wsgi(app, "/api/me", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            me = json.loads(body.decode("utf-8"))
            self.assertTrue(me["user"]["must_change_password"])
            csrf = me["csrfToken"]

            status, _, body = call_wsgi(app, "/api/cases", cookie=cookie)
            self.assertTrue(status.startswith("403"), body)

            status, headers, _ = call_wsgi(app, "/cases", cookie=cookie)
            self.assertTrue(status.startswith("302"), status)
            self.assertEqual(dict(headers).get("Location"), "/app")

            status, _, body = call_wsgi(app, "/api/admin/security-audit", cookie=cookie)
            self.assertTrue(status.startswith("403"), body)

            status, _, body = call_wsgi(
                app,
                "/api/me/password",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={"current_password": "admin12345", "new_password": "Fresh-strong-password-2026"},
            )
            self.assertTrue(status.startswith("200"), body)

            status, _, body = call_wsgi(app, "/api/cases", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)

    def test_login_rate_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = CVDApplication(make_test_config(Path(tmp) / "cvd.sqlite3"), start_batch_worker=False)

            for _ in range(10):
                status, _, body = call_wsgi(
                    app,
                    "/api/login",
                    method="POST",
                    body={"email": "admin@test.local", "password": "wrong-password"},
                )
                self.assertTrue(status.startswith("401"), body)

            status, headers, body = call_wsgi(
                app,
                "/api/login",
                method="POST",
                body={"email": "admin@test.local", "password": "wrong-password"},
            )
            self.assertTrue(status.startswith("429"), body)
            self.assertIn("Retry-After", headers)

    def test_production_rejects_default_admin_password_and_requires_secure_cookie_for_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            insecure_config = make_test_config(Path(tmp) / "insecure.sqlite3")
            insecure_config = Config(
                **{
                    **insecure_config.__dict__,
                    "app_env": "production",
                    "admin_email": "admin@example.local",
                    "admin_password": "admin12345",
                }
            )
            with self.assertRaisesRegex(RuntimeError, "default administrator password"):
                CVDApplication(insecure_config, start_batch_worker=False)

            ready_config = make_test_config(Path(tmp) / "ready.sqlite3")
            ready_config = Config(
                **{
                    **ready_config.__dict__,
                    "app_env": "production",
                    "admin_password": "Strong-production-password-2026!",
                    "cookie_secure": False,
                }
            )
            app = CVDApplication(ready_config, start_batch_worker=False)
            status, _, body = call_wsgi(app, "/readyz")
            self.assertTrue(status.startswith("503"), body)
            readiness = json.loads(body.decode("utf-8"))
            self.assertFalse(readiness["ok"])
            self.assertFalse(readiness["checks"]["security"]["ok"])
            self.assertFalse(readiness["checks"]["runtime"]["ok"])
            self.assertIn("queue-backend-memory", readiness["checks"]["runtime"]["blockers"])
            self.assertIn("rate-limit-memory", readiness["checks"]["runtime"]["blockers"])
            self.assertIn("worker-in-process", readiness["checks"]["runtime"]["blockers"])

    def test_migration_workflow_creates_backup_before_pending_migrations(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "migrations.sqlite3"
            config = make_test_config(db_path)
            CVDApplication(config, start_batch_worker=False)
            with connect(db_path) as conn:
                conn.execute("DELETE FROM schema_migrations WHERE id = ?", ("0010_gold_release_gate",))

            status = migration_status(db_path)
            self.assertIn("0010_gold_release_gate", status["pending"])
            backup_dir = Path(tmp) / "migration-backups"
            result = run_migrations(config, backup=True, backup_dir=backup_dir)
            self.assertTrue(result["ok"], result)
            self.assertFalse(result["after"]["pending"], result)
            self.assertTrue(result["backup_path"].endswith(".sqlite3"), result)
            self.assertTrue(Path(result["backup_path"]).is_file())

    def test_q8_default_migration_updates_legacy_max_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "q8-default.sqlite3"
            config = make_test_config(db_path)
            CVDApplication(config, start_batch_worker=False)
            with connect(db_path) as conn:
                conn.execute(
                    "UPDATE app_settings SET value = '1536' WHERE key = 'lm_studio_max_tokens'"
                )
                conn.execute(
                    "DELETE FROM schema_migrations WHERE id = ?",
                    ("0012_q8_streaming_defaults",),
                )

            status = migration_status(db_path)
            self.assertIn("0012_q8_streaming_defaults", status["pending"])
            CVDApplication(config, start_batch_worker=False)

            with connect(db_path) as conn:
                value = conn.execute(
                    "SELECT value FROM app_settings WHERE key = 'lm_studio_max_tokens'"
                ).fetchone()[0]
            self.assertEqual(value, "4096")
            self.assertFalse(migration_status(db_path)["pending"])

    def test_memory_rate_limiter_window(self):
        now = [100.0]
        limiter = MemoryRateLimiter(clock=lambda: now[0])

        self.assertEqual(limiter.allow("key", limit=2, window_seconds=10), (True, 0))
        self.assertEqual(limiter.allow("key", limit=2, window_seconds=10), (True, 0))
        allowed, retry_after = limiter.allow("key", limit=2, window_seconds=10)
        self.assertFalse(allowed)
        self.assertGreaterEqual(retry_after, 1)

        now[0] = 111.0
        self.assertEqual(limiter.allow("key", limit=2, window_seconds=10), (True, 0))


if __name__ == "__main__":
    unittest.main()
