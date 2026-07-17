# CVD Web v0.9.9

Release focused on everyday clinician UX and product hardening.

## Highlights

- Forces administrators signing in with a default password to set a new one before any other action; unattended installs with strong passwords are unaffected.
- Protects unsaved patient-form data: beforeunload warning, synchronous local draft flush, and an unsaved-changes indicator on the save button.
- Adds a recent-cases strip to the workspace for one-click resume of unfinished work.
- Notifies about finished background AI jobs with a toast, a tab-title badge, and a desktop notification when the tab is hidden.
- Shows adult reference ranges next to 30+ numeric fields and highlights out-of-range values while typing.
- Replaces raw AI failures with an actionable error card: cause, what to do next, and a retry button.
- Adds Ctrl/Cmd+S to save the case and Alt+N to jump to the first missing key field.
- Adds a one-click synthetic demo case for product evaluation, plus call-to-action empty states in the archive and admin dashboard.
- Fixes tablet layouts: no horizontal overflow at 768px on the workspace, archive, and admin pages.
- Splits the 4400-line `app.py` into domain handler mixins with a shared HTTP core (no behavior change) and adds WSGI-level smoke tests for the key user journeys.
- Updates the Umbrel package to use `ghcr.io/granyov/cvd-web:v0.9.9`.

## Install

```bash
./install.sh --target local
./install.sh --target wsl2 --unattended
sudo ./install.sh --target vps --domain cvd.example.com --unattended
```

For release-archive installs:

```bash
scripts/install_from_release.sh \
  --url https://github.com/granyov/cvd-web/releases/download/v0.9.9/cvd-web-v0.9.9.tar.gz \
  --sha256-url https://github.com/granyov/cvd-web/releases/download/v0.9.9/cvd-web-v0.9.9.tar.gz.sha256 \
  -- --target local --unattended
```

## Beta limitations

- Not a medical device and not clinically validated.
- Use only synthetic or deidentified data.
- The SQLite worker and in-process inference queue support one backend process.
- Production deployments must add HTTPS and should use external queue/rate-limit adapters before strict production readiness.
