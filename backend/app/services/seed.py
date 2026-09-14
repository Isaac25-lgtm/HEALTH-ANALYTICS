from sqlalchemy.orm import Session

from app.domain.enums import (
    ActionPermission,
    ApprovalStatus,
    OrgUnitLevel,
    PeriodRuleScope,
    ProgrammeCode,
)
from app.domain.formula_spec import validate_classification_spec, validate_formula_spec
from app.domain.indicator_catalog import INDICATOR_CATALOG
from app.models import (
    Indicator,
    IndicatorVersion,
    PeriodPopulationRule,
    Programme,
    Role,
    RolePermission,
    User,
    UserGeographyScope,
    UserProgrammeScope,
    UserRole,
)
from app.services.geography import create_org_unit
from app.services.passwords import hash_password
from app.services.quality import seed_quality_rules


def seed_reference_data(session: Session, seed_password: str) -> dict:
    """Synthetic development fixtures. Not production geography, UIDs, or populations."""
    programmes = _programmes(session)
    roles = _roles(session)
    geography = _synthetic_geography(session)
    _indicators(session, programmes)
    _period_rules(session, programmes)
    seed_quality_rules(session)
    users = _users(session, seed_password, roles, programmes, geography)
    session.flush()
    return {"programmes": programmes, "roles": roles, "geography": geography, "users": users}


def _programmes(session: Session) -> dict:
    specs = [
        (ProgrammeCode.MNCH, "Maternal, Newborn and Child Health", False),
        (ProgrammeCode.EPI, "Immunization / EPI", False),
        (ProgrammeCode.MPDSR, "MPDSR", True),
    ]
    out = {}
    for code, name, sensitive in specs:
        row = Programme(
            code=code.value,
            name=name,
            first_release=True,
            sensitive=sensitive,
            description=(
                "First-release programme. Future programmes are not seeded into navigation."
            ),
        )
        session.add(row)
        session.flush()
        out[code.value] = row
    return out


def _roles(session: Session) -> dict:
    catalog = {
        "national_analyst": [
            ActionPermission.VIEW,
            ActionPermission.EXPORT,
            ActionPermission.GENERATE_AI_REPORT,
        ],
        "regional_analyst": [
            ActionPermission.VIEW,
            ActionPermission.EXPORT,
            ActionPermission.GENERATE_AI_REPORT,
        ],
        "district_mch_focal": [
            ActionPermission.VIEW,
            ActionPermission.EXPORT,
            ActionPermission.GENERATE_AI_REPORT,
            ActionPermission.EDIT_POPULATION,
        ],
        "facility_user": [ActionPermission.VIEW],
        "view_only": [ActionPermission.VIEW],
        "mpdsr_analyst": [
            ActionPermission.VIEW,
            ActionPermission.EXPORT,
            ActionPermission.VIEW_MPDSR_EVENTS,
        ],
        "system_administrator": list(ActionPermission),
    }
    roles = {}
    for code, actions in catalog.items():
        role = Role(code=code, name=code.replace("_", " ").title())
        session.add(role)
        session.flush()
        for action in actions:
            session.add(RolePermission(role_id=role.id, action=action.value))
        roles[code] = role
    return roles


def _synthetic_geography(session) -> dict:
    uganda = create_org_unit(
        session, code="UG", name="Uganda", level_type=OrgUnitLevel.COUNTRY
    )
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


def _indicators(session: Session, programmes: dict) -> None:
    for spec in INDICATOR_CATALOG:
        validate_formula_spec(spec["formula_spec"])
        validate_classification_spec(spec["classification_spec"])
        indicator = Indicator(
            code=spec["code"],
            programme_id=programmes[spec["programme"]].id,
            name=spec["name"],
        )
        session.add(indicator)
        session.flush()
        session.add(
            IndicatorVersion(
                indicator_id=indicator.id,
                formula_version="v1",
                numerator_definition=spec["numerator_definition"],
                denominator_type=spec["denominator_type"],
                denominator_coefficient=spec["denominator_coefficient"],
                multiplier=spec["multiplier"],
                unit=spec["unit"],
                display_precision=spec["display_precision"],
                direction=spec["direction"],
                target=spec["target"],
                green_band=spec["green_band"],
                yellow_band=spec["yellow_band"],
                red_band=spec["red_band"],
                blue_rule=spec["blue_rule"],
                aggregation_method=spec["aggregation_method"],
                period_adjustment=spec["period_adjustment"],
                methodology_text=spec["methodology_text"],
                formula_spec=spec["formula_spec"],
                classification_spec=spec["classification_spec"],
                is_current=True,
            )
        )


def _period_rules(session: Session, programmes: dict) -> None:
    """Binding decision D-004: full financial years use the FY base-year population.

    Only the ``fy`` period kind is covered. Monthly and quarterly population selection
    is unresolved (OPEN_ITEMS) and is not seeded.
    """
    for key, year in (("FY2024/25", 2024), ("FY2025/26", 2025)):
        for programme_id in (None, programmes["MNCH"].id):
            session.add(
                PeriodPopulationRule(
                    financial_year_key=key,
                    population_year=year,
                    programme_id=programme_id,
                    scope_kind=PeriodRuleScope.FINANCIAL_YEAR.value,
                    applies_to_period_kinds=["fy"],
                    approval_status=ApprovalStatus.APPROVED.value,
                    notes="Current MNCH convention (D-004). Covers full financial years only.",
                )
            )
