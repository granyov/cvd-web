# CVD Web v0.9.12

Release focused on daily case triage: the system now starts from a shift worklist, keeps AI work visible across browser sessions, and makes recognized text import easier to review clinically.

## Highlights

- Starts authenticated users on the case archive, which now acts as the daily worklist.
- Adds backend-computed workflow stages for new cases, cases in work, AI waiting, review-needed, completed, and archive views.
- Adds a shift worklist with per-stage counts and next actions on case cards.
- Shows case owner, active AI task state, and review state in case lists and details.
- Shows global AI queue position across users, including who launched a task and which case/patient it belongs to.
- Allows queued diagnosis and text-preparation AI jobs to be cancelled before execution.
- Adds clearer model-facing errors for Cloudflare 524, cloudflared tunnel issues, timeouts, JSON/schema parse failures, connection failures, and resource pressure.
- Groups recognized free-text facts by clinical workflow before import: anamnesis, lab tests, instrumental tests, objective status, treatment, and diagnosis.
- Adds timeline events for creation, updates, and physician review.
- Updates the Umbrel package to use `ghcr.io/granyov/cvd-web:v0.9.12`.

## Install

```bash
./install.sh --target local
./install.sh --target wsl2 --unattended
sudo ./install.sh --target vps --domain cvd.example.com --unattended
```

For release-archive installs:

```bash
scripts/install_from_release.sh \
  --url https://github.com/granyov/cvd-web/releases/download/v0.9.12/cvd-web-v0.9.12.tar.gz \
  --sha256-url https://github.com/granyov/cvd-web/releases/download/v0.9.12/cvd-web-v0.9.12.tar.gz.sha256 \
  -- --target local --unattended
```

## Beta limitations

- Not a medical device and not clinically validated.
- Use only synthetic or deidentified data.
- PDF intake reads the text layer only; scanned documents need OCR before import.
- The SQLite worker and in-process inference queue support one backend process.
- Production deployments must add HTTPS and should use external queue/rate-limit adapters before strict production readiness.
