# Changelog

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
