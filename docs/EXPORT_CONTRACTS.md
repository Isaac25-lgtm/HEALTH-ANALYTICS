# Export contracts

Publishing formats a calculation run. It does not recalculate with a different formula or invent missing values.

## Shared context written into every file

- Authorised geography name/code
- Period and comparison period
- Module
- Calculation run id
- Template version (`hpip-publish-1`)
- Software version
- Note that official MoH branding is pending

## Excel

Sheets: Scorecard, Calculations, Raw Data, Population, Methodology, Data Quality, Metadata.

Scorecard status uses the same green/yellow/red/blue/n_a fills as the dashboard. Values above 100% are retained. Missing is not written as zero.

## PowerPoint

Platform-default editable slides (title, scorecard table, evidence notes). Tables are native PPTX tables. Official national/regional/district/facility/MPDSR slide families are not supplied.

## Narrative report

Markdown with executive summary, key results, population, data quality, and limitations. Official Word/PDF templates are not supplied.

## Completeness and labelling (amendment 2026-09-13)

- Labels, formats, extensions and MIME types come from `app/domain/exports.py`: `Excel workbook (.xlsx)`, `PowerPoint briefing (.pptx)`, `Narrative report (Markdown .md)`. The report states "Format: Markdown (.md). This is not a Word or PDF document." Word and PDF actions are listed as unavailable and unimplemented.
- Excel governance columns (formula version, thresholds, change interpretation, mapping version, source freshness, aggregation scope) are filled from governed evidence, then the committed snapshot row, and otherwise say `Not recorded in the governed evidence` — never blank. Data Quality rows show grouped occurrences.
- PowerPoint paginates every indicator (8 rows per slide) with Unit and Status columns and a module-aware title; the notes slide states the indicator count. Nothing is silently truncated.

## Permissions

`export` is required. Files are downloadable only by the user who created the job, through `POST /exports/jobs/{job_id}/download` (CSRF-protected because each download writes an audit record). `export_mpdsr_linelist` remains blocked until disclosure governance is supplied.

## Rate limit

`EXPORT_RATE_LIMIT` requests per user per minute (default 30).
