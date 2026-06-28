from __future__ import annotations

import copy
import re
from typing import Any


EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?\d[\s().-]*){10,16}(?!\d)")
DATE_PATTERN = re.compile(r"\b(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}[./-]\d{1,2}[./-]\d{1,2})\b")
PASSPORT_PATTERN = re.compile(r"\b\d{4}\s?\d{6}\b")
SNILS_PATTERN = re.compile(r"\b\d{3}[- ]?\d{3}[- ]?\d{3}[- ]?\d{2}\b")


PATTERN_RULES = (
    ("email", EMAIL_PATTERN, "[EMAIL]"),
    ("phone", PHONE_PATTERN, "[PHONE]"),
    ("date", DATE_PATTERN, "[DATE]"),
    ("passport", PASSPORT_PATTERN, "[ID_DOCUMENT]"),
    ("snils", SNILS_PATTERN, "[SNILS]"),
)


def detect_phi_signals(value: Any) -> list[dict[str, str]]:
    signals: list[dict[str, str]] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                walk(item, f"{path}.{key}" if path else str(key))
            return
        if isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]")
            return
        if not isinstance(node, str):
            return
        for kind, pattern, _replacement in PATTERN_RULES:
            if pattern.search(node):
                signals.append({"kind": kind, "path": path})

    walk(value, "")
    return signals


def deidentify_patient_data(patient_data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    output = copy.deepcopy(patient_data)
    signals = detect_phi_signals(output)

    general = output.get("GENERAL_INFO")
    if isinstance(general, dict):
        direct_identifiers = (
            ("Patient_ID", "patient_id", "[CASE_ID]"),
            ("Full_name", "patient_name", "[PATIENT_NAME]"),
        )
        for field, kind, replacement in direct_identifiers:
            if not general.get(field):
                continue
            path = f"GENERAL_INFO.{field}"
            if not any(signal["path"] == path and signal["kind"] == kind for signal in signals):
                signals.append({"kind": kind, "path": path})
            general[field] = replacement

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {key: walk(value) for key, value in node.items()}
        if isinstance(node, list):
            return [walk(value) for value in node]
        if not isinstance(node, str):
            return node
        cleaned = node
        for _kind, pattern, replacement in PATTERN_RULES:
            cleaned = pattern.sub(replacement, cleaned)
        return cleaned

    return walk(output), signals
