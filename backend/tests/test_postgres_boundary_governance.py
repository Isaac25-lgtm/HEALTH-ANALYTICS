"""PostgreSQL: boundary activation governance against real constraints and row locks.

Runs only against the disposable verification cluster named by HPIP_POSTGRES_TEST_URL.
"""

from __future__ import annotations

from datetime import date

import pytest
from alembic import command
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models import AuditLog, Geometry, User
from app.services.authorization import AuthorizationError
from app.services.geometry import (
    apply_geometry_import,
    boundary_authority,
    boundary_crosswalk_semantics,
    prepare_geometry_import,
)
from app.services.seed import seed_reference_data
from tests import boundary_fixtures as fx
from tests.conftest import SEED_PASSWORD
from tests.test_postgres_migrations import (
    _admin_url,
    _alembic_cfg,
    _cleanup,
    _point_alembic,
    _prepare_verify_db,
    requires_postgres,
)


def _activate(session, plan, **overrides):
    arguments = {
        "valid_from": date(2031, 1, 1),
        "effective_date_verified": True,
        "effective_date_reference": fx.EFFECTIVE_DATE_REFERENCE,
        "mapping_decision_reference": fx.MAPPING_REFERENCE,
    }
    arguments.update(overrides)
    admin = session.scalar(select(User).where(User.username == "admin.user"))
    return apply_geometry_import(session, admin, plan, **arguments)


@requires_postgres
def test_postgres_boundary_activation_is_governed(monkeypatch, tmp_path):
    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    try:
        command.upgrade(_alembic_cfg(), "head")
        engine = create_engine(test_url, future=True)
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        with factory() as session:
            seed_reference_data(session, SEED_PASSWORD)
            session.commit()

            synthetic = prepare_geometry_import(
                session, fx.write_geojson(tmp_path / "synthetic.geojson", ["Pader", "Kitgum", "Soroti"]), "district"
            )
            monkeypatch.setattr(get_settings(), "boundary_district_hierarchy_approval_reference", fx.APPROVAL)
            semantics = boundary_crosswalk_semantics(synthetic, boundary_authority(session, synthetic))
            assert (semantics["reconciliation_matched"], semantics["production_unresolved"]) == (3, 3)
            with pytest.raises(AuthorizationError) as refused:
                _activate(session, synthetic)
            assert refused.value.code == "boundary_hierarchy_not_approved"

            names = fx.create_cohort(session)
            full = prepare_geometry_import(session, fx.write_geojson(tmp_path / "full.geojson", names), "district")
            monkeypatch.setattr(get_settings(), "boundary_district_hierarchy_approval_reference", "")
            with pytest.raises(AuthorizationError) as unapproved:
                _activate(session, full)
            assert unapproved.value.code == "boundary_hierarchy_not_approved"
            session.rollback()

            monkeypatch.setattr(get_settings(), "boundary_district_hierarchy_approval_reference", fx.APPROVAL)
            with pytest.raises(AuthorizationError) as partial:
                _activate(
                    session,
                    prepare_geometry_import(
                        session, fx.write_geojson(tmp_path / "partial.geojson", [*names, "Unmapped"]), "district"
                    ),
                    allow_unmatched=True,
                )
            assert partial.value.code == "boundary_partial_activation_unapproved"
            assert session.scalar(select(func.count()).select_from(Geometry)) == 0

            assert _activate(session, full) == {"inserted": 146, "unchanged": 0, "superseded": 0}
            session.commit()
            audit = session.scalar(select(AuditLog).where(AuditLog.action == "geometry_imported"))
            assert audit.after_json["hierarchy_approval_reference"] == fx.APPROVAL
            assert audit.after_json["source_sha256"] == full.source_sha256
            again = prepare_geometry_import(session, tmp_path / "full.geojson", "district")
            assert _activate(session, again) == {"inserted": 0, "unchanged": 146, "superseded": 0}
            session.commit()
            current = session.scalar(select(func.count()).select_from(Geometry).where(Geometry.valid_to.is_(None)))
            assert current == 146
        engine.dispose()
    finally:
        _cleanup(admin, monkeypatch)
