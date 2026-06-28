# Security Policy

## Beta status

CVD Web `v0.6.0-beta.1` is intended for development, synthetic data, and controlled evaluation. It is not validated for processing identifiable patient data or making clinical decisions.

## Deployment requirements

- Do not expose port `8080` directly to the public Internet.
- On a VPS, use a reverse proxy with HTTPS and restrict LM Studio access to a VPN or private network.
- Replace the initial administrator password immediately and protect `.env` and SQLite backups.
- Keep the application single-process while the built-in SQLite batch worker is in use.
- Define retention, access-control, backup, and incident-response policies before any clinical pilot.

## Reporting

Report vulnerabilities privately through GitHub Security Advisories for this repository. Do not include patient data, credentials, or production logs in an issue.
