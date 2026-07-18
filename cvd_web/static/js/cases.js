(function () {
  "use strict";

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const state = {
    view: "cases",
    cases: [],
    results: [],
    imports: [],
    preparations: [],
    selectedCaseId: null,
    selectedCase: null,
    latestResultId: null,
    caseSequence: 0,
    detailSequence: 0,
    resultSequence: 0,
    importSequence: 0,
    preparationSequence: 0
  };

  const nodes = {
    libraryLoading: document.getElementById("libraryLoading"),
    libraryError: document.getElementById("libraryError"),
    casesMetric: document.getElementById("casesMetric"),
    resultsMetric: document.getElementById("resultsMetric"),
    successMetric: document.getElementById("successMetric"),
    importsMetric: document.getElementById("importsMetric"),
    caseSearch: document.getElementById("caseSearchInput"),
    caseAnalysis: document.getElementById("caseAnalysisFilter"),
    caseCount: document.getElementById("caseCount"),
    casesList: document.getElementById("casesList"),
    moreCases: document.getElementById("loadMoreCasesButton"),
    detailEmpty: document.getElementById("caseDetailEmpty"),
    detailContent: document.getElementById("caseDetailContent"),
    detailTitle: document.getElementById("caseDetailTitle"),
    detailMeta: document.getElementById("caseDetailMeta"),
    caseQuality: document.getElementById("caseQuality"),
    clinicalSummary: document.getElementById("caseClinicalSummary"),
    caseTimeline: document.getElementById("caseTimeline"),
    caseResults: document.getElementById("caseResultsList"),
    editCase: document.getElementById("editCaseLink"),
    caseResult: document.getElementById("caseResultButton"),
    copyCase: document.getElementById("copyCaseButton"),
    fhirCase: document.getElementById("fhirCaseButton"),
    deleteCase: document.getElementById("deleteCaseButton"),
    resultSearch: document.getElementById("resultSearchInput"),
    resultStatus: document.getElementById("resultStatusFilter"),
    resultModel: document.getElementById("resultModelFilter"),
    resultReview: document.getElementById("resultReviewFilter"),
    resultRedFlags: document.getElementById("resultRedFlagsFilter"),
    resultAbstain: document.getElementById("resultAbstainFilter"),
    resultsCount: document.getElementById("resultsCount"),
    resultsList: document.getElementById("resultsList"),
    moreResults: document.getElementById("loadMoreResultsButton"),
    importSearch: document.getElementById("importSearchInput"),
    importStatus: document.getElementById("importStatusFilter"),
    importsCount: document.getElementById("importsCount"),
    importsList: document.getElementById("importsList"),
    moreImports: document.getElementById("loadMoreImportsButton"),
    preparationSearch: document.getElementById("preparationSearchInput"),
    preparationStatus: document.getElementById("preparationStatusFilter"),
    preparationsCount: document.getElementById("preparationsCount"),
    preparationsList: document.getElementById("preparationsList"),
    morePreparations: document.getElementById("loadMorePreparationsButton")
  };

  let caseSearchTimer = null;
  let resultSearchTimer = null;
  let importSearchTimer = null;
  let preparationSearchTimer = null;

  let interfaceMode = "doctor";
  try { interfaceMode = window.localStorage.getItem("cvd:interface-mode") || "doctor"; } catch (_) {}
  if (interfaceMode === "admin" && window.CURRENT_USER?.role !== "admin") interfaceMode = "doctor";

  function displayModelName(model) {
    // Врач видит бренд сервиса, а не внутреннее имя модели.
    return interfaceMode === "doctor" ? "CVD Engine" : (model || "модель не указана");
  }

  if (interfaceMode === "doctor") {
    document.getElementById("resultModelFilter")?.classList.add("hidden");
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
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  function toast(message) {
    const item = document.createElement("div");
    item.className = "toast";
    item.textContent = message;
    document.body.appendChild(item);
    window.setTimeout(() => item.remove(), 3200);
  }

  function setLoading(loading) {
    nodes.libraryLoading.classList.toggle("hidden", !loading);
  }

  function showError(error = "") {
    nodes.libraryError.textContent = error;
    nodes.libraryError.classList.toggle("hidden", !error);
  }

  function formatDateTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value || "");
    return new Intl.DateTimeFormat("ru-RU", {
      day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit"
    }).format(date);
  }

  function valueAt(data, section, field, fallback = "Не указано") {
    const value = data?.[section]?.[field];
    if (Array.isArray(value)) return value.length ? value.join("; ") : fallback;
    return value === null || value === undefined || value === "" ? fallback : String(value);
  }

  function pill(text, kind = "") {
    const node = document.createElement("span");
    node.className = `pill ${kind}`.trim();
    node.textContent = text;
    return node;
  }

  function actionLink(label, href, primary = false) {
    const link = document.createElement("a");
    link.className = `button ${primary ? "primary-link" : ""}`.trim();
    link.href = href;
    link.textContent = label;
    if (href.startsWith("/reports/")) {
      link.target = "_blank";
      link.rel = "noopener";
    }
    return link;
  }

  function caseWorkflowStatus(item) {
    const quality = item.quality || {};
    if (item.ai_result_stale) return ["Данные изменены после AI", "warning"];
    if (item.latest_request_status === "error") return ["AI завершился ошибкой", "error"];
    if (item.has_review) return ["Проверен врачом", "ok"];
    if (item.latest_result_id) return ["Ожидает экспертной проверки", "warning"];
    if (Number(quality.critical_signals || 0) > 0) return ["Есть критические сигналы", "error"];
    if (Number(quality.readiness_percent || 0) === 100) return ["Готов к AI", "ok"];
    if (Number(quality.readiness_percent || 0) > 0) return ["Черновик: данные неполные", "warning"];
    return ["Черновик без AI", "warning"];
  }

  function caseStatusDescription(item) {
    const quality = item.quality || {};
    if (item.ai_result_stale) return "данные кейса изменились после последнего AI-результата";
    if (item.latest_request_status === "error") return "последний запуск требует внимания";
    if (item.has_review) return "результат содержит экспертную оценку";
    if (item.latest_result_id) return `последний отчёт #${item.latest_result_id}`;
    if (Number(quality.critical_signals || 0) > 0) return `${quality.critical_signals} крит. сигналов, проверьте данные`;
    if (Number(quality.readiness_percent || 0) === 100) return "ключевые данные заполнены, можно запускать AI";
    if (Number(item.analysis_count || 0) > 0) return "результаты есть, проверьте актуальность";
    return "сохранённые данные ещё не отправлялись в AI";
  }

  function actionButton(label, onClick, options = {}) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    if (options.primary) button.classList.add("primary");
    if (options.disabled) button.disabled = true;
    button.addEventListener("click", onClick);
    return button;
  }

  async function loadSummary() {
    const response = await api("/api/library/summary");
    const summary = response.summary || {};
    const total = Number(summary.requests_total || 0);
    const success = Number(summary.requests_success || 0);
    nodes.casesMetric.textContent = String(summary.cases_total || 0);
    nodes.resultsMetric.textContent = String(total);
    nodes.successMetric.textContent = total ? `${Math.round(success * 100 / total)}%` : "0%";
    nodes.importsMetric.textContent = String(summary.imports_total || 0);
  }

  async function loadCases(append = false) {
    const sequence = ++state.caseSequence;
    const query = nodes.caseSearch.value.trim();
    const analysis = nodes.caseAnalysis.value;
    const offset = append ? state.cases.length : 0;
    const response = await api(
      `/api/cases?q=${encodeURIComponent(query)}&analysis=${encodeURIComponent(analysis)}&limit=50&offset=${offset}`
    );
    if (sequence !== state.caseSequence) return;
    state.cases = append ? [...state.cases, ...(response.cases || [])] : (response.cases || []);
    nodes.caseCount.textContent = `${response.total || 0} кейсов`;
    nodes.moreCases.classList.toggle("hidden", !response.has_more);
    renderCases();
    if (!append && state.cases.length && !state.cases.some((item) => item.id === state.selectedCaseId)) {
      await selectCase(state.cases[0].id);
    } else if (!state.cases.length) {
      clearCaseDetail();
    }
  }

  function renderCases() {
    nodes.casesList.innerHTML = "";
    if (!state.cases.length) {
      nodes.casesList.className = "record-list record-empty";
      const filtered = Boolean(nodes.caseSearch.value.trim() || nodes.caseAnalysis.value);
      const title = document.createElement("strong");
      title.textContent = filtered ? "По заданным фильтрам ничего не найдено" : "Кейсов пока нет";
      const hint = document.createElement("span");
      hint.textContent = filtered
        ? "Попробуйте изменить запрос или сбросить фильтры."
        : "Создайте первый кейс в рабочем месте или импортируйте данные пациента.";
      const actions = document.createElement("div");
      actions.className = "toolbar empty-state-actions";
      if (filtered) {
        const resetButton = document.createElement("button");
        resetButton.type = "button";
        resetButton.textContent = "Сбросить фильтры";
        resetButton.addEventListener("click", () => document.getElementById("clearCaseFiltersButton")?.click());
        actions.appendChild(resetButton);
      } else {
        const createLink = document.createElement("a");
        createLink.className = "button primary-link";
        createLink.href = "/app";
        createLink.textContent = "Создать кейс";
        const importLink = document.createElement("a");
        importLink.className = "button";
        importLink.href = "/app?import=1";
        importLink.textContent = "Импортировать";
        const demoButton = document.createElement("button");
        demoButton.type = "button";
        demoButton.textContent = "Создать демо-кейс";
        demoButton.addEventListener("click", async () => {
          demoButton.disabled = true;
          try {
            const response = await api("/api/cases/demo", {method: "POST", body: "{}"});
            window.location.href = `/app?case=${response.case_id}`;
          } catch (error) {
            demoButton.disabled = false;
            handleError(error);
          }
        });
        actions.append(createLink, importLink, demoButton);
      }
      nodes.casesList.append(title, hint, actions);
      return;
    }
    nodes.casesList.className = "record-list";
    state.cases.forEach((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `record-list-item ${item.id === state.selectedCaseId ? "selected" : ""}`.trim();
      button.dataset.caseId = String(item.id);
      const head = document.createElement("span");
      head.className = "record-list-head";
      const title = document.createElement("strong");
      title.textContent = item.title;
      const [statusText, statusKind] = caseWorkflowStatus(item);
      head.append(title, pill(statusText, statusKind));
      const patient = document.createElement("span");
      patient.textContent = item.patient_id ? `ID пациента: ${item.patient_id}` : "ID пациента не указан";
      const meta = document.createElement("small");
      const quality = item.quality || {};
      meta.textContent = `Кейс #${item.id} · готовность ${quality.readiness_percent || 0}% · сигналов ${(quality.signals || []).length} · ${item.analysis_count || 0} анализов · ${caseStatusDescription(item)} · ${formatDateTime(item.updated_at)}`;
      button.append(head, patient, meta);
      button.addEventListener("click", () => selectCase(item.id).catch(handleError));
      nodes.casesList.appendChild(button);
    });
  }

  function clearCaseDetail() {
    state.selectedCaseId = null;
    state.selectedCase = null;
    state.latestResultId = null;
    nodes.detailEmpty.querySelector("strong").textContent = "Выберите кейс";
    nodes.detailEmpty.classList.remove("hidden");
    nodes.detailContent.classList.add("hidden");
  }

  async function selectCase(caseId) {
    state.selectedCaseId = Number(caseId);
    renderCases();
    const sequence = ++state.detailSequence;
    nodes.detailEmpty.classList.remove("hidden");
    nodes.detailEmpty.querySelector("strong").textContent = "Загрузка кейса...";
    nodes.detailContent.classList.add("hidden");
    const [caseResponse, resultsResponse, importsResponse] = await Promise.all([
      api(`/api/cases/${caseId}`),
      api(`/api/requests?case_id=${caseId}&limit=30`),
      api(`/api/imports?case_id=${caseId}&limit=30`)
    ]);
    if (sequence !== state.detailSequence) return;
    const listItem = state.cases.find((item) => item.id === Number(caseId));
    state.selectedCase = caseResponse.case;
    state.latestResultId = listItem?.latest_result_id || resultsResponse.requests?.find((item) => item.status === "success")?.id || null;
    renderCaseDetail(caseResponse.case, resultsResponse.requests || [], importsResponse.imports || [], listItem);
  }

  function renderCaseDetail(caseItem, results, imports, listItem) {
    nodes.detailEmpty.classList.add("hidden");
    nodes.detailContent.classList.remove("hidden");
    nodes.detailTitle.textContent = caseItem.title;
    nodes.detailMeta.innerHTML = "";
    nodes.detailMeta.append(
      pill(`Кейс #${caseItem.id}`),
      pill(caseItem.patient_id ? `ID ${caseItem.patient_id}` : "без ID", caseItem.patient_id ? "ok" : "warning"),
      pill(...caseWorkflowStatus(listItem || {analysis_count: results.length, latest_result_id: state.latestResultId, latest_request_status: results[0]?.status, quality: caseItem.quality || {}})),
      pill(caseStatusDescription(listItem || {analysis_count: results.length, latest_result_id: state.latestResultId, latest_request_status: results[0]?.status, quality: caseItem.quality || {}})),
      pill(`${listItem?.analysis_count || results.length} анализов`)
    );
    nodes.editCase.href = `/app?case=${caseItem.id}`;
    nodes.caseResult.disabled = !state.latestResultId;
    renderCaseQuality(caseItem.quality || {});
    renderClinicalSummary(caseItem.data || {});
    renderCaseResults(results);
    renderCaseTimeline(caseItem, results, imports);
  }

  function renderCaseQuality(quality) {
    nodes.caseQuality.innerHTML = "";
    const values = [
      ["Заполненность", `${quality.completeness_percent || 0}%`],
      ["Готовность", `${quality.readiness_percent || 0}%`],
      ["Сигналы", String((quality.signals || []).length)],
      ["Критические", String(quality.critical_signals || 0)]
    ];
    values.forEach(([label, value]) => {
      const card = document.createElement("div");
      const caption = document.createElement("span");
      caption.textContent = label;
      const strong = document.createElement("strong");
      strong.textContent = value;
      card.append(caption, strong);
      nodes.caseQuality.appendChild(card);
    });
  }

  function renderClinicalSummary(data) {
    nodes.clinicalSummary.innerHTML = "";
    const fields = [
      ["Пациент", valueAt(data, "GENERAL_INFO", "Full_name")],
      ["Возраст / пол", `${valueAt(data, "GENERAL_INFO", "Age", "?")} лет · ${valueAt(data, "GENERAL_INFO", "Sex", "?")}`],
      ["Основная жалоба", valueAt(data, "COMPLAINTS", "Main_complaint")],
      ["Рабочий диагноз", valueAt(data, "FINAL_DIAGNOSES", "Main_cardiovascular_diagnosis_text")]
    ];
    fields.forEach(([label, value]) => {
      const row = document.createElement("div");
      const caption = document.createElement("span");
      caption.textContent = label;
      const text = document.createElement("strong");
      text.textContent = value;
      row.append(caption, text);
      nodes.clinicalSummary.appendChild(row);
    });
  }

  function renderCaseResults(items) {
    nodes.caseResults.innerHTML = "";
    if (!items.length) {
      nodes.caseResults.textContent = "Анализов по этому кейсу пока нет.";
      return;
    }
    items.forEach((item) => {
      const row = document.createElement("div");
      row.className = "compact-history-item";
      const title = document.createElement("strong");
      title.textContent = `Результат #${item.id}`;
      const meta = document.createElement("small");
      meta.textContent = `${item.status === "success" ? "готов" : "ошибка"} · ${formatDateTime(item.created_at)}`;
      const actions = document.createElement("div");
      actions.className = "toolbar";
      if (item.status === "success") actions.appendChild(actionLink("Отчёт", `/reports/${item.id}`, true));
      actions.appendChild(actionLink(item.review ? "Оценка" : "Оценить", `/app?request=${item.id}`));
      row.append(title, meta, actions);
      nodes.caseResults.appendChild(row);
    });
  }

  function renderCaseTimeline(caseItem, results, imports) {
    const events = [{when: caseItem.updated_at, kind: "case", text: "Кейс обновлён"}];
    results.forEach((item) => events.push({
      when: item.created_at,
      kind: item.status,
      text: `AI-анализ #${item.id}: ${item.status === "success" ? "результат готов" : "ошибка"}`
    }));
    imports.forEach((item) => events.push({
      when: item.applied_at || item.created_at,
      kind: item.status === "applied" ? "case" : "warning",
      text: `Импорт #${item.id}: ${item.status === "applied" ? "применён" : "подготовлен"}`
    }));
    events.sort((a, b) => String(b.when).localeCompare(String(a.when)));
    nodes.caseTimeline.innerHTML = "";
    events.forEach((event) => {
      const row = document.createElement("div");
      row.className = `timeline-item ${event.kind}`;
      const dot = document.createElement("span");
      dot.className = "timeline-dot";
      const content = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = event.text;
      const time = document.createElement("small");
      time.textContent = formatDateTime(event.when);
      content.append(title, time);
      row.append(dot, content);
      nodes.caseTimeline.appendChild(row);
    });
  }

  async function loadResults(append = false) {
    const sequence = ++state.resultSequence;
    const query = nodes.resultSearch.value.trim();
    const status = nodes.resultStatus.value;
    const model = nodes.resultModel.value;
    const review = nodes.resultReview.value;
    const redFlags = nodes.resultRedFlags.value;
    const abstain = nodes.resultAbstain.value;
    const offset = append ? state.results.length : 0;
    const response = await api(
      `/api/requests?q=${encodeURIComponent(query)}&status=${encodeURIComponent(status)}&model=${encodeURIComponent(model)}&review=${encodeURIComponent(review)}&red_flags=${encodeURIComponent(redFlags)}&abstain=${encodeURIComponent(abstain)}&limit=50&offset=${offset}`
    );
    if (sequence !== state.resultSequence) return;
    state.results = append ? [...state.results, ...(response.requests || [])] : (response.requests || []);
    updateModelFilter(response.filters?.models || []);
    nodes.resultsCount.textContent = `${response.total || 0} результатов`;
    nodes.moreResults.classList.toggle("hidden", !response.has_more);
    renderResults();
  }

  function updateModelFilter(models) {
    const selected = nodes.resultModel.value;
    const known = new Set(Array.from(nodes.resultModel.options).map((option) => option.value));
    models.forEach((model) => {
      if (!known.has(model)) {
        const option = document.createElement("option");
        option.value = model;
        option.textContent = model;
        nodes.resultModel.appendChild(option);
      }
    });
    nodes.resultModel.value = selected;
  }

  function reviewLabel(rating) {
    return {useful: "полезно", partial: "частично", wrong: "неверно", unsafe: "небезопасно"}[rating] || "без оценки";
  }

  function renderResults() {
    nodes.resultsList.innerHTML = "";
    if (!state.results.length) {
      nodes.resultsList.className = "result-records record-empty";
      nodes.resultsList.textContent = "Результаты не найдены.";
      return;
    }
    nodes.resultsList.className = "result-records";
    state.results.forEach((item) => {
      const card = document.createElement("article");
      card.className = "result-record";
      const heading = document.createElement("div");
      heading.className = "result-record-heading";
      const title = document.createElement("strong");
      title.textContent = `Результат #${item.id}`;
      heading.append(title, pill(item.status === "success" ? "готов" : "ошибка", item.status === "success" ? "ok" : "error"));
      const flags = item.result_flags || {};
      if (flags.red_flags_count) heading.appendChild(pill(`red flags: ${flags.red_flags_count}`, "error"));
      if (flags.model_should_abstain) heading.appendChild(pill("abstain", "warning"));
      heading.appendChild(pill(reviewLabel(item.review?.rating), item.review ? "ok" : ""));
      const caseText = document.createElement("small");
      caseText.textContent = item.case_id
        ? `${item.case_title || `Кейс #${item.case_id}`} · ${item.patient_id || "ID не указан"}`
        : "Кейс удалён или не был сохранён";
      const summary = document.createElement("p");
      summary.textContent = item.status === "success"
        ? item.parsed_output?.CDS_OUTPUT?.summary || "Клиническая сводка не указана."
        : "AI-анализ завершился ошибкой. Технические детали доступны администратору.";
      const footer = document.createElement("div");
      footer.className = "result-record-footer";
      const meta = document.createElement("span");
      meta.textContent = `${formatDateTime(item.created_at)} · ${displayModelName(item.model)} · ${(Number(item.duration_ms || 0) / 1000).toFixed(1)} с`;
      const actions = document.createElement("div");
      actions.className = "toolbar";
      if (item.status === "success") actions.appendChild(actionLink("Открыть отчёт", `/reports/${item.id}`, true));
      actions.appendChild(actionLink(item.review ? "Открыть оценку" : "Оценить", `/app?request=${item.id}`));
      if (item.case_id) actions.appendChild(actionLink("Открыть кейс", `/app?case=${item.case_id}`));
      footer.append(meta, actions);
      card.append(heading, caseText, summary, footer);
      nodes.resultsList.appendChild(card);
    });
  }

  async function loadImports(append = false) {
    const sequence = ++state.importSequence;
    const query = nodes.importSearch.value.trim();
    const status = nodes.importStatus.value;
    const offset = append ? state.imports.length : 0;
    const response = await api(
      `/api/imports?q=${encodeURIComponent(query)}&status=${encodeURIComponent(status)}&limit=50&offset=${offset}`
    );
    if (sequence !== state.importSequence) return;
    state.imports = append ? [...state.imports, ...(response.imports || [])] : (response.imports || []);
    nodes.importsCount.textContent = `${response.total || 0} импортов`;
    nodes.moreImports.classList.toggle("hidden", !response.has_more);
    renderImports();
  }

  function renderImports() {
    nodes.importsList.innerHTML = "";
    if (!state.imports.length) {
      nodes.importsList.className = "import-records record-empty";
      nodes.importsList.textContent = "Импорты не найдены.";
      return;
    }
    nodes.importsList.className = "import-records";
    state.imports.forEach((item) => {
      const card = document.createElement("article");
      card.className = "import-record";
      const heading = document.createElement("div");
      heading.className = "result-record-heading";
      const title = document.createElement("strong");
      title.textContent = item.filename || `Импорт #${item.id}`;
      heading.append(title, pill(item.status === "applied" ? "применён" : "подготовлен", item.status === "applied" ? "ok" : "warning"));
      const meta = document.createElement("p");
      meta.textContent = `${item.source_format} · сопоставлено полей: ${item.mapped_fields} · предупреждений: ${item.warning_count}`;
      const footer = document.createElement("div");
      footer.className = "result-record-footer";
      const date = document.createElement("span");
      date.textContent = formatDateTime(item.applied_at || item.created_at);
      footer.appendChild(date);
      if (item.case_id) footer.appendChild(actionLink(item.case_title || `Кейс #${item.case_id}`, `/app?case=${item.case_id}`));
      card.append(heading, meta, footer);
      nodes.importsList.appendChild(card);
    });
  }

  async function loadPreparations(append = false) {
    const sequence = ++state.preparationSequence;
    const query = nodes.preparationSearch.value.trim();
    const status = nodes.preparationStatus.value;
    const offset = append ? state.preparations.length : 0;
    const response = await api(
      `/api/text-preparations?q=${encodeURIComponent(query)}&status=${encodeURIComponent(status)}&limit=50&offset=${offset}`
    );
    if (sequence !== state.preparationSequence) return;
    state.preparations = append ? [...state.preparations, ...(response.text_preparations || [])] : (response.text_preparations || []);
    nodes.preparationsCount.textContent = `${response.total || 0} подготовок`;
    nodes.morePreparations.classList.toggle("hidden", !response.has_more);
    renderPreparations();
  }

  function renderPreparations() {
    nodes.preparationsList.innerHTML = "";
    if (!state.preparations.length) {
      nodes.preparationsList.className = "import-records record-empty";
      nodes.preparationsList.textContent = "AI-подготовки не найдены.";
      return;
    }
    nodes.preparationsList.className = "import-records";
    state.preparations.forEach((item) => {
      const card = document.createElement("article");
      card.className = "import-record";
      const heading = document.createElement("div");
      heading.className = "result-record-heading";
      const title = document.createElement("strong");
      title.textContent = `${item.source_label || "AI-подготовка"} #${item.id}`;
      const statusKind = item.status === "applied" ? "ok" : item.status === "archived" ? "" : "warning";
      heading.append(title, pill(item.status === "applied" ? "применено" : item.status === "archived" ? "архив" : "подготовлено", statusKind));
      const meta = document.createElement("p");
      meta.textContent = `полей: ${item.mapped_fields || 0} · предупреждений: ${item.warning_count || 0} · импорт #${item.import_id || "—"}`;
      const preview = document.createElement("p");
      preview.textContent = item.corrected_text_preview || "Текстовый фрагмент не сохранён.";
      const footer = document.createElement("div");
      footer.className = "result-record-footer";
      const date = document.createElement("span");
      date.textContent = formatDateTime(item.applied_at || item.updated_at || item.created_at);
      footer.appendChild(date);
      if (item.case_id) footer.appendChild(actionLink(item.case_title || `Кейс #${item.case_id}`, `/app?case=${item.case_id}`));
      card.append(heading, meta, preview, footer);
      nodes.preparationsList.appendChild(card);
    });
  }

  async function switchView(view) {
    state.view = view;
    document.querySelectorAll(".records-tab").forEach((button) => {
      button.classList.toggle("active", button.dataset.libraryView === view);
    });
    document.querySelectorAll(".library-view").forEach((section) => {
      section.classList.toggle("hidden", section.id !== `library-${view}`);
    });
    if (view === "results" && !state.results.length) await loadResults();
    if (view === "imports" && !state.imports.length) await loadImports();
    if (view === "preparations" && !state.preparations.length) await loadPreparations();
  }

  async function refreshActiveView() {
    setLoading(true);
    showError();
    try {
      await Promise.all([
        loadSummary(),
        state.view === "cases" ? loadCases() : state.view === "results" ? loadResults() : state.view === "imports" ? loadImports() : loadPreparations()
      ]);
    } catch (error) {
      showError(error.message);
    } finally {
      setLoading(false);
    }
  }

  function handleError(error) {
    showError(error.message);
    toast(error.message);
  }

  function debounce(timerName, callback) {
    if (timerName === "case" && caseSearchTimer) window.clearTimeout(caseSearchTimer);
    if (timerName === "result" && resultSearchTimer) window.clearTimeout(resultSearchTimer);
    if (timerName === "import" && importSearchTimer) window.clearTimeout(importSearchTimer);
    if (timerName === "preparation" && preparationSearchTimer) window.clearTimeout(preparationSearchTimer);
    const timer = window.setTimeout(() => callback().catch(handleError), 250);
    if (timerName === "case") caseSearchTimer = timer;
    if (timerName === "result") resultSearchTimer = timer;
    if (timerName === "import") importSearchTimer = timer;
    if (timerName === "preparation") preparationSearchTimer = timer;
  }

  function setupActions() {
    const user = window.CURRENT_USER || {};
    document.getElementById("userLabel").textContent = user.email || "";
    if (user.role === "admin") document.getElementById("adminLink").classList.remove("hidden");
    document.getElementById("logoutButton").addEventListener("click", async () => {
      const response = await api("/api/logout", {method: "POST", body: "{}"});
      window.location.href = response.redirect || "/login";
    });
    document.querySelectorAll(".records-tab").forEach((button) => {
      button.addEventListener("click", () => switchView(button.dataset.libraryView).catch(handleError));
    });
    document.getElementById("refreshLibraryButton").addEventListener("click", refreshActiveView);
    nodes.caseSearch.addEventListener("input", () => debounce("case", () => loadCases()));
    nodes.caseAnalysis.addEventListener("change", () => loadCases().catch(handleError));
    document.getElementById("clearCaseFiltersButton").addEventListener("click", () => {
      nodes.caseSearch.value = "";
      nodes.caseAnalysis.value = "";
      loadCases().catch(handleError);
    });
    nodes.moreCases.addEventListener("click", () => loadCases(true).catch(handleError));
    nodes.resultSearch.addEventListener("input", () => debounce("result", () => loadResults()));
    nodes.resultStatus.addEventListener("change", () => loadResults().catch(handleError));
    nodes.resultModel.addEventListener("change", () => loadResults().catch(handleError));
    nodes.resultReview.addEventListener("change", () => loadResults().catch(handleError));
    nodes.resultRedFlags.addEventListener("change", () => loadResults().catch(handleError));
    nodes.resultAbstain.addEventListener("change", () => loadResults().catch(handleError));
    document.getElementById("clearResultFiltersButton").addEventListener("click", () => {
      nodes.resultSearch.value = "";
      nodes.resultStatus.value = "";
      nodes.resultModel.value = "";
      nodes.resultReview.value = "";
      nodes.resultRedFlags.value = "";
      nodes.resultAbstain.value = "";
      loadResults().catch(handleError);
    });
    nodes.moreResults.addEventListener("click", () => loadResults(true).catch(handleError));
    nodes.importSearch.addEventListener("input", () => debounce("import", () => loadImports()));
    nodes.importStatus.addEventListener("change", () => loadImports().catch(handleError));
    document.getElementById("clearImportFiltersButton").addEventListener("click", () => {
      nodes.importSearch.value = "";
      nodes.importStatus.value = "";
      loadImports().catch(handleError);
    });
    nodes.moreImports.addEventListener("click", () => loadImports(true).catch(handleError));
    nodes.preparationSearch.addEventListener("input", () => debounce("preparation", () => loadPreparations()));
    nodes.preparationStatus.addEventListener("change", () => loadPreparations().catch(handleError));
    document.getElementById("clearPreparationFiltersButton").addEventListener("click", () => {
      nodes.preparationSearch.value = "";
      nodes.preparationStatus.value = "";
      loadPreparations().catch(handleError);
    });
    nodes.morePreparations.addEventListener("click", () => loadPreparations(true).catch(handleError));
    nodes.caseResult.addEventListener("click", () => {
      if (state.latestResultId) window.open(`/reports/${state.latestResultId}`, "_blank", "noopener,noreferrer");
    });
    nodes.copyCase.addEventListener("click", async () => {
      if (!state.selectedCaseId) return;
      const response = await api(`/api/cases/${state.selectedCaseId}/copy`, {method: "POST", body: "{}"});
      await Promise.all([loadSummary(), loadCases()]);
      await selectCase(response.case_id);
      toast(`Создана копия кейса #${response.case_id}`);
    });
    nodes.fhirCase.addEventListener("click", () => {
      if (!state.selectedCaseId) return;
      const link = document.createElement("a");
      link.href = `/api/cases/${state.selectedCaseId}/fhir`;
      document.body.appendChild(link);
      link.click();
      link.remove();
    });
    nodes.deleteCase.addEventListener("click", async () => {
      if (!state.selectedCaseId || !state.selectedCase) return;
      if (!window.confirm(`Удалить кейс «${state.selectedCase.title}»? Результаты останутся в истории.`)) return;
      await api(`/api/cases/${state.selectedCaseId}/delete`, {method: "POST", body: "{}"});
      clearCaseDetail();
      await Promise.all([loadSummary(), loadCases()]);
      toast("Кейс удалён");
    });
  }

  async function initialize() {
    setupActions();
    const requestedView = new URLSearchParams(window.location.search).get("view");
    if (["cases", "results", "imports"].includes(requestedView)) {
      await switchView(requestedView);
    }
    await refreshActiveView();
  }

  initialize().catch(handleError);
})();
