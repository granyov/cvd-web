const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const storage = new Map();
const context = {
  navigator: {platform: "Linux x86_64", userAgent: "node"},
  localStorage: {
    getItem: (key) => (storage.has(key) ? storage.get(key) : null),
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: (key) => storage.delete(key)
  },
  document: {querySelectorAll: () => []},
  window: {CURRENT_USER: {role: "user"}},
  Intl,
  Date
};
context.window.localStorage = context.localStorage;
vm.createContext(context);
vm.runInContext(fs.readFileSync("cvd_web/static/js/common.js", "utf8"), context);
const ui = context.window.CVDUI;

assert.strictEqual(ui.ageText(1), "1 год");
assert.strictEqual(ui.ageText(62), "62 года");
assert.strictEqual(ui.ageText(58), "58 лет");
assert.strictEqual(ui.ageText(11), "11 лет");
assert.strictEqual(ui.ageText(""), "");
assert.strictEqual(ui.demographicsText(62, "male"), "Мужчина, 62 года");
assert.strictEqual(ui.demographicsText(null, "female"), "Женщина");
assert.strictEqual(ui.demographicsText(45, ""), "45 лет");

const now = new Date("2026-10-21T12:00:00");
assert.strictEqual(ui.relativeTime(new Date("2026-10-21T11:59:40"), now), "только что");
assert.strictEqual(ui.relativeTime(new Date("2026-10-21T11:55:00"), now), "5 мин назад");
assert.strictEqual(ui.relativeTime(new Date("2026-10-21T09:10:00"), now), "2 ч назад");
assert.ok(ui.relativeTime(new Date("2026-10-20T18:30:00"), now).startsWith("вчера, "));

const humanized = ui.humanizeError("Не удалось получить модели LM Studio: <urlopen error [Errno 111] Connection refused>");
assert.ok(humanized.startsWith("Не удалось получить модели LM Studio: сервис не отвечает"), humanized);
assert.ok(!/urlopen|Errno/.test(humanized), humanized);
assert.strictEqual(ui.humanizeError("Кейс не найден"), "Кейс не найден");
assert.ok(/Нет связи с сервером/.test(ui.humanizeError("Failed to fetch")));

// Врач по умолчанию видит интерфейс без технических данных, администратор — с ними.
assert.strictEqual(ui.interfaceMode(), "doctor");
storage.set("cvd:interface-mode", "researcher");
assert.strictEqual(ui.interfaceMode(), "researcher");
storage.set("cvd:technical-data", "0");
assert.strictEqual(ui.interfaceMode(), "doctor");
storage.clear();
context.window.CURRENT_USER = {role: "admin"};
assert.strictEqual(ui.interfaceMode(), "admin");

const qualityContext = {window: {CVD_SCHEMA: []}};
vm.createContext(qualityContext);
vm.runInContext(fs.readFileSync("cvd_web/static/js/clinical-quality.js", "utf8"), qualityContext);
const troponin = (value) => qualityContext.window.CVDClinicalQuality
  .clinicalSignals({LABS_CARDIAC_MARKERS: {Troponin_ng_L: value}})
  .filter((signal) => signal.title.includes("Тропонин"))
  .map((signal) => signal.kind)
  .join(",");
assert.strictEqual(troponin(9), "info");
assert.strictEqual(troponin(48), "warning");

console.log("common.js checks passed");
