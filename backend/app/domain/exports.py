"""One source of truth for export labels, file extensions and media types.

Labels must describe the file actually produced. The narrative report is Markdown; it is
never described as a Word or PDF document until an approved generator exists.
"""

from __future__ import annotations

EXPORT_FORMATS: dict[str, dict[str, str]] = {
    "excel": {
        "label": "Excel workbook (.xlsx)",
        "format": "xlsx",
        "extension": ".xlsx",
        "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    },
    "powerpoint": {
        "label": "PowerPoint briefing (.pptx)",
        "format": "pptx",
        "extension": ".pptx",
        "media_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    },
    "report": {
        "label": "Narrative report (Markdown .md)",
        "format": "md",
        "extension": ".md",
        "media_type": "text/markdown; charset=utf-8",
    },
}

UNAVAILABLE_EXPORT_FORMATS: dict[str, dict[str, str]] = {
    "word": {"label": "Word report (.docx)", "format": "docx"},
    "pdf": {"label": "PDF report (.pdf)", "format": "pdf"},
}


def export_label(export_type: str) -> str:
    return EXPORT_FORMATS.get(export_type, {}).get("label", export_type)


def export_media_type(extension: str) -> str:
    for spec in EXPORT_FORMATS.values():
        if spec["extension"] == extension:
            return spec["media_type"]
    return "application/octet-stream"
