(function () {
  "use strict";

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const form = document.getElementById("caseForm");
  const jsonPreview = document.getElementById("jsonPreview");
  const modelPreview = document.getElementById("modelPreview");
  const modelStructured = document.getElementById("modelStructured");
  const saveStatus = document.getElementById("saveStatus");
  const modelStatus = document.getElementById("modelStatus");
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
  const structureTextError = document.getElementById("structureTextError");
  const exportHtmlButton = document.getElementById("exportHtmlButton");
  const resultReadyBanner = document.getElementById("resultReadyBanner");
  const viewResultButton = document.getElementById("viewResultButton");
  const minimumPasswordLength = 15;
  const maxImportBytes = 5 * 1024 * 1024;
  let currentCaseId = null;
  let currentModelRequestId = null;
  let pendingReviewAction = null;
  let pendingImport = null;
  let structureTextBusy = false;
  let structureTextTimer = null;
  let structureTextStartedAt = 0;
  let structureTextChunkEstimate = 1;
  let structureQueueState = null;
  let structureQueueTimer = null;
  let diagnosisQueueTimer = null;
  const modalTriggers = new WeakMap();

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

  function openModalElement(modal, focusTarget = null) {
    if (document.activeElement instanceof HTMLElement) {
      modalTriggers.set(modal, document.activeElement);
    }
    modal.classList.remove("hidden");
    const scrollArea = modal.querySelector(".modal-body");
    if (scrollArea) scrollArea.scrollTop = 0;
    modal.querySelectorAll(".import-diff, .corrected-text-block").forEach((node) => {
      node.scrollTop = 0;
      node.scrollLeft = 0;
    });
    document.body.classList.add("modal-open");
    window.requestAnimationFrame(() => focusTarget?.focus());
  }

  function closeModalElement(modal) {
    modal.classList.add("hidden");
    if (!document.querySelector(".modal:not(.hidden)")) {
      document.body.classList.remove("modal-open");
    }
    const trigger = modalTriggers.get(modal);
    modalTriggers.delete(modal);
    if (trigger?.isConnected) trigger.focus();
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
    title.textContent = cds.model_should_abstain ? "AI не сформировал заключение" : "Клиническая сводка";
    const text = document.createElement("p");
    text.textContent = cds.summary || "Сводка не указана.";
    summary.append(title, text);
    if (meta.duration_ms) {
      const version = document.createElement("small");
      version.textContent = `Время анализа: ${(Number(meta.duration_ms) / 1000).toFixed(1)} с`;
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

    modelStructured.appendChild(renderModelList("Red flags", cds.red_flags, "Нет явных red flags в результате AI-анализа."));
    modelStructured.appendChild(renderModelList("Недостающие данные", cds.missing_data, "Недостающие данные не указаны."));
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

  function setHtmlExportAvailable(available) {
    if (exportHtmlButton) exportHtmlButton.disabled = !available;
    resultReadyBanner?.classList.toggle("hidden", !available);
    if (viewResultButton) viewResultButton.disabled = !available;
  }

  function viewHtmlResult(requestId = currentModelRequestId) {
    if (!requestId) {
      toast("Сначала получите успешный результат AI-анализа");
      return;
    }
    const link = document.createElement("a");
    link.href = `/reports/${encodeURIComponent(requestId)}`;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  async function exportHtmlReport() {
    if (!currentModelRequestId) {
      toast("Сначала получите успешный результат AI-анализа");
      return;
    }
    exportHtmlButton.disabled = true;
    try {
      const response = await fetch("/api/reports/html", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken
        },
        body: JSON.stringify({
          request_id: currentModelRequestId,
          patient_data: updatePreview()
        })
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || `HTTP ${response.status}`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `cvd-report-${currentModelRequestId}.html`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast("HTML-отчёт сформирован");
    } finally {
      setHtmlExportAvailable(Boolean(currentModelRequestId));
    }
  }

  async function saveRequestReview(event) {
    event.preventDefault();
    if (!currentModelRequestId) {
      toast("Сначала выберите результат AI-анализа");
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
    currentModelRequestId = null;
    setHtmlExportAvailable(false);
    modelStatus.textContent = "запрос выполняется";
    modelStatus.className = "pill warning";
    modelPreview.textContent = "Выполняется AI-анализ...";
    diagnosisQueueTimer = window.setInterval(async () => {
      try {
        const status = await api("/api/inference/status");
        const queue = status.queue || {};
        const own = queue.user?.by_kind?.diagnosis || {};
        if (own.state === "queued") {
          modelStatus.textContent = `в очереди · позиция ${own.position}`;
        } else if (own.state === "running") {
          modelStatus.textContent = "AI обрабатывает запрос";
        }
      } catch (_) {
        // Основной запрос покажет ошибку; сбой служебного polling не должен его прерывать.
      }
    }, 2000);
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
      setHtmlExportAvailable(true);
      const seconds = (Number(response.duration_ms || 0) / 1000).toFixed(1);
      const waited = Number(response.queue_wait_ms || 0) > 0 ? ` · очередь ${(Number(response.queue_wait_ms) / 1000).toFixed(1)} с` : "";
      modelStatus.textContent = `результат готов за ${seconds} с${waited}`;
      modelStatus.className = "pill ok";
      toast("Результат AI-анализа готов");
      await loadHistory();
    } catch (err) {
      modelPreview.textContent = err.message;
      modelStatus.textContent = "ошибка AI-анализа";
      modelStatus.className = "pill error";
      toast(err.message);
    } finally {
      if (diagnosisQueueTimer) window.clearInterval(diagnosisQueueTimer);
      diagnosisQueueTimer = null;
      button.disabled = false;
    }
  }

  async function loadHistory() {
    const response = await api("/api/library/summary");
    if (requestMetric) requestMetric.textContent = String(response.summary?.requests_total || 0);
  }

  function requestErrorText() {
    return "AI-анализ завершился ошибкой. Повторите запрос или обратитесь к администратору.";
  }

  async function openCase(caseId) {
    const response = await api(`/api/cases/${caseId}`);
    currentCaseId = response.case.id;
    resetModelState();
    applyData(response.case.data);
    toast("Кейс загружен");
  }

  function openRequestResult(item) {
    document.querySelectorAll(".tab").forEach((button) => {
      button.classList.toggle("active", button.dataset.tab === "model");
    });
    ["quality", "json", "model"].forEach((name) => {
      document.getElementById(`tab-${name}`).classList.toggle("hidden", name !== "model");
    });
    currentModelRequestId = item.id;
    modelStatus.textContent = item.status === "success" ? "ответ из истории" : "ошибка из истории";
    modelStatus.className = `pill ${item.status === "success" ? "ok" : "error"}`;
    modelPreview.textContent = JSON.stringify(item.parsed_output || {error: requestErrorText()}, null, 2);
    renderModelOutput(item.parsed_output || {}, item);
    showReviewForm(item.id, item.review);
    setHtmlExportAvailable(item.status === "success");
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
      preview.mapping_version || "",
      Number(preview.chunk_count || 1) > 1 ? `${preview.chunk_count} частей` : ""
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
    const visibleWarnings = warnings.slice(0, 8).map((item) => `• ${item}`);
    if (warnings.length > visibleWarnings.length) {
      visibleWarnings.push(`• И ещё предупреждений: ${warnings.length - visibleWarnings.length}`);
    }
    importWarnings.textContent = visibleWarnings.join("\n");
    renderImportDiff();
    openModalElement(importModal, document.getElementById("closeImportModal"));
  }

  function shouldAutoSelectImportRow(row) {
    if (row.state !== "new" || row.mapping.source_conflict) return false;
    if (pendingImport?.preview?.source_format !== "ai-text") return true;
    return row.mapping.confidence === "high";
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
      checkbox.checked = shouldAutoSelectImportRow(row);
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
    document.getElementById("importSelectionFooter").textContent = selected
      ? `К применению выбрано полей: ${selected}`
      : "Выберите хотя бы одно поле";
    document.getElementById("applyImportButton").disabled = selected === 0;
  }

  function selectNewImportFields() {
    pendingImport?.rows.forEach((row) => {
      if (row.checkbox && !row.checkbox.disabled) row.checkbox.checked = shouldAutoSelectImportRow(row);
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
    closeModalElement(importModal);
    correctedTextBlock.classList.add("hidden");
    correctedTextContent.textContent = "";
    pendingImport = null;
  }

  function openStructureTextModal() {
    structureTextStatus.textContent = "ожидание";
    structureTextStatus.className = "pill";
    structureTextError.textContent = "";
    structureTextError.classList.add("hidden");
    openModalElement(structureTextModal, structureTextInput);
  }

  function closeStructureTextModal() {
    if (structureTextBusy) {
      toast("Дождитесь завершения AI-разбора");
      return;
    }
    closeModalElement(structureTextModal);
  }

  function setStructureTextBusy(busy) {
    structureTextBusy = busy;
    document.getElementById("submitStructureTextButton").disabled = busy;
    document.getElementById("cancelStructureTextModal").disabled = busy;
    document.getElementById("closeStructureTextModal").disabled = busy;
  }

  function stopStructureTextProgress() {
    if (structureTextTimer) window.clearInterval(structureTextTimer);
    if (structureQueueTimer) window.clearInterval(structureQueueTimer);
    structureTextTimer = null;
    structureQueueTimer = null;
    structureQueueState = null;
  }

  function updateStructureTextProgress() {
    const elapsed = Math.max(0, Math.floor((Date.now() - structureTextStartedAt) / 1000));
    const minutes = String(Math.floor(elapsed / 60)).padStart(2, "0");
    const seconds = String(elapsed % 60).padStart(2, "0");
    const chunks = structureTextChunkEstimate > 1 ? ` · частей: ${structureTextChunkEstimate}` : "";
    if (structureQueueState?.state === "queued") {
      structureTextStatus.textContent = `в очереди · позиция ${structureQueueState.position} · ${minutes}:${seconds}`;
      return;
    }
    structureTextStatus.textContent = `AI обрабатывает${chunks} · ${minutes}:${seconds}`;
  }

  function updateStructureTextCounter() {
    document.getElementById("structureTextCounter").textContent = `${structureTextInput.value.length} / 10000`;
  }

  async function structureText(event) {
    event.preventDefault();
    const text = structureTextInput.value.trim();
    if (text.length < 10) {
      toast("Добавьте медицинский текст длиной не менее 10 символов");
      return;
    }
    setStructureTextBusy(true);
    structureTextError.textContent = "";
    structureTextError.classList.add("hidden");
    structureTextStartedAt = Date.now();
    structureTextChunkEstimate = Math.max(1, Math.ceil(text.length / 1400));
    updateStructureTextProgress();
    structureTextTimer = window.setInterval(updateStructureTextProgress, 1000);
    structureQueueTimer = window.setInterval(async () => {
      try {
        const status = await api("/api/inference/status");
        structureQueueState = status.queue?.user?.by_kind?.text_structuring || null;
        updateStructureTextProgress();
      } catch (_) {
        structureQueueState = null;
      }
    }, 2000);
    structureTextStatus.className = "pill warning";
    try {
      const preview = await api("/api/model/structure-text", {
        method: "POST",
        body: JSON.stringify({text})
      });
      const chunks = Number(preview.chunk_count || 1) > 1 ? ` · частей: ${preview.chunk_count}` : "";
      const failed = Number(preview.failed_chunk_count || 0);
      structureTextStatus.textContent = `${failed ? "частично готово" : "готово"} · ${preview.mappings?.length || 0} полей${chunks}`;
      structureTextStatus.className = `pill ${failed ? "warning" : "ok"}`;
      stopStructureTextProgress();
      setStructureTextBusy(false);
      closeStructureTextModal();
      openImportPreview(preview);
    } catch (error) {
      structureTextStatus.textContent = "ошибка обработки";
      structureTextStatus.className = "pill error";
      structureTextError.textContent = error.message || "Не удалось подготовить текст";
      structureTextError.classList.remove("hidden");
      throw error;
    } finally {
      stopStructureTextProgress();
      setStructureTextBusy(false);
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
    openModalElement(reviewModal, aiMode ? confirmReviewButton : document.getElementById("closeReviewModal"));
  }

  function closeReviewModal() {
    closeModalElement(reviewModal);
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
    setHtmlExportAvailable(false);
    if (clearFields) {
      const modelSection = window.CVD_SCHEMA.find((section) => section.key === "MODEL_OUTPUT");
      modelSection?.fields.forEach((field) => setFieldValue(`MODEL_OUTPUT.${field.key}`, null));
    }
    modelPreview.textContent = "Технический ответ AI появится здесь.";
    modelStructured.innerHTML = "";
    modelStatus.textContent = "AI не запускался";
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
        ["quality", "json", "model"].forEach((name) => {
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
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      const openModals = Array.from(document.querySelectorAll(".modal:not(.hidden)"));
      const modal = openModals[openModals.length - 1];
      if (!modal) return;
      event.preventDefault();
      if (modal === importModal) closeImportModal();
      else if (modal === structureTextModal) closeStructureTextModal();
      else if (modal === reviewModal) closeReviewModal();
      else if (modal === passwordModal) closePasswordModal();
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
    openModalElement(passwordModal, passwordForm.current_password);
  }

  function closePasswordModal() {
    closeModalElement(passwordModal);
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

  async function initializeWorkspace() {
    await loadHistory();
    const params = new URLSearchParams(window.location.search);
    const caseId = Number(params.get("case") || 0);
    const requestId = Number(params.get("request") || 0);
    if (Number.isInteger(caseId) && caseId > 0) {
      await openCase(caseId);
    }
    if (Number.isInteger(requestId) && requestId > 0) {
      const response = await api(`/api/requests/${requestId}`);
      openRequestResult(response.request);
    }
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
    setHtmlExportAvailable(false);
    saveStatus.textContent = currentCaseId ? `кейс #${currentCaseId} изменён` : "не сохранено";
  });
  document.getElementById("saveCaseButton").addEventListener("click", () => saveCase().catch((err) => toast(err.message)));
  document.getElementById("diagnoseButton").addEventListener("click", diagnose);
  document.getElementById("downloadJsonButton").addEventListener("click", downloadJson);
  exportHtmlButton?.addEventListener("click", () => exportHtmlReport().catch((err) => toast(err.message)));
  viewResultButton?.addEventListener("click", () => viewHtmlResult());
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
  initializeWorkspace().catch((err) => toast(err.message));
})();
