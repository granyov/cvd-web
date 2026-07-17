"""Синтетический демонстрационный CVD-кейс.

Данные полностью вымышлены и предназначены для знакомства с продуктом,
скриншотов и тестов. Не основаны на реальном пациенте.
"""
from __future__ import annotations

from typing import Any


DEMO_CASE_TITLE = "Демо: ИБС, стабильная стенокардия"

DEMO_PATIENT_DATA: dict[str, dict[str, Any]] = {
    "GENERAL_INFO": {
        "Patient_ID": "DEMO_CVD_001",
        "Full_name": "Демо Пациент (синтетический)",
        "Sex": "male",
        "Age": 62,
        "Height_cm": 176,
        "Weight_kg": 92,
        "BMI": 29.7,
    },
    "COMPLAINTS": {
        "Main_complaint": "Давящая боль за грудиной при быстрой ходьбе и подъёме на 2-й этаж, купируется в покое за 3–5 минут. Одышка при умеренной нагрузке.",
        "Complaint_duration": "Около 8 месяцев, последние 2 месяца чаще",
        "Onset_context": "Впервые заметил боль при подъёме в гору на даче. Эпизодов боли в покое не было.",
    },
    "RISK_FACTORS": {
        "Smoking_status": "former",
        "Hypertension": "yes",
        "Diabetes_mellitus": "type2",
        "Dyslipidemia": "yes",
        "Obesity_or_Metabolic_syndrome": "Абдоминальное ожирение, окружность талии 108 см",
        "Chronic_kidney_disease_stage": "C2 (СКФ 72)",
        "Family_history_early_CVD": "Отец перенёс инфаркт миокарда в 54 года",
        "Physical_activity_level": "Малоподвижный образ жизни, офисная работа",
        "Alcohol_and_other_substances": "Алкоголь эпизодически, до 2 доз в неделю",
    },
    "PAST_EVENTS": {
        "Prior_MI": "Отрицает",
        "Prior_stroke_TIA": "Отрицает",
        "Prior_PE_DVT": "Отрицает",
        "Prior_cardiac_surgeries": "Не было",
        "Prior_congenital_heart_defect_and_surgeries": "Не было",
        "History_myocarditis_pericarditis": "Не было",
        "Other_major_diseases": "СД 2 типа с 2019 года, ХОБЛ нет",
    },
    "KNOWN_CVD_DIAGNOSES": {
        "Known_IHD": "Подозрение на ИБС, ранее не верифицирована",
        "Known_HF": "Нет установленного диагноза",
        "Known_arrhythmias": "Редкая наджелудочковая экстрасистолия по ЭКГ 2023 года",
        "Known_valvular_disease": "Нет",
        "Known_aortic_or_peripheral_arterial_disease": "Нет данных",
        "Known_pulmonary_hypertension": "Нет",
        "Known_congenital_heart_disease": "Нет",
    },
    "PHYSICAL_EXAM": {
        "Blood_pressure_right_systolic_mmHg": 148,
        "Blood_pressure_right_diastolic_mmHg": 92,
        "Blood_pressure_left_systolic_mmHg": 146,
        "Blood_pressure_left_diastolic_mmHg": 90,
        "Heart_rate_bpm": 78,
        "Resp_rate": 16,
        "SpO2_room_air_percent": 97,
        "Peripheral_edema": "Пастозность голеней к вечеру",
        "Lung_auscultation": "Дыхание везикулярное, хрипов нет",
        "Heart_auscultation": "Тоны приглушены, ритм правильный, шумов нет",
        "Peripheral_pulses": "Пульсация на артериях стоп сохранена, симметрична",
    },
    "LABS_CBC": {
        "Hb_g_L": 142,
        "WBC_10e9_L": 6.8,
        "PLT_10e9_L": 240,
    },
    "LABS_BIOCHEM": {
        "Creatinine_umol_L": 96,
        "eGFR_ml_min_1_73m2": 72,
        "ALT_U_L": 28,
        "AST_U_L": 24,
        "Na_mmol_L": 140,
        "K_mmol_L": 4.4,
        "Mg_mmol_L": 0.86,
        "Glucose_fasting_mmol_L": 7.1,
        "HbA1c_percent": 7.2,
    },
    "LABS_LIPIDS": {
        "Total_cholesterol_mmol_L": 5.9,
        "LDL_mmol_L": 3.8,
        "HDL_mmol_L": 1.0,
        "Triglycerides_mmol_L": 2.1,
    },
    "LABS_CARDIAC_MARKERS": {
        "Troponin_ng_L": 8,
        "NT_proBNP_pg_ml": 110,
    },
    "LABS_COAGULATION": {
        "INR": 1.0,
        "APTT_sec": 30,
    },
    "ECG_AND_BP_MONITORING": {
        "Resting_ECG_summary": "Синусовый ритм, ЧСС 76. Отклонение ЭОС влево. Признаки ГЛЖ (индекс Соколова–Лайона 38 мм). Очаговых изменений нет.",
        "Holter_ECG_summary": "За сутки: синусовый ритм, средняя ЧСС 72, редкие НЖЭС (54/сут), ЖЭС 12/сут, пауз и ишемических изменений не зарегистрировано.",
        "ABPM_summary": "Среднесуточное АД 142/88, недостаточное ночное снижение (non-dipper).",
    },
    "ECHOCARDIOGRAPHY": {
        "LVEDD_mm": 52,
        "LVESD_mm": 34,
        "LVEF_percent": 58,
        "LA_diameter_mm": 41,
        "RV_diameter_mm": 28,
        "PASP_mmHg": 28,
        "IVS_thickness_mm": 13,
        "PW_LV_thickness_mm": 12,
        "Valvular_regurgitation": "Митральная регургитация 1 ст., трикуспидальная 1 ст.",
        "Pericardial_effusion": "Нет",
    },
    "FUNCTIONAL_TESTS": {
        "Exercise_test_summary": "Тредмил-тест: при нагрузке 6.4 METs — депрессия ST до 1.5 мм в V4–V6, типичная стенокардия. Проба положительная.",
        "METs_max": 6.4,
        "SixMWT_distance_m": 420,
    },
    "CORONARY_AND_VASCULAR_IMAGING": {
        "Coronary_angiography_or_CTCA": "КТ-коронарография: стеноз ПМЖВ 60–70%, ПКА 40%. Кальциевый индекс 420 (Агатстон).",
        "Aorta_CT_MR": "Аорта не расширена, признаков диссекции нет",
        "Carotid_ultrasound": "Стеноз правой ВСА 35%, комплекс интима-медиа 1.1 мм",
        "Peripheral_artery_imaging": "Не проводилось",
        "Venous_ultrasound": "Не проводилось",
    },
    "DEVICES_AND_PROCEDURES": {
        "Coronary_stents": "Нет",
        "CABG_details": "Нет",
        "Valve_surgery_or_prosthesis": "Нет",
        "Pacemaker_ICD_CRT": "Нет",
        "Other_advanced_therapies": "Нет",
    },
    "CURRENT_MEDICATIONS": {
        "Antiplatelets": "Ацетилсалициловая кислота 100 мг вечером",
        "Anticoagulants": "Не получает",
        "Beta_blockers": "Бисопролол 5 мг утром",
        "ACEi_ARB_ARNI": "Периндоприл 8 мг утром",
        "MRA": "Не получает",
        "SGLT2_inhibitors": "Эмпаглифлозин 10 мг утром",
        "Diuretics": "Индапамид 1.5 мг утром",
        "Antiarrhythmics": "Не получает",
        "Lipid_lowering": "Аторвастатин 40 мг вечером",
        "Antidiabetic_drugs": "Метформин 1000 мг 2 раза в день",
        "Other_relevant_drugs": "Нет",
    },
    "SCORES_AND_CLASSES": {
        "NYHA_class": "II",
        "Angina_CCS_class": "II",
        "Killip_class_if_acute_MI": "Не применимо",
        "CHA2DS2_VASc": 3,
        "HAS_BLED": 1,
    },
    "FINAL_DIAGNOSES": {
        "Main_cardiovascular_diagnosis_text": "ИБС: стабильная стенокардия напряжения II ФК. Стенозирующий атеросклероз коронарных артерий (ПМЖВ 60–70%).",
        "Other_cardiovascular_diagnoses": "Гипертоническая болезнь II стадии, АГ 1 степени, риск 4. ГЛЖ. Дислипидемия.",
        "Non_cardiac_comorbidities": "СД 2 типа, целевой HbA1c не достигнут. Ожирение 1 степени. ХБП C2.",
        "ICD10_codes": ["I20.8", "I10", "E11.9", "E78.5"],
    },
    "MODEL_OUTPUT": {},
}


def demo_case_payload() -> dict[str, Any]:
    """Return a deep copy safe to mutate by the caller."""
    import copy

    return copy.deepcopy(DEMO_PATIENT_DATA)
