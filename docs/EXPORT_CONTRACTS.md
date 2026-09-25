# Export contracts

Publishing formats a committed analysis snapshot. It does not recalculate, re-aggregate or
re-classify, and it never invents missing values. Every format mirrors the dashboard: the same
status labels (On track, Needs attention, Off track, Non-assessable, No approved threshold,
No data), the same heat colours on whole cells, and values shown as the dashboard shows them
("92.4%", "1,204"). The presentation model is `app/services/export_view.py`.

## Shared context written into every file

- Authorised geography name, period and comparison period (readable labels, e.g. "Nov 2024 – Dec 2025")
- Module
- Calculation run id and snapshot id
- Template version (`hpip-publish-2`) and software version
- Note that official MoH branding and templates are pending (platform-default layout)

## Excel (`publishing_excel.py`)

Sheets: Scorecard, Units, Ranking, Trends, Calculations, Raw Data, Population, Methodology,
Data Quality, Metadata.

- Scorecard: title, legend, then Indicator, Value, Unit, Status, Comparison, Change,
  Interpretation, Approved bands, Numerator, Denominator. Value and status cells are filled with
  the status colour. Cells hold the exact stored value; number formats round for display only.
- Units: the unit grid shown on screen (districts and cities on national/regional views,
  facilities on district views), each value cell coloured by its own status.
- Ranking: best and needs-attention lists as ranked by the server's approved ordering rule.
- Trends: every indicator across the snapshot's trend periods, plus a native line chart for the
  selected indicator.
- Governance sheets keep their columns: governed evidence first, then the committed snapshot row,
  otherwise `Not recorded in the governed evidence`, never blank. Values above 100% are retained.

## PowerPoint (`publishing_pptx.py`)

16:9, native and editable, no embedded pictures: title slide, six headline KPI cards, the
scorecard (10 rows per slide, all indicators, value/status/comparison cells coloured), the
district map drawn as vector freeform shapes coloured by status with the best/needs-attention
lists, performer bar charts on a shared zero-based scale, the trend line chart, the unit grid
(16 rows per slide) and evidence notes stating the indicator count and run.

## PDF (`publishing_documents.write_pdf`)

A4 landscape: headline KPI cards and the trend chart, the vector district map with performer
tables, the full scorecard with approved bands, the unit grid, data quality and evidence notes.

## Word (`publishing_documents.write_docx`)

Landscape .docx with the same tables as the PDF, whole cells shaded by status. The map is in the
PDF and PowerPoint only.

## Narrative report

Markdown with executive summary, key results, population, data quality and limitations. It
states "Format: Markdown (.md). This is not a Word or PDF document."

## Map in exports

The export job reads the snapshot's map cohort (`map_feature_org_unit_ids`) with simplified
stored geometry and re-checks the export owner's access. Values come from the snapshot rows. A map
that cannot be produced is left out rather than failing the export.

## Labelling

Labels, formats, extensions and MIME types come from `app/domain/exports.py`:
`Excel workbook (.xlsx)`, `PowerPoint briefing (.pptx)`, `Narrative report (Markdown .md)`,
`PDF report (.pdf)`, `Word report (.docx)`.

## Permissions and download

`export` is required. Files are downloadable only by the user who created the job, through
`POST /exports/jobs/{job_id}/download` (CSRF-protected because each download writes an audit
record). The web client adds `?transport=blob`: the same bytes are sent as
`application/octet-stream` with the name in `X-Export-Filename` and no `Content-Disposition`,
because Chrome otherwise intercepts a `*.pdf` attachment and hands the page an empty body.
`export_mpdsr_linelist` remains blocked until disclosure governance is supplied.

## Rate limit

`EXPORT_RATE_LIMIT` requests per user per minute (default 30).
