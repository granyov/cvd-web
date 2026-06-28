(function () {
  "use strict";

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const form = document.getElementById("caseForm");
  const jsonPreview = document.getElementById("jsonPreview");
  const modelPreview = document.getElementById("modelPreview");
  const modelStructured = document.getElementById("modelStructured");
  const saveStatus = document.getElementById("saveStatus");
  const modelStatus = document.getElementById("modelStatus");
  const casesList = document.getElementById("casesList");
  const requestsList = document.getElementById("requestsList");
  const icdSummary = document.getElementById("icdSummary");
  const filledMetric = document.getElementById("filledMetric");
  const readinessMetric = document.getElementById("readinessMetric");
  const icdMetric = document.getElementById("icdMetric");
  const requestMetric = document.getElementById("requestMetric");
  const patientSnapshot = document.getElementById("patientSnapshot");
  const readinessPanel = document.getElementById("readinessPanel");
  const signalsPanel = document.getElementById("signalsPanel");
  const passwordModal = document.getElementById("passwordModal");
  const passwordForm = document.getElementById("passwordForm");
  const passwordStrength = document.getElementById("passwordStrength");
  const reviewModal = document.getElementById("reviewModal");
  const reviewContent = document.getElementById("reviewContent");
  const confirmReviewButton = document.getElementById("confirmReviewButton");
  const requestReviewForm = document.getElementById("requestReviewForm");
  const reviewStatus = document.getElementById("reviewStatus");
  const caseTimeline = document.getElementById("caseTimeline");
  const importsList = document.getElementById("importsList");
  const importJsonInput = document.getElementById("importJsonInput");
  const importModal = document.getElementById("importModal");
  const importFileLabel = document.getElementById("importFileLabel");
  const importSummary = document.getElementById("importSummary");
  const importWarnings = document.getElementById("importWarnings");
  const importDiff = document.getElementById("importDiff");
  const importSelectionStatus = document.getElementById("importSelectionStatus");
  const correctedTextBlock = document.getElementById("correctedTextBlock");
  const correctedTextContent = document.getElementById("correctedTextContent");
  const structureTextModal = document.getElementById("structureTextModal");
  const structureTextForm = document.getElementById("structureTextForm");
  const structureTextInput = document.getElementById("structureTextInput");
  const structureTextStatus = document.getElementById("structureTextStatus");
  const minimumPasswordLength = 15;
  const maxImportBytes = 5 * 1024 * 1024;
  let currentCaseId = null;
  let currentModelRequestId = null;
  let pendingReviewAction = null;
  let pendingImport = null;

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

  function toast(message) {
    const node = document.createElement("div");
    node.className = "toast";
    node.textContent = message;
    document.body.appendChild(node);
    setTimeout(() => node.remove(), 3200);
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
        ...(options.headers || {})
      }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    return data;
  }

  function fieldPath(sectionKey, fieldKey) {
    return `${sectionKey}.${fieldKey}`;
  }

  function fieldId(sectionKey, fieldKey) {
    return fieldPath(sectionKey, fieldKey).replace(/[^a-zA-Z0-9_-]/g, "_");
  }

  function getValue(data, path) {
    const [section, field] = path.split(".");
    return data?.[section]?.[field];
  }

  function isFilled(value) {
    return Array.isArray(value) ? value.length > 0 : value !== null && value !== undefined && String(value).trim() !== "";
  }

  function displayValue(value, fallback = "не указано") {
    if (!isFilled(value)) return fallback;
    return Array.isArray(value) ? value.join("; ") : String(value);
  }

  function numericValue(data, path) {
    const value = getValue(data, path);
    if (!isFilled(value)) return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function renderField(section, field) {
    const wrapper = document.createElement("div");
    wrapper.className = field.type === "textarea" ? "field full" : "field";

    const id = fieldId(section.key, field.key);
    const label = document.createElement("label");
    label.htmlFor = id;
    label.textContent = field.label;

    let input;
    if (field.type === "textarea") {
      input = document.createElement("textarea");
    } else if (field.type === "select") {
      input = document.createElement("select");
      for (const [value, text] of field.options || []) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = text;
        input.appendChild(option);
      }
    } else {
      input = document.createElement("input");
      input.type = field.type || "text";
      if (field.step) input.step = field.step;
      if (field.min !== undefined) input.min = field.min;
      if (field.max !== undefined) input.max = field.max;
    }
    input.id = id;
    input.name = fieldPath(section.key, field.key);
    input.dataset.section = section.key;
    input.dataset.field = field.key;
    if (field.placeholder) input.placeholder = field.placeholder;

    wrapper.appendChild(label);
    wrapper.appendChild(input);
    return wrapper;
  }

  function renderForm() {
    form.innerHTML = "";
    window.CVD_SCHEMA.forEach((section, index) => {
      const details = document.createElement("details");
      details.className = "section";
      details.open = index < 3 || section.key === "FINAL_DIAGNOSES" || section.key === "MODEL_OUTPUT";

      const summary = document.createElement("summary");
      const title = document.createElement("span");
      title.textContent = section.title;
      summary.appendChild(title);

      const body = document.createElement("div");
      body.className = "section-body form-grid";
      section.fields.forEach((field) => body.appendChild(renderField(section, field)));

      details.appendChild(summary);
      details.appendChild(body);
      form.appendChild(details);
    });
  }

  function parseIcdString(value) {
    return String(value || "")
      .split(/[,;]+/)
      .map((item) => item.trim().toUpperCase())
      .filter(Boolean);
  }

  function collectData() {
    const result = {};
    window.CVD_SCHEMA.forEach((section) => {
      result[section.key] = {};
      section.fields.forEach((field) => {
        const input = form.elements[fieldPath(section.key, field.key)];
        let value = input ? String(input.value || "").trim() : "";
        if (value === "") {
          result[section.key][field.key] = null;
          return;
        }
        if (field.type === "number") {
          const parsed = Number(value.replace(",", "."));
          result[section.key][field.key] = Number.isFinite(parsed) ? parsed : null;
          return;
        }
        if (field.key.endsWith("ICD10_codes") || field.key === "Model_ICD10_codes") {
          result[section.key][field.key] = parseIcdString(value);
          return;
        }
        result[section.key][field.key] = value;
      });
    });
    return result;
  }

  function setFieldValue(path, value) {
    const input = form.elements[path];
    if (!input) return;
    if (value === null || value === undefined) {
      input.value = "";
    } else if (Array.isArray(value)) {
      input.value = value.join("; ");
    } else {
      input.value = value;
    }
  }

  function applyData(data) {
    window.CVD_SCHEMA.forEach((section) => {
      const sectionData = data[section.key] || {};
      section.fields.forEach((field) => {
        setFieldValue(fieldPath(section.key, field.key), sectionData[field.key]);
      });
    });
    updatePreview();
    saveStatus.textContent = currentCaseId ? `кейс #${currentCaseId}` : "не сохранено";
  }

  function calculateBMI() {
    const h = Number(form.elements["GENERAL_INFO.Height_cm"]?.value || 0);
    const w = Number(form.elements["GENERAL_INFO.Weight_kg"]?.value || 0);
    const bmiInput = form.elements["GENERAL_INFO.BMI"];
    if (h > 0 && w > 0 && bmiInput) {
      bmiInput.value = (w / Math.pow(h / 100, 2)).toFixed(1);
    }
  }

  function updateIcdComparison(data) {
    const trueCodes = new Set(data.FINAL_DIAGNOSES?.ICD10_codes || []);
    const modelCodes = new Set(data.MODEL_OUTPUT?.Model_ICD10_codes || []);
    if (trueCodes.size === 0 && modelCodes.size === 0) {
      icdSummary.textContent = "Коды МКБ-10 ещё не сравнивались.";
      return;
    }
    let matches = 0;
    let missed = 0;
    let extra = 0;
    trueCodes.forEach((code) => modelCodes.has(code) ? matches++ : missed++);
    modelCodes.forEach((code) => { if (!trueCodes.has(code)) extra++; });
    icdSummary.textContent = `Совпадений: ${matches}. Пропущено: ${missed}. Лишние: ${extra}.`;
  }

  function updatePreview() {
    const data = collectData();
    jsonPreview.textContent = JSON.stringify(data, null, 2);
    updateIcdComparison(data);
    updateMetrics(data);
    updateClinicalQuality(data);
    return data;
  }

  function updateMetrics(data) {
    let total = 0;
    let filled = 0;
    window.CVD_SCHEMA.forEach((section) => {
      section.fields.forEach((field) => {
        total++;
        const value = data[section.key]?.[field.key];
        if (Array.isArray(value) ? value.length > 0 : value !== null && value !== "") {
          filled++;
        }
      });
    });
    const percent = total ? Math.round((filled / total) * 100) : 0;
    if (filledMetric) filledMetric.textContent = `${percent}%`;
    const trueCodes = data.FINAL_DIAGNOSES?.ICD10_codes || [];
    const modelCodes = data.MODEL_OUTPUT?.Model_ICD10_codes || [];
    if (icdMetric) icdMetric.textContent = String(new Set([...trueCodes, ...modelCodes]).size);
  }

  function missingRequiredData(data) {
    return requiredDataPoints.filter(([path]) => !isFilled(getValue(data, path)));
  }

  function updateClinicalQuality(data) {
    renderPatientSnapshot(data);
    renderReadiness(data);
    renderSignals(data);
  }

  function renderPatientSnapshot(data) {
    if (!patientSnapshot) return;
    patientSnapshot.innerHTML = "";
    const systolic = getValue(data, "PHYSICAL_EXAM.Blood_pressure_right_systolic_mmHg");
    const diastolic = getValue(data, "PHYSICAL_EXAM.Blood_pressure_right_diastolic_mmHg");
    const bp = isFilled(systolic) || isFilled(diastolic) ? `${displayValue(systolic, "?")}/${displayValue(diastolic, "?")} мм рт.ст.` : null;
    const cards = [
      ["Пациент", displayValue(getValue(data, "GENERAL_INFO.Full_name"))],
      ["Случай", displayValue(getValue(data, "GENERAL_INFO.Patient_ID"))],
      ["Возраст / пол", `${displayValue(getValue(data, "GENERAL_INFO.Age"), "?")} лет · ${displayValue(getValue(data, "GENERAL_INFO.Sex"), "?")}`],
      ["АД / ЧСС", `${displayValue(bp)} · ${displayValue(getValue(data, "PHYSICAL_EXAM.Heart_rate_bpm"), "?")} уд/мин`],
      ["Диагноз врача", displayValue(getValue(data, "FINAL_DIAGNOSES.Main_cardiovascular_diagnosis_text"))]
    ];
    cards.forEach(([label, value]) => {
      const card = document.createElement("div");
      card.className = "clinical-card";
      const caption = document.createElement("span");
      caption.textContent = label;
      const strong = document.createElement("strong");
      strong.textContent = value;
      card.append(caption, strong);
      patientSnapshot.appendChild(card);
    });
  }

  function renderReadiness(data) {
    if (!readinessPanel) return;
    readinessPanel.innerHTML = "";
    const missing = missingRequiredData(data);
    const ready = requiredDataPoints.length - missing.length;
    const percent = Math.round((ready / requiredDataPoints.length) * 100);
    if (readinessMetric) readinessMetric.textContent = `${percent}%`;
    requiredDataPoints.forEach(([path, label]) => {
      const ok = isFilled(getValue(data, path));
      const row = document.createElement("div");
      row.className = `check-row ${ok ? "ok" : "warning"}`;
      const mark = document.createElement("span");
      mark.className = "check-mark";
      mark.textContent = ok ? "✓" : "!";
      const text = document.createElement("span");
      text.textContent = label;
      const state = document.createElement("small");
      state.textContent = ok ? "заполнено" : "нужно заполнить";
      row.append(mark, text, state);
      readinessPanel.appendChild(row);
    });
  }

  function renderSignals(data) {
    if (!signalsPanel) return;
    signalsPanel.innerHTML = "";
    const signals = [];
    const age = numericValue(data, "GENERAL_INFO.Age");
    const systolic = numericValue(data, "PHYSICAL_EXAM.Blood_pressure_right_systolic_mmHg");
    const diastolic = numericValue(data, "PHYSICAL_EXAM.Blood_pressure_right_diastolic_mmHg");
    const heartRate = numericValue(data, "PHYSICAL_EXAM.Heart_rate_bpm");
    const spo2 = numericValue(data, "PHYSICAL_EXAM.SpO2_room_air_percent");
    const lvef = numericValue(data, "ECHOCARDIOGRAPHY.LVEF_percent");
    const troponin = numericValue(data, "LABS_CARDIAC_MARKERS.Troponin_ng_L");

    if (age !== null && age >= 75) signals.push(["warning", "Возраст 75+", "проверьте гериатрический риск и сопутствующие факторы"]);
    if ((systolic !== null && systolic >= 180) || (diastolic !== null && diastolic >= 120)) signals.push(["error", "Очень высокое АД", "проверьте корректность ввода и клинический контекст"]);
    if (heartRate !== null && (heartRate < 50 || heartRate > 120)) signals.push(["warning", "ЧСС вне обычного диапазона", "важно для интерпретации симптомов и ЭКГ"]);
    if (spo2 !== null && spo2 < 92) signals.push(["error", "SpO2 < 92%", "проверьте дыхательный статус и условия измерения"]);
    if (lvef !== null && lvef < 40) signals.push(["warning", "ФВ ЛЖ < 40%", "важный маркер структурного поражения"]);
    if (troponin !== null && troponin > 0) signals.push(["warning", "Тропонин указан", "сверьте единицы, динамику и референсы лаборатории"]);

    if (signals.length === 0) {
      const row = document.createElement("div");
      row.className = "check-row";
      row.textContent = "Явных сигналов по заполненным числовым данным нет.";
      signalsPanel.appendChild(row);
      return;
    }

    signals.forEach(([kind, title, text]) => {
      const row = document.createElement("div");
      row.className = `signal-row ${kind}`;
      const strong = document.createElement("strong");
      strong.textContent = title;
      const small = document.createElement("small");
      small.textContent = text;
      row.append(strong, small);
      signalsPanel.appendChild(row);
    });
  }

  async function saveCase() {
    const data = updatePreview();
    const response = await api("/api/cases", {
      method: "POST",
      body: JSON.stringify({
        case_id: currentCaseId,
        patient_data: data
      })
    });
    currentCaseId = response.case_id;
    saveStatus.textContent = `кейс #${currentCaseId} сохранён`;
    toast("Кейс сохранён");
    await loadHistory();
  }

  function fillModelOutput(parsed) {
    const modelOutput = parsed?.MODEL_OUTPUT || parsed;
    if (!modelOutput || typeof modelOutput !== "object") return;
    for (const [key, value] of Object.entries(modelOutput)) {
      setFieldValue(`MODEL_OUTPUT.${key}`, value);
    }
    updatePreview();
  }

  function renderModelOutput(parsed, meta = {}) {
    if (!modelStructured) return;
    modelStructured.innerHTML = "";
    const cds = parsed?.CDS_OUTPUT;
    if (!cds || typeof cds !== "object") {
      modelStructured.textContent = "Структурированный CDS-ответ отсутствует.";
      return;
    }
    const summary = document.createElement("div");
    summary.className = "model-summary-card";
    const title = document.createElement("strong");
    title.textContent = cds.model_should_abstain ? "Модель воздержалась от заключения" : "Сводка модели";
    const text = document.createElement("p");
    text.textContent = cds.summary || "Сводка не указана.";
    summary.append(title, text);
    if (meta.prompt_version || meta.output_schema_version || meta.completion_tokens) {
      const version = document.createElement("small");
      version.textContent = [
        meta.prompt_version,
        meta.output_schema_version,
        meta.completion_tokens ? `${meta.completion_tokens} output tokens` : "",
        Number(meta.tokens_per_second) > 0 ? `${Number(meta.tokens_per_second).toFixed(1)} tok/s` : "",
        meta.finish_reason ? `finish: ${meta.finish_reason}` : ""
      ].filter(Boolean).join(" · ");
      summary.appendChild(version);
    }
    modelStructured.appendChild(summary);

    const diagnoses = Array.isArray(cds.possible_diagnoses) ? cds.possible_diagnoses : [];
    if (diagnoses.length > 0) {
      const section = document.createElement("div");
      section.className = "model-section";
      const heading = document.createElement("h3");
      heading.textContent = "Возможные диагнозы";
      section.appendChild(heading);
      diagnoses.forEach((diagnosis) => section.appendChild(renderDiagnosisCard(diagnosis)));
      modelStructured.appendChild(section);
    }

    modelStructured.appendChild(renderModelList("Red flags", cds.red_flags, "Нет явных red flags в ответе модели."));
    modelStructured.appendChild(renderModelList("Недостающие данные", cds.missing_data, "Модель не указала недостающие данные."));
    modelStructured.appendChild(renderModelList("Что ещё собрать", cds.recommended_next_data, "Дополнительные данные не указаны."));
    modelStructured.appendChild(renderModelList("Ограничения", cds.limitations, "Ограничения не указаны."));
  }

  function renderDiagnosisCard(diagnosis) {
    const card = document.createElement("div");
    card.className = "diagnosis-card";
    const header = document.createElement("div");
    header.className = "diagnosis-card-header";
    const name = document.createElement("strong");
    name.textContent = diagnosis.name || "Диагноз без названия";
    const confidence = document.createElement("span");
    confidence.className = `pill ${diagnosis.confidence === "high" ? "ok" : diagnosis.confidence === "low" ? "warning" : ""}`;
    confidence.textContent = diagnosis.confidence || "unknown";
    header.append(name, confidence);
    card.appendChild(header);
    const codes = document.createElement("small");
    codes.textContent = (diagnosis.icd10_codes || []).join("; ") || "МКБ-10 не указаны";
    card.appendChild(codes);
    card.appendChild(renderInlineList("За", diagnosis.supporting_findings));
    card.appendChild(renderInlineList("Против", diagnosis.against_findings));
    card.appendChild(renderInlineList("Не хватает", diagnosis.missing_data));
    return card;
  }

  function renderInlineList(label, items) {
    const wrapper = document.createElement("div");
    wrapper.className = "inline-evidence";
    const title = document.createElement("span");
    title.textContent = `${label}:`;
    const text = document.createElement("small");
    text.textContent = Array.isArray(items) && items.length ? items.join("; ") : "нет";
    wrapper.append(title, text);
    return wrapper;
  }

  function renderModelList(title, items, emptyText) {
    const section = document.createElement("div");
    section.className = "model-section";
    const heading = document.createElement("h3");
    heading.textContent = title;
    const list = document.createElement("div");
    list.className = "quality-list";
    const values = Array.isArray(items) ? items.filter(Boolean) : [];
    if (values.length === 0) {
      const row = document.createElement("div");
      row.className = "check-row";
      row.textContent = emptyText;
      list.appendChild(row);
    } else {
      values.forEach((item) => {
        const row = document.createElement("div");
        row.className = "check-row";
        row.textContent = item;
        list.appendChild(row);
      });
    }
    section.append(heading, list);
    return section;
  }

  function showReviewForm(requestId, review = null) {
    currentModelRequestId = requestId;
    if (!requestReviewForm) return;
    requestReviewForm.classList.toggle("hidden", !requestId);
    if (!requestId) return;
    requestReviewForm.rating.value = review?.rating || "useful";
    requestReviewForm.issue_types.value = (review?.issue_types || []).join("; ");
    requestReviewForm.corrected_diagnosis.value = review?.corrected_diagnosis || "";
    requestReviewForm.corrected_icd10.value = (review?.corrected_icd10 || []).join("; ");
    requestReviewForm.comment.value = review?.comment || "";
    reviewStatus.textContent = review ? `оценено: ${review.rating}` : "не оценено";
    reviewStatus.className = `pill ${review ? "ok" : ""}`;
  }

  async function saveRequestReview(event) {
    event.preventDefault();
    if (!currentModelRequestId) {
      toast("Сначала выберите ответ модели");
      return;
    }
    const payload = {
      rating: requestReviewForm.rating.value,
      issue_types: parseIcdString(requestReviewForm.issue_types.value).map((item) => item.toLowerCase()),
      corrected_diagnosis: requestReviewForm.corrected_diagnosis.value,
      corrected_icd10: parseIcdString(requestReviewForm.corrected_icd10.value),
      comment: requestReviewForm.comment.value
    };
    await api(`/api/requests/${currentModelRequestId}/review`, {
      method: "POST",
      body: JSON.stringify(payload)
    });
    reviewStatus.textContent = `оценено: ${payload.rating}`;
    reviewStatus.className = "pill ok";
    toast("Оценка сохранена");
    await loadHistory();
  }

  function diagnose() {
    const patientData = updatePreview();
    openReviewModal(() => runDiagnose(patientData), true);
  }

  async function runDiagnose(patientData) {
    const button = document.getElementById("diagnoseButton");
    button.disabled = true;
    modelStatus.textContent = "запрос выполняется";
    modelStatus.className = "pill warning";
    modelPreview.textContent = "Ожидание ответа LM Studio...";
    try {
      const response = await api("/api/model/diagnose", {
        method: "POST",
        body: JSON.stringify({
          case_id: currentCaseId,
          patient_data: patientData
        })
      });
      modelPreview.textContent = JSON.stringify(response.parsed || response.response, null, 2);
      fillModelOutput(response.parsed);
      renderModelOutput(response.parsed, response);
      showReviewForm(response.request_id, null);
      const seconds = (Number(response.duration_ms || 0) / 1000).toFixed(1);
      const speed = Number(response.tokens_per_second) > 0 ? ` · ${Number(response.tokens_per_second).toFixed(1)} tok/s` : "";
      modelStatus.textContent = `ответ получен за ${seconds} с${speed}`;
      modelStatus.className = "pill ok";
      toast("Ответ модели получен");
      await loadHistory();
    } catch (err) {
      modelPreview.textContent = err.message;
      modelStatus.textContent = "ошибка модели";
      modelStatus.className = "pill error";
      toast(err.message);
    } finally {
      button.disabled = false;
    }
  }

  async function loadHistory() {
    const [casesResponse, requestsResponse, importsResponse] = await Promise.all([
      api("/api/cases"),
      api("/api/requests"),
      api("/api/imports")
    ]);
    window.__lastCases = casesResponse.cases || [];
    window.__lastRequests = requestsResponse.requests || [];
    window.__lastImports = importsResponse.imports || [];
    renderCases(window.__lastCases);
    renderRequests(window.__lastRequests);
    renderImports(window.__lastImports);
    renderTimeline(window.__lastCases, window.__lastRequests, window.__lastImports);
  }

  function renderCases(items) {
    casesList.innerHTML = "";
    if (items.length === 0) {
      casesList.textContent = "Сохранённых кейсов пока нет.";
      return;
    }
    items.forEach((item) => {
      const div = document.createElement("div");
      div.className = "history-item";
      const title = document.createElement("strong");
      title.textContent = item.title;
      const meta = document.createElement("span");
      meta.className = "muted";
      meta.textContent = `#${item.id} · ${item.updated_at}`;
      const load = document.createElement("button");
      load.type = "button";
      load.textContent = "Открыть";
      load.addEventListener("click", () => openCase(item.id).catch((err) => toast(err.message)));
      const fhir = document.createElement("button");
      fhir.type = "button";
      fhir.textContent = "FHIR";
      fhir.addEventListener("click", () => downloadFHIR(item.id).catch((err) => toast(err.message)));
      const actions = document.createElement("div");
      actions.className = "toolbar";
      actions.append(load, fhir);
      div.append(title, meta, document.createElement("br"), actions);
      casesList.appendChild(div);
    });
  }

  async function openCase(caseId) {
    const response = await api(`/api/cases/${caseId}`);
    currentCaseId = response.case.id;
    applyData(response.case.data);
    renderTimeline(window.__lastCases || [], window.__lastRequests || [], window.__lastImports || []);
    toast("Кейс загружен");
  }

  function renderRequests(items) {
    if (requestMetric) requestMetric.textContent = String(items.length);
    requestsList.innerHTML = "";
    if (items.length === 0) {
      requestsList.textContent = "Запросов к модели пока нет.";
      return;
    }
    items.forEach((item) => {
      const div = document.createElement("div");
      div.className = "history-item";
      const status = item.status === "success" ? "ok" : "error";
      const diagnosis = item.parsed_output?.CDS_OUTPUT?.summary || item.parsed_output?.MODEL_OUTPUT?.Final_model_diagnosis || item.error || "без текста";
      div.innerHTML = "";
      const title = document.createElement("strong");
      title.textContent = `#${item.id} · ${item.model}`;
      const pill = document.createElement("span");
      pill.className = `pill ${status}`;
      pill.textContent = item.status;
      const text = document.createElement("p");
      text.textContent = diagnosis;
      const meta = document.createElement("span");
      meta.className = "muted";
      const seconds = (Number(item.duration_ms || 0) / 1000).toFixed(1);
      const tokens = item.completion_tokens ? ` · ${item.completion_tokens} tokens` : "";
      const speed = Number(item.tokens_per_second) > 0 ? ` · ${Number(item.tokens_per_second).toFixed(1)} tok/s` : "";
      meta.textContent = `${item.created_at} · ${seconds} с${tokens}${speed}`;
      const open = document.createElement("button");
      open.type = "button";
      open.textContent = item.review ? "Открыть оценку" : "Оценить";
      open.addEventListener("click", () => openRequestResult(item));
      div.append(title, pill, text, meta, document.createElement("br"), open);
      requestsList.appendChild(div);
    });
  }

  function openRequestResult(item) {
    document.querySelectorAll(".tab").forEach((button) => {
      button.classList.toggle("active", button.dataset.tab === "model");
    });
    ["quality", "json", "model", "history"].forEach((name) => {
      document.getElementById(`tab-${name}`).classList.toggle("hidden", name !== "model");
    });
    currentModelRequestId = item.id;
    modelStatus.textContent = item.status === "success" ? "ответ из истории" : "ошибка из истории";
    modelStatus.className = `pill ${item.status === "success" ? "ok" : "error"}`;
    modelPreview.textContent = JSON.stringify(item.parsed_output || { error: item.error }, null, 2);
    renderModelOutput(item.parsed_output || {}, item);
    showReviewForm(item.id, item.review);
  }

  function renderImports(items) {
    if (!importsList) return;
    importsList.innerHTML = "";
    if (items.length === 0) {
      importsList.textContent = "Импортов пока нет.";
      return;
    }
    items.forEach((item) => {
      const div = document.createElement("div");
      div.className = "history-item";
      const title = document.createElement("strong");
      title.textContent = item.filename || `Импорт #${item.id}`;
      const pill = document.createElement("span");
      pill.className = `pill ${item.status === "applied" ? "ok" : "warning"}`;
      pill.textContent = item.status === "applied" ? "применён" : "просмотрен";
      const meta = document.createElement("span");
      meta.className = "muted";
      meta.textContent = `${item.source_format} · полей ${item.mapped_fields} · предупреждений ${item.warning_count} · ${item.created_at}`;
      div.append(title, pill, document.createElement("br"), meta);
      importsList.appendChild(div);
    });
  }

  function renderTimeline(cases, requests, imports = []) {
    if (!caseTimeline) return;
    caseTimeline.innerHTML = "";
    const events = [];
    cases.forEach((item) => {
      if (!currentCaseId || item.id === currentCaseId) {
        events.push({ when: item.updated_at, type: "case", text: `Кейс #${item.id}: ${item.title}` });
      }
    });
    requests.forEach((item) => {
      if (!currentCaseId || item.case_id === currentCaseId) {
        events.push({ when: item.created_at, type: item.status, text: `Модель ${item.model}: ${item.status}` });
      }
    });
    imports.forEach((item) => {
      if (!currentCaseId || item.case_id === currentCaseId) {
        events.push({
          when: item.applied_at || item.created_at,
          type: item.status === "applied" ? "case" : "warning",
          text: `Импорт ${item.source_format}: ${item.status === "applied" ? "применён" : "просмотрен"}`
        });
      }
    });
    events.sort((a, b) => String(b.when).localeCompare(String(a.when)));
    if (events.length === 0) {
      caseTimeline.textContent = currentCaseId ? "По этому кейсу пока нет событий." : "Откройте кейс, чтобы увидеть его таймлайн.";
      return;
    }
    events.slice(0, 8).forEach((event) => {
      const row = document.createElement("div");
      row.className = `timeline-item ${event.type}`;
      const mark = document.createElement("span");
      mark.className = "timeline-dot";
      const text = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = event.text;
      const meta = document.createElement("small");
      meta.textContent = event.when;
      text.append(title, meta);
      row.append(mark, text);
      caseTimeline.appendChild(row);
    });
  }

  function downloadJson() {
    const data = updatePreview();
    const exported = window.CVDPatientTransfer.createExport(data, {
      patientSchemaVersion: window.CVD_PATIENT_SCHEMA_VERSION || "unknown"
    });
    const filename = window.CVDPatientTransfer.exportFilename(data);
    const blob = new Blob([JSON.stringify(exported, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast("Данные экспортированы");
  }

  function importFieldMeta(path) {
    const [sectionKey, fieldKey] = String(path).split(".");
    const section = window.CVD_SCHEMA.find((item) => item.key === sectionKey);
    const field = section?.fields.find((item) => item.key === fieldKey);
    return {
      section: section?.title || sectionKey,
      label: field?.label || fieldKey
    };
  }

  function importValueText(value, fallback = "пусто") {
    if (!isFilled(value)) return fallback;
    if (Array.isArray(value)) return value.join("; ");
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }

  function importSourceText(mapping) {
    const sources = Array.isArray(mapping.sources) ? mapping.sources : [];
    return sources.map((source) => {
      const name = source.label || source.resource_type || "Источник";
      const details = [source.date, source.unit].filter(Boolean).join(" · ");
      return details ? `${name} · ${details}` : name;
    }).join("\n") || "Локальный файл CVD";
  }

  async function importJson(file) {
    if (!file) return;
    if (file.size > maxImportBytes) {
      throw new Error("Файл больше 5 МБ");
    }
    const text = await file.text();
    let preview;
    if (text.trimStart().startsWith("<")) {
      preview = await api("/api/import/preview", {
        method: "POST",
        body: JSON.stringify({source_format: "cda", filename: file.name, payload: text})
      });
    } else {
      let payload;
      try {
        payload = JSON.parse(text);
      } catch (_error) {
        throw new Error("Файл не является корректным JSON или CDA XML");
      }
      if (payload?.resourceType === "Bundle") {
        preview = await api("/api/import/preview", {
          method: "POST",
          body: JSON.stringify({source_format: "fhir", filename: file.name, payload})
        });
      } else {
        preview = await api("/api/import/preview", {
          method: "POST",
          body: JSON.stringify({source_format: "cvd", filename: file.name, payload})
        });
      }
    }
    openImportPreview(preview);
  }

  function appendImportMetric(value, label) {
    const card = document.createElement("div");
    const strong = document.createElement("strong");
    strong.textContent = String(value);
    const caption = document.createElement("span");
    caption.textContent = label;
    card.append(strong, caption);
    importSummary.appendChild(card);
  }

  function openImportPreview(preview) {
    const currentData = collectData();
    const rows = (preview.mappings || []).map((mapping) => {
      const currentValue = getValue(currentData, mapping.path);
      const state = window.CVDPatientTransfer.classifyMapping(mapping, currentValue);
      return {mapping, currentValue, state, checkbox: null};
    });
    pendingImport = {preview, rows};

    const counts = rows.reduce((result, row) => {
      result[row.state] = (result[row.state] || 0) + 1;
      return result;
    }, {});
    importFileLabel.textContent = [
      preview.filename || "Файл",
      preview.source_format || "неизвестный формат",
      preview.mapping_version || ""
    ].filter(Boolean).join(" · ");
    importSummary.innerHTML = "";
    appendImportMetric(rows.length, "сопоставлено");
    appendImportMetric(counts.new || 0, "новых полей");
    appendImportMetric((counts.conflict || 0) + (counts["source-conflict"] || 0), "конфликтов");
    appendImportMetric((preview.warnings || []).length, "предупреждений");

    const correctedText = String(preview.corrected_text || "").trim();
    correctedTextBlock.classList.toggle("hidden", !correctedText);
    correctedTextContent.textContent = correctedText;

    const warnings = preview.warnings || [];
    importWarnings.classList.toggle("hidden", warnings.length === 0);
    importWarnings.textContent = warnings.length ? warnings.slice(0, 8).map((item) => `• ${item}`).join("\n") : "";
    renderImportDiff();
    importModal.classList.remove("hidden");
  }

  function renderImportDiff() {
    importDiff.innerHTML = "";
    const header = document.createElement("div");
    header.className = "import-diff-row header";
    ["", "Поле", "Сейчас", "Новое значение", "Источник"].forEach((value) => {
      const cell = document.createElement("div");
      cell.className = "import-diff-cell";
      cell.textContent = value;
      header.appendChild(cell);
    });
    importDiff.appendChild(header);

    pendingImport.rows.forEach((row) => {
      const meta = importFieldMeta(row.mapping.path);
      const line = document.createElement("div");
      line.className = `import-diff-row ${row.state}`;

      const selectCell = document.createElement("div");
      selectCell.className = "import-diff-cell select";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = row.state === "new";
      checkbox.disabled = row.state === "same";
      checkbox.setAttribute("aria-label", `Импортировать ${meta.label}`);
      checkbox.addEventListener("change", updateImportSelection);
      row.checkbox = checkbox;
      selectCell.appendChild(checkbox);

      const fieldCell = document.createElement("div");
      fieldCell.className = "import-diff-cell";
      const fieldLabel = document.createElement("strong");
      fieldLabel.textContent = meta.label;
      const sectionLabel = document.createElement("small");
      sectionLabel.textContent = meta.section;
      const state = document.createElement("span");
      const stateConfig = {
        new: ["новое", "ok"],
        conflict: ["конфликт", "warning"],
        "source-conflict": ["несколько значений", "error"],
        same: ["совпадает", "ok"]
      }[row.state];
      state.className = `pill ${stateConfig[1]}`;
      state.textContent = stateConfig[0];
      fieldCell.append(fieldLabel, sectionLabel, state);

      const currentCell = document.createElement("div");
      currentCell.className = "import-diff-cell";
      currentCell.textContent = importValueText(row.currentValue);
      const importedCell = document.createElement("div");
      importedCell.className = "import-diff-cell";
      importedCell.textContent = importValueText(row.mapping.value);
      const sourceCell = document.createElement("div");
      sourceCell.className = "import-diff-cell";
      sourceCell.textContent = importSourceText(row.mapping);
      const confidence = document.createElement("small");
      confidence.textContent = `маппинг: ${row.mapping.confidence || "не указано"}`;
      sourceCell.appendChild(confidence);

      line.append(selectCell, fieldCell, currentCell, importedCell, sourceCell);
      importDiff.appendChild(line);
    });
    updateImportSelection();
  }

  function updateImportSelection() {
    const selected = pendingImport?.rows.filter((row) => row.checkbox?.checked).length || 0;
    importSelectionStatus.textContent = `выбрано: ${selected}`;
    document.getElementById("applyImportButton").disabled = selected === 0;
  }

  function selectNewImportFields() {
    pendingImport?.rows.forEach((row) => {
      if (row.checkbox && !row.checkbox.disabled) row.checkbox.checked = row.state === "new";
    });
    updateImportSelection();
  }

  function clearImportSelection() {
    pendingImport?.rows.forEach((row) => {
      if (row.checkbox && !row.checkbox.disabled) row.checkbox.checked = false;
    });
    updateImportSelection();
  }

  function closeImportModal() {
    importModal.classList.add("hidden");
    correctedTextBlock.classList.add("hidden");
    correctedTextContent.textContent = "";
    pendingImport = null;
  }

  function openStructureTextModal() {
    structureTextStatus.textContent = "ожидание";
    structureTextStatus.className = "pill";
    structureTextModal.classList.remove("hidden");
    structureTextInput.focus();
  }

  function closeStructureTextModal() {
    structureTextModal.classList.add("hidden");
  }

  function updateStructureTextCounter() {
    document.getElementById("structureTextCounter").textContent = `${structureTextInput.value.length} / 30000`;
  }

  async function structureText(event) {
    event.preventDefault();
    const text = structureTextInput.value.trim();
    if (text.length < 10) {
      toast("Добавьте медицинский текст длиной не менее 10 символов");
      return;
    }
    const button = document.getElementById("submitStructureTextButton");
    button.disabled = true;
    structureTextStatus.textContent = "MedGemma обрабатывает текст...";
    structureTextStatus.className = "pill warning";
    try {
      const preview = await api("/api/model/structure-text", {
        method: "POST",
        body: JSON.stringify({text})
      });
      structureTextStatus.textContent = `готово · ${preview.mappings?.length || 0} полей`;
      structureTextStatus.className = "pill ok";
      closeStructureTextModal();
      openImportPreview(preview);
    } catch (error) {
      structureTextStatus.textContent = "ошибка обработки";
      structureTextStatus.className = "pill error";
      throw error;
    } finally {
      button.disabled = false;
    }
  }

  async function copyCorrectedText() {
    const text = correctedTextContent.textContent || "";
    if (!text) return;
    await navigator.clipboard.writeText(text);
    toast("Исправленный текст скопирован");
  }

  async function applyPendingImport() {
    if (!pendingImport) return;
    const selected = pendingImport.rows.filter((row) => row.checkbox?.checked);
    if (selected.length === 0) return;
    const button = document.getElementById("applyImportButton");
    button.disabled = true;
    try {
      const importId = pendingImport.preview.import_id;
      if (importId) {
        await api(`/api/imports/${importId}/applied`, {
          method: "POST",
          body: JSON.stringify({
            case_id: currentCaseId,
            selected_paths: selected.map((row) => row.mapping.path)
          })
        });
      }
      resetModelState(true);
      selected.forEach((row) => setFieldValue(row.mapping.path, row.mapping.value));
      updatePreview();
      saveStatus.textContent = currentCaseId ? `кейс #${currentCaseId} изменён импортом` : "импортировано · не сохранено";
      closeImportModal();
      toast(`Импортировано полей: ${selected.length}`);
      await loadHistory();
    } finally {
      button.disabled = false;
    }
  }

  async function downloadFHIR(caseId = currentCaseId) {
    if (!caseId) {
      toast("Сначала сохраните кейс");
      return;
    }
    const response = await fetch(`/api/cases/${caseId}/fhir`, {
      headers: { "X-CSRF-Token": csrfToken }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/fhir+json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `cvd_case_${caseId}_fhir.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function openReviewModal(action, aiMode = false) {
    const data = updatePreview();
    pendingReviewAction = action || null;
    confirmReviewButton.classList.toggle("hidden", !aiMode);
    renderReviewContent(data);
    reviewModal.classList.remove("hidden");
  }

  function closeReviewModal() {
    reviewModal.classList.add("hidden");
    pendingReviewAction = null;
  }

  function renderReviewContent(data) {
    reviewContent.innerHTML = "";
    const missing = missingRequiredData(data);
    const signalRows = Array.from(signalsPanel.querySelectorAll(".signal-row"));
    const signals = signalRows.map((node) => node.textContent.trim());
    const cards = [
      ["Пациент", displayValue(getValue(data, "GENERAL_INFO.Full_name"))],
      ["Случай", displayValue(getValue(data, "GENERAL_INFO.Patient_ID"))],
      ["Возраст / пол", `${displayValue(getValue(data, "GENERAL_INFO.Age"), "?")} / ${displayValue(getValue(data, "GENERAL_INFO.Sex"), "?")}`],
      ["Готовность", readinessMetric?.textContent || "0%"],
      ["Размер JSON", `${JSON.stringify(data).length} символов`]
    ];
    const cardGrid = document.createElement("div");
    cardGrid.className = "clinical-cards compact";
    cards.forEach(([label, value]) => {
      const card = document.createElement("div");
      card.className = "clinical-card";
      const caption = document.createElement("span");
      caption.textContent = label;
      const strong = document.createElement("strong");
      strong.textContent = value;
      card.append(caption, strong);
      cardGrid.appendChild(card);
    });
    reviewContent.appendChild(cardGrid);
    reviewContent.appendChild(reviewList("Не хватает для полной готовности", missing.map(([, label]) => label), "Все ключевые поля заполнены."));
    reviewContent.appendChild(reviewList("Сигналы", signals, "Явных сигналов по заполненным числовым данным нет."));
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(data, null, 2);
    reviewContent.appendChild(pre);
  }

  function reviewList(title, items, emptyText) {
    const section = document.createElement("div");
    section.className = "quality-section";
    const heading = document.createElement("h3");
    heading.textContent = title;
    const list = document.createElement("div");
    list.className = "quality-list";
    if (items.length === 0) {
      const row = document.createElement("div");
      row.className = "check-row ok";
      row.textContent = emptyText;
      list.appendChild(row);
    } else {
      items.forEach((item) => {
        const row = document.createElement("div");
        row.className = "check-row warning";
        row.textContent = item;
        list.appendChild(row);
      });
    }
    section.append(heading, list);
    return section;
  }

  function resetModelState(clearFields = false) {
    currentModelRequestId = null;
    if (clearFields) {
      const modelSection = window.CVD_SCHEMA.find((section) => section.key === "MODEL_OUTPUT");
      modelSection?.fields.forEach((field) => setFieldValue(`MODEL_OUTPUT.${field.key}`, null));
    }
    modelPreview.textContent = "Ответ модели появится здесь.";
    modelStructured.innerHTML = "";
    modelStatus.textContent = "модель не вызывалась";
    modelStatus.className = "pill";
    requestReviewForm?.classList.add("hidden");
  }

  function resetCase() {
    currentCaseId = null;
    form.reset();
    resetModelState();
    updatePreview();
    saveStatus.textContent = "не сохранено";
  }

  function setupTabs() {
    document.querySelectorAll(".tab").forEach((button) => {
      button.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
        button.classList.add("active");
        ["quality", "json", "model", "history"].forEach((name) => {
          document.getElementById(`tab-${name}`).classList.toggle("hidden", name !== button.dataset.tab);
        });
      });
    });
  }

  function setupUser() {
    const user = window.CURRENT_USER || {};
    document.getElementById("userLabel").textContent = `${user.email || ""} · ${user.role || ""}`;
    if (user.role === "admin") {
      document.getElementById("adminLink").classList.remove("hidden");
    }
    document.getElementById("changePasswordButton").addEventListener("click", openPasswordModal);
    document.getElementById("closePasswordModal").addEventListener("click", closePasswordModal);
    document.getElementById("cancelPasswordModal").addEventListener("click", closePasswordModal);
    document.getElementById("reviewButton").addEventListener("click", () => openReviewModal(null, false));
    document.getElementById("closeReviewModal").addEventListener("click", closeReviewModal);
    document.getElementById("cancelReviewModal").addEventListener("click", closeReviewModal);
    confirmReviewButton.addEventListener("click", () => {
      const action = pendingReviewAction;
      closeReviewModal();
      if (action) action().catch((err) => toast(err.message));
    });
    reviewModal.addEventListener("click", (event) => {
      if (event.target === reviewModal) closeReviewModal();
    });
    document.getElementById("closeImportModal").addEventListener("click", closeImportModal);
    document.getElementById("cancelImportModal").addEventListener("click", closeImportModal);
    document.getElementById("selectNewImportButton").addEventListener("click", selectNewImportFields);
    document.getElementById("clearImportSelectionButton").addEventListener("click", clearImportSelection);
    document.getElementById("applyImportButton").addEventListener("click", () => applyPendingImport().catch((err) => toast(err.message)));
    importModal.addEventListener("click", (event) => {
      if (event.target === importModal) closeImportModal();
    });
    document.getElementById("structureTextButton").addEventListener("click", openStructureTextModal);
    document.getElementById("closeStructureTextModal").addEventListener("click", closeStructureTextModal);
    document.getElementById("cancelStructureTextModal").addEventListener("click", closeStructureTextModal);
    structureTextModal.addEventListener("click", (event) => {
      if (event.target === structureTextModal) closeStructureTextModal();
    });
    structureTextForm.addEventListener("submit", (event) => structureText(event).catch((err) => toast(err.message)));
    structureTextInput.addEventListener("input", updateStructureTextCounter);
    document.getElementById("copyCorrectedTextButton").addEventListener("click", () => copyCorrectedText().catch((err) => toast(err.message)));
    passwordModal.addEventListener("click", (event) => {
      if (event.target === passwordModal) closePasswordModal();
    });
    passwordForm.addEventListener("submit", (event) => changeOwnPassword(event).catch((err) => toast(err.message)));
    passwordForm.new_password.addEventListener("input", updatePasswordStrength);
    requestReviewForm?.addEventListener("submit", (event) => saveRequestReview(event).catch((err) => toast(err.message)));
    document.getElementById("logoutButton").addEventListener("click", async () => {
      const response = await api("/api/logout", { method: "POST", body: "{}" });
      window.location.href = response.redirect || "/login";
    });
  }

  function openPasswordModal() {
    passwordForm.reset();
    updatePasswordStrength();
    passwordModal.classList.remove("hidden");
    passwordForm.current_password.focus();
  }

  function closePasswordModal() {
    passwordModal.classList.add("hidden");
  }

  function updatePasswordStrength() {
    const value = passwordForm.new_password.value || "";
    const longEnough = value.length >= minimumPasswordLength;
    const varied = [/[a-zа-я]/i, /\d/, /[^a-zа-я0-9]/i].filter((pattern) => pattern.test(value)).length;
    passwordStrength.className = `notice ${longEnough && varied >= 2 ? "ok-note" : "warning-note"}`;
    passwordStrength.textContent = longEnough
      ? "Длина достаточная. Проверьте, что пароль не совпадает с email и не является типовым."
      : `Нужно ещё ${minimumPasswordLength - value.length} символов до минимальной длины.`;
  }

  async function changeOwnPassword(event) {
      event.preventDefault();
      await api("/api/me/password", {
        method: "POST",
        body: JSON.stringify({
          current_password: passwordForm.current_password.value,
          new_password: passwordForm.new_password.value
        })
      });
      closePasswordModal();
      toast("Пароль изменён");
  }

  renderForm();
  setupTabs();
  setupUser();
  updateStructureTextCounter();
  form.addEventListener("input", (event) => {
    if (event.target.name === "GENERAL_INFO.Height_cm" || event.target.name === "GENERAL_INFO.Weight_kg") {
      calculateBMI();
    }
    updatePreview();
    saveStatus.textContent = currentCaseId ? `кейс #${currentCaseId} изменён` : "не сохранено";
  });
  document.getElementById("saveCaseButton").addEventListener("click", () => saveCase().catch((err) => toast(err.message)));
  document.getElementById("diagnoseButton").addEventListener("click", diagnose);
  document.getElementById("downloadJsonButton").addEventListener("click", downloadJson);
  document.getElementById("importJsonButton").addEventListener("click", () => importJsonInput.click());
  importJsonInput.addEventListener("change", () => {
    const file = importJsonInput.files?.[0];
    importJson(file).catch((err) => toast(err.message)).finally(() => {
      importJsonInput.value = "";
    });
  });
  document.getElementById("downloadFhirButton").addEventListener("click", () => downloadFHIR().catch((err) => toast(err.message)));
  document.getElementById("newCaseButton").addEventListener("click", resetCase);
  updatePreview();
  loadHistory().catch((err) => toast(err.message));
})();
