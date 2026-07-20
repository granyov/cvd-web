# CVD Web v0.9.16

Release focused on what happens when a case does not fit the model, and on making the version stamped in history match the prompt that actually ran.

## Highlights

- Refuses an oversized case in milliseconds instead of after about forty seconds of queueing and generation. The admin health check records the real context length of the loaded model, and the size check runs before the job is queued.
- Shows the case size in tokens in the review window, replacing an opaque JSON character count, with an explicit warning and a disabled confirm button when the case will not fit.
- Re-reads the model context from LM Studio before refusing anything, so a stale stored value cannot block work after the model is reloaded with a larger context. When that check cannot be made, the job goes through and the doctor sees the genuine service error rather than an invented size limit.
- Fixes the prompt version recorded in history. Migration 0014 replaced the stored template but left `active_prompt_version` at v4, and the setting is seeded with INSERT OR IGNORE, so every existing database saved prompt v5 runs under the v4 label. The model-quality dashboard would have compared prompt versions against fiction. Migration 0015 lifts the version only when the template is already the current default and the version is a known previous default; a clinic's own version string is untouched.
- Repairs the Gold Set summary, which showed "Средний score 50% / Threshold 80%" with the threshold field named as if it were the worst observed score. The summary now carries the real worst case next to the threshold, and the remaining English labels in that panel are in Russian.

## Recommended model setup

Load the model in LM Studio with at least **32768 tokens** of context. A typical case with history, ECG, echo and imaging descriptions takes 3-15 thousand tokens, and `lm_studio_max_tokens` is reserved on top for the answer. At 8192 tokens only about 4000 remain for data, and larger cases do not fit.

## Install

```bash
./install.sh --target local
./install.sh --target wsl2 --unattended
sudo ./install.sh --target vps --domain cvd.example.com --unattended
```

For release-archive installs:

```bash
scripts/install_from_release.sh \
  --url https://github.com/granyov/cvd-web/releases/download/v0.9.16/cvd-web-v0.9.16.tar.gz \
  --sha256-url https://github.com/granyov/cvd-web/releases/download/v0.9.16/cvd-web-v0.9.16.tar.gz.sha256 \
  -- --target local --unattended
```

## Beta limitations

- Not a medical device and not clinically validated.
- Use only synthetic or deidentified data.
- Exported documents are drafts: they are not signed with УКЭП and are not legally valid medical records.
- The token estimate used for the size check is approximate; only the model tokenizer knows the exact count.
- PDF intake reads the text layer only; scanned documents need OCR before import.
- The SQLite worker and in-process inference queue support one backend process.
- Production deployments must add HTTPS and should use external queue/rate-limit adapters before strict production readiness.
