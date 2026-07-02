const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const context = {
  window: {
    CVD_SCHEMA: [
      {key: "GENERAL_INFO", fields: [{key: "Patient_ID"}, {key: "Age"}, {key: "Sex"}]},
      {key: "COMPLAINTS", fields: [{key: "Main_complaint"}]},
      {key: "PHYSICAL_EXAM", fields: [{key: "Blood_pressure_right_systolic_mmHg"}, {key: "Heart_rate_bpm"}, {key: "SpO2_room_air_percent"}]},
      {key: "ECG_AND_BP_MONITORING", fields: [{key: "Resting_ECG_summary"}]},
      {key: "FINAL_DIAGNOSES", fields: [{key: "Main_cardiovascular_diagnosis_text"}]},
      {key: "MODEL_OUTPUT", fields: [{key: "Final_model_diagnosis"}]}
    ]
  }
};
vm.createContext(context);
vm.runInContext(fs.readFileSync("cvd_web/static/js/clinical-quality.js", "utf8"), context);

const rules = context.window.CVDClinicalQuality;
const data = {
  GENERAL_INFO: {Patient_ID: "JS-1", Age: 80, Sex: "female"},
  COMPLAINTS: {Main_complaint: "Боль в груди, одышка"},
  PHYSICAL_EXAM: {Blood_pressure_right_systolic_mmHg: 85, Heart_rate_bpm: 130, SpO2_room_air_percent: 88},
  ECG_AND_BP_MONITORING: {},
  ECHOCARDIOGRAPHY: {LVEF_percent: 33},
  FINAL_DIAGNOSES: {Main_cardiovascular_diagnosis_text: "ОКС?"},
  MODEL_OUTPUT: {Final_model_diagnosis: "old"}
};
const summary = rules.qualitySummary(data);
const titles = new Set(summary.signals.map((signal) => signal.title));
assert(titles.has("Боль в груди без ЭКГ"));
assert(titles.has("Низкая SpO2 + тахикардия"));
assert(summary.critical_signals >= 3);
const changedModel = {...data, MODEL_OUTPUT: {Final_model_diagnosis: "new"}};
assert.strictEqual(rules.dataFingerprint(data), rules.dataFingerprint(changedModel));
const changedClinical = {...data, GENERAL_INFO: {...data.GENERAL_INFO, Age: 81}};
assert.notStrictEqual(rules.dataFingerprint(data), rules.dataFingerprint(changedClinical));
assert.strictEqual(rules.hasClinicalInput({MODEL_OUTPUT: {Final_model_diagnosis: "old"}}), false);
assert.strictEqual(rules.hasClinicalInput({GENERAL_INFO: {Patient_ID: "JS-2"}}), true);
console.log("clinical-quality.js checks passed");
