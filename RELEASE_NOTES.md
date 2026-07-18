# CVD Web v0.9.11

Release focused on daily clinical usability: fewer always-open blocks, clearer next actions, visible background AI work, and tighter responsive text handling.

## Highlights

- Adds one sticky case status bar with the saved/unsaved case state, scenario readiness, AI status, next action, and active task count.
- Makes "Рабочий минимум" collapsible and closed by default. It now stays out of the way until the user explicitly opens scenario-based quick fields.
- Adds clinical scenarios for general cardiology, IHD/ACS, heart failure, arrhythmias, hypertension, and valvular disease. Each scenario extends the readiness checklist and quick fields with the data that matters for that workflow.
- Adds search across the whole patient form, so typing terms like "тропонин", "ФВ", "МКБ", "АД", or "жалобы" jumps directly to the right field.
- Adds a center for AI tasks with queued, running, finished, and failed jobs. Finished diagnosis and text-preparation jobs can be opened directly from the list.
- Reworks the AI result modal into a working document: doctor-vs-AI diagnosis panels, copy, open report, accept AI diagnosis into the physician draft, and mark answer issue.
- Simplifies import review around decisions first: reliable fields, conflicts, unchanged values, and a collapsible detailed diff.
- Adds inline warnings next to important fields such as blood pressure, heart rate, SpO2, troponin, NT-proBNP, potassium, LVEF, and ECG text.
- Adds an archive action queue for cases that need attention: stale AI results, failed AI runs, incomplete data, and unreviewed results.
- Tightens font sizes, button labels, wrapping, mobile layout, and doctor-mode hiding of technical controls so labels fit without horizontal overflow.
- Updates the Umbrel package to use `ghcr.io/granyov/cvd-web:v0.9.11`.

## Install

```bash
./install.sh --target local
./install.sh --target wsl2 --unattended
sudo ./install.sh --target vps --domain cvd.example.com --unattended
```

For release-archive installs:

```bash
scripts/install_from_release.sh \
  --url https://github.com/granyov/cvd-web/releases/download/v0.9.11/cvd-web-v0.9.11.tar.gz \
  --sha256-url https://github.com/granyov/cvd-web/releases/download/v0.9.11/cvd-web-v0.9.11.tar.gz.sha256 \
  -- --target local --unattended
```

## Beta limitations

- Not a medical device and not clinically validated.
- Use only synthetic or deidentified data.
- PDF intake reads the text layer only; scanned documents need OCR before import.
- The SQLite worker and in-process inference queue support one backend process.
- Production deployments must add HTTPS and should use external queue/rate-limit adapters before strict production readiness.
