# CVD Web v0.9.0

First beta release of the CVD clinical case workspace.

## Highlights

- Structured cardiovascular case workspace with validation and readiness checks.
- Local MedGemma/LM Studio integration with structured CDS output and audit history.
- Administrative dashboard, user management, reviews, imports, and system health.
- Persistent batch processing and AI-assisted preparation of unstructured text.
- JSON, FHIR R4, CDA R2/SEMD import workflows with manual conflict review.
- One installer for a home-network workstation, Debian/Ubuntu VPS, and WSL2.
- Cloud release helper for downloading a published archive, verifying SHA-256, and running local/WSL2/VPS installation from it.
- Fixed structured AI-result rendering in the clinical workspace.
- Empty clinical cases are rejected before an AI request is queued.
- AI results now show a clearer stale-result card with a field-level diff of case changes after analysis.
- Admins can compare model quality by Gold Set score, expert reviews, unsafe rate, latency, throughput, and per-case model results.
- Production reliability adds admin SQLite backup/download/restore, external queue readiness settings, and richer LM Studio monitoring.
- Clinical-validation runs preserve per-case Gold Set evaluations for repeatable release checks.
- The expert-review cockpit surfaces low-scoring, unsafe, and unevaluated cases for follow-up.

## Install

```bash
./install.sh --target local
sudo ./install.sh --target vps --domain cvd.example.com
./install.sh --target wsl2
```

The installer prints the generated administrator password once. VPS deployments must add HTTPS before real use.

## Beta limitations

- Not a medical device and not clinically validated.
- Use only synthetic or deidentified data.
- The SQLite batch worker supports one application process.
- WSL2 access from other LAN devices requires Windows port forwarding and a firewall rule printed by the installer.
