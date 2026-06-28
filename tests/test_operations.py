from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cvd_web.app import CVDApplication
from cvd_web.db import connect
from cvd_web.text_structuring import normalize_structuring_output
from test_core import call_wsgi, test_config


class OperationsTests(unittest.TestCase):
    def login(self, app: CVDApplication) -> tuple[str, str]:
        status, headers, body = call_wsgi(
            app,
            "/api/login",
            method="POST",
            body={"email": "admin@test.local", "password": "admin12345"},
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

    def test_batch_processing_dashboard_and_text_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = CVDApplication(test_config(Path(tmp) / "cvd.sqlite3"), start_batch_worker=False)
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
            with patch("cvd_web.app.call_lm_studio", return_value=({}, model_response, parsed, 1000)):
                self.assertTrue(app.process_next_batch_item())
                self.assertTrue(app.process_next_batch_item())
                self.assertFalse(app.process_next_batch_item())

            status, _, body = call_wsgi(app, f"/api/admin/batch/jobs/{job_id}", cookie=cookie)
            self.assertTrue(status.startswith("200"), body)
            job = json.loads(body.decode("utf-8"))["job"]
            self.assertEqual(job["status"], "completed")
            self.assertEqual(job["success_items"], 2)

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
                "cvd_web.app.call_text_structuring",
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
            self.assertEqual(sources, ["batch", "batch"])
            self.assertEqual(len(preparation["input_sha256"]), 64)
            self.assertNotIn("пациэнт", preparation.keys())


if __name__ == "__main__":
    unittest.main()
