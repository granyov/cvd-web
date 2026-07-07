(function () {
  "use strict";

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const usersTable = document.getElementById("usersTable");
  const requestsTable = document.getElementById("requestsTable");
  const auditTable = document.getElementById("auditTable");
  const qualityTable = document.getElementById("qualityTable");
  const qualitySummary = document.getElementById("qualitySummary");
  const goldSetTable = document.getElementById("goldSetTable");
  const goldSetSummary = document.getElementById("goldSetSummary");
  const goldSetForm = document.getElementById("goldSetForm");
  const goldRunsList = document.getElementById("goldRunsList");
  const reviewsTable = document.getElementById("reviewsTable");
  const statsNode = document.getElementById("stats");
  const settingsForm = document.getElementById("settingsForm");
  const modelHealthStatus = document.getElementById("modelHealthStatus");
  const backupsList = document.getElementById("backupsList");
  const backupStatus = document.getElementById("backupStatus");
  const dashboardMetrics = document.getElementById("dashboardMetrics");
  const modelQualityDashboard = document.getElementById("modelQualityDashboard");
  const modelQualityModels = document.getElementById("modelQualityModels");
  const modelQualityReviews = document.getElementById("modelQualityReviews");
  const modelComparisonList = document.getElementById("modelComparisonList");
  const goldCockpitSummary = document.getElementById("goldCockpitSummary");
  const goldCockpitList = document.getElementById("goldCockpitList");
  const activityChart = document.getElementById("activityChart");
  const systemHealthGrid = document.getElementById("systemHealthGrid");
  const dashboardUpdated = document.getElementById("dashboardUpdated");
  const batchCasesTable = document.getElementById("batchCasesTable");
  const batchJobs = document.getElementById("batchJobs");
  const batchSelectionStatus = document.getElementById("batchSelectionStatus");
  const modelSelect = document.getElementById("lmStudioModelSelect");
  const textStructuringModelSelect = document.getElementById("textStructuringModelSelect");
  const modelCatalogStatus = document.getElementById("modelCatalogStatus");
  const activateModelButton = document.getElementById("activateModelButton");
  const unloadPreviousModel = document.getElementById("unloadPreviousModel");
  const selectedBatchCases = new Set();
  let batchCases = [];
  let lastModelHealth = null;

  function panelStorageKey(panel) {
    return `cvd:${panel.dataset.collapsible}:open`;
  }

  function readPanelState(panel) {
    try {
      return localStorage.getItem(panelStorageKey(panel));
    } catch {
      return null;
    }
  }

  function writePanelState(panel, isOpen) {
    try {
      localStorage.setItem(panelStorageKey(panel), isOpen ? "1" : "0");
    } catch {
      // Collapsing still works if browser storage is unavailable.
    }
  }

  function setPanelOpen(panel, isOpen, {persist = true} = {}) {
    const toggle = panel.querySelector(".collapsible-toggle");
    const content = panel.querySelector(".collapsible-content");
    panel.classList.toggle("is-open", isOpen);
    if (toggle) toggle.setAttribute("aria-expanded", String(isOpen));
    if (content) content.hidden = !isOpen;
    if (persist) writePanelState(panel, isOpen);
  }

  function initCollapsiblePanels() {
    document.querySelectorAll("[data-collapsible]").forEach((panel) => {
      const saved = readPanelState(panel);
      setPanelOpen(panel, saved === "1", {persist: false});
      panel.querySelector(".collapsible-toggle")?.addEventListener("click", () => {
        setPanelOpen(panel, !panel.classList.contains("is-open"));
      });
    });
  }

  function updateCount(id, count, label = "записей") {
    const node = document.getElementById(id);
    if (node) node.textContent = `${Number(count || 0)} ${label}`;
  }

  initCollapsiblePanels();

  function applyAdminMode(mode) {
    const nextMode = ["admin", "researcher", "doctor"].includes(mode) ? mode : "admin";
    document.body.dataset.interfaceMode = nextMode;
    try { localStorage.setItem("cvd:admin-mode", nextMode); } catch (_) {}
    document.getElementById("adminModeSelect")?.querySelectorAll("option").forEach((option) => {
      option.selected = option.value === nextMode;
    });
  }

  function initAdminMode() {
    let mode = "admin";
    try { mode = localStorage.getItem("cvd:admin-mode") || "admin"; } catch (_) {}
    applyAdminMode(mode);
    document.getElementById("adminModeSelect")?.addEventListener("change", (event) => applyAdminMode(event.target.value));
  }

  initAdminMode();

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
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  function td(content) {
    const cell = document.createElement("td");
    if (content instanceof Node) {
      cell.appendChild(content);
    } else {
      cell.textContent = content ?? "";
    }
    return cell;
  }

  function pill(text, kind = "") {
    const node = document.createElement("span");
    node.className = `pill ${kind}`;
    node.textContent = text;
    return node;
  }

  async function loadStats() {
    const response = await api("/api/admin/stats");
    const stats = response.stats || {};
    statsNode.innerHTML = "";
    [
      ["Пользователи", stats.users],
      ["Активные", stats.active_users],
      ["Кейсы", stats.cases],
      ["Запросы", stats.model_requests],
      ["Ошибки модели", stats.model_errors],
      ["Модель", stats.lm_studio_model],
      ["API", stats.lm_studio_api_url]
    ].forEach(([label, value]) => {
      const node = pill(`${label}: ${value}`);
      if (label === "Ошибки модели" && value > 0) node.classList.add("warning");
      statsNode.appendChild(node);
    });
  }

  function number(value) {
    return new Intl.NumberFormat("ru-RU").format(Number(value || 0));
  }

  function duration(milliseconds) {
    const seconds = Math.round(Number(milliseconds || 0) / 1000);
    if (seconds < 60) return `${seconds} с`;
    const minutes = Math.floor(seconds / 60);
    return `${minutes} мин ${seconds % 60} с`;
  }

  function uptime(secondsValue) {
    const seconds = Number(secondsValue || 0);
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return [days ? `${days} д` : "", hours ? `${hours} ч` : "", `${minutes} мин`].filter(Boolean).join(" ");
  }

  function metricCard(label, value, detail, kind = "") {
    const card = document.createElement("div");
    card.className = `metric-card ${kind}`.trim();
    const labelNode = document.createElement("span");
    labelNode.className = "metric-label";
    labelNode.textContent = label;
    const valueNode = document.createElement("strong");
    valueNode.textContent = value;
    const detailNode = document.createElement("small");
    detailNode.textContent = detail;
    card.append(labelNode, valueNode, detailNode);
    return card;
  }

  function renderActivity(days) {
    activityChart.innerHTML = "";
    const maxRequests = Math.max(1, ...(days || []).map((item) => Number(item.requests || 0)));
    (days || []).forEach((item) => {
      const day = document.createElement("div");
      day.className = "activity-day";
      const barWrap = document.createElement("div");
      barWrap.className = "activity-bar-wrap";
      const bar = document.createElement("div");
      bar.className = `activity-bar ${Number(item.errors || 0) ? "has-errors" : ""}`.trim();
      bar.style.height = `${Math.max(4, Math.round(Number(item.requests || 0) * 100 / maxRequests))}%`;
      bar.title = `Запросы: ${item.requests || 0}, ошибки: ${item.errors || 0}`;
      const count = document.createElement("strong");
      count.textContent = String(item.requests || 0);
      const label = document.createElement("span");
      label.textContent = new Date(`${item.day}T00:00:00`).toLocaleDateString("ru-RU", {day: "2-digit", month: "2-digit"});
      barWrap.appendChild(bar);
      day.append(barWrap, count, label);
      activityChart.appendChild(day);
    });
  }

  function renderSystemHealth(dashboard) {
    const system = dashboard.system || {};
    const queue = dashboard.inference_queue || {};
    systemHealthGrid.innerHTML = "";
    const rows = [
      ["LM Studio", lastModelHealth?.ok ? `доступна · ${lastModelHealth.latency_ms} мс` : lastModelHealth ? "недоступна" : "не проверена", lastModelHealth?.ok ? "ok" : lastModelHealth ? "error" : "warning"],
      ["База данных", system.db_integrity === "ok" ? "integrity ok" : system.db_integrity || "нет данных", system.db_integrity === "ok" ? "ok" : "error"],
      ["Фоновый worker", system.worker_running ? "работает" : "остановлен", system.worker_running ? "ok" : "error"],
      ["Очередь LM Studio", `${number(queue.active_count)} активно · ${number(queue.queued_count)} ожидает · лимит ${number(queue.max_concurrent)}`, Number(queue.queued_count) > 0 ? "warning" : "ok"],
      ["Production queue", dashboard.production_queue?.backend ? `${dashboard.production_queue.active_backend} active · target ${dashboard.production_queue.backend}` : "нет данных", dashboard.production_queue?.external_requested ? "warning" : "ok"],
      ["Размер БД", `${(Number(system.db_size_bytes || 0) / 1024 / 1024).toFixed(2)} МБ`, ""],
      ["Время работы", uptime(system.uptime_seconds), ""],
      ["Версия", system.app_version || "", ""]
    ];
    rows.forEach(([label, value, kind]) => {
      const row = document.createElement("div");
      row.className = "health-row";
      const name = document.createElement("span");
      name.textContent = label;
      row.append(name, pill(value, kind));
      systemHealthGrid.appendChild(row);
    });
  }

  async function loadDashboard() {
    const dashboard = await api("/api/admin/dashboard");
    window.__dashboard = dashboard;
    const model = dashboard.model || {};
    const quality = dashboard.quality || {};
    const batch = dashboard.batch || {};
    const preparations = dashboard.preparations || {};
    const queue = dashboard.inference_queue || {};
    dashboardMetrics.innerHTML = "";
    [
      metricCard("Пользователи", number(dashboard.users?.active), `${number(dashboard.users?.total)} всего · ${number(dashboard.users?.active_24h)} входов за 24 ч`),
      metricCard("Кейсы", number(dashboard.cases?.total), `${number(dashboard.cases?.created_24h)} новых за 24 ч`),
      metricCard("Успешность модели", `${Number(model.success_rate_percent || 0).toFixed(1)}%`, `${number(model.success)} успешно · ${number(model.errors)} ошибок`, Number(model.errors) > 0 ? "warning" : ""),
      metricCard("Среднее время", duration(model.avg_duration_ms), `p95 ${duration(model.p95_duration_ms)}`),
      metricCard("Готовность данных", `${quality.avg_readiness_percent || 0}%`, `заполненность ${quality.avg_completeness_percent || 0}% · сигналов ${number(quality.signals)}`),
      metricCard("Скорость генерации", `${Number(model.avg_tokens_per_second || 0).toFixed(1)} tok/s`, `${number(model.total_tokens)} токенов всего`),
      metricCard("AI-подготовка", number(preparations.success), `${number(preparations.mapped_fields)} полей · ${number(preparations.errors)} ошибок`, Number(preparations.errors) > 0 ? "warning" : ""),
      metricCard("Пакетная очередь", number(batch.active_jobs), `${number(batch.success_items)} готово · ${number(batch.error_items)} ошибок`, Number(batch.error_items) > 0 ? "warning" : ""),
      metricCard("Очередь LM Studio", number(queue.queued_count), `${number(queue.active_count)} активно · среднее ожидание ${duration(queue.average_wait_ms)}`, Number(queue.queued_count) > 0 ? "warning" : "")
    ].forEach((card) => dashboardMetrics.appendChild(card));
    renderActivity(dashboard.daily || []);
    renderSystemHealth(dashboard);
    renderModelQualityDashboard(dashboard);
    dashboardUpdated.textContent = `обновлено ${new Date(dashboard.generated_at).toLocaleTimeString("ru-RU", {hour: "2-digit", minute: "2-digit", second: "2-digit"})}`;
  }

  async function loadModelQuality() {
    const quality = await api("/api/admin/model-quality");
    renderModelQualityDashboard(quality);
  }

  function renderModelQualityDashboard(quality) {
    if (!modelQualityDashboard) return;
    const summary = quality.summary || {};
    const reviews = quality.reviews || {};
    modelQualityDashboard.innerHTML = "";
    [
      metricCard("Моделей", number(summary.models), `${number(summary.multi_model_cases)} кейсов с несколькими моделями`),
      metricCard("Gold comparisons", number(summary.gold_comparisons), `${number(summary.gold_cases)} gold cases`),
      metricCard("Экспертные оценки", number(summary.reviews), `${Number(reviews.useful_rate_percent || 0).toFixed(1)}% useful`, Number(summary.unsafe_reviews || 0) ? "warning" : "ok"),
      metricCard("Unsafe", number(summary.unsafe_reviews), "ответов с экспертной оценкой unsafe", Number(summary.unsafe_reviews || 0) ? "error" : "ok")
    ].forEach((card) => modelQualityDashboard.appendChild(card));

    if (modelQualityModels) {
      modelQualityModels.innerHTML = "";
      const models = quality.models || [];
      if (!models.length) modelQualityModels.textContent = "Нет данных по моделям.";
      models.forEach((item) => {
        const row = document.createElement("div");
        row.className = "review-cockpit-item";
        const title = document.createElement("strong");
        title.textContent = item.model;
        const details = document.createElement("small");
        details.textContent = `${number(item.requests)} запросов · success ${Number(item.success_rate_percent || 0).toFixed(1)}% · gold ${item.gold_avg_score_percent || 0}% · useful ${Number(item.review_useful_rate_percent || 0).toFixed(1)}%`;
        const perf = document.createElement("small");
        perf.textContent = `latency ${duration(item.avg_duration_ms)} · p95 ${duration(item.p95_duration_ms)} · ${Number(item.avg_tokens_per_second || 0).toFixed(1)} tok/s`;
        row.append(title, details, perf, pill(`${item.reviews?.unsafe || 0} unsafe`, Number(item.reviews?.unsafe || 0) ? "error" : "ok"));
        modelQualityModels.appendChild(row);
      });
    }

    if (modelQualityReviews) {
      modelQualityReviews.innerHTML = "";
      const rating = document.createElement("div");
      rating.className = "review-cockpit-item";
      rating.append(
        document.createElement("strong"),
        pill(`useful ${reviews.useful || 0}`, "ok"),
        pill(`partial ${reviews.partial || 0}`, "warning"),
        pill(`wrong ${reviews.wrong || 0}`, "error"),
        pill(`unsafe ${reviews.unsafe || 0}`, Number(reviews.unsafe || 0) ? "error" : "ok")
      );
      rating.querySelector("strong").textContent = "Распределение оценок";
      modelQualityReviews.appendChild(rating);
      const issues = reviews.issue_counts || [];
      if (!issues.length) {
        const empty = document.createElement("div");
        empty.className = "review-cockpit-item";
        empty.textContent = "Типы ошибок пока не отмечались.";
        modelQualityReviews.appendChild(empty);
      }
      issues.slice(0, 6).forEach((issue) => {
        const row = document.createElement("div");
        row.className = "review-cockpit-item";
        const name = document.createElement("strong");
        name.textContent = issue.issue;
        row.append(name, pill(`${issue.count}×`, "warning"));
        modelQualityReviews.appendChild(row);
      });
    }

    if (modelComparisonList) {
      modelComparisonList.innerHTML = "";
      const comparisons = quality.comparisons || [];
      if (!comparisons.length) modelComparisonList.textContent = "Для сравнения нужны gold cases с успешными результатами моделей.";
      comparisons.slice(0, 10).forEach((item) => {
        const row = document.createElement("div");
        row.className = "review-cockpit-item";
        const title = document.createElement("strong");
        title.textContent = `#${item.case_id} · ${item.title}`;
        const details = document.createElement("small");
        details.textContent = `Лучше: ${item.best_model} · ${item.best_score_percent}%`;
        const models = document.createElement("small");
        models.textContent = (item.models || []).map((model) => `${model.model}: ${model.evaluation?.score_percent || 0}% (#${model.request_id})`).join(" · ");
        row.append(title, details, models);
        modelComparisonList.appendChild(row);
      });
    }
  }

  function renderGoldCockpit(goldCases, runs) {
    if (!goldCockpitSummary || !goldCockpitList) return;
    const latestRun = runs[0] || {};
    const evaluated = goldCases.filter((item) => item.evaluation?.status === "evaluated");
    const lowScore = evaluated.filter((item) => Number(item.evaluation?.score_percent || 0) < 80);
    goldCockpitSummary.innerHTML = "";
    [
      metricCard("Gold cases", number(goldCases.length), `${number(evaluated.length)} evaluated`),
      metricCard("Latest run", latestRun.id ? `#${latestRun.id}` : "—", latestRun.id ? `${latestRun.avg_score_percent || 0}% avg score` : "run not created", latestRun.id && Number(latestRun.avg_score_percent || 0) < 80 ? "warning" : ""),
      metricCard("Needs review", number(lowScore.length), "score below 80%", lowScore.length ? "warning" : "ok"),
      metricCard("Coverage", `${goldCases.length ? Math.round(evaluated.length * 100 / goldCases.length) : 0}%`, "evaluated gold cases")
    ].forEach((card) => goldCockpitSummary.appendChild(card));
    goldCockpitList.innerHTML = "";
    const items = [...lowScore, ...goldCases.filter((item) => item.evaluation?.status !== "evaluated")].slice(0, 6);
    if (!items.length) {
      goldCockpitList.textContent = "Критичных элементов для ревью нет.";
      return;
    }
    items.forEach((item) => {
      const row = document.createElement("div");
      row.className = "review-cockpit-item";
      const title = document.createElement("strong");
      title.textContent = `#${item.case_id} · ${item.title}`;
      const details = document.createElement("small");
      details.textContent = item.evaluation?.status === "evaluated"
        ? `score ${item.evaluation.score_percent}% · проверьте расхождения`
        : "нет успешного результата для оценки";
      const actions = document.createElement("div");
      actions.className = "toolbar";
      actions.appendChild(actionLink("Открыть кейс", `/app?case=${item.case_id}`));
      if (item.latest_request_id) actions.appendChild(actionLink("Отчёт", `/reports/${item.latest_request_id}`, true));
      row.append(title, details, actions);
      goldCockpitList.appendChild(row);
    });
  }

  function actionLink(label, href, primary = false) {
    const link = document.createElement("a");
    link.className = `button ${primary ? "primary-link" : ""}`.trim();
    link.href = href;
    if (href.startsWith("/reports/")) {
      link.target = "_blank";
      link.rel = "noopener";
    }
    link.textContent = label;
    return link;
  }

  function gatewayProfileHint(profile) {
    const hints = {
      local: "LM Studio и CVD на одной системе: http://127.0.0.1:1234/v1/chat/completions",
      wsl2: "CVD в WSL2, LM Studio на Windows host: используйте IP Windows host или mirrored networking, например http://172.x.x.1:1234/v1/chat/completions",
      lan: "CVD и LM Studio в одной LAN: http://IP-КОМПЬЮТЕРА-С-LM-STUDIO:1234/v1/chat/completions",
      cloudflared: "Cloudflared tunnel: https://your-tunnel.example.com/v1/chat/completions; при Cloudflare Access заполните auth headers."
    };
    return hints[profile] || hints.local;
  }

  function updateGatewayHint() {
    if (!aiGatewayHint || !aiGatewayProfile) return;
    aiGatewayHint.textContent = gatewayProfileHint(aiGatewayProfile.value);
  }

  async function testGateway() {
    testGatewayButton.disabled = true;
    modelCatalogStatus.textContent = "Проверка AI Gateway...";
    try {
      const response = await api("/api/admin/ai-gateway/test", {
        method: "POST",
        body: JSON.stringify({
          api_url: settingsForm.elements.lm_studio_api_url?.value || "",
          model: modelSelect.value || settingsForm.elements.lm_studio_model?.value || ""
        })
      });
      const gateway = response.gateway || {};
      const auth = gateway.auth_header_configured ? " · auth header настроен" : "";
      modelCatalogStatus.textContent = `${gateway.profile || "gateway"} · ${response.api_version || "?"} · моделей ${response.models_count || 0} · ${response.selected_state || "?"} · ${response.latency_ms} мс${auth}`;
      modelCatalogStatus.classList.toggle("error", !response.ok);
      if (!response.ok) toast(`AI Gateway доступен, но выбранная модель: ${response.selected_state || "не найдена"}`);
    } catch (err) {
      modelCatalogStatus.textContent = err.message;
      toast(err.message);
    } finally {
      testGatewayButton.disabled = false;
    }
  }

  async function loadModelHealth() {
    modelHealthStatus.textContent = "LM Studio: проверка...";
    modelHealthStatus.className = "pill warning";
    const response = await api("/api/admin/model-health");
    lastModelHealth = response;
    renderSystemHealth(window.__dashboard || {});
    if (response.ok) {
      const context = response.loaded_context_length ? ` · ctx ${response.loaded_context_length}` : "";
      const profile = response.gateway?.profile ? `${response.gateway.profile} · ` : "";
      const stats = response.request_stats || {};
      const recent = stats.last_error_at ? ` · last err ${stats.last_error_at}` : stats.last_success_at ? ` · last ok ${stats.last_success_at}` : "";
      modelHealthStatus.textContent = `AI Gateway: ${profile}loaded · ${response.latency_ms} мс${context}${recent}`;
      modelHealthStatus.className = "pill ok";
      return;
    }
    modelHealthStatus.textContent = `AI Gateway: ${response.selected_state || response.error || "недоступен"}`;
    modelHealthStatus.className = "pill error";
  }

  async function loadSettings() {
    const response = await api("/api/admin/settings");
    const values = {};
    (response.settings || []).forEach((item) => {
      values[item.key] = item.value;
    });
    Object.entries(values).forEach(([key, value]) => {
      if (settingsForm.elements[key]) {
        settingsForm.elements[key].value = value;
      }
    });
    window.APP_SETTINGS = { ...(window.APP_SETTINGS || {}), ...values };
    updateGatewayHint();
    return values;
  }

  function modelSize(bytes) {
    const size = Number(bytes || 0);
    if (!size) return "";
    return `${(size / 1024 / 1024 / 1024).toFixed(1)} GB`;
  }

  function modelOptionLabel(model) {
    const details = [model.params, model.quantization, modelSize(model.size_bytes)].filter(Boolean).join(" · ");
    const state = model.state === "loaded" ? "загружена" : "не загружена";
    return `${model.display_name || model.id}${details ? ` · ${details}` : ""} · ${state}`;
  }

  async function loadModels() {
    modelCatalogStatus.textContent = "Получение каталога LM Studio...";
    const response = await api("/api/admin/models");
    const configured = window.APP_SETTINGS?.lm_studio_model || response.selected_model || "";
    const configuredTextModel = window.APP_SETTINGS?.text_structuring_model || "";
    const models = (response.models || []).filter((model) => ["llm", "vlm"].includes(model.type));
    modelSelect.innerHTML = "";
    textStructuringModelSelect.innerHTML = "";
    const defaultTextOption = document.createElement("option");
    defaultTextOption.value = "";
    defaultTextOption.textContent = "Использовать основную модель";
    defaultTextOption.selected = !configuredTextModel;
    textStructuringModelSelect.appendChild(defaultTextOption);
    models.forEach((model) => {
      const option = document.createElement("option");
      option.value = model.id;
      option.textContent = modelOptionLabel(model);
      option.selected = model.id === configured;
      modelSelect.appendChild(option);
      const textOption = option.cloneNode(true);
      textOption.selected = model.id === configuredTextModel;
      textStructuringModelSelect.appendChild(textOption);
    });
    if (configured && !models.some((model) => model.id === configured)) {
      const option = document.createElement("option");
      option.value = configured;
      option.textContent = `${configured} · отсутствует в каталоге`;
      option.selected = true;
      modelSelect.prepend(option);
    }
    if (configuredTextModel && !models.some((model) => model.id === configuredTextModel)) {
      const option = document.createElement("option");
      option.value = configuredTextModel;
      option.textContent = `${configuredTextModel} · отсутствует в каталоге`;
      option.selected = true;
      textStructuringModelSelect.appendChild(option);
    }
    const loaded = models.filter((model) => model.state === "loaded").map((model) => model.display_name || model.id);
    modelCatalogStatus.textContent = `${response.api_version.toUpperCase()} · моделей ${models.length} · загружено: ${loaded.join(", ") || "нет"}`;
  }

  async function activateModel() {
    const model = modelSelect.value;
    if (!model) throw new Error("Выберите модель");
    activateModelButton.disabled = true;
    modelCatalogStatus.textContent = `Активация ${model}...`;
    try {
      const response = await api("/api/admin/models/activate", {
        method: "POST",
        body: JSON.stringify({
          model,
          unload_previous: unloadPreviousModel.checked
        })
      });
      window.APP_SETTINGS = { ...(window.APP_SETTINGS || {}), lm_studio_model: response.selected_model };
      toast(`Активна модель ${response.selected_model}`);
      await Promise.all([loadSettings(), loadModels(), loadModelHealth(), loadStats(), loadDashboard(), loadModelQuality()]);
    } finally {
      activateModelButton.disabled = false;
    }
  }

  async function saveSettings(event) {
    event.preventDefault();
    const settings = {};
    Array.from(settingsForm.elements).forEach((element) => {
      if (!element.name) return;
      settings[element.name] = element.value;
    });
    settings.lm_studio_model = window.APP_SETTINGS?.lm_studio_model || settings.lm_studio_model;
    await api("/api/admin/settings", {
      method: "POST",
      body: JSON.stringify({ settings })
    });
    window.APP_SETTINGS = { ...(window.APP_SETTINGS || {}), ...settings };
    toast("Настройки сохранены");
    await loadSettings();
    await Promise.all([loadStats(), loadModels()]);
  }

  async function loadUsers() {
    const response = await api("/api/admin/users");
    usersTable.innerHTML = "";
    (response.users || []).forEach((user) => usersTable.appendChild(renderUserRow(user)));
  }

  function renderUserRow(user) {
    const row = document.createElement("tr");

    const nameInput = document.createElement("input");
    nameInput.value = user.full_name || "";

    const roleSelect = document.createElement("select");
    ["user", "admin"].forEach((role) => {
      const option = document.createElement("option");
      option.value = role;
      option.textContent = role;
      option.selected = role === user.role;
      roleSelect.appendChild(option);
    });

    const activeInput = document.createElement("input");
    activeInput.type = "checkbox";
    activeInput.checked = Boolean(user.is_active);

    const actions = document.createElement("div");
    actions.className = "toolbar";
    const saveButton = document.createElement("button");
    saveButton.type = "button";
    saveButton.textContent = "Сохранить";
    saveButton.addEventListener("click", () => updateUser(user.id, nameInput.value, roleSelect.value, activeInput.checked).catch((err) => toast(err.message)));

    const passwordButton = document.createElement("button");
    passwordButton.type = "button";
    passwordButton.textContent = "Пароль";
    passwordButton.addEventListener("click", () => resetUserPassword(user.id, user.email).catch((err) => toast(err.message)));
    actions.append(saveButton, passwordButton);

    row.append(
      td(user.id),
      td(user.email),
      td(nameInput),
      td(roleSelect),
      td(activeInput),
      td(actions)
    );
    return row;
  }

  async function updateUser(userId, fullName, role, isActive) {
    await api(`/api/admin/users/${userId}/update`, {
      method: "POST",
      body: JSON.stringify({
        full_name: fullName,
        role,
        is_active: isActive
      })
    });
    toast("Пользователь обновлён");
    await Promise.all([loadUsers(), loadStats()]);
  }

  async function resetUserPassword(userId, email) {
    const password = window.prompt(`Новый временный пароль для ${email}, минимум 15 символов`);
    if (!password) return;
    await api(`/api/admin/users/${userId}/password`, {
      method: "POST",
      body: JSON.stringify({ password })
    });
    toast("Пароль сброшен");
  }

  async function createUser(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = {
      email: form.email.value,
      full_name: form.full_name.value,
      role: form.role.value,
      password: form.password.value
    };
    await api("/api/admin/users", {
      method: "POST",
      body: JSON.stringify(payload)
    });
    form.reset();
    toast("Пользователь создан");
    await Promise.all([loadUsers(), loadStats()]);
  }

  async function loadRequests() {
    const response = await api("/api/admin/requests?limit=200");
    const requests = response.requests || [];
    updateCount("requestsCount", requests.length);
    requestsTable.innerHTML = "";
    requests.forEach((request) => requestsTable.appendChild(renderRequestRow(request)));
  }

  function renderRequestRow(request) {
    const row = document.createElement("tr");
    const diagnosis = request.parsed_output?.CDS_OUTPUT?.summary || request.parsed_output?.MODEL_OUTPUT?.Final_model_diagnosis || request.error || "";
    const status = request.status === "success" ? pill("success", "ok") : pill("error", "error");
    const meta = [
      request.prompt_version,
      request.output_schema_version,
      request.completion_tokens ? `${request.completion_tokens} output tokens` : "",
      Number(request.tokens_per_second) > 0 ? `${Number(request.tokens_per_second).toFixed(1)} tok/s` : "",
      request.finish_reason ? `finish: ${request.finish_reason}` : "",
      request.request_source === "batch" ? "пакетная обработка" : "",
      (request.phi_signals || []).length ? `PHI: ${(request.phi_signals || []).length}` : ""
    ].filter(Boolean).join(" · ");
    const reviewText = request.review_count ? ` · оценок: ${request.review_count}` : "";
    row.append(
      td(request.id),
      td(request.email),
      td(status),
      td(request.model),
      td(`${request.created_at}\n${(Number(request.duration_ms || 0) / 1000).toFixed(1)} с`),
      td(`${diagnosis}${meta || reviewText ? `\n${meta}${reviewText}` : ""}`)
    );
    return row;
  }

  async function loadReviews() {
    const response = await api("/api/admin/reviews?limit=200");
    const reviews = response.reviews || [];
    updateCount("reviewsCount", reviews.length);
    reviewsTable.innerHTML = "";
    reviews.forEach((review) => reviewsTable.appendChild(renderReviewRow(review)));
  }

  function renderReviewRow(review) {
    const row = document.createElement("tr");
    const ratingKind = review.rating === "useful" ? "ok" : review.rating === "unsafe" ? "error" : "warning";
    row.append(
      td(review.id),
      td(`#${review.model_request_id}\n${review.model || ""}\n${review.prompt_version || ""}`),
      td(pill(review.rating, ratingKind)),
      td((review.issue_types || []).join(", ") || "нет"),
      td(review.comment || review.corrected_diagnosis || ""),
      td(`${review.reviewer_email}\n${review.updated_at}`)
    );
    return row;
  }

  async function loadQuality() {
    const response = await api("/api/admin/quality");
    const summary = response.summary || {};
    qualitySummary.innerHTML = "";
    [
      ["Кейсы", summary.cases],
      ["Средняя заполненность", `${summary.avg_completeness_percent || 0}%`],
      ["Средняя готовность", `${summary.avg_readiness_percent || 0}%`],
      ["Сигналы", summary.signals || 0]
    ].forEach(([label, value]) => {
      const node = pill(`${label}: ${value}`);
      if (label === "Сигналы" && Number(value) > 0) node.classList.add("warning");
      qualitySummary.appendChild(node);
    });
    const cases = response.cases || [];
    updateCount("qualityCount", cases.length, "кейсов");
    qualityTable.innerHTML = "";
    cases.forEach((item) => qualityTable.appendChild(renderQualityRow(item)));
  }

  function renderQualityRow(item) {
    const row = document.createElement("tr");
    const quality = item.quality || {};
    const missing = (quality.missing_required || []).map((entry) => entry.label).join(", ");
    const signals = (quality.signals || []).map((entry) => entry.title).join(", ");
    row.append(
      td(item.id),
      td(item.title),
      td(`${quality.completeness_percent || 0}%`),
      td(`${quality.readiness_percent || 0}%`),
      td(signals || "нет"),
      td(missing || "нет")
    );
    return row;
  }

  async function loadGoldSet() {
    const [response, runsResponse] = await Promise.all([
      api("/api/admin/gold-set"),
      api("/api/admin/gold-runs")
    ]);
    const summary = response.summary || {};
    goldSetSummary.innerHTML = "";
    [
      ["Эталонов", summary.gold_cases],
      ["Оценено", summary.evaluated],
      ["Средний score", `${summary.avg_score_percent || 0}%`],
      ["МКБ-10 hit", summary.icd10_hits || 0],
      ["Red flags match", summary.red_flag_matches || 0],
      ["Missing data match", summary.missing_data_matches || 0],
      ["Abstain match", summary.abstain_matches || 0]
    ].forEach(([label, value]) => {
      const node = pill(`${label}: ${value}`);
      if (label === "Средний score" && Number(summary.avg_score_percent || 0) < 80 && Number(summary.evaluated || 0) > 0) node.classList.add("warning");
      goldSetSummary.appendChild(node);
    });
    const goldCases = response.gold_cases || [];
    updateCount("goldSetCount", goldCases.length, "эталонов");
    goldSetTable.innerHTML = "";
    goldCases.forEach((item) => goldSetTable.appendChild(renderGoldSetRow(item)));
    const runs = runsResponse.runs || [];
    renderGoldRuns(runs);
    renderGoldCockpit(goldCases, runs);
  }

  function boolMark(value) {
    if (value === true) return "✓";
    if (value === false) return "×";
    return "—";
  }

  function renderGoldSetRow(item) {
    const row = document.createElement("tr");
    const evaluation = item.evaluation || {};
    const scoreKind = evaluation.status !== "evaluated" ? "warning" : Number(evaluation.score_percent || 0) >= 80 ? "ok" : "error";
    const expected = [
      item.expected_diagnosis ? `диагноз: ${item.expected_diagnosis}` : "",
      (item.expected_icd10 || []).length ? `МКБ-10: ${(item.expected_icd10 || []).join(", ")}` : "",
      (item.expected_red_flags || []).length ? `red flags: ${(item.expected_red_flags || []).join("; ")}` : "red flags: нет",
      (item.expected_missing_data || []).length ? `missing data: ${(item.expected_missing_data || []).join("; ")}` : "",
      `abstain: ${item.expected_abstain ? "да" : "нет"}`,
      `severity: ${item.severity || "medium"}`
    ].filter(Boolean).join("\n");
    const result = item.latest_request_id
      ? `#${item.latest_request_id} · ${item.latest_model || ""}\n${item.latest_prompt_version || ""}\n${item.latest_request_created_at || ""}`
      : "нет успешного результата";
    const score = evaluation.status === "evaluated"
      ? `${evaluation.score_percent}%\nМКБ-10 ${boolMark(evaluation.icd10_match)} · red flags ${boolMark(evaluation.red_flags_match)} · missing data ${boolMark(evaluation.missing_data_match)} · abstain ${boolMark(evaluation.abstain_match)} · диагноз ${boolMark(evaluation.diagnosis_match)}`
      : "ожидает успешного результата";
    row.append(
      td(item.id),
      td(`#${item.case_id} · ${item.title}\n${item.patient_id || "ID не указан"}`),
      td(expected),
      td(result),
      td(pill(score, scoreKind))
    );
    return row;
  }

  async function saveGoldCase(event) {
    event.preventDefault();
    const form = event.currentTarget;
    await api("/api/admin/gold-set", {
      method: "POST",
      body: JSON.stringify({
        case_id: form.case_id.value,
        expected_diagnosis: form.expected_diagnosis.value,
        expected_icd10: form.expected_icd10.value,
        expected_red_flags: form.expected_red_flags.value,
        expected_missing_data: form.expected_missing_data.value,
        expected_abstain: form.expected_abstain.value === "1",
        severity: form.severity.value,
        notes: form.notes.value
      })
    });
    form.reset();
    toast("Эталон Gold Set сохранён");
    await Promise.all([loadGoldSet(), loadAudit()]);
  }

  async function startGoldRun() {
    const button = document.getElementById("startGoldRunButton");
    button.disabled = true;
    try {
      const response = await api("/api/admin/gold-runs", {method: "POST", body: "{}"});
      const summary = response.summary || {};
      toast(`Validation run #${response.run_id}: оценено ${summary.evaluated_items || 0}/${summary.total_items || 0}`);
      await Promise.all([loadGoldSet(), loadAudit()]);
    } finally {
      button.disabled = false;
    }
  }

  function renderGoldRuns(runs) {
    goldRunsList.innerHTML = "";
    if (!runs.length) {
      goldRunsList.textContent = "Validation runs пока не создавались.";
      return;
    }
    runs.forEach((run) => {
      const node = document.createElement("div");
      node.className = "batch-job";
      const identity = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = `Validation run #${run.id}`;
      const snapshot = run.settings_snapshot || {};
      const meta = document.createElement("small");
      meta.textContent = `${run.created_by_email || "system"} · ${run.created_at} · ${snapshot.lm_studio_model || "модель не указана"} · ${snapshot.active_prompt_version || ""}`;
      identity.append(title, meta, pill(run.status === "completed" ? "завершён" : "пустой", run.status === "completed" ? "ok" : "warning"));

      const progress = document.createElement("div");
      const progressText = document.createElement("small");
      progressText.textContent = `${run.evaluated_items || 0} из ${run.total_items || 0} · средний score ${run.avg_score_percent || 0}%`;
      const track = document.createElement("div");
      track.className = "progress-track";
      const fill = document.createElement("div");
      fill.className = "progress-fill";
      fill.style.width = `${Math.max(0, Math.min(100, Number(run.avg_score_percent || 0)))}%`;
      track.appendChild(fill);
      progress.append(progressText, track);

      const worst = (run.items || []).slice(0, 3).map((item) => `#${item.case_id}: ${item.score_percent}%`).join(" · ");
      const details = document.createElement("small");
      details.textContent = worst ? `Слабые места: ${worst}` : "Нет элементов для отображения.";
      node.append(identity, progress, details);
      goldRunsList.appendChild(node);
    });
  }

  async function loadAudit() {
    const response = await api("/api/admin/audit?limit=200");
    const audit = response.audit || [];
    updateCount("auditCount", audit.length);
    auditTable.innerHTML = "";
    audit.forEach((entry) => auditTable.appendChild(renderAuditRow(entry)));
  }

  function bytesText(bytes) {
    const value = Number(bytes || 0);
    if (value > 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
    if (value > 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${value} B`;
  }

  async function loadBackups() {
    if (!backupsList) return;
    const response = await api("/api/admin/backups");
    const backups = response.backups || [];
    backupsList.innerHTML = "";
    if (!backups.length) {
      backupsList.textContent = "Backup пока не создавались.";
      return;
    }
    backups.forEach((backup) => {
      const row = document.createElement("div");
      row.className = "batch-job";
      const title = document.createElement("strong");
      title.textContent = backup.filename;
      const meta = document.createElement("small");
      meta.textContent = `${backup.created_at} · ${bytesText(backup.size_bytes)}`;
      const actions = document.createElement("div");
      actions.className = "toolbar";
      const download = actionLink("Скачать", `/api/admin/backups/${encodeURIComponent(backup.filename)}`, true);
      const restore = document.createElement("button");
      restore.type = "button";
      restore.textContent = "Restore";
      restore.addEventListener("click", () => restoreBackup(backup.filename).catch((err) => toast(err.message)));
      actions.append(download, restore);
      row.append(title, meta, actions);
      backupsList.appendChild(row);
    });
  }

  async function createBackup() {
    const button = document.getElementById("createBackupButton");
    button.disabled = true;
    try {
      const response = await api("/api/admin/backups", {method: "POST", body: "{}"});
      backupStatus.textContent = `Backup создан: ${response.backup?.filename || "ok"}`;
      toast("Backup создан");
      await Promise.all([loadBackups(), loadAudit()]);
    } finally {
      button.disabled = false;
    }
  }

  async function restoreBackup(filename) {
    if (!window.confirm(`Восстановить базу из ${filename}? Текущая база будет сохранена safety backup.`)) return;
    const response = await api("/api/admin/restore", {method: "POST", body: JSON.stringify({filename})});
    backupStatus.textContent = `Restore выполнен из ${response.restored_from}; safety backup: ${response.safety_backup}`;
    toast("База восстановлена из backup");
    await Promise.all([loadBackups(), loadDashboard(), loadStats(), loadAudit()]);
  }

  function renderAuditRow(entry) {
    const row = document.createElement("tr");
    const target = [entry.target_type, entry.target_id].filter(Boolean).join(" #");
    row.append(
      td(entry.id),
      td(entry.email || "system"),
      td(entry.action),
      td(target),
      td(entry.created_at),
      td(JSON.stringify(entry.details || {}))
    );
    return row;
  }

  function updateBatchSelection() {
    batchSelectionStatus.textContent = `выбрано: ${selectedBatchCases.size}`;
    document.getElementById("startBatchButton").disabled = selectedBatchCases.size === 0;
  }

  function renderBatchCases() {
    batchCasesTable.innerHTML = "";
    batchCases.forEach((item) => {
      const row = document.createElement("tr");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = selectedBatchCases.has(item.id);
      checkbox.disabled = Number(item.active_job_count || 0) > 0;
      checkbox.setAttribute("aria-label", `Выбрать кейс ${item.title}`);
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) selectedBatchCases.add(item.id);
        else selectedBatchCases.delete(item.id);
        updateBatchSelection();
      });
      const requestText = Number(item.active_job_count || 0) > 0
        ? "уже в активной очереди"
        : item.request_count
        ? `${item.request_count} · успешно ${item.success_count || 0}`
        : "не обрабатывался";
      row.append(
        td(checkbox),
        td(`#${item.id} · ${item.title}`),
        td(item.email),
        td(requestText),
        td(item.updated_at)
      );
      batchCasesTable.appendChild(row);
    });
    updateBatchSelection();
  }

  function batchStatus(status) {
    const labels = {
      queued: "в очереди",
      running: "выполняется",
      completed: "завершено",
      partial: "частично",
      failed: "ошибка",
      cancelled: "отменено"
    };
    const kind = status === "completed" ? "ok" : status === "failed" ? "error" : ["partial", "cancelled"].includes(status) ? "warning" : "";
    return pill(labels[status] || status, kind);
  }

  function renderBatchJobs(items) {
    batchJobs.innerHTML = "";
    if (!items.length) {
      batchJobs.textContent = "Пакетных заданий пока нет.";
      return;
    }
    items.forEach((job) => {
      const node = document.createElement("div");
      node.className = "batch-job";
      const identity = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = `Задание #${job.id}`;
      const meta = document.createElement("small");
      meta.textContent = `${job.created_by_email || "system"} · ${job.created_at}`;
      identity.append(title, meta, batchStatus(job.status));

      const progress = document.createElement("div");
      const jobProgress = job.progress || {};
      const progressText = document.createElement("small");
      const eta = Number(jobProgress.eta_seconds || 0) ? ` · осталось ${duration(Number(jobProgress.eta_seconds || 0) * 1000)}` : "";
      const speed = Number(jobProgress.throughput_per_hour || 0) ? ` · ${Number(jobProgress.throughput_per_hour).toFixed(1)} кейсов/ч` : "";
      progressText.textContent = `${job.completed_items || 0} из ${job.total_items || 0} · успешно ${job.success_items || 0} · ошибок ${job.error_items || 0}${eta}${speed}`;
      const track = document.createElement("div");
      track.className = "progress-track";
      const fill = document.createElement("div");
      fill.className = "progress-fill";
      fill.style.width = `${jobProgress.progress_percent ?? (job.total_items ? Math.round(Number(job.completed_items || 0) * 100 / Number(job.total_items)) : 0)}%`;
      track.appendChild(fill);
      progress.append(progressText, track);

      const action = document.createElement("div");
      if (["queued", "running"].includes(job.status)) {
        const cancel = document.createElement("button");
        cancel.type = "button";
        cancel.textContent = "Отменить";
        cancel.addEventListener("click", () => cancelBatchJob(job.id).catch((err) => toast(err.message)));
        action.appendChild(cancel);
      }
      node.append(identity, progress, action);
      batchJobs.appendChild(node);
    });
  }

  async function loadBatch() {
    const [casesResponse, jobsResponse] = await Promise.all([
      api("/api/admin/batch/cases"),
      api("/api/admin/batch/jobs")
    ]);
    batchCases = casesResponse.cases || [];
    const existingIds = new Set(batchCases.map((item) => item.id));
    Array.from(selectedBatchCases).forEach((id) => {
      if (!existingIds.has(id)) selectedBatchCases.delete(id);
    });
    renderBatchCases();
    renderBatchJobs(jobsResponse.jobs || []);
  }

  function selectUnprocessedCases() {
    selectedBatchCases.clear();
    batchCases.forEach((item) => {
      if (!Number(item.success_count || 0) && !Number(item.active_job_count || 0)) selectedBatchCases.add(item.id);
    });
    renderBatchCases();
  }

  async function startBatch() {
    const caseIds = Array.from(selectedBatchCases);
    if (!caseIds.length) return;
    const button = document.getElementById("startBatchButton");
    button.disabled = true;
    try {
      const response = await api("/api/admin/batch/jobs", {
        method: "POST",
        body: JSON.stringify({case_ids: caseIds})
      });
      selectedBatchCases.clear();
      toast(`Задание #${response.job_id} поставлено в очередь`);
      await Promise.all([loadBatch(), loadDashboard()]);
    } finally {
      updateBatchSelection();
    }
  }

  async function cancelBatchJob(jobId) {
    await api(`/api/admin/batch/jobs/${jobId}/cancel`, {method: "POST", body: "{}"});
    toast(`Задание #${jobId} отменено`);
    await Promise.all([loadBatch(), loadDashboard()]);
  }

  async function logout() {
    const response = await api("/api/logout", { method: "POST", body: "{}" });
    window.location.href = response.redirect || "/login";
  }

  document.getElementById("createUserForm").addEventListener("submit", (event) => {
    createUser(event).catch((err) => toast(err.message));
  });
  settingsForm.addEventListener("submit", (event) => {
    saveSettings(event).catch((err) => toast(err.message));
  });
  document.getElementById("refreshSettingsButton").addEventListener("click", () => loadSettings().then(loadModels).catch((err) => toast(err.message)));
  document.getElementById("testModelButton").addEventListener("click", () => loadModelHealth().catch((err) => toast(err.message)));
  document.getElementById("refreshModelsButton").addEventListener("click", () => loadModels().catch((err) => {
    modelCatalogStatus.textContent = err.message;
    toast(err.message);
  }));
  activateModelButton.addEventListener("click", () => activateModel().catch((err) => {
    modelCatalogStatus.textContent = err.message;
    toast(err.message);
  }));
  document.getElementById("refreshUsersButton").addEventListener("click", () => loadUsers().catch((err) => toast(err.message)));
  document.getElementById("refreshRequestsButton").addEventListener("click", () => loadRequests().catch((err) => toast(err.message)));
  document.getElementById("refreshQualityButton").addEventListener("click", () => loadQuality().catch((err) => toast(err.message)));
  document.getElementById("refreshGoldSetButton").addEventListener("click", () => loadGoldSet().catch((err) => toast(err.message)));
  goldSetForm.addEventListener("submit", (event) => saveGoldCase(event).catch((err) => toast(err.message)));
  document.getElementById("startGoldRunButton").addEventListener("click", () => startGoldRun().catch((err) => toast(err.message)));
  document.getElementById("refreshAuditButton").addEventListener("click", () => loadAudit().catch((err) => toast(err.message)));
  document.getElementById("refreshReviewsButton").addEventListener("click", () => loadReviews().catch((err) => toast(err.message)));
  document.getElementById("refreshDashboardButton").addEventListener("click", () => Promise.all([loadDashboard(), loadModelHealth()]).catch((err) => toast(err.message)));
  document.getElementById("refreshModelQualityButton")?.addEventListener("click", () => loadModelQuality().catch((err) => toast(err.message)));
  document.getElementById("refreshGoldCockpitButton")?.addEventListener("click", () => loadGoldSet().catch((err) => toast(err.message)));
  document.getElementById("refreshBatchButton").addEventListener("click", () => loadBatch().catch((err) => toast(err.message)));
  document.getElementById("selectUnprocessedButton").addEventListener("click", selectUnprocessedCases);
  document.getElementById("clearBatchSelectionButton").addEventListener("click", () => {
    selectedBatchCases.clear();
    renderBatchCases();
  });
  document.getElementById("startBatchButton").addEventListener("click", () => startBatch().catch((err) => toast(err.message)));
  document.getElementById("logoutButton").addEventListener("click", () => logout().catch((err) => toast(err.message)));

  const settingsAndModels = loadSettings().then(loadModels);
  Promise.all([loadStats(), loadDashboard(), loadModelQuality(), loadModelHealth(), loadBatch(), loadBackups(), settingsAndModels, loadUsers(), loadRequests(), loadQuality(), loadGoldSet(), loadAudit(), loadReviews()]).catch((err) => toast(err.message));
  window.setInterval(() => Promise.all([loadDashboard(), loadBatch()]).catch(() => {}), 10000);
})();
