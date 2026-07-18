# CVD Web v0.9.13

Release focused on the printable conclusion and on clearing defects found while walking the cardiologist's daily path through the interface.

## Highlights

- Rebuilds the HTML export as a clinical conclusion: the physician's own diagnosis and the AI draft open the document side by side with their ICD-10 codes, so agreement and divergence are visible at a glance.
- Adds a signature block (physician, signature, date) and orders the document the way a doctor reads it: conclusion, recommendations, signature, disclaimer, then the AI reasoning.
- Moves patient data into an appendix that starts on its own page and can be switched off before printing, so the conclusion fits a single sheet.
- Prepares print output for A4: page margins, a running header with patient name and ID on every page, blocks that do not break across pages, hidden interface controls, and a "Печать / Сохранить PDF" action that maps onto the browser's Save-as-PDF.
- Renders report dates as "18 июля 2026, 22:52" instead of ISO timestamps and shows case number, age, and sex in the header.
- Drops the broken right-panel tab numbering, which showed "1. Проверка" and "3. Результат" with no second tab because the JSON tab is hidden for doctors.
- Removes the sticky section strip that had returned as a fourth copy of the section list with 3081px of horizontal scroll inside an 828px column.
- Hides the technical "Ответ модели" form section in the doctor role, where the AI answer belongs to the result window instead of being editable as captured data.
- Renames the worklist total to "Все кейсы" and separates it, so stage counters no longer read as a sum of eight cases when there are four.
- Renames "Рабочий минимум" to "Быстрый ввод" with "Профиль случая", collapses it into a single line, and explains readiness changes with a "+N к обязательным" badge.
- Updates the Umbrel package to use `ghcr.io/granyov/cvd-web:v0.9.13`.

## Install

```bash
./install.sh --target local
./install.sh --target wsl2 --unattended
sudo ./install.sh --target vps --domain cvd.example.com --unattended
```

For release-archive installs:

```bash
scripts/install_from_release.sh \
  --url https://github.com/granyov/cvd-web/releases/download/v0.9.13/cvd-web-v0.9.13.tar.gz \
  --sha256-url https://github.com/granyov/cvd-web/releases/download/v0.9.13/cvd-web-v0.9.13.tar.gz.sha256 \
  -- --target local --unattended
```

## Beta limitations

- Not a medical device and not clinically validated.
- Use only synthetic or deidentified data.
- PDF intake reads the text layer only; scanned documents need OCR before import.
- The SQLite worker and in-process inference queue support one backend process.
- Production deployments must add HTTPS and should use external queue/rate-limit adapters before strict production readiness.
