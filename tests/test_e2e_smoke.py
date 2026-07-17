"""Smoke-сценарии ключевых пользовательских потоков поверх WSGI-приложения.

Каждый тест проходит целый путь пользователя (логин → действия → результат),
чтобы ловить регрессии маршрутизации, шаблонов и API-контрактов без браузера.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cvd_web.app import CVDApplication

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
