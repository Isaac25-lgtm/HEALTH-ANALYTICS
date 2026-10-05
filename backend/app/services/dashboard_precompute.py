"""Prepare default authorised views in the existing worker, without introducing shared-user snapshots."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.db.session import get_session_factory
from app.domain.enums import ActionPermission
from app.domain.modules import MODULE_PROGRAMME
from app.models import User
from app.services.authorization import has_action, primary_landing_org_unit, programme_scope_codes
from app.services.dashboard import FACILITY_JOBS_KEY, build_dashboard
from app.services.facility_data import run_facility_job
from app.services.prepared_dashboard import find_prepared_dashboard


def prepare_default_dashboards(programme_code: str | None = None) -> dict:
    factory = get_session_factory()
    with factory() as directory:
        users = list(directory.scalars(select(User.id).where(User.is_active.is_(True))).all())
    today = datetime.now(UTC).date()
    start = today.year - 1 if today.month >= 7 else today.year - 2
    period = f"FY{start}/{str(start + 1)[2:]}"
    prepared = reused = skipped = 0
    for user_id in users:
        with factory() as session:
            user = session.get(User, user_id)
            if user is None or not user.is_active or not has_action(session, user, ActionPermission.VIEW):
                skipped += 1
                continue
            landing = primary_landing_org_unit(session, user)
            programmes = programme_scope_codes(session, user)
            if landing is None:
                skipped += 1
                continue
            for module, code in MODULE_PROGRAMME.items():
                if code not in programmes or (programme_code and code != programme_code):
                    continue
                existing = find_prepared_dashboard(session, user, org_unit_id=landing.id, period=period, module=module)
                if existing is not None:
                    reused += 1
                    continue
                build_dashboard(session, user=user, org_unit_id=landing.id, period=period, module=module)
                session.commit()
                for job_id in session.info.pop(FACILITY_JOBS_KEY, []):
                    run_facility_job(job_id)
                prepared += 1
    return {"prepared": prepared, "reused": reused, "skipped_unauthorised_or_without_landing": skipped}
