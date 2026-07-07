# CVD Web v0.9.3

Release focused on deployability, controlled VPS/WSL2 operation, AI Gateway diagnostics, and a calmer clinical workspace UI.

## Highlights

- Adds a reproducible release archive builder with SHA-256 checksum output.
- Adds installer support for local, WSL2, and Debian/Ubuntu VPS targets, including generated environment files and service setup.
- Adds WSL2 guidance for Windows localhost access and optional LAN port forwarding.
- Adds VPS-oriented defaults for controlled evaluation before HTTPS production hardening.
- Adds `/readyz` runtime checks for database, templates, static assets, security posture, and production queue readiness.
- Adds a WSGI entrypoint for production runners behind reverse proxies.
- Improves the clinical workspace by removing duplicated metrics, duplicated next-action guidance, and repeated workflow/progress panels.
- Fixes mobile layout ordering so the patient form appears before the review sidebar on narrow screens.
- Extends model quality validation with severity and expected missing-data checks in the Gold Set workflow.
- Fixes SQLite backup/restore connection cleanup.

## Install

```bash
./install.sh --target local
./install.sh --target wsl2 --unattended
sudo ./install.sh --target vps --domain cvd.example.com --unattended
```

For release-archive installs:

```bash
scripts/install_from_release.sh \
  --url https://github.com/granyov/cvd-web/releases/download/v0.9.3/cvd-web-v0.9.3.tar.gz \
  --sha256-url https://github.com/granyov/cvd-web/releases/download/v0.9.3/cvd-web-v0.9.3.tar.gz.sha256 \
  -- --target local --unattended
```

## Beta limitations

- Not a medical device and not clinically validated.
- Use only synthetic or deidentified data.
- The SQLite batch worker and in-process inference queue support one backend process.
- Production deployments must add HTTPS and should use external queue/rate-limit adapters before strict production readiness.
