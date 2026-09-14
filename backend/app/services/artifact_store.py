"""Export artifact storage.

The worker publishes finished export bytes here and the API reads them back. Two backends:

- ``filesystem``: one disk shared by the API and the worker (local development, Docker Compose
  with a shared volume). Rejected in production when EXPORT_SHARED_FILESYSTEM is false.
- ``database``: small aggregated export files kept in PostgreSQL, for platforms where each
  service has its own ephemeral disk (Render). Bounded by EXPORT_ARTIFACT_MAX_BYTES and purged
  with the 24-hour export-file policy. Never raw DHIS2 extracts, never an export archive.

Job metadata (checksum, size, media type) always outlives the bytes, so an expired download is
reported as ``artifact_expired`` instead of an unexplained 404.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.domain.exports import EXPORT_FORMATS
from app.models import ExportArtifact, ExportJob

STORAGE_FILESYSTEM = "filesystem"
STORAGE_DATABASE = "database"

ARTIFACT_EXPIRED = "artifact_expired"
ARTIFACT_MISSING = "artifact_missing"
ARTIFACT_TOO_LARGE = "artifact_too_large"

SAFE_ARTIFACT_MESSAGES = {
    ARTIFACT_EXPIRED: (
        "This export file has passed its retention window and was deleted. "
        "Request the export again from the same snapshot."
    ),
    ARTIFACT_MISSING: "The export file is no longer available. Request the export again.",
    ARTIFACT_TOO_LARGE: "The generated export is larger than this deployment allows.",
}


class ArtifactError(RuntimeError):
    """Artifact problem with a client-safe code. Never carries a path or an exception message."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(SAFE_ARTIFACT_MESSAGES.get(code, "The export file is not available."))


@dataclass(frozen=True)
class StoredArtifact:
    storage: str
    size_bytes: int
    checksum: str
    media_type: str
    expires_at: datetime
    file_path: str | None


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def active_storage(settings: Settings | None = None) -> str:
    return (settings or get_settings()).export_artifact_storage.strip().lower()


def artifact_expiry(settings: Settings | None = None, now: datetime | None = None) -> datetime:
    settings = settings or get_settings()
    return (now or _now()) + timedelta(hours=settings.export_file_retention_hours)


def media_type_for(export_type: str) -> str:
    return EXPORT_FORMATS.get(export_type, {}).get("media_type", "application/octet-stream")


def artifact_filename(job: ExportJob) -> str:
    return f"{job.id}{EXPORT_FORMATS.get(job.export_type, {}).get('extension', '')}"


def publish(
    session: Session,
    job: ExportJob,
    source: Path,
    *,
    checksum: str,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> StoredArtifact:
    """Move a freshly generated temporary file into durable artifact storage.

    Called while the worker still holds the job claim and inside its transaction, so a rollback
    leaves no published artifact.
    """
    settings = settings or get_settings()
    storage = active_storage(settings)
    size = source.stat().st_size
    if size > settings.export_artifact_max_bytes:
        raise ArtifactError(ARTIFACT_TOO_LARGE)
    expires_at = artifact_expiry(settings, now)
    media_type = media_type_for(job.export_type)
    if storage == STORAGE_DATABASE:
        content = source.read_bytes()
        session.execute(
            delete(ExportArtifact)
            .where(ExportArtifact.export_job_id == job.id)
            .execution_options(synchronize_session=False)
        )
        session.add(
            ExportArtifact(
                export_job_id=job.id,
                content=content,
                media_type=media_type,
                size_bytes=size,
                checksum=checksum,
                expires_at=expires_at,
            )
        )
        source.unlink(missing_ok=True)
        return StoredArtifact(STORAGE_DATABASE, size, checksum, media_type, expires_at, None)
    destination = Path(settings.export_dir) / artifact_filename(job)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.replace(destination)
    return StoredArtifact(STORAGE_FILESYSTEM, size, checksum, media_type, expires_at, str(destination))


def is_expired(job: ExportJob, now: datetime | None = None) -> bool:
    moment = now or _now()
    if job.artifact_deleted_at is not None:
        return True
    expires = _aware(job.artifact_expires_at)
    return expires is not None and expires <= moment


def is_available(session: Session, job: ExportJob, now: datetime | None = None) -> bool:
    """True when the bytes can still be served. Used for the `downloadable` flag."""
    if job.status != "succeeded" or is_expired(job, now):
        return False
    if (job.artifact_storage or STORAGE_FILESYSTEM) == STORAGE_DATABASE:
        return session.scalar(
            select(ExportArtifact.id).where(ExportArtifact.export_job_id == job.id)
        ) is not None
    return bool(job.file_path and Path(job.file_path).exists())


@dataclass(frozen=True)
class ArtifactPayload:
    filename: str
    media_type: str
    size_bytes: int
    checksum: str | None
    path: Path | None = None
    content: bytes | None = None

    def chunks(self, chunk_size: int = 1 << 20) -> Iterator[bytes]:
        """Stream the artifact without holding a second copy in memory."""
        if self.content is not None:
            for start in range(0, len(self.content), chunk_size):
                yield self.content[start : start + chunk_size]
            return
        if self.path is None:
            raise ArtifactError(ARTIFACT_MISSING)
        with self.path.open("rb") as handle:
            while True:
                block = handle.read(chunk_size)
                if not block:
                    break
                yield block


def load(session: Session, job: ExportJob, now: datetime | None = None) -> ArtifactPayload:
    """Return the artifact for download, or raise a client-safe ArtifactError."""
    if is_expired(job, now):
        raise ArtifactError(ARTIFACT_EXPIRED)
    filename = artifact_filename(job)
    media_type = job.artifact_media_type or media_type_for(job.export_type)
    if (job.artifact_storage or STORAGE_FILESYSTEM) == STORAGE_DATABASE:
        row = session.scalar(select(ExportArtifact).where(ExportArtifact.export_job_id == job.id))
        if row is None:
            raise ArtifactError(ARTIFACT_MISSING)
        if _aware(row.expires_at) <= (now or _now()):
            raise ArtifactError(ARTIFACT_EXPIRED)
        return ArtifactPayload(
            filename,
            row.media_type or media_type,
            row.size_bytes,
            row.checksum,
            content=row.content,
        )
    if not job.file_path:
        raise ArtifactError(ARTIFACT_MISSING)
    path = Path(job.file_path)
    if not path.exists():
        raise ArtifactError(ARTIFACT_MISSING)
    return ArtifactPayload(filename, media_type, path.stat().st_size, job.checksum, path=path)


def discard(session: Session, job: ExportJob) -> None:
    """Remove any stored bytes for a job that is being regenerated. Absent is fine."""
    session.execute(
        delete(ExportArtifact)
        .where(ExportArtifact.export_job_id == job.id)
        .execution_options(synchronize_session=False)
    )
    if job.file_path:
        try:
            Path(job.file_path).unlink()
        except (FileNotFoundError, OSError):
            pass
