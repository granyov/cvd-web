(function () {
  "use strict";

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const form = document.getElementById("caseForm");
  const jsonPreview = document.getElementById("jsonPreview");
  const modelPreview = document.getElementById("modelPreview");
  const modelStructured = document.getElementById("modelStructured");
  const saveStatus = document.getElementById("saveStatus");
  const modelStatus = document.getElementById("modelStatus");
  const queueStatus = document.getElementById("queueStatus");
  const activeJobsLine = document.getElementById("activeJobsLine");
  const sectionNav = document.getElementById("sectionNav");
  const icdSummary = document.getElementById("icdSummary");
  const patientSnapshot = document.getElementById("patientSnapshot");
  const readinessPanel = document.getElementById("readinessPanel");
  const signalsPanel = document.getElementById("signalsPanel");
  const nextActionText = document.getElementById("nextActionText");
  const diagnoseButton = document.getElementById("diagnoseButton");
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
  const modelResultModal = document.getElementById("modelResultModal");
  const structureTextModal = document.getElementById("structureTextModal");
  const structureTextForm = document.getElementById("structureTextForm");
  const structureTextInput = document.getElementById("structureTextInput");
  const structureTextStatus = document.getElementById("structureTextStatus");
  const structureTextError = document.getElementById("structureTextError");
  const exportHtmlButton = document.getElementById("exportHtmlButton");
  const resultReadyBanner = document.getElementById("resultReadyBanner");
  const viewResultButton = document.getElementById("viewResultButton");
  const draftBanner = document.getElementById("draftBanner");
  const draftBannerText = document.getElementById("draftBannerText");
  const restoreDraftButton = document.getElementById("restoreDraftButton");
  const dismissDraftButton = document.getElementById("dismissDraftButton");
  const jumpMissingButton = document.getElementById("jumpMissingButton");
  const lastModelSummary = document.getElementById("lastModelSummary");
  const saveCaseButton = document.getElementById("saveCaseButton");
  const minimumPasswordLength = 15;
  const maxImportBytes = 5 * 1024 * 1024;
  const draftStorageKey = `cvd:case-draft:${window.CURRENT_USER?.email || "user"}`;
  let currentCaseId = null;
  let currentModelRequestId = null;
  let lastModelDataFingerprint = null;
  let pendingReviewAction = null;
  let pendingImport = null;
  let structureTextBusy = false;
  let structureTextTimer = null;
  let structureTextStartedAt = 0;
  let structureTextChunkEstimate = 1;
  let structureQueueState = null;
  let structureQueueTimer = null;
  let diagnosisQueueTimer = null;
  let activeJobsTimer = null;
  let draftSaveTimer = null;
  let suppressDraftSave = false;
  let pendingDraft = null;
  let hasUnsavedChanges = false;
  let passwordChangeForced = false;
  const baseDocumentTitle = document.title;
  const knownJobStatuses = new Map();
  let jobStatusesPrimed = false;
  let awaitedDiagnosisJobId = null;
  const modalTriggers = new WeakMap();

  const qualityRules = window.CVDClinicalQuality;
  const requiredDataPoints = qualityRules.requiredDataPoints;
  const panelTabs = ["quality", "json"];
  const formSectionGroups = [
    {
      key: "anamnesis",
      title: "Анамнез и исходные данные",
      hint: "Идентификация случая, жалобы, факторы риска, перенесённые события и известные диагнозы.",
      sectionKeys: ["GENERAL_INFO", "COMPLAINTS", "RISK_FACTORS", "PAST_EVENTS", "KNOWN_CVD_DIAGNOSES"]
    },
    {
      key: "objective",
      title: "Объективный статус",
      hint: "Осмотр, витальные параметры и физикальные признаки.",
      sectionKeys: ["PHYSICAL_EXAM"]
    },
    {
      key: "laboratory",
      title: "Лабораторные исследования",
      hint: "ОАК, биохимия, липиды, кардиомаркеры и коагулограмма.",
      sectionKeys: ["LABS_CBC", "LABS_BIOCHEM", "LABS_LIPIDS", "LABS_CARDIAC_MARKERS", "LABS_COAGULATION"]
    },
    {
      key: "instrumental",
      title: "Инструментальные исследования",
      hint: "ЭКГ, мониторинг, эхокардиография, функциональные тесты и визуализация.",
      sectionKeys: ["ECG_AND_BP_MONITORING", "ECHOCARDIOGRAPHY", "FUNCTIONAL_TESTS", "CORONARY_AND_VASCULAR_IMAGING"]
    },
    {
      key: "treatment",
      title: "Лечение, вмешательства и заключение",
      hint: "Устройства, процедуры, текущая терапия, шкалы, диагноз врача и поля ответа модели.",
      sectionKeys: ["DEVICES_AND_PROCEDURES", "CURRENT_MEDICATIONS", "SCORES_AND_CLASSES", "FINAL_DIAGNOSES", "MODEL_OUTPUT"]
    }
  ];
  const sectionGroupByKey = new Map();
  formSectionGroups.forEach((group) => {
    group.sectionKeys.forEach((key) => sectionGroupByKey.set(key, group));
  });

  function toast(message) {
    const node = document.createElement("div");
    node.className = "toast";
    node.textContent = message;
    document.body.appendChild(node);
    setTimeout(() => node.remove(), 3200);
  }

  function pill(text, kind = "") {
    const node = document.createElement("span");
    node.className = `pill ${kind}`.trim();
    node.textContent = text;
    return node;
  }

  function setSaveState(text, unsaved) {
    hasUnsavedChanges = Boolean(unsaved);
    saveStatus.textContent = text;
    saveStatus.classList.toggle("warning", hasUnsavedChanges);
    saveCaseButton?.classList.toggle("attention", hasUnsavedChanges);
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
    return qualityRules.getValue(data, path);
  }

  function isFilled(value) {
    return qualityRules.isFilled(value);
  }

  function displayValue(value, fallback = "не указано") {
    if (!isFilled(value)) return fallback;
    return Array.isArray(value) ? value.join("; ") : String(value);
  }

  function numericValue(data, path) {
    return qualityRules.numericValue(data, path);
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
    const reference = qualityRules.referenceRanges?.[input.name];
    if (reference) {
      const hint = document.createElement("small");
      hint.className = "field-reference";
      hint.dataset.referenceFor = input.name;
      hint.textContent = `Референс: ${reference.text}`;
      wrapper.appendChild(hint);
      input.dataset.hasReference = "1";
    }
    return wrapper;
  }

  function updateFieldReference(input) {
    if (!input?.dataset?.hasReference) return;
    const status = qualityRules.referenceStatus(input.name, input.value);
    if (!status) return;
    const hint = form.querySelector(`[data-reference-for="${input.name}"]`);
    if (!hint) return;
    const out = status.state === "below" || status.state === "above";
    input.classList.toggle("out-of-range", out);
    hint.classList.toggle("out", out);
    hint.textContent = out
      ? `${status.state === "below" ? "Ниже референса" : "Выше референса"}: ${status.range.text}`
      : `Референс: ${status.range.text}`;
  }

  function sectionNumber(index) {
    return String(index + 1).padStart(2, "0");
  }

  function sectionGroup(section) {
    return sectionGroupByKey.get(section.key) || {
      key: "other",
      title: "Прочие данные",
      hint: "",
      sectionKeys: []
    };
  }

  function renderFormGroupHeader(group) {
    const header = document.createElement("div");
    header.className = "form-section-group";
    const title = document.createElement("strong");
    title.textContent = group.title;
    const hint = document.createElement("span");
    hint.textContent = group.hint;
    header.append(title, hint);
    return header;
  }

  function renderForm() {
    form.innerHTML = "";
    let currentGroupKey = "";
    window.CVD_SCHEMA.forEach((section, index) => {
      const group = sectionGroup(section);
      if (group.key !== currentGroupKey) {
        currentGroupKey = group.key;
        form.appendChild(renderFormGroupHeader(group));
      }
      const details = document.createElement("details");
      details.className = "section";
      details.id = `section-${section.key}`;
      details.dataset.group = group.key;
      details.dataset.sectionIndex = String(index + 1);

      const summary = document.createElement("summary");
      const heading = document.createElement("span");
      heading.className = "section-summary-title";
      const number = document.createElement("span");
      number.className = "section-number";
      number.textContent = `${sectionNumber(index)}. `;
      const title = document.createElement("span");
      title.textContent = section.title;
      heading.append(number, title);
      const badge = document.createElement("span");
      badge.className = "section-fill-badge";
      badge.dataset.sectionBadge = section.key;
      badge.textContent = "0%";
      summary.append(heading, badge);

      const body = document.createElement("div");
      body.className = "section-body form-grid";
      section.fields.forEach((field) => body.appendChild(renderField(section, field)));

      details.appendChild(summary);
      details.appendChild(body);
      form.appendChild(details);
    });
    renderSectionNav();
  }

  function renderSectionNav() {
    if (!sectionNav) return;
    sectionNav.innerHTML = "";
    window.CVD_SCHEMA.forEach((section, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "section-nav-item";
      button.dataset.sectionNav = section.key;
      button.textContent = `${sectionNumber(index)}. ${section.title}`;
      button.addEventListener("click", () => focusSection(section.key));
      sectionNav.appendChild(button);
    });
  }

  function focusSection(sectionKey) {
    const details = document.getElementById(`section-${sectionKey}`);
    if (!details) return;
    details.open = true;
    details.scrollIntoView({behavior: "smooth", block: "start"});
    const firstInput = details.querySelector("input, select, textarea");
    window.setTimeout(() => firstInput?.focus(), 250);
  }

  function collapseAllSections() {
    form.querySelectorAll("details.section").forEach((details) => {
      details.open = false;
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
    setSaveState(currentCaseId ? `кейс #${currentCaseId}` : "не сохранено", false);
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
    updateSectionBadges(data);
    updateClinicalQuality(data);
    form.querySelectorAll('[data-has-reference="1"]').forEach(updateFieldReference);
    return data;
  }

  function readLocalDraft() {
    try {
      const raw = localStorage.getItem(draftStorageKey);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  }

  function writeLocalDraft(data) {
    if (suppressDraftSave) return;
    if (!qualityRules.hasClinicalInput(data)) return;
    const payload = {
      case_id: currentCaseId,
      patient_data: data,
      updated_at: new Date().toISOString(),
      fingerprint: qualityRules.dataFingerprint(data)
    };
    try {
      localStorage.setItem(draftStorageKey, JSON.stringify(payload));
    } catch {
      // Local draft is a convenience only; quota/storage errors must not block work.
    }
  }

  function scheduleDraftSave(data = null) {
    if (suppressDraftSave) return;
    const snapshot = data || collectData();
    window.clearTimeout(draftSaveTimer);
    draftSaveTimer = window.setTimeout(() => writeLocalDraft(snapshot), 350);
  }

  function clearLocalDraft() {
    pendingDraft = null;
    draftBanner?.classList.add("hidden");
    try { localStorage.removeItem(draftStorageKey); } catch (_) {}
  }

  function showDraftBanner(draft) {
    if (!draftBanner || !draft?.patient_data) return;
    pendingDraft = draft;
    const when = draft.updated_at ? new Date(draft.updated_at).toLocaleString("ru-RU", {day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit"}) : "";
    draftBannerText.textContent = `Найден локальный черновик${when ? ` от ${when}` : ""}.`;
    draftBanner.classList.remove("hidden");
  }

  function restoreLocalDraft() {
    if (!pendingDraft?.patient_data) return;
    suppressDraftSave = true;
    currentCaseId = pendingDraft.case_id || null;
    resetModelState(true);
    applyData(pendingDraft.patient_data);
    collapseAllSections();
    setSaveState(currentCaseId ? `кейс #${currentCaseId} восстановлен из черновика` : "черновик восстановлен", true);
    suppressDraftSave = false;
    clearLocalDraft();
    updatePreview();
    toast("Черновик восстановлен");
  }

  function initDraftRestore() {
    const params = new URLSearchParams(window.location.search);
    if (params.get("case") || params.get("request")) return;
    const draft = readLocalDraft();
    if (draft?.patient_data && qualityRules.hasClinicalInput(draft.patient_data)) showDraftBanner(draft);
  }

  function sectionFillPercent(section, data) {
    return qualityRules.sectionFillPercent(section, data);
  }

  function updateSectionBadges(data) {
    window.CVD_SCHEMA.forEach((section, index) => {
      const badge = form.querySelector(`[data-section-badge="${section.key}"]`);
      if (!badge) return;
      const {filled, total, percent} = sectionFillPercent(section, data);
      badge.textContent = `${filled}/${total} · ${percent}%`;
      badge.className = `section-fill-badge ${percent === 100 ? "ok" : percent > 0 ? "warning" : ""}`.trim();
      const navItem = sectionNav?.querySelector(`[data-section-nav="${section.key}"]`);
      if (navItem) {
        navItem.textContent = `${sectionNumber(index)}. ${section.title} · ${percent}%`;
        navItem.className = `section-nav-item ${percent === 100 ? "ok" : percent > 0 ? "warning" : ""}`.trim();
      }
    });
  }

  function missingRequiredData(data) {
    return qualityRules.missingRequiredData(data);
  }

  function updateClinicalQuality(data) {
    renderPatientSnapshot(data);
    renderReadiness(data);
    renderSignals(data);
    updateModelFreshness(data);
    updateWorkflow(data);
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

  function updateWorkflow(data) {
    const missing = missingRequiredData(data);
    const hasCase = Boolean(currentCaseId);
    const hasResult = Boolean(currentModelRequestId);
    const ready = missing.length === 0;
    document.getElementById("workflowStepData")?.classList.toggle("done", hasCase || ready);
    document.getElementById("workflowStepCheck")?.classList.toggle("done", ready);
    document.getElementById("workflowStepAi")?.classList.toggle("done", hasResult);
    document.getElementById("workflowStepResult")?.classList.toggle("done", hasResult);
    let nextAction = "Заполните ключевые поля пациента.";
    let ctaText = "Запустить AI-анализ";
    if (!hasCase) {
      nextAction = "Сохраните кейс, чтобы зафиксировать данные и историю действий.";
      ctaText = "Сначала сохраните кейс";
    } else if (!ready) {
      nextAction = `Дозаполните ключевые поля: ${missing.slice(0, 3).map(([, label]) => label).join(", ")}${missing.length > 3 ? "…" : ""}.`;
      ctaText = "Заполните данные для AI";
    } else if (!hasResult) {
      nextAction = "Кейс готов к проверке и запуску AI-анализа.";
      ctaText = "Запустить AI-анализ";
    } else {
      nextAction = "Результат готов: проверьте заключение и сохраните экспертную оценку.";
      ctaText = "Обновить AI-анализ";
    }
    if (nextActionText) nextActionText.textContent = nextAction;
    if (diagnoseButton && !diagnoseButton.disabled) diagnoseButton.textContent = ctaText;
  }

  function focusFieldPath(path) {
    const [section, field] = String(path || "").split(".");
    focusSection(section);
    const target = document.getElementById(fieldId(section, field));
    window.setTimeout(() => target?.focus(), 260);
  }

  function focusFirstMissing(data = updatePreview()) {
    const missing = missingRequiredData(data);
    if (!missing.length) {
      toast("Ключевые поля заполнены");
      return;
    }
    focusFieldPath(missing[0][0]);
  }

  function updateModelFreshness(data) {
    const stale = Boolean(currentModelRequestId && lastModelDataFingerprint && qualityRules.dataFingerprint(data) !== lastModelDataFingerprint);
    if (stale) {
      modelStatus.textContent = "данные изменены после AI";
      modelStatus.className = "pill warning";
    }
    diagnoseButton?.classList.toggle("warning", stale);
    diagnoseButton?.setAttribute("title", stale ? "Данные кейса изменились после последнего AI-анализа — рекомендуется обновить результат." : "");
  }

  function renderReadiness(data) {
    if (!readinessPanel) return;
    readinessPanel.innerHTML = "";
    const missing = missingRequiredData(data);
    const ready = requiredDataPoints.length - missing.length;
    const percent = Math.round((ready / requiredDataPoints.length) * 100);
    if (jumpMissingButton) {
      jumpMissingButton.disabled = missing.length === 0;
      jumpMissingButton.textContent = missing.length ? `К первому незаполненному (${missing.length})` : "Ключевые поля заполнены";
    }
    requiredDataPoints.forEach(([path, label]) => {
      const ok = isFilled(getValue(data, path));
      const row = document.createElement("button");
      row.type = "button";
      row.className = `check-row ${ok ? "ok" : "warning"}`;
      row.disabled = ok;
      row.title = ok ? `${label}: заполнено` : `Перейти к полю: ${label}`;
      const mark = document.createElement("span");
      mark.className = "check-mark";
      mark.textContent = ok ? "✓" : "!";
      const text = document.createElement("span");
      text.textContent = label;
      const state = document.createElement("small");
      state.textContent = ok ? "заполнено" : "заполнить";
      row.append(mark, text, state);
      if (!ok) row.addEventListener("click", () => focusFieldPath(path));
      readinessPanel.appendChild(row);
    });
  }

  function renderSignals(data) {
    if (!signalsPanel) return;
    signalsPanel.innerHTML = "";
    const signals = qualityRules.clinicalSignals(data);
    if (signals.length === 0) {
      const row = document.createElement("div");
      row.className = "check-row";
      row.textContent = "Явных сигналов по заполненным числовым данным нет.";
      signalsPanel.appendChild(row);
      return;
    }

    signals.forEach(({kind, title, text, category}) => {
      const row = document.createElement("div");
      row.className = `signal-row ${kind}`;
      const strong = document.createElement("strong");
      strong.textContent = title;
      const small = document.createElement("small");
      small.textContent = `${category ? `${category}: ` : ""}${text || "проверьте клинический контекст"}`;
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
    if (currentModelRequestId) updateModelFreshness(data);
    setSaveState(`кейс #${currentCaseId} сохранён`, false);
    clearLocalDraft();
    toast("Кейс сохранён");
  }

  function fillModelOutput(parsed) {
    const modelOutput = parsed?.MODEL_OUTPUT || parsed;
    if (!modelOutput || typeof modelOutput !== "object") return;
    for (const [key, value] of Object.entries(modelOutput)) {
      setFieldValue(`MODEL_OUTPUT.${key}`, value);
    }
    updatePreview();
    scheduleDraftSave();
  }

  function durationText(ms) {
    const value = Number(ms || 0);
    if (!value) return "—";
    if (value < 1000) return `${Math.round(value)} мс`;
    const seconds = value / 1000;
    return seconds < 60 ? `${seconds.toFixed(1)} с` : `${Math.round(seconds / 60)} мин`;
  }

  function queueEtaText(ms) {
    const value = Number(ms || 0);
    if (!value) return "оценка уточняется";
    if (value < 60000) return `~${Math.max(1, Math.round(value / 1000))} с`;
    return `~${Math.round(value / 60000)} мин`;
  }

  function wait(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  function aiJobTitle(job) {
    return job.type === "text_preparation" ? `Текст #${job.id}` : `Диагноз #${job.id}`;
  }

  function aiJobStatusText(job) {
    if (job.status === "queued") return job.position ? `очередь ${job.position}` : "в очереди";
    if (job.status === "running") return "выполняется";
    if (job.status === "success") return "готово";
    if (job.status === "error") return "ошибка";
    return job.status || "статус";
  }

  async function openAiJob(job) {
    if (job.type === "text_preparation") {
      if (job.status !== "success") {
        toast(job.status === "error" ? job.error || "Подготовка текста завершилась ошибкой" : "Подготовка текста ещё выполняется");
        return;
      }
      const response = await api(`/api/model/structure-text/jobs/${job.id}`);
      const result = response.job?.result;
      if (!result) throw new Error("Результат подготовки текста ещё не сохранён");
      openImportPreview(result);
      return;
    }
    if (job.type === "diagnosis") {
      if (job.status !== "success" || !job.model_request_id) {
        toast(job.status === "error" ? job.error || "AI-анализ завершился ошибкой" : "AI-анализ ещё выполняется");
        return;
      }
      const response = await api(`/api/requests/${job.model_request_id}`);
      openRequestResult(response.request);
    }
  }

  function renderActiveJobs(payload) {
    if (!activeJobsLine) return;
    const jobs = payload?.jobs || [];
    const visible = [
      ...jobs.filter((job) => ["queued", "running"].includes(job.status)),
      ...jobs.filter((job) => ["success", "error"].includes(job.status)).slice(0, 3)
    ].slice(0, 6);
    activeJobsLine.innerHTML = "";
    activeJobsLine.classList.toggle("hidden", visible.length === 0);
    visible.forEach((job) => {
      const actionable = job.status === "success" && (
        (job.type === "text_preparation" && job.import_id) ||
        (job.type === "diagnosis" && job.model_request_id)
      );
      const node = document.createElement(actionable ? "button" : "span");
      if (actionable) node.type = "button";
      node.className = `job-chip ${job.status === "success" ? "ok" : job.status === "error" ? "error" : "warning"}`;
      const title = document.createElement("strong");
      title.textContent = aiJobTitle(job);
      const state = document.createElement("span");
      state.className = "muted";
      state.textContent = aiJobStatusText(job);
      node.append(title, state);
      if (actionable) {
        node.addEventListener("click", () => openAiJob(job).catch((err) => toast(err.message)));
      }
      activeJobsLine.appendChild(node);
    });
  }

  function requestNotifyPermission() {
    if (!("Notification" in window)) return;
    if (Notification.permission === "default") {
      Notification.requestPermission().catch(() => {});
    }
  }

  function notifyDesktop(title, body) {
    if (!("Notification" in window)) return;
    if (Notification.permission !== "granted" || !document.hidden) return;
    try {
      const notification = new Notification(title, {body, icon: "/static/favicon.svg"});
      notification.addEventListener("click", () => window.focus());
    } catch (_) {}
  }

  function markTitleReady() {
    if (document.hidden) document.title = `✓ ${baseDocumentTitle}`;
  }

  function notifyJobTransitions(jobs) {
    if (!jobStatusesPrimed) {
      // First poll after page load: remember statuses without notifying about old jobs.
      jobs.forEach((job) => knownJobStatuses.set(`${job.type}:${job.id}`, job.status));
      jobStatusesPrimed = true;
      return;
    }
    jobs.forEach((job) => {
      const key = `${job.type}:${job.id}`;
      const previous = knownJobStatuses.get(key);
      knownJobStatuses.set(key, job.status);
      const wasActive = previous === undefined || ["queued", "running"].includes(previous);
      const finished = ["success", "error"].includes(job.status);
      if (!wasActive || !finished || previous === job.status) return;
      if (job.type === "diagnosis" && job.id === awaitedDiagnosisJobId) return;
      const ready = job.status === "success";
      toast(ready ? `${aiJobTitle(job)}: результат готов` : `${aiJobTitle(job)}: ошибка выполнения`);
      markTitleReady();
      notifyDesktop(
        ready ? "Результат AI готов" : "AI-задание завершилось ошибкой",
        `${aiJobTitle(job)} · откройте рабочее место, чтобы посмотреть результат.`
      );
    });
  }

  async function refreshAiJobs() {
    const payload = await api("/api/ai/jobs");
    renderActiveJobs(payload);
    notifyJobTransitions(payload?.jobs || []);
    return payload;
  }

  function renderModelMetaGrid(items) {
    const grid = document.createElement("div");
    grid.className = "model-meta-grid";
    items.forEach(([label, value, kind = ""]) => {
      const item = document.createElement("div");
      item.className = `model-meta-item ${kind}`.trim();
      const caption = document.createElement("span");
      caption.textContent = label;
      const strong = document.createElement("strong");
      strong.textContent = value;
      item.append(caption, strong);
      grid.appendChild(item);
    });
    return grid;
  }

  function openModelResultModal() {
    if (!modelResultModal) return;
    openModalElement(modelResultModal, document.getElementById("closeModelResultModal"));
  }

  function closeModelResultModal() {
    if (!modelResultModal) return;
    closeModalElement(modelResultModal);
  }

  function openTab(name) {
    if (name === "model") {
      openModelResultModal();
      return;
    }
    if (!panelTabs.includes(name)) return;
    document.querySelectorAll(".tab").forEach((button) => {
      button.classList.toggle("active", button.dataset.tab === name);
    });
    panelTabs.forEach((tabName) => {
      document.getElementById(`tab-${tabName}`).classList.toggle("hidden", tabName !== name);
    });
  }

  function renderLastModelSummary(cds, meta = {}) {
    if (!lastModelSummary) return;
    if (!cds || typeof cds !== "object") {
      lastModelSummary.classList.add("hidden");
      lastModelSummary.innerHTML = "";
      return;
    }
    const diagnoses = Array.isArray(cds.possible_diagnoses) ? cds.possible_diagnoses : [];
    const redFlags = Array.isArray(cds.red_flags) ? cds.red_flags.filter(Boolean) : [];
    const missing = Array.isArray(cds.missing_data) ? cds.missing_data.filter(Boolean) : [];
    const mainDiagnosis = diagnoses[0]?.name || cds.summary || "AI-результат без диагноза";
    lastModelSummary.innerHTML = "";
    const toolbar = document.createElement("div");
    toolbar.className = "toolbar";
    const title = document.createElement("strong");
    title.textContent = "Последний AI-результат";
    const open = document.createElement("button");
    open.type = "button";
    open.textContent = "Открыть ответ";
    open.addEventListener("click", () => openTab("model"));
    toolbar.append(title, open);
    const summary = document.createElement("small");
    summary.textContent = mainDiagnosis;
    const stats = document.createElement("div");
    stats.className = "status-line";
    stats.append(
      pill(`${diagnoses.length} диагнозов`),
      pill(`${redFlags.length} red flags`, redFlags.length ? "error" : ""),
      pill(`${missing.length} missing`, missing.length ? "warning" : ""),
      pill(durationText(meta.duration_ms))
    );
    lastModelSummary.append(toolbar, summary, stats);
    lastModelSummary.classList.remove("hidden");
  }

  function renderModelOutput(parsed, meta = {}) {
    if (!modelStructured) return;
    modelStructured.innerHTML = "";
    const cds = parsed?.CDS_OUTPUT;
    if (!cds || typeof cds !== "object") {
      modelStructured.textContent = "Структурированный CDS-ответ отсутствует.";
      renderLastModelSummary(null);
      return;
    }
    const diagnoses = Array.isArray(cds.possible_diagnoses) ? cds.possible_diagnoses : [];
    const redFlags = Array.isArray(cds.red_flags) ? cds.red_flags.filter(Boolean) : [];
    const missing = Array.isArray(cds.missing_data) ? cds.missing_data.filter(Boolean) : [];
    const summary = document.createElement("div");
    summary.className = `model-summary-card ${cds.model_should_abstain ? "warning" : redFlags.length ? "danger" : ""}`.trim();
    const titleRow = document.createElement("div");
    titleRow.className = "model-summary-title";
    const title = document.createElement("strong");
    title.textContent = cds.model_should_abstain ? "AI воздержался от заключения" : "Клиническая сводка";
    titleRow.append(title, pill(cds.model_should_abstain ? "нужна ручная оценка" : "готово", cds.model_should_abstain ? "warning" : "ok"));
    const text = document.createElement("p");
    text.textContent = cds.summary || "Сводка не указана.";
    summary.append(titleRow, text, renderModelMetaGrid([
      ["Модель", meta.model || "—"],
      ["Время анализа", durationText(meta.duration_ms)],
      ["Ожидание", durationText(meta.queue_wait_ms)],
      ["Диагнозов", String(diagnoses.length)],
      ["Red flags", String(redFlags.length), redFlags.length ? "danger" : ""],
      ["Не хватает", String(missing.length), missing.length ? "warning" : ""]
    ]));
    modelStructured.appendChild(summary);
    renderLastModelSummary(cds, meta);
    if (meta.ai_result_stale) {
      modelStructured.appendChild(renderStaleDiff(meta.ai_result_changes || []));
    }
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

  function formatChangeValue(value) {
    if (Array.isArray(value)) return value.length ? value.join("; ") : "—";
    if (value && typeof value === "object") return JSON.stringify(value);
    return qualityRules.isFilled(value) ? String(value) : "—";
  }

  function renderStaleDiff(changes) {
    const section = document.createElement("div");
    section.className = "model-stale-card";
    const header = document.createElement("div");
    header.className = "model-summary-title";
    const title = document.createElement("strong");
    title.textContent = "Что изменилось после AI";
    header.append(title, pill(changes.length ? `${changes.length} изм.` : "требуется обновление", "warning"));
    const hint = document.createElement("p");
    hint.textContent = changes.length
      ? "Текущий кейс отличается от данных, по которым был получен этот AI-результат. Перед клиническим использованием обновите анализ."
      : "Данные кейса изменились после AI-анализа, но подробный diff недоступен для старого результата. Обновите AI-анализ.";
    section.append(header, hint);
    if (changes.length) {
      const list = document.createElement("div");
      list.className = "stale-diff-list";
      const labels = {added: "добавлено", removed: "удалено", changed: "изменено"};
      changes.slice(0, 12).forEach((change) => {
        const row = document.createElement("div");
        row.className = `stale-diff-row ${change.kind || "changed"}`;
        const name = document.createElement("strong");
        name.textContent = change.label || change.path || "Поле";
        const before = document.createElement("small");
        before.textContent = `Было: ${formatChangeValue(change.before)}`;
        const after = document.createElement("small");
        after.textContent = `Стало: ${formatChangeValue(change.after)}`;
        row.append(name, pill(labels[change.kind] || "изменено", change.kind === "removed" ? "error" : "warning"), before, after);
        list.appendChild(row);
      });
      if (changes.length > 12) {
        const more = document.createElement("small");
        more.className = "muted";
        more.textContent = `Показаны первые 12 изменений из ${changes.length}.`;
        list.appendChild(more);
      }
      section.appendChild(list);
    }
    return section;
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
    const confidenceLabels = {high: "высокая", medium: "средняя", low: "низкая"};
    confidence.textContent = confidenceLabels[diagnosis.confidence] || diagnosis.confidence || "не указана";
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
  }

  function diagnose() {
    const patientData = updatePreview();
    if (!qualityRules.hasClinicalInput(patientData)) {
      modelStatus.textContent = "добавьте данные пациента";
      modelStatus.className = "pill warning";
      toast("Добавьте данные пациента перед запуском AI-анализа");
      focusFieldPath("GENERAL_INFO.Patient_ID");
      return;
    }
    openReviewModal(() => runDiagnose(patientData), true);
  }

  async function runDiagnose(patientData) {
    const button = diagnoseButton || document.getElementById("diagnoseButton");
    const idleButtonText = button.textContent;
    let response = null;
    button.disabled = true;
    currentModelRequestId = null;
    lastModelDataFingerprint = null;
    setHtmlExportAvailable(false);
    hideAiErrorCard();
    modelStatus.textContent = "запрос выполняется";
    modelStatus.className = "pill warning";
    modelPreview.textContent = "Выполняется AI-анализ...";
    modelStructured.textContent = "AI-анализ выполняется. Результат появится здесь после завершения задания.";
    requestReviewForm?.classList.add("hidden");
    diagnosisQueueTimer = window.setInterval(async () => {
      try {
        const status = await api("/api/inference/status");
        const queue = status.queue || {};
        const own = queue.user?.by_kind?.diagnosis || {};
        if (own.state === "queued") {
          const eta = own.estimated_wait_ms ? ` · ${queueEtaText(own.estimated_wait_ms)}` : "";
          modelStatus.textContent = `в очереди · позиция ${own.position}${eta}`;
          if (queueStatus) {
            queueStatus.textContent = `AI очередь: позиция ${own.position}${eta}`;
            queueStatus.className = "pill warning";
          }
        } else if (own.state === "running") {
          modelStatus.textContent = "AI обрабатывает запрос";
          if (queueStatus) {
            queueStatus.textContent = "AI обрабатывает запрос";
            queueStatus.className = "pill ok";
          }
        }
      } catch (_) {
        // Основной запрос покажет ошибку; сбой служебного polling не должен его прерывать.
      }
    }, 2000);
    try {
      const requestFingerprint = qualityRules.dataFingerprint(patientData);
      const job = await api("/api/model/diagnose/jobs", {
        method: "POST",
        body: JSON.stringify({
          case_id: currentCaseId,
          patient_data: patientData
        })
      });
      awaitedDiagnosisJobId = job.job_id;
      requestNotifyPermission();
      await refreshAiJobs();
      modelStatus.textContent = `задание #${job.job_id} в очереди`;
      while (true) {
        await wait(2000);
        const jobStatus = await api(`/api/model/diagnose/jobs/${job.job_id}`);
        refreshAiJobs().catch(() => {});
        const item = jobStatus.job || {};
        if (item.status === "queued") {
          modelStatus.textContent = `задание #${item.id} ожидает`;
          continue;
        }
        if (item.status === "running") {
          modelStatus.textContent = `задание #${item.id} выполняется`;
          continue;
        }
        response = jobStatus.result || {ok: false, error: item.error || "AI-задание завершилось без результата"};
        if (!response.ok) throw new Error(response.error || "AI-анализ завершился ошибкой");
        break;
      }
      modelPreview.textContent = JSON.stringify(response.parsed || response.response, null, 2);
      fillModelOutput(response.parsed);
      renderModelOutput(response.parsed, response);
      showReviewForm(response.request_id, null);
      openModelResultModal();
      lastModelDataFingerprint = requestFingerprint;
      setHtmlExportAvailable(true);
      const seconds = (Number(response.duration_ms || 0) / 1000).toFixed(1);
      const waited = Number(response.queue_wait_ms || 0) > 0 ? ` · очередь ${(Number(response.queue_wait_ms) / 1000).toFixed(1)} с` : "";
      modelStatus.textContent = `результат готов за ${seconds} с${waited}`;
      modelStatus.className = "pill ok";
      if (queueStatus) queueStatus.className = "pill hidden";
      updateWorkflow(patientData);
      toast("Результат AI-анализа готов");
    } catch (err) {
      const resultWasSaved = Boolean(response?.request_id);
      if (!resultWasSaved) {
        modelPreview.textContent = err.message;
        showAiErrorCard(err.message);
      }
      modelStatus.textContent = resultWasSaved ? "результат сохранён · ошибка отображения" : "ошибка AI-анализа";
      modelStatus.className = "pill error";
      if (resultWasSaved) {
        currentModelRequestId = response.request_id;
        setHtmlExportAvailable(true);
      }
      if (queueStatus) queueStatus.className = "pill hidden";
      toast(resultWasSaved ? `Результат сохранён, но не отображён: ${err.message}` : err.message);
    } finally {
      if (diagnosisQueueTimer) window.clearInterval(diagnosisQueueTimer);
      diagnosisQueueTimer = null;
      awaitedDiagnosisJobId = null;
      markTitleReady();
      notifyDesktop(
        response?.ok ? "Результат AI-анализа готов" : "AI-анализ завершился",
        response?.ok ? "Откройте вкладку CVD Web, чтобы посмотреть результат." : "Проверьте статус задания в рабочем месте."
      );
      button.disabled = false;
      button.textContent = idleButtonText;
      updateWorkflow(updatePreview());
    }
  }

  function requestErrorText() {
    return "AI-анализ завершился ошибкой. Повторите запрос или обратитесь к администратору.";
  }

  function aiErrorAdviceText(message) {
    const text = String(message || "").toLowerCase();
    if (text.includes("недоступ") || text.includes("connection") || text.includes("unreachable")) {
      return "Похоже, сервис AI не запущен или недоступен по сети. Убедитесь, что LM Studio работает и модель загружена, затем повторите. Если ошибка повторяется — сообщите администратору.";
    }
    if (text.includes("не ответила") || text.includes("timeout")) {
      return "Модель не успела ответить за отведённое время. Повторите попытку; при повторении администратор может увеличить таймаут или разгрузить очередь.";
    }
    if (text.includes("очеред")) {
      return "Очередь AI сейчас переполнена. Подождите немного и повторите запрос.";
    }
    return "Повторите попытку. Если ошибка повторяется — сообщите администратору: диагностика доступна в Админке, раздел «Настройки».";
  }

  function showAiErrorCard(message) {
    const card = document.getElementById("aiErrorCard");
    if (!card) return;
    document.getElementById("aiErrorText").textContent = message || "Неизвестная ошибка";
    document.getElementById("aiErrorAdvice").textContent = aiErrorAdviceText(message);
    card.classList.remove("hidden");
    card.scrollIntoView({behavior: "smooth", block: "nearest"});
  }

  function hideAiErrorCard() {
    document.getElementById("aiErrorCard")?.classList.add("hidden");
  }

  async function openCase(caseId) {
    const response = await api(`/api/cases/${caseId}`);
    currentCaseId = response.case.id;
    resetModelState();
    applyData(response.case.data);
    collapseAllSections();
    hideRecentCases();
    toast("Кейс загружен");
  }

  function hideRecentCases() {
    document.getElementById("recentCases")?.classList.add("hidden");
  }

  async function showRecentCases() {
    const container = document.getElementById("recentCases");
    const list = document.getElementById("recentCasesList");
    if (!container || !list) return;
    const response = await api("/api/cases?limit=5");
    const cases = response.cases || [];
    if (!cases.length) return;
    list.innerHTML = "";
    cases.forEach((item) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "recent-case-chip";
      const title = document.createElement("strong");
      title.textContent = item.title || `Кейс #${item.id}`;
      const meta = document.createElement("small");
      const quality = item.quality || {};
      const updated = new Date(item.updated_at).toLocaleString("ru-RU", {day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit"});
      meta.textContent = `#${item.id} · готовность ${quality.readiness_percent || 0}% · ${updated}`;
      chip.append(title, meta);
      chip.addEventListener("click", () => openCase(item.id).catch((err) => toast(err.message)));
      list.appendChild(chip);
    });
    container.classList.remove("hidden");
  }

  function openRequestResult(item) {
    openTab("model");
    currentModelRequestId = item.id;
    lastModelDataFingerprint = qualityRules.dataFingerprint(collectData());
    modelStatus.textContent = item.status === "success"
      ? item.ai_result_stale ? "данные изменены после AI" : "ответ из истории"
      : "ошибка из истории";
    modelStatus.className = `pill ${item.status === "success" ? item.ai_result_stale ? "warning" : "ok" : "error"}`;
    modelPreview.textContent = JSON.stringify(item.parsed_output || {error: requestErrorText()}, null, 2);
    renderModelOutput(item.parsed_output || {}, item);
    showReviewForm(item.id, item.review);
    setHtmlExportAvailable(item.status === "success");
    updateWorkflow(updatePreview());
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
    renderImportReviewSummary(counts, rows.length);
    renderImportDiff();
    openModalElement(importModal, document.getElementById("closeImportModal"));
  }

  function renderImportReviewSummary(counts, total) {
    const node = document.getElementById("importReviewSummary");
    if (!node) return;
    node.innerHTML = "";
    [
      ["Всего", total, ""],
      ["Новые", counts.new || 0, "ok"],
      ["Конфликты", (counts.conflict || 0) + (counts["source-conflict"] || 0), "warning"],
      ["Без изменений", counts.same || 0, ""]
    ].forEach(([label, value, kind]) => {
      const item = document.createElement("div");
      item.className = `import-review-card ${kind}`.trim();
      const strong = document.createElement("strong");
      strong.textContent = String(value);
      const span = document.createElement("span");
      span.textContent = label;
      item.append(strong, span);
      node.appendChild(item);
    });
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
      row.decision = null;
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
      const decision = document.createElement("small");
      decision.className = row.checkbox?.checked ? "ok-text" : "muted";
      decision.textContent = checkbox.checked ? "будет применено" : row.state === "same" ? "пропущено: совпадает" : "оставить текущее";
      row.decision = decision;
      sourceCell.append(confidence, decision);

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
    pendingImport?.rows.forEach((row) => {
      if (!row.decision) return;
      row.decision.className = row.checkbox?.checked ? "ok-text" : "muted";
      row.decision.textContent = row.checkbox?.checked
        ? "будет применено"
        : row.state === "same" ? "пропущено: совпадает" : "оставить текущее";
    });
  }

  function selectNewImportFields() {
    pendingImport?.rows.forEach((row) => {
      if (row.checkbox && !row.checkbox.disabled) row.checkbox.checked = shouldAutoSelectImportRow(row);
    });
    updateImportSelection();
  }

  function selectConflictedImportFields() {
    pendingImport?.rows.forEach((row) => {
      if (row.checkbox && !row.checkbox.disabled) row.checkbox.checked = ["conflict", "source-conflict"].includes(row.state);
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
    closeModalElement(structureTextModal);
  }

  function setStructureTextBusy(busy) {
    structureTextBusy = busy;
    document.getElementById("submitStructureTextButton").disabled = busy;
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
      const eta = structureQueueState.estimated_wait_ms ? ` · ${queueEtaText(structureQueueState.estimated_wait_ms)}` : "";
      structureTextStatus.textContent = `в очереди · позиция ${structureQueueState.position}${eta} · ${minutes}:${seconds}`;
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
    structureTextStatus.className = "pill warning";
    try {
      const job = await api("/api/model/structure-text/jobs", {
        method: "POST",
        body: JSON.stringify({text})
      });
      structureTextStatus.textContent = `задание #${job.job_id} в очереди`;
      structureTextStatus.className = "pill warning";
      requestNotifyPermission();
      stopStructureTextProgress();
      setStructureTextBusy(false);
      closeStructureTextModal();
      structureTextInput.value = "";
      updateStructureTextCounter();
      await refreshAiJobs();
      toast(`Подготовка текста поставлена в очередь: #${job.job_id}`);
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
      scheduleDraftSave(updatePreview());
      setSaveState(currentCaseId ? `кейс #${currentCaseId} изменён импортом` : "импортировано · не сохранено", true);
      closeImportModal();
      toast(`Импортировано полей: ${selected.length}`);
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
    const ready = requiredDataPoints.length - missing.length;
    const readinessPercent = Math.round((ready / requiredDataPoints.length) * 100);
    const signalRows = Array.from(signalsPanel.querySelectorAll(".signal-row"));
    const signals = signalRows.map((node) => node.textContent.trim());
    const cards = [
      ["Пациент", displayValue(getValue(data, "GENERAL_INFO.Full_name"))],
      ["Случай", displayValue(getValue(data, "GENERAL_INFO.Patient_ID"))],
      ["Возраст / пол", `${displayValue(getValue(data, "GENERAL_INFO.Age"), "?")} / ${displayValue(getValue(data, "GENERAL_INFO.Sex"), "?")}`],
      ["Готовность", `${readinessPercent}%`],
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
    lastModelDataFingerprint = null;
    setHtmlExportAvailable(false);
    hideAiErrorCard();
    if (clearFields) {
      const modelSection = window.CVD_SCHEMA.find((section) => section.key === "MODEL_OUTPUT");
      modelSection?.fields.forEach((field) => setFieldValue(`MODEL_OUTPUT.${field.key}`, null));
    }
    modelPreview.textContent = "Технический ответ AI появится здесь.";
    modelStructured.textContent = "Структурированный ответ появится после AI-анализа.";
    lastModelSummary?.classList.add("hidden");
    if (lastModelSummary) lastModelSummary.innerHTML = "";
    modelStatus.textContent = "AI не запускался";
    modelStatus.className = "pill";
    requestReviewForm?.classList.add("hidden");
  }

  function resetCase() {
    currentCaseId = null;
    form.reset();
    collapseAllSections();
    resetModelState();
    clearLocalDraft();
    updatePreview();
    setSaveState("не сохранено", false);
  }

  function setupTabs() {
    document.querySelectorAll(".tab").forEach((button) => {
      button.addEventListener("click", () => openTab(button.dataset.tab));
    });
  }

  function applyInterfaceMode(mode) {
    const nextMode = ["doctor", "researcher", "admin"].includes(mode) ? mode : "doctor";
    document.body.dataset.interfaceMode = nextMode;
    try { localStorage.setItem("cvd:interface-mode", nextMode); } catch (_) {}
    document.getElementById("interfaceModeSelect")?.querySelectorAll("option").forEach((option) => {
      option.selected = option.value === nextMode;
    });
    if (nextMode === "doctor") openTab("quality");
  }

  function setupUser() {
    const user = window.CURRENT_USER || {};
    document.getElementById("userLabel").textContent = `${user.email || ""} · ${user.role || ""}`;
    if (user.role === "admin") {
      document.getElementById("adminLink").classList.remove("hidden");
    } else {
      document.querySelector('#interfaceModeSelect option[value="admin"]')?.remove();
    }
    let savedMode = "doctor";
    try { savedMode = localStorage.getItem("cvd:interface-mode") || "doctor"; } catch (_) {}
    if (savedMode === "admin" && user.role !== "admin") savedMode = "doctor";
    applyInterfaceMode(savedMode);
    document.getElementById("interfaceModeSelect")?.addEventListener("change", (event) => applyInterfaceMode(event.target.value));
    document.getElementById("changePasswordButton").addEventListener("click", () => openPasswordModal(false));
    if (user.must_change_password) openPasswordModal(true);
    document.getElementById("closePasswordModal").addEventListener("click", closePasswordModal);
    document.getElementById("cancelPasswordModal").addEventListener("click", closePasswordModal);
    document.getElementById("reviewButton").addEventListener("click", () => openReviewModal(null, false));
    document.getElementById("closeModelResultModal")?.addEventListener("click", closeModelResultModal);
    document.getElementById("closeModelResultFooter")?.addEventListener("click", closeModelResultModal);
    modelResultModal?.addEventListener("click", (event) => {
      if (event.target === modelResultModal) closeModelResultModal();
    });
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
    document.getElementById("selectConflictsImportButton").addEventListener("click", selectConflictedImportFields);
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
      else if (modal === modelResultModal) closeModelResultModal();
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
      // Draft is already in localStorage; do not double-warn on intentional logout.
      hasUnsavedChanges = false;
      window.location.href = response.redirect || "/login";
    });
  }

  function openPasswordModal(forced = false) {
    passwordChangeForced = Boolean(forced);
    passwordForm.reset();
    updatePasswordStrength();
    document.getElementById("passwordForcedNotice")?.classList.toggle("hidden", !passwordChangeForced);
    document.getElementById("closePasswordModal")?.classList.toggle("hidden", passwordChangeForced);
    document.getElementById("cancelPasswordModal")?.classList.toggle("hidden", passwordChangeForced);
    openModalElement(passwordModal, passwordForm.current_password);
  }

  function closePasswordModal() {
    if (passwordChangeForced) return;
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
      passwordChangeForced = false;
      if (window.CURRENT_USER) window.CURRENT_USER.must_change_password = false;
      closePasswordModal();
      toast("Пароль изменён");
  }

  async function initializeWorkspace() {
    const params = new URLSearchParams(window.location.search);
    if (params.get("import")) {
      const importButton = document.getElementById("importJsonButton");
      importButton?.classList.add("attention");
      importButton?.scrollIntoView({block: "center"});
      toast("Нажмите «Импорт», чтобы выбрать файл JSON, FHIR или CDA");
    }
    const caseId = Number(params.get("case") || 0);
    const requestId = Number(params.get("request") || 0);
    if (Number.isInteger(caseId) && caseId > 0) {
      await openCase(caseId);
    }
    if (Number.isInteger(requestId) && requestId > 0) {
      const response = await api(`/api/requests/${requestId}`);
      openRequestResult(response.request);
    }
    if (!caseId && !requestId) {
      showRecentCases().catch(() => {});
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
    const data = updatePreview();
    scheduleDraftSave(data);
    setHtmlExportAvailable(false);
    hideRecentCases();
    setSaveState(currentCaseId ? `кейс #${currentCaseId} изменён` : "не сохранено", true);
  });
  window.addEventListener("beforeunload", (event) => {
    if (!hasUnsavedChanges) return;
    window.clearTimeout(draftSaveTimer);
    try { writeLocalDraft(collectData()); } catch (_) {}
    event.preventDefault();
    event.returnValue = "";
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) document.title = baseDocumentTitle;
  });
  document.addEventListener("keydown", (event) => {
    const modKey = event.metaKey || event.ctrlKey;
    if (modKey && !event.shiftKey && !event.altKey && event.code === "KeyS") {
      event.preventDefault();
      saveCase().catch((err) => toast(err.message));
      return;
    }
    if (event.altKey && !modKey && event.code === "KeyN") {
      event.preventDefault();
      focusFirstMissing();
    }
  });
  restoreDraftButton?.addEventListener("click", restoreLocalDraft);
  dismissDraftButton?.addEventListener("click", () => draftBanner?.classList.add("hidden"));
  jumpMissingButton?.addEventListener("click", () => focusFirstMissing());
  document.getElementById("saveCaseButton").addEventListener("click", () => saveCase().catch((err) => toast(err.message)));
  document.getElementById("diagnoseButton").addEventListener("click", diagnose);
  document.getElementById("retryDiagnoseButton")?.addEventListener("click", () => {
    hideAiErrorCard();
    runDiagnose(updatePreview()).catch((err) => toast(err.message));
  });
  document.getElementById("downloadJsonButton").addEventListener("click", downloadJson);
  exportHtmlButton?.addEventListener("click", () => exportHtmlReport().catch((err) => toast(err.message)));
  viewResultButton?.addEventListener("click", () => viewHtmlResult());
  document.getElementById("importJsonButton").addEventListener("click", (event) => {
    event.currentTarget.classList.remove("attention");
    importJsonInput.click();
  });
  importJsonInput.addEventListener("change", () => {
    const file = importJsonInput.files?.[0];
    importJson(file).catch((err) => toast(err.message)).finally(() => {
      importJsonInput.value = "";
    });
  });
  document.getElementById("downloadFhirButton").addEventListener("click", () => downloadFHIR().catch((err) => toast(err.message)));
  document.getElementById("newCaseButton").addEventListener("click", resetCase);
  document.getElementById("demoCaseButton")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const response = await api("/api/cases/demo", {method: "POST", body: "{}"});
      await openCase(response.case_id);
      toast("Демо-кейс создан: данные синтетические");
    } catch (err) {
      toast(err.message);
    } finally {
      button.disabled = false;
    }
  });
  updatePreview();
  initDraftRestore();
  refreshAiJobs().catch(() => {});
  activeJobsTimer = window.setInterval(() => {
    refreshAiJobs().catch(() => {});
  }, 5000);
  initializeWorkspace().catch((err) => toast(err.message));
})();
