# CVD Web v0.6.0-beta.1

First beta release of the CVD clinical case workspace.

## Highlights

- Structured cardiovascular case workspace with validation and readiness checks.
- Local MedGemma/LM Studio integration with structured CDS output and audit history.
- Administrative dashboard, user management, reviews, imports, and system health.
- Persistent batch processing and AI-assisted preparation of unstructured text.
- JSON, FHIR R4, CDA R2/SEMD import workflows with manual conflict review.
- One installer for a home-network workstation, Debian/Ubuntu VPS, and WSL2.

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
