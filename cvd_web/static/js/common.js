(function () {
  "use strict";

  // Общие элементы интерфейса для рабочего места, архива и админки: тосты, диалоги,
  // человеческие тексты ошибок, форматирование времени и режим технических данных.

  const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");

  function shortcut(key, {alt = false} = {}) {
    if (alt) return isMac ? `⌥${key}` : `Alt+${key}`;
    return isMac ? `⌘${key}` : `Ctrl+${key}`;
  }

  function pluralize(value, forms) {
    const n = Math.abs(Number(value)) % 100;
    const last = n % 10;
    if (n > 10 && n < 20) return forms[2];
    if (last > 1 && last < 5) return forms[1];
    if (last === 1) return forms[0];
    return forms[2];
  }

  function countText(value, forms) {
    return `${value} ${pluralize(value, forms)}`;
  }

  function ageText(age) {
    const value = Number(age);
    if (String(age ?? "").trim() === "" || !Number.isFinite(value)) return "";
    return countText(value, ["год", "года", "лет"]);
  }

  const sexNouns = {male: "Мужчина", female: "Женщина", other: "Пол: иное", unknown: "Пол не указан"};

  // «Мужчина, 62 года» вместо «62 лет · male»: сырое значение select и несклоняемое «лет» видно врачу.
  function demographicsText(age, sex) {
    const parts = [];
    const sexValue = String(sex ?? "").trim();
    if (sexValue) parts.push(sexNouns[sexValue] || sexValue);
    const years = ageText(age);
    if (years) parts.push(years);
    return parts.join(", ");
  }

  const dateTimeFormat = new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit"
  });
  const timeFormat = new Intl.DateTimeFormat("ru-RU", {hour: "2-digit", minute: "2-digit"});
  const dayMonthFormat = new Intl.DateTimeFormat("ru-RU", {day: "numeric", month: "short"});

  function parseDate(value) {
    const date = value instanceof Date ? value : new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function formatDateTime(value) {
    const date = parseDate(value);
    return date ? dateTimeFormat.format(date) : String(value || "");
  }

  function relativeTime(value, now = new Date()) {
    const date = parseDate(value);
    if (!date) return String(value || "");
    const seconds = (now.getTime() - date.getTime()) / 1000;
    if (seconds < -60) return formatDateTime(date);
    if (seconds < 45) return "только что";
    if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} мин назад`;
    const sameDay = date.toDateString() === now.toDateString();
    if (sameDay) return `${Math.floor(seconds / 3600)} ч назад`;
    const yesterday = new Date(now);
    yesterday.setDate(now.getDate() - 1);
    if (date.toDateString() === yesterday.toDateString()) return `вчера, ${timeFormat.format(date)}`;
    if (date.getFullYear() === now.getFullYear()) return `${dayMonthFormat.format(date).replace(".", "")}, ${timeFormat.format(date)}`;
    return formatDateTime(date).split(",")[0];
  }

  // Относительное время читается быстрее, точное остаётся в подсказке.
  function timeElement(value) {
    const node = document.createElement("time");
    const date = parseDate(value);
    node.textContent = relativeTime(value);
    if (date) {
      node.dateTime = date.toISOString();
      node.title = formatDateTime(date);
    }
    return node;
  }

  const technicalReasons = [
    [/connection refused|errno 111|econnrefused|errno 61/i, "сервис не отвечает — соединение отклонено"],
    [/timed out|timeout|errno 110|errno 60/i, "сервис не ответил вовремя"],
    [/name or service not known|nodename nor servname|getaddrinfo|errno -[23]|errno 8\b/i, "адрес сервиса не найден"],
    [/certificate|ssl/i, "ошибка защищённого соединения: проверьте сертификат"],
    [/http error 40[13]|forbidden|unauthorized/i, "доступ запрещён — проверьте ключ или заголовки доступа"],
    [/http error 404|not found/i, "адрес сервиса указан неверно"],
    [/http error 5\d\d|bad gateway|service unavailable|gateway time-?out/i, "сервис вернул ошибку сервера"],
    [/connection reset|broken pipe|remote end closed/i, "соединение прервалось"]
  ];

  // Серверные ошибки иногда приходят с текстом исключения Python («<urlopen error [Errno 111] …>»).
  // Пользователю нужен смысл и что делать, а не стек вызовов.
  function humanizeError(raw) {
    const text = String(raw?.message ?? raw ?? "").trim();
    if (!text) return "Неизвестная ошибка";
    if (/failed to fetch|networkerror when attempting|load failed|network request failed/i.test(text)) {
      return "Нет связи с сервером CVD Web. Проверьте подключение и повторите.";
    }
    if (!/<urlopen error|\[errno|traceback|urllib|socket\.|errno \d+/i.test(text)) return text;
    const reason = (technicalReasons.find(([pattern]) => pattern.test(text)) || [null, "не удалось установить соединение"])[1];
    const prefix = text.split(/:\s*[<[(]/)[0].replace(/[.:\s]+$/, "");
    const aboutModel = /lm studio|модел|ai gateway|cvd engine/i.test(prefix);
    const hint = aboutModel ? " Проверьте, что LM Studio запущена и адрес AI Gateway в настройках верный." : " Повторите попытку позже.";
    if (window.console?.debug) window.console.debug("CVD Web technical error:", text);
    return `${prefix && prefix !== text ? `${prefix}: ` : ""}${reason}.${hint}`;
  }

  let activeToast = null;

  function toast(message, {actionLabel = "", onAction = null, duration = 3200} = {}) {
    activeToast?.dismiss();
    const node = document.createElement("div");
    node.className = "toast";
    node.setAttribute("role", "status");
    node.setAttribute("aria-live", "polite");
    const text = document.createElement("span");
    text.textContent = humanizeError(message);
    node.appendChild(text);
    let timer = null;
    const handle = {
      dismiss() {
        window.clearTimeout(timer);
        node.remove();
        if (activeToast === handle) activeToast = null;
      }
    };
    if (actionLabel && onAction) {
      const action = document.createElement("button");
      action.type = "button";
      action.className = "toast-action";
      action.textContent = actionLabel;
      action.addEventListener("click", () => {
        handle.dismiss();
        onAction();
      });
      node.appendChild(action);
    }
    document.body.appendChild(node);
    timer = window.setTimeout(() => handle.dismiss(), duration);
    activeToast = handle;
    return handle;
  }

  // Диалоги-листы вместо window.confirm/prompt: системные окна выбиваются из интерфейса,
  // не умеют разметку и в некоторых браузерах блокируются.
  function openDialog({title, message = "", input = null, confirmLabel = "OK", cancelLabel = "Отмена", destructive = false}) {
    return new Promise((resolve) => {
      const previousFocus = document.activeElement;
      const overlay = document.createElement("div");
      overlay.className = "modal ui-dialog";
      overlay.setAttribute("role", "dialog");
      overlay.setAttribute("aria-modal", "true");
      const card = document.createElement("div");
      card.className = "modal-card dialog-card";
      const body = document.createElement("div");
      body.className = "dialog-body";
      const heading = document.createElement("h2");
      heading.id = `dialog-title-${Date.now()}`;
      heading.textContent = title;
      overlay.setAttribute("aria-labelledby", heading.id);
      body.appendChild(heading);
      if (message) {
        const text = document.createElement("p");
        text.textContent = message;
        body.appendChild(text);
      }
      let field = null;
      const error = document.createElement("p");
      error.className = "dialog-error hidden";
      if (input) {
        const wrap = document.createElement("label");
        wrap.className = "dialog-field";
        if (input.label) {
          const caption = document.createElement("span");
          caption.textContent = input.label;
          wrap.appendChild(caption);
        }
        field = document.createElement(input.multiline ? "textarea" : "input");
        if (!input.multiline) field.type = input.type || "text";
        if (input.autocomplete) field.autocomplete = input.autocomplete;
        if (input.readOnly) field.readOnly = true;
        field.value = input.value || "";
        if (input.multiline) field.rows = 8;
        wrap.appendChild(field);
        body.append(wrap, error);
      }
      const actions = document.createElement("div");
      actions.className = "dialog-actions";
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.textContent = cancelLabel;
      const confirm = document.createElement("button");
      confirm.type = "button";
      confirm.className = destructive ? "danger-fill" : "primary";
      confirm.textContent = confirmLabel;
      if (cancelLabel) actions.appendChild(cancel);
      actions.appendChild(confirm);
      card.append(body, actions);
      overlay.appendChild(card);

      function close(result) {
        overlay.remove();
        if (!document.querySelector(".modal:not(.hidden)")) document.body.classList.remove("modal-open");
        if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
        resolve(result);
      }

      function submit() {
        if (!field) {
          close(true);
          return;
        }
        const value = field.value;
        const minLength = Number(input.minLength || 0);
        if (minLength && value.length < minLength) {
          error.textContent = `Нужно не меньше ${countText(minLength, ["символа", "символов", "символов"])} — сейчас ${value.length}.`;
          error.classList.remove("hidden");
          field.focus();
          return;
        }
        close(value);
      }

      cancel.addEventListener("click", () => close(field ? null : false));
      confirm.addEventListener("click", submit);
      overlay.addEventListener("click", (event) => {
        if (event.target === overlay) close(field ? null : false);
      });
      overlay.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          close(field ? null : false);
        } else if (event.key === "Enter" && field && !input.multiline) {
          event.preventDefault();
          submit();
        }
      });
      document.body.appendChild(overlay);
      document.body.classList.add("modal-open");
      window.requestAnimationFrame(() => {
        if (field) {
          field.focus();
          if (input.readOnly) field.select();
        } else {
          (destructive ? cancel : confirm).focus();
        }
      });
    });
  }

  function confirmDialog(options) {
    return openDialog({confirmLabel: "Продолжить", ...options});
  }

  function promptDialog(options) {
    return openDialog({
      ...options,
      input: {
        label: options.label,
        value: options.value,
        type: options.type,
        multiline: options.multiline,
        readOnly: options.readOnly,
        minLength: options.minLength,
        autocomplete: options.autocomplete
      }
    });
  }

  // Вместо трёх режимов («Врач», «Исследователь», «Админ») — один переключатель технических данных.
  // По умолчанию он включён у администратора и выключен у врача.
  const technicalKey = "cvd:technical-data";
  const legacyModeKey = "cvd:interface-mode";

  function userRole() {
    return window.CURRENT_USER?.role || "user";
  }

  function technicalDataEnabled() {
    try {
      const stored = localStorage.getItem(technicalKey);
      if (stored === "1") return true;
      if (stored === "0") return false;
      const legacy = localStorage.getItem(legacyModeKey);
      if (legacy) return legacy !== "doctor";
    } catch (_) {}
    return userRole() === "admin";
  }

  function interfaceMode() {
    if (!technicalDataEnabled()) return "doctor";
    return userRole() === "admin" ? "admin" : "researcher";
  }

  function syncTechnicalToggles() {
    const enabled = technicalDataEnabled();
    document.querySelectorAll("[data-technical-toggle]").forEach((button) => {
      button.setAttribute("aria-checked", String(enabled));
      button.classList.toggle("is-on", enabled);
    });
  }

  function applyInterfaceMode() {
    const mode = interfaceMode();
    document.body.dataset.interfaceMode = mode;
    syncTechnicalToggles();
    return mode;
  }

  function setTechnicalData(enabled) {
    try {
      localStorage.setItem(technicalKey, enabled ? "1" : "0");
      localStorage.setItem(legacyModeKey, enabled ? (userRole() === "admin" ? "admin" : "researcher") : "doctor");
    } catch (_) {}
    const mode = applyInterfaceMode();
    document.dispatchEvent(new CustomEvent("cvd:interface-mode", {detail: {mode, technical: enabled}}));
  }

  document.querySelectorAll("[data-technical-toggle]").forEach((button) => {
    button.addEventListener("click", () => setTechnicalData(!technicalDataEnabled()));
  });
  document.querySelectorAll("[data-shortcut]").forEach((node) => {
    const [key, modifier] = String(node.dataset.shortcut).split(":");
    node.textContent = shortcut(key, {alt: modifier === "alt"});
  });

  window.CVDUI = {
    isMac,
    shortcut,
    pluralize,
    countText,
    ageText,
    demographicsText,
    formatDateTime,
    relativeTime,
    timeElement,
    humanizeError,
    toast,
    confirm: confirmDialog,
    prompt: promptDialog,
    technicalDataEnabled,
    interfaceMode,
    applyInterfaceMode,
    setTechnicalData
  };
})();
