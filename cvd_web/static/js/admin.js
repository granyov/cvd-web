(function () {
  "use strict";

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const usersTable = document.getElementById("usersTable");
  const requestsTable = document.getElementById("requestsTable");
  const auditTable = document.getElementById("auditTable");
  const qualityTable = document.getElementById("qualityTable");
  const qualitySummary = document.getElementById("qualitySummary");
  const reviewsTable = document.getElementById("reviewsTable");
  const statsNode = document.getElementById("stats");
  const settingsForm = document.getElementById("settingsForm");
  const modelHealthStatus = document.getElementById("modelHealthStatus");
  const dashboardMetrics = document.getElementById("dashboardMetrics");
  const activityChart = document.getElementById("activityChart");
  const systemHealthGrid = document.getElementById("systemHealthGrid");
  const dashboardUpdated = document.getElementById("dashboardUpdated");
  const batchCasesTable = document.getElementById("batchCasesTable");
  const batchJobs = document.getElementById("batchJobs");
  const batchSelectionStatus = document.getElementById("batchSelectionStatus");
  const selectedBatchCases = new Set();
  let batchCases = [];
  let lastModelHealth = null;

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
    systemHealthGrid.innerHTML = "";
    const rows = [
      ["LM Studio", lastModelHealth?.ok ? `доступна · ${lastModelHealth.latency_ms} мс` : lastModelHealth ? "недоступна" : "не проверена", lastModelHealth?.ok ? "ok" : lastModelHealth ? "error" : "warning"],
      ["База данных", system.db_integrity === "ok" ? "integrity ok" : system.db_integrity || "нет данных", system.db_integrity === "ok" ? "ok" : "error"],
      ["Фоновый worker", system.worker_running ? "работает" : "остановлен", system.worker_running ? "ok" : "error"],
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
    dashboardMetrics.innerHTML = "";
    [
      metricCard("Пользователи", number(dashboard.users?.active), `${number(dashboard.users?.total)} всего · ${number(dashboard.users?.active_24h)} входов за 24 ч`),
      metricCard("Кейсы", number(dashboard.cases?.total), `${number(dashboard.cases?.created_24h)} новых за 24 ч`),
      metricCard("Успешность модели", `${Number(model.success_rate_percent || 0).toFixed(1)}%`, `${number(model.success)} успешно · ${number(model.errors)} ошибок`, Number(model.errors) > 0 ? "warning" : ""),
      metricCard("Среднее время", duration(model.avg_duration_ms), `p95 ${duration(model.p95_duration_ms)}`),
      metricCard("Готовность данных", `${quality.avg_readiness_percent || 0}%`, `заполненность ${quality.avg_completeness_percent || 0}% · сигналов ${number(quality.signals)}`),
      metricCard("Скорость генерации", `${Number(model.avg_tokens_per_second || 0).toFixed(1)} tok/s`, `${number(model.total_tokens)} токенов всего`),
      metricCard("AI-подготовка", number(preparations.success), `${number(preparations.mapped_fields)} полей · ${number(preparations.errors)} ошибок`, Number(preparations.errors) > 0 ? "warning" : ""),
      metricCard("Пакетная очередь", number(batch.active_jobs), `${number(batch.success_items)} готово · ${number(batch.error_items)} ошибок`, Number(batch.error_items) > 0 ? "warning" : "")
    ].forEach((card) => dashboardMetrics.appendChild(card));
    renderActivity(dashboard.daily || []);
    renderSystemHealth(dashboard);
    dashboardUpdated.textContent = `обновлено ${new Date(dashboard.generated_at).toLocaleTimeString("ru-RU", {hour: "2-digit", minute: "2-digit", second: "2-digit"})}`;
  }

  async function loadModelHealth() {
    modelHealthStatus.textContent = "LM Studio: проверка...";
    modelHealthStatus.className = "pill warning";
    const response = await api("/api/admin/model-health");
    lastModelHealth = response;
    renderSystemHealth(window.__dashboard || {});
    if (response.ok) {
      const context = response.loaded_context_length ? ` · ctx ${response.loaded_context_length}` : "";
      modelHealthStatus.textContent = `LM Studio: loaded · ${response.latency_ms} мс${context}`;
      modelHealthStatus.className = "pill ok";
      return;
    }
    modelHealthStatus.textContent = `LM Studio: ${response.selected_state || response.error || "недоступен"}`;
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
  }

  async function saveSettings(event) {
    event.preventDefault();
    const settings = {};
    Array.from(settingsForm.elements).forEach((element) => {
      if (!element.name) return;
      settings[element.name] = element.value;
    });
    await api("/api/admin/settings", {
      method: "POST",
      body: JSON.stringify({ settings })
    });
    window.APP_SETTINGS = { ...(window.APP_SETTINGS || {}), ...settings };
    toast("Настройки сохранены");
    await Promise.all([loadStats(), loadSettings()]);
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
    requestsTable.innerHTML = "";
    (response.requests || []).forEach((request) => requestsTable.appendChild(renderRequestRow(request)));
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
    reviewsTable.innerHTML = "";
    (response.reviews || []).forEach((review) => reviewsTable.appendChild(renderReviewRow(review)));
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
    qualityTable.innerHTML = "";
    (response.cases || []).forEach((item) => qualityTable.appendChild(renderQualityRow(item)));
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

  async function loadAudit() {
    const response = await api("/api/admin/audit?limit=200");
    auditTable.innerHTML = "";
    (response.audit || []).forEach((entry) => auditTable.appendChild(renderAuditRow(entry)));
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
      const progressText = document.createElement("small");
      progressText.textContent = `${job.completed_items || 0} из ${job.total_items || 0} · успешно ${job.success_items || 0} · ошибок ${job.error_items || 0}`;
      const track = document.createElement("div");
      track.className = "progress-track";
      const fill = document.createElement("div");
      fill.className = "progress-fill";
      fill.style.width = `${job.total_items ? Math.round(Number(job.completed_items || 0) * 100 / Number(job.total_items)) : 0}%`;
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
  document.getElementById("refreshSettingsButton").addEventListener("click", () => loadSettings().catch((err) => toast(err.message)));
  document.getElementById("testModelButton").addEventListener("click", () => loadModelHealth().catch((err) => toast(err.message)));
  document.getElementById("refreshUsersButton").addEventListener("click", () => loadUsers().catch((err) => toast(err.message)));
  document.getElementById("refreshRequestsButton").addEventListener("click", () => loadRequests().catch((err) => toast(err.message)));
  document.getElementById("refreshQualityButton").addEventListener("click", () => loadQuality().catch((err) => toast(err.message)));
  document.getElementById("refreshAuditButton").addEventListener("click", () => loadAudit().catch((err) => toast(err.message)));
  document.getElementById("refreshReviewsButton").addEventListener("click", () => loadReviews().catch((err) => toast(err.message)));
  document.getElementById("refreshDashboardButton").addEventListener("click", () => Promise.all([loadDashboard(), loadModelHealth()]).catch((err) => toast(err.message)));
  document.getElementById("refreshBatchButton").addEventListener("click", () => loadBatch().catch((err) => toast(err.message)));
  document.getElementById("selectUnprocessedButton").addEventListener("click", selectUnprocessedCases);
  document.getElementById("clearBatchSelectionButton").addEventListener("click", () => {
    selectedBatchCases.clear();
    renderBatchCases();
  });
  document.getElementById("startBatchButton").addEventListener("click", () => startBatch().catch((err) => toast(err.message)));
  document.getElementById("logoutButton").addEventListener("click", () => logout().catch((err) => toast(err.message)));

  Promise.all([loadStats(), loadDashboard(), loadModelHealth(), loadBatch(), loadSettings(), loadUsers(), loadRequests(), loadQuality(), loadAudit(), loadReviews()]).catch((err) => toast(err.message));
  window.setInterval(() => Promise.all([loadDashboard(), loadBatch()]).catch(() => {}), 10000);
})();
