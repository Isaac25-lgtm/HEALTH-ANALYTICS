"""PDF and Word reports written from a committed snapshot.

Both carry the same colour-coded content as the dashboard: headline indicators, the full
scorecard, the unit grid, performers, the trend and the evidence notes. The PDF also draws the
district map and the trend as vector graphics. No value is recalculated.
"""

from __future__ import annotations

import math
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, Polygon, String
from reportlab.graphics.widgets.markers import makeMarker
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.export_view import (
    INK,
    MUTED,
    NAVY,
    STATUS_FILL,
    STATUS_INK,
    ExportView,
    change_text,
    format_measure,
    interpretation_text,
    resolve_status,
    status_label,
    thresholds_text,
    trend_series,
)
from app.version import SOFTWARE_VERSION

LEGEND_STATUSES = ("green", "yellow", "red", "blue", "missing")


def _notes(view: ExportView, template_version: str) -> list[str]:
    lines = [
        f"All {len(view.indicators)} indicators in the snapshot are reported. Values come from calculation run "
        f"{view.run_id} (snapshot {view.snapshot_id}); nothing was recalculated.",
        "Colours follow each value's approved status. Missing values are shown as No data, never as zero.",
        "AI did not calculate any official number. Sensitive MPDSR identifiers and narratives are excluded.",
        f"Official MoH report templates are not yet supplied; this is the platform-default layout "
        f"({template_version}, software {SOFTWARE_VERSION}).",
    ]
    population = view.population
    if population.get("population"):
        lines.append(
            f"Population {population['population']:,} ({population.get('year')}) · "
            f"{population.get('source') or 'source not stated'} · {population.get('approval_status') or ''}".rstrip(
                " ·"
            )
        )
    elif population.get("reason"):
        lines.append(f"Population unavailable: {population['reason']}")
    return lines


# --------------------------------------------------------------------------------------- PDF


def _hex(value: str) -> colors.Color:
    return colors.HexColor(f"#{value}")


def _pdf_styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontSize=22, textColor=_hex(NAVY), alignment=TA_LEFT),
        "subtitle": ParagraphStyle("subtitle", parent=base["Normal"], fontSize=11, textColor=_hex(MUTED)),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontSize=14, textColor=_hex(NAVY), spaceBefore=10, spaceAfter=6
        ),
        "body": ParagraphStyle("body", parent=base["Normal"], fontSize=9.5, textColor=_hex(INK), leading=13),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontSize=8.5, textColor=_hex(INK), leading=10.5),
        "small": ParagraphStyle("small", parent=base["Normal"], fontSize=8, textColor=_hex(MUTED)),
    }


def _status_style(commands: list, column: int, row: int, status: str) -> None:
    commands.append(("BACKGROUND", (column, row), (column, row), _hex(STATUS_FILL.get(status, STATUS_FILL["n_a"]))))
    commands.append(("TEXTCOLOR", (column, row), (column, row), _hex(STATUS_INK.get(status, INK))))
    commands.append(("FONTNAME", (column, row), (column, row), "Helvetica-Bold"))


def _base_table_style() -> list:
    return [
        ("BACKGROUND", (0, 0), (-1, 0), _hex(NAVY)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.white),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, _hex("D5DEE8")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]


def _legend_table() -> Table:
    table = Table([[status_label(status) for status in LEGEND_STATUSES]], colWidths=[3.6 * cm] * 5)
    commands = [
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 1.5, colors.white),
    ]
    for index, status in enumerate(LEGEND_STATUSES):
        _status_style(commands, index, 0, status)
    table.setStyle(TableStyle(commands))
    table.hAlign = "LEFT"
    return table


def _kpi_table(view: ExportView, styles: dict) -> Table:
    """Six cards, three per row: name, large value, then status and change, each on its own line."""
    name_style = ParagraphStyle("kpi_name", parent=styles["cell"], fontSize=9.5, leading=12, textColor=_hex(NAVY))
    value_style = ParagraphStyle("kpi_value", parent=styles["cell"], fontSize=22, leading=27)
    note_style = ParagraphStyle("kpi_note", parent=styles["cell"], fontSize=8, leading=10)
    cells: list = []
    commands: list = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 4, colors.white),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
    ]
    row: list = []
    for index, indicator in enumerate(view.kpis[:6]):
        status = resolve_status(indicator)
        interpretation = interpretation_text(indicator)
        change = change_text(indicator) + (f" · {interpretation}" if interpretation else "")
        name = indicator.get("name") or indicator.get("indicator_code")
        row.append(
            [
                Paragraph(f"<b>{name}</b>", name_style),
                Paragraph(f"<b>{format_measure(indicator)}</b>", value_style),
                Paragraph(
                    f"<font color='#{STATUS_INK.get(status, INK)}'><b>{status_label(status)}</b></font>"
                    f"<font color='#{MUTED}'> · {change}</font>",
                    note_style,
                ),
            ]
        )
        position = (index % 3, index // 3)
        commands.append(("BACKGROUND", position, position, _hex(STATUS_FILL.get(status, "EEF3F7"))))
        if len(row) == 3:
            cells.append(row)
            row = []
    if row:
        cells.append(row + [""] * (3 - len(row)))
    table = Table(cells, colWidths=[8.8 * cm] * 3)
    table.setStyle(TableStyle(commands))
    return table


def _scorecard_table(view: ExportView, styles: dict) -> Table:
    comparison_head = f"Comparison ({view.comparison_label})" if view.comparison_label else "Comparison"
    rows = [["Indicator", "Value", "Status", comparison_head, "Change", "Approved bands"]]
    commands = _base_table_style()
    for index, indicator in enumerate(view.indicators, start=1):
        status = resolve_status(indicator)
        comparison = indicator.get("comparison") or {}
        rows.append(
            [
                Paragraph(f"<b>{indicator.get('name') or indicator.get('indicator_code')}</b>", styles["cell"]),
                format_measure(indicator),
                status_label(status),
                format_measure(comparison),
                change_text(indicator),
                Paragraph(thresholds_text(indicator) or "", styles["small"]),
            ]
        )
        _status_style(commands, 1, index, status)
        _status_style(commands, 2, index, status)
        if comparison.get("raw_value") is not None:
            _status_style(commands, 3, index, resolve_status(comparison))
    table = Table(rows, colWidths=[7.0 * cm, 2.4 * cm, 3.4 * cm, 3.6 * cm, 2.4 * cm, 7.8 * cm], repeatRows=1)
    table.setStyle(TableStyle(commands))
    return table


def _unit_table(view: ExportView, styles: dict) -> Table | None:
    if not view.units or not view.unit_columns:
        return None
    header = ["Unit"] + [
        Paragraph(
            f"<font color='white'><b>{column.get('name') or column.get('indicator_code')}</b></font>", styles["cell"]
        )
        for column in view.unit_columns
    ]
    rows = [header]
    commands = _base_table_style()
    for row_index, unit in enumerate(view.units, start=1):
        values = unit.get("values") or {}
        line = [unit.get("org_unit_name") or ""]
        for column_index, column in enumerate(view.unit_columns, start=1):
            measure = values.get(column.get("indicator_code"))
            line.append(format_measure(measure))
            _status_style(commands, column_index, row_index, resolve_status(measure))
        rows.append(line)
    width = (26.6 * cm - 5.4 * cm) / len(view.unit_columns)
    table = Table(rows, colWidths=[5.4 * cm] + [width] * len(view.unit_columns), repeatRows=1)
    table.setStyle(TableStyle(commands))
    return table


def _ranking_table(view: ExportView, styles: dict) -> list | None:
    """Best and needs-attention lists, stacked so they fit beside the map."""
    ranking = view.ranking
    if not ranking.get("ranking_allowed"):
        return None
    flowables: list = []
    for title, entries in (
        ("Best performing", ranking.get("best") or []),
        ("Needs attention", ranking.get("worst") or []),
    ):
        rows = [[title, "Value", "Status"]]
        commands = _base_table_style()
        for index, entry in enumerate(entries, start=1):
            status = resolve_status(entry)
            rows.append(
                [
                    entry.get("org_unit_name") or entry.get("org_unit_code") or "",
                    format_measure(entry),
                    status_label(status),
                ]
            )
            _status_style(commands, 1, index, status)
            _status_style(commands, 2, index, status)
        table = Table(rows, colWidths=[6.2 * cm, 2.6 * cm, 3.6 * cm])
        table.setStyle(TableStyle(commands))
        table.hAlign = "LEFT"
        flowables.extend([table, Spacer(1, 0.4 * cm)])
    return flowables


def _map_drawing(view: ExportView, width: float, height: float) -> Drawing | None:
    points = []
    for feature in view.map_features:
        for ring in _rings(feature.get("geometry") or {}):
            points.extend(point for point in ring if len(point) >= 2)
    if not points:
        return None
    lons = [point[0] for point in points]
    lats = [point[1] for point in points]
    factor = math.cos(math.radians((min(lats) + max(lats)) / 2))
    span_x = (max(lons) - min(lons)) * factor or 1
    span_y = (max(lats) - min(lats)) or 1
    scale = min(width / span_x, height / span_y)
    drawing = Drawing(width, height)
    for feature in view.map_features:
        status = resolve_status(feature.get("properties") or {})
        for ring in _rings(feature.get("geometry") or {}):
            flat: list[float] = []
            for point in ring:
                if len(point) >= 2:
                    flat.extend(((point[0] - min(lons)) * factor * scale, (point[1] - min(lats)) * scale))
            if len(flat) >= 6:
                drawing.add(
                    Polygon(
                        flat,
                        fillColor=_hex(STATUS_FILL.get(status, STATUS_FILL["missing"])),
                        strokeColor=colors.white,
                        strokeWidth=0.4,
                    )
                )
    return drawing


def _rings(geometry: dict) -> list[list]:
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if kind == "Polygon":
        return [coordinates[0]] if coordinates else []
    if kind == "MultiPolygon":
        return [polygon[0] for polygon in coordinates if polygon]
    return []


def _trend_drawing(view: ExportView) -> Drawing | None:
    series = trend_series(view)
    present = [(index, value) for index, (_label, value) in enumerate(series) if value is not None]
    if not present:
        return None
    drawing = Drawing(25 * cm, 7 * cm)
    plot = LinePlot()
    plot.x, plot.y, plot.width, plot.height = 1.5 * cm, 1.2 * cm, 22.5 * cm, 5.3 * cm
    plot.data = [present]
    plot.lines[0].strokeColor = _hex(NAVY)
    plot.lines[0].strokeWidth = 2
    plot.lines[0].symbol = makeMarker("FilledCircle", size=4, fillColor=_hex(NAVY))
    plot.xValueAxis.valueMin = 0
    plot.xValueAxis.valueMax = max(len(series) - 1, 1)
    plot.xValueAxis.valueSteps = list(range(len(series)))
    plot.xValueAxis.labelTextFormat = lambda value: series[int(value)][0] if 0 <= int(value) < len(series) else ""
    plot.xValueAxis.labels.fontSize = 7
    values = [value for _index, value in present]
    top = max(values) * 1.1 if max(values) > 0 else 1
    if (view.trend_indicator or {}).get("unit") == "%":
        top = max(top, 100)
    step = 10 ** math.floor(math.log10(top / 5)) if top > 0 else 1
    step = next(size * step for size in (1, 2, 2.5, 5, 10) if top / (size * step) <= 6)
    plot.yValueAxis.valueMin = min(0, *values)
    plot.yValueAxis.valueMax = math.ceil(top / step) * step
    plot.yValueAxis.valueStep = step
    plot.yValueAxis.visibleGrid = True
    plot.yValueAxis.gridStrokeColor = _hex("E2E8F0")
    plot.yValueAxis.gridStrokeWidth = 0.5
    plot.yValueAxis.labels.fontSize = 7
    if (view.trend_indicator or {}).get("unit") == "%":
        plot.yValueAxis.labelTextFormat = "%d%%"
    drawing.add(plot)
    drawing.add(String(1.5 * cm, 0.2 * cm, "Missing periods are gaps, never zero.", fontSize=7, fillColor=_hex(MUTED)))
    return drawing


def write_pdf(view: ExportView, destination: Path, template_version: str) -> None:
    styles = _pdf_styles()

    def decorate(canvas, document):
        canvas.saveState()
        canvas.setFillColor(_hex(NAVY))
        canvas.rect(0, document.pagesize[1] - 0.6 * cm, document.pagesize[0], 0.6 * cm, stroke=0, fill=1)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(_hex(MUTED))
        canvas.drawString(
            1.5 * cm,
            0.8 * cm,
            f"{view.scope_name} · {view.module_title} · {view.period_label} · run {view.run_id}",
        )
        canvas.drawRightString(document.pagesize[0] - 1.5 * cm, 0.8 * cm, f"Page {document.page}")
        canvas.restoreState()

    document = SimpleDocTemplate(
        str(destination),
        pagesize=landscape(A4),
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.3 * cm,
        bottomMargin=1.4 * cm,
        title=view.title,
        author="Health Performance Intelligence",
    )
    story: list = [
        Paragraph(view.title, styles["title"]),
        Paragraph(f"{view.subtitle} · generated {view.generated_at}", styles["subtitle"]),
        Spacer(1, 0.35 * cm),
        _legend_table(),
        Spacer(1, 0.35 * cm),
        Paragraph("Headline indicators", styles["h2"]),
        _kpi_table(view, styles),
    ]
    trend = _trend_drawing(view)
    if trend is not None:
        indicator = view.trend_indicator or {}
        story.append(KeepTogether([Paragraph(f"Trend · {indicator.get('name') or ''}", styles["h2"]), trend]))
    drawing = _map_drawing(view, 11 * cm, 11 * cm)
    ranking = _ranking_table(view, styles)
    if drawing is not None or ranking is not None:
        story.append(PageBreak())
        story.append(
            Paragraph(
                f"Geographic performance · {view.map_indicator_name or view.ranking_indicator_name}", styles["h2"]
            )
        )
        side = [[drawing or "", ranking or Paragraph("Ranking is not available.", styles["body"])]]
        layout = Table(side, colWidths=[13 * cm, 13.6 * cm])
        layout.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(layout)
        if view.map_note:
            story.append(Paragraph(view.map_note, styles["small"]))
    story.extend([PageBreak(), Paragraph("Verified scorecard", styles["h2"]), _scorecard_table(view, styles)])
    units = _unit_table(view, styles)
    if units is not None:
        story.extend([PageBreak(), Paragraph(f"{view.unit_label} scorecard", styles["h2"]), units])
    story.append(Paragraph("Data quality", styles["h2"]))
    if view.quality_flags:
        for flag in view.quality_flags:
            story.append(
                Paragraph(
                    f"<b>{flag.get('rule_id')}</b> ({flag.get('occurrences') or 1}): {flag.get('explanation')}",
                    styles["body"],
                )
            )
    else:
        story.append(Paragraph("No quality flags were attached to this run.", styles["body"]))
    story.append(Paragraph("Evidence notes", styles["h2"]))
    for line in _notes(view, template_version):
        story.append(Paragraph(f"• {line}", styles["body"]))
    document.build(story, onFirstPage=decorate, onLaterPages=decorate)


# -------------------------------------------------------------------------------------- Word


def _shade(cell, hex_fill: str) -> None:
    properties = cell._tc.get_or_add_tcPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:color"), "auto")
    shading.set(qn("w:fill"), hex_fill)
    properties.append(shading)


def _cell_text(cell, text: str, *, color: str = INK, bold: bool = False, size: float = 9, center: bool = False):
    cell.text = ""
    paragraph = cell.paragraphs[0]
    if center:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run(text)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = RGBColor.from_string(color)


def _word_table(document, header: list[str], rows: list[list[tuple[str, str | None]]], widths: list[float]):
    """rows: lists of (text, status or None). Status cells are shaded whole.

    Cells are written through the list each ``add_row`` returns; python-docx rebuilds the table grid
    on every ``row.cells`` access, which is quadratic on large unit tables.
    """
    table = document.add_table(rows=1, cols=len(header))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    table.autofit = False
    header_cells = table.rows[0].cells
    for index, label in enumerate(header):
        cell = header_cells[index]
        cell.width = Cm(widths[index])
        _shade(cell, NAVY)
        _cell_text(cell, label, color="FFFFFF", bold=True, center=index > 0)
    for values in rows:
        cells = table.add_row().cells
        for index, (text, status) in enumerate(values):
            cell = cells[index]
            cell.width = Cm(widths[index])
            if status:
                _shade(cell, STATUS_FILL.get(status, STATUS_FILL["n_a"]))
                _cell_text(cell, text, color=STATUS_INK.get(status, INK), bold=True, center=True)
            else:
                _cell_text(cell, text, bold=index == 0, center=index > 0)
    return table


def _heading(document, text: str, level: int = 1) -> None:
    heading = document.add_heading(text, level=level)
    for run in heading.runs:
        run.font.color.rgb = RGBColor.from_string(NAVY)


def write_docx(view: ExportView, destination: Path, template_version: str) -> None:
    document = Document()
    section = document.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = section.page_height, section.page_width
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, side, Cm(1.6))
    style = document.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)

    title = document.add_heading(view.title, level=0)
    for run in title.runs:
        run.font.color.rgb = RGBColor.from_string(NAVY)
    subtitle = document.add_paragraph(f"{view.subtitle} · generated {view.generated_at}")
    subtitle.runs[0].font.color.rgb = RGBColor.from_string(MUTED)
    legend = document.add_table(rows=1, cols=len(LEGEND_STATUSES))
    legend.alignment = WD_TABLE_ALIGNMENT.LEFT
    for index, status in enumerate(LEGEND_STATUSES):
        cell = legend.rows[0].cells[index]
        _shade(cell, STATUS_FILL[status])
        _cell_text(cell, status_label(status), color=STATUS_INK[status], bold=True, center=True)

    _heading(document, "Headline indicators")
    _word_table(
        document,
        ["Indicator", "Value", "Status", "Change"],
        [
            [
                (str(item.get("name") or item.get("indicator_code")), None),
                (format_measure(item), resolve_status(item)),
                (status_label(resolve_status(item)), resolve_status(item)),
                (
                    change_text(item) + (f" · {interpretation_text(item)}" if interpretation_text(item) else ""),
                    None,
                ),
            ]
            for item in view.kpis
        ],
        [9, 3.5, 4.5, 6],
    )

    _heading(document, "Verified scorecard")
    comparison_head = f"Comparison ({view.comparison_label})" if view.comparison_label else "Comparison"
    rows = []
    for item in view.indicators:
        status = resolve_status(item)
        comparison = item.get("comparison") or {}
        rows.append(
            [
                (str(item.get("name") or item.get("indicator_code")), None),
                (format_measure(item), status),
                (status_label(status), status),
                (
                    format_measure(comparison),
                    resolve_status(comparison) if comparison.get("raw_value") is not None else None,
                ),
                (change_text(item), None),
            ]
        )
    _word_table(document, ["Indicator", "Value", "Status", comparison_head, "Change"], rows, [9, 3, 4, 4.5, 3.5])

    ranking = view.ranking
    if ranking.get("ranking_allowed"):
        _heading(document, f"Top and bottom performers · {view.ranking_indicator_name}")
        best, worst = ranking.get("best") or [], ranking.get("worst") or []
        rows = []
        for index in range(max(len(best), len(worst))):
            left = best[index] if index < len(best) else None
            right = worst[index] if index < len(worst) else None
            rows.append(
                [
                    ((left or {}).get("org_unit_name") or "", None),
                    (format_measure(left) if left else "", resolve_status(left) if left else None),
                    ((right or {}).get("org_unit_name") or "", None),
                    (format_measure(right) if right else "", resolve_status(right) if right else None),
                ]
            )
        _word_table(document, ["Best performing", "Value", "Needs attention", "Value"], rows, [7.5, 3.5, 7.5, 3.5])

    series = trend_series(view)
    if series and any(value is not None for _label, value in series):
        indicator = view.trend_indicator or {}
        _heading(document, f"Trend · {indicator.get('name') or ''}")
        code = indicator.get("indicator_code")
        trend_rows = []
        for (label, _value), trend in zip(series, view.trends, strict=False):
            measure = (trend.get("values") or {}).get(code)
            trend_rows.append([(label, None), (format_measure(measure), resolve_status(measure))])
        _word_table(document, ["Period", "Value"], trend_rows, [5, 4])

    if view.units and view.unit_columns:
        _heading(document, f"{view.unit_label} scorecard")
        header = ["Unit"] + [str(column.get("name") or column.get("indicator_code")) for column in view.unit_columns]
        rows = []
        for unit in view.units:
            values = unit.get("values") or {}
            line = [(str(unit.get("org_unit_name") or ""), None)]
            for column in view.unit_columns:
                measure = values.get(column.get("indicator_code"))
                line.append((format_measure(measure), resolve_status(measure)))
            rows.append(line)
        width = 20 / len(view.unit_columns)
        _word_table(document, header, rows, [5.5] + [width] * len(view.unit_columns))

    _heading(document, "Data quality")
    if view.quality_flags:
        for flag in view.quality_flags:
            document.add_paragraph(
                f"{flag.get('rule_id')} ({flag.get('occurrences') or 1}): {flag.get('explanation')}",
                style="List Bullet",
            )
    else:
        document.add_paragraph("No quality flags were attached to this run.")
    _heading(document, "Evidence notes")
    for line in _notes(view, template_version):
        document.add_paragraph(line, style="List Bullet")
    if view.map_features:
        document.add_paragraph("The district map is included in the PDF and PowerPoint versions of this report.").runs[
            0
        ].font.color.rgb = RGBColor.from_string(MUTED)
    document.save(str(destination))
