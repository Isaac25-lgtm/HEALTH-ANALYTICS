"""One source of truth for export labels, file extensions and media types.

Labels must describe the file actually produced. The narrative report is Markdown; the PDF and
Word reports are separate, platform-default documents until official MoH templates are supplied.
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
    "pdf": {
        "label": "PDF report (.pdf)",
        "format": "pdf",
        "extension": ".pdf",
        "media_type": "application/pdf",
    },
    "word": {
        "label": "Word report (.docx)",
        "format": "docx",
        "extension": ".docx",
        "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    },
}


def export_label(export_type: str) -> str:
    return EXPORT_FORMATS.get(export_type, {}).get("label", export_type)


def export_media_type(extension: str) -> str:
    for spec in EXPORT_FORMATS.values():
        if spec["extension"] == extension:
            return spec["media_type"]
    return "application/octet-stream"
