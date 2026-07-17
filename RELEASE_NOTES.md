# CVD Web v0.9.7

Release focused on persistent AI jobs for free-text preparation and diagnosis workflow reliability.

## Highlights

- Moves `Подготовить текст с AI` to a persistent background job so processing continues after closing the modal, tab, or browser.
- Adds a combined workspace job line showing active and recently finished text-preparation and diagnosis jobs.
- Preserves FIFO ordering across diagnosis and text-preparation jobs on the backend worker.
- Lets users reopen finished text-preparation results and diagnosis results from the workspace job line.
- Restores interrupted text-preparation jobs to the queue after an application restart.
- Applies one per-user AI job limit across diagnosis and text-preparation jobs.
- Keeps the full source text only while the worker still needs it, then leaves a short preview, hash, metrics, and the prepared result.
- Updates the Umbrel package to use `ghcr.io/granyov/cvd-web:v0.9.7`.

## Install

```bash
./install.sh --target local
./install.sh --target wsl2 --unattended
sudo ./install.sh --target vps --domain cvd.example.com --unattended
```

For release-archive installs:

```bash
scripts/install_from_release.sh \
  --url https://github.com/granyov/cvd-web/releases/download/v0.9.7/cvd-web-v0.9.7.tar.gz \
  --sha256-url https://github.com/granyov/cvd-web/releases/download/v0.9.7/cvd-web-v0.9.7.tar.gz.sha256 \
  -- --target local --unattended
```

## Beta limitations

- Not a medical device and not clinically validated.
- Use only synthetic or deidentified data.
- The SQLite worker and in-process inference queue support one backend process.
- Production deployments must add HTTPS and should use external queue/rate-limit adapters before strict production readiness.
