(function () {
  "use strict";

  const settings = window.APP_SETTINGS || {};
  const defaultTheme = settings.default_theme === "dark" ? "dark" : "light";
  const storedTheme = window.localStorage.getItem("cvd_theme");
  const initialTheme = storedTheme === "dark" || storedTheme === "light" ? storedTheme : defaultTheme;

  function applyTheme(theme) {
    document.body.dataset.theme = theme;
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.textContent = theme === "dark" ? "Светлая тема" : "Тёмная тема";
    });
  }

  window.CVDTheme = {
    apply: applyTheme,
    toggle() {
      const next = document.body.dataset.theme === "dark" ? "light" : "dark";
      window.localStorage.setItem("cvd_theme", next);
      applyTheme(next);
    }
  };

  applyTheme(initialTheme);
  document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
    button.addEventListener("click", () => window.CVDTheme.toggle());
  });

  const userLabel = document.getElementById("userLabel");
  if (userLabel && !userLabel.textContent && window.CURRENT_USER?.email) {
    userLabel.textContent = window.CURRENT_USER.email;
  }

  function closeMenus() {
    document.querySelectorAll("[data-menu] [data-menu-panel]:not(.hidden)").forEach((panel) => {
      panel.classList.add("hidden");
      panel.closest("[data-menu]")?.querySelector("[data-menu-toggle]")?.setAttribute("aria-expanded", "false");
    });
  }

  document.querySelectorAll("[data-menu]").forEach((menu) => {
    const toggle = menu.querySelector("[data-menu-toggle]");
    const panel = menu.querySelector("[data-menu-panel]");
    if (!toggle || !panel) return;
    toggle.addEventListener("click", (event) => {
      event.stopPropagation();
      const willOpen = panel.classList.contains("hidden");
      closeMenus();
      panel.classList.toggle("hidden", !willOpen);
      toggle.setAttribute("aria-expanded", String(willOpen));
    });
    panel.addEventListener("click", (event) => {
      if (event.target.closest("button")) closeMenus();
    });
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest("[data-menu]")) closeMenus();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMenus();
  });
})();
