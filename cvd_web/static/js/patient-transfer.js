(function (global) {
  "use strict";

  function safeFilenamePart(value) {
    return String(value || "")
      .trim()
      .replace(/[^\p{L}\p{N}._-]+/gu, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 80);
  }

  function createExport(patientData, options = {}) {
    return {
      format: "cvd-patient",
      format_version: 1,
      patient_schema_version: options.patientSchemaVersion || "unknown",
      exported_at: options.exportedAt || new Date().toISOString(),
      patient_data: patientData
    };
  }

  function exportFilename(patientData) {
    const general = patientData?.GENERAL_INFO || {};
    const base = safeFilenamePart(general.Patient_ID)
      || safeFilenamePart(general.Full_name)
      || "cvd_case";
    return `${base}.cvd.json`;
  }

  function extractImportedPatientData(payload, cvdSchema) {
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw new Error("JSON должен содержать объект с данными пациента");
    }

    let data = payload;
    if (payload.format === "cvd-patient") {
      if (payload.format_version !== 1) {
        throw new Error("Версия файла импорта не поддерживается");
      }
      data = payload.patient_data;
    }
    if (!data || typeof data !== "object" || Array.isArray(data)) {
      throw new Error("В файле отсутствует объект patient_data");
    }

    const schema = new Map(cvdSchema.map((section) => [
      section.key,
      new Set(section.fields.map((field) => field.key))
    ]));
    const errors = [];
    let recognizedFields = 0;

    Object.entries(data).forEach(([sectionKey, sectionData]) => {
      const knownFields = schema.get(sectionKey);
      if (!knownFields) {
        errors.push(`неизвестный раздел ${sectionKey}`);
        return;
      }
      if (!sectionData || typeof sectionData !== "object" || Array.isArray(sectionData)) {
        errors.push(`раздел ${sectionKey} должен быть объектом`);
        return;
      }
      Object.keys(sectionData).forEach((fieldKey) => {
        if (knownFields.has(fieldKey)) {
          recognizedFields++;
        } else {
          errors.push(`неизвестное поле ${sectionKey}.${fieldKey}`);
        }
      });
    });

    if (errors.length > 0) {
      const suffix = errors.length > 3 ? `; ещё ${errors.length - 3}` : "";
      throw new Error(`Импорт отклонён: ${errors.slice(0, 3).join("; ")}${suffix}`);
    }
    if (recognizedFields === 0) {
      throw new Error("В файле нет полей CVD-анкеты");
    }
    return data;
  }

  function isFilled(value) {
    return Array.isArray(value)
      ? value.length > 0
      : value !== null && value !== undefined && String(value).trim() !== "";
  }

  function classifyMapping(mapping, currentValue) {
    const same = (!isFilled(currentValue) && !isFilled(mapping.value))
      || JSON.stringify(currentValue) === JSON.stringify(mapping.value);
    if (mapping.source_conflict) return "source-conflict";
    if (same) return "same";
    if (isFilled(currentValue)) return "conflict";
    return "new";
  }

  global.CVDPatientTransfer = {
    createExport,
    exportFilename,
    extractImportedPatientData,
    classifyMapping
  };
})(window);
