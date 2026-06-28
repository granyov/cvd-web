from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


ICD10_PATTERN = re.compile(r"^[A-Z]\d{2}(?:\.\d{1,2})?$")


@dataclass(frozen=True)
class FieldSpec:
    key: str
    kind: str = "text"
    min_value: float | None = None
    max_value: float | None = None


@dataclass(frozen=True)
class SectionSpec:
    key: str
    fields: tuple[FieldSpec, ...]


CVD_SCHEMA: tuple[SectionSpec, ...] = (
    SectionSpec("GENERAL_INFO", (
        FieldSpec("Patient_ID"),
        FieldSpec("Full_name"),
        FieldSpec("Sex"),
        FieldSpec("Age", "number", 0, 120),
        FieldSpec("Height_cm", "number", 80, 230),
        FieldSpec("Weight_kg", "number", 20, 250),
        FieldSpec("BMI", "number", 5, 90),
    )),
    SectionSpec("COMPLAINTS", (
        FieldSpec("Main_complaint"),
        FieldSpec("Complaint_duration"),
        FieldSpec("Onset_context"),
    )),
    SectionSpec("RISK_FACTORS", (
        FieldSpec("Smoking_status"),
        FieldSpec("Hypertension"),
        FieldSpec("Diabetes_mellitus"),
        FieldSpec("Dyslipidemia"),
        FieldSpec("Obesity_or_Metabolic_syndrome"),
        FieldSpec("Chronic_kidney_disease_stage"),
        FieldSpec("Family_history_early_CVD"),
        FieldSpec("Physical_activity_level"),
        FieldSpec("Alcohol_and_other_substances"),
    )),
    SectionSpec("PAST_EVENTS", (
        FieldSpec("Prior_MI"),
        FieldSpec("Prior_stroke_TIA"),
        FieldSpec("Prior_PE_DVT"),
        FieldSpec("Prior_cardiac_surgeries"),
        FieldSpec("Prior_congenital_heart_defect_and_surgeries"),
        FieldSpec("History_myocarditis_pericarditis"),
        FieldSpec("Other_major_diseases"),
    )),
    SectionSpec("KNOWN_CVD_DIAGNOSES", (
        FieldSpec("Known_IHD"),
        FieldSpec("Known_HF"),
        FieldSpec("Known_arrhythmias"),
        FieldSpec("Known_valvular_disease"),
        FieldSpec("Known_aortic_or_peripheral_arterial_disease"),
        FieldSpec("Known_pulmonary_hypertension"),
        FieldSpec("Known_congenital_heart_disease"),
    )),
    SectionSpec("PHYSICAL_EXAM", (
        FieldSpec("Blood_pressure_right_systolic_mmHg", "number", 40, 300),
        FieldSpec("Blood_pressure_right_diastolic_mmHg", "number", 20, 200),
        FieldSpec("Blood_pressure_left_systolic_mmHg", "number", 40, 300),
        FieldSpec("Blood_pressure_left_diastolic_mmHg", "number", 20, 200),
        FieldSpec("Heart_rate_bpm", "number", 20, 250),
        FieldSpec("Resp_rate", "number", 4, 80),
        FieldSpec("SpO2_room_air_percent", "number", 40, 100),
        FieldSpec("Peripheral_edema"),
        FieldSpec("Lung_auscultation"),
        FieldSpec("Heart_auscultation"),
        FieldSpec("Peripheral_pulses"),
    )),
    SectionSpec("LABS_CBC", (
        FieldSpec("Hb_g_L", "number", 20, 250),
        FieldSpec("WBC_10e9_L", "number", 0, 300),
        FieldSpec("PLT_10e9_L", "number", 0, 2000),
    )),
    SectionSpec("LABS_BIOCHEM", (
        FieldSpec("Creatinine_umol_L", "number", 0, 3000),
        FieldSpec("eGFR_ml_min_1_73m2", "number", 0, 200),
        FieldSpec("ALT_U_L", "number", 0, 5000),
        FieldSpec("AST_U_L", "number", 0, 5000),
        FieldSpec("Na_mmol_L", "number", 80, 200),
        FieldSpec("K_mmol_L", "number", 1, 10),
        FieldSpec("Mg_mmol_L", "number", 0, 5),
        FieldSpec("Glucose_fasting_mmol_L", "number", 0, 80),
        FieldSpec("HbA1c_percent", "number", 0, 25),
    )),
    SectionSpec("LABS_LIPIDS", (
        FieldSpec("Total_cholesterol_mmol_L", "number", 0, 30),
        FieldSpec("LDL_mmol_L", "number", 0, 30),
        FieldSpec("HDL_mmol_L", "number", 0, 10),
        FieldSpec("Triglycerides_mmol_L", "number", 0, 50),
    )),
    SectionSpec("LABS_CARDIAC_MARKERS", (
        FieldSpec("Troponin_ng_L", "number", 0, 1000000),
        FieldSpec("CKMB_U_L", "number", 0, 100000),
        FieldSpec("NT_proBNP_pg_ml", "number", 0, 1000000),
    )),
    SectionSpec("LABS_COAGULATION", (
        FieldSpec("INR", "number", 0, 20),
        FieldSpec("APTT_sec", "number", 0, 300),
    )),
    SectionSpec("ECG_AND_BP_MONITORING", (
        FieldSpec("Resting_ECG_summary"),
        FieldSpec("Holter_ECG_summary"),
        FieldSpec("ABPM_summary"),
    )),
    SectionSpec("ECHOCARDIOGRAPHY", (
        FieldSpec("LVEDD_mm", "number", 0, 150),
        FieldSpec("LVESD_mm", "number", 0, 150),
        FieldSpec("LVEF_percent", "number", 0, 100),
        FieldSpec("LA_diameter_mm", "number", 0, 120),
        FieldSpec("RV_diameter_mm", "number", 0, 120),
        FieldSpec("PASP_mmHg", "number", 0, 200),
        FieldSpec("IVS_thickness_mm", "number", 0, 50),
        FieldSpec("PW_LV_thickness_mm", "number", 0, 50),
        FieldSpec("Mitral_valve_area_cm2", "number", 0, 20),
        FieldSpec("Aortic_valve_area_cm2", "number", 0, 20),
        FieldSpec("Valvular_regurgitation"),
        FieldSpec("Pericardial_effusion"),
    )),
    SectionSpec("FUNCTIONAL_TESTS", (
        FieldSpec("Exercise_test_summary"),
        FieldSpec("METs_max", "number", 0, 30),
        FieldSpec("SixMWT_distance_m", "number", 0, 1500),
    )),
    SectionSpec("CORONARY_AND_VASCULAR_IMAGING", (
        FieldSpec("Coronary_angiography_or_CTCA"),
        FieldSpec("Aorta_CT_MR"),
        FieldSpec("Carotid_ultrasound"),
        FieldSpec("Peripheral_artery_imaging"),
        FieldSpec("Venous_ultrasound"),
    )),
    SectionSpec("DEVICES_AND_PROCEDURES", (
        FieldSpec("Coronary_stents"),
        FieldSpec("CABG_details"),
        FieldSpec("Valve_surgery_or_prosthesis"),
        FieldSpec("Pacemaker_ICD_CRT"),
        FieldSpec("Other_advanced_therapies"),
    )),
    SectionSpec("CURRENT_MEDICATIONS", (
        FieldSpec("Antiplatelets"),
        FieldSpec("Anticoagulants"),
        FieldSpec("Beta_blockers"),
        FieldSpec("ACEi_ARB_ARNI"),
        FieldSpec("MRA"),
        FieldSpec("SGLT2_inhibitors"),
        FieldSpec("Diuretics"),
        FieldSpec("Antiarrhythmics"),
        FieldSpec("Lipid_lowering"),
        FieldSpec("Antidiabetic_drugs"),
        FieldSpec("Other_relevant_drugs"),
    )),
    SectionSpec("SCORES_AND_CLASSES", (
        FieldSpec("NYHA_class"),
        FieldSpec("Angina_CCS_class"),
        FieldSpec("Killip_class_if_acute_MI"),
        FieldSpec("CHA2DS2_VASc", "number", 0, 20),
        FieldSpec("HAS_BLED", "number", 0, 20),
    )),
    SectionSpec("FINAL_DIAGNOSES", (
        FieldSpec("Main_cardiovascular_diagnosis_text"),
        FieldSpec("Other_cardiovascular_diagnoses"),
        FieldSpec("Non_cardiac_comorbidities"),
        FieldSpec("ICD10_codes", "icd10_list"),
    )),
    SectionSpec("MODEL_OUTPUT", (
        FieldSpec("Final_model_diagnosis"),
        FieldSpec("Model_ICD10_codes", "icd10_list"),
        FieldSpec("Model_treatment_recommendations"),
        FieldSpec("Model_rehabilitation_recommendations"),
    )),
)


def validate_and_normalize_patient_data(value: Any) -> tuple[dict[str, dict[str, Any]], list[str]]:
    if not isinstance(value, dict):
        return {}, ["patient_data должен быть объектом"]

    errors: list[str] = []
    normalized: dict[str, dict[str, Any]] = {}
    known_sections = {section.key for section in CVD_SCHEMA}

    for unknown_section in sorted(set(value.keys()) - known_sections):
        errors.append(f"Неизвестный раздел: {unknown_section}")

    for section in CVD_SCHEMA:
        raw_section = value.get(section.key) or {}
        if not isinstance(raw_section, dict):
            errors.append(f"{section.key} должен быть объектом")
            raw_section = {}
        normalized[section.key] = {}
        known_fields = {field.key for field in section.fields}
        for unknown_field in sorted(set(raw_section.keys()) - known_fields):
            errors.append(f"Неизвестное поле: {section.key}.{unknown_field}")

        for field in section.fields:
            raw = raw_section.get(field.key)
            normalized[section.key][field.key] = normalize_field(section.key, field, raw, errors)

    return normalized, errors


def normalize_field(section_key: str, field: FieldSpec, raw: Any, errors: list[str]) -> Any:
    path = f"{section_key}.{field.key}"
    if raw is None or raw == "":
        return None

    if field.kind == "number":
        try:
            value = float(str(raw).replace(",", "."))
        except (TypeError, ValueError):
            errors.append(f"{path} должен быть числом")
            return None
        if field.min_value is not None and value < field.min_value:
            errors.append(f"{path} ниже допустимого минимума {field.min_value:g}")
        if field.max_value is not None and value > field.max_value:
            errors.append(f"{path} выше допустимого максимума {field.max_value:g}")
        return int(value) if value.is_integer() else value

    if field.kind == "icd10_list":
        if isinstance(raw, list):
            items = raw
        else:
            items = re.split(r"[,;]+", str(raw))
        codes = [str(item).strip().upper() for item in items if str(item).strip()]
        invalid = [code for code in codes if not ICD10_PATTERN.match(code)]
        for code in invalid:
            errors.append(f"{path} содержит некорректный код МКБ-10: {code}")
        return codes or None

    if isinstance(raw, (dict, list)):
        errors.append(f"{path} должен быть строкой")
        return None
    text = str(raw).strip()
    return text or None
