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

  // Ориентировочные референсные интервалы взрослых для подсказок при вводе.
  // Не заменяют локальные лабораторные референсы и клиническую оценку.
  const referenceRanges = {
    "GENERAL_INFO.BMI": {min: 18.5, max: 24.9, text: "18.5–24.9 кг/м²"},
    "PHYSICAL_EXAM.Blood_pressure_right_systolic_mmHg": {min: 90, max: 139, text: "90–139 мм рт. ст."},
    "PHYSICAL_EXAM.Blood_pressure_right_diastolic_mmHg": {min: 60, max: 89, text: "60–89 мм рт. ст."},
    "PHYSICAL_EXAM.Blood_pressure_left_systolic_mmHg": {min: 90, max: 139, text: "90–139 мм рт. ст."},
    "PHYSICAL_EXAM.Blood_pressure_left_diastolic_mmHg": {min: 60, max: 89, text: "60–89 мм рт. ст."},
    "PHYSICAL_EXAM.Heart_rate_bpm": {min: 60, max: 100, text: "60–100 уд/мин"},
    "PHYSICAL_EXAM.Resp_rate": {min: 12, max: 20, text: "12–20 в мин"},
    "PHYSICAL_EXAM.SpO2_room_air_percent": {min: 94, text: "≥ 94 %"},
    "LABS_CBC.Hb_g_L": {min: 120, max: 160, text: "120–160 г/л"},
    "LABS_CBC.WBC_10e9_L": {min: 4, max: 9, text: "4–9 ×10⁹/л"},
    "LABS_CBC.PLT_10e9_L": {min: 150, max: 400, text: "150–400 ×10⁹/л"},
    "LABS_BIOCHEM.Creatinine_umol_L": {min: 60, max: 110, text: "60–110 мкмоль/л"},
    "LABS_BIOCHEM.eGFR_ml_min_1_73m2": {min: 60, text: "≥ 60 мл/мин/1.73 м²"},
    "LABS_BIOCHEM.ALT_U_L": {max: 40, text: "≤ 40 Ед/л"},
    "LABS_BIOCHEM.AST_U_L": {max: 40, text: "≤ 40 Ед/л"},
    "LABS_BIOCHEM.Na_mmol_L": {min: 135, max: 145, text: "135–145 ммоль/л"},
    "LABS_BIOCHEM.K_mmol_L": {min: 3.5, max: 5.1, text: "3.5–5.1 ммоль/л"},
    "LABS_BIOCHEM.Mg_mmol_L": {min: 0.7, max: 1.05, text: "0.7–1.05 ммоль/л"},
    "LABS_BIOCHEM.Glucose_fasting_mmol_L": {min: 3.9, max: 5.6, text: "3.9–5.6 ммоль/л"},
    "LABS_BIOCHEM.HbA1c_percent": {max: 6.0, text: "≤ 6.0 %"},
    "LABS_LIPIDS.Total_cholesterol_mmol_L": {max: 5.0, text: "≤ 5.0 ммоль/л"},
    "LABS_LIPIDS.LDL_mmol_L": {max: 3.0, text: "≤ 3.0 ммоль/л"},
    "LABS_LIPIDS.HDL_mmol_L": {min: 1.0, text: "≥ 1.0 ммоль/л"},
    "LABS_LIPIDS.Triglycerides_mmol_L": {max: 1.7, text: "≤ 1.7 ммоль/л"},
    "LABS_CARDIAC_MARKERS.Troponin_ng_L": {max: 14, text: "≤ 14 нг/л"},
    "LABS_CARDIAC_MARKERS.NT_proBNP_pg_ml": {max: 125, text: "≤ 125 пг/мл"},
    "LABS_COAGULATION.INR": {min: 0.8, max: 1.2, text: "0.8–1.2 (без антикоагулянтов)"},
    "LABS_COAGULATION.APTT_sec": {min: 25, max: 35, text: "25–35 с"},
    "ECHOCARDIOGRAPHY.LVEF_percent": {min: 50, text: "≥ 50 %"},
    "ECHOCARDIOGRAPHY.PASP_mmHg": {max: 35, text: "≤ 35 мм рт. ст."}
  };

  function referenceStatus(path, rawValue) {
    const range = referenceRanges[path];
    if (!range) return null;
    const value = Number(rawValue);
    if (String(rawValue ?? "").trim() === "" || !Number.isFinite(value)) return {range, state: "empty"};
    if (range.min !== undefined && value < range.min) return {range, state: "below"};
    if (range.max !== undefined && value > range.max) return {range, state: "above"};
    return {range, state: "ok"};
  }

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
    referenceRanges,
    referenceStatus,
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
