# Changelog

## v0.9.16 - 2026-07-20

- Record the real context length of the loaded model during the admin health check, and refuse an oversized case in milliseconds instead of letting the doctor wait about forty seconds for the model to fail.
- Show the case size in tokens in the review window instead of a JSON character count, with an explicit warning and a disabled confirm button when the case will not fit.
- Re-read the model context from LM Studio before any size refusal, so a stale setting cannot block work after the model is reloaded with a different context; when the check cannot be made, let the job through and surface the genuine service error.
- Recommend loading the model with at least 32768 tokens of context and document how the size check behaves.
- Fix the prompt version stamped on analyses: migration 0014 replaced the template but left `active_prompt_version` at v4, so runs on prompt v5 were saved under the wrong label and the model-quality dashboard would have compared versions against fiction. Migration 0015 lifts the version only when the template is the current default and the version is a known previous default.
- Add the real worst-case score to the Gold Set summary and rename the threshold field, which previously read as a minimum observed score, and translate the remaining English labels in that panel.
- Update Umbrel metadata and image tag for `ghcr.io/granyov/cvd-web:v0.9.16`.

## v0.9.15 - 2026-07-20

- Raise the structuring ceiling from 14 to 30 facts per chunk: a real EMIAS consultation protocol silently lost NT-proBNP, creatinine, eGFR, potassium, haemoglobin, SpO2, respiratory rate and the whole medication list, because they sat after the cut-off at the end of the note.
- Ask the model explicitly for laboratory values and current therapy at the end of a note, and to warn when facts do not fit; the same protocol now yields 27 fields instead of 14.
- Refuse to accept an abstention as a diagnosis: when the model abstains, "Принять в черновик" is disabled with an explanation and the placeholder ICD-10 codes are hidden, so a non-diagnosis cannot be written into the physician's conclusion with one click.
- Remove the duplicated diagnosis from the result window, where it appeared three times: in the comparison panel, as the "МКБ-10: ..." tail inside the text, and as a separate leading-diagnosis block with different wording.
- Strip the trailing ICD-10 list wherever codes are already rendered as chips or a separate line, in the UI, the printable report and the MIS text.
- Collapse the result actions from six buttons across two rows into one row with an overflow menu, and drop metric tiles that repeat the lists below.
- Fix the ICD-10 comparison disappearing when a result was opened from history: it read codes from a form field that only a fresh run fills.
- Update Umbrel metadata and image tag for `ghcr.io/granyov/cvd-web:v0.9.15`.

## v0.9.14 - 2026-07-19

- Classify context-overflow failures correctly: LM Studio echoes the request body in its error payload, so the message matched the "json" branch and told the doctor the answer could not be structured and the request could be repeated, which never worked.
- Return an actionable message instead: the case does not fit the model context, repeating will not help, shorten long free-text fields or raise the model context; the retry button hides for this failure class.
- Fix the task centre layout, where a long error text in the actions column squeezed the job title into a syllable-per-line column with the status badge overlapping it; the message now spans its own row.
- Stop leaking "LM Studio" into doctor-facing errors and cap the raw fallback message at 300 characters.
- Add "Копировать для МИС": a ready protocol block with the physician's diagnosis, the AI draft, ICD-10 codes, reasoning, recommendations and disclaimer, exposed via `GET /api/reports/{id}/mis-text` and recorded in the audit log.
- Extend the FHIR R4 export with the conclusion: DiagnosticReport with conclusionCode in `http://hl7.org/fhir/sid/icd-10` (preliminary when the model abstained), ClinicalImpression with reasoning and red flags, CarePlan with status=draft and intent=proposal, Practitioner and Organization performers, and a Composition with real sections.
- Mark the physician's diagnosis as a Condition with verificationStatus=confirmed so a receiving system can tell it from the AI draft.
- Keep exports of cases without a result unchanged, covered by a backward-compatibility test.
- Update Umbrel metadata and image tag for `ghcr.io/granyov/cvd-web:v0.9.14`.

## v0.9.13 - 2026-07-18

- Rebuild the HTML export as a printable clinical conclusion: the physician's diagnosis and the AI draft open the document side by side with their ICD-10 codes, followed by the AI summary, recommendation draft, and a signature block.
- Move patient data into an appendix that starts on its own page and can be switched off before printing, so the conclusion fits a single sheet.
- Set up print output for A4: page margins, a running header with patient name and ID on every page, blocks that do not break across pages, hidden interface controls, and a "Печать / Сохранить PDF" action.
- Render report dates as "18 июля 2026, 22:52" instead of ISO timestamps, and show case number, age, and sex in the report header.
- Drop the broken tab numbering in the right panel ("1. Проверка" and "3. Результат" with no second tab in the doctor role).
- Remove the sticky section strip that returned as a fourth copy of the section list with 3081px of horizontal scroll.
- Hide the technical "Ответ модели" form section in the doctor role, where the AI answer belongs to the result window rather than to editable case fields.
- Rename the worklist total chip to "Все кейсы" and separate it visually, so stage counters no longer read as a sum.
- Rename "Рабочий минимум" to "Быстрый ввод" with "Профиль случая", collapse it into one line, and show a "+N к обязательным" badge explaining readiness changes after switching profile.
- Update Umbrel metadata and image tag for `ghcr.io/granyov/cvd-web:v0.9.13`.

## v0.9.12 - 2026-07-18

- Start daily work from the case archive/worklist instead of opening the patient form first.
- Add backend-computed workflow stages: new, in work, waiting for AI, needs review, done, and archive.
- Add a shift worklist with stage counts, owners, priorities, next actions, and active AI task state.
- Show global AI queue position across users and include launched-by user, case, and patient context in the task center.
- Allow cancellation of queued diagnosis and text-preparation AI jobs.
- Add user-friendly AI error messages for Cloudflare 524, cloudflared tunnel issues, timeouts, response schema/JSON failures, connection failures, and resource pressure.
- Group recognized free-text facts by clinical category before import: anamnesis, laboratory tests, instrumental tests, objective status, treatment, and diagnosis.
- Extend the case timeline with creation, update, and physician review events.
- Add smoke coverage for the worklist and AI job cancellation contract.
- Update Umbrel metadata and image tag for `ghcr.io/granyov/cvd-web:v0.9.12`.

## v0.9.11 - 2026-07-18

- Add a unified sticky case status bar with case state, readiness, AI status, next action, and AI task count.
- Add a collapsible "Рабочий минимум" that is closed by default and exposes scenario-based quick fields only when needed.
- Add clinical scenarios for general cardiology, IHD/ACS, heart failure, arrhythmias, hypertension, and valvular disease; readiness now includes scenario-specific fields.
- Add field search across the full patient form, with quick navigation to matching sections and fields.
- Add an AI task center showing queued, running, finished, and failed diagnosis/text-preparation jobs with open actions for finished jobs.
- Turn the AI result modal into a working review document with doctor-vs-AI diagnosis panels, copy, report, draft-acceptance, and issue-marking actions.
- Simplify import review around decisions first: apply reliable fields, review conflicts, and keep detailed diff in a collapsible section.
- Add inline clinical warnings next to high-signal fields such as blood pressure, heart rate, SpO2, troponin, NT-proBNP, potassium, LVEF, and ECG text.
- Add an archive action queue for cases that need attention: stale AI results, failed AI runs, incomplete cases, and unreviewed results.
- Tighten responsive typography, button sizing, wrapping, and doctor-mode hiding of technical controls.
- Update Umbrel metadata and image tag for `ghcr.io/granyov/cvd-web:v0.9.11`.

## v0.9.10 - 2026-07-18

- Accept EMIAS PDF exports in the import flow: extract the text layer with the standard library only (FlateDecode, ToUnicode CMap for Cyrillic) and hand the text to AI preparation, where every field still needs an explicit diff confirmation.
- Return a helpful message instead of an empty result when a PDF has no text layer (scan).
- Ask the model for treatment and rehabilitation drafts: the prompt now requests MODEL_OUTPUT next to CDS_OUTPUT, so the recommendation fields that existed in the template are finally filled.
- Restrict recommendation wording to drug classes and targets — never brand names, doses, or prescriptions — and require ICD-10 codes in the array to match the diagnosis text.
- Refresh the stored prompt template on upgrade only when it still holds the previous default, leaving customised templates untouched (migration 0014).
- Show the recommendation draft in the result modal and the printable report behind an explicit disclaimer.
- Rework the AI result into a clinical document: leading diagnosis first, red flags as badges, ICD-10 codes as click-to-copy chips, and a meaningful doctor-vs-AI code comparison.
- Load the latest successful result when a case is opened from the archive, so editing and re-running the analysis is one continuous flow; add an "Обновить анализ" action to the result modal.
- Present the engine as "CVD Engine" in the doctor role and hide model names, the model filter, and the demo case button there.
- Declutter the workspace: no decorative hero, no workflow strip, no sticky section navigator, no floating emoji layer; case status moved into the panel header and secondary actions into an "Ещё" menu.
- Collapse per-page navigation into one row with a single user menu holding interface mode, theme, password change, and logout.
- Render numeric sections as a dense 3-4 column grid with units inside the field, and replace the key-field checklist with a progress bar plus missing rows only.
- Add inline SVG icons, tabular numerals, visible focus rings, dropdown/section transitions, and an indeterminate loading bar in the archive.
- Update Umbrel metadata and image tag for `ghcr.io/granyov/cvd-web:v0.9.10`.

## v0.9.9 - 2026-07-17

- Force administrators who sign in with a default password to set a new one before using any other part of the application.
- Only flag the bootstrap administrator for a forced password change when the configured password is a known default, keeping unattended installs with strong passwords untouched.
- Protect unsaved patient-form data with a beforeunload warning, synchronous draft flush, and an unsaved-changes indicator.
- Show recent cases on the workspace start screen for one-click resume.
- Notify about finished background AI jobs with a toast, tab-title badge, and desktop notification when the tab is hidden.
- Show adult reference ranges next to 30+ numeric fields and highlight out-of-range values while typing.
- Replace raw AI failures with an actionable error card (cause, advice, retry button).
- Add Ctrl/Cmd+S to save the case and Alt+N to jump to the first missing key field.
- Add a one-click synthetic demo case (`POST /api/cases/demo`) in the workspace and empty archive.
- Add call-to-action empty states in the case archive and the admin activity chart.
- Translate the remaining English admin navigation and backup texts into Russian.
- Fix tablet layouts: no horizontal overflow at 768px, wrapping top bar.
- Split the 4400-line `app.py` into domain handler mixins with a shared HTTP core; no behavior change.
- Add WSGI-level smoke tests covering login, case lifecycle, demo case with FHIR export, archive filters, admin dashboards, and logout.
- Update Umbrel metadata and image tag for `ghcr.io/granyov/cvd-web:v0.9.9`.

## v0.9.8 - 2026-07-17

- Reorganize patient-data sections into clinical groups for anamnesis, objective status, laboratory tests, instrumental studies, and treatment/conclusion.
- Number every patient-data section and keep all sections collapsed by default.
- Move the model response from the right panel into a larger working modal with structured output, expert review, export, and technical JSON.
- Keep the right panel focused on numbered quick-check and JSON tabs.
- Update Umbrel metadata and image tag for `ghcr.io/granyov/cvd-web:v0.9.8`.

## v0.9.7 - 2026-07-17

- Move free-text AI preparation to persistent background jobs that continue after closing the UI.
- Show active and recently finished diagnosis/text-preparation jobs in the workspace.
- Process diagnosis and text-preparation jobs through one backend FIFO worker.
- Restore interrupted text-preparation jobs after restart.
- Apply per-user AI job limits across both diagnosis and text-preparation jobs.
- Keep full source text in the job record only until the worker finishes, then retain a preview, hash, metrics, and result.
- Update Umbrel metadata and image tag for `ghcr.io/granyov/cvd-web:v0.9.7`.

## v0.9.3 - 2026-07-07

- Add release archive build/publish tooling with SHA-256 checksums.
- Add local, WSL2, and VPS installer paths with service-oriented runtime configuration.
- Add `/readyz` checks and a WSGI entrypoint for reverse-proxy deployments.
- Improve the clinical workspace by removing duplicated metrics, workflow panels, and repeated next-action guidance.
- Fix narrow-screen workspace ordering so the patient form stays before the review sidebar.
- Extend Gold Set validation with severity and expected missing-data checks.
- Close SQLite backup/restore connections explicitly after backup operations.

## v0.9.0 - 2026-07-02

- Add a clinical-validation Gold Set with versioned validation runs and per-case scoring.
- Add model-quality comparison across Gold Set scores, expert reviews, unsafe rate, latency, throughput, and request success.
- Add an expert-review cockpit for low-scoring, unsafe, and unevaluated cases.
- Add production-readiness controls for SQLite backup/restore, queue backend planning, and LM Studio monitoring.
- Improve AI-result traceability with saved input snapshots, stale-result warnings, and field-level changes.

## v0.8.6 - 2026-07-02

- Add admin SQLite backup, download, and restore with an automatic safety backup before restore.
- Add production queue backend readiness settings for Redis/PostgreSQL rollout while keeping the in-process adapter active in this build.
- Extend LM Studio monitoring with request history, queue status, and production queue readiness signals.

## v0.8.5 - 2026-07-02

- Add an admin model-quality API that compares models by success rate, latency, expert reviews, unsafe rate, and Gold Set score.
- Show model comparison, review distribution, common issue types, and per-case Gold Set comparisons in the admin dashboard.
- Extend tests for multi-model Gold Set comparison and expert-review dashboard metrics.

## v0.8.4 - 2026-07-02

- Improve the AI-result UX with clearer result cards and stale-result warnings.
- Store the original clinical input snapshot for each model request.
- Show a field-level diff explaining what changed in the case after the AI result was generated.

## v0.8.3 - 2026-07-01

- Fix the missing UI badge helper that mislabeled successfully saved model responses as AI-analysis errors.
- Reject completely empty clinical cases in both the browser and backend before calling LM Studio.
- Distinguish AI service failures from client-side result-rendering failures.
- Compare saved result freshness consistently after reloading the workspace.

## v0.8.2 - 2026-06-30

- Define the v0.8 roadmap for AI Gateway, result center, model compare, text structuring, and validation/gold set work.
- Add AI Gateway profiles for same-host, WSL2, LAN, and cloudflared tunnel deployments.
- Add optional admin-only auth header settings for tunnel-protected LM Studio endpoints.
- Pass AI Gateway auth headers to model catalog, activation, diagnosis, and text-structuring calls.
- Add an admin AI Gateway diagnostic endpoint and UI action.
- Add a cloud-release installer wrapper for downloading, verifying, and locally deploying release archives.

## v0.7.0-beta.8 - 2026-06-29

- Move cases, analysis history, and imports into a dedicated bounded-height medical archive.
- Add server-side search, status filters, case filters, summaries, and pagination for growing histories.
- Add case detail navigation with clinical summary, quality metrics, timeline, and linked results.
- Fix model activation when the configured model differs from the model actually loaded in LM Studio.

## v0.7.0-beta.7 - 2026-06-29

- Add a prominent result-ready action and an authenticated inline HTML report view.
- Add searchable, paginated personal case history with edit, copy, FHIR export, and delete actions.
- Link each case to its latest successful analysis while preserving historical reports after case deletion.
- Remove LM Studio and MedGemma names and low-level generation metadata from the user workspace and reports.

## v0.7.0-beta.6 - 2026-06-29

- Keep import preview headers and actions visible while its content scrolls within the viewport.
- Reset modal scroll positions, lock background scrolling, restore focus, and support closing dialogs with Escape.
- Improve partial-import warning visibility and add a favicon to remove the browser 404.
- Reject AI-generated identity/demographic fields, unknown placeholders, and non-high-confidence mappings before import.

## v0.7.0-beta.5 - 2026-06-29

- Add a shared configurable FIFO queue for diagnosis, text structuring, and batch LM Studio calls.
- Show queue position to users and queue load/wait metrics on the admin dashboard.
- Limit concurrent and per-user requests to protect LM Studio under multi-user load.
- Reduce text-structuring chunk/output bounds and allow only one bounded retry after truncation.
- Return an explicitly warned partial preview when only part of a long note can be structured.

## v0.7.0-beta.4 - 2026-06-29

- Split long unstructured notes into bounded model requests and merge their results.
- Retry an output-truncated chunk at a smaller size before failing the operation.
- Detect conflicting values across chunks and require manual review.
- Show the estimated and completed chunk count in the text-preparation UI.

## v0.7.0-beta.3 - 2026-06-29

- Reject truncated or empty AI text-structuring responses.
- Bound corrected text and extracted mappings to keep structured output within the model budget.
- Add persistent progress, elapsed time, and actionable errors to the text preparation dialog.
- Store text-structuring finish reasons for operational diagnostics.

## v0.7.0-beta.2 - 2026-06-29

- Reject truncated LM Studio responses instead of presenting them as model abstentions.
- Preserve raw responses and token metrics for failed structured outputs.
- Limit structured CDS list sizes and raise the default output budget to 1536 tokens.
- Reclassify historical requests with `finish_reason=length` as errors.

## v0.7.0-beta.1 - 2026-06-29

- Added self-contained HTML export for model results with print layout.
- Added LM Studio model discovery, loading, activation, and optional unloading from the admin panel.
- Switched the local development profile to `medgemma-4b-it`.

## v0.6.0-beta.1 - 2026-06-29

- Added the administrative operations dashboard and system health metrics.
- Added persistent batch processing for saved cases.
- Added AI-assisted structuring of free clinical text with validation and manual diff.
- Added FHIR R4 and CDA R2/SEMD import and FHIR export.
- Added a threaded local WSGI server resistant to stalled connections.
- Added `install.sh` profiles for local LAN, Debian/Ubuntu VPS, and WSL2.
- Added CI checks and installer smoke testing.

This is a beta release and is not a certified medical device.
