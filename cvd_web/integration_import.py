from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from typing import Any

from .cvd_schema import CVD_SCHEMA, ICD10_PATTERN, validate_and_normalize_patient_data
from .versions import IMPORT_MAPPING_VERSION


MAX_TEXT_LENGTH = 4000
MAX_WARNINGS = 50
KNOWN_PATHS = tuple(
    f"{section.key}.{field.key}"
    for section in CVD_SCHEMA
    for field in section.fields
    if section.key != "MODEL_OUTPUT"
)
PATH_ORDER = {path: index for index, path in enumerate(KNOWN_PATHS)}


LOINC_PATHS: dict[str, tuple[str, str]] = {
    "30525-0": ("GENERAL_INFO.Age", "a"),
    "8302-2": ("GENERAL_INFO.Height_cm", "cm"),
    "29463-7": ("GENERAL_INFO.Weight_kg", "kg"),
    "39156-5": ("GENERAL_INFO.BMI", "kg/m2"),
    "8480-6": ("PHYSICAL_EXAM.Blood_pressure_right_systolic_mmHg", "mmHg"),
    "8462-4": ("PHYSICAL_EXAM.Blood_pressure_right_diastolic_mmHg", "mmHg"),
    "8867-4": ("PHYSICAL_EXAM.Heart_rate_bpm", "/min"),
    "9279-1": ("PHYSICAL_EXAM.Resp_rate", "/min"),
    "59408-5": ("PHYSICAL_EXAM.SpO2_room_air_percent", "%"),
    "718-7": ("LABS_CBC.Hb_g_L", "g/L"),
    "6690-2": ("LABS_CBC.WBC_10e9_L", "10^9/L"),
    "777-3": ("LABS_CBC.PLT_10e9_L", "10^9/L"),
    "2160-0": ("LABS_BIOCHEM.Creatinine_umol_L", "umol/L"),
    "33914-3": ("LABS_BIOCHEM.eGFR_ml_min_1_73m2", "mL/min/1.73m2"),
    "1742-6": ("LABS_BIOCHEM.ALT_U_L", "U/L"),
    "1920-8": ("LABS_BIOCHEM.AST_U_L", "U/L"),
    "2951-2": ("LABS_BIOCHEM.Na_mmol_L", "mmol/L"),
    "2823-3": ("LABS_BIOCHEM.K_mmol_L", "mmol/L"),
    "2601-3": ("LABS_BIOCHEM.Mg_mmol_L", "mmol/L"),
    "1558-6": ("LABS_BIOCHEM.Glucose_fasting_mmol_L", "mmol/L"),
    "4548-4": ("LABS_BIOCHEM.HbA1c_percent", "%"),
    "2093-3": ("LABS_LIPIDS.Total_cholesterol_mmol_L", "mmol/L"),
    "13457-7": ("LABS_LIPIDS.LDL_mmol_L", "mmol/L"),
    "2085-9": ("LABS_LIPIDS.HDL_mmol_L", "mmol/L"),
    "2571-8": ("LABS_LIPIDS.Triglycerides_mmol_L", "mmol/L"),
    "89579-7": ("LABS_CARDIAC_MARKERS.Troponin_ng_L", "ng/L"),
    "13969-1": ("LABS_CARDIAC_MARKERS.CKMB_U_L", "U/L"),
    "33762-6": ("LABS_CARDIAC_MARKERS.NT_proBNP_pg_ml", "pg/mL"),
    "6301-6": ("LABS_COAGULATION.INR", ""),
    "14979-9": ("LABS_COAGULATION.APTT_sec", "s"),
    "33878-0": ("ECHOCARDIOGRAPHY.LVEF_percent", "%"),
}

COMBINE_PATHS = {
    "PAST_EVENTS.Prior_MI",
    "PAST_EVENTS.Prior_stroke_TIA",
    "PAST_EVENTS.Prior_PE_DVT",
    "PAST_EVENTS.Prior_cardiac_surgeries",
    "PAST_EVENTS.Other_major_diseases",
    "KNOWN_CVD_DIAGNOSES.Known_IHD",
    "KNOWN_CVD_DIAGNOSES.Known_HF",
    "KNOWN_CVD_DIAGNOSES.Known_arrhythmias",
    "KNOWN_CVD_DIAGNOSES.Known_valvular_disease",
    "KNOWN_CVD_DIAGNOSES.Known_aortic_or_peripheral_arterial_disease",
    "KNOWN_CVD_DIAGNOSES.Known_pulmonary_hypertension",
    "KNOWN_CVD_DIAGNOSES.Known_congenital_heart_disease",
    "CURRENT_MEDICATIONS.Antiplatelets",
    "CURRENT_MEDICATIONS.Anticoagulants",
    "CURRENT_MEDICATIONS.Beta_blockers",
    "CURRENT_MEDICATIONS.ACEi_ARB_ARNI",
    "CURRENT_MEDICATIONS.MRA",
    "CURRENT_MEDICATIONS.SGLT2_inhibitors",
    "CURRENT_MEDICATIONS.Diuretics",
    "CURRENT_MEDICATIONS.Antiarrhythmics",
    "CURRENT_MEDICATIONS.Lipid_lowering",
    "CURRENT_MEDICATIONS.Antidiabetic_drugs",
    "CURRENT_MEDICATIONS.Other_relevant_drugs",
    "DEVICES_AND_PROCEDURES.Coronary_stents",
    "DEVICES_AND_PROCEDURES.CABG_details",
    "DEVICES_AND_PROCEDURES.Valve_surgery_or_prosthesis",
    "DEVICES_AND_PROCEDURES.Pacemaker_ICD_CRT",
    "DEVICES_AND_PROCEDURES.Other_advanced_therapies",
    "FINAL_DIAGNOSES.Other_cardiovascular_diagnoses",
    "FINAL_DIAGNOSES.Non_cardiac_comorbidities",
}


@dataclass(frozen=True)
class Source:
    resource_type: str
    resource_id: str = ""
    label: str = ""
    date: str = ""
    unit: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "label": self.label,
            "date": self.date,
            "unit": self.unit,
        }


class MappingCollector:
    def __init__(self) -> None:
        self._items: dict[str, list[dict[str, Any]]] = {}
        self.warnings: list[str] = []

    def warn(self, message: str) -> None:
        message = clean_text(message, 500)
        if message and message not in self.warnings and len(self.warnings) < MAX_WARNINGS:
            self.warnings.append(message)

    def add(self, path: str, value: Any, source: Source, confidence: str = "structured") -> None:
        if path not in PATH_ORDER or value is None or value == "" or value == []:
            return
        if isinstance(value, str):
            value = clean_text(value)
        self._items.setdefault(path, []).append({
            "value": value,
            "source": source,
            "confidence": confidence,
        })

    def add_condition(self, code: str, text: str, source: Source, confidence: str = "coded") -> None:
        code = str(code or "").strip().upper()
        text = clean_text(text or code)
        if not text and not code:
            return

        if code.startswith("I10") or code.startswith(("I11", "I12", "I13", "I15")):
            self.add("RISK_FACTORS.Hypertension", "yes", source, confidence)
        if code.startswith(("E10", "E11")):
            self.add("RISK_FACTORS.Diabetes_mellitus", "type1" if code.startswith("E10") else "type2", source, confidence)
        if code.startswith("E78"):
            self.add("RISK_FACTORS.Dyslipidemia", "yes", source, confidence)
        if code.startswith(("I20", "I21", "I22", "I23", "I24", "I25")):
            self.add("KNOWN_CVD_DIAGNOSES.Known_IHD", text, source, confidence)
        if code.startswith("I50"):
            self.add("KNOWN_CVD_DIAGNOSES.Known_HF", text, source, confidence)
        if code.startswith(("I47", "I48", "I49")):
            self.add("KNOWN_CVD_DIAGNOSES.Known_arrhythmias", text, source, confidence)
        if code.startswith(("I05", "I06", "I07", "I08", "I34", "I35", "I36", "I37")):
            self.add("KNOWN_CVD_DIAGNOSES.Known_valvular_disease", text, source, confidence)
        if code.startswith(("I70", "I71", "I72", "I73", "I74")):
            self.add("KNOWN_CVD_DIAGNOSES.Known_aortic_or_peripheral_arterial_disease", text, source, confidence)
        if code.startswith("I27"):
            self.add("KNOWN_CVD_DIAGNOSES.Known_pulmonary_hypertension", text, source, confidence)
        if code.startswith("Q2"):
            self.add("KNOWN_CVD_DIAGNOSES.Known_congenital_heart_disease", text, source, confidence)
        if code.startswith(("I21", "I22")):
            self.add("PAST_EVENTS.Prior_MI", text, source, confidence)
        if code.startswith(("I63", "I64", "G45")):
            self.add("PAST_EVENTS.Prior_stroke_TIA", text, source, confidence)
        if code.startswith(("I26", "I80", "I82")):
            self.add("PAST_EVENTS.Prior_PE_DVT", text, source, confidence)

        if ICD10_PATTERN.match(code):
            if code.startswith(("I", "Q2")):
                self.add("FINAL_DIAGNOSES.ICD10_codes", [code], source, confidence)
                self.add("FINAL_DIAGNOSES.Other_cardiovascular_diagnoses", text, source, confidence)
            else:
                self.add("FINAL_DIAGNOSES.Non_cardiac_comorbidities", text, source, confidence)

    def finalize(self) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for path, items in self._items.items():
            items = sorted(items, key=lambda item: item["source"].date or "")
            values = [item["value"] for item in items]
            serialized_values = {json.dumps(value, ensure_ascii=False, sort_keys=True) for value in values}

            if path == "FINAL_DIAGNOSES.ICD10_codes":
                combined: list[str] = []
                for value in values:
                    candidates = value if isinstance(value, list) else [value]
                    for candidate in candidates:
                        code = str(candidate).strip().upper()
                        if ICD10_PATTERN.match(code) and code not in combined:
                            combined.append(code)
                value: Any = combined
                source_conflict = False
            elif path in COMBINE_PATHS:
                unique = []
                for item in values:
                    text = clean_text(item)
                    if text and text not in unique:
                        unique.append(text)
                value = "; ".join(unique)[:MAX_TEXT_LENGTH]
                source_conflict = False
            else:
                value = items[-1]["value"]
                source_conflict = len(serialized_values) > 1

            sources = [item["source"].as_dict() for item in items[-5:]]
            confidence = "structured" if all(item["confidence"] == "structured" for item in items) else items[-1]["confidence"]
            output.append({
                "path": path,
                "value": value,
                "confidence": confidence,
                "source_conflict": source_conflict,
                "sources": sources,
            })

        output.sort(key=lambda item: PATH_ORDER[item["path"]])
        return output


def parse_clinical_import(source_format: str, payload: Any) -> dict[str, Any]:
    requested = str(source_format or "auto").strip().lower()
    if requested not in {"auto", "fhir", "cda", "cvd"}:
        raise ValueError("Неподдерживаемый формат импорта")

    if requested == "fhir" or (requested == "auto" and isinstance(payload, dict) and payload.get("resourceType") == "Bundle"):
        return parse_fhir_bundle(payload)
    if requested == "cvd" or (requested == "auto" and isinstance(payload, dict)):
        return parse_cvd_document(payload)
    if requested == "cda" or (requested == "auto" and isinstance(payload, str) and payload.lstrip().startswith("<")):
        return parse_cda_document(str(payload))
    raise ValueError("Не удалось определить формат. Нужен FHIR Bundle JSON или CDA XML")


def parse_cvd_document(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("CVD-импорт ожидает JSON-объект")
    patient_data = payload
    if payload.get("format") == "cvd-patient":
        if payload.get("format_version") != 1:
            raise ValueError("Версия CVD-файла не поддерживается")
        patient_data = payload.get("patient_data")
    normalized, errors = validate_and_normalize_patient_data(patient_data)
    if errors:
        preview = "; ".join(errors[:5])
        if len(errors) > 5:
            preview += f"; и ещё {len(errors) - 5}"
        raise ValueError(f"Некорректный CVD-файл: {preview}")

    collector = MappingCollector()
    source = Source("CVD JSON", "", "CVD JSON")
    for section in CVD_SCHEMA:
        if section.key == "MODEL_OUTPUT":
            continue
        for field in section.fields:
            collector.add(f"{section.key}.{field.key}", normalized[section.key][field.key], source, "native")
    mappings = collector.finalize()
    if not mappings:
        collector.warn("В CVD-файле нет заполненных полей")
    return import_result("cvd-json", mappings, collector.warnings, 1)


def parse_fhir_bundle(bundle: Any) -> dict[str, Any]:
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        raise ValueError("FHIR-импорт ожидает ресурс Bundle")
    entries = bundle.get("entry") or []
    if not isinstance(entries, list):
        raise ValueError("FHIR Bundle.entry должен быть массивом")

    collector = MappingCollector()
    resources = [entry.get("resource") for entry in entries if isinstance(entry, dict) and isinstance(entry.get("resource"), dict)]
    for resource in resources:
        resource_type = str(resource.get("resourceType") or "")
        handlers = {
            "Patient": map_fhir_patient,
            "Observation": map_fhir_observation,
            "Condition": map_fhir_condition,
            "DiagnosticReport": map_fhir_diagnostic_report,
            "MedicationStatement": map_fhir_medication,
            "MedicationRequest": map_fhir_medication,
            "Procedure": map_fhir_procedure,
        }
        handler = handlers.get(resource_type)
        if handler:
            handler(resource, collector)

    mappings = collector.finalize()
    if not mappings:
        collector.warn("В FHIR Bundle не найдено данных, которые можно сопоставить с CVD-анкетой")
    return import_result("fhir-r4", mappings, collector.warnings, len(resources))


def map_fhir_patient(resource: dict[str, Any], collector: MappingCollector) -> None:
    source = Source("Patient", str(resource.get("id") or ""), "Пациент")
    identifiers = resource.get("identifier") or []
    values = [str(item.get("value") or "").strip() for item in identifiers if isinstance(item, dict)]
    patient_id = next((value for value in values if value), "")
    collector.add("GENERAL_INFO.Patient_ID", patient_id, source)

    names = resource.get("name") or []
    full_name = ""
    for name in names:
        if not isinstance(name, dict):
            continue
        full_name = clean_text(name.get("text"))
        if not full_name:
            parts = [name.get("family"), *(name.get("given") or [])]
            full_name = clean_text(" ".join(str(part or "") for part in parts))
        if full_name:
            break
    collector.add("GENERAL_INFO.Full_name", full_name, source)

    gender = str(resource.get("gender") or "").lower()
    if gender in {"male", "female", "other", "unknown"}:
        collector.add("GENERAL_INFO.Sex", gender, source)
    birth_date = str(resource.get("birthDate") or "")
    age = age_from_date(birth_date)
    if age is not None:
        collector.add("GENERAL_INFO.Age", age, Source("Patient", source.resource_id, "Дата рождения", birth_date))


def map_fhir_observation(resource: dict[str, Any], collector: MappingCollector) -> None:
    status = str(resource.get("status") or "")
    if status == "entered-in-error":
        return
    resource_id = str(resource.get("id") or "")
    effective = str(resource.get("effectiveDateTime") or resource.get("issued") or "")
    observation_label = concept_text(resource.get("code")) or "Наблюдение"
    code_values = concept_codes(resource.get("code"))
    map_observation_value(code_values, resource, resource_id, observation_label, effective, collector)

    for component in resource.get("component") or []:
        if not isinstance(component, dict):
            continue
        label = concept_text(component.get("code")) or observation_label
        map_observation_value(concept_codes(component.get("code")), component, resource_id, label, effective, collector)


def map_observation_value(
    codes: list[str],
    node: dict[str, Any],
    resource_id: str,
    label: str,
    effective: str,
    collector: MappingCollector,
) -> None:
    matched_code = next((code for code in codes if code in LOINC_PATHS), "")
    if not matched_code:
        return
    value, unit = fhir_value(node)
    if value is None:
        return
    path, expected_unit = LOINC_PATHS[matched_code]
    source = Source("Observation", resource_id, label, effective, unit)
    collector.add(path, value, source)
    if unit and expected_unit and normalize_unit(unit) != normalize_unit(expected_unit):
        collector.warn(f"{label}: единица '{unit}' отличается от ожидаемой '{expected_unit}', проверьте значение")


def map_fhir_condition(resource: dict[str, Any], collector: MappingCollector) -> None:
    if resource_status_code(resource.get("verificationStatus")) == "entered-in-error":
        return
    text = concept_text(resource.get("code")) or "Диагноз без названия"
    codes = concept_codes(resource.get("code"))
    source = Source(
        "Condition",
        str(resource.get("id") or ""),
        text,
        str(resource.get("onsetDateTime") or resource.get("recordedDate") or ""),
    )
    icd_codes = [code.upper() for code in codes if ICD10_PATTERN.match(code.upper())]
    if icd_codes:
        for code in icd_codes:
            collector.add_condition(code, text, source)
    else:
        collector.warn(f"Condition '{text}' не сопоставлен: отсутствует распознанный код МКБ-10")


def map_fhir_diagnostic_report(resource: dict[str, Any], collector: MappingCollector) -> None:
    if str(resource.get("status") or "") == "entered-in-error":
        return
    label = concept_text(resource.get("code")) or "Диагностический отчёт"
    conclusion = clean_text(resource.get("conclusion"))
    if not conclusion:
        return
    path = report_path(label)
    source = Source("DiagnosticReport", str(resource.get("id") or ""), label, str(resource.get("effectiveDateTime") or resource.get("issued") or ""))
    if path:
        collector.add(path, conclusion, source, "report-text")
    else:
        collector.warn(f"DiagnosticReport '{label}' сохранён как источник, но не имеет однозначного поля CVD")


def map_fhir_medication(resource: dict[str, Any], collector: MappingCollector) -> None:
    if str(resource.get("status") or "") == "entered-in-error":
        return
    concept = resource.get("medicationCodeableConcept")
    name = concept_text(concept)
    if not name and isinstance(resource.get("medicationReference"), dict):
        name = clean_text(resource["medicationReference"].get("display"))
    dosage_texts = []
    for dosage in resource.get("dosage") or resource.get("dosageInstruction") or []:
        if isinstance(dosage, dict) and dosage.get("text"):
            dosage_texts.append(clean_text(dosage.get("text"), 500))
    value = name
    if name and dosage_texts:
        value = f"{name}: {'; '.join(dosage_texts)}"
    if not value:
        return
    source = Source(str(resource.get("resourceType") or "Medication"), str(resource.get("id") or ""), name)
    collector.add(medication_path(value), value, source, "keyword")


def map_fhir_procedure(resource: dict[str, Any], collector: MappingCollector) -> None:
    if str(resource.get("status") or "") == "entered-in-error":
        return
    name = concept_text(resource.get("code"))
    if not name:
        return
    path = procedure_path(name)
    source = Source("Procedure", str(resource.get("id") or ""), name, str(resource.get("performedDateTime") or ""))
    if path:
        collector.add(path, name, source, "keyword")
    else:
        collector.warn(f"Procedure '{name}' не относится к поддерживаемым кардиологическим процедурам")


def parse_cda_document(xml_text: str) -> dict[str, Any]:
    if not isinstance(xml_text, str) or not xml_text.strip():
        raise ValueError("CDA XML пуст")
    upper_prefix = xml_text[:10000].upper()
    if "<!DOCTYPE" in upper_prefix or "<!ENTITY" in upper_prefix:
        raise ValueError("CDA с DTD или ENTITY не поддерживается")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError("Некорректный CDA XML") from exc
    if local_name(root.tag) != "ClinicalDocument":
        raise ValueError("XML не является CDA ClinicalDocument")

    collector = MappingCollector()
    document_id = attr(first_descendant(root, "id"), "extension") or attr(first_descendant(root, "id"), "root")
    map_cda_patient(root, document_id, collector)
    map_cda_sections(root, document_id, collector)
    map_cda_entries(root, document_id, collector)
    mappings = collector.finalize()
    if not mappings:
        collector.warn("В CDA не найдено данных, которые можно сопоставить с CVD-анкетой")
    return import_result("cda-r2-semd", mappings, collector.warnings, len(list(root.iter())))


def map_cda_patient(root: ET.Element, document_id: str, collector: MappingCollector) -> None:
    patient_role = first_descendant(root, "patientRole")
    patient = first_descendant(patient_role, "patient") if patient_role is not None else None
    source = Source("CDA Patient", document_id, "Пациент CDA")
    if patient_role is not None:
        patient_id_node = first_descendant(patient_role, "id")
        collector.add("GENERAL_INFO.Patient_ID", attr(patient_id_node, "extension") or attr(patient_id_node, "root"), source)
    if patient is None:
        return
    name = first_descendant(patient, "name")
    if name is not None:
        full_name = clean_text(" ".join(text_content(child) for child in list(name)))
        collector.add("GENERAL_INFO.Full_name", full_name, source)
    gender_code = attr(first_descendant(patient, "administrativeGenderCode"), "code").upper()
    gender = {"M": "male", "F": "female", "UN": "unknown", "UNK": "unknown"}.get(gender_code)
    if gender:
        collector.add("GENERAL_INFO.Sex", gender, source)
    birth_value = attr(first_descendant(patient, "birthTime"), "value")
    age = age_from_date(birth_value)
    if age is not None:
        collector.add("GENERAL_INFO.Age", age, Source("CDA Patient", document_id, "Дата рождения", birth_value))


def map_cda_sections(root: ET.Element, document_id: str, collector: MappingCollector) -> None:
    for section in descendants(root, "section"):
        title = text_content(first_child(section, "title"))
        code_node = first_child(section, "code")
        label = title or attr(code_node, "displayName") or "Раздел CDA"
        text = clean_text(text_content(first_child(section, "text")))
        if not text:
            continue
        normalized = normalize_terms(label)
        path = report_path(label)
        source = Source("CDA Section", document_id, label)
        if path:
            collector.add(path, text, source, "section-text")
        elif contains_any(normalized, ("жалоб", "chief complaint", "complaint")):
            collector.add("COMPLAINTS.Main_complaint", text, source, "section-text")
        elif contains_any(normalized, ("лекар", "назначен", "medication", "therapy", "лечение")):
            collector.add("CURRENT_MEDICATIONS.Other_relevant_drugs", text, source, "section-text")
        elif contains_any(normalized, ("диагноз", "problem", "condition")):
            collector.warn(f"CDA-раздел '{label}' не импортирован как диагноз без структурированного кода МКБ-10")
        elif contains_any(normalized, ("операц", "процедур", "procedure")):
            path = procedure_path(text)
            if path:
                collector.add(path, text, source, "section-text")
            else:
                collector.warn(f"CDA-раздел '{label}' не имеет однозначной кардиологической процедуры")


def map_cda_entries(root: ET.Element, document_id: str, collector: MappingCollector) -> None:
    for observation in descendants(root, "observation"):
        code_node = first_child(observation, "code")
        code = attr(code_node, "code")
        label = attr(code_node, "displayName") or code or "CDA observation"
        effective = attr(first_child(observation, "effectiveTime"), "value")
        value_node = first_child(observation, "value")
        value_code = attr(value_node, "code").upper()
        value_display = attr(value_node, "displayName") or text_content(value_node)
        source = Source("CDA Observation", document_id, label, effective, attr(value_node, "unit"))

        if code in LOINC_PATHS:
            raw_value = attr(value_node, "value") or text_content(value_node)
            numeric = parse_number(raw_value)
            if numeric is not None:
                path, expected_unit = LOINC_PATHS[code]
                collector.add(path, numeric, source)
                if source.unit and expected_unit and normalize_unit(source.unit) != normalize_unit(expected_unit):
                    collector.warn(f"{label}: единица '{source.unit}' отличается от ожидаемой '{expected_unit}', проверьте значение")
        if ICD10_PATTERN.match(value_code):
            collector.add_condition(value_code, value_display or value_code, source)

    for substance in descendants(root, "substanceAdministration"):
        code_node = first_descendant(substance, "manufacturedMaterial")
        code_node = first_descendant(code_node, "code") if code_node is not None else None
        name = attr(code_node, "displayName") or text_content(code_node)
        if name:
            source = Source("CDA Medication", document_id, name)
            collector.add(medication_path(name), name, source, "keyword")

    for procedure in descendants(root, "procedure"):
        code_node = first_child(procedure, "code")
        name = attr(code_node, "displayName") or text_content(code_node)
        path = procedure_path(name)
        if path:
            collector.add(path, name, Source("CDA Procedure", document_id, name), "keyword")


def import_result(source_format: str, mappings: list[dict[str, Any]], warnings: list[str], source_records: int) -> dict[str, Any]:
    candidate: dict[str, dict[str, Any]] = {}
    for mapping in mappings:
        section, field = mapping["path"].split(".", 1)
        candidate.setdefault(section, {})[field] = mapping["value"]
    normalized, validation_errors = validate_and_normalize_patient_data(candidate)
    invalid_paths = {
        mapping["path"]
        for mapping in mappings
        if any(error.startswith(mapping["path"]) for error in validation_errors)
    }
    validated_mappings = []
    for mapping in mappings:
        if mapping["path"] in invalid_paths:
            continue
        section, field = mapping["path"].split(".", 1)
        item = dict(mapping)
        item["value"] = normalized[section][field]
        validated_mappings.append(item)
    merged_warnings = list(warnings)
    for error in validation_errors:
        message = f"Не импортировано: {error}"
        if message not in merged_warnings and len(merged_warnings) < MAX_WARNINGS:
            merged_warnings.append(message)

    return {
        "source_format": source_format,
        "mapping_version": IMPORT_MAPPING_VERSION,
        "mappings": validated_mappings,
        "warnings": merged_warnings,
        "summary": {
            "mapped_fields": len(validated_mappings),
            "warnings": len(merged_warnings),
            "source_records": source_records,
        },
    }


def report_path(value: str) -> str:
    text = normalize_terms(value)
    if contains_any(text, ("эхок", "эхо-к", "echocardi")):
        return ""
    routes = (
        (("холтер", "holter"), "ECG_AND_BP_MONITORING.Holter_ECG_summary"),
        (("смад", "abpm", "ambulatory blood pressure"), "ECG_AND_BP_MONITORING.ABPM_summary"),
        (("экг", "electrocard", "ecg"), "ECG_AND_BP_MONITORING.Resting_ECG_summary"),
        (("нагрузоч", "exercise test", "treadmill"), "FUNCTIONAL_TESTS.Exercise_test_summary"),
        (("коронарограф", "ктка", "ct coronary", "coronary angiograph"), "CORONARY_AND_VASCULAR_IMAGING.Coronary_angiography_or_CTCA"),
        (("аорт", "aorta"), "CORONARY_AND_VASCULAR_IMAGING.Aorta_CT_MR"),
        (("сонн", "carotid"), "CORONARY_AND_VASCULAR_IMAGING.Carotid_ultrasound"),
        (("узи вен", "venous ultrasound"), "CORONARY_AND_VASCULAR_IMAGING.Venous_ultrasound"),
        (("периферическ", "peripheral arter"), "CORONARY_AND_VASCULAR_IMAGING.Peripheral_artery_imaging"),
    )
    for terms, path in routes:
        if contains_any(text, terms):
            return path
    return ""


def medication_path(value: str) -> str:
    text = normalize_terms(value)
    routes = (
        (("аспирин", "ацетилсалиц", "clopidogrel", "клопидогрел", "ticagrelor", "тикагрелор", "prasugrel"), "CURRENT_MEDICATIONS.Antiplatelets"),
        (("warfarin", "варфарин", "apixaban", "апиксабан", "rivaroxaban", "ривароксабан", "dabigatran", "дабигатран", "heparin", "гепарин"), "CURRENT_MEDICATIONS.Anticoagulants"),
        (("metoprolol", "метопролол", "bisoprolol", "бисопролол", "carvedilol", "карведилол", "nebivolol", "небиволол"), "CURRENT_MEDICATIONS.Beta_blockers"),
        (("ramipril", "рамиприл", "enalapril", "эналаприл", "lisinopril", "лизиноприл", "perindopril", "периндоприл", "losartan", "лозартан", "valsartan", "валсартан", "sacubitril", "сакубитрил"), "CURRENT_MEDICATIONS.ACEi_ARB_ARNI"),
        (("spironolactone", "спиронолактон", "eplerenone", "эплеренон"), "CURRENT_MEDICATIONS.MRA"),
        (("dapagliflozin", "дапаглифлозин", "empagliflozin", "эмпаглифлозин"), "CURRENT_MEDICATIONS.SGLT2_inhibitors"),
        (("furosemide", "фуросемид", "torasemide", "торасемид", "indapamide", "индапамид", "hydrochlorothiazide"), "CURRENT_MEDICATIONS.Diuretics"),
        (("amiodarone", "амиодарон", "sotalol", "соталол", "propafenone", "пропафенон"), "CURRENT_MEDICATIONS.Antiarrhythmics"),
        (("statin", "статин", "atorvastatin", "аторвастатин", "rosuvastatin", "розувастатин", "ezetimibe", "эзетимиб"), "CURRENT_MEDICATIONS.Lipid_lowering"),
        (("metformin", "метформин", "insulin", "инсулин", "glimepiride", "глимепирид"), "CURRENT_MEDICATIONS.Antidiabetic_drugs"),
    )
    for terms, path in routes:
        if contains_any(text, terms):
            return path
    return "CURRENT_MEDICATIONS.Other_relevant_drugs"


def procedure_path(value: str) -> str:
    text = normalize_terms(value)
    routes = (
        (("стент", "pci", "percutaneous coronary"), "DEVICES_AND_PROCEDURES.Coronary_stents"),
        (("акш", "cabg", "coronary artery bypass"), "DEVICES_AND_PROCEDURES.CABG_details"),
        (("клапан", "valve replacement", "valve repair", "протезирован"), "DEVICES_AND_PROCEDURES.Valve_surgery_or_prosthesis"),
        (("кардиостимулятор", "pacemaker", "icd", "crt", "дефибриллятор"), "DEVICES_AND_PROCEDURES.Pacemaker_ICD_CRT"),
    )
    for terms, path in routes:
        if contains_any(text, terms):
            return path
    return ""


def fhir_value(node: dict[str, Any]) -> tuple[Any, str]:
    quantity = node.get("valueQuantity")
    if isinstance(quantity, dict):
        return parse_number(quantity.get("value")), str(quantity.get("unit") or quantity.get("code") or "")
    for key in ("valueInteger", "valueDecimal"):
        if key in node:
            return parse_number(node.get(key)), ""
    if "valueString" in node:
        return clean_text(node.get("valueString")), ""
    return None, ""


def concept_codes(concept: Any) -> list[str]:
    if not isinstance(concept, dict):
        return []
    return [
        str(item.get("code") or "").strip()
        for item in concept.get("coding") or []
        if isinstance(item, dict) and item.get("code")
    ]


def concept_text(concept: Any) -> str:
    if not isinstance(concept, dict):
        return ""
    if concept.get("text"):
        return clean_text(concept.get("text"))
    for item in concept.get("coding") or []:
        if isinstance(item, dict) and item.get("display"):
            return clean_text(item.get("display"))
    return ""


def resource_status_code(concept: Any) -> str:
    codes = concept_codes(concept)
    return codes[0] if codes else ""


def age_from_date(value: str) -> int | None:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    if len(digits) < 4:
        return None
    try:
        year = int(digits[:4])
        month = int(digits[4:6]) if len(digits) >= 6 else 1
        day = int(digits[6:8]) if len(digits) >= 8 else 1
        born = date(year, month, day)
    except ValueError:
        return None
    today = date.today()
    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    return age if 0 <= age <= 120 else None


def parse_number(value: Any) -> int | float | None:
    try:
        parsed = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return int(parsed) if parsed.is_integer() else parsed


def clean_text(value: Any, limit: int = MAX_TEXT_LENGTH) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def normalize_terms(value: str) -> str:
    return clean_text(value).lower().replace("ё", "е")


def normalize_unit(value: str) -> str:
    return re.sub(r"[^a-zа-я0-9%/]", "", str(value or "").lower().replace("μ", "u").replace("µ", "u"))


def contains_any(value: str, terms: tuple[str, ...]) -> bool:
    return any(term in value for term in terms)


def local_name(tag: str) -> str:
    return str(tag).split("}", 1)[-1]


def descendants(node: ET.Element | None, name: str) -> list[ET.Element]:
    if node is None:
        return []
    return [item for item in node.iter() if local_name(item.tag) == name]


def first_descendant(node: ET.Element | None, name: str) -> ET.Element | None:
    return next(iter(descendants(node, name)), None)


def first_child(node: ET.Element | None, name: str) -> ET.Element | None:
    if node is None:
        return None
    return next((child for child in list(node) if local_name(child.tag) == name), None)


def attr(node: ET.Element | None, name: str) -> str:
    return str(node.attrib.get(name) or "").strip() if node is not None else ""


def text_content(node: ET.Element | None) -> str:
    return clean_text(" ".join(node.itertext())) if node is not None else ""
