from __future__ import annotations

import unittest

from cvd_web.integration_import import parse_cda_document, parse_cvd_document, parse_fhir_bundle


def mapped(result: dict) -> dict:
    return {item["path"]: item for item in result["mappings"]}


class IntegrationImportTests(unittest.TestCase):
    def test_native_cvd_mapping_excludes_model_output(self):
        result = parse_cvd_document({
            "format": "cvd-patient",
            "format_version": 1,
            "patient_data": {
                "GENERAL_INFO": {"Patient_ID": "CASE_44", "Full_name": "Тестовый Пациент"},
                "MODEL_OUTPUT": {"Final_model_diagnosis": "Не импортировать"},
            },
        })
        values = mapped(result)
        self.assertEqual(result["source_format"], "cvd-json")
        self.assertEqual(values["GENERAL_INFO.Patient_ID"]["value"], "CASE_44")
        self.assertNotIn("MODEL_OUTPUT.Final_model_diagnosis", values)

    def test_fhir_multiple_measurements_require_review(self):
        bundle = {
            "resourceType": "Bundle",
            "entry": [
                {"resource": {
                    "resourceType": "Observation",
                    "id": "hr-old",
                    "status": "final",
                    "effectiveDateTime": "2026-06-20T10:00:00+03:00",
                    "code": {"coding": [{"code": "8867-4", "display": "Heart rate"}]},
                    "valueQuantity": {"value": 72, "unit": "/min"},
                }},
                {"resource": {
                    "resourceType": "Observation",
                    "id": "hr-new",
                    "status": "final",
                    "effectiveDateTime": "2026-06-21T10:00:00+03:00",
                    "code": {"coding": [{"code": "8867-4", "display": "Heart rate"}]},
                    "valueQuantity": {"value": 96, "unit": "bpm"},
                }},
            ],
        }
        result = parse_fhir_bundle(bundle)
        heart_rate = mapped(result)["PHYSICAL_EXAM.Heart_rate_bpm"]
        self.assertEqual(heart_rate["value"], 96)
        self.assertTrue(heart_rate["source_conflict"])
        self.assertEqual(len(heart_rate["sources"]), 2)
        self.assertTrue(any("единица" in warning for warning in result["warnings"]))

    def test_fhir_out_of_range_value_is_not_imported(self):
        result = parse_fhir_bundle({
            "resourceType": "Bundle",
            "entry": [{"resource": {
                "resourceType": "Observation",
                "status": "final",
                "code": {"coding": [{"code": "59408-5", "display": "SpO2"}]},
                "valueQuantity": {"value": 140, "unit": "%"},
            }}],
        })
        self.assertNotIn("PHYSICAL_EXAM.SpO2_room_air_percent", mapped(result))
        self.assertTrue(any("выше допустимого максимума" in warning for warning in result["warnings"]))

    def test_fhir_r4_bundle_mapping(self):
        bundle = {
            "resourceType": "Bundle",
            "type": "collection",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Patient",
                        "id": "patient-1",
                        "identifier": [{"value": "EMIAS-1001"}],
                        "name": [{"text": "Тестов Тест Тестович"}],
                        "gender": "male",
                        "birthDate": "1980-01-02",
                    }
                },
                {
                    "resource": {
                        "resourceType": "Observation",
                        "id": "bp-1",
                        "status": "final",
                        "code": {"coding": [{"code": "85354-9", "display": "Blood pressure"}]},
                        "effectiveDateTime": "2026-06-20T10:00:00+03:00",
                        "component": [
                            {
                                "code": {"coding": [{"code": "8480-6", "display": "Systolic blood pressure"}]},
                                "valueQuantity": {"value": 148, "unit": "mmHg"},
                            },
                            {
                                "code": {"coding": [{"code": "8462-4", "display": "Diastolic blood pressure"}]},
                                "valueQuantity": {"value": 92, "unit": "mmHg"},
                            },
                        ],
                    }
                },
                {
                    "resource": {
                        "resourceType": "Observation",
                        "id": "lvef-1",
                        "status": "final",
                        "code": {"coding": [{"code": "33878-0", "display": "LVEF"}]},
                        "valueQuantity": {"value": 42, "unit": "%"},
                    }
                },
                {
                    "resource": {
                        "resourceType": "Condition",
                        "id": "condition-1",
                        "code": {
                            "text": "Гипертоническая болезнь",
                            "coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": "I10"}],
                        },
                    }
                },
                {
                    "resource": {
                        "resourceType": "MedicationStatement",
                        "id": "med-1",
                        "status": "active",
                        "medicationCodeableConcept": {"text": "Бисопролол"},
                        "dosage": [{"text": "5 мг утром"}],
                    }
                },
                {
                    "resource": {
                        "resourceType": "Procedure",
                        "id": "procedure-1",
                        "status": "completed",
                        "code": {"text": "АКШ"},
                    }
                },
                {
                    "resource": {
                        "resourceType": "DiagnosticReport",
                        "id": "report-1",
                        "status": "final",
                        "code": {"text": "ЭКГ покоя"},
                        "conclusion": "Синусовый ритм, ЧСС 68/мин.",
                    }
                },
            ],
        }

        result = parse_fhir_bundle(bundle)
        values = mapped(result)

        self.assertEqual(result["source_format"], "fhir-r4")
        self.assertEqual(values["GENERAL_INFO.Patient_ID"]["value"], "EMIAS-1001")
        self.assertEqual(values["GENERAL_INFO.Full_name"]["value"], "Тестов Тест Тестович")
        self.assertEqual(values["PHYSICAL_EXAM.Blood_pressure_right_systolic_mmHg"]["value"], 148)
        self.assertEqual(values["ECHOCARDIOGRAPHY.LVEF_percent"]["value"], 42)
        self.assertEqual(values["RISK_FACTORS.Hypertension"]["value"], "yes")
        self.assertEqual(values["FINAL_DIAGNOSES.ICD10_codes"]["value"], ["I10"])
        self.assertIn("Бисопролол", values["CURRENT_MEDICATIONS.Beta_blockers"]["value"])
        self.assertEqual(values["DEVICES_AND_PROCEDURES.CABG_details"]["value"], "АКШ")
        self.assertIn("Синусовый ритм", values["ECG_AND_BP_MONITORING.Resting_ECG_summary"]["value"])

    def test_cda_semd_mapping_and_entity_rejection(self):
        document = """<?xml version="1.0" encoding="UTF-8"?>
        <ClinicalDocument xmlns="urn:hl7-org:v3" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
          <id root="1.2.3" extension="SEMD-55"/>
          <recordTarget><patientRole>
            <id extension="EMIAS-2002"/>
            <patient>
              <name><family>Тестова</family><given>Мария</given><given>Ивановна</given></name>
              <administrativeGenderCode code="F"/>
              <birthTime value="19750115"/>
            </patient>
          </patientRole></recordTarget>
          <component><structuredBody>
            <component><section>
              <title>Жалобы</title>
              <text>Одышка при обычной физической нагрузке.</text>
            </section></component>
            <component><section>
              <title>ЭКГ покоя</title>
              <text>Фибрилляция предсердий, ЧСС 96/мин.</text>
              <entry><observation classCode="OBS" moodCode="EVN">
                <code code="8867-4" displayName="Heart rate"/>
                <value xsi:type="PQ" value="96" unit="/min"/>
              </observation></entry>
              <entry><observation classCode="OBS" moodCode="EVN">
                <code code="problem" displayName="Diagnosis"/>
                <value xsi:type="CD" code="I48.1" displayName="Фибрилляция предсердий"/>
              </observation></entry>
            </section></component>
            <component><section>
              <title>Лекарственные назначения</title>
              <text>Апиксабан 5 мг два раза в сутки.</text>
              <entry><substanceAdministration classCode="SBADM" moodCode="EVN">
                <consumable><manufacturedProduct><manufacturedMaterial>
                  <code displayName="Апиксабан"/>
                </manufacturedMaterial></manufacturedProduct></consumable>
              </substanceAdministration></entry>
            </section></component>
          </structuredBody></component>
        </ClinicalDocument>"""

        result = parse_cda_document(document)
        values = mapped(result)

        self.assertEqual(result["source_format"], "cda-r2-semd")
        self.assertEqual(values["GENERAL_INFO.Patient_ID"]["value"], "EMIAS-2002")
        self.assertEqual(values["GENERAL_INFO.Full_name"]["value"], "Тестова Мария Ивановна")
        self.assertEqual(values["GENERAL_INFO.Sex"]["value"], "female")
        self.assertEqual(values["PHYSICAL_EXAM.Heart_rate_bpm"]["value"], 96)
        self.assertEqual(values["FINAL_DIAGNOSES.ICD10_codes"]["value"], ["I48.1"])
        self.assertIn("Апиксабан", values["CURRENT_MEDICATIONS.Anticoagulants"]["value"])
        self.assertIn("Одышка", values["COMPLAINTS.Main_complaint"]["value"])

        with self.assertRaisesRegex(ValueError, "DTD или ENTITY"):
            parse_cda_document("<!DOCTYPE x [<!ENTITY x 'bad'>]><ClinicalDocument>&x;</ClinicalDocument>")


if __name__ == "__main__":
    unittest.main()
