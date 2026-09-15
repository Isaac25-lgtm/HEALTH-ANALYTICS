"""Synthetic development fixtures layered on the production reference bootstrap.

The approved reference (programmes, roles, catalogue, quality rules, D-045 period rules and the
country root) comes from ``reference_bootstrap`` so development and production share one
definition. Everything this module adds on top is synthetic: geography, users and passwords.
None of it is production geography, a DHIS2 UID or a population.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import OrgUnitLevel
from app.models import (
    OrgUnit,
    Programme,
    Role,
    User,
    UserGeographyScope,
    UserProgrammeScope,
    UserRole,
)
from app.services.geography import create_org_unit
from app.services.passwords import hash_password
from app.services.reference_bootstrap import (  # noqa: F401  (re-exported for existing imports)
    FY_PERIOD_KINDS,
    POPULATION_SOURCE_FIRST_YEAR,
    POPULATION_SOURCE_LAST_YEAR,
    PROGRAMME_CATALOG,
    ROLE_CATALOG,
    ROOT_ORG_UNIT_CODE,
    bootstrap_reference_data,
)


def seed_reference_data(session: Session, seed_password: str) -> dict:
    """Synthetic development fixtures. Not production geography, UIDs, or populations."""
    bootstrap_reference_data(session)
    by_code = {row.code: row for row in session.scalars(select(Programme)).all()}
    programmes = {code: by_code[code] for code, _name, _sensitive in PROGRAMME_CATALOG}
    by_role = {row.code: row for row in session.scalars(select(Role)).all()}
    roles = {code: by_role[code] for code in ROLE_CATALOG}
    geography = _synthetic_geography(session)
    users = _users(session, seed_password, roles, programmes, geography)
    session.flush()
    return {"programmes": programmes, "roles": roles, "geography": geography, "users": users}


def _synthetic_geography(session) -> dict:
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == ROOT_ORG_UNIT_CODE))
    acholi = create_org_unit(
        session, code="ACHOLI", name="Acholi", level_type=OrgUnitLevel.SUB_REGION, parent=uganda
    )
    teso = create_org_unit(
        session, code="TESO", name="Teso", level_type=OrgUnitLevel.SUB_REGION, parent=uganda
    )
    pader = create_org_unit(
        session, code="PADER", name="Pader", level_type=OrgUnitLevel.DISTRICT, parent=acholi
    )
    kitgum = create_org_unit(
        session, code="KITGUM", name="Kitgum", level_type=OrgUnitLevel.DISTRICT, parent=acholi
    )
    soroti = create_org_unit(
        session, code="SOROTI", name="Soroti", level_type=OrgUnitLevel.DISTRICT, parent=teso
    )
    pader_town = create_org_unit(
        session,
        code="PADER_TOWN",
        name="Pader Town",
        level_type=OrgUnitLevel.SUB_COUNTY,
        parent=pader,
    )
    pader_hc3 = create_org_unit(
        session,
        code="PADER_HC_III",
        name="Pader HC III",
        level_type=OrgUnitLevel.FACILITY,
        parent=pader_town,
        ownership="Government",
        facility_level="HC III",
    )
    return {
        "uganda": uganda,
        "acholi": acholi,
        "teso": teso,
        "pader": pader,
        "kitgum": kitgum,
        "soroti": soroti,
        "pader_town": pader_town,
        "pader_hc3": pader_hc3,
    }


def _grant(session, user, role, org_unit, programmes: list):
    session.add(UserRole(user_id=user.id, role_id=role.id))
    session.add(UserGeographyScope(user_id=user.id, org_unit_id=org_unit.id))
    for programme in programmes:
        session.add(UserProgrammeScope(user_id=user.id, programme_id=programme.id))


def _users(session, password, roles, programmes, geography) -> dict:
    hashed = hash_password(password)
    all_programmes = list(programmes.values())
    mnch = programmes["MNCH"]
    users = {}

    specs = [
        (
            "national.analyst",
            "National Analyst",
            roles["national_analyst"],
            geography["uganda"],
            all_programmes,
            False,
        ),
        (
            "acholi.analyst",
            "Acholi Regional Analyst",
            roles["regional_analyst"],
            geography["acholi"],
            all_programmes,
            False,
        ),
        (
            "pader.focal",
            "Pader District MCH Focal Person",
            roles["district_mch_focal"],
            geography["pader"],
            [mnch],
            False,
        ),
        (
            "paderhc3.user",
            "Pader HC III User",
            roles["facility_user"],
            geography["pader_hc3"],
            [mnch],
            False,
        ),
        (
            "mnch.only",
            "National MNCH-only Analyst",
            roles["national_analyst"],
            geography["uganda"],
            [mnch],
            False,
        ),
        (
            "view.only",
            "National View-only Analyst",
            roles["view_only"],
            geography["uganda"],
            all_programmes,
            False,
        ),
        (
            "mpdsr.analyst",
            "Acholi MPDSR Analyst",
            roles["mpdsr_analyst"],
            geography["acholi"],
            [programmes["MPDSR"]],
            False,
        ),
        (
            "admin.user",
            "System Administrator",
            roles["system_administrator"],
            geography["uganda"],
            all_programmes,
            True,
        ),
    ]
    for username, display, role, org, progs, admin in specs:
        user = User(
            username=username,
            display_name=display,
            email=f"{username.replace('.', '_')}@dev.local",
            password_hash=hashed,
            is_system_admin=admin,
            identity_provider="local_dev",
        )
        session.add(user)
        session.flush()
        _grant(session, user, role, org, progs)
        users[username] = user
    return users
