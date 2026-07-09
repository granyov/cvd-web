# Security Policy

## Beta status

CVD Web `v0.9.x` is intended for development, synthetic data, and controlled evaluation. It is not validated for processing identifiable patient data or making clinical decisions.

## Deployment requirements

- Do not expose port `8080` directly to the public Internet.
- On a VPS, use a reverse proxy with HTTPS and restrict LM Studio access to a VPN or private network.
- Set `CVD_ENV=production`, `CVD_COOKIE_SECURE=1`, `CVD_ADMIN_EMAIL`, and a strong unique `CVD_ADMIN_PASSWORD` before the first production start. Production bootstrap refuses the default administrator password.
- Use `/healthz` for process liveness and `/readyz` for readiness checks that include SQLite integrity, required directories, and production security posture.
- Use `/api/admin/security-audit` from the admin UI before exposing a VPS. Treat critical findings as release blockers.
- Run production behind a dedicated WSGI server via `cvd_web.wsgi:application`; the built-in stdlib server is for local development and controlled evaluation.
- Treat the in-process LM Studio queue and in-memory rate limiter as non-production components. Production readiness remains blocked until external queue/rate-limit adapters are deployed.
- Protect `.env` and SQLite backups.
- Keep the application single-process while the built-in SQLite batch worker is in use.
- Define retention, access-control, backup, and incident-response policies before any clinical pilot.

## VPS checklist

- Confirm `CVD_ENV=production`, `CVD_COOKIE_SECURE=1`, a non-default `CVD_ADMIN_EMAIL`, and a strong admin password before first start.
- Put nginx/Caddy/Cloudflare in front of the app; do not publish the Python listener directly.
- Keep LM Studio behind Cloudflare Access, VPN, or a private network; configure `CF-Access-Client-Id`, `CF-Access-Client-Secret`, and any required tunnel `User-Agent` in AI Gateway headers.
- Run `python3 -m cvd_web migrate --check` before deployment and `python3 -m cvd_web migrate` during rollout; the migration command creates a pre-migration SQLite backup by default.
- Create and restore-test SQLite backups before clinical pilots.
- Review `/readyz`, `/api/admin/security-audit`, and the admin audit log after every settings change.
- Do not paste secrets into issues, release notes, screenshots, or support messages. Settings audit entries mask header values, DSNs, tokens, passwords, and prompt contents.

## Reporting

Report vulnerabilities privately through GitHub Security Advisories for this repository. Do not include patient data, credentials, or production logs in an issue.
