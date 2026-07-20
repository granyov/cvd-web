"""Референсные интервалы взрослых для подсказок и печатных отчётов.

Значения ориентировочные: они не заменяют локальные лабораторные референсы и
клиническую оценку. Тот же набор продублирован в static/js/clinical-quality.js
для подсказок при вводе; тест test_reference_ranges_match_javascript следит,
чтобы копии не разъезжались.
"""
from __future__ import annotations

from typing import Any


REFERENCE_RANGES: dict[str, dict[str, Any]] = {
    "GENERAL_INFO.BMI": {"min": 18.5, "max": 24.9, "text": "18.5–24.9 кг/м²"},
    "PHYSICAL_EXAM.Blood_pressure_right_systolic_mmHg": {"min": 90, "max": 139, "text": "90–139 мм рт. ст."},
    "PHYSICAL_EXAM.Blood_pressure_right_diastolic_mmHg": {"min": 60, "max": 89, "text": "60–89 мм рт. ст."},
    "PHYSICAL_EXAM.Blood_pressure_left_systolic_mmHg": {"min": 90, "max": 139, "text": "90–139 мм рт. ст."},
    "PHYSICAL_EXAM.Blood_pressure_left_diastolic_mmHg": {"min": 60, "max": 89, "text": "60–89 мм рт. ст."},
    "PHYSICAL_EXAM.Heart_rate_bpm": {"min": 60, "max": 100, "text": "60–100 уд/мин"},
    "PHYSICAL_EXAM.Resp_rate": {"min": 12, "max": 20, "text": "12–20 в мин"},
    "PHYSICAL_EXAM.SpO2_room_air_percent": {"min": 94, "text": "≥ 94 %"},
    "LABS_CBC.Hb_g_L": {"min": 120, "max": 160, "text": "120–160 г/л"},
    "LABS_CBC.WBC_10e9_L": {"min": 4, "max": 9, "text": "4–9 ×10⁹/л"},
    "LABS_CBC.PLT_10e9_L": {"min": 150, "max": 400, "text": "150–400 ×10⁹/л"},
    "LABS_BIOCHEM.Creatinine_umol_L": {"min": 60, "max": 110, "text": "60–110 мкмоль/л"},
    "LABS_BIOCHEM.eGFR_ml_min_1_73m2": {"min": 60, "text": "≥ 60 мл/мин/1.73 м²"},
    "LABS_BIOCHEM.ALT_U_L": {"max": 40, "text": "≤ 40 Ед/л"},
    "LABS_BIOCHEM.AST_U_L": {"max": 40, "text": "≤ 40 Ед/л"},
    "LABS_BIOCHEM.Na_mmol_L": {"min": 135, "max": 145, "text": "135–145 ммоль/л"},
    "LABS_BIOCHEM.K_mmol_L": {"min": 3.5, "max": 5.1, "text": "3.5–5.1 ммоль/л"},
    "LABS_BIOCHEM.Mg_mmol_L": {"min": 0.7, "max": 1.05, "text": "0.7–1.05 ммоль/л"},
    "LABS_BIOCHEM.Glucose_fasting_mmol_L": {"min": 3.9, "max": 5.6, "text": "3.9–5.6 ммоль/л"},
    "LABS_BIOCHEM.HbA1c_percent": {"max": 6.0, "text": "≤ 6.0 %"},
    "LABS_LIPIDS.Total_cholesterol_mmol_L": {"max": 5.0, "text": "≤ 5.0 ммоль/л"},
    "LABS_LIPIDS.LDL_mmol_L": {"max": 3.0, "text": "≤ 3.0 ммоль/л"},
    "LABS_LIPIDS.HDL_mmol_L": {"min": 1.0, "text": "≥ 1.0 ммоль/л"},
    "LABS_LIPIDS.Triglycerides_mmol_L": {"max": 1.7, "text": "≤ 1.7 ммоль/л"},
    "LABS_CARDIAC_MARKERS.Troponin_ng_L": {"max": 14, "text": "≤ 14 нг/л"},
    "LABS_CARDIAC_MARKERS.NT_proBNP_pg_ml": {"max": 125, "text": "≤ 125 пг/мл"},
    "LABS_COAGULATION.INR": {"min": 0.8, "max": 1.2, "text": "0.8–1.2 (без антикоагулянтов)"},
    "LABS_COAGULATION.APTT_sec": {"min": 25, "max": 35, "text": "25–35 с"},
    "ECHOCARDIOGRAPHY.LVEF_percent": {"min": 50, "text": "≥ 50 %"},
    "ECHOCARDIOGRAPHY.PASP_mmHg": {"max": 35, "text": "≤ 35 мм рт. ст."},
}


def reference_status(path: str, value: Any) -> dict[str, Any] | None:
    """Положение значения относительно референса: below / above / ok."""
    reference = REFERENCE_RANGES.get(path)
    if reference is None:
        return None
    try:
        numeric = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if reference.get("min") is not None and numeric < reference["min"]:
        state = "below"
    elif reference.get("max") is not None and numeric > reference["max"]:
        state = "above"
    else:
        state = "ok"
    return {"state": state, "text": reference["text"], "abnormal": state != "ok"}
