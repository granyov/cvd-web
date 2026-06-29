# Changelog

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
