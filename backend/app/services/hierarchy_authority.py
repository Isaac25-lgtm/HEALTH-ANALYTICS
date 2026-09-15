"""Whether an organisation-unit hierarchy is authoritative enough to turn a name match into a
production mapping.

Authority is never inferred from how many units exist. It requires an explicit owner approval
reference for the specific purpose and geography level, recorded in configuration, **and** a
complete cohort at that level. Each purpose has its own reference, because approving the
district/city population crosswalk does not approve sub-county boundaries:

- population crosswalk (district/city):    ``POPULATION_HIERARCHY_APPROVAL_REFERENCE``
- district/city boundaries:                ``BOUNDARY_DISTRICT_HIERARCHY_APPROVAL_REFERENCE``
- sub-county boundaries:                   ``BOUNDARY_SUB_COUNTY_HIERARCHY_APPROVAL_REFERENCE``

All three are empty until the owner supplies them. Nothing here invents a reference.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.domain.enums import OrgUnitLevel
from app.models import OrgUnit

REFERENCE_SYNTHETIC = "synthetic_development_fixtures"
REFERENCE_UNAPPROVED = "unapproved_hierarchy"
REFERENCE_AUTHORITATIVE = "authoritative_org_units"

PURPOSE_POPULATION = "population_crosswalk"
PURPOSE_BOUNDARY = "boundary_geometry"

LEVEL_DISTRICT = OrgUnitLevel.DISTRICT.value
LEVEL_SUB_COUNTY = OrgUnitLevel.SUB_COUNTY.value

# The approved district/city cohort (D-045/D-046: 135 districts and 11 cities).
DISTRICT_CITY_COHORT = 146

LEVEL_TYPES = {
    LEVEL_DISTRICT: (OrgUnitLevel.DISTRICT.value, OrgUnitLevel.CITY.value),
    LEVEL_SUB_COUNTY: (OrgUnitLevel.SUB_COUNTY.value,),
}


@dataclass(frozen=True)
class HierarchyAuthority:
    purpose: str
    level: str
    reference_scope: str
    approval_reference: str | None
    units_at_level: int
    required_units: int

    @property
    def authoritative(self) -> bool:
        return self.reference_scope == REFERENCE_AUTHORITATIVE

    def as_dict(self) -> dict:
        return {
            "purpose": self.purpose,
            "level": self.level,
            "reference_scope": self.reference_scope,
            "hierarchy_approval_reference": self.approval_reference,
            "units_at_level": self.units_at_level,
            "required_units": self.required_units,
        }


def approval_reference(purpose: str, level: str, settings: Settings | None = None) -> str | None:
    settings = settings or get_settings()
    if purpose == PURPOSE_POPULATION:
        value = settings.population_hierarchy_approval_reference
    elif level == LEVEL_DISTRICT:
        value = settings.boundary_district_hierarchy_approval_reference
    elif level == LEVEL_SUB_COUNTY:
        value = settings.boundary_sub_county_hierarchy_approval_reference
    else:
        value = ""
    value = (value or "").strip()
    return value or None


def hierarchy_authority(
    session: Session,
    *,
    purpose: str,
    level: str,
    required_units: int | None = None,
    settings: Settings | None = None,
) -> HierarchyAuthority:
    """Classify the hierarchy for one purpose and level.

    ``required_units`` is the size of the cohort that must exist (146 district/city units by
    default; for sub-counties the caller passes the number of source features being mapped,
    because no approved sub-county count exists).
    """
    if level not in LEVEL_TYPES:
        raise ValueError(f"Unsupported hierarchy level: {level}")
    count = int(
        session.scalar(
            select(func.count())
            .select_from(OrgUnit)
            .where(OrgUnit.active.is_(True), OrgUnit.level_type.in_(LEVEL_TYPES[level]))
        )
        or 0
    )
    required = (
        required_units if required_units is not None else (DISTRICT_CITY_COHORT if level == LEVEL_DISTRICT else 1)
    )
    reference = approval_reference(purpose, level, settings)
    if count < max(required, 1):
        scope = REFERENCE_SYNTHETIC
    elif reference is None:
        scope = REFERENCE_UNAPPROVED
    else:
        scope = REFERENCE_AUTHORITATIVE
    return HierarchyAuthority(
        purpose=purpose,
        level=level,
        reference_scope=scope,
        approval_reference=reference,
        units_at_level=count,
        required_units=required,
    )
