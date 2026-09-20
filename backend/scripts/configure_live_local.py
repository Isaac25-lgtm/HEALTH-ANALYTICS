"""Create a persistent local HPIP control database and a gitignored live-DHIS2 configuration.

This command is intentionally interactive. PostgreSQL and DHIS2 passwords are read without echo,
never accepted as command-line arguments, and never printed. The DHIS2 credential is written only
to the repository-root ``.env`` file, which is excluded from Git. HPIP retains no user's DHIS2
password in its database.

The resulting environment is local live-data UAT, not a public production deployment: cookies use
HTTP localhost, jobs execute eagerly, and rate limiting is process-local. Render/Neon production
must use HTTPS, Redis/Celery and provider-managed secrets.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import os
import secrets
from pathlib import Path
from urllib.parse import quote_plus

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / ".env"


def _secret(prompt: str) -> str:
    value = getpass.getpass(prompt)
    if not value:
        raise SystemExit("A required secret was empty; nothing was configured.")
    if "\n" in value or "\r" in value:
        raise SystemExit("Secrets cannot contain line breaks; nothing was configured.")
    return value


def _create_database(
    *,
    host: str,
    port: int,
    admin_user: str,
    admin_password: str,
    app_user: str,
    app_password: str,
    database: str,
) -> None:
    with psycopg.connect(
        host=host,
        port=port,
        user=admin_user,
        password=admin_password,
        dbname="postgres",
        autocommit=True,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (app_user,))
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                        sql.Identifier(app_user),
                        sql.Literal(app_password),
                    )
                )
            else:
                cursor.execute(
                    sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(
                        sql.Identifier(app_user),
                        sql.Literal(app_password),
                    )
                )
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,))
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL("CREATE DATABASE {} OWNER {}").format(
                        sql.Identifier(database),
                        sql.Identifier(app_user),
                    )
                )


def _environment(
    *,
    host: str,
    port: int,
    app_user: str,
    app_password: str,
    database: str,
    dhis2_username: str,
    dhis2_password: str,
) -> str:
    database_url = (
        f"postgresql+psycopg://{quote_plus(app_user)}:{quote_plus(app_password)}"
        f"@{host}:{port}/{quote_plus(database)}"
    )
    values = {
        "APP_ENV": "development",
        "API_HOST": "127.0.0.1",
        "API_PORT": "8010",
        "WEB_ORIGIN": "http://localhost:3000",
        "LOG_LEVEL": "INFO",
        "DATABASE_URL": database_url,
        "DB_REQUIRE_SSL": "false",
        "AUTH_SECRET": secrets.token_urlsafe(48),
        "AUTH_COOKIE_SECURE": "false",
        "AUTH_COOKIE_SAMESITE": "lax",
        "SEED_DEV_DATA": "false",
        "SYNC_EXECUTION": "eager",
        "RATE_LIMIT_BACKEND": "memory",
        "EXPORT_EAGER": "true",
        "EXPORT_ARTIFACT_STORAGE": "filesystem",
        "EXPORT_SHARED_FILESYSTEM": "true",
        "DHIS2_ENABLED": "true",
        "SYNC_ENABLED": "true",
        "DHIS2_LOGIN_ENABLED": "true",
        "DHIS2_BASE_URL": "https://hmis.health.go.ug",
        "DHIS2_USERNAME": dhis2_username,
        # Encoding is not encryption; the file remains a secret. It prevents dotenv `${...}`
        # interpolation from corrupting an otherwise valid rotated password.
        "DHIS2_PASSWORD_B64": base64.b64encode(dhis2_password.encode("utf-8")).decode("ascii"),
        "DHIS2_AUTH_METHOD": "basic",
        "DHIS2_API_PATH_PREFIX": "/api",
        "DHIS2_TIMEOUT_SECONDS": "30",
        "DHIS2_MAX_RETRIES": "3",
        "DHIS2_PAGE_SIZE": "200",
        "DHIS2_MAX_PAGES": "50",
        "DHIS2_MAX_RESPONSE_BYTES": "5000000",
        "DHIS2_STALE_HOURS": "72",
        "RAW_AGGREGATE_RETENTION_DAYS": "7",
        "MPDSR_EVENT_RETENTION_HOURS": "24",
        "EXPORT_FILE_RETENTION_HOURS": "24",
        "EXPORT_JOB_RETENTION_DAYS": "90",
        "CALCULATION_SNAPSHOT_RETENTION_MONTHS": "36",
        "AUDIT_LOG_RETENTION_MONTHS": "24",
        "PURGE_ENABLED": "true",
        "PURGE_DRY_RUN": "false",
        "PURGE_SCHEDULE_ENABLED": "false",
        "AI_ENABLED": "false",
        "BACKEND_INTERNAL_URL": "http://127.0.0.1:8010",
    }
    # Single-quoted dotenv values preserve spaces, #, $ and URL punctuation. Escape the two
    # characters python-dotenv recognises inside single quotes so rotated passwords remain exact.
    def quoted(value: str) -> str:
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"

    return "\n".join(f"{key}={quoted(value)}" for key, value in values.items()) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dhis2-username", required=True)
    parser.add_argument("--postgres-host", default="127.0.0.1")
    parser.add_argument("--postgres-port", type=int, default=5432)
    parser.add_argument("--postgres-admin", default="postgres")
    parser.add_argument("--app-user", default="hpip_app")
    parser.add_argument("--database", default="hpip_live")
    parser.add_argument("--force", action="store_true", help="Replace an existing root .env file.")
    args = parser.parse_args(argv)
    if ENV_PATH.exists() and not args.force:
        print(f"Refusing to overwrite existing {ENV_PATH}. Re-run with --force after reviewing it.")
        return 2

    postgres_password = _secret("PostgreSQL administrator password: ")
    dhis2_password = _secret("DHIS2 password (stored only in gitignored .env): ")
    app_password = secrets.token_urlsafe(32)
    _create_database(
        host=args.postgres_host,
        port=args.postgres_port,
        admin_user=args.postgres_admin,
        admin_password=postgres_password,
        app_user=args.app_user,
        app_password=app_password,
        database=args.database,
    )
    ENV_PATH.write_text(
        _environment(
            host=args.postgres_host,
            port=args.postgres_port,
            app_user=args.app_user,
            app_password=app_password,
            database=args.database,
            dhis2_username=args.dhis2_username,
            dhis2_password=dhis2_password,
        ),
        encoding="utf-8",
    )
    try:
        os.chmod(ENV_PATH, 0o600)
    except OSError:
        pass
    print(f"Configured persistent local database {args.database} and wrote {ENV_PATH}.")
    print("No synthetic users, geography, populations, mappings or performance values were created.")
    print("Next: run migrations, bootstrap approved reference data, and provision a DHIS2-backed administrator.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
