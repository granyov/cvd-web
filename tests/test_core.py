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
    LMStudioError,
    build_chat_request,
    call_lm_studio,
    extract_json_from_text,
    lm_studio_http_error_message,
    normalize_model_output,
)
from cvd_web.lmstudio_models import activate_lm_model, list_lm_models
from cvd_web.privacy import deidentify_patient_data
from cvd_web.rate_limit import MemoryRateLimiter
from cvd_web.reporting import build_html_report


def test_config(db_path: Path) -> Config:
    return Config(
        project_root=PROJECT_ROOT,
        db_path=db_path,
        host="127.0.0.1",
        port=0,
        cookie_secure=False,
        session_days=7,
        admin_email="admin@test.local",
        admin_password="admin12345",
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
                }
            },
            {"request_id": 7, "model": "medgemma-4b-it"},
        )
        self.assertIn("onclick=\"window.print()\"", report)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", report)
        self.assertNotIn("<script>alert(1)</script>", report)
        self.assertIn("Результат &lt;опасный&gt;", report)

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
        with patch("cvd_web.lmstudio_models._request_json", return_value=initial):
            catalog = list_lm_models("http://127.0.0.1:1234/v1/chat/completions")
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
        response_schema = request["response_format"]["json_schema"]["schema"]
        self.assertEqual(response_schema["required"], ["CDS_OUTPUT"])
        self.assertEqual(
            response_schema["properties"]["CDS_OUTPUT"]["properties"]["possible_diagnoses"]["maxItems"],
            3,
        )
        self.assertNotIn("MODEL_OUTPUT", response_schema["properties"])
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
                "Model_treatment_recommendations": "",
                "Model_rehabilitation_recommendations": "",
            },
        })
        self.assertEqual(normalized["CDS_OUTPUT"]["possible_diagnoses"][0]["icd10_codes"], ["I10"])
        self.assertEqual(normalized["CDS_OUTPUT"]["possible_diagnoses"][0]["confidence"], "medium")
        self.assertEqual(normalized["MODEL_OUTPUT"]["Model_ICD10_codes"], ["I10"])

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
            app = CVDApplication(test_config(Path(tmp) / "cvd.sqlite3"), start_batch_worker=False)

            status, _, body = call_wsgi(app, "/healthz")
            self.assertTrue(status.startswith("200"), body)
            self.assertEqual(json.loads(body.decode("utf-8"))["ok"], True)
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
                body={"email": "admin@test.local", "password": "admin12345"},
            )
            self.assertTrue(status.startswith("200"), body)
            cookie = headers["Set-Cookie"].split(";", 1)[0]

            status, _, body = call_wsgi(app, "/api/me", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            csrf = json.loads(body.decode("utf-8"))["csrfToken"]

            status, _, body = call_wsgi(app, "/app", cookie=cookie)
            app_html = body.decode("utf-8")
            self.assertTrue(status.startswith("200"), body)
            self.assertNotIn("lm_studio_api_url", app_html)
            self.assertNotIn("127.0.0.1:1234", app_html)
            self.assertNotIn("LM Studio", app_html)
            self.assertNotIn("MedGemma", app_html)

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
            self.assertIn("lm_studio_temperature", settings)
            self.assertIn("lm_studio_structured_output", settings)
            self.assertEqual(settings["lm_studio_max_concurrent"], "1")
            self.assertEqual(settings["lm_studio_queue_limit"], "64")
            self.assertEqual(settings["lm_studio_per_user_limit"], "2")
            self.assertIn("text_structuring_model", settings)
            self.assertIn("deidentify_before_model", settings)
            self.assertIn("active_prompt_version", settings)
            self.assertIn("active_prompt_template", settings)
            self.assertIn("{{PATIENT_JSON}}", settings["active_prompt_template"])

            updated_settings = dict(settings)
            updated_settings["active_prompt_version"] = "test-prompt-v2"
            updated_settings["active_prompt_template"] = "Clinical prompt\n{{PATIENT_JSON}}"
            status, _, body = call_wsgi(
                app,
                "/api/admin/settings",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={"settings": updated_settings},
            )
            self.assertTrue(status.startswith("200"), body)

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
            self.assertIn("prompt_version", columns)
            self.assertIn("settings_snapshot_json", columns)
            self.assertIn("completion_tokens", columns)
            self.assertIn("tokens_per_second", columns)
            self.assertIn("finish_reason", columns)
            self.assertIn("queue_wait_ms", columns)

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
            self.assertIn("Распечатать", body.decode("utf-8"))
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

            status, _, body = call_wsgi(app, "/api/admin/reviews", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            reviews = json.loads(body.decode("utf-8"))["reviews"]
            self.assertEqual(reviews[0]["model_request_id"], request_id)
            self.assertEqual(reviews[0]["issue_types"], ["missing_data"])

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
                body={"current_password": "admin12345", "new_password": "too-short"},
            )
            self.assertTrue(status.startswith("400"), body)

            status, _, body = call_wsgi(
                app,
                "/api/me/password",
                method="POST",
                cookie=cookie,
                csrf=csrf,
                body={"current_password": "admin12345", "new_password": "Long-enough-password-2026"},
            )
            self.assertTrue(status.startswith("200"), body)

    def test_login_rate_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = CVDApplication(test_config(Path(tmp) / "cvd.sqlite3"), start_batch_worker=False)

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
