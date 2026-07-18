"""Тесты извлечения текста из PDF и приёма PDF в импорт-flow."""
from __future__ import annotations

import json
import tempfile
import unittest
import zlib
from pathlib import Path

from cvd_web.app import CVDApplication
from cvd_web.pdf_text import PDFTextError, extract_pdf_text

from test_core import make_test_config
from test_e2e_smoke import login


def build_pdf(objects: list[bytes]) -> bytes:
    body = b"%PDF-1.4\n" + b"\n".join(objects) + b"\ntrailer\n<< /Root 1 0 R >>\n%%EOF"
    return body


def simple_latin_pdf() -> bytes:
    content = b"BT /F1 12 Tf 50 700 Td (Patient visit summary: cardiology consultation) Tj T* (BP 148/92 HR 78 SpO2 97) Tj ET"
    return build_pdf([
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj",
        b"4 0 obj\n<< /Length %d >>\nstream\n%s\nendstream\nendobj" % (len(content), content),
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj",
    ])


def cyrillic_type0_pdf() -> bytes:
    """Type0-шрифт с Identity-H и ToUnicode CMap — как в PDF из печати браузера."""
    text = "Жалобы: одышка"
    codes = b"".join((0x100 + index).to_bytes(2, "big") for index in range(len(text)))
    bfchar = "\n".join(
        f"<{0x100 + index:04x}> <{ord(char):04x}>" for index, char in enumerate(text)
    ).encode("ascii")
    cmap_stream = (
        b"/CIDInit /ProcSet findresource begin\nbegincmap\n"
        b"1 beginbfchar\n" + bfchar + b"\nendbfchar\nendcmap\nend"
    )
    compressed_cmap = zlib.compress(cmap_stream)
    hex_codes = codes.hex().encode("ascii")
    content = b"BT /F1 11 Tf 40 700 Td <" + hex_codes + b"> Tj ET"
    compressed_content = zlib.compress(content)
    return build_pdf([
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj",
        b"4 0 obj\n<< /Filter /FlateDecode /Length %d >>\nstream\n%s\nendstream\nendobj"
        % (len(compressed_content), compressed_content),
        b"5 0 obj\n<< /Type /Font /Subtype /Type0 /Encoding /Identity-H /ToUnicode 6 0 R >>\nendobj",
        b"6 0 obj\n<< /Filter /FlateDecode /Length %d >>\nstream\n%s\nendstream\nendobj"
        % (len(compressed_cmap), compressed_cmap),
    ])


def scanned_pdf() -> bytes:
    """PDF без текстового слоя: страница с одной JPEG-картинкой."""
    content = b"q 612 0 0 792 0 0 cm /Im1 Do Q"
    return build_pdf([
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>\nendobj",
        b"4 0 obj\n<< /Length %d >>\nstream\n%s\nendstream\nendobj" % (len(content), content),
        b"5 0 obj\n<< /Subtype /Image /Filter /DCTDecode /Length 3 >>\nstream\n\xff\xd8\xff\nendstream\nendobj",
    ])


class PdfTextTests(unittest.TestCase):

    def test_simple_latin_pdf(self):
        result = extract_pdf_text(simple_latin_pdf())
        self.assertIn("Patient visit summary", result["text"])
        self.assertIn("BP 148/92 HR 78", result["text"])
        self.assertEqual(result["pages"], 1)

    def test_cyrillic_type0_tounicode(self):
        result = extract_pdf_text(cyrillic_type0_pdf())
        self.assertIn("Жалобы: одышка", result["text"])

    def test_scanned_pdf_has_no_text_layer(self):
        result = extract_pdf_text(scanned_pdf())
        self.assertFalse(result["has_text_layer"])

    def test_not_a_pdf_raises(self):
        with self.assertRaises(PDFTextError):
            extract_pdf_text(b"hello world")


class PdfImportFlowTests(unittest.TestCase):

    def call_pdf_endpoint(self, app: CVDApplication, cookie: str, csrf: str, payload: bytes):
        from io import BytesIO

        environ = {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": "/api/import/pdf-text",
            "QUERY_STRING": "",
            "CONTENT_LENGTH": str(len(payload)),
            "CONTENT_TYPE": "application/pdf",
            "wsgi.input": BytesIO(payload),
            "HTTP_COOKIE": cookie,
            "HTTP_X_CSRF_TOKEN": csrf,
            "HTTP_HOST": "127.0.0.1",
            "REMOTE_ADDR": "127.0.0.1",
            "wsgi.url_scheme": "http",
        }
        captured = {}

        def start_response(status, headers):
            captured["status"] = status

        body = b"".join(app(environ, start_response))
        return captured["status"], body

    def test_pdf_import_returns_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = CVDApplication(make_test_config(Path(tmp) / "cvd.sqlite3"), start_batch_worker=False)
            cookie, csrf = login(app)
            status, body = self.call_pdf_endpoint(app, cookie, csrf, simple_latin_pdf())
            self.assertTrue(status.startswith("200"), body)
            data = json.loads(body.decode("utf-8"))
            self.assertIn("Patient visit summary", data["text"])

    def test_scanned_pdf_returns_helpful_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = CVDApplication(make_test_config(Path(tmp) / "cvd.sqlite3"), start_batch_worker=False)
            cookie, csrf = login(app)
            status, body = self.call_pdf_endpoint(app, cookie, csrf, scanned_pdf())
            self.assertTrue(status.startswith("422"), body)
            self.assertIn("скан", json.loads(body.decode("utf-8"))["error"])

    def test_non_pdf_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = CVDApplication(make_test_config(Path(tmp) / "cvd.sqlite3"), start_batch_worker=False)
            cookie, csrf = login(app)
            status, body = self.call_pdf_endpoint(app, cookie, csrf, b"not a pdf at all")
            self.assertTrue(status.startswith("400"), body)


if __name__ == "__main__":
    unittest.main()
