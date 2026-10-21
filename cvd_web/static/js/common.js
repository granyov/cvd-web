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
      node.dataset.relative = "1";
    }
    return node;
  }

  // «Только что» и «5 мин назад» должны стареть, пока страница открыта.
  function refreshRelativeTimes() {
    document.querySelectorAll("time[data-relative]").forEach((node) => {
      node.textContent = relativeTime(node.dateTime);
    });
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

  // Тосты живут в одной области поверх модальных окон: результат AI открыт на весь экран,
  // и подтверждения «скопировано» или ошибки сохранения иначе оказывались под ним.
  let toastRegion = null;
  let plainToast = null;
  let actionToast = null;

  function ensureToastRegion() {
    if (toastRegion?.isConnected) return toastRegion;
    toastRegion = document.getElementById("toastRegion") || document.createElement("div");
    toastRegion.id = "toastRegion";
    toastRegion.className = "toast-region";
    toastRegion.setAttribute("role", "status");
    toastRegion.setAttribute("aria-live", "polite");
    if (!toastRegion.isConnected) document.body.appendChild(toastRegion);
    return toastRegion;
  }

  // onDismiss(reason) узнаёт, чем закончился тост: "action", "timeout", "replaced" или "manual".
  function toast(message, {actionLabel = "", onAction = null, onDismiss = null, duration = 3200, focusAction = false} = {}) {
    const hasAction = Boolean(actionLabel && onAction);
    // Тост с действием («Отменить») не вытесняется обычным сообщением, иначе отмена пропадала бы молча.
    (hasAction ? actionToast : plainToast)?.dismiss("replaced");
    const node = document.createElement("div");
    node.className = hasAction ? "toast has-action" : "toast";
    const text = document.createElement("span");
    text.textContent = humanizeError(message);
    node.appendChild(text);
    const returnFocus = document.activeElement;
    let timer = null;
    let remaining = duration;
    let startedAt = 0;
    let holds = 0;
    const handle = {
      dismissed: false,
      dismiss(reason = "manual") {
        if (handle.dismissed) return;
        handle.dismissed = true;
        window.clearTimeout(timer);
        const hadFocus = node.contains(document.activeElement);
        node.remove();
        if (plainToast === handle) plainToast = null;
        if (actionToast === handle) actionToast = null;
        if (hadFocus && returnFocus instanceof HTMLElement && returnFocus.isConnected) returnFocus.focus();
        onDismiss?.(reason);
      }
    };
    const start = () => {
      startedAt = Date.now();
      timer = window.setTimeout(() => handle.dismiss("timeout"), remaining);
    };
    // Пока указатель или фокус на тосте, он не исчезает: успеть нажать «Отменить» можно и с клавиатуры.
    const hold = () => {
      if (holds++ > 0) return;
      window.clearTimeout(timer);
      remaining = Math.max(1500, remaining - (Date.now() - startedAt));
    };
    const release = () => {
      if (holds > 0 && --holds === 0) start();
    };
    node.addEventListener("mouseenter", hold);
    node.addEventListener("mouseleave", release);
    node.addEventListener("focusin", hold);
    node.addEventListener("focusout", release);
    let action = null;
    if (hasAction) {
      action = document.createElement("button");
      action.type = "button";
      action.className = "toast-action";
      action.textContent = actionLabel;
      action.addEventListener("click", () => {
        handle.dismiss("action");
        onAction();
      });
      node.appendChild(action);
    }
    ensureToastRegion().appendChild(node);
    if (hasAction) actionToast = handle;
    else plainToast = handle;
    start();
    if (action && focusAction) action.focus({preventScroll: true});
    return handle;
  }

  // Диалоги-листы вместо window.confirm/prompt: системные окна выбиваются из интерфейса,
  // не умеют разметку и в некоторых браузерах блокируются.
  let dialogCounter = 0;
  const openDialogs = [];

  function dialogOpen() {
    return openDialogs.length > 0;
  }

  function focusableIn(root) {
    return Array.from(root.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'))
      .filter((node) => !node.disabled && node.getClientRects().length > 0);
  }

  function openDialog({title, message = "", input = null, confirmLabel = "OK", cancelLabel = "Отмена", destructive = false}) {
    return new Promise((resolve) => {
      const previousFocus = document.activeElement;
      const id = ++dialogCounter;
      const openedAt = Date.now();
      const overlay = document.createElement("div");
      overlay.className = "modal ui-dialog";
      overlay.setAttribute("role", destructive ? "alertdialog" : "dialog");
      overlay.setAttribute("aria-modal", "true");
      const card = document.createElement("div");
      card.className = "modal-card dialog-card";
      card.tabIndex = -1;
      const body = document.createElement("div");
      body.className = "dialog-body";
      const heading = document.createElement("h2");
      heading.id = `cvd-dialog-title-${id}`;
      heading.textContent = title;
      overlay.setAttribute("aria-labelledby", heading.id);
      body.appendChild(heading);
      if (message) {
        const text = document.createElement("p");
        text.id = `cvd-dialog-message-${id}`;
        text.textContent = message;
        overlay.setAttribute("aria-describedby", text.id);
        body.appendChild(text);
      }
      let field = null;
      const error = document.createElement("p");
      error.className = "dialog-error hidden";
      error.id = `cvd-dialog-error-${id}`;
      error.setAttribute("role", "alert");
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
        if (input.spellcheck === false) field.spellcheck = false;
        if (input.readOnly) field.readOnly = true;
        field.value = input.value || "";
        if (input.multiline) field.rows = 8;
        field.setAttribute("aria-describedby", error.id);
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

      const dialog = {overlay};

      function close(result) {
        document.removeEventListener("keydown", onKeydown, true);
        const index = openDialogs.indexOf(dialog);
        if (index >= 0) openDialogs.splice(index, 1);
        overlay.remove();
        if (!document.querySelector(".modal:not(.hidden)")) document.body.classList.remove("modal-open");
        if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
        resolve(result);
      }

      const dismiss = () => close(field ? null : false);

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
          field.setAttribute("aria-invalid", "true");
          field.focus();
          return;
        }
        close(value);
      }

      // Клавиатуру слушаем на документе: фокус может уйти из диалога, а Escape должен работать всегда.
      function onKeydown(event) {
        if (openDialogs[openDialogs.length - 1] !== dialog) return;
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopImmediatePropagation();
          dismiss();
        } else if (event.key === "Enter" && field && event.target === field && !input.multiline) {
          // Enter на кнопке «Отмена» нажимает её саму, а не подтверждает введённое.
          event.preventDefault();
          event.stopImmediatePropagation();
          submit();
        } else if (event.key === "Tab") {
          const items = focusableIn(card);
          if (!items.length) {
            event.preventDefault();
            card.focus();
            return;
          }
          const first = items[0];
          const last = items[items.length - 1];
          const active = document.activeElement;
          if (!card.contains(active)) {
            event.preventDefault();
            (event.shiftKey ? last : first).focus();
          } else if (event.shiftKey && (active === first || active === card)) {
            event.preventDefault();
            last.focus();
          } else if (!event.shiftKey && active === last) {
            event.preventDefault();
            first.focus();
          }
        }
      }

      cancel.addEventListener("click", dismiss);
      confirm.addEventListener("click", submit);
      // Закрываем по фону, только если нажатие и началось на фоне: выделение текста, отпущенное
      // за краем карточки, и второй щелчок двойного нажатия не должны отменять диалог.
      let pressedOnBackdrop = false;
      overlay.addEventListener("pointerdown", (event) => {
        pressedOnBackdrop = event.target === overlay;
      });
      overlay.addEventListener("click", (event) => {
        const fromBackdrop = pressedOnBackdrop && event.target === overlay;
        pressedOnBackdrop = false;
        if (fromBackdrop && Date.now() - openedAt > 300) dismiss();
      });
      openDialogs.push(dialog);
      document.addEventListener("keydown", onKeydown, true);
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
        autocomplete: options.autocomplete,
        spellcheck: options.spellcheck
      }
    });
  }

  // Вместо трёх режимов («Врач», «Исследователь», «Админ») — один переключатель технических данных.
  // По умолчанию он включён у администратора и выключен у врача.
  const legacyModeKey = "cvd:interface-mode";

  function userRole() {
    return window.CURRENT_USER?.role || "user";
  }

  // Выбор хранится для каждой учётной записи: на общем компьютере врач не должен
  // унаследовать технический режим администратора, а администратор — выключенный режим врача.
  function technicalKey() {
    const user = window.CURRENT_USER || {};
    return `cvd:technical-data:${user.id ?? user.email ?? "anonymous"}`;
  }

  function technicalDataEnabled() {
    try {
      const stored = localStorage.getItem(technicalKey());
      if (stored === "1") return true;
      if (stored === "0") return false;
      // Режим прежних версий общий для браузера; «admin» у не-администратора не учитываем, как и раньше.
      const legacy = localStorage.getItem(legacyModeKey);
      if (legacy === "doctor") return false;
      if (legacy === "researcher") return true;
      if (legacy === "admin" && userRole() === "admin") return true;
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
      localStorage.setItem(technicalKey(), enabled ? "1" : "0");
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
  window.setInterval(refreshRelativeTimes, 60000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshRelativeTimes();
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
    refreshRelativeTimes,
    humanizeError,
    toast,
    dialogOpen,
    confirm: confirmDialog,
    prompt: promptDialog,
    technicalDataEnabled,
    interfaceMode,
    applyInterfaceMode,
    setTechnicalData
  };
})();
