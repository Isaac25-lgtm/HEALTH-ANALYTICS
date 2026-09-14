# Phase 6 completion report

**Date:** 2026-09-12  
**Status:** Phase 6 publishing engines generate Excel, PowerPoint, and narrative reports from calculation runs.

## Delivered

| Output | Endpoint | Notes |
|---|---|---|
| Excel | `POST /exports/excel` | Scorecard, Calculations, Raw Data, Population, Methodology, Data Quality, Metadata. RAG/BLUE fills match dashboard status. Values are not capped. |
| PowerPoint | `POST /exports/powerpoint` | Editable text and table objects. Platform-default template family, labelled as such. Official MoH slides are not supplied. |
| Narrative report | `POST /exports/report` | Markdown, run-linked. Word/PDF official templates remain pending. |
| Download | `GET /exports/jobs/{id}` and `/file` | Owner-scoped. |
| MPDSR line list | `POST /exports/mpdsr-linelist` | Still blocked pending disclosure governance. |

Dashboard export actions are live when the user has `export`. Files embed period, module, scope, template version, software version, and calculation run id.

## Gate

- Workbook/slide/report values match the dashboard calculation for the same inputs.
- Current-view metadata is written into the file.
- PPTX objects remain editable; generation does not flatten slides to images.
- AI does not design workbook structure.

## Not delivered (by design)

Official MoH logo, branded Excel/PPTX/Word templates, and export retention policy remain owner inputs.
