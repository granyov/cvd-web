# CVD Web v0.9.14

Release focused on getting the conclusion out of the system and into a hospital record, and on telling the doctor the truth when an analysis fails.

## Highlights

- Adds "Копировать для МИС": a ready protocol block on the clipboard with the physician's diagnosis and ICD-10 codes, the AI draft with its own codes, the reasoning with red flags and missing data, the recommendation draft, and the disclaimer. Doctors move text between systems by copying, so this works today without any integration.
- Extends the FHIR R4 export so it carries the conclusion instead of only the questionnaire: DiagnosticReport with the AI conclusion and conclusionCode in `http://hl7.org/fhir/sid/icd-10`, ClinicalImpression with the reasoning, findings and red flags, CarePlan with `status=draft` and `intent=proposal` for recommendations, and Practitioner and Organization as performers.
- Marks the physician's own diagnosis as a Condition with `verificationStatus=confirmed`, so a receiving system can distinguish a confirmed diagnosis from an AI draft; the report is `preliminary` when the model abstained.
- Fixes the misleading error a doctor saw when a case exceeded the model context. LM Studio echoes the request body inside its error, so the failure matched the "json" branch and reported that the answer could not be structured and the request could be repeated — repeating always failed. The message now says the case does not fit the model context, that repeating will not help, and what to do; the retry button hides for this class of failure.
- Repairs the task centre layout, where the long error text consumed the actions column and squeezed job titles into a syllable-per-line column with the status badge overlapping the text.
- Stops leaking "LM Studio" into doctor-facing messages and caps raw fallback errors at 300 characters.

## Not included

A СЭМД CDA R2 export is deliberately absent: it requires the medical organisation and practitioner OIDs from the current РЭМД/НСИ registry. Those numbers must come from the clinic's own registration rather than be invented in code.

## Install

```bash
./install.sh --target local
./install.sh --target wsl2 --unattended
sudo ./install.sh --target vps --domain cvd.example.com --unattended
```

For release-archive installs:

```bash
scripts/install_from_release.sh \
  --url https://github.com/granyov/cvd-web/releases/download/v0.9.14/cvd-web-v0.9.14.tar.gz \
  --sha256-url https://github.com/granyov/cvd-web/releases/download/v0.9.14/cvd-web-v0.9.14.tar.gz.sha256 \
  -- --target local --unattended
```

## Beta limitations

- Not a medical device and not clinically validated.
- Use only synthetic or deidentified data.
- Exported documents are drafts: they are not signed with УКЭП and are not legally valid medical records.
- PDF intake reads the text layer only; scanned documents need OCR before import.
- The SQLite worker and in-process inference queue support one backend process.
- Production deployments must add HTTPS and should use external queue/rate-limit adapters before strict production readiness.
