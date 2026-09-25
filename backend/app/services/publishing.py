from __future__ import annotations

from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.enums import JobStatus
from app.models import ExportJob
from app.services.authorization import AuthorizationError
from app.services.export_view import MODULE_TITLES, build_export_view
from app.services.publishing_documents import write_docx, write_pdf
from app.services.publishing_excel import NOT_RECORDED, write_excel
from app.services.publishing_pptx import write_pptx
from app.version import SOFTWARE_VERSION

TEMPLATE_VERSION = "hpip-publish-2"
# Map features for the snapshot's map cohort, added to the writer's copy of the snapshot payload by
# the export job (they are read from stored geometry, never recalculated).
MAP_FEATURES_KEY = "_export_map_features"

__all__ = ["NOT_RECORDED", "TEMPLATE_VERSION", "export_output_dir", "write_artifact"]


def export_output_dir() -> Path:
    path = Path(get_settings().export_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _view(dashboard: dict, package: dict):
    return build_export_view(dashboard, package, dashboard.get(MAP_FEATURES_KEY))


def _write_excel(dashboard: dict, package: dict, destination: Path) -> None:
    write_excel(_view(dashboard, package), dashboard, package, destination, TEMPLATE_VERSION)


def _write_pptx(dashboard: dict, package: dict, destination: Path) -> None:
    write_pptx(_view(dashboard, package), destination, TEMPLATE_VERSION)


def _write_pdf(dashboard: dict, package: dict, destination: Path) -> None:
    write_pdf(_view(dashboard, package), destination, TEMPLATE_VERSION)


def _write_word(dashboard: dict, package: dict, destination: Path) -> None:
    write_docx(_view(dashboard, package), destination, TEMPLATE_VERSION)


def _write_report(_dashboard: dict, package: dict, destination: Path) -> None:
    module_title = MODULE_TITLES.get(str(package.get("module")), str(package.get("module")))
    population = package.get("population") or {}
    lines = [
        f"# {module_title} narrative report — {package['scope'].get('org_unit_name')}",
        "",
        "Format: Markdown (.md). This is not a Word or PDF document.",
        "",
        f"Period: {package.get('period')}",
        f"Comparison: {package.get('comparison_period')}",
        f"Module: {package.get('module')}",
        f"Calculation run: {package.get('current_run_id')}",
        f"Software: {SOFTWARE_VERSION}",
        f"Template: {TEMPLATE_VERSION}",
        "",
        "## Executive summary",
        "This report uses only verified calculation-run values. AI did not calculate official numbers.",
        f"Snapshot: {package.get('analysis_snapshot_id') or _dashboard.get('analysis_snapshot_id')}",
        f"View hash: {package.get('view_hash') or _dashboard.get('view_hash')}",
        "",
        "## Key performance results",
    ]
    for row in package["indicators"]:
        reason = f"; {row.get('reason_code')}" if row.get("reason_code") else ""
        lines.append(
            f"- {row.get('name') or row.get('indicator_code')}: {row.get('display_value') or 'No data'} "
            f"{row.get('unit') or ''} ({row.get('status')}{reason})"
        )
    lines.extend(
        [
            "",
            "## Population",
            f"- Status: {population.get('status')}",
            f"- Year: {population.get('year')}",
            f"- Value: {population.get('population')}",
            f"- Source: {population.get('source')}",
            f"- Version: {population.get('version_code')}",
            f"- Reason: {population.get('reason')}",
            "",
            "## Data quality",
        ]
    )
    for flag in package.get("quality_flags") or []:
        lines.append(
            f"- {flag.get('rule_id')} ({flag.get('occurrences') or 1} occurrence(s)): {flag.get('explanation')}"
        )
    if not package.get("quality_flags"):
        lines.append("- No quality flags were attached to this run.")
    lines.extend(
        [
            "",
            "## Comparisons and contributors",
            "Child comparisons and contribution rows come from the persisted snapshot.",
            "No causal inference is added.",
            "",
            "## Methodology",
            f"Formula catalogue and template {TEMPLATE_VERSION}.",
            "Population and mapping versions are those stored on the snapshot.",
            "",
            "## Limitations",
            "Sensitive MPDSR identifiers and narratives are excluded. Official branding templates remain pending.",
            "",
            "## Recommendations",
            "Only verified snapshot findings are restated. None are invented.",
        ]
    )
    destination.write_text("\n".join(lines), encoding="utf-8")


ARTIFACT_WRITERS = {
    "excel": _write_excel,
    "powerpoint": _write_pptx,
    "report": _write_report,
    "pdf": _write_pdf,
    "word": _write_word,
}


def write_artifact(export_type: str, dashboard: dict, package: dict, destination: Path) -> None:
    """Write one export from committed snapshot content. Never recalculates."""
    writer = ARTIFACT_WRITERS.get(export_type)
    if writer is None:
        raise ValueError("Unsupported export type.")
    writer(dashboard, package, destination)


def generate_export_artifact(session: Session, job_id: UUID) -> ExportJob:
    """Run one claimed generation attempt in ``session`` (worker semantics, no automatic retry).

    Kept for callers that process a queued job synchronously. The attempt uses the same claim,
    temporary-file and durable-failure path as the Celery worker.
    """
    from app.services.export_jobs import ExportGenerationError, process_export_job

    job = session.get(ExportJob, job_id)
    if job is None:
        raise AuthorizationError("not_found", "Export job was not found.")
    if job.status == JobStatus.SUCCEEDED.value and job.file_path and Path(job.file_path).exists():
        return job
    attempt = process_export_job(job_id, session=session, auto_retry=False)
    session.expire_all()
    job = session.get(ExportJob, job_id)
    if attempt.outcome != "succeeded" and (job is None or job.status != JobStatus.SUCCEEDED.value):
        raise ExportGenerationError(attempt.error_code)
    return job
