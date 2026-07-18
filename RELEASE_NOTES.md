# CVD Web v0.9.10

Release focused on EMIAS PDF intake, a professional result view, and a much quieter interface.

## Highlights

- Imports PDF exports from EMIAS.INFO: the text layer is extracted with the standard library only (FlateDecode, ToUnicode CMap so Cyrillic decodes correctly) and passed to AI preparation, where every extracted field still requires an explicit diff confirmation. Scans without a text layer get an actionable message instead of an empty result.
- Asks the model for treatment and rehabilitation drafts. These fields existed in the patient template from the start but no prompt ever requested them, so they were always empty; the prompt now returns MODEL_OUTPUT next to the CDS reasoning.
- Keeps recommendations safe by construction: drug classes and targets only, never brand names, doses, or prescriptions, and every answer is framed as a draft for the physician.
- Refreshes the stored prompt template on upgrade only when it still holds the previous default, so customised templates survive the update (migration 0014).
- Presents the AI result as a clinical document: leading diagnosis first with confidence and codes, red flags as badges, ICD-10 codes as click-to-copy chips, and a doctor-vs-AI code comparison that only appears when both sides have codes.
- Completes the loop from history: opening a case from the archive loads its latest successful result, edits mark it stale, and "Обновить анализ" re-runs the analysis in the same flow.
- Uses "CVD Engine" in the doctor role instead of internal model names, and hides the model filter and demo case button there.
- Declutters the workspace from eleven meta layers above the form to three: no decorative hero, no workflow strip, no sticky section navigator, no floating emoji layer; three primary actions plus an "Ещё" menu; one navigation row with a single user menu.
- Renders numeric sections as a dense 3-4 column grid with units inside the field, so a full lab panel fits one screen, and replaces the key-field checklist with a progress bar plus the missing rows.
- Adds inline SVG icons, tabular numerals, visible focus rings, dropdown and section transitions, and an indeterminate loading bar in the archive.
- Updates the Umbrel package to use `ghcr.io/granyov/cvd-web:v0.9.10`.

## Install

```bash
./install.sh --target local
./install.sh --target wsl2 --unattended
sudo ./install.sh --target vps --domain cvd.example.com --unattended
```

For release-archive installs:

```bash
scripts/install_from_release.sh \
  --url https://github.com/granyov/cvd-web/releases/download/v0.9.10/cvd-web-v0.9.10.tar.gz \
  --sha256-url https://github.com/granyov/cvd-web/releases/download/v0.9.10/cvd-web-v0.9.10.tar.gz.sha256 \
  -- --target local --unattended
```

## Beta limitations

- Not a medical device and not clinically validated.
- Use only synthetic or deidentified data.
- PDF intake reads the text layer only; scanned documents need OCR before import.
- The SQLite worker and in-process inference queue support one backend process.
- Production deployments must add HTTPS and should use external queue/rate-limit adapters before strict production readiness.
