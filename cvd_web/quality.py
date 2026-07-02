from __future__ import annotations

import hashlib
import json
from typing import Any

from .cvd_schema import CVD_SCHEMA


REQUIRED_DATA_POINTS = (
    ("GENERAL_INFO.Patient_ID", "ID случая"),
    ("GENERAL_INFO.Sex", "Пол"),
    ("GENERAL_INFO.Age", "Возраст"),
    ("COMPLAINTS.Main_complaint", "Основная жалоба"),
    ("PHYSICAL_EXAM.Blood_pressure_right_systolic_mmHg", "Систолическое АД"),
    ("PHYSICAL_EXAM.Heart_rate_bpm", "ЧСС"),
    ("ECG_AND_BP_MONITORING.Resting_ECG_summary", "ЭКГ покоя"),
    ("FINAL_DIAGNOSES.Main_cardiovascular_diagnosis_text", "Рабочий диагноз врача"),
)


def get_value(data: dict[str, Any], path: str) -> Any:
    section, field = path.split(".", 1)
    return data.get(section, {}).get(field)


def is_filled(value: Any) -> bool:
    if isinstance(value, list):
        return len(value) > 0
    return value is not None and str(value).strip() != ""


def has_clinical_input(data: dict[str, Any]) -> bool:
    for section in CVD_SCHEMA:
        if section.key == "MODEL_OUTPUT":
            continue
        section_data = data.get(section.key, {})
        if any(is_filled(section_data.get(field.key)) for field in section.fields):
            return True
    return False


def comparable_clinical_data(data: dict[str, Any]) -> dict[str, Any]:
    comparable = dict(data or {})
    comparable.pop("MODEL_OUTPUT", None)
    return comparable


def patient_data_changes(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[dict[str, Any]]:
    before_data = comparable_clinical_data(before or {})
    after_data = comparable_clinical_data(after or {})
    changes: list[dict[str, Any]] = []
    for section in CVD_SCHEMA:
        if section.key == "MODEL_OUTPUT":
            continue
        before_section = before_data.get(section.key, {}) if isinstance(before_data.get(section.key, {}), dict) else {}
        after_section = after_data.get(section.key, {}) if isinstance(after_data.get(section.key, {}), dict) else {}
        for field in section.fields:
            path = f"{section.key}.{field.key}"
            old = before_section.get(field.key)
            new = after_section.get(field.key)
            if old == new:
                continue
            if is_filled(old) and is_filled(new):
                kind = "changed"
            elif is_filled(new):
                kind = "added"
            else:
                kind = "removed"
            changes.append({"path": path, "label": field.key, "kind": kind, "before": old, "after": new})
    return changes

def numeric_value(data: dict[str, Any], path: str) -> float | None:
    value = get_value(data, path)
    if not is_filled(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def patient_data_hash(data: dict[str, Any]) -> str:
    comparable = comparable_clinical_data(data)
    payload = json.dumps(comparable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def case_quality_summary(data: dict[str, Any]) -> dict[str, Any]:
    total = 0
    filled = 0
    for section in CVD_SCHEMA:
        for field in section.fields:
            total += 1
            if is_filled(data.get(section.key, {}).get(field.key)):
                filled += 1

    missing_required = [
        {"path": path, "label": label}
        for path, label in REQUIRED_DATA_POINTS
        if not is_filled(get_value(data, path))
    ]
    readiness = round(((len(REQUIRED_DATA_POINTS) - len(missing_required)) / len(REQUIRED_DATA_POINTS)) * 100)
    completeness = round((filled / total) * 100) if total else 0
    signals = clinical_signals(data)
    return {
        "completeness_percent": completeness,
        "readiness_percent": readiness,
        "filled_fields": filled,
        "total_fields": total,
        "missing_required": missing_required,
        "signals": signals,
        "critical_signals": sum(1 for signal in signals if signal.get("kind") in {"critical", "error"}),
    }


def clinical_signals(data: dict[str, Any]) -> list[dict[str, str]]:
    signals: list[dict[str, str]] = []
    age = numeric_value(data, "GENERAL_INFO.Age")
    systolic = numeric_value(data, "PHYSICAL_EXAM.Blood_pressure_right_systolic_mmHg")
    diastolic = numeric_value(data, "PHYSICAL_EXAM.Blood_pressure_right_diastolic_mmHg")
    heart_rate = numeric_value(data, "PHYSICAL_EXAM.Heart_rate_bpm")
    spo2 = numeric_value(data, "PHYSICAL_EXAM.SpO2_room_air_percent")
    lvef = numeric_value(data, "ECHOCARDIOGRAPHY.LVEF_percent")
    troponin = numeric_value(data, "LABS_CARDIAC_MARKERS.Troponin_ng_L")
    complaint = str(get_value(data, "COMPLAINTS.Main_complaint") or "").lower()
    dyspnea = any(token in complaint for token in ("одыш", "dysp", "shortness"))
    chest_pain = any(token in complaint for token in ("боль", "груд", "chest", "стенок"))
    ecg = get_value(data, "ECG_AND_BP_MONITORING.Resting_ECG_summary")

    def add(kind: str, title: str, text: str, category: str) -> None:
        signals.append({"kind": kind, "title": title, "text": text, "category": category})

    if age is not None and age >= 75:
        add("warning", "Возраст 75+", "Проверьте гериатрический риск, коморбидность и переносимость терапии.", "Демография")
    if (systolic is not None and systolic >= 180) or (diastolic is not None and diastolic >= 120):
        add("critical", "Очень высокое АД", "АД ≥180/120 требует проверки корректности ввода и клинического контекста.", "Витальные")
    if systolic is not None and systolic < 90:
        add("critical", "Систолическое АД < 90", "Возможна гемодинамическая нестабильность; интерпретируйте AI-вывод особенно осторожно.", "Витальные")
    if heart_rate is not None and (heart_rate < 50 or heart_rate > 120):
        add("warning", "ЧСС вне обычного диапазона", "Важный фактор для интерпретации симптомов, ЭКГ и риска декомпенсации.", "Витальные")
    if spo2 is not None and spo2 < 92:
        add("critical", "SpO2 < 92%", "Проверьте дыхательный статус, условия измерения и необходимость срочной оценки.", "Витальные")
    if lvef is not None and lvef < 40:
        add("warning", "ФВ ЛЖ < 40%", "Маркер структурного поражения и возможной сердечной недостаточности.", "ЭхоКГ")
    if troponin is not None and troponin > 0:
        add("warning", "Тропонин указан", "Сверьте единицы, референсы лаборатории и динамику показателя.", "Лаборатория")
    if chest_pain and not is_filled(ecg):
        add("critical", "Боль в груди без ЭКГ", "Для такого сценария ЭКГ — ключевой контекст перед AI-анализом.", "Диагностика")
    if dyspnea and lvef is not None and lvef < 40:
        add("warning", "Одышка + сниженная ФВ ЛЖ", "Проверьте признаки сердечной недостаточности и текущую терапию.", "Комбинированный")
    if spo2 is not None and spo2 < 92 and heart_rate is not None and heart_rate > 120:
        add("critical", "Низкая SpO2 + тахикардия", "Комбинация может указывать на высокий риск и требует клинической приоритизации.", "Комбинированный")
    return signals
