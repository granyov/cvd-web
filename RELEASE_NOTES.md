# CVD Web v0.9.8

Release focused on making the clinical workspace easier to scan and use during review.

## Highlights

- Reorganizes patient data into clinical groups: anamnesis/source data, objective status, laboratory tests, instrumental studies, and treatment/conclusion.
- Numbers every patient-data section and the section navigator.
- Keeps all patient-data sections collapsed by default when opening the workspace, loading a case, restoring a draft, or starting a new case.
- Moves the model response out of the narrow right panel into a larger working modal.
- Keeps the model-response modal focused on structured CDS output, expert review, HTML export, and technical JSON.
- Keeps the right panel for quick case checks and technical JSON, with numbered tabs.
- Updates the Umbrel package to use `ghcr.io/granyov/cvd-web:v0.9.8`.

## Install

```bash
./install.sh --target local
./install.sh --target wsl2 --unattended
sudo ./install.sh --target vps --domain cvd.example.com --unattended
```

For release-archive installs:

```bash
scripts/install_from_release.sh \
  --url https://github.com/granyov/cvd-web/releases/download/v0.9.8/cvd-web-v0.9.8.tar.gz \
  --sha256-url https://github.com/granyov/cvd-web/releases/download/v0.9.8/cvd-web-v0.9.8.tar.gz.sha256 \
  -- --target local --unattended
```

## Beta limitations

- Not a medical device and not clinically validated.
- Use only synthetic or deidentified data.
- The SQLite worker and in-process inference queue support one backend process.
- Production deployments must add HTTPS and should use external queue/rate-limit adapters before strict production readiness.
