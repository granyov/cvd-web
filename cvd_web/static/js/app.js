(function () {
  "use strict";

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const form = document.getElementById("caseForm");
  const jsonPreview = document.getElementById("jsonPreview");
  const modelPreview = document.getElementById("modelPreview");
  const modelStructured = document.getElementById("modelStructured");
  const workflowCockpit = document.getElementById("workflowCockpit");
  const caseStatusText = document.getElementById("caseStatusText");
  const saveStateText = document.getElementById("saveStateText");
  const readinessStatusText = document.getElementById("readinessStatusText");
  const aiStatusText = document.getElementById("aiStatusText");
  const workflowProgressBar = document.getElementById("workflowProgressBar");
  const nextActionButton = document.getElementById("nextActionButton");
  const workspaceStart = document.getElementById("workspaceStart");
  const formArea = document.getElementById("formArea");
  const sectionNav = document.getElementById("sectionNav");
  const missingOnlyToggle = document.getElementById("missingOnlyToggle");
  const missingOnlyNotice = document.getElementById("missingOnlyNotice");
  const readinessCount = document.getElementById("readinessCount");
  const modelResultSubtitle = document.getElementById("modelResultSubtitle");
  const commandPalette = document.getElementById("commandPalette");
  const commandPaletteInput = document.getElementById("commandPaletteInput");
  const commandPaletteList = document.getElementById("commandPaletteList");
  const taskCountBadge = document.getElementById("taskCountBadge");
  const activeJobsLine = document.getElementById("activeJobsLine");
  const openTaskCenterButton = document.getElementById("openTaskCenterButton");
  const taskCenterModal = document.getElementById("taskCenterModal");
  const taskCenterSummary = document.getElementById("taskCenterSummary");
  const taskCenterList = document.getElementById("taskCenterList");
  const icdSummary = document.getElementById("icdSummary");
  const patientSnapshot = document.getElementById("patientSnapshot");
  const readinessPanel = document.getElementById("readinessPanel");
  const signalsPanel = document.getElementById("signalsPanel");
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
  const draftBanner = document.getElementById("draftBanner");
  const draftBannerText = document.getElementById("draftBannerText");
  const restoreDraftButton = document.getElementById("restoreDraftButton");
  const dismissDraftButton = document.getElementById("dismissDraftButton");
  const lastModelSummary = document.getElementById("lastModelSummary");
  const saveCaseButton = document.getElementById("saveCaseButton");
  const scenarioSelect = document.getElementById("scenarioSelect");
  const scenarioHint = document.getElementById("scenarioHint");
  const fieldSearchInput = document.getElementById("fieldSearchInput");
  const fieldSearchResults = document.getElementById("fieldSearchResults");
  const doctorDiagnosisWorkbench = document.getElementById("doctorDiagnosisWorkbench");
  const aiDiagnosisWorkbench = document.getElementById("aiDiagnosisWorkbench");
  const acceptModelDraftButton = document.getElementById("acceptModelDraftButton");
  const copyModelDiagnosisButton = document.getElementById("copyModelDiagnosisButton");
  const openModelReportButton = document.getElementById("openModelReportButton");
  const importDecisionPanel = document.getElementById("importDecisionPanel");
  const importFactReview = document.getElementById("importFactReview");
  const importDiffDetails = document.getElementById("importDiffDetails");
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
  let activeJobsTimer = null;
  let draftSaveTimer = null;
  let suppressDraftSave = false;
  let pendingDraft = null;
  let hasUnsavedChanges = false;
  let passwordChangeForced = false;
  let selectedScenarioKey = "general";
  let lastModelParsed = null;
  let lastModelMeta = {};
  let modelStatusText = "AI не запускался";
  let modelStatusKind = "";
  // Сессии кейсов, в которых сейчас идёт AI-анализ: результат принадлежит своему кейсу.
  const aiRunningSessions = new Set();
  let currentModelRequestOk = false;
  let resultStaleOnServer = false;
  let resultOpened = false;
  let caseReadOnly = false;
  let manualEntry = false;
  let missingOnly = false;
  // Автосохранение: пауза после ввода и минимальный интервал между записями,
  // потому что каждое сохранение кейса попадает в журнал аудита.
  const autosaveDelayMs = 2500;
  const autosaveMinIntervalMs = 15000;
  let autosaveTimer = null;
  let saveQueue = Promise.resolve();
  let saveInFlight = null;
  let inFlightSnapshot = null;
  let lastSavedAt = null;
  let lastSaveAttemptAt = 0;
  let saveErrorText = "";
  // Растёт при переключении кейса: ответ сохранения от прежнего кейса не должен менять текущий.
  let caseSession = 0;
  const sectionNodes = new Map();
  const groupHeaderNodes = new Map();
  let extraSectionsNode = null;
  let sectionObserver = null;
  const baseDocumentTitle = document.title;
  const knownJobStatuses = new Map();
  let jobStatusesPrimed = false;
  const awaitedDiagnosisJobIds = new Set();
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
  // Секции с преимущественно числовыми полями показываются плотной сеткой.
  const denseSectionKeys = new Set([
    "PHYSICAL_EXAM", "LABS_CBC", "LABS_BIOCHEM", "LABS_LIPIDS",
    "LABS_CARDIAC_MARKERS", "LABS_COAGULATION", "ECHOCARDIOGRAPHY",
    "FUNCTIONAL_TESTS", "SCORES_AND_CLASSES"
  ]);
  const commonQuickPaths = [
    "GENERAL_INFO.Patient_ID",
    "GENERAL_INFO.Age",
    "GENERAL_INFO.Sex",
    "COMPLAINTS.Main_complaint",
    "PHYSICAL_EXAM.Blood_pressure_right_systolic_mmHg",
    "PHYSICAL_EXAM.Blood_pressure_right_diastolic_mmHg",
    "PHYSICAL_EXAM.Heart_rate_bpm",
    "ECG_AND_BP_MONITORING.Resting_ECG_summary",
    "FINAL_DIAGNOSES.Main_cardiovascular_diagnosis_text",
    "FINAL_DIAGNOSES.ICD10_codes"
  ];
  const clinicalScenarios = [
    {
      key: "general",
      title: "Общий кардиологический кейс",
      hint: "Базовый набор для первичного анализа и архивации.",
      quickPaths: commonQuickPaths,
      requiredPaths: []
    },
    {
      key: "acs",
      title: "ИБС / ОКС",
      hint: "Акцент на боли в груди, ЭКГ, тропонине, коронарной визуализации и антиагрегантах.",
      quickPaths: [
        ...commonQuickPaths,
        "LABS_CARDIAC_MARKERS.Troponin_ng_L",
        "LABS_LIPIDS.LDL_mmol_L",
        "CORONARY_AND_VASCULAR_IMAGING.Coronary_angiography_or_CTCA",
        "CURRENT_MEDICATIONS.Antiplatelets"
      ],
      requiredPaths: [
        ["LABS_CARDIAC_MARKERS.Troponin_ng_L", "Тропонин"],
        ["CORONARY_AND_VASCULAR_IMAGING.Coronary_angiography_or_CTCA", "Коронарография / КТКА"]
      ]
    },
    {
      key: "hf",
      title: "ХСН",
      hint: "Акцент на одышке, ФВ ЛЖ, NT-proBNP, СКФ, калии и терапии ХСН.",
      quickPaths: [
        ...commonQuickPaths,
        "ECHOCARDIOGRAPHY.LVEF_percent",
        "LABS_CARDIAC_MARKERS.NT_proBNP_pg_ml",
        "LABS_BIOCHEM.eGFR_ml_min_1_73m2",
        "LABS_BIOCHEM.K_mmol_L",
        "CURRENT_MEDICATIONS.ACEi_ARB_ARNI",
        "CURRENT_MEDICATIONS.Beta_blockers",
        "CURRENT_MEDICATIONS.SGLT2_inhibitors"
      ],
      requiredPaths: [
        ["ECHOCARDIOGRAPHY.LVEF_percent", "ФВ ЛЖ"],
        ["LABS_CARDIAC_MARKERS.NT_proBNP_pg_ml", "NT-proBNP"],
        ["LABS_BIOCHEM.K_mmol_L", "Калий"]
      ]
    },
    {
      key: "arrhythmia",
      title: "Аритмии",
      hint: "Акцент на ЭКГ/Холтере, ЧСС, антикоагулянтах и тромбоэмболическом риске.",
      quickPaths: [
        ...commonQuickPaths,
        "ECG_AND_BP_MONITORING.Holter_ECG_summary",
        "SCORES_AND_CLASSES.CHA2DS2_VASc",
        "SCORES_AND_CLASSES.HAS_BLED",
        "CURRENT_MEDICATIONS.Anticoagulants",
        "CURRENT_MEDICATIONS.Antiarrhythmics"
      ],
      requiredPaths: [
        ["ECG_AND_BP_MONITORING.Holter_ECG_summary", "Холтер-ЭКГ"],
        ["SCORES_AND_CLASSES.CHA2DS2_VASc", "CHA2DS2-VASc"]
      ]
    },
    {
      key: "hypertension",
      title: "Артериальная гипертензия",
      hint: "Акцент на АД, СМАД, факторах риска, почечной функции и терапии.",
      quickPaths: [
        ...commonQuickPaths,
        "ECG_AND_BP_MONITORING.ABPM_summary",
        "LABS_BIOCHEM.Creatinine_umol_L",
        "LABS_BIOCHEM.eGFR_ml_min_1_73m2",
        "LABS_LIPIDS.LDL_mmol_L",
        "CURRENT_MEDICATIONS.ACEi_ARB_ARNI",
        "CURRENT_MEDICATIONS.Diuretics"
      ],
      requiredPaths: [
        ["ECG_AND_BP_MONITORING.ABPM_summary", "СМАД"],
        ["LABS_BIOCHEM.Creatinine_umol_L", "Креатинин"]
      ]
    },
    {
      key: "valves",
      title: "Клапанные пороки",
      hint: "Акцент на ЭхоКГ, легочной гипертензии, вмешательствах и симптомах.",
      quickPaths: [
        ...commonQuickPaths,
        "ECHOCARDIOGRAPHY.LVEF_percent",
        "ECHOCARDIOGRAPHY.PASP_mmHg",
        "ECHOCARDIOGRAPHY.Valvular_regurgitation",
        "ECHOCARDIOGRAPHY.Mitral_valve_area_cm2",
        "ECHOCARDIOGRAPHY.Aortic_valve_area_cm2",
        "DEVICES_AND_PROCEDURES.Valve_surgery_or_prosthesis"
      ],
      requiredPaths: [
        ["ECHOCARDIOGRAPHY.Valvular_regurgitation", "Клапанные регургитации"],
        ["ECHOCARDIOGRAPHY.PASP_mmHg", "PASP"]
      ]
    }
  ];
  const scenarioByKey = new Map(clinicalScenarios.map((scenario) => [scenario.key, scenario]));

  function toast(message, options) {
    return window.CVDUI.toast(message, options);
  }

  function pill(text, kind = "") {
    const node = document.createElement("span");
    node.className = `pill ${kind}`.trim();
    node.textContent = text;
    return node;
  }

  // Новый кейс создаётся на сервере автоматически, только когда в нём есть что-то опознаваемое:
  // иначе случайное нажатие клавиши плодило бы пустые кейсы в архиве.
  function canAutoCreateCase(data) {
    return ["GENERAL_INFO.Patient_ID", "GENERAL_INFO.Full_name", "COMPLAINTS.Main_complaint"]
      .some((path) => isFilled(getValue(data, path)));
  }

  function setSaveState(_label, unsaved) {
    hasUnsavedChanges = Boolean(unsaved);
    if (hasUnsavedChanges) scheduleAutosave();
    syncStatusBar();
  }

  const readOnlyText = "Кейс другого пользователя открыт только для просмотра — изменения не сохраняются";

  function saveStateLabel(data) {
    if (caseReadOnly) return [hasUnsavedChanges ? "только просмотр · изменения не сохраняются" : "только просмотр", "warning"];
    if (saveErrorText) return [`не сохранено: ${saveErrorText}`, "error"];
    if (saveInFlight) return ["сохранение…", ""];
    if (hasUnsavedChanges) {
      return currentCaseId || canAutoCreateCase(data)
        ? ["изменения сохранятся автоматически", ""]
        : ["черновик · сохранится после ввода ID, ФИО или жалобы", "warning"];
    }
    if (lastSavedAt) return [`сохранено ${window.CVDUI.relativeTime(lastSavedAt)}`, "ok"];
    return currentCaseId ? ["сохранён", "ok"] : ["черновик", ""];
  }

  function syncStatusBar(data = null) {
    if (!caseStatusText) return;
    const snapshot = data || (form ? collectData() : {});
    const required = scenarioRequiredDataPoints();
    const missing = missingRequiredData(snapshot);
    const ready = required.length - missing.length;
    const percent = required.length ? Math.round((ready / required.length) * 100) : 0;
    caseStatusText.textContent = currentCaseId ? `Кейс #${currentCaseId}` : "Новый кейс";
    if (saveStateText) {
      const [label, kind] = saveStateLabel(snapshot);
      saveStateText.textContent = label;
      saveStateText.className = `cockpit-meta ${kind}`.trim();
    }
    if (readinessStatusText) {
      readinessStatusText.textContent = `ключевые ${ready} из ${required.length}`;
      readinessStatusText.className = `cockpit-meta ${missing.length ? "" : "ok"}`.trim();
    }
    if (aiStatusText) {
      aiStatusText.textContent = modelStatusText;
      aiStatusText.className = `cockpit-meta ${modelStatusKind}`.trim();
    }
    if (workflowProgressBar) {
      workflowProgressBar.style.width = `${percent}%`;
      workflowProgressBar.classList.toggle("ok", percent === 100);
    }
  }

  function setModelStatus(text, kind = "") {
    modelStatusText = text;
    modelStatusKind = kind;
    syncStatusBar();
  }

  function scheduleAutosave() {
    window.clearTimeout(autosaveTimer);
    if (!hasUnsavedChanges || caseReadOnly) return;
    const sinceLastAttempt = Date.now() - lastSaveAttemptAt;
    const delay = Math.max(autosaveDelayMs, autosaveMinIntervalMs - sinceLastAttempt);
    autosaveTimer = window.setTimeout(() => {
      autosave().catch(() => {});
    }, delay);
  }

  async function autosave(options = {}) {
    if (!hasUnsavedChanges || caseReadOnly) return;
    if (!currentCaseId && !canAutoCreateCase(collectData())) {
      syncStatusBar();
      return;
    }
    // Ошибку уже показала строка статуса, а повтор запланировал saveCase.
    await saveCase({silent: true, ...options}).catch(() => {});
  }

  // Перед сменой кейса незаписанные изменения сохраняются, а не теряются.
  async function flushAutosave() {
    window.clearTimeout(autosaveTimer);
    if (caseReadOnly) return;
    await saveQueue;
    if (hasUnsavedChanges && (currentCaseId || canAutoCreateCase(collectData()))) {
      await saveCase({silent: true});
    }
  }

  // Сохраняет правки перед уходом с кейса. Если сохранить не удалось, спрашивает, уходить ли:
  // правки тогда остаются только в локальном черновике.
  async function flushBeforeLeaving(actionText) {
    try {
      await flushAutosave();
      return {ok: true, saved: true};
    } catch (err) {
      window.clearTimeout(draftSaveTimer);
      writeLocalDraft(collectData());
      const proceed = await window.CVDUI.confirm({
        title: "Изменения не сохранены на сервере",
        message: `${window.CVDUI.humanizeError(err)} Если ${actionText} сейчас, правки останутся только в локальном черновике этого браузера, и новый ввод его перезапишет.`,
        confirmLabel: "Всё равно продолжить",
        cancelLabel: "Остаться",
        destructive: true
      });
      return {ok: proceed, saved: false};
    }
  }

  // 408 и 429 — временные, 409 — кейс занят пакетной обработкой; остальные 4xx повтором не исправить.
  function isRetryableSaveError(err) {
    const status = Number(err?.status || 0);
    return !status || status >= 500 || [408, 409, 425, 429].includes(status);
  }

  // keepalive-запрос браузер ограничивает 64 КБ тела; кириллица занимает по два байта на символ.
  function fitsKeepalive(body) {
    return new TextEncoder().encode(body).length <= 60000;
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
      const error = new Error(data.error || `HTTP ${response.status}`);
      error.status = response.status;
      throw error;
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

  function normalizeSearchText(value) {
    return String(value || "").toLowerCase().replace(/\s+/g, " ").trim();
  }

  function selectedScenario() {
    return scenarioByKey.get(selectedScenarioKey) || clinicalScenarios[0];
  }

  function uniquePaths(paths) {
    return Array.from(new Set((paths || []).filter(Boolean)));
  }

  function fieldMeta(path) {
    const [sectionKey, fieldKey] = String(path || "").split(".");
    const section = window.CVD_SCHEMA.find((item) => item.key === sectionKey);
    const field = section?.fields.find((item) => item.key === fieldKey);
    if (!section || !field) return null;
    return {path, section, field, sectionKey, fieldKey};
  }

  function scenarioRequiredDataPoints() {
    const base = requiredDataPoints.map(([path, label]) => [path, label]);
    selectedScenario().requiredPaths.forEach(([path, label]) => {
      if (!base.some(([existingPath]) => existingPath === path)) base.push([path, label]);
    });
    return base;
  }

  function scenarioMissingRequiredData(data) {
    return scenarioRequiredDataPoints().filter(([path]) => !isFilled(getValue(data, path)));
  }

  function renderField(section, field) {
    const wrapper = document.createElement("div");
    wrapper.className = field.type === "textarea" ? "field full" : "field";

    const id = fieldId(section.key, field.key);
    const label = document.createElement("label");
    label.htmlFor = id;
    // У числовых полей единица измерения из подписи переезжает суффиксом в само поле.
    let labelText = field.label;
    let unit = "";
    if (field.type === "number" && field.label.includes(", ")) {
      const unitIndex = field.label.lastIndexOf(", ");
      const candidate = field.label.slice(unitIndex + 2);
      // Длинные единицы (СКФ и т.п.) не влезают суффиксом — остаются в подписи.
      if (candidate.length <= 10) {
        labelText = field.label.slice(0, unitIndex);
        unit = candidate;
      }
    }
    label.textContent = labelText;

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
    if (unit) {
      const unitWrap = document.createElement("div");
      unitWrap.className = "input-unit";
      const unitLabel = document.createElement("span");
      unitLabel.textContent = unit;
      unitWrap.append(input, unitLabel);
      wrapper.appendChild(unitWrap);
    } else {
      wrapper.appendChild(input);
    }
    const reference = qualityRules.referenceRanges?.[input.name];
    if (reference) {
      const hint = document.createElement("small");
      hint.className = "field-reference";
      hint.dataset.referenceFor = input.name;
      hint.textContent = `Референс: ${reference.text}`;
      wrapper.appendChild(hint);
      input.dataset.hasReference = "1";
    }
    const alert = document.createElement("small");
    alert.className = "field-alert hidden";
    alert.dataset.alertFor = input.name;
    wrapper.appendChild(alert);
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

  function fieldAlert(path, data) {
    const value = numericValue(data, path);
    const text = String(getValue(data, path) || "").toLowerCase();
    const alerts = {
      "PHYSICAL_EXAM.Blood_pressure_right_systolic_mmHg": () => value >= 180 ? ["critical", "Очень высокое систолическое АД: проверьте кризовый контекст."] : value > 0 && value < 90 ? ["critical", "Систолическое АД ниже 90: проверьте гемодинамику."] : null,
      "PHYSICAL_EXAM.Blood_pressure_right_diastolic_mmHg": () => value >= 120 ? ["critical", "Диастолическое АД 120 и выше: проверьте срочность ситуации."] : null,
      "PHYSICAL_EXAM.Heart_rate_bpm": () => value > 120 ? ["warning", "Выраженная тахикардия: сверьте ЭКГ и ритм."] : value > 0 && value < 50 ? ["warning", "Брадикардия: сверьте ритм, симптомы и терапию."] : null,
      "PHYSICAL_EXAM.SpO2_room_air_percent": () => value > 0 && value < 92 ? ["critical", "SpO2 ниже 92%: проверьте дыхательный статус."] : null,
      "LABS_CARDIAC_MARKERS.Troponin_ng_L": () => value > 14 ? ["warning", "Тропонин выше ориентировочного референса: важна динамика и единицы."] : null,
      "LABS_CARDIAC_MARKERS.NT_proBNP_pg_ml": () => value > 125 ? ["warning", "NT-proBNP повышен: сопоставьте с возрастом, СКФ и симптомами."] : null,
      "LABS_BIOCHEM.K_mmol_L": () => value >= 5.5 ? ["critical", "Калий высокий: проверьте риск аритмий и терапию."] : value > 0 && value < 3.5 ? ["warning", "Калий снижен: проверьте аритмогенный риск."] : null,
      "ECHOCARDIOGRAPHY.LVEF_percent": () => value > 0 && value < 40 ? ["warning", "ФВ ЛЖ ниже 40%: выделите контекст ХСН и терапию."] : null,
      "ECG_AND_BP_MONITORING.Resting_ECG_summary": () => text.includes("st") || text.includes("подъем") || text.includes("элевац") ? ["critical", "В ЭКГ-тексте есть признаки ST-изменений: проверьте ОКС-контекст."] : null
    };
    return alerts[path]?.() || null;
  }

  function updateFieldAlerts(data) {
    form.querySelectorAll("[data-alert-for]").forEach((node) => {
      const result = fieldAlert(node.dataset.alertFor, data);
      node.classList.toggle("hidden", !result);
      node.classList.toggle("critical", result?.[0] === "critical");
      node.classList.toggle("warning", result?.[0] === "warning");
      node.textContent = result?.[1] || "";
    });
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
    header.dataset.group = group.key;
    const title = document.createElement("strong");
    title.textContent = group.title;
    const hint = document.createElement("span");
    hint.textContent = group.hint;
    header.append(title, hint);
    return header;
  }

  function renderForm() {
    form.innerHTML = "";
    sectionNodes.clear();
    groupHeaderNodes.clear();
    window.CVD_SCHEMA.forEach((section, index) => {
      const group = sectionGroup(section);
      if (!groupHeaderNodes.has(group.key)) groupHeaderNodes.set(group.key, renderFormGroupHeader(group));
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
      number.textContent = sectionNumber(index);
      const title = document.createElement("span");
      title.textContent = section.title;
      heading.append(number, title);
      const badge = document.createElement("span");
      badge.className = "section-fill-badge";
      badge.dataset.sectionBadge = section.key;
      badge.textContent = "0%";
      summary.append(heading, badge);

      const body = document.createElement("div");
      body.className = `section-body form-grid${denseSectionKeys.has(section.key) ? " dense" : ""}`;
      section.fields.forEach((field) => body.appendChild(renderField(section, field)));

      details.appendChild(summary);
      details.appendChild(body);
      sectionNodes.set(section.key, details);
    });
    extraSectionsNode = document.createElement("details");
    extraSectionsNode.className = "extra-sections";
    const extraSummary = document.createElement("summary");
    const extraTitle = document.createElement("strong");
    extraTitle.dataset.extraTitle = "1";
    const extraHint = document.createElement("span");
    extraHint.dataset.extraHint = "1";
    extraSummary.append(extraTitle, extraHint);
    const extraBody = document.createElement("div");
    extraBody.className = "extra-sections-body";
    extraSectionsNode.append(extraSummary, extraBody);
    arrangeSections();
  }

  // Разделы, важные для профиля случая, всегда сверху. Остальные уходят в «Дополнительные разделы»,
  // но раздел с уже введёнными данными остаётся на виду: импорт не должен прятать заполненное.
  const alwaysPrimarySections = new Set(["GENERAL_INFO", "COMPLAINTS", "FINAL_DIAGNOSES"]);

  function scenarioSectionKeys(scenario = selectedScenario()) {
    const keys = new Set(alwaysPrimarySections);
    [
      ...scenario.quickPaths,
      ...scenario.requiredPaths.map(([path]) => path),
      ...requiredDataPoints.map(([path]) => path)
    ].forEach((path) => keys.add(String(path).split(".")[0]));
    return keys;
  }

  function arrangeSections(data = collectData()) {
    if (!extraSectionsNode) return;
    const primaryKeys = scenarioSectionKeys();
    const fragment = document.createDocumentFragment();
    const extraBody = extraSectionsNode.querySelector(".extra-sections-body");
    const extra = [];
    let currentGroupKey = "";
    window.CVD_SCHEMA.forEach((section) => {
      const node = sectionNodes.get(section.key);
      if (!node) return;
      const hasData = sectionFillPercent(section, data).filled > 0;
      const primary = section.key !== "MODEL_OUTPUT" && (primaryKeys.has(section.key) || hasData);
      node.dataset.primary = primary ? "1" : "0";
      if (!primary) {
        extra.push(node);
        return;
      }
      const group = sectionGroup(section);
      if (group.key !== currentGroupKey) {
        currentGroupKey = group.key;
        fragment.appendChild(groupHeaderNodes.get(group.key));
      }
      fragment.appendChild(node);
    });
    extraBody.replaceChildren(...extra);
    const visibleExtra = extra.filter((node) => node.id !== "section-MODEL_OUTPUT" || !isDoctorMode()).length;
    extraSectionsNode.querySelector("[data-extra-title]").textContent = `Дополнительные разделы · ${visibleExtra}`;
    extraSectionsNode.querySelector("[data-extra-hint]").textContent =
      `Не входят в профиль «${selectedScenario().title}». Раскройте, если данные есть.`;
    extraSectionsNode.classList.toggle("hidden", visibleExtra === 0);
    fragment.appendChild(extraSectionsNode);
    form.replaceChildren(fragment);
    renderSectionNav(data);
    if (missingOnly) applyMissingOnly(data);
  }

  function sectionMissingPaths(data) {
    const result = new Map();
    missingRequiredData(data).forEach(([path]) => {
      const sectionKey = String(path).split(".")[0];
      result.set(sectionKey, (result.get(sectionKey) || 0) + 1);
    });
    return result;
  }

  function renderSectionNav(data = collectData()) {
    if (!sectionNav) return;
    sectionNav.innerHTML = "";
    const groups = [["Разделы профиля", "1"], ["Дополнительно", "0"]];
    groups.forEach(([title, primaryFlag]) => {
      const entries = window.CVD_SCHEMA
        .map((section, index) => [section, index])
        .filter(([section]) => sectionNodes.get(section.key)?.dataset.primary === primaryFlag)
        .filter(([section]) => section.key !== "MODEL_OUTPUT" || !isDoctorMode());
      if (!entries.length) return;
      const heading = document.createElement("p");
      heading.className = "section-nav-heading";
      heading.textContent = title;
      sectionNav.appendChild(heading);
      entries.forEach(([section, index]) => {
        const link = document.createElement("button");
        link.type = "button";
        link.className = `section-nav-link ${primaryFlag === "0" ? "is-extra" : ""}`.trim();
        link.dataset.navSection = section.key;
        const number = document.createElement("span");
        number.className = "section-nav-number";
        number.textContent = sectionNumber(index);
        const label = document.createElement("span");
        label.className = "section-nav-label";
        label.textContent = section.title;
        const state = document.createElement("span");
        state.className = "section-nav-state";
        state.dataset.navState = section.key;
        link.append(number, label, state);
        link.addEventListener("click", () => {
          // Пока идёт плавная прокрутка, наблюдатель не перебивает выбранный раздел.
          navLockUntil = Date.now() + 900;
          focusSection(section.key);
        });
        sectionNav.appendChild(link);
      });
    });
    updateSectionNavStates(data);
    observeActiveSection();
  }

  function updateSectionNavStates(data) {
    if (!sectionNav) return;
    const missingBySection = sectionMissingPaths(data);
    window.CVD_SCHEMA.forEach((section) => {
      const state = sectionNav.querySelector(`[data-nav-state="${section.key}"]`);
      if (!state) return;
      const {filled, total, percent} = sectionFillPercent(section, data);
      const missing = missingBySection.get(section.key) || 0;
      state.className = `section-nav-state ${missing ? "warning" : percent === 100 ? "ok" : filled ? "partial" : ""}`.trim();
      state.textContent = missing ? "" : percent === 100 ? "✓" : filled ? `${filled}/${total}` : "";
      state.title = missing ? `Не заполнено ключевых полей: ${missing}` : "";
    });
  }

  let navLockUntil = 0;
  const visibleSections = new Set();

  function setActiveNav(key) {
    sectionNav?.querySelectorAll(".section-nav-link").forEach((link) => {
      const active = link.dataset.navSection === key;
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    });
  }

  // Подсветка раздела, который сейчас на экране, — как в оглавлении документа: верхний из видимых.
  function observeActiveSection() {
    if (!("IntersectionObserver" in window) || !sectionNav) return;
    sectionObserver?.disconnect();
    visibleSections.clear();
    sectionObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) visibleSections.add(entry.target);
        else visibleSections.delete(entry.target);
      });
      if (Date.now() < navLockUntil) return;
      const top = Array.from(visibleSections)
        .filter((node) => node.isConnected && node.getClientRects().length > 0)
        .sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top)[0];
      if (top) setActiveNav(top.id.replace(/^section-/, ""));
    }, {rootMargin: `-${stickyOffset()}px 0px -55% 0px`});
    sectionNodes.forEach((node) => sectionObserver.observe(node));
  }

  function stickyOffset() {
    const value = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--sticky-offset"));
    return Number.isFinite(value) && value > 0 ? Math.round(value) : 140;
  }

  // Высота шапки и строки статуса меняется (перенос строк, ширина окна) — отступы прилипания и
  // прокрутки к разделу берутся из реальных размеров, чтобы заголовок раздела не уходил под них.
  function updateStickyOffsets() {
    const root = document.documentElement;
    const topbar = document.querySelector(".topbar");
    const topbarHeight = topbar ? Math.ceil(topbar.getBoundingClientRect().height) : 56;
    const cockpitSticky = workflowCockpit && !workflowCockpit.classList.contains("hidden")
      && getComputedStyle(workflowCockpit).position === "sticky";
    const cockpitHeight = cockpitSticky ? Math.ceil(workflowCockpit.getBoundingClientRect().height) : 0;
    root.style.setProperty("--topbar-h", `${topbarHeight}px`);
    root.style.setProperty("--cockpit-h", `${cockpitHeight}px`);
    root.style.setProperty("--sticky-offset", `${topbarHeight + (cockpitHeight ? cockpitHeight + 24 : 12)}px`);
  }

  function watchStickyOffsets() {
    updateStickyOffsets();
    if ("ResizeObserver" in window) {
      const observer = new ResizeObserver(() => updateStickyOffsets());
      [document.querySelector(".topbar"), workflowCockpit].filter(Boolean).forEach((node) => observer.observe(node));
    }
    window.addEventListener("resize", updateStickyOffsets);
  }

  function applyMissingOnly(data = collectData()) {
    form.classList.toggle("missing-only", missingOnly);
    missingOnlyToggle?.setAttribute("aria-pressed", String(missingOnly));
    missingOnlyToggle?.classList.toggle("is-on", missingOnly);
    form.querySelectorAll(".is-missing, .has-missing").forEach((node) => node.classList.remove("is-missing", "has-missing"));
    if (!missingOnly) {
      missingOnlyNotice?.classList.add("hidden");
      return;
    }
    const missing = missingRequiredData(data);
    if (!missing.length) {
      missingOnly = false;
      form.classList.remove("missing-only");
      missingOnlyToggle?.setAttribute("aria-pressed", "false");
      missingOnlyToggle?.classList.remove("is-on");
      if (missingOnlyNotice) {
        missingOnlyNotice.textContent = "Все ключевые поля профиля заполнены — показана вся анкета.";
        missingOnlyNotice.className = "notice ok-note";
        window.setTimeout(() => missingOnlyNotice.classList.add("hidden"), 4000);
      }
      return;
    }
    // Набор полей фиксируется при включении фильтра: поле не исчезает из-под курсора, пока его заполняют.
    missing.forEach(([path]) => {
      const input = form.elements[path];
      input?.closest(".field")?.classList.add("is-missing");
      const details = input?.closest("details.section");
      if (details) {
        details.classList.add("has-missing");
        details.open = true;
      }
      const extra = input?.closest(".extra-sections");
      if (extra) {
        extra.classList.add("has-missing");
        extra.open = true;
      }
    });
    if (missingOnlyNotice) {
      missingOnlyNotice.textContent = `Показаны только незаполненные ключевые поля: ${missing.length}. Заполненные останутся на экране, пока фильтр включён.`;
      missingOnlyNotice.className = "notice info-note";
    }
  }

  function toggleMissingOnly(force) {
    missingOnly = typeof force === "boolean" ? force : !missingOnly;
    const data = collectData();
    applyMissingOnly(data);
    if (missingOnly) {
      const first = missingRequiredData(data)[0];
      if (first) focusFieldPath(first[0]);
    }
  }

  function updateScenarioHint() {
    if (!scenarioHint) return;
    const scenario = selectedScenario();
    const extraRequired = scenario.requiredPaths.length;
    // Профиль может добавлять обязательные поля — врач должен видеть, почему меняется готовность.
    scenarioHint.textContent = extraRequired ? `+${extraRequired} к ключевым` : "";
    scenarioHint.title = extraRequired
      ? `${scenario.hint} Добавлено в ключевые: ${scenario.requiredPaths.map(([, label]) => label).join(", ")}.`
      : scenario.hint;
    scenarioHint.classList.toggle("hidden", !extraRequired);
  }

  function setupScenarioTemplates() {
    if (!scenarioSelect) return;
    scenarioSelect.innerHTML = "";
    clinicalScenarios.forEach((scenario) => {
      const option = document.createElement("option");
      option.value = scenario.key;
      option.textContent = scenario.title;
      option.title = scenario.hint;
      scenarioSelect.appendChild(option);
    });
    try {
      selectedScenarioKey = localStorage.getItem("cvd:selected-scenario") || selectedScenarioKey;
    } catch (_) {}
    if (!scenarioByKey.has(selectedScenarioKey)) selectedScenarioKey = "general";
    scenarioSelect.value = selectedScenarioKey;
    scenarioSelect.addEventListener("change", () => {
      selectedScenarioKey = scenarioSelect.value;
      try { localStorage.setItem("cvd:selected-scenario", selectedScenarioKey); } catch (_) {}
      updateScenarioHint();
      arrangeSections(updatePreview());
      toast(`Профиль: ${selectedScenario().title}`);
    });
    updateScenarioHint();
    arrangeSections(collectData());
  }

  // В режиме врача раздел ответа модели скрыт, поэтому и в поиске его полей нет.
  function searchableSections() {
    return window.CVD_SCHEMA
      .map((section, sectionIndex) => ({section, sectionIndex}))
      .filter(({section}) => section.key !== "MODEL_OUTPUT" || !isDoctorMode());
  }

  function fieldSearchMatches(query) {
    const normalized = normalizeSearchText(query);
    if (normalized.length < 2) return [];
    return searchableSections().flatMap(({section, sectionIndex}) =>
      section.fields.map((field) => {
        const path = fieldPath(section.key, field.key);
        return {
          path,
          sectionIndex,
          section: section.title,
          label: field.label,
          haystack: normalizeSearchText(`${field.label} ${field.key} ${section.title} ${section.key} ${path}`)
        };
      })
    ).filter((item) => item.haystack.includes(normalized)).slice(0, 8);
  }

  function renderFieldSearchResults(query) {
    if (!fieldSearchResults) return;
    const matches = fieldSearchMatches(query);
    fieldSearchResults.innerHTML = "";
    fieldSearchResults.classList.toggle("hidden", matches.length === 0);
    matches.forEach((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "field-search-result";
      const label = document.createElement("strong");
      label.textContent = item.label;
      const meta = document.createElement("span");
      meta.textContent = `${sectionNumber(item.sectionIndex)}. ${item.section}`;
      button.append(label, meta);
      button.addEventListener("click", () => {
        fieldSearchInput.value = "";
        fieldSearchResults.classList.add("hidden");
        focusFieldPath(item.path);
      });
      fieldSearchResults.appendChild(button);
    });
  }

  // Фильтр «только незаполненные» прячет остальное; переход к скрытому разделу или полю его выключает.
  function revealThroughFilter(node, isTarget) {
    if (!missingOnly || !node || isTarget(node)) return;
    toggleMissingOnly(false);
    toast("Показана вся анкета, чтобы открыть выбранное поле");
  }

  // Фокус переводится с задержкой (после прокрутки); если за это время открыли окно, его не трогаем.
  function modalIsOpen() {
    return Boolean(document.querySelector(".modal:not(.hidden)"));
  }

  function focusSection(sectionKey, {focusInput = true} = {}) {
    const details = document.getElementById(`section-${sectionKey}`);
    if (!details) return;
    revealForm();
    revealThroughFilter(details, (node) => node.classList.contains("has-missing"));
    const extra = details.closest(".extra-sections");
    if (extra) extra.open = true;
    details.open = true;
    setActiveNav(sectionKey);
    details.scrollIntoView({behavior: "smooth", block: "start"});
    if (!focusInput) return;
    const firstInput = Array.from(details.querySelectorAll("input, select, textarea")).find((input) => input.getClientRects().length > 0);
    window.setTimeout(() => {
      if (!modalIsOpen()) firstInput?.focus({preventScroll: true});
    }, 250);
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
    arrangeSections(updatePreview());
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
    // Коды AI берём из загруженного результата: поле анкеты заполняется только после
    // свежего запуска, а результат может быть открыт из истории.
    const aiCodes = lastModelParsed
      ? modelDiagnosisSummary(lastModelParsed).codes
      : (data.MODEL_OUTPUT?.Model_ICD10_codes || []);
    const modelCodes = new Set(aiCodes);
    if (trueCodes.size === 0 || modelCodes.size === 0) {
      // Сравнение имеет смысл только когда есть и коды врача, и коды AI.
      icdSummary.classList.add("hidden");
      return;
    }
    let matches = 0;
    let missed = 0;
    let extra = 0;
    trueCodes.forEach((code) => modelCodes.has(code) ? matches++ : missed++);
    modelCodes.forEach((code) => { if (!trueCodes.has(code)) extra++; });
    icdSummary.classList.remove("hidden");
    icdSummary.className = `notice ${missed || extra ? "warning-note" : "ok-note"}`;
    icdSummary.textContent = missed || extra
      ? `МКБ-10: совпадает ${matches} · только в диагнозе врача ${missed} · только у AI ${extra}. Сверьте кодировку перед выгрузкой.`
      : `МКБ-10: все ${matches} кода(ов) врача и AI совпадают.`;
  }

  function updatePreview() {
    const data = collectData();
    jsonPreview.textContent = JSON.stringify(data, null, 2);
    updateIcdComparison(data);
    updateSectionBadges(data);
    updateClinicalQuality(data);
    form.querySelectorAll('[data-has-reference="1"]').forEach(updateFieldReference);
    updateFieldAlerts(data);
    updateSectionNavStates(data);
    renderModelWorkbench(lastModelParsed, data);
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
    if (suppressDraftSave || caseReadOnly) return;
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
    if (suppressDraftSave || caseReadOnly) return;
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
    caseSession++;
    caseReadOnly = false;
    saveErrorText = "";
    currentCaseId = pendingDraft.case_id || null;
    if (window.history?.replaceState) window.history.replaceState(null, "", currentCaseId ? `/app?case=${currentCaseId}` : "/app");
    manualEntry = true;
    resetModelState(true);
    collapseAllSections();
    applyData(pendingDraft.patient_data);
    setSaveState(currentCaseId ? `кейс #${currentCaseId} восстановлен из черновика` : "черновик восстановлен", true);
    suppressDraftSave = false;
    clearLocalDraft();
    updatePreview();
    toast("Черновик восстановлен");
  }

  function initDraftRestore() {
    const params = new URLSearchParams(window.location.search);
    // Черновик открытого по ссылке кейса сверяется с сервером после загрузки (offerCaseDraft).
    if (params.get("case") || params.get("request")) return;
    const draft = readLocalDraft();
    if (draft?.patient_data && qualityRules.hasClinicalInput(draft.patient_data)) showDraftBanner(draft);
  }

  // После перезагрузки /app?case=N черновик этого кейса предлагается, только если он новее
  // серверной копии и отличается от неё: иначе правки, не успевшие уйти на сервер, терялись бы.
  function offerCaseDraft(caseId, serverUpdatedAt) {
    const draft = readLocalDraft();
    if (!draft?.patient_data || Number(draft.case_id) !== Number(caseId)) return;
    const draftTime = new Date(draft.updated_at || 0).getTime();
    const serverTime = serverUpdatedAt ? new Date(serverUpdatedAt).getTime() : 0;
    if (serverTime && draftTime <= serverTime) return;
    if (JSON.stringify(draft.patient_data) === JSON.stringify(collectData())) return;
    showDraftBanner(draft);
  }

  function sectionFillPercent(section, data) {
    return qualityRules.sectionFillPercent(section, data);
  }

  function updateSectionBadges(data) {
    window.CVD_SCHEMA.forEach((section) => {
      const badge = form.querySelector(`[data-section-badge="${section.key}"]`);
      const {filled, total, percent} = sectionFillPercent(section, data);
      if (badge) {
        // Пустые секции не шумят бейджами; частично заполненные показывают счётчик.
        badge.textContent = percent === 0 ? "" : percent === 100 ? "✓" : `${filled}/${total}`;
        badge.className = `section-fill-badge ${percent === 100 ? "ok" : percent > 0 ? "warning" : "empty"}`.trim();
      }
    });
  }

  function missingRequiredData(data) {
    return scenarioMissingRequiredData(data);
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
    const age = getValue(data, "GENERAL_INFO.Age");
    const sex = getValue(data, "GENERAL_INFO.Sex");
    const heartRate = getValue(data, "PHYSICAL_EXAM.Heart_rate_bpm");
    const cards = [
      ["Пациент", isFilled(getValue(data, "GENERAL_INFO.Full_name")) ? displayValue(getValue(data, "GENERAL_INFO.Full_name")) : null],
      ["Случай", isFilled(getValue(data, "GENERAL_INFO.Patient_ID")) ? displayValue(getValue(data, "GENERAL_INFO.Patient_ID")) : null],
      ["Пол и возраст", isFilled(age) || isFilled(sex) ? window.CVDUI.demographicsText(age, sex) : null],
      ["АД / ЧСС", bp || isFilled(heartRate) ? `${displayValue(bp)} · ${displayValue(heartRate, "?")} уд/мин` : null],
      ["Диагноз врача", isFilled(getValue(data, "FINAL_DIAGNOSES.Main_cardiovascular_diagnosis_text")) ? displayValue(getValue(data, "FINAL_DIAGNOSES.Main_cardiovascular_diagnosis_text")) : null]
    ].filter(([, value]) => value !== null);
    if (!cards.length) {
      const empty = document.createElement("p");
      empty.className = "muted snapshot-empty";
      empty.textContent = "Сводка пациента появится по мере заполнения анкеты.";
      patientSnapshot.appendChild(empty);
      return;
    }
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

  // Диагноз врача не учитываем: принятый черновик AI не должен делать заключение «устаревшим»
  // и отправлять врача на повторный анализ собственного вывода модели.
  function clinicalFingerprint(data) {
    const copy = {...(data || {})};
    delete copy.FINAL_DIAGNOSES;
    return qualityRules.dataFingerprint(copy);
  }

  // Сервер считает результат устаревшим при любой правке, в том числе диагноза врача.
  function serverResultStale(item) {
    if (!item?.ai_result_stale) return false;
    const changes = Array.isArray(item.ai_result_changes) ? item.ai_result_changes : [];
    return !changes.length || changes.some((change) => !String(change.path || "").startsWith("FINAL_DIAGNOSES."));
  }

  function hasUsableResult() {
    return Boolean(currentModelRequestId && currentModelRequestOk);
  }

  function isResultStale(data) {
    if (!hasUsableResult()) return false;
    if (resultStaleOnServer) return true;
    return Boolean(lastModelDataFingerprint && clinicalFingerprint(data) !== lastModelDataFingerprint);
  }

  function aiBusy() {
    return aiRunningSessions.has(caseSession);
  }

  // Одна главная кнопка, которая ведёт по шагам: дозаполнить → запустить AI → открыть результат → в МИС.
  function nextAction(data) {
    const missing = missingRequiredData(data);
    if (aiBusy()) return {label: "AI-анализ выполняется…", hint: "Задание в очереди или обрабатывается. Можно продолжать работу.", disabled: true};
    if (hasUsableResult() && !isResultStale(data)) {
      return resultOpened
        ? {label: "Копировать для МИС", hint: "Текст заключения для вставки в протокол ЕМИАС или другой МИС.", run: () => copyMisText()}
        : {label: "Открыть результат", hint: "Заключение AI рядом с диагнозом врача.", run: () => openTab("model")};
    }
    if (missing.length) {
      const labels = missing.map(([, label]) => label);
      return {
        label: `Заполнить ${window.CVDUI.countText(missing.length, ["ключевое поле", "ключевых поля", "ключевых полей"])}`,
        hint: `Не заполнены: ${labels.join(", ")}.`,
        run: () => focusFirstMissing(data)
      };
    }
    if (hasUsableResult()) return {label: "Обновить AI-анализ", hint: "Данные изменились после последнего анализа.", run: () => diagnose()};
    return {label: "Запустить AI-анализ", hint: "Сначала откроется проверка данных перед отправкой.", run: () => diagnose()};
  }

  let currentNextAction = null;

  function updateNextAction(data) {
    if (!nextActionButton) return;
    currentNextAction = nextAction(data);
    nextActionButton.textContent = currentNextAction.label;
    nextActionButton.title = currentNextAction.hint || "";
    nextActionButton.disabled = Boolean(currentNextAction.disabled);
  }

  function startScreenVisible(data) {
    return !currentCaseId && !manualEntry && !qualityRules.hasClinicalInput(data);
  }

  function updateStartScreen(data) {
    const visible = startScreenVisible(data);
    workspaceStart?.classList.toggle("hidden", !visible);
    formArea?.classList.toggle("hidden", visible);
    workflowCockpit?.classList.toggle("hidden", visible);
  }

  // Анкета показывается, как только врач выбрал путь «вручную» или перешёл к конкретному полю.
  function revealForm() {
    if (manualEntry) return;
    manualEntry = true;
    updateStartScreen(collectData());
  }

  function updateWorkflow(data) {
    updateStartScreen(data);
    updateNextAction(data);
    if (missingOnlyToggle && !missingOnly) {
      const nothingMissing = missingRequiredData(data).length === 0;
      missingOnlyToggle.disabled = nothingMissing;
      missingOnlyToggle.title = nothingMissing
        ? "Все ключевые поля профиля заполнены"
        : "Скрыть всё, кроме незаполненных ключевых полей профиля";
    }
    syncStatusBar(data);
  }

  function focusFieldPath(path) {
    const [section, field] = String(path || "").split(".");
    const target = document.getElementById(fieldId(section, field));
    revealThroughFilter(target, (node) => Boolean(node.closest(".field")?.classList.contains("is-missing")));
    focusSection(section, {focusInput: false});
    window.setTimeout(() => {
      if (modalIsOpen()) return;
      target?.scrollIntoView({behavior: "smooth", block: "center"});
      target?.focus({preventScroll: true});
    }, 260);
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
    const stale = isResultStale(data);
    if (stale) {
      setModelStatus("данные изменены после AI", "warning");
    }
    diagnoseButton?.classList.toggle("warning", stale);
    diagnoseButton?.setAttribute("title", stale ? "Данные кейса изменились после последнего AI-анализа — рекомендуется обновить результат." : "");
    syncStatusBar(data);
  }

  function renderReadiness(data) {
    if (!readinessPanel) return;
    readinessPanel.innerHTML = "";
    const missing = missingRequiredData(data);
    const total = scenarioRequiredDataPoints().length;
    const ready = total - missing.length;
    // Прогресс уже показан в строке статуса — здесь только сам список того, что осталось.
    if (readinessCount) {
      readinessCount.textContent = `${ready} из ${total}`;
      readinessCount.className = `pill ${missing.length ? "warning" : "ok"}`;
    }
    if (!missing.length) {
      const row = document.createElement("div");
      row.className = "check-row ok";
      const mark = document.createElement("span");
      mark.className = "check-mark";
      mark.textContent = "✓";
      const text = document.createElement("span");
      text.textContent = "Все ключевые поля заполнены";
      row.append(mark, text);
      readinessPanel.appendChild(row);
      return;
    }
    missing.forEach(([path, label]) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "check-row warning";
      row.title = `Перейти к полю: ${label}`;
      const mark = document.createElement("span");
      mark.className = "check-mark";
      mark.textContent = "!";
      const text = document.createElement("span");
      text.textContent = label;
      const state = document.createElement("small");
      state.textContent = "заполнить";
      row.append(mark, text, state);
      row.addEventListener("click", () => focusFieldPath(path));
      readinessPanel.appendChild(row);
    });
  }

  function renderSignals(data) {
    if (!signalsPanel) return;
    signalsPanel.innerHTML = "";
    // Сначала критические, затем отклонения; справочные свёрнуты, чтобы не приучать игнорировать сигналы.
    const tierOrder = {critical: 0, error: 0, warning: 1, info: 2};
    const signals = qualityRules.clinicalSignals(data)
      .slice()
      .sort((a, b) => (tierOrder[a.kind] ?? 1) - (tierOrder[b.kind] ?? 1));
    const significant = signals.filter((signal) => signal.kind !== "info");
    const informational = signals.filter((signal) => signal.kind === "info");
    const renderSignal = ({kind, title, text, category}) => {
      const row = document.createElement("div");
      row.className = `signal-row ${kind}`;
      const strong = document.createElement("strong");
      strong.textContent = title;
      const small = document.createElement("small");
      small.textContent = `${category ? `${category}: ` : ""}${text || "проверьте клинический контекст"}`;
      row.append(strong, small);
      return row;
    };
    if (!significant.length) {
      const row = document.createElement("div");
      row.className = "check-row";
      row.textContent = "Значимых сигналов по заполненным данным нет.";
      signalsPanel.appendChild(row);
    }
    significant.forEach((signal) => signalsPanel.appendChild(renderSignal(signal)));
    if (informational.length) {
      const details = document.createElement("details");
      details.className = "signal-info";
      const summary = document.createElement("summary");
      summary.textContent = `Справочно · ${informational.length}`;
      details.appendChild(summary);
      informational.forEach((signal) => details.appendChild(renderSignal(signal)));
      signalsPanel.appendChild(details);
    }
  }

  // Сохранения идут строго по очереди: два параллельных создания дали бы два кейса.
  function saveCase(options = {}) {
    const run = saveQueue.then(() => performSave(options));
    saveQueue = run.catch(() => {});
    return run;
  }

  async function performSave({silent = false, keepalive = false} = {}) {
    if (caseReadOnly) throw new Error(readOnlyText);
    // Пока сохранение ждало очереди, предыдущее могло уже записать эти же правки.
    if (silent && !hasUnsavedChanges) return null;
    window.clearTimeout(autosaveTimer);
    const session = caseSession;
    const data = collectData();
    const snapshot = JSON.stringify(data);
    const caseIdAtStart = currentCaseId;
    const body = JSON.stringify({case_id: caseIdAtStart, patient_data: data});
    lastSaveAttemptAt = Date.now();
    inFlightSnapshot = snapshot;
    saveInFlight = api("/api/cases", {
      method: "POST",
      keepalive: Boolean(keepalive && caseIdAtStart && fitsKeepalive(body)),
      body
    });
    syncStatusBar(data);
    let response;
    try {
      response = await saveInFlight;
    } catch (err) {
      if (session === caseSession) {
        saveErrorText = window.CVDUI.humanizeError(err).replace(/\.$/, "");
        // Сеть могла моргнуть: следующая попытка — через обычный интервал автосохранения.
        if (isRetryableSaveError(err)) scheduleAutosave();
      }
      throw err;
    } finally {
      saveInFlight = null;
      inFlightSnapshot = null;
      syncStatusBar();
    }
    if (session !== caseSession) return response;
    currentCaseId = response.case_id;
    lastSavedAt = new Date();
    saveErrorText = "";
    if (!caseIdAtStart && window.history?.replaceState) {
      window.history.replaceState(null, "", `/app?case=${currentCaseId}`);
    }
    const current = collectData();
    if (currentModelRequestId) updateModelFreshness(current);
    if (!caseIdAtStart) {
      // Черновик, записанный до создания кейса, теперь относится к нему.
      window.clearTimeout(draftSaveTimer);
      if (hasUnsavedChanges) writeLocalDraft(current);
    }
    // Пока запрос шёл, врач мог продолжить ввод — тогда кейс остаётся «изменённым».
    if (JSON.stringify(current) === snapshot) {
      setSaveState("", false);
      clearLocalDraft();
    } else {
      setSaveState("", true);
    }
    updateWorkflow(current);
    if (!silent) toast("Кейс сохранён");
    return response;
  }

  function fillModelOutput(parsed) {
    const modelOutput = parsed?.MODEL_OUTPUT || parsed;
    if (!modelOutput || typeof modelOutput !== "object") return;
    for (const [key, value] of Object.entries(modelOutput)) {
      setFieldValue(`MODEL_OUTPUT.${key}`, value);
    }
    scheduleDraftSave(updatePreview());
    // Поля ответа модели — часть кейса: сохраняем их, иначе в браузере остаётся «черновик»,
    // который потом всплывает баннером на новом кейсе. На свежесть AI-результата они не влияют.
    setSaveState("", true);
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
    if (job.type === "text_preparation") return `Текст #${job.id}`;
    return job.case_title ? `Диагноз #${job.id}: ${job.case_title}` : `Диагноз #${job.id}`;
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
        toast(job.status === "error" ? job.user_error || job.error || "Подготовка текста завершилась ошибкой" : "Подготовка текста ещё выполняется");
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
        toast(job.status === "error" ? job.user_error || job.error || "AI-анализ завершился ошибкой" : "AI-анализ ещё выполняется");
        return;
      }
      const response = await api(`/api/requests/${job.model_request_id}`);
      openRequestResult(response.request);
    }
  }

  async function cancelAiJob(job) {
    if (job.status !== "queued") {
      toast("Отменить можно только задание в очереди");
      return;
    }
    await api(`/api/ai/jobs/${job.type}/${job.id}/cancel`, {method: "POST", body: "{}"});
    toast(`${aiJobTitle(job)} отменено`);
    await refreshAiJobs();
  }

  function openJobCase(job) {
    if (!job.case_id) {
      toast("У задания нет сохранённого кейса");
      return;
    }
    openCase(job.case_id).catch((err) => toast(err.message));
  }

  function taskCounts(jobs) {
    return jobs.reduce((result, job) => {
      const key = ["queued", "running", "success", "error"].includes(job.status) ? job.status : "other";
      result[key] = (result[key] || 0) + 1;
      return result;
    }, {queued: 0, running: 0, success: 0, error: 0, other: 0});
  }

  function renderTaskSummary(jobs) {
    if (!taskCenterSummary) return;
    const counts = taskCounts(jobs);
    taskCenterSummary.innerHTML = "";
    [
      ["В очереди", counts.queued, "warning"],
      ["В работе", counts.running, "ok"],
      ["Готово", counts.success, "ok"],
      ["Ошибки", counts.error, "error"]
    ].forEach(([label, value, kind]) => {
      const card = document.createElement("div");
      card.className = `task-summary-card ${kind}`.trim();
      const strong = document.createElement("strong");
      strong.textContent = String(value);
      const span = document.createElement("span");
      span.textContent = label;
      card.append(strong, span);
      taskCenterSummary.appendChild(card);
    });
  }

  function renderJobNode(job, compact = false) {
    const actionable = job.status === "success" && (
      (job.type === "text_preparation" && job.import_id) ||
      (job.type === "diagnosis" && job.model_request_id)
    );
    const node = document.createElement(compact && actionable ? "button" : "div");
    if (compact && actionable) node.type = "button";
    node.className = compact
      ? `job-chip ${job.status === "success" ? "ok" : job.status === "error" ? "error" : "warning"}`
      : `task-center-item ${job.status === "success" ? "ok" : job.status === "error" ? "error" : job.status === "running" ? "running" : "warning"}`;
    const title = document.createElement("strong");
    title.textContent = aiJobTitle(job);
    const state = document.createElement("span");
    state.className = compact ? "muted" : "task-center-state";
    state.textContent = aiJobStatusText(job);
    node.append(title, state);
    if (!compact) {
      const meta = document.createElement("small");
      const created = job.created_at ? window.CVDUI.relativeTime(job.created_at) : "";
      const owner = job.created_by?.name || job.created_by?.email || "";
      meta.textContent = [
        job.position ? `позиция ${job.position}` : "",
        job.queue_ahead ? `перед ним ${job.queue_ahead}` : "",
        job.estimated_wait_ms ? queueEtaText(job.estimated_wait_ms) : "",
        owner ? `запустил: ${owner}` : "",
        job.patient_id ? `ID ${job.patient_id}` : "",
        created
      ].filter(Boolean).join(" · ") || "статус обновляется";
      const actionRow = document.createElement("div");
      actionRow.className = "task-center-actions";
      if (actionable) {
        const openButton = document.createElement("button");
        openButton.type = "button";
        openButton.className = "small-button";
        openButton.textContent = "Открыть";
        openButton.addEventListener("click", () => openAiJob(job).catch((err) => toast(err.message)));
        actionRow.appendChild(openButton);
      }
      if (job.case_id) {
        const caseButton = document.createElement("button");
        caseButton.type = "button";
        caseButton.className = "small-button";
        caseButton.textContent = "Кейс";
        caseButton.addEventListener("click", () => openJobCase(job));
        actionRow.appendChild(caseButton);
      }
      if (job.status === "queued") {
        const cancelButton = document.createElement("button");
        cancelButton.type = "button";
        cancelButton.className = "small-button danger";
        cancelButton.textContent = "Отменить";
        cancelButton.addEventListener("click", () => cancelAiJob(job).catch((err) => toast(err.message)));
        actionRow.appendChild(cancelButton);
      }
      if (!actionRow.childNodes.length) {
        const waiting = document.createElement("span");
        waiting.className = "task-center-action";
        waiting.textContent = job.status === "running" ? "идёт обработка" : "ожидание";
        actionRow.appendChild(waiting);
      }
      node.append(meta, actionRow);
      // Текст ошибки — отдельной строкой во всю ширину, иначе он сжимает заголовок задачи.
      if (job.status === "error") {
        const errorText = document.createElement("p");
        errorText.className = "task-center-error";
        errorText.textContent = job.user_error || job.error || "Задание завершилось ошибкой.";
        node.appendChild(errorText);
      }
    }
    if (compact && actionable) {
      node.addEventListener("click", () => openAiJob(job).catch((err) => toast(err.message)));
    }
    return node;
  }

  function renderActiveJobs(payload) {
    const jobs = payload?.jobs || [];
    const recentFinishedCutoffMs = Date.now() - 30 * 60 * 1000;
    const visible = [
      ...jobs.filter((job) => ["queued", "running"].includes(job.status)),
      ...jobs
        .filter((job) => ["success", "error"].includes(job.status))
        .filter((job) => new Date(job.finished_at || job.created_at || 0).getTime() >= recentFinishedCutoffMs)
        .slice(0, 1)
    ].slice(0, 5);
    const activeCount = jobs.filter((job) => ["queued", "running"].includes(job.status)).length;
    const attentionCount = jobs.filter((job) => ["queued", "running", "error"].includes(job.status)).length;
    // Кнопка «Задачи» появляется, только когда в центре задач есть что смотреть.
    openTaskCenterButton?.classList.toggle("hidden", jobs.length === 0);
    if (taskCountBadge) {
      taskCountBadge.textContent = String(attentionCount);
      taskCountBadge.classList.toggle("hidden", attentionCount === 0);
    }
    openTaskCenterButton?.classList.toggle("attention", attentionCount > 0);
    if (activeJobsLine) {
      activeJobsLine.innerHTML = "";
      activeJobsLine.classList.toggle("hidden", visible.length === 0);
      if (activeCount) {
        const label = document.createElement("strong");
        label.textContent = "AI-задачи";
        activeJobsLine.appendChild(label);
      }
      visible.forEach((job) => activeJobsLine.appendChild(renderJobNode(job, true)));
    }
    renderTaskSummary(jobs);
    if (taskCenterList) {
      taskCenterList.innerHTML = "";
      if (!jobs.length) {
        const empty = document.createElement("div");
        empty.className = "record-empty";
        const strong = document.createElement("strong");
        strong.textContent = "Активных AI-задач нет";
        const span = document.createElement("span");
        span.textContent = "Здесь появятся подготовка текста, диагнозы, готовые результаты и ошибки.";
        empty.append(strong, span);
        taskCenterList.appendChild(empty);
      } else {
        jobs.slice(0, 20).forEach((job) => taskCenterList.appendChild(renderJobNode(job, false)));
      }
    }
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
      if (job.type === "diagnosis" && awaitedDiagnosisJobIds.has(job.id)) return;
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

  function isDoctorMode() {
    return (document.body.dataset.interfaceMode || "doctor") === "doctor";
  }

  function displayModelName(model) {
    // Врач видит бренд сервиса, а не внутреннее имя модели.
    return isDoctorMode() ? "CVD Engine" : (model || "—");
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

  function openModelResultModal(focusTarget = null) {
    if (!modelResultModal) return;
    openModalElement(modelResultModal, focusTarget || document.getElementById("closeModelResultModal"));
    if (hasUsableResult() && !resultOpened) {
      resultOpened = true;
      updateNextAction(collectData());
    }
  }

  function closeModelResultModal() {
    if (!modelResultModal) return;
    closeModalElement(modelResultModal);
  }

  function openTaskCenterModal() {
    if (!taskCenterModal) return;
    openModalElement(taskCenterModal, document.getElementById("refreshTaskCenterButton"));
    refreshAiJobs().catch((err) => toast(err.message));
  }

  function closeTaskCenterModal() {
    if (!taskCenterModal) return;
    closeModalElement(taskCenterModal);
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
      pill(`не хватает: ${missing.length}`, missing.length ? "warning" : ""),
      pill(displayModelName(meta.model))
    );
    lastModelSummary.append(toolbar, summary, stats);
    lastModelSummary.classList.remove("hidden");
  }

  function stripTrailingIcdList(text) {
    // Модель дублирует коды в конце диагноза («… МКБ-10: I20.8, I10»), а UI рисует их чипами.
    return String(text || "").replace(/\s*МКБ-?10\s*[::]\s*[A-ZА-Я]?\d[\d.,;\sA-Z]*\.?\s*$/iu, "").trim();
  }

  function modelDiagnosisSummary(parsed) {
    const cds = parsed?.CDS_OUTPUT || {};
    const output = parsed?.MODEL_OUTPUT || {};
    const lead = Array.isArray(cds.possible_diagnoses) ? cds.possible_diagnoses[0] : null;
    const abstained = Boolean(cds.model_should_abstain);
    return {
      abstained,
      text: stripTrailingIcdList(output.Final_model_diagnosis || lead?.name || cds.summary || ""),
      // При отказе модели коды не показываем: это не кодируемый диагноз.
      codes: abstained ? [] : (Array.isArray(output.Model_ICD10_codes) ? output.Model_ICD10_codes : (lead?.icd10_codes || [])),
      summary: cds.summary || "",
      redFlags: Array.isArray(cds.red_flags) ? cds.red_flags.filter(Boolean) : [],
      missing: Array.isArray(cds.missing_data) ? cds.missing_data.filter(Boolean) : []
    };
  }

  function renderWorkbenchDiagnosis(node, title, text, codes, emptyText) {
    if (!node) return;
    node.innerHTML = "";
    const value = String(text || "").trim();
    if (!value && (!codes || codes.length === 0)) {
      node.textContent = emptyText;
      return;
    }
    const diagnosis = document.createElement("p");
    diagnosis.textContent = value || "Диагноз не указан";
    node.appendChild(diagnosis);
    if (codes?.length) {
      const chips = document.createElement("div");
      chips.className = "icd-chips";
      codes.forEach((code) => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "icd-chip";
        chip.textContent = code;
        chip.title = `Скопировать ${title}: ${code}`;
        chip.addEventListener("click", () => navigator.clipboard?.writeText(code).then(() => toast(`Код ${code} скопирован`)).catch(() => {}));
        chips.appendChild(chip);
      });
      node.appendChild(chips);
    }
  }

  function renderModelWorkbench(parsed = lastModelParsed, data = collectData()) {
    const doctorText = getValue(data, "FINAL_DIAGNOSES.Main_cardiovascular_diagnosis_text") || "";
    const doctorCodes = data.FINAL_DIAGNOSES?.ICD10_codes || [];
    const ai = modelDiagnosisSummary(parsed || {});
    renderWorkbenchDiagnosis(doctorDiagnosisWorkbench, "врача", doctorText, doctorCodes, "Итоговый диагноз врача еще не заполнен.");
    renderWorkbenchDiagnosis(aiDiagnosisWorkbench, "AI", ai.text, ai.codes, "AI-заключение появится после анализа.");
    const hasAi = Boolean(ai.text || ai.codes.length);
    // Когда модель воздержалась, принимать нечего: заключения нет, есть только запрос данных.
    const acceptable = hasAi && !ai.abstained;
    acceptModelDraftButton?.toggleAttribute("disabled", !acceptable);
    acceptModelDraftButton?.classList.toggle("primary", acceptable);
    if (acceptModelDraftButton) {
      acceptModelDraftButton.title = ai.abstained
        ? "AI воздержался от заключения — принимать в черновик нечего"
        : "Принять AI-диагноз в черновик врача";
    }
    copyModelDiagnosisButton?.toggleAttribute("disabled", !hasAi);
    openModelReportButton?.toggleAttribute("disabled", !hasUsableResult());
  }

  async function acceptModelDiagnosisDraft() {
    const ai = modelDiagnosisSummary(lastModelParsed || {});
    if (ai.abstained) {
      toast("AI воздержался от заключения — принимать в черновик нечего");
      return;
    }
    if (!ai.text && !ai.codes.length) {
      toast("AI-диагноз пока отсутствует");
      return;
    }
    const currentDiagnosis = String(form.elements["FINAL_DIAGNOSES.Main_cardiovascular_diagnosis_text"]?.value || "").trim();
    const currentCodes = String(form.elements["FINAL_DIAGNOSES.ICD10_codes"]?.value || "").trim();
    if (currentDiagnosis || currentCodes) {
      const replace = await window.CVDUI.confirm({
        title: "Заменить диагноз врача?",
        message: `Сейчас в анкете: «${currentDiagnosis || currentCodes}». Он будет заменён черновиком AI — после замены проверьте формулировку и коды.`,
        confirmLabel: "Заменить",
        destructive: true
      });
      if (!replace) return;
    }
    setFieldValue("FINAL_DIAGNOSES.Main_cardiovascular_diagnosis_text", ai.text);
    setFieldValue("FINAL_DIAGNOSES.ICD10_codes", ai.codes);
    const data = updatePreview();
    scheduleDraftSave(data);
    setSaveState(currentCaseId ? `кейс #${currentCaseId} изменён` : "не сохранено", true);
    closeModelResultModal();
    focusFieldPath("FINAL_DIAGNOSES.Main_cardiovascular_diagnosis_text");
    toast("AI-диагноз перенесён в черновик врача — проверьте формулировку");
  }

  async function copyModelDiagnosis() {
    const ai = modelDiagnosisSummary(lastModelParsed || {});
    const text = [ai.text, ai.codes.length ? `МКБ-10: ${ai.codes.join("; ")}` : ""].filter(Boolean).join("\n");
    if (!text) {
      toast("AI-диагноз пока отсутствует");
      return;
    }
    await navigator.clipboard.writeText(text);
    toast("AI-диагноз скопирован");
  }

  function markModelIssue() {
    if (!currentModelRequestId || !requestReviewForm) {
      toast("Сначала откройте результат AI");
      return;
    }
    requestReviewForm.classList.remove("hidden");
    const details = document.getElementById("reviewDetails");
    if (details) details.open = true;
    openModelResultModal(requestReviewForm.comment);
    // Оценку «опасно» не понижаем до «неверно»: она важнее для разбора ошибок модели.
    const rating = requestReviewForm.rating.value;
    requestReviewForm.issue_types.value = requestReviewForm.issue_types.value || "needs_correction";
    if (rating === "unsafe" || rating === "wrong") return;
    requestReviewForm.rating.value = "wrong";
    scheduleRatingSave();
  }

  function renderModelOutput(parsed, meta = {}) {
    if (!modelStructured) return;
    lastModelParsed = parsed || null;
    lastModelMeta = meta || {};
    if (modelResultSubtitle) {
      const when = meta.created_at ? window.CVDUI.formatDateTime(meta.created_at) : "";
      const caseId = meta.case_id ?? currentCaseId;
      modelResultSubtitle.textContent = [
        caseId ? `Кейс #${caseId}` : "Несохранённый кейс",
        when,
        meta.model || isDoctorMode() ? displayModelName(meta.model) : "",
        "черновик для проверки врачом"
      ].filter(Boolean).join(" · ");
    }
    renderModelWorkbench(lastModelParsed, collectData());
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
    // Сам диагноз показан выше в панели «Заключение AI» — здесь только обоснование,
    // иначе одно и то же читается трижды.
    const eyebrow = document.createElement("span");
    eyebrow.className = "verdict-eyebrow";
    eyebrow.textContent = cds.model_should_abstain ? "AI воздержался от заключения" : "Клиническая сводка";
    summary.append(eyebrow);
    const text = document.createElement("p");
    text.textContent = cds.summary || "Сводка не указана.";
    const metaItems = [
      ["Сервис", displayModelName(meta.model)],
      ["Время анализа", durationText(meta.duration_ms)]
    ];
    if (!isDoctorMode()) metaItems.push(["Ожидание", durationText(meta.queue_wait_ms)]);
    // Счётчики диагнозов и недостающих данных не дублируем: их списки идут ниже.
    if (redFlags.length) metaItems.push(["Red flags", String(redFlags.length), "danger"]);
    summary.append(text, renderModelMetaGrid(metaItems));
    modelStructured.appendChild(summary);
    if (redFlags.length > 0) {
      const strip = document.createElement("div");
      strip.className = "red-flag-strip";
      const stripTitle = document.createElement("strong");
      stripTitle.textContent = "Red flags";
      strip.appendChild(stripTitle);
      redFlags.forEach((flag) => {
        const badge = document.createElement("span");
        badge.className = "red-flag-badge";
        badge.textContent = flag;
        strip.appendChild(badge);
      });
      modelStructured.appendChild(strip);
    }
    renderLastModelSummary(cds, meta);
    if (serverResultStale(meta)) {
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

    if (redFlags.length === 0) {
      modelStructured.appendChild(renderModelList("Red flags", [], "Нет явных red flags в результате AI-анализа."));
    }
    const modelOutput = parsed?.MODEL_OUTPUT || {};
    const treatment = String(modelOutput.Model_treatment_recommendations || "").trim();
    const rehabilitation = String(modelOutput.Model_rehabilitation_recommendations || "").trim();
    if (treatment || rehabilitation) {
      const section = document.createElement("div");
      section.className = "model-section recommendations-section";
      const heading = document.createElement("h3");
      heading.textContent = "Черновик рекомендаций";
      const note = document.createElement("p");
      note.className = "muted recommendations-note";
      note.textContent = "Ориентиры по тактике без препаратов и доз. Назначения определяет врач.";
      section.append(heading, note);
      if (treatment) section.appendChild(renderRecommendationBlock("Тактика ведения", treatment));
      if (rehabilitation) section.appendChild(renderRecommendationBlock("Реабилитация и профилактика", rehabilitation));
      modelStructured.appendChild(section);
    }
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
    const codeList = diagnosis.icd10_codes || [];
    if (codeList.length) {
      const chips = document.createElement("div");
      chips.className = "icd-chips";
      codeList.forEach((code) => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "icd-chip";
        chip.textContent = code;
        chip.title = "Скопировать код";
        chip.addEventListener("click", () => {
          navigator.clipboard?.writeText(code).then(() => toast(`Код ${code} скопирован`)).catch(() => {});
        });
        chips.appendChild(chip);
      });
      card.appendChild(chips);
    } else {
      const codes = document.createElement("small");
      codes.textContent = "МКБ-10 не указаны";
      card.appendChild(codes);
    }
    card.appendChild(renderInlineList("За", diagnosis.supporting_findings));
    card.appendChild(renderInlineList("Против", diagnosis.against_findings));
    card.appendChild(renderInlineList("Не хватает", diagnosis.missing_data));
    return card;
  }

  function guessFieldPathForEvidence(text) {
    const value = normalizeSearchText(text);
    const rules = [
      [["тропонин", "troponin"], "LABS_CARDIAC_MARKERS.Troponin_ng_L"],
      [["nt-probnp", "nt probnp", "bnp"], "LABS_CARDIAC_MARKERS.NT_proBNP_pg_ml"],
      [["фв", "lvef", "фракц"], "ECHOCARDIOGRAPHY.LVEF_percent"],
      [["эхо", "экокг"], "ECHOCARDIOGRAPHY.LVEF_percent"],
      [["экг", "st ", "st-", "ритм"], "ECG_AND_BP_MONITORING.Resting_ECG_summary"],
      [["холтер"], "ECG_AND_BP_MONITORING.Holter_ECG_summary"],
      [["смад"], "ECG_AND_BP_MONITORING.ABPM_summary"],
      [["ад", "давлен"], "PHYSICAL_EXAM.Blood_pressure_right_systolic_mmHg"],
      [["чсс", "пульс", "тахик", "брадик"], "PHYSICAL_EXAM.Heart_rate_bpm"],
      [["spo2", "сатурац"], "PHYSICAL_EXAM.SpO2_room_air_percent"],
      [["жалоб", "боль", "одыш", "отек"], "COMPLAINTS.Main_complaint"],
      [["креатинин"], "LABS_BIOCHEM.Creatinine_umol_L"],
      [["скф", "egfr"], "LABS_BIOCHEM.eGFR_ml_min_1_73m2"],
      [["калий", " k ", "k+"], "LABS_BIOCHEM.K_mmol_L"],
      [["лпнп", "ldl"], "LABS_LIPIDS.LDL_mmol_L"],
      [["мкб", "icd"], "FINAL_DIAGNOSES.ICD10_codes"],
      [["диагноз"], "FINAL_DIAGNOSES.Main_cardiovascular_diagnosis_text"]
    ];
    const match = rules.find(([tokens]) => tokens.some((token) => value.includes(token)));
    if (match) return match[1];
    return fieldSearchMatches(value.split(" ").slice(0, 3).join(" "))[0]?.path || null;
  }

  function focusEvidenceText(text) {
    const path = guessFieldPathForEvidence(text);
    if (!path) {
      toast("Не удалось сопоставить аргумент с конкретным полем");
      return;
    }
    focusFieldPath(path);
  }

  function renderInlineList(label, items) {
    const wrapper = document.createElement("div");
    wrapper.className = "inline-evidence";
    const title = document.createElement("span");
    title.textContent = `${label}:`;
    const values = Array.isArray(items) ? items.filter(Boolean) : [];
    const text = document.createElement("small");
    if (values.length) {
      values.forEach((item, index) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "evidence-link";
        button.textContent = item;
        button.title = "Найти связанное поле анкеты";
        button.addEventListener("click", () => focusEvidenceText(item));
        text.appendChild(button);
        if (index < values.length - 1) text.append("; ");
      });
    } else {
      text.textContent = "нет";
    }
    wrapper.append(title, text);
    return wrapper;
  }

  function renderRecommendationBlock(title, text) {
    const block = document.createElement("div");
    block.className = "recommendation-block";
    const heading = document.createElement("strong");
    heading.textContent = title;
    const body = document.createElement("p");
    body.textContent = text;
    block.append(heading, body);
    return block;
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

  function updateModelTabVisibility() {
    document.getElementById("modelTabButton")?.classList.toggle("hidden", !currentModelRequestId);
  }

  function showReviewForm(requestId, review = null) {
    currentModelRequestId = requestId;
    updateModelTabVisibility();
    if (!requestReviewForm) return;
    requestReviewForm.classList.toggle("hidden", !requestId);
    if (!requestId) return;
    // Без оценки ни один вариант не выбран: прежнее «Полезно» по умолчанию подталкивало сохранить не глядя.
    requestReviewForm.querySelectorAll('input[name="rating"]').forEach((input) => {
      input.checked = input.value === review?.rating;
    });
    requestReviewForm.issue_types.value = (review?.issue_types || []).join("; ");
    requestReviewForm.corrected_diagnosis.value = review?.corrected_diagnosis || "";
    requestReviewForm.corrected_icd10.value = (review?.corrected_icd10 || []).join("; ");
    requestReviewForm.comment.value = review?.comment || "";
    const details = document.getElementById("reviewDetails");
    if (details) {
      details.open = Boolean(review && (review.comment || review.corrected_diagnosis || (review.issue_types || []).length));
    }
    reviewStatus.textContent = review ? `сохранено: ${ratingLabel(review.rating)}` : "не оценено";
    reviewStatus.className = `pill ${review ? "ok" : ""}`;
  }

  function ratingLabel(rating) {
    return {useful: "полезно", partial: "частично", wrong: "неверно", unsafe: "опасно"}[rating] || rating || "без оценки";
  }

  function setHtmlExportAvailable(available) {
    if (exportHtmlButton) exportHtmlButton.disabled = !available;
    const copyButton = document.getElementById("copyMisTextButton");
    if (copyButton) copyButton.disabled = !available;
  }

  // Текст для МИС и отчёт сервер собирает из сохранённого кейса, поэтому сначала дописываем правки.
  async function flushForReport() {
    try {
      await flushAutosave();
      return true;
    } catch (err) {
      toast(`Кейс не сохранён: ${window.CVDUI.humanizeError(err)} Отчёт собирается из сохранённой версии — сохраните кейс и повторите.`, {duration: 6000});
      return false;
    }
  }

  async function copyMisText() {
    if (!hasUsableResult()) {
      toast("Сначала получите успешный результат AI-анализа");
      return;
    }
    if (!(await flushForReport())) return;
    const response = await api(`/api/reports/${currentModelRequestId}/mis-text`);
    const text = String(response.text || "");
    try {
      await navigator.clipboard.writeText(text);
      toast("Заключение скопировано — вставьте в протокол МИС");
    } catch (_) {
      // Clipboard API недоступен (не-HTTPS контекст) — показываем текст для ручного копирования.
      await window.CVDUI.prompt({
        title: "Текст для МИС",
        message: `Браузер не дал скопировать автоматически. Текст уже выделен — нажмите ${window.CVDUI.shortcut("C")}.`,
        value: text,
        multiline: true,
        readOnly: true,
        confirmLabel: "Готово",
        cancelLabel: ""
      });
    }
  }

  async function viewHtmlResult(requestId = currentModelRequestId) {
    if (!requestId || !hasUsableResult()) {
      toast("Сначала получите успешный результат AI-анализа");
      return;
    }
    if (!(await flushForReport())) return;
    const link = document.createElement("a");
    link.href = `/reports/${encodeURIComponent(requestId)}`;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  async function exportHtmlReport() {
    if (!hasUsableResult()) {
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
      setHtmlExportAvailable(hasUsableResult());
    }
  }

  let reviewSaveTimer = null;
  let reviewSaveQueue = Promise.resolve();
  let reviewSaveSeq = 0;

  // Стрелки в группе оценок проходят через соседние варианты: отправляем только итоговый выбор.
  function scheduleRatingSave() {
    window.clearTimeout(reviewSaveTimer);
    const requestId = currentModelRequestId;
    reviewStatus.textContent = "сохранение…";
    reviewStatus.className = "pill";
    reviewSaveTimer = window.setTimeout(() => {
      if (requestId !== currentModelRequestId) return;
      saveRequestReview().catch((err) => toast(err.message));
    }, 400);
  }

  async function saveRequestReview(event) {
    event?.preventDefault();
    window.clearTimeout(reviewSaveTimer);
    if (!currentModelRequestId) {
      toast("Сначала выберите результат AI-анализа");
      return;
    }
    const rating = requestReviewForm.rating.value;
    if (!rating) {
      toast("Сначала выберите оценку: полезно, частично, неверно или опасно");
      return;
    }
    const requestId = currentModelRequestId;
    const payload = {
      rating,
      issue_types: parseIcdString(requestReviewForm.issue_types.value).map((item) => item.toLowerCase()),
      corrected_diagnosis: requestReviewForm.corrected_diagnosis.value,
      corrected_icd10: parseIcdString(requestReviewForm.corrected_icd10.value),
      comment: requestReviewForm.comment.value
    };
    const seq = ++reviewSaveSeq;
    const isLatest = () => seq === reviewSaveSeq && requestId === currentModelRequestId;
    // Оценки уходят по очереди: иначе параллельные запросы могли сохранить не ту, что выбрана.
    const run = reviewSaveQueue.then(() => api(`/api/requests/${requestId}/review`, {
      method: "POST",
      body: JSON.stringify(payload)
    }));
    reviewSaveQueue = run.catch(() => {});
    try {
      await run;
    } catch (err) {
      if (isLatest()) {
        reviewStatus.textContent = `не сохранено: ${ratingLabel(payload.rating)}`;
        reviewStatus.className = "pill error";
      }
      throw err;
    }
    if (!isLatest()) return;
    reviewStatus.textContent = `сохранено: ${ratingLabel(payload.rating)}`;
    reviewStatus.className = "pill ok";
    toast(event ? "Подробности оценки сохранены" : `Оценка «${ratingLabel(payload.rating)}» сохранена`);
  }

  function diagnose() {
    if (aiBusy()) {
      toast("AI-анализ этого кейса уже выполняется — дождитесь результата");
      return;
    }
    const patientData = updatePreview();
    if (!qualityRules.hasClinicalInput(patientData)) {
      setModelStatus("добавьте данные пациента", "warning");
      toast("Добавьте данные пациента перед запуском AI-анализа");
      focusFieldPath("GENERAL_INFO.Patient_ID");
      return;
    }
    openReviewModal(() => runDiagnose(patientData), true);
  }

  async function runDiagnose(patientData) {
    if (aiBusy()) return;
    let response = null;
    let jobId = null;
    const session = caseSession;
    // Пока идёт анализ, врач может открыть другой кейс: всё, что ниже меняет экран, проверяет это.
    const sameCase = () => session === caseSession;
    aiRunningSessions.add(session);
    if (diagnoseButton) diagnoseButton.disabled = true;
    updateNextAction(patientData);
    // Результат привязывается к кейсу, поэтому незаписанные правки сохраняем до отправки.
    await flushAutosave().catch(() => {});
    if (!sameCase()) {
      aiRunningSessions.delete(session);
      return;
    }
    const caseIdAtRun = currentCaseId;
    resultOpened = false;
    currentModelRequestId = null;
    currentModelRequestOk = false;
    resultStaleOnServer = false;
    lastModelDataFingerprint = null;
    lastModelParsed = null;
    renderModelWorkbench(null, patientData);
    setHtmlExportAvailable(false);
    hideAiErrorCard();
    setModelStatus("запрос выполняется", "warning");
    modelPreview.textContent = "Выполняется AI-анализ...";
    modelStructured.textContent = "AI-анализ выполняется. Результат появится здесь после завершения задания.";
    requestReviewForm?.classList.add("hidden");
    const queueTimer = window.setInterval(async () => {
      if (!sameCase()) return;
      try {
        const status = await api("/api/inference/status");
        const queue = status.queue || {};
        const own = queue.user?.by_kind?.diagnosis || {};
        if (!sameCase()) return;
        if (own.state === "queued") {
          const eta = own.estimated_wait_ms ? ` · ${queueEtaText(own.estimated_wait_ms)}` : "";
          setModelStatus(`AI в очереди · позиция ${own.position}${eta}`, "warning");
        } else if (own.state === "running") {
          setModelStatus("AI обрабатывает запрос", "ok");
        }
      } catch (_) {
        // Основной запрос покажет ошибку; сбой служебного polling не должен его прерывать.
      }
    }, 2000);
    try {
      const requestFingerprint = clinicalFingerprint(patientData);
      const job = await api("/api/model/diagnose/jobs", {
        method: "POST",
        body: JSON.stringify({
          case_id: caseIdAtRun,
          patient_data: patientData
        })
      });
      jobId = job.job_id;
      awaitedDiagnosisJobIds.add(jobId);
      requestNotifyPermission();
      await refreshAiJobs();
      if (sameCase()) setModelStatus(`задание #${job.job_id} в очереди`, "warning");
      while (true) {
        await wait(2000);
        const jobStatus = await api(`/api/model/diagnose/jobs/${job.job_id}`);
        refreshAiJobs().catch(() => {});
        const item = jobStatus.job || {};
        if (item.status === "queued" || item.status === "running") {
          if (sameCase()) {
            setModelStatus(`задание #${item.id} ${item.status === "queued" ? "ожидает" : "выполняется"}`, item.status === "queued" ? "warning" : "ok");
          }
          continue;
        }
        response = jobStatus.result || {ok: false, error: item.user_error || item.error || "AI-задание завершилось без результата"};
        if (!response.ok) throw new Error(response.user_error || response.error || "AI-анализ завершился ошибкой");
        break;
      }
      if (!sameCase()) {
        // Результат остаётся у своего кейса: в открытую сейчас анкету его не переносим.
        announceForeignResult(caseIdAtRun, response.request_id, true);
        return;
      }
      modelPreview.textContent = JSON.stringify(response.parsed || response.response, null, 2);
      fillModelOutput(response.parsed);
      renderModelOutput(response.parsed, response);
      showReviewForm(response.request_id, null);
      currentModelRequestOk = true;
      openModelResultModal();
      lastModelDataFingerprint = requestFingerprint;
      setHtmlExportAvailable(true);
      const seconds = (Number(response.duration_ms || 0) / 1000).toFixed(1);
      const waited = Number(response.queue_wait_ms || 0) > 0 ? ` · очередь ${(Number(response.queue_wait_ms) / 1000).toFixed(1)} с` : "";
      setModelStatus(`AI-результат готов за ${seconds} с${waited}`, "ok");
      updateWorkflow(patientData);
      toast("Результат AI-анализа готов");
    } catch (err) {
      // Неуспешный запуск тоже получает request_id — результатом он от этого не становится.
      const resultWasSaved = Boolean(response?.ok && response?.request_id);
      if (!sameCase()) {
        if (resultWasSaved) announceForeignResult(caseIdAtRun, response.request_id, true);
        else announceForeignResult(caseIdAtRun, null, false, err.message);
        return;
      }
      if (!resultWasSaved) {
        modelPreview.textContent = err.message;
        showAiErrorCard(err.message);
      }
      setModelStatus(resultWasSaved ? "результат сохранён · ошибка отображения" : "ошибка AI-анализа", "error");
      if (resultWasSaved) {
        currentModelRequestId = response.request_id;
        currentModelRequestOk = true;
        setHtmlExportAvailable(true);
      }
      toast(resultWasSaved ? `Результат сохранён, но не отображён: ${err.message}` : err.message);
    } finally {
      window.clearInterval(queueTimer);
      if (jobId) awaitedDiagnosisJobIds.delete(jobId);
      aiRunningSessions.delete(session);
      markTitleReady();
      notifyDesktop(
        response?.ok ? "Результат AI-анализа готов" : "AI-анализ завершился",
        response?.ok ? "Откройте вкладку CVD Web, чтобы посмотреть результат." : "Проверьте статус задания в рабочем месте."
      );
      if (sameCase()) {
        if (diagnoseButton) diagnoseButton.disabled = false;
        updateWorkflow(updatePreview());
      }
    }
  }

  // Анализ закончился, когда врач уже работает с другим кейсом: сообщаем и даём перейти к результату.
  function announceForeignResult(caseId, requestId, ok, errorText = "") {
    const caseText = caseId ? `кейса #${caseId}` : "предыдущего кейса";
    if (!ok) {
      toast(`AI-анализ ${caseText} завершился ошибкой: ${errorText}`, {duration: 8000});
      return;
    }
    toast(`Результат AI-анализа ${caseText} готов`, {
      actionLabel: "Открыть",
      duration: 10000,
      onAction: () => openCaseResult(caseId, requestId).catch((err) => toast(err.message))
    });
  }

  async function openCaseResult(caseId, requestId) {
    if (!caseId) {
      openTaskCenterModal();
      return;
    }
    if (!(await openCase(caseId))) return;
    const response = await api(`/api/requests/${requestId}`);
    if (currentCaseId === caseId) openRequestResult(response.request);
  }

  function requestErrorText() {
    return "AI-анализ завершился ошибкой. Повторите запрос или обратитесь к администратору.";
  }

  function aiErrorAdviceText(message) {
    const text = String(message || "").toLowerCase();
    if (text.includes("контекст") || text.includes("context") || text.includes("слишком большой")) {
      return "Повторный запуск не поможет: данные кейса не помещаются в контекст модели. Сократите объёмные текстовые поля — анамнез, описания ЭКГ и исследований — или попросите администратора увеличить контекст модели.";
    }
    if (text.includes("недоступ") || text.includes("connection") || text.includes("unreachable")) {
      return "Сервис CVD Engine сейчас недоступен. Повторите попытку через минуту; если ошибка повторяется — сообщите администратору.";
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
    // При переполнении контекста повтор бессмыслен: сначала нужно сократить данные.
    const lowered = String(message || "").toLowerCase();
    const retryUseless = lowered.includes("контекст") || lowered.includes("context") || lowered.includes("слишком большой");
    const retryButton = document.getElementById("retryDiagnoseButton");
    if (retryButton) {
      retryButton.classList.toggle("hidden", retryUseless);
      retryButton.disabled = retryUseless;
    }
    card.classList.remove("hidden");
    card.scrollIntoView({behavior: "smooth", block: "nearest"});
  }

  function hideAiErrorCard() {
    document.getElementById("aiErrorCard")?.classList.add("hidden");
  }

  async function openCase(caseId) {
    const flush = await flushBeforeLeaving("открыть другой кейс");
    if (!flush.ok) return false;
    const response = await api(`/api/cases/${caseId}`);
    caseSession++;
    currentCaseId = response.case.id;
    // Администратор видит чужие кейсы, но сервер сохраняет только кейсы владельца.
    const ownerId = response.case.owner?.id;
    caseReadOnly = Boolean(ownerId && window.CURRENT_USER?.id && ownerId !== window.CURRENT_USER.id);
    lastSavedAt = response.case.updated_at ? new Date(response.case.updated_at) : null;
    saveErrorText = "";
    if (window.history?.replaceState) window.history.replaceState(null, "", `/app?case=${currentCaseId}`);
    if (flush.saved) {
      pendingDraft = null;
      draftBanner?.classList.add("hidden");
    }
    resetModelState();
    collapseAllSections();
    applyData(response.case.data);
    hideRecentCases();
    loadLatestCaseResult(currentCaseId).catch(() => {});
    if (caseReadOnly) {
      const owner = response.case.owner?.name || response.case.owner?.email || "другого пользователя";
      toast(`Кейс ${owner} открыт только для просмотра: правки не сохраняются`, {duration: 6000});
    } else {
      toast("Кейс загружен");
    }
    return true;
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
      meta.append(`#${item.id} · готовность ${quality.readiness_percent || 0}% · `, window.CVDUI.timeElement(item.updated_at));
      chip.append(title, meta);
      chip.addEventListener("click", () => openCase(item.id).catch((err) => toast(err.message)));
      list.appendChild(chip);
    });
    container.classList.remove("hidden");
  }

  function openRequestResult(item, {openModal = true} = {}) {
    // Тот же результат, загруженный повторно, не сбрасывает отметку «уже открыт».
    if (currentModelRequestId !== item.id) resultOpened = false;
    currentModelRequestId = item.id;
    currentModelRequestOk = item.status === "success";
    // Вердикт сервера о свежести переживает перезагрузку страницы, сравнение отпечатков — нет.
    resultStaleOnServer = currentModelRequestOk && serverResultStale(item);
    lastModelDataFingerprint = clinicalFingerprint(collectData());
    if (openModal) openTab("model");
    setModelStatus(
      currentModelRequestOk ? resultStaleOnServer ? "данные изменены после AI" : "AI-результат готов" : "AI: ошибка в последнем запуске",
      currentModelRequestOk ? resultStaleOnServer ? "warning" : "ok" : "error"
    );
    modelPreview.textContent = JSON.stringify(item.parsed_output || {error: requestErrorText()}, null, 2);
    renderModelOutput(item.parsed_output || {}, item);
    showReviewForm(item.id, item.review);
    setHtmlExportAvailable(item.status === "success");
    updateWorkflow(updatePreview());
  }

  async function loadLatestCaseResult(caseId) {
    const payload = await api(`/api/requests?case_id=${caseId}&status=success&limit=1`);
    const item = (payload.requests || [])[0];
    if (!item || !item.parsed_output) return;
    // Пока шёл запрос, мог открыться другой кейс или уже выбранный результат.
    if (currentCaseId !== caseId || currentModelRequestId) return;
    openRequestResult(item, {openModal: false});
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

  async function importPdf(file) {
    const response = await fetch("/api/import/pdf-text", {
      method: "POST",
      headers: {
        "Content-Type": "application/pdf",
        "X-CSRF-Token": csrfToken,
        "Accept": "application/json"
      },
      body: file
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    const fullText = String(data.text || "");
    openStructureTextModal();
    structureTextInput.value = fullText.slice(0, 10000);
    updateStructureTextCounter();
    if (fullText.length > 10000) {
      toast(`Текст из PDF обрезан до 10 000 символов (${data.pages} стр.) — проверьте перед AI-подготовкой`);
    } else {
      toast(`Текст извлечён из PDF (${data.pages} стр.). Проверьте его и запустите AI-подготовку`);
    }
  }

  async function importJson(file) {
    if (!file) return;
    if (file.size > maxImportBytes) {
      throw new Error("Файл больше 5 МБ");
    }
    if (file.type === "application/pdf" || /\.pdf$/i.test(file.name || "")) {
      await importPdf(file);
      return;
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

  function renderImportDecisionPanel(counts, rows) {
    if (!importDecisionPanel) return;
    const reliable = rows.filter((row) => shouldAutoSelectImportRow(row)).length;
    const conflicts = (counts.conflict || 0) + (counts["source-conflict"] || 0);
    const unchanged = counts.same || 0;
    importDecisionPanel.innerHTML = "";
    [
      ["Можно применить", reliable, "Поля с новым надежным значением уже выбраны.", "ok", selectNewImportFields],
      ["Нужна проверка", conflicts, "Конфликты не применяются без ручного выбора.", "warning", selectConflictedImportFields],
      ["Без изменений", unchanged, "Совпадающие поля будут пропущены.", "", clearImportSelection]
    ].forEach(([title, value, text, kind, action]) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = `import-decision-card ${kind}`.trim();
      const strong = document.createElement("strong");
      strong.textContent = String(value);
      const label = document.createElement("span");
      label.textContent = title;
      const hint = document.createElement("small");
      hint.textContent = text;
      card.append(strong, label, hint);
      card.addEventListener("click", action);
      importDecisionPanel.appendChild(card);
    });
  }

  function importFactGroup(path) {
    const [sectionKey] = String(path || "").split(".");
    const group = sectionGroupByKey.get(sectionKey);
    if (!group) return {key: "other", title: "Прочие данные"};
    if (group.key === "anamnesis") return {key: "anamnesis", title: "Анамнез"};
    if (group.key === "laboratory") return {key: "laboratory", title: "Лабораторные методы"};
    if (group.key === "instrumental") return {key: "instrumental", title: "Инструментальные методы"};
    if (group.key === "objective") return {key: "objective", title: "Объективный статус"};
    return {key: group.key, title: group.title};
  }

  function renderImportFactReview(rows) {
    if (!importFactReview) return;
    importFactReview.innerHTML = "";
    const groups = new Map();
    rows.forEach((row) => {
      const group = importFactGroup(row.mapping.path);
      const bucket = groups.get(group.key) || {title: group.title, rows: []};
      bucket.rows.push(row);
      groups.set(group.key, bucket);
    });
    if (!groups.size) {
      importFactReview.classList.add("hidden");
      return;
    }
    importFactReview.classList.remove("hidden");
    const header = document.createElement("div");
    header.className = "import-fact-review-head";
    const title = document.createElement("strong");
    title.textContent = "Проверка извлечённых фактов";
    const hint = document.createElement("span");
    hint.textContent = "Поля не попадут в карту, пока вы не выберете их и не нажмёте «Применить».";
    header.append(title, hint);
    importFactReview.appendChild(header);

    const list = document.createElement("div");
    list.className = "import-fact-groups";
    groups.forEach((group) => {
      const section = document.createElement("details");
      section.className = "import-fact-group";
      section.open = group.rows.some((row) => ["conflict", "source-conflict"].includes(row.state));
      const summary = document.createElement("summary");
      const summaryTitle = document.createElement("span");
      summaryTitle.textContent = group.title;
      const selected = group.rows.filter((row) => shouldAutoSelectImportRow(row)).length;
      summary.append(summaryTitle, pill(`${selected}/${group.rows.length}`, selected ? "ok" : "warning"));
      section.appendChild(summary);
      const body = document.createElement("div");
      body.className = "import-fact-list";
      group.rows.slice(0, 8).forEach((row) => {
        const meta = importFieldMeta(row.mapping.path);
        const item = document.createElement("button");
        item.type = "button";
        item.className = `import-fact-item ${row.state}`.trim();
        const label = document.createElement("strong");
        label.textContent = meta.label;
        const value = document.createElement("span");
        value.textContent = importValueText(row.mapping.value);
        const state = document.createElement("small");
        const stateLabels = {
          new: "новое значение",
          conflict: "конфликт с текущим",
          "source-conflict": "несколько значений",
          same: "без изменений"
        };
        state.textContent = stateLabels[row.state] || "проверить";
        item.append(label, value, state);
        item.addEventListener("click", () => {
          if (importDiffDetails) importDiffDetails.open = true;
          row.checkbox?.focus();
        });
        body.appendChild(item);
      });
      if (group.rows.length > 8) {
        const more = document.createElement("small");
        more.className = "muted";
        more.textContent = `Ещё полей: ${group.rows.length - 8}. Полный список в подробном сравнении.`;
        body.appendChild(more);
      }
      section.appendChild(body);
      list.appendChild(section);
    });
    importFactReview.appendChild(list);
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
    renderImportDecisionPanel(counts, rows);
    renderImportFactReview(rows);
    if (importDiffDetails) importDiffDetails.open = (counts.conflict || 0) + (counts["source-conflict"] || 0) > 0;

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
    importFactReview?.classList.add("hidden");
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
      manualEntry = true;
      const importedData = updatePreview();
      arrangeSections(importedData);
      scheduleDraftSave(importedData);
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

  function estimateCaseTokens(data) {
    // Та же эвристика, что и на сервере (примерно 3 символа на токен),
    // плюс постоянная часть промпта — чтобы цифры в UI и в отказе совпадали.
    const PROMPT_OVERHEAD_CHARS = 4200;
    return Math.round((JSON.stringify(data, null, 2).length + PROMPT_OVERHEAD_CHARS) / 3);
  }

  function contextBudget() {
    const settings = window.APP_SETTINGS || {};
    const context = Number(settings.lm_studio_context_tokens || 0);
    const reserve = Number(settings.lm_studio_max_tokens || 0);
    // Место для ответа модели тоже занимает контекст.
    return context ? Math.max(0, context - reserve) : 0;
  }

  function renderReviewContent(data) {
    reviewContent.innerHTML = "";
    const missing = missingRequiredData(data);
    const scenarioRequired = scenarioRequiredDataPoints();
    const ready = scenarioRequired.length - missing.length;
    const readinessPercent = Math.round((ready / scenarioRequired.length) * 100);
    // Справочные сигналы в проверку перед отправкой не выносим: здесь только то, что влияет на решение.
    const signals = qualityRules.clinicalSignals(data)
      .filter((signal) => signal.kind !== "info")
      .map((signal) => `${signal.title} — ${signal.text}`);
    const cards = [
      ["Пациент", displayValue(getValue(data, "GENERAL_INFO.Full_name"))],
      ["Случай", displayValue(getValue(data, "GENERAL_INFO.Patient_ID"))],
      ["Пол и возраст", window.CVDUI.demographicsText(getValue(data, "GENERAL_INFO.Age"), getValue(data, "GENERAL_INFO.Sex")) || "не указаны"],
      ["Готовность", `${readinessPercent}%`],
      // Объём в токенах понятнее размера JSON: именно он упирается в контекст модели.
      ["Объём для модели", `~${estimateCaseTokens(data).toLocaleString("ru-RU")} токенов`]
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
    // Переполнение контекста ловим до отправки: иначе врач ждёт минуту ради ошибки.
    const budget = contextBudget();
    const estimate = estimateCaseTokens(data);
    const overflows = Boolean(budget) && estimate > budget;
    if (confirmReviewButton) {
      confirmReviewButton.disabled = overflows;
      confirmReviewButton.title = overflows ? "Случай не помещается в контекст модели" : "";
    }
    if (overflows) {
      const warning = document.createElement("div");
      warning.className = "notice error-note";
      warning.textContent =
        `Случай не поместится в контекст модели: примерно ${estimate.toLocaleString("ru-RU")} токенов ` +
        `при доступных ${budget.toLocaleString("ru-RU")}. Сократите объёмные текстовые поля ` +
        "(анамнез, описания исследований) или попросите администратора увеличить контекст модели.";
      reviewContent.appendChild(warning);
    }
    reviewContent.appendChild(reviewList("Не хватает для полной готовности", missing.map(([, label]) => label), "Все ключевые поля заполнены."));
    reviewContent.appendChild(reviewList("Сигналы", signals, "Значимых сигналов по заполненным данным нет."));
    // Сырой JSON нужен исследователю, а не врачу: в режиме врача блок скрыт стилями.
    const technical = document.createElement("details");
    technical.className = "technical-response";
    const summary = document.createElement("summary");
    summary.textContent = "Данные для модели (JSON)";
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(data, null, 2);
    technical.append(summary, pre);
    reviewContent.appendChild(technical);
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
    currentModelRequestOk = false;
    resultStaleOnServer = false;
    lastModelDataFingerprint = null;
    lastModelParsed = null;
    lastModelMeta = {};
    resultOpened = false;
    setHtmlExportAvailable(false);
    hideAiErrorCard();
    updateModelTabVisibility();
    if (clearFields) {
      const modelSection = window.CVD_SCHEMA.find((section) => section.key === "MODEL_OUTPUT");
      modelSection?.fields.forEach((field) => setFieldValue(`MODEL_OUTPUT.${field.key}`, null));
    }
    modelPreview.textContent = "Технический ответ AI появится здесь.";
    modelStructured.textContent = "Структурированный ответ появится после AI-анализа.";
    lastModelSummary?.classList.add("hidden");
    if (lastModelSummary) lastModelSummary.innerHTML = "";
    renderModelWorkbench(null, collectData());
    setModelStatus("AI не запускался");
    requestReviewForm?.classList.add("hidden");
  }

  async function resetCase() {
    // Незаписанные правки текущего кейса сохраняются, прежде чем анкета очистится.
    const flush = await flushBeforeLeaving("начать новый кейс");
    if (!flush.ok) return;
    caseSession++;
    currentCaseId = null;
    caseReadOnly = false;
    lastSavedAt = null;
    saveErrorText = "";
    manualEntry = false;
    window.clearTimeout(draftSaveTimer);
    form.reset();
    collapseAllSections();
    resetModelState();
    // Если сохранить не удалось, локальный черновик — единственная копия правок.
    if (flush.saved) clearLocalDraft();
    else {
      pendingDraft = null;
      draftBanner?.classList.add("hidden");
    }
    if (window.history?.replaceState) window.history.replaceState(null, "", "/app");
    arrangeSections(updatePreview());
    setSaveState("не сохранено", false);
    window.scrollTo({top: 0, behavior: "smooth"});
    showRecentCases().catch(() => {});
  }

  function setupTabs() {
    document.querySelectorAll(".tab").forEach((button) => {
      button.addEventListener("click", () => openTab(button.dataset.tab));
    });
  }

  // Переключатель «Технические данные» живёт в общем модуле; здесь — реакция рабочего места на него.
  function onInterfaceModeChange() {
    if (isDoctorMode()) openTab("quality");
    arrangeSections(collectData());
    if (lastModelParsed) renderModelOutput(lastModelParsed, lastModelMeta);
  }

  function setupUser() {
    const user = window.CURRENT_USER || {};
    document.getElementById("userLabel").textContent = user.email || "";
    if (user.role === "admin") document.getElementById("adminLink").classList.remove("hidden");
    if (isDoctorMode()) openTab("quality");
    document.addEventListener("cvd:interface-mode", onInterfaceModeChange);
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
    openTaskCenterButton?.addEventListener("click", openTaskCenterModal);
    document.getElementById("closeTaskCenterModal")?.addEventListener("click", closeTaskCenterModal);
    document.getElementById("closeTaskCenterFooter")?.addEventListener("click", closeTaskCenterModal);
    document.getElementById("refreshTaskCenterButton")?.addEventListener("click", () => refreshAiJobs().catch((err) => toast(err.message)));
    taskCenterModal?.addEventListener("click", (event) => {
      if (event.target === taskCenterModal) closeTaskCenterModal();
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
      // Диалоги CVDUI закрываются сами; здесь — только модальные окна рабочего места.
      if (event.key !== "Escape" || window.CVDUI.dialogOpen()) return;
      const openModals = Array.from(document.querySelectorAll(".modal:not(.hidden):not(.ui-dialog)"));
      const modal = openModals[openModals.length - 1];
      if (!modal) return;
      event.preventDefault();
      if (modal === commandPalette) closeCommandPalette();
      else if (modal === importModal) closeImportModal();
      else if (modal === structureTextModal) closeStructureTextModal();
      else if (modal === taskCenterModal) closeTaskCenterModal();
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
      // После выхода сессия недействительна, поэтому правки отправляем до него.
      const flush = await flushBeforeLeaving("выйти");
      if (!flush.ok) return;
      const response = await api("/api/logout", { method: "POST", body: "{}" });
      // Черновик уже в localStorage; при намеренном выходе второй раз не предупреждаем.
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

  // Палитра команд (Cmd/Ctrl+K): действия рабочего места и поля анкеты в одном поиске.
  let paletteItems = [];
  let paletteIndex = 0;

  function paletteActions() {
    const data = collectData();
    const technical = !isDoctorMode();
    const hasResult = hasUsableResult();
    const user = window.CURRENT_USER || {};
    const theme = document.body.dataset.theme === "dark" ? "светлую" : "тёмную";
    return [
      {label: currentNextAction?.label || "Следующий шаг", hint: "главное действие", run: () => currentNextAction?.run?.(), enabled: Boolean(currentNextAction?.run) && !currentNextAction?.disabled},
      {label: "Новый кейс", run: () => resetCase()},
      {label: "Вставить текст выписки…", run: openStructureTextModal},
      {label: "Загрузить файл…", hint: "PDF, FHIR, CDA/СЭМД, .cvd.json", run: () => importJsonInput.click()},
      {label: "Запустить AI-анализ", shortcut: window.CVDUI.shortcut("↵"), run: diagnose, enabled: !aiBusy()},
      {label: "Проверить перед AI…", run: () => openReviewModal(null, false)},
      {label: "Открыть результат AI", run: () => openTab("model"), enabled: hasResult},
      {label: "Копировать для МИС", run: () => copyMisText(), enabled: hasResult},
      {label: "Пометить ошибку AI", run: markModelIssue, enabled: hasResult},
      {label: "Сохранить сейчас", shortcut: window.CVDUI.shortcut("S"), run: () => saveCase(), enabled: !caseReadOnly},
      {label: "К первому незаполненному ключевому полю", shortcut: window.CVDUI.shortcut("N", {alt: true}), run: () => focusFirstMissing(data), enabled: missingRequiredData(data).length > 0},
      {label: missingOnly ? "Показать всю анкету" : "Только незаполненные ключевые", run: () => { revealForm(); toggleMissingOnly(); }},
      {label: "Центр AI-задач", run: openTaskCenterModal},
      {label: "Кейсы и история", hint: "архив", run: () => { window.location.href = "/cases"; }},
      {label: "Админка", run: () => { window.location.href = "/admin"; }, enabled: user.role === "admin"},
      {label: `Включить ${theme} тему`, run: () => window.CVDTheme?.toggle()},
      {label: technical ? "Скрыть технические данные" : "Показать технические данные", run: () => window.CVDUI.setTechnicalData(!technical)},
      {label: "Скачать JSON", run: downloadJson, enabled: technical},
      {label: "Экспорт FHIR", run: () => downloadFHIR().catch((err) => toast(err.message)), enabled: technical && Boolean(currentCaseId)}
    ]
      .filter((item) => item.enabled !== false)
      // Главное действие часто совпадает с одним из пунктов списка — показываем его один раз.
      .filter((item, index, items) => items.findIndex((other) => other.label === item.label) === index)
      .map((item) => ({...item, kind: "action"}));
  }

  function paletteFieldItems(query) {
    const normalized = normalizeSearchText(query);
    if (normalized.length < 2) return [];
    return searchableSections().flatMap(({section, sectionIndex}) => section.fields.map((field) => ({
      kind: "field",
      label: field.label,
      hint: `${sectionNumber(sectionIndex)}. ${section.title}`,
      path: fieldPath(section.key, field.key),
      haystack: normalizeSearchText(`${field.label} ${field.key} ${section.title}`)
    })))
      .filter((item) => item.haystack.includes(normalized))
      .slice(0, 12)
      .map((item) => ({...item, run: () => focusFieldPath(item.path)}));
  }

  function renderCommandPalette() {
    const query = commandPaletteInput.value;
    const normalized = normalizeSearchText(query);
    const actions = paletteActions().filter((item) => !normalized || normalizeSearchText(`${item.label} ${item.hint || ""}`).includes(normalized));
    paletteItems = [...actions, ...paletteFieldItems(query)];
    paletteIndex = Math.min(paletteIndex, Math.max(0, paletteItems.length - 1));
    commandPaletteList.innerHTML = "";
    if (!paletteItems.length) {
      commandPaletteInput.removeAttribute("aria-activedescendant");
      const empty = document.createElement("p");
      empty.setAttribute("role", "presentation");
      empty.className = "palette-empty";
      empty.textContent = "Ничего не найдено. Попробуйте название поля: «тропонин», «ФВ», «МКБ».";
      commandPaletteList.appendChild(empty);
      return;
    }
    let lastKind = "";
    paletteItems.forEach((item, index) => {
      if (item.kind !== lastKind) {
        lastKind = item.kind;
        const heading = document.createElement("p");
        heading.className = "palette-heading";
        heading.setAttribute("role", "presentation");
        heading.textContent = item.kind === "action" ? "Действия" : "Поля анкеты";
        commandPaletteList.appendChild(heading);
      }
      const row = document.createElement("button");
      row.type = "button";
      row.id = `palette-item-${index}`;
      row.className = `palette-item ${index === paletteIndex ? "active" : ""}`.trim();
      row.setAttribute("role", "option");
      row.setAttribute("aria-selected", String(index === paletteIndex));
      const label = document.createElement("span");
      label.className = "palette-label";
      label.textContent = item.label;
      row.appendChild(label);
      if (item.hint) {
        const hint = document.createElement("span");
        hint.className = "palette-hint";
        hint.textContent = item.hint;
        row.appendChild(hint);
      }
      if (item.shortcut) {
        const kbd = document.createElement("kbd");
        kbd.className = "menu-shortcut";
        kbd.textContent = item.shortcut;
        row.appendChild(kbd);
      }
      row.addEventListener("mousemove", () => {
        if (paletteIndex === index) return;
        paletteIndex = index;
        highlightPaletteItem();
      });
      row.addEventListener("click", () => runPaletteItem(index));
      commandPaletteList.appendChild(row);
    });
    commandPaletteInput.setAttribute("aria-activedescendant", `palette-item-${paletteIndex}`);
  }

  function highlightPaletteItem() {
    commandPaletteList.querySelectorAll(".palette-item").forEach((row) => {
      const active = row.id === `palette-item-${paletteIndex}`;
      row.classList.toggle("active", active);
      row.setAttribute("aria-selected", String(active));
      if (active) row.scrollIntoView({block: "nearest"});
    });
    commandPaletteInput.setAttribute("aria-activedescendant", `palette-item-${paletteIndex}`);
  }

  function runPaletteItem(index) {
    const item = paletteItems[index];
    if (!item) return;
    // Фокус возвращается туда, откуда открыли палитру: окна, открытые командой, вернут его туда же.
    closeCommandPalette();
    Promise.resolve(item.run?.()).catch((err) => toast(err.message));
  }

  function openCommandPalette() {
    if (!commandPalette) return;
    commandPaletteInput.value = "";
    paletteIndex = 0;
    renderCommandPalette();
    openModalElement(commandPalette, commandPaletteInput);
  }

  function closeCommandPalette({restoreFocus = true} = {}) {
    if (!commandPalette || commandPalette.classList.contains("hidden")) return;
    if (!restoreFocus) modalTriggers.delete(commandPalette);
    closeModalElement(commandPalette);
  }

  function setupCommandPalette() {
    if (!commandPalette) return;
    document.getElementById("commandPaletteButton")?.addEventListener("click", openCommandPalette);
    commandPaletteInput.addEventListener("input", () => {
      paletteIndex = 0;
      renderCommandPalette();
    });
    commandPaletteInput.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        if (!paletteItems.length) return;
        const step = event.key === "ArrowDown" ? 1 : -1;
        paletteIndex = (paletteIndex + step + paletteItems.length) % paletteItems.length;
        highlightPaletteItem();
      } else if (event.key === "Enter") {
        // Ctrl/Cmd+Enter здесь выбирает пункт, а не запускает анализ глобальной комбинацией.
        event.preventDefault();
        event.stopPropagation();
        runPaletteItem(paletteIndex);
      }
    });
    commandPalette.addEventListener("click", (event) => {
      if (event.target === commandPalette) closeCommandPalette();
    });
  }

  async function initializeWorkspace() {
    const params = new URLSearchParams(window.location.search);
    if (params.get("import")) {
      document.getElementById("startFileButton")?.classList.add("attention");
      toast("Выберите «Загрузить файл»: PDF из ЕМИАС, FHIR, CDA/СЭМД или .cvd.json");
    }
    const caseId = Number(params.get("case") || 0);
    const requestId = Number(params.get("request") || 0);
    if (Number.isInteger(caseId) && caseId > 0) {
      await openCase(caseId);
      if (currentCaseId === caseId && !caseReadOnly) offerCaseDraft(caseId, lastSavedAt);
    }
    if (Number.isInteger(requestId) && requestId > 0) {
      const response = await api(`/api/requests/${requestId}`);
      openRequestResult(response.request);
    }
    if (!caseId && !requestId && !pendingDraft) {
      showRecentCases().catch(() => {});
    }
  }

  async function createDemoCase(button) {
    if (button) button.disabled = true;
    try {
      const response = await api("/api/cases/demo", {method: "POST", body: "{}"});
      if (await openCase(response.case_id)) toast("Демо-кейс создан: данные синтетические");
    } catch (err) {
      toast(err.message);
    } finally {
      if (button) button.disabled = false;
    }
  }

  // Изменения, не успевшие уйти автосохранением, отправляем при уходе со страницы.
  // keepalive переживает закрытие вкладки, но ограничен 64 КБ — большой кейс остаётся в локальном черновике.
  // Новый кейс так не создаём: ответ не прочитать, и восстановленный черновик создал бы второй такой же.
  function flushOnPageHide() {
    if (!hasUnsavedChanges || !currentCaseId || caseReadOnly) return;
    const data = collectData();
    // Те же данные уже уходят обычным запросом — второй не нужен.
    if (JSON.stringify(data) === inFlightSnapshot) return;
    const body = JSON.stringify({case_id: currentCaseId, patient_data: data});
    if (!fitsKeepalive(body)) return;
    try {
      fetch("/api/cases", {
        method: "POST",
        keepalive: true,
        headers: {"Content-Type": "application/json", "X-CSRF-Token": csrfToken},
        body
      }).catch(() => {});
    } catch (_) {}
  }

  window.CVDUI.applyInterfaceMode();
  watchStickyOffsets();
  renderForm();
  setupTabs();
  setupScenarioTemplates();
  setupUser();
  setupCommandPalette();
  updateStructureTextCounter();
  fieldSearchInput?.addEventListener("input", () => renderFieldSearchResults(fieldSearchInput.value));
  fieldSearchInput?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    const first = fieldSearchMatches(fieldSearchInput.value)[0];
    if (!first) return;
    event.preventDefault();
    fieldSearchInput.value = "";
    fieldSearchResults?.classList.add("hidden");
    focusFieldPath(first.path);
  });
  document.addEventListener("click", (event) => {
    if (!fieldSearchResults || fieldSearchResults.classList.contains("hidden")) return;
    if (event.target === fieldSearchInput || fieldSearchResults.contains(event.target)) return;
    fieldSearchResults.classList.add("hidden");
  });
  nextActionButton?.addEventListener("click", () => {
    Promise.resolve(currentNextAction?.run?.()).catch((err) => toast(err.message));
  });
  missingOnlyToggle?.addEventListener("click", () => toggleMissingOnly());
  document.getElementById("startPasteButton")?.addEventListener("click", openStructureTextModal);
  document.getElementById("startFileButton")?.addEventListener("click", (event) => {
    event.currentTarget.classList.remove("attention");
    importJsonInput.click();
  });
  document.getElementById("startManualButton")?.addEventListener("click", () => {
    revealForm();
    focusFirstMissing(collectData());
  });
  document.getElementById("startDemoButton")?.addEventListener("click", (event) => createDemoCase(event.currentTarget));
  acceptModelDraftButton?.addEventListener("click", () => acceptModelDiagnosisDraft().catch((err) => toast(err.message)));
  copyModelDiagnosisButton?.addEventListener("click", () => copyModelDiagnosis().catch((err) => toast(err.message)));
  openModelReportButton?.addEventListener("click", () => viewHtmlResult().catch((err) => toast(err.message)));
  // Оценка сохраняется сразу по нажатию — подробности можно дописать позже.
  requestReviewForm?.querySelectorAll('input[name="rating"]').forEach((input) => {
    input.addEventListener("change", scheduleRatingSave);
  });
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
    if (!hasUnsavedChanges || caseReadOnly) return;
    window.clearTimeout(draftSaveTimer);
    try { writeLocalDraft(collectData()); } catch (_) {}
    event.preventDefault();
    event.returnValue = "";
  });
  window.addEventListener("pagehide", flushOnPageHide);
  // Вкладку могут закрыть, пока она в фоне: сохраняем сразу, но не чаще обычного интервала
  // (каждое сохранение пишется в журнал аудита). Запрос keepalive переживёт закрытие вкладки.
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      document.title = baseDocumentTitle;
      return;
    }
    if (!hasUnsavedChanges || !currentCaseId || saveInFlight) return;
    if (Date.now() - lastSaveAttemptAt < autosaveMinIntervalMs) return;
    autosave({keepalive: true});
  });
  // Страница вернулась из кеша «назад/вперёд»: досохраняем то, что могло не уйти при уходе.
  window.addEventListener("pageshow", (event) => {
    if (event.persisted && hasUnsavedChanges) scheduleAutosave();
  });
  document.addEventListener("keydown", (event) => {
    if (event.defaultPrevented) return;
    const modKey = event.metaKey || event.ctrlKey;
    const modalOpen = Boolean(document.querySelector(".modal:not(.hidden)"));
    if (modKey && !event.shiftKey && !event.altKey && event.code === "KeyK") {
      event.preventDefault();
      if (commandPalette && !commandPalette.classList.contains("hidden")) closeCommandPalette();
      else if (!modalOpen) openCommandPalette();
      return;
    }
    if (modKey && !event.shiftKey && !event.altKey && event.code === "KeyS") {
      event.preventDefault();
      saveCase().catch((err) => toast(err.message));
      return;
    }
    if (modKey && !event.shiftKey && !event.altKey && event.key === "Enter" && !modalOpen) {
      event.preventDefault();
      diagnose();
      return;
    }
    // Поверх анкеты открыто окно — переход к полю под ним только сбил бы фокус.
    if (event.altKey && !modKey && event.code === "KeyN" && !modalOpen) {
      event.preventDefault();
      focusFirstMissing();
    }
  });
  restoreDraftButton?.addEventListener("click", restoreLocalDraft);
  dismissDraftButton?.addEventListener("click", () => draftBanner?.classList.add("hidden"));
  document.getElementById("saveCaseButton").addEventListener("click", () => saveCase().catch((err) => toast(err.message)));
  document.getElementById("diagnoseButton").addEventListener("click", diagnose);
  document.getElementById("retryDiagnoseButton")?.addEventListener("click", () => {
    if (aiBusy()) return;
    hideAiErrorCard();
    runDiagnose(updatePreview()).catch((err) => toast(err.message));
  });
  document.getElementById("rerunAnalysisButton")?.addEventListener("click", () => {
    closeModelResultModal();
    diagnose();
  });
  document.getElementById("downloadJsonButton").addEventListener("click", downloadJson);
  exportHtmlButton?.addEventListener("click", () => exportHtmlReport().catch((err) => toast(err.message)));
  document.getElementById("copyMisTextButton")?.addEventListener("click", () => copyMisText().catch((err) => toast(err.message)));
  document.getElementById("importJsonButton").addEventListener("click", () => importJsonInput.click());
  importJsonInput.addEventListener("change", () => {
    const file = importJsonInput.files?.[0];
    importJson(file).catch((err) => toast(err.message)).finally(() => {
      importJsonInput.value = "";
    });
  });
  document.getElementById("downloadFhirButton").addEventListener("click", () => downloadFHIR().catch((err) => toast(err.message)));
  document.getElementById("newCaseButton").addEventListener("click", () => resetCase().catch((err) => toast(err.message)));
  document.getElementById("demoCaseButton")?.addEventListener("click", (event) => createDemoCase(event.currentTarget));
  updatePreview();
  initDraftRestore();
  refreshAiJobs().catch(() => {});
  activeJobsTimer = window.setInterval(() => {
    refreshAiJobs().catch(() => {});
  }, 5000);
  // «Сохранено 2 мин назад» должно стареть, даже если врач ничего не трогает.
  window.setInterval(() => syncStatusBar(), 30000);
  initializeWorkspace().catch((err) => toast(err.message));
})();
