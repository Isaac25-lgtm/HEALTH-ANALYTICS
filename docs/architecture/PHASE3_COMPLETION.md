# Phase 3 completion report

**Date:** 2026-09-12  
**Status:** Phase 3 MNCH analytical modules passed the automated gate. Phase 5 was not started.

> **Superseded route (2026-09-13 amendment §1):** the module GET routes below created calculation runs and were removed. Use `POST /analytics/modules/{module}/query` (CSRF-protected). See `API_AUTH.md`. This report is kept as a historical record and is not an acceptance statement.

## Delivered modules

All four modules use the shared mapping, period, population, calculation, classification, provenance, quality, and authorisation engines. Formulas remain in `backend/app/domain/indicator_catalog.py`, not in frontend components.

| Module | API | Programme | Canonical indicators |
|---|---|---|---|
| ANC | `GET /analytics/modules/anc` | MNCH | ANC1, first-trimester, ANC4, ANC8, IPT3, Hb testing, IFA ≥30, obstetric ultrasound, teenage pregnancy |
| Intrapartum/newborn | `GET /analytics/modules/intrapartum` | MNCH | Institutional delivery, C-section, direct-only KMC, successful resuscitation, PMR, fresh stillbirth rate, MMR |
| Immunisation/child health | `GET /analytics/modules/immunization` | EPI | Canonical coverage catalogue plus Penta1–Penta3 and MV1–MV4 dropout |
| MPDSR | `GET /analytics/modules/mpdsr` | MPDSR | Perinatal and maternal reported/notified/reviewed counts, coverage, and timeliness |

Shared module contract (`evaluate_module`) returns current-period results, comparison-period results, percentage-point versus relative change, trends, authorised child-unit comparison, numerator/denominator evidence, freshness, RAG/BLUE or unclassified state, exact units, quality flags, and calculation-run lineage.

## Required behaviours verified

- Population-derived ANC uses the approved year-aware denominator and 5% coefficient; period scaling applies only to population denominators.
- Missing population disables only population-derived indicators; service-derived values remain.
- Teenage pregnancy is inverse and requires registered age components.
- IFA values above 100% are retained and flagged; they are not capped.
- Institutional delivery uses 4.85%; C-section uses the desired-range bands; KMC remains direct-only; resuscitation >100% is BLUE.
- PMR and fresh stillbirth remain rates per 1,000; MMR remains per 100,000 live births.
- EPI dropout is `(Dose1 − FinalDose) / Dose1 × 100`, inverse, and unclassified until approved bands exist.
- MPDSR keeps perinatal and maternal streams visible together; event UIDs are not returned on the ordinary module payload; MNCH-only users receive 403.

Appendix T-style fixtures in `backend/tests/test_phase3_modules.py` are synthetic labelled fixtures, not production Acholi values.

## Gate evidence

Included in the 2026-09-12 full backend suite: **171 passed, 0 skipped** when the disposable PostgreSQL 18 verifier was available. Ruff was clean over `app`, `tests`, `alembic`, and `scripts`.
