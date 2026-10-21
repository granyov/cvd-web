# CVD Web v0.9.20

Release focused on the doctor's path from a discharge note to a checked conclusion. The workspace used to open on an empty form of 117 fields with a dozen equal buttons; now every screen has one obvious next step.

## Highlights

- Opens a new case on a start screen with three paths: paste a discharge note, upload a file, or fill in manually. Text preparation and file import were previously hidden in the "More" menu.
- Replaces three status tiles, the "Next:" hint and a duplicate progress bar with one status line and one primary button that walks the case: fill the key fields, run the AI analysis, open the result, copy it for the MIS. Accepting the AI draft into the doctor's diagnosis keeps the button on "Copy for MIS" instead of asking for a re-run.
- Saves cases automatically after a pause in typing and at most once every 15 seconds, because every save is written to the audit log. A new case is created only once it has an ID, a name or a complaint, so a stray keystroke does not litter the archive. Pending edits are saved before switching cases, before an AI run, before copying for the MIS and before logout; when the tab closes, edits to an existing case go out in a background request. If a save fails, the status line says so and the app asks before leaving the case.
- Keeps an AI result with the case that started it. A doctor can open another case while the analysis runs; when it finishes, a notification offers to open the result instead of writing it into the open form.
- Lets the case profile shape the form: the profile's sections come first, the rest move under "Additional sections", and a section that already holds data never hides. A section sidebar shows fill state, and a "missing key fields only" filter narrows the form to what is left.
- Shows the AI result as a full-screen document with two primary actions, "Accept into draft" and "Copy for MIS", and a one-tap expert rating; details are optional.
- Turns the archive's worklist stages into the case filter, shortens list rows to title, status and relative time, and makes deletion undoable instead of asking for confirmation. The undo stays on screen while it has focus or the pointer, and focus moves to it, so it works from the keyboard too.
- Opens another user's case read-only for administrators: the server only saves cases for their owner, and editing such a case used to end in an endless failing autosave.
- Tiers clinical signals: critical first, then deviations. A troponin within the reference range is now informational instead of a warning that fired for every entered value.
- Adds a Cmd/Ctrl+K palette for commands and form fields and Cmd/Ctrl+Enter to run the analysis.
- Replaces the doctor/researcher/admin interface modes with one "Technical data" switch, on by default for administrators and off for doctors, remembered per account so a shared workstation does not carry one user's choice over to the next.
- Restyles the interface after Apple's iOS/iPadOS and macOS design kits, in light and dark themes, using the system font stack (SF Pro is not bundled: its licence covers Apple-platform UI only). Status text, links and white-on-red buttons use darker shades that pass WCAG AA, and the focus outline is opaque.
- Fixes text a doctor read every day: "Мужчина, 62 года" instead of "62 лет · male", readable connection errors instead of Python tracebacks, and app dialogs instead of browser confirm/prompt windows.

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
  --url https://github.com/granyov/cvd-web/releases/download/v0.9.20/cvd-web-v0.9.20.tar.gz \
  --sha256-url https://github.com/granyov/cvd-web/releases/download/v0.9.20/cvd-web-v0.9.20.tar.gz.sha256 \
  -- --target local --unattended
```

## Beta limitations

- Not a medical device and not clinically validated.
- Use only synthetic or deidentified data.
- Exported documents are drafts: they are not signed with УКЭП and are not legally valid medical records.
- Autosave writes an audit entry at most every 15 seconds while a case is being edited.
- A brand-new case that was never saved is not sent when the tab closes; its edits stay in the browser's local draft and are offered on the next visit.
- Reference ranges in the printed appendix are indicative adult ranges; they do not replace local laboratory references or clinical judgement.
- Printed page numbers are not available: Chrome does not support CSS `@page` margin boxes.
- PDF intake reads the text layer only; scanned documents need OCR before import.
- The SQLite worker and in-process inference queue support one backend process.
- Production deployments must add HTTPS and should use external queue/rate-limit adapters before strict production readiness.
