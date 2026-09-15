"""Database URL normalisation and connection arguments shared by the runtime and Alembic.

Only psycopg 3 is installed in the application image, so a standard provider URL such as
Neon's ``postgresql://...`` (or Heroku-style ``postgres://``) is rewritten to the
``postgresql+psycopg`` driver instead of failing with a missing-psycopg2 import. A URL that
names another PostgreSQL driver is left unchanged and reported by configuration validation.

TLS precedence is explicit: an ``sslmode`` in the URL is used as written; otherwise
``DB_SSLMODE`` is applied through the connection arguments. When both are present they must
agree (validation reports a conflict). Nothing in this module logs or returns a URL inside an
error message.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

POSTGRES_DRIVER = "postgresql+psycopg"
TLS_MODES = frozenset({"require", "verify-ca", "verify-full"})
_PLAIN_SCHEMES = ("postgres://", "postgresql://")


def normalise_database_url(raw: str | None) -> str:
    """Rewrite plain PostgreSQL schemes to the installed psycopg 3 driver. Idempotent."""
    value = (raw or "").strip()
    lowered = value.lower()
    for scheme in _PLAIN_SCHEMES:
        if lowered.startswith(scheme):
            return POSTGRES_DRIVER + "://" + value[len(scheme) :]
    return value


def is_postgres(url: str) -> bool:
    return url.lower().startswith("postgresql")


def driver_error(url: str, label: str) -> str | None:
    """A PostgreSQL URL must use psycopg 3, the only driver in the application image."""
    if not url or not is_postgres(url):
        return None
    scheme = url.split("://", 1)[0].lower()
    if scheme != POSTGRES_DRIVER:
        return f"{label} must use the {POSTGRES_DRIVER} driver (psycopg 3); '{scheme}' is not installed."
    return None


def is_well_formed(url: str) -> bool:
    if "://" not in url or url.split("://", 1)[1] == "":
        return False
    try:
        make_url(url)
    except (ArgumentError, ValueError):
        return False
    return True


def url_sslmode(url: str) -> str:
    """The sslmode written in the URL query, lower-cased, or '' when absent."""
    try:
        query = urlsplit(url).query
    except ValueError:
        return ""
    values = parse_qs(query).get("sslmode") or []
    return values[-1].strip().lower() if values else ""


def effective_sslmode(url: str, configured: str) -> str:
    """URL first, then DB_SSLMODE: exactly what the driver will receive."""
    return url_sslmode(url) or (configured or "").strip().lower()


def tls_errors(url: str, label: str, *, configured: str, require_ssl: bool) -> list[str]:
    errors: list[str] = []
    in_url = url_sslmode(url)
    declared = (configured or "").strip().lower()
    if in_url and declared and in_url != declared:
        errors.append(f"{label} sets sslmode={in_url}, which conflicts with DB_SSLMODE={declared}.")
    if require_ssl:
        mode = effective_sslmode(url, configured)
        if mode == "disable":
            errors.append(f"{label} disables TLS while DB_REQUIRE_SSL is true.")
        elif mode not in TLS_MODES:
            errors.append(
                f"{label} must require TLS: set DB_SSLMODE=require or sslmode=require in the URL. "
                "Set DB_REQUIRE_SSL=false only for a database on a private network you control."
            )
    return errors


def connect_args(url: str, *, sslmode: str, connect_timeout: int, application_name: str) -> dict:
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    args: dict = {"connect_timeout": connect_timeout}
    # A URL that already carries sslmode wins; DB_SSLMODE fills the gap.
    if sslmode and not url_sslmode(url):
        args["sslmode"] = sslmode
    if application_name:
        args["application_name"] = application_name
    return args
