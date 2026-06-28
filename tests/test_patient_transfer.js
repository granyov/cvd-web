"use strict";

const assert = require("node:assert/strict");

global.window = globalThis;
require("../cvd_web/static/js/patient-transfer.js");

const schema = [
  {
    key: "GENERAL_INFO",
    fields: [
      { key: "Patient_ID" },
      { key: "Full_name" },
      { key: "Age" }
    ]
  }
];
const patientData = {
  GENERAL_INFO: {
    Patient_ID: "CASE 001",
    Full_name: "Тестов Тест Тестович",
    Age: 64
  }
};

const exported = CVDPatientTransfer.createExport(patientData, {
  patientSchemaVersion: "test-schema-v1",
  exportedAt: "2026-06-27T00:00:00Z"
});
assert.equal(exported.format, "cvd-patient");
assert.equal(exported.format_version, 1);
assert.equal(exported.patient_schema_version, "test-schema-v1");
assert.deepEqual(exported.patient_data, patientData);
assert.equal(CVDPatientTransfer.exportFilename(patientData), "CASE_001.cvd.json");
assert.deepEqual(CVDPatientTransfer.extractImportedPatientData(exported, schema), patientData);
assert.deepEqual(CVDPatientTransfer.extractImportedPatientData(patientData, schema), patientData);
assert.equal(CVDPatientTransfer.classifyMapping({value: 148, source_conflict: false}, null), "new");
assert.equal(CVDPatientTransfer.classifyMapping({value: 148, source_conflict: false}, 148), "same");
assert.equal(CVDPatientTransfer.classifyMapping({value: 148, source_conflict: false}, 130), "conflict");
assert.equal(CVDPatientTransfer.classifyMapping({value: 148, source_conflict: true}, 130), "source-conflict");

assert.throws(
  () => CVDPatientTransfer.extractImportedPatientData({ UNKNOWN: { value: 1 } }, schema),
  /неизвестный раздел UNKNOWN/
);
assert.throws(
  () => CVDPatientTransfer.extractImportedPatientData({ format: "cvd-patient", format_version: 2 }, schema),
  /Версия файла импорта не поддерживается/
);

console.log("patient transfer tests: ok");
