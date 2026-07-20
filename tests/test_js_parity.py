"""Python дублирует справочники из фронтенда - тесты следят, чтобы копии совпадали.

Форма ввода подсвечивает отклонения по static/js/clinical-quality.js, а печатный
отчёт - по cvd_web/reference_ranges.py. Если копии разъедутся, врач увидит на
экране норму, а на распечатке отклонение (или наоборот) по одному и тому же
анализу. То же с подписями полей.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from cvd_web.field_labels import SCHEMA_FIELD_LABELS
from cvd_web.reference_ranges import REFERENCE_RANGES
from cvd_web.reporting import FIELD_LABELS


STATIC = Path(__file__).resolve().parent.parent / "cvd_web" / "static" / "js"


def parse_js_reference_ranges() -> dict[str, dict[str, object]]:
    source = (STATIC / "clinical-quality.js").read_text(encoding="utf-8")
    ranges: dict[str, dict[str, object]] = {}
    pattern = re.compile(r'"([A-Z_]+\.[A-Za-z0-9_]+)":\s*\{([^}]*)\}')
    for path, body in pattern.findall(source):
        entry: dict[str, object] = {}
        for key, value in re.findall(r'(min|max):\s*(-?[\d.]+)', body):
            entry[key] = float(value)
        text = re.search(r'text:\s*"([^"]*)"', body)
        if text:
            entry["text"] = text.group(1)
        ranges[path] = entry
    return ranges


def parse_js_field_labels() -> dict[str, str]:
    source = (STATIC / "schema.js").read_text(encoding="utf-8")
    return dict(re.findall(r'\{\s*key:\s*"([^"]+)",\s*label:\s*"([^"]+)"', source))


class JavaScriptParityTests(unittest.TestCase):
    def test_reference_ranges_match_javascript(self):
        js_ranges = parse_js_reference_ranges()
        self.assertTrue(js_ranges, "не удалось разобрать clinical-quality.js")
        self.assertEqual(set(REFERENCE_RANGES), set(js_ranges))
        for path, js_entry in js_ranges.items():
            py_entry = REFERENCE_RANGES[path]
            self.assertEqual(py_entry.get("min"), js_entry.get("min"), path)
            self.assertEqual(py_entry.get("max"), js_entry.get("max"), path)
            self.assertEqual(py_entry.get("text"), js_entry.get("text"), path)

    def test_field_labels_match_javascript(self):
        js_labels = parse_js_field_labels()
        self.assertTrue(js_labels, "не удалось разобрать schema.js")
        self.assertEqual(SCHEMA_FIELD_LABELS, js_labels)

    def test_print_labels_cover_only_real_fields(self):
        js_labels = parse_js_field_labels()
        unknown = sorted(set(FIELD_LABELS) - set(js_labels))
        self.assertEqual(unknown, [], f"подписи для несуществующих полей: {unknown}")


if __name__ == "__main__":
    unittest.main()
