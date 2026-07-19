from __future__ import annotations

from typing import Any

from .auth import utc_now
from .versions import FHIR_PROFILE_VERSION


ICD10_SYSTEM = "http://hl7.org/fhir/sid/icd-10"
LOINC_SYSTEM = "http://loinc.org"


OBSERVATION_MAP = {
    ("GENERAL_INFO", "Age"): ("30525-0", "Age"),
    ("GENERAL_INFO", "Height_cm"): ("8302-2", "Body height"),
    ("GENERAL_INFO", "Weight_kg"): ("29463-7", "Body weight"),
    ("GENERAL_INFO", "BMI"): ("39156-5", "Body mass index"),
    ("PHYSICAL_EXAM", "Blood_pressure_right_systolic_mmHg"): ("8480-6", "Systolic blood pressure"),
    ("PHYSICAL_EXAM", "Blood_pressure_right_diastolic_mmHg"): ("8462-4", "Diastolic blood pressure"),
    ("PHYSICAL_EXAM", "Heart_rate_bpm"): ("8867-4", "Heart rate"),
    ("PHYSICAL_EXAM", "Resp_rate"): ("9279-1", "Respiratory rate"),
    ("PHYSICAL_EXAM", "SpO2_room_air_percent"): ("59408-5", "Oxygen saturation in arterial blood by pulse oximetry"),
    ("LABS_CBC", "Hb_g_L"): ("718-7", "Hemoglobin"),
    ("LABS_CBC", "WBC_10e9_L"): ("6690-2", "Leukocytes"),
    ("LABS_CBC", "PLT_10e9_L"): ("777-3", "Platelets"),
    ("LABS_BIOCHEM", "Creatinine_umol_L"): ("2160-0", "Creatinine"),
    ("LABS_BIOCHEM", "eGFR_ml_min_1_73m2"): ("33914-3", "Glomerular filtration rate"),
    ("LABS_BIOCHEM", "Na_mmol_L"): ("2951-2", "Sodium"),
    ("LABS_BIOCHEM", "K_mmol_L"): ("2823-3", "Potassium"),
    ("LABS_BIOCHEM", "Glucose_fasting_mmol_L"): ("1558-6", "Fasting glucose"),
    ("LABS_BIOCHEM", "HbA1c_percent"): ("4548-4", "Hemoglobin A1c"),
    ("LABS_LIPIDS", "Total_cholesterol_mmol_L"): ("2093-3", "Cholesterol"),
    ("LABS_LIPIDS", "LDL_mmol_L"): ("13457-7", "LDL cholesterol"),
    ("LABS_LIPIDS", "HDL_mmol_L"): ("2085-9", "HDL cholesterol"),
    ("LABS_LIPIDS", "Triglycerides_mmol_L"): ("2571-8", "Triglycerides"),
    ("LABS_CARDIAC_MARKERS", "Troponin_ng_L"): ("89579-7", "Troponin"),
    ("LABS_CARDIAC_MARKERS", "NT_proBNP_pg_ml"): ("33762-6", "NT-proBNP"),
    ("LABS_COAGULATION", "INR"): ("6301-6", "INR"),
    ("ECHOCARDIOGRAPHY", "LVEF_percent"): ("33878-0", "Left ventricular ejection fraction"),
}


def _icd10_concept(code: str) -> dict[str, Any]:
    return {"system": ICD10_SYSTEM, "code": str(code).strip()}


def _conclusion_resources(
    parsed_output: dict[str, Any],
    metadata: dict[str, Any],
    *,
    patient_ref: str,
    now: str,
) -> list[dict[str, Any]]:
    """Ресурсы заключения: диагноз врача, черновик AI и отчёт для МИС."""
    cds = parsed_output.get("CDS_OUTPUT") if isinstance(parsed_output.get("CDS_OUTPUT"), dict) else {}
    model_output = parsed_output.get("MODEL_OUTPUT") if isinstance(parsed_output.get("MODEL_OUTPUT"), dict) else {}
    resources: list[dict[str, Any]] = []

    doctor_name = str(metadata.get("doctor_name") or "").strip()
    organization = str(metadata.get("organization_name") or "").strip()
    performers: list[dict[str, Any]] = []
    if doctor_name:
        resources.append({
            "resourceType": "Practitioner",
            "id": "cvd-practitioner",
            "name": [{"use": "official", "text": doctor_name}],
        })
        performers.append({"reference": "Practitioner/cvd-practitioner", "display": doctor_name})
    if organization:
        resources.append({
            "resourceType": "Organization",
            "id": "cvd-organization",
            "name": organization,
        })
        performers.append({"reference": "Organization/cvd-organization", "display": organization})

    ai_diagnosis = str(model_output.get("Final_model_diagnosis") or cds.get("summary") or "").strip()
    ai_codes = [code for code in (model_output.get("Model_ICD10_codes") or []) if str(code).strip()]
    abstained = bool(cds.get("model_should_abstain"))

    report: dict[str, Any] = {
        "resourceType": "DiagnosticReport",
        "id": "cvd-ai-report",
        "status": "preliminary" if abstained else "final",
        "category": [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                "code": "OTH",
                "display": "Clinical decision support draft",
            }],
            "text": "Черновик системы поддержки принятия решений",
        }],
        "code": {"text": "Кардиологическое заключение (черновик AI)"},
        "subject": {"reference": patient_ref},
        "effectiveDateTime": now,
        "issued": now,
        "conclusion": ai_diagnosis or "AI воздержался от заключения: данных недостаточно.",
    }
    if performers:
        report["performer"] = performers
    if ai_codes:
        report["conclusionCode"] = [{
            "coding": [_icd10_concept(code) for code in ai_codes],
            "text": ai_diagnosis or "Черновик AI",
        }]
    resources.append(report)

    diagnoses = cds.get("possible_diagnoses") if isinstance(cds.get("possible_diagnoses"), list) else []
    red_flags = [str(flag) for flag in (cds.get("red_flags") or []) if str(flag).strip()]
    impression: dict[str, Any] = {
        "resourceType": "ClinicalImpression",
        "id": "cvd-ai-impression",
        "status": "completed",
        "description": "Черновик клинического рассуждения CVD Engine. Требует проверки врачом.",
        "subject": {"reference": patient_ref},
        "date": now,
        "summary": str(cds.get("summary") or "").strip() or "Сводка не сформирована.",
    }
    findings = []
    for item in diagnoses:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        codes = [code for code in (item.get("icd10_codes") or []) if str(code).strip()]
        finding: dict[str, Any] = {"itemCodeableConcept": {"text": name}}
        if codes:
            finding["itemCodeableConcept"]["coding"] = [_icd10_concept(code) for code in codes]
        supporting = [str(value) for value in (item.get("supporting_findings") or []) if str(value).strip()]
        if supporting:
            finding["basis"] = "; ".join(supporting)
        findings.append(finding)
    if findings:
        impression["finding"] = findings
    if red_flags:
        impression["note"] = [{"text": "Red flags: " + "; ".join(red_flags)}]
    resources.append(impression)

    treatment = str(model_output.get("Model_treatment_recommendations") or "").strip()
    rehabilitation = str(model_output.get("Model_rehabilitation_recommendations") or "").strip()
    if treatment or rehabilitation:
        resources.append({
            "resourceType": "CarePlan",
            "id": "cvd-ai-careplan",
            "status": "draft",
            "intent": "proposal",
            "title": "Черновик рекомендаций (требует утверждения врачом)",
            "subject": {"reference": patient_ref},
            "created": now,
            "description": " ".join(part for part in (treatment, rehabilitation) if part),
        })

    return resources


def build_fhir_bundle(
    patient_data: dict[str, Any],
    *,
    case_id: int | None,
    case_title: str,
    parsed_output: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = utc_now()
    patient_ref = "Patient/cvd-patient"
    entries: list[dict[str, Any]] = []
    patient = {
        "resourceType": "Patient",
        "id": "cvd-patient",
        "identifier": [
            {
                "system": "urn:cvd:case-patient-id",
                "value": str(patient_data.get("GENERAL_INFO", {}).get("Patient_ID") or case_id or "unknown"),
            }
        ],
    }
    sex = patient_data.get("GENERAL_INFO", {}).get("Sex")
    if sex in {"male", "female", "other", "unknown"}:
        patient["gender"] = sex
    full_name = str(patient_data.get("GENERAL_INFO", {}).get("Full_name") or "").strip()
    if full_name:
        patient["name"] = [{"use": "usual", "text": full_name}]
    entries.append(entry(patient))

    for (section, field), (code, display) in OBSERVATION_MAP.items():
        value = patient_data.get(section, {}).get(field)
        if value is None or value == "":
            continue
        observation = {
            "resourceType": "Observation",
            "status": "final",
            "code": {"coding": [{"system": LOINC_SYSTEM, "code": code, "display": display}], "text": display},
            "subject": {"reference": patient_ref},
            "effectiveDateTime": now,
        }
        if isinstance(value, (int, float)):
            observation["valueQuantity"] = {"value": value}
        else:
            observation["valueString"] = str(value)
        entries.append(entry(observation))

    diagnoses = patient_data.get("FINAL_DIAGNOSES", {})
    main_diagnosis = diagnoses.get("Main_cardiovascular_diagnosis_text")
    icd_codes = diagnoses.get("ICD10_codes") or []
    if main_diagnosis or icd_codes:
        condition = {
            "resourceType": "Condition",
            "id": "cvd-doctor-diagnosis",
            "clinicalStatus": {
                "coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]
            },
            # Диагноз врача — подтверждённый, в отличие от черновика AI в ClinicalImpression.
            "verificationStatus": {
                "coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status", "code": "confirmed"}]
            },
            "subject": {"reference": patient_ref},
            "code": {
                "text": str(main_diagnosis or "; ".join(icd_codes)),
                "coding": [{"system": ICD10_SYSTEM, "code": code} for code in icd_codes],
            },
        }
        entries.append(entry(condition))

    medication_section = patient_data.get("CURRENT_MEDICATIONS", {})
    for key, value in medication_section.items():
        if value is None or value == "":
            continue
        entries.append(entry({
            "resourceType": "MedicationStatement",
            "status": "recorded",
            "medicationCodeableConcept": {"text": f"{key}: {value}"},
            "subject": {"reference": patient_ref},
            "effectiveDateTime": now,
        }))

    conclusion_sections: list[dict[str, Any]] = []
    if parsed_output:
        for resource in _conclusion_resources(parsed_output, metadata or {}, patient_ref=patient_ref, now=now):
            entries.append(entry(resource))
        conclusion_sections = [
            {
                "title": "Заключение (черновик AI)",
                "entry": [{"reference": "DiagnosticReport/cvd-ai-report"}],
            },
            {
                "title": "Клиническое рассуждение AI",
                "entry": [{"reference": "ClinicalImpression/cvd-ai-impression"}],
            },
        ]

    composition: dict[str, Any] = {
        "resourceType": "Composition",
        "id": "cvd-composition",
        "status": "final",
        "type": {"text": "Кардиологический случай CVD"},
        "subject": {"reference": patient_ref},
        "date": now,
        "title": case_title,
        "section": [
            {
                "title": "Структурированные данные случая",
                "text": {"status": "generated", "div": "<div>Структурированная CVD-анкета</div>"},
            },
            *conclusion_sections,
        ],
    }
    if (metadata or {}).get("doctor_name"):
        composition["author"] = [{"reference": "Practitioner/cvd-practitioner"}]
    entries.append(entry(composition))

    return {
        "resourceType": "Bundle",
        "type": "collection",
        "timestamp": now,
        "meta": {"profile": [f"urn:cvd:{FHIR_PROFILE_VERSION}"]},
        "entry": entries,
    }


def entry(resource: dict[str, Any]) -> dict[str, Any]:
    return {"resource": resource}
