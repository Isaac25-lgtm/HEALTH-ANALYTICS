# AI governance

AI interprets verified, permission-filtered evidence. It never calculates official indicator values, chooses RAG/BLUE, invents denominators, or expands access.

## Allowed tasks

- Key findings
- Explain an indicator already in the evidence package
- Ask the Data (bounded questions)
- Management brief / report narrative (`generate_ai_report`)

## Evidence package

Built from the current dashboard calculation run. Includes scope codes/names, period, module, run id, indicator values, quality flags, and redacted MPDSR aggregates. Identifying keys (`event_uid`, names, narratives, clinician identifiers) are removed before any provider call.

## Provider policy

- Disabled unless `AI_ENABLED=true` and both `AI_API_KEY` and `AI_BASE_URL` are set.
- Optional HTTP contract: `POST {AI_BASE_URL}/v1/generate`.
- Provider text that contains numbers not present in the evidence package is rejected.
- Blame/causation questions are answered as unsupported.
- Failures fall back to the deterministic interpreter. Dashboards do not depend on a provider.

## Language safety and schema (amendment 2026-09-13)

- `BLAME_CAUSATION_PATTERNS` detects negligence/negligent, blame/blamed, preventable death(s), caused by staff/facility, staff failure, facility failure, poor care caused, responsible for death, who caused, at fault, malpractice and disciplinary demands. Such questions are refused (`unsafe_causal_or_blame_question`) without calling a provider, and the refusal text itself contains none of those phrases.
- The provider request carries `response_schema` `hpip.statements.v1`: statements with `text`, `kind` (`observation`, `association`, `data_quality`, `insufficient_evidence`, `recommendation`) and `evidence_refs` naming indicator codes in the package. Invalid schema, unknown or missing references, blame/causation wording and unsupported numbers fall back to the deterministic answer with a recorded error code.
- Deterministic findings are direction-aware: they follow `change.interpretation`, report BLUE and missing values as data-quality findings, and never call an unclassified change an improvement.
- AI always consumes the displayed snapshot. Snapshot ownership and the snapshot's own programme are re-checked, so omitting `module` cannot widen access. An evidence package above `AI_MAX_EVIDENCE_CHARS` skips the provider (`evidence_exceeds_provider_limit`) and uses the local deterministic answer.

## Persistence

`ai_requests` stores task, prompt version, evidence hash, calculation run, fallback flag, and a minimal response summary. Raw MPDSR line lists are not stored on the request.

## Open owner decisions

Approved provider/model, data-processing agreement, retention of prompts, cost caps, and any local-model sensitivity tier. See `docs/project-context/OPEN_ITEMS.md`.
