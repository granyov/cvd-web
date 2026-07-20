# CVD Web v0.9.15

Release built from running the whole clinician path against a live MedGemma endpoint instead of mocks. Two of the findings were data-loss and safety defects that no synthetic test had surfaced.

## Highlights

- Fixes silent data loss in text structuring. A real EMIAS consultation protocol returned exactly fourteen fields, and everything after them was dropped: NT-proBNP, creatinine, eGFR, potassium, haemoglobin, SpO2, respiratory rate and all five medications sat at the end of the note. The ceiling is now thirty facts per chunk, the prompt asks explicitly for laboratory values and current therapy at the end of a note, and the same protocol yields 27 fields.
- Refuses to accept an abstention as a diagnosis. When the model abstains it still fills a placeholder conclusion and ICD-10 codes; the result window used to offer "Принять в черновик" as the primary action next to those codes, so one click could write a non-diagnosis into the physician's own conclusion. Abstentions now disable the action with an explanation and hide the codes.
- Removes the diagnosis triplication found on live output: the comparison panel, the "МКБ-10: ..." tail the prompt asks the model to append, and a separate leading-diagnosis block with different wording. The trailing code list is stripped wherever codes already render as chips or a separate line, in the UI, the printable report and the MIS text.
- Collapses the result actions from six buttons across two rows into one row with an overflow menu, and drops the metric tiles that repeated the lists below.
- Restores the ICD-10 comparison when a result is opened from history: it previously read codes from a form field that only a fresh run fills.

## Verified against a live model

MedGemma 27B (q4_k_s) over an OpenAI-compatible endpoint: full case analysis (48 s, 3464+1126 tokens, 23.5 tok/s), prompt v5 filling both the CDS reasoning and the treatment/rehabilitation drafts, protocol structuring, abstention on thin data, queued-job cancellation, and a two-case batch run.

## Install

```bash
./install.sh --target local
./install.sh --target wsl2 --unattended
sudo ./install.sh --target vps --domain cvd.example.com --unattended
```

For release-archive installs:

```bash
scripts/install_from_release.sh \
  --url https://github.com/granyov/cvd-web/releases/download/v0.9.15/cvd-web-v0.9.15.tar.gz \
  --sha256-url https://github.com/granyov/cvd-web/releases/download/v0.9.15/cvd-web-v0.9.15.tar.gz.sha256 \
  -- --target local --unattended
```

## Beta limitations

- Not a medical device and not clinically validated.
- Use only synthetic or deidentified data.
- Exported documents are drafts: they are not signed with УКЭП and are not legally valid medical records.
- PDF intake reads the text layer only; scanned documents need OCR before import.
- The SQLite worker and in-process inference queue support one backend process.
- Production deployments must add HTTPS and should use external queue/rate-limit adapters before strict production readiness.
