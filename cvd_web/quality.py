from __future__ import annotations

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


def numeric_value(data: dict[str, Any], path: str) -> float | None:
    value = get_value(data, path)
    if not is_filled(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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

    if age is not None and age >= 75:
        signals.append({"kind": "warning", "title": "Возраст 75+"})
    if (systolic is not None and systolic >= 180) or (diastolic is not None and diastolic >= 120):
        signals.append({"kind": "error", "title": "Очень высокое АД"})
    if heart_rate is not None and (heart_rate < 50 or heart_rate > 120):
        signals.append({"kind": "warning", "title": "ЧСС вне обычного диапазона"})
    if spo2 is not None and spo2 < 92:
        signals.append({"kind": "error", "title": "SpO2 < 92%"})
    if lvef is not None and lvef < 40:
        signals.append({"kind": "warning", "title": "ФВ ЛЖ < 40%"})
    if troponin is not None and troponin > 0:
        signals.append({"kind": "warning", "title": "Тропонин указан"})
    return signals
