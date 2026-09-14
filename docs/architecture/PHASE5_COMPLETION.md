# Phase 5 completion report

**Date:** 2026-09-12  
**Status:** Phase 5 AI Gateway and Ask the Data implemented. No AI provider or API key was invented.

## Delivered

| Surface | Contract |
|---|---|
| Evidence package | `app/services/evidence.py` builds a permission-filtered, redacted package from a verified dashboard calculation run. Identifying MPDSR keys and narratives are stripped. |
| AI Gateway | `POST /ai/findings`, `/ai/explain`, `/ai/ask`, `/ai/report`. Persists `AiRequest` with evidence hash, prompt version, fallback flag, and calculation run. |
| No-AI mode | Default. `AI_ENABLED` is false unless a key and base URL are also configured. Deterministic findings/explanations still work. |
| Provider path | Optional `POST {AI_BASE_URL}/v1/generate`. Provider text that contains numbers absent from the evidence package is discarded and the deterministic fallback is used. |
| UI | Dashboard **Ask the Data** panel calls the live APIs. It does not run on page load. |

## Gate

- AI sees verified evidence, not raw unvalidated calculations.
- Sensitive MPDSR identifiers are not present in the evidence package.
- Provider failure or disabled AI leaves dashboards and calculations intact.
- Outputs carry prompt version, evidence hash, and calculation run id.

## Not delivered (by design)

Approved production provider/model, data-processing agreement, and token budgets remain owner inputs. Official narrative templates are still pending.
