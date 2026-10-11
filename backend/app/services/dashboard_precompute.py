"""Prepare default authorised views ahead of use, without introducing shared-user snapshots.

Calculation runs are shared between users and verified against the analytics revision, so the
expensive part of a view is paid once here; each user's own snapshot is then a quick assembly.
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select, text

from app.db.session import get_engine, get_session_factory
from app.domain.enums import ActionPermission
from app.domain.modules import MODULE_PROGRAMME
from app.models import User
from app.services.authorization import has_action, primary_landing_org_unit, programme_scope_codes
from app.services.dashboard import FACILITY_JOBS_KEY, build_dashboard
from app.services.facility_data import run_facility_job
from app.services.prepared_dashboard import find_prepared_dashboard

# One preparation at a time, whichever process starts it (API start, refresh script or worker).
_PREPARATION_LOCK_KEY = 7_204_601_001


def default_period(today: date) -> str:
    """The latest closed financial year, which is the period every user lands on."""
    start = today.year - 1 if today.month >= 7 else today.year - 2
    return f"FY{start}/{str(start + 1)[2:]}"


def extended_periods(today: date) -> list[str]:
    """Other periods people open first: the financial year in progress and the two latest closed months."""
    start = today.year if today.month >= 7 else today.year - 1
    periods = [f"FY{start}/{str(start + 1)[2:]}"]
    month_start = today.replace(day=1)
    for _ in range(2):
        month_start = (month_start - timedelta(days=1)).replace(day=1)
        periods.append(f"{month_start.year}{month_start.month:02d}")
    return periods


def prepare_default_dashboards(
    programme_code: str | None = None, *, extended: bool = False, wait: bool = False
) -> dict:
    """Prepare each active user's landing view for every authorised module.

    With ``extended``, the widest-scope account also prepares the other commonly opened periods,
    which calculates their shared runs for everyone. One failed view never stops the rest.
    ``wait`` queues behind a preparation already in progress instead of skipping: a refresh that
    has just changed the data must prepare again once the earlier pass has finished.
    """
    engine = get_engine()
    lock_connection = None
    if engine.dialect.name == "postgresql":
        lock_connection = engine.connect()
        if wait:
            lock_connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _PREPARATION_LOCK_KEY})
        elif not lock_connection.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": _PREPARATION_LOCK_KEY}
        ).scalar():
            lock_connection.close()
            return {"prepared": 0, "reused": 0, "failed": 0, "skipped_already_running": True}
    try:
        return _prepare(programme_code, extended)
    finally:
        if lock_connection is not None:
            lock_connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _PREPARATION_LOCK_KEY})
            lock_connection.close()


def _prepare(programme_code: str | None, extended: bool) -> dict:
    factory = get_session_factory()
    with factory() as directory:
        users = list(
            directory.execute(
                select(User.id, User.is_system_admin).where(User.is_active.is_(True)).order_by(User.created_at)
            ).all()
        )
    today = datetime.now(UTC).date()
    counts = {"prepared": 0, "reused": 0, "failed": 0, "skipped_unauthorised_or_without_landing": 0}

    def prepare_user(user_id, periods: list[str]) -> None:
        with factory() as session:
            user = session.get(User, user_id)
            if user is None or not user.is_active or not has_action(session, user, ActionPermission.VIEW):
                counts["skipped_unauthorised_or_without_landing"] += 1
                return
            landing = primary_landing_org_unit(session, user)
            programmes = programme_scope_codes(session, user)
            if landing is None:
                counts["skipped_unauthorised_or_without_landing"] += 1
                return
            landing_id = landing.id
            for period in periods:
                for module, code in MODULE_PROGRAMME.items():
                    if code not in programmes or (programme_code and code != programme_code):
                        continue
                    try:
                        existing = find_prepared_dashboard(
                            session, user, org_unit_id=landing_id, period=period, module=module
                        )
                        if existing is not None:
                            counts["reused"] += 1
                            continue
                        build_dashboard(session, user=user, org_unit_id=landing_id, period=period, module=module)
                        session.commit()
                        for job_id in session.info.pop(FACILITY_JOBS_KEY, []):
                            run_facility_job(job_id)
                        counts["prepared"] += 1
                    except Exception:  # noqa: BLE001 - one unavailable view must not stop the others
                        session.rollback()
                        session.info.pop(FACILITY_JOBS_KEY, None)
                        counts["failed"] += 1

    # Landing views first: they are what a person waits for at sign-in.
    for user_id, _is_admin in users:
        prepare_user(user_id, [default_period(today)])
    if extended:
        widest = next((user_id for user_id, is_admin in users if is_admin), None)
        if widest is not None:
            prepare_user(widest, extended_periods(today))
    return counts
