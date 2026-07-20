# CVD Web v0.9.17

Release focused on the printed clinical conclusion: the HTML export is read on paper, hours or days after the analysis, by someone who cannot hover a value or open the archive.

## Highlights

- Warns when the case was edited after the analysis and names the changed fields. On screen that warning lives a second; the printed document lives for years and previously said nothing.
- Prints the reviewing doctor's verdict, corrected diagnosis, ICD-10 codes and comment. Without a review it states plainly that the conclusion is an unreviewed draft, rather than letting a machine draft pass for a checked document.
- Gives red flags their own block instead of one tile among equals.
- Prints reference ranges next to every numeric value and marks deviations. On paper nobody can hover a field, and "Hb 121" says nothing without the range.
- Replaces the appendix checkbox with three modes: do not print, deviations only, full. On a real case "deviations only" prints 10 rows instead of 110.
- Adds a traceability line with the application, prompt and output schema versions. The model identifier is deliberately absent: the product speaks to the doctor as CVD Engine, and the model stays in the archive under the analysis number.
- Fixes Russian field labels in the appendix. Python knew 25 of the 117 labels the input form uses, so the printout carried rows like "LDL mmol L".
- Adds a parity test between Python and the frontend for reference ranges and field labels. The two copies drifting would show one thing on screen and another on the printout for the same laboratory value.

## Recommended model setup

Load the model in LM Studio with at least **32768 tokens** of context. A typical case with history, ECG, echo and imaging descriptions takes 3-15 thousand tokens, and `lm_studio_max_tokens` is reserved on top for the answer.

## Install

```bash
./install.sh --target local
./install.sh --target wsl2 --unattended
sudo ./install.sh --target vps --domain cvd.example.com --unattended
```

For release-archive installs:

```bash
scripts/install_from_release.sh \
  --url https://github.com/granyov/cvd-web/releases/download/v0.9.17/cvd-web-v0.9.17.tar.gz \
  --sha256-url https://github.com/granyov/cvd-web/releases/download/v0.9.17/cvd-web-v0.9.17.tar.gz.sha256 \
  -- --target local --unattended
```

## Beta limitations

- Not a medical device and not clinically validated.
- Use only synthetic or deidentified data.
- Exported documents are drafts: they are not signed with УКЭП and are not legally valid medical records.
- Reference ranges in the printed appendix are indicative adult ranges; they do not replace local laboratory references or clinical judgement.
- Printed page numbers are not available: Chrome does not support CSS `@page` margin boxes.
- PDF intake reads the text layer only; scanned documents need OCR before import.
- The SQLite worker and in-process inference queue support one backend process.
- Production deployments must add HTTPS and should use external queue/rate-limit adapters before strict production readiness.
