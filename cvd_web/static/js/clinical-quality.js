(function () {
  "use strict";

  const requiredDataPoints = [
    ["GENERAL_INFO.Patient_ID", "ID случая"],
    ["GENERAL_INFO.Sex", "Пол"],
    ["GENERAL_INFO.Age", "Возраст"],
    ["COMPLAINTS.Main_complaint", "Основная жалоба"],
    ["PHYSICAL_EXAM.Blood_pressure_right_systolic_mmHg", "Систолическое АД"],
    ["PHYSICAL_EXAM.Heart_rate_bpm", "ЧСС"],
    ["ECG_AND_BP_MONITORING.Resting_ECG_summary", "ЭКГ покоя"],
    ["FINAL_DIAGNOSES.Main_cardiovascular_diagnosis_text", "Рабочий диагноз врача"]
  ];

  function getValue(data, path) {
    const [section, field] = String(path || "").split(".");
    return data?.[section]?.[field];
  }

  function isFilled(value) {
    return Array.isArray(value) ? value.length > 0 : value !== null && value !== undefined && String(value).trim() !== "";
  }

  function hasClinicalInput(data, schema = window.CVD_SCHEMA || []) {
    return schema.some((section) => section.key !== "MODEL_OUTPUT" &&
      (section.fields || []).some((field) => isFilled(data?.[section.key]?.[field.key])));
  }

  function numericValue(data, path) {
    const value = getValue(data, path);
    if (!isFilled(value)) return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function missingRequiredData(data) {
    return requiredDataPoints.filter(([path]) => !isFilled(getValue(data, path)));
  }

  function sectionFillPercent(section, data) {
    const total = section.fields.length || 1;
    const filled = section.fields.filter((field) => isFilled(data[section.key]?.[field.key])).length;
    return {filled, total, percent: Math.round((filled / total) * 100)};
  }

  function stableStringify(value) {
    if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
    if (value && typeof value === "object") {
      return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`).join(",")}}`;
    }
    return JSON.stringify(value);
  }

  function dataFingerprint(data) {
    const copy = {...(data || {})};
    delete copy.MODEL_OUTPUT;
    return stableStringify(copy);
  }

  function includesAny(text, tokens) {
    const normalized = String(text || "").toLowerCase();
    return tokens.some((token) => normalized.includes(token));
  }

  function clinicalSignals(data) {
    const signals = [];
    const add = (kind, title, text, category) => signals.push({kind, title, text, category});
    const age = numericValue(data, "GENERAL_INFO.Age");
    const systolic = numericValue(data, "PHYSICAL_EXAM.Blood_pressure_right_systolic_mmHg");
    const diastolic = numericValue(data, "PHYSICAL_EXAM.Blood_pressure_right_diastolic_mmHg");
    const heartRate = numericValue(data, "PHYSICAL_EXAM.Heart_rate_bpm");
    const spo2 = numericValue(data, "PHYSICAL_EXAM.SpO2_room_air_percent");
    const lvef = numericValue(data, "ECHOCARDIOGRAPHY.LVEF_percent");
    const troponin = numericValue(data, "LABS_CARDIAC_MARKERS.Troponin_ng_L");
    const complaint = getValue(data, "COMPLAINTS.Main_complaint");
    const ecg = getValue(data, "ECG_AND_BP_MONITORING.Resting_ECG_summary");
    const chestPain = includesAny(complaint, ["боль", "груд", "chest", "стенок"]);
    const dyspnea = includesAny(complaint, ["одыш", "dysp", "shortness"]);

    if (age !== null && age >= 75) add("warning", "Возраст 75+", "Проверьте гериатрический риск, коморбидность и переносимость терапии.", "Демография");
    if ((systolic !== null && systolic >= 180) || (diastolic !== null && diastolic >= 120)) add("critical", "Очень высокое АД", "АД ≥180/120 требует проверки корректности ввода и клинического контекста.", "Витальные");
    if (systolic !== null && systolic < 90) add("critical", "Систолическое АД < 90", "Возможна гемодинамическая нестабильность.", "Витальные");
    if (heartRate !== null && (heartRate < 50 || heartRate > 120)) add("warning", "ЧСС вне обычного диапазона", "Важный фактор для интерпретации симптомов и ЭКГ.", "Витальные");
    if (spo2 !== null && spo2 < 92) add("critical", "SpO2 < 92%", "Проверьте дыхательный статус и условия измерения.", "Витальные");
    if (lvef !== null && lvef < 40) add("warning", "ФВ ЛЖ < 40%", "Маркер структурного поражения и возможной сердечной недостаточности.", "ЭхоКГ");
    if (troponin !== null && troponin > 0) add("warning", "Тропонин указан", "Сверьте единицы, референсы и динамику.", "Лаборатория");
    if (chestPain && !isFilled(ecg)) add("critical", "Боль в груди без ЭКГ", "ЭКГ — ключевой контекст перед AI-анализом.", "Диагностика");
    if (dyspnea && lvef !== null && lvef < 40) add("warning", "Одышка + сниженная ФВ ЛЖ", "Проверьте признаки сердечной недостаточности.", "Комбинированный");
    if (spo2 !== null && spo2 < 92 && heartRate !== null && heartRate > 120) add("critical", "Низкая SpO2 + тахикардия", "Комбинация может указывать на высокий риск.", "Комбинированный");
    return signals;
  }

  function qualitySummary(data, schema = window.CVD_SCHEMA || []) {
    let total = 0;
    let filled = 0;
    schema.forEach((section) => (section.fields || []).forEach((field) => {
      total++;
      if (isFilled(data?.[section.key]?.[field.key])) filled++;
    }));
    const missing = missingRequiredData(data).map(([path, label]) => ({path, label}));
    const signals = clinicalSignals(data);
    return {
      completeness_percent: total ? Math.round((filled / total) * 100) : 0,
      readiness_percent: Math.round(((requiredDataPoints.length - missing.length) / requiredDataPoints.length) * 100),
      filled_fields: filled,
      total_fields: total,
      missing_required: missing,
      signals,
      critical_signals: signals.filter((signal) => ["critical", "error"].includes(signal.kind)).length
    };
  }

  window.CVDClinicalQuality = {
    requiredDataPoints,
    getValue,
    isFilled,
    hasClinicalInput,
    numericValue,
    missingRequiredData,
    sectionFillPercent,
    clinicalSignals,
    qualitySummary,
    dataFingerprint
  };
})();
