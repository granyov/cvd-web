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
})();
