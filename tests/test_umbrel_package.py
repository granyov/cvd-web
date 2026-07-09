from __future__ import annotations

import re
import unittest
from pathlib import Path

from cvd_web.versions import APP_VERSION


ROOT = Path(__file__).resolve().parent.parent
APP_ID = "granyov-cvd-web"


class UmbrelPackageTests(unittest.TestCase):
    def test_umbrel_package_matches_application_version(self):
        version = APP_VERSION.removeprefix("v")
        store = (ROOT / "umbrel-app-store.yml").read_text(encoding="utf-8")
        manifest = (ROOT / APP_ID / "umbrel-app.yml").read_text(encoding="utf-8")
        compose = (ROOT / APP_ID / "docker-compose.yml").read_text(encoding="utf-8")
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        data_dir = ROOT / APP_ID / "data"

        self.assertIn('id: "granyov"', store)
        self.assertRegex(manifest, rf"(?m)^id:\s+{APP_ID}$")
        self.assertRegex(manifest, rf'(?m)^version:\s+"{re.escape(version)}"$')
        self.assertIn('defaultUsername: "admin@umbrel.local"', manifest)
        self.assertIn('defaultPassword: "UmbrelCVD2026Pass!"', manifest)

        self.assertIn("APP_HOST: granyov-cvd-web_server_1", compose)
        self.assertIn("APP_PORT: 8080", compose)
        self.assertIn(f"image: ghcr.io/granyov/cvd-web:{APP_VERSION}", compose)
        self.assertIn("${APP_DATA_DIR}/data:/app/data", compose)
        self.assertIn("CVD_DB_PATH: /app/data/cvd.sqlite3", compose)
        self.assertIn("host.docker.internal:host-gateway", compose)

        self.assertIn("CVD_HOST=0.0.0.0", dockerfile)
        self.assertIn("EXPOSE 8080", dockerfile)
        self.assertIn("/healthz", dockerfile)
        self.assertTrue(data_dir.is_dir())


if __name__ == "__main__":
    unittest.main()
