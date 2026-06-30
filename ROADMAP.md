# CVD Web roadmap

## v0.8 product-quality work plan

1. **AI Gateway profiles and diagnostics**
   - local same-host LM Studio (`127.0.0.1`), WSL2/Windows host, LAN endpoint, and cloudflared tunnel profiles.
   - Optional auth header support for Cloudflare Access/service-token protected tunnels.
   - Admin diagnostics for model catalog, selected/loaded model, latency, model count, and auth-header status.

2. **Result Center**
   - Dedicated result workspace with filters for status, model, prompt version, red flags, abstain, and review state.
   - Quick actions for HTML report, expert review, rerun, and export.

3. **Model Compare**
   - Run the same case through two model/prompt profiles.
   - Compare summary, diagnoses, ICD-10, missing data, red flags, latency, tokens, and expert ratings.

4. **Text-to-structured quality upgrade**
   - Side-by-side source text and extracted facts.
   - Confidence, source snippets, stronger medication dictionary, and stricter auto-select rules.

5. **Validation / Gold Set**
   - Gold cases with expected diagnoses, ICD-10 codes, red flags, and expected abstain behavior.
   - Batch validation metrics for model/prompt versions.
