"""Synthetic demonstration dataset for development and test environments only.

Everything here is invented so the dashboards can be seen working: fictional sub-counties and
facilities under the existing synthetic districts, a fictional population version, fictional source
counts, and crude fictional polygons. **None of it is Ugandan health data, a national population, a
DHIS2 identifier or an approved boundary.** Every row is written with a source that names itself as
a demonstration fixture so it can never be mistaken for a production extract.

The numbers are deterministic (no randomness, no clock) so screenshots and tests are stable, and
they are shaped only to exercise the approved catalogue: the coverage bands, directions and
formulas all come from ``indicator_catalog``. Nothing here defines a threshold or a formula.

Deliberate gaps are kept so the honest-missing behaviour stays visible: facilities have no approved
catchment population, sub-counties and facilities have no geometry, and the periods before
FY2024/25 have no approved population rule.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.domain.enums import ApprovalStatus, OrgUnitLevel, PopulationType
from app.domain.indicator_catalog import INDICATOR_CATALOG
from app.models import (
    Geometry,
    OrgUnit,
    PopulationValue,
    PopulationVersion,
    Programme,
    RawAggregateValue,
    SourceMapping,
)
from app.services.geography import create_org_unit

SOURCE_SYSTEM = "synthetic_demo_fixture"
POPULATION_VERSION_CODE = "DEMO_SYNTHETIC"
PERIODS = ("FY2024/25", "FY2025/26", "FY2026/27")
YEARS = (2024, 2025, 2026, 2027)
GEOMETRY_VALID_FROM = date(2024, 7, 1)
# Demonstration rows record when the fixture was seeded, to the second, and re-seeding never
# rewrites it: one timestamp per database, identical across every row and every re-seed. A fixed
# calendar constant would be deterministic but would age past DHIS2_STALE_HOURS, flagging all 180
# rows as stale reporting and burying the real data-quality console in fixture noise.

# District demonstration profile: population, and how each district performs relative to target.
# Different profiles give the scorecard and map visibly different colours.
DISTRICT_PROFILE = {
    "PADER": {"population": 412_000, "performance": 1.01, "trend": 0.015},
    "KITGUM": {"population": 318_000, "performance": 0.90, "trend": 0.03},
    "SOROTI": {"population": 496_000, "performance": 0.80, "trend": -0.01},
}

# Fictional sub-counties and facilities per district. Facility share sums to 1.0 per district.
FACILITY_PLAN = {
    "PADER": [
        ("PADER_TOWN", "Pader Town", [("Pader HC III", "HC III", 0.34, 1.04)]),
        (
            "ATANGA",
            "Atanga",
            [("Atanga HC IV", "HC IV", 0.40, 1.00), ("Atanga East HC II", "HC II", 0.26, 0.90)],
        ),
    ],
    "KITGUM": [
        (
            "KITGUM_CENTRAL",
            "Kitgum Central",
            [("Kitgum Central HC IV", "HC IV", 0.45, 0.95), ("Kitgum Central HC II", "HC II", 0.20, 0.72)],
        ),
        ("LAGORO", "Lagoro", [("Lagoro HC III", "HC III", 0.35, 0.86)]),
    ],
    "SOROTI": [
        (
            "SOROTI_EAST",
            "Soroti East",
            [("Soroti East HC IV", "HC IV", 0.42, 0.83), ("Soroti East HC II", "HC II", 0.18, 0.58)],
        ),
        ("KAMUDA", "Kamuda", [("Kamuda HC III", "HC III", 0.40, 0.66)]),
    ],
}

# How many source events each key produces per 1,000 population in a year, before the district and
# facility performance factors are applied. Purely illustrative volumes.
KEY_RATE = {
    "ANC1": 48.5,
    "ANC1_FT": 23.3,
    "ANC4": 41.2,
    "ANC8": 3.5,
    "IPT3": 50.0,
    "HB_TESTED": 39.8,
    "IFA_30": 42.7,
    "ULTRASOUND": 17.0,
    "ANC1_AGE_LT15": 0.4,
    "ANC1_AGE_15_19": 6.4,
    "DELIVERIES": 37.8,
    "CS": 3.4,
    "LIVE_BIRTHS": 36.7,
    "RESUSCITATED": 1.09,
    "BIRTH_ASPHYXIA": 1.4,
    "KMC_PERCENT": 62.0,
    "FRESH_SB": 0.4,
    "MACERATED_SB": 0.35,
    "NEWBORN_DEATHS": 0.45,
    "MATERNAL_DEATHS": 0.045,
    "BCG": 41.7,
    "HEPB_BIRTH": 32.7,
    "OPV0": 38.7,
    "OPV1": 40.0,
    "OPV2": 38.3,
    "OPV3": 36.6,
    "IPV1": 35.3,
    "IPV2": 29.2,
    "MR": 36.0,
    "PCV1": 40.4,
    "PCV2": 38.7,
    "PCV3": 36.6,
    "PENTA1": 40.9,
    "PENTA2": 38.9,
    "PENTA3": 37.0,
    "ROTAV1": 39.6,
    "ROTAV2": 37.0,
    "MV1": 37.8,
    "MV2": 33.5,
    "MV3": 30.1,
    "MV4": 27.5,
    "TD_1549": 26.7,
    "VITA_6_11": 33.1,
    "VITA_12_59": 31.0,
    "DEWORM_1_14": 28.8,
    "HPV": 24.5,
    "UNDER5": 44.0,
    "YF": 35.0,
}
# Keys that are a supplied percentage rather than a count.
PERCENT_KEYS = {"KMC_PERCENT"}


def _formula_source_keys(formula: dict) -> set[str]:
    keys: set[str] = set()
    for value in formula.values():
        if isinstance(value, str) and value.isupper():
            keys.add(value)
        elif isinstance(value, list):
            keys.update(item for item in value if isinstance(item, str))
        elif isinstance(value, dict):
            keys.update(item for item in value.get("source_keys", []) if isinstance(item, str))
    return keys


def _catalogue_sources() -> list[tuple[str, str]]:
    """Every programme/source-key pair read by the approved catalogue.

    The programme is part of raw-data identity. Several death keys intentionally occur in both
    MNCH outcome indicators and MPDSR process indicators, so reducing this to one programme per key
    silently leaves part of the catalogue unavailable.
    """
    sources: set[tuple[str, str]] = set()
    for spec in INDICATOR_CATALOG:
        programme = str(spec["programme"])
        formula = spec.get("formula_spec") or {}
        sources.update((key, programme) for key in _formula_source_keys(formula))
    return sorted(sources)


def _catalogue_source_keys() -> list[str]:
    """Every distinct source key the approved catalogue reads."""
    return sorted({key for key, _programme in _catalogue_sources()})


def _period_index(period: str) -> int:
    return PERIODS.index(period) if period in PERIODS else 0


def _year_of(period: str) -> int:
    return 2024 + _period_index(period)


def seed_demo_analytics(session: Session, *, settings: Settings | None = None) -> dict:
    """Layer the demonstration dataset on the synthetic development seed. Never for production."""
    settings = settings or get_settings()
    if not settings.is_dev_or_test:
        raise RuntimeError("The demonstration dataset is available in development and test only.")
    geography = _extra_geography(session)
    version = _populations(session, geography)
    mappings = _source_mappings(session)
    values = _raw_values(session, geography, extracted_at=datetime.now(UTC).replace(microsecond=0))
    polygons = _geometry(session, geography)
    session.flush()
    return {
        "facilities": len(geography["facilities"]),
        "population_version": version.code,
        "source_mappings": mappings,
        "raw_values": values,
        "geometries": polygons,
        "periods": list(PERIODS),
    }


def _source_mappings(session: Session) -> int:
    """Fictional source mappings for the demonstration keys, so the data has a declared origin.

    Without them every calculation is flagged as unmapped, which says nothing useful about a
    dataset that never came from DHIS2. The identifiers are demonstration labels, not DHIS2 UIDs.
    """
    programmes = _programme_ids(session)
    written = 0
    for key, programme_code in _catalogue_sources():
        programme_id = programmes.get(programme_code)
        if programme_id is None:
            raise RuntimeError(f"Demonstration source requires missing programme {programme_code}.")
        existing = session.scalar(
            select(SourceMapping).where(
                SourceMapping.internal_source_key == key,
                SourceMapping.programme_id == programme_id,
                SourceMapping.mapping_version == "demo",
            )
        )
        if existing is not None:
            existing.dhis2_item_uid = f"DEMO_{key}"
            existing.item_kind = "data_element"
            existing.enabled = True
            existing.notes = "Synthetic demonstration mapping. Not a DHIS2 identifier."
            continue
        session.add(
            SourceMapping(
                internal_source_key=key,
                programme_id=programme_id,
                dhis2_item_uid=f"DEMO_{key}",
                item_kind="data_element",
                mapping_version="demo",
                enabled=True,
                notes="Synthetic demonstration mapping. Not a DHIS2 identifier.",
            )
        )
        written += 1
    session.flush()
    return written


def _unit(session: Session, code: str) -> OrgUnit | None:
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def _extra_geography(session: Session) -> dict:
    """Fictional sub-counties and facilities under the existing synthetic districts."""
    districts = {code: _unit(session, code) for code in DISTRICT_PROFILE}
    sub_counties: list[OrgUnit] = []
    facilities: list[tuple[OrgUnit, str, float, float]] = []
    for district_code, plan in FACILITY_PLAN.items():
        district = districts[district_code]
        if district is None:
            continue
        for sub_code, sub_name, facility_specs in plan:
            sub_county = _unit(session, sub_code)
            if sub_county is None:
                sub_county = create_org_unit(
                    session,
                    code=sub_code,
                    name=sub_name,
                    level_type=OrgUnitLevel.SUB_COUNTY,
                    parent=district,
                )
            sub_counties.append(sub_county)
            for name, level, share, performance in facility_specs:
                code = name.upper().replace(" ", "_")
                facility = _unit(session, code)
                if facility is None:
                    facility = session.scalar(select(OrgUnit).where(OrgUnit.name == name))
                if facility is None:
                    facility = create_org_unit(
                        session,
                        code=code,
                        name=name,
                        level_type=OrgUnitLevel.FACILITY,
                        parent=sub_county,
                        ownership="Government",
                        facility_level=level,
                    )
                facilities.append((facility, district_code, share, performance))
    session.flush()
    return {"districts": districts, "sub_counties": sub_counties, "facilities": facilities}


def _populations(session: Session, geography: dict) -> PopulationVersion:
    """A fictional, self-labelled population version for non-facility units only."""
    version = session.scalar(select(PopulationVersion).where(PopulationVersion.code == POPULATION_VERSION_CODE))
    if version is None:
        version = PopulationVersion(
            code=POPULATION_VERSION_CODE,
            name="Synthetic demonstration population — invented, not a national figure",
            source_name="SYNTHETIC_DEMONSTRATION_FIXTURE",
            population_type=PopulationType.PROJECTION.value,
            approval_status=ApprovalStatus.APPROVED.value,
            valid_from=date(2024, 1, 1),
            notes="Development and test demonstration only. Not an approved population source.",
        )
        session.add(version)
        session.flush()

    totals: dict[str, float] = {}
    for district_code, profile in DISTRICT_PROFILE.items():
        district = geography["districts"].get(district_code)
        if district is None:
            continue
        for year in YEARS:
            # A flat 3% annual growth keeps successive years distinguishable.
            population = profile["population"] * (1.03 ** (year - YEARS[0]))
            _put_population(session, version, district, year, round(population))
            totals[f"{district_code}:{year}"] = round(population)

    for sub_county in geography["sub_counties"]:
        parent = session.get(OrgUnit, sub_county.parent_id)
        siblings = [
            item
            for item in session.scalars(select(OrgUnit).where(OrgUnit.parent_id == parent.id)).all()
            if item.level_type == OrgUnitLevel.SUB_COUNTY.value
        ]
        share = 1 / max(len(siblings), 1)
        for year in YEARS:
            base = totals.get(f"{parent.code}:{year}", 0)
            _put_population(session, version, sub_county, year, round(base * share))

    for level in (OrgUnitLevel.SUB_REGION, OrgUnitLevel.COUNTRY):
        for unit in session.scalars(select(OrgUnit).where(OrgUnit.level_type == level.value)).all():
            for year in YEARS:
                children = session.scalars(select(OrgUnit).where(OrgUnit.parent_id == unit.id)).all()
                total = 0.0
                for child in children:
                    value = session.scalar(
                        select(PopulationValue.population).where(
                            PopulationValue.version_id == version.id,
                            PopulationValue.org_unit_id == child.id,
                            PopulationValue.year == year,
                        )
                    )
                    total += float(value or 0)
                if total:
                    _put_population(session, version, unit, year, round(total))
    return version


def _put_population(session: Session, version: PopulationVersion, unit: OrgUnit, year: int, value: float) -> None:
    existing = session.scalar(
        select(PopulationValue).where(
            PopulationValue.version_id == version.id,
            PopulationValue.org_unit_id == unit.id,
            PopulationValue.year == year,
        )
    )
    if existing is not None:
        existing.population = value
        return
    session.add(PopulationValue(version_id=version.id, org_unit_id=unit.id, year=year, population=value))
    session.flush()


def _programme_ids(session: Session) -> dict[str, object]:
    return {row.code: row.id for row in session.scalars(select(Programme)).all()}


def _raw_values(session: Session, geography: dict, *, extracted_at: datetime) -> int:
    """Facility-level source counts for every catalogue programme/key, period by period."""
    programmes = _programme_ids(session)
    sources = _catalogue_sources()
    written = 0
    for facility, district_code, share, facility_performance in geography["facilities"]:
        profile = DISTRICT_PROFILE[district_code]
        for period in PERIODS:
            index = _period_index(period)
            district_population = profile["population"] * (1.03**index)
            facility_population = district_population * share
            performance = profile["performance"] * facility_performance + profile["trend"] * index
            for key, programme_code in sources:
                value = _value_for(key, facility_population, performance, index)
                if value is None:
                    raise RuntimeError(f"Demonstration rate is missing for catalogue source {key}.")
                programme_id = programmes.get(programme_code)
                if programme_id is None:
                    raise RuntimeError(f"Demonstration source requires missing programme {programme_code}.")
                _put_raw(session, facility, period, key, value, programme_id, extracted_at)
                written += 1
    return written


def _value_for(key: str, population: float, performance: float, index: int) -> float | None:
    rate = KEY_RATE.get(key)
    if rate is None:
        return None
    if key in PERCENT_KEYS:
        # A supplied percentage, held inside a sensible range.
        return round(min(98.0, max(35.0, rate * performance)), 1)
    expected = population * rate / 1000.0
    value = expected * performance
    if key in {"MATERNAL_DEATHS", "FRESH_SB", "MACERATED_SB", "NEWBORN_DEATHS"}:
        # Rarer events improve as performance rises, and stay small whole numbers.
        value = expected * (2.0 - min(performance, 1.4))
    return float(max(0, round(value)))


def _put_raw(
    session: Session,
    unit: OrgUnit,
    period: str,
    key: str,
    value: float,
    programme_id,
    extracted_at: datetime,
) -> None:
    existing_rows = list(
        session.scalars(
            select(RawAggregateValue).where(
                RawAggregateValue.source_system == SOURCE_SYSTEM,
                RawAggregateValue.programme_id == programme_id,
                RawAggregateValue.org_unit_id == unit.id,
                RawAggregateValue.period == period,
                RawAggregateValue.internal_source_key == key,
                RawAggregateValue.category_option_combo_uid.is_(None),
                RawAggregateValue.is_current.is_(True),
            )
        ).all()
    )
    if len(existing_rows) > 1:
        raise RuntimeError(f"Duplicate current demonstration rows for {unit.code}/{period}/{key}/{programme_id}.")
    existing = existing_rows[0] if existing_rows else None
    if existing is not None:
        existing.value = value
        existing.source_metric_id = f"DEMO_{key}"
        existing.dhis2_item_uid = f"DEMO_{key}"
        existing.mapping_version = "demo"
        existing.checksum = "synthetic-demo"
        # extracted_at is deliberately preserved: the fixture keeps the provenance of its first
        # seeding, so re-seeding is idempotent and the rows do not silently refresh themselves.
        return
    session.add(
        RawAggregateValue(
            source_system=SOURCE_SYSTEM,
            programme_id=programme_id,
            org_unit_id=unit.id,
            period=period,
            source_metric_id=f"DEMO_{key}",
            internal_source_key=key,
            dhis2_item_uid=f"DEMO_{key}",
            value=value,
            extracted_at=extracted_at,
            mapping_version="demo",
            is_current=True,
            checksum="synthetic-demo",
        )
    )
    session.flush()


# Crude invented outlines inside Uganda's bounding box. They are stylised shapes for a
# demonstration map, not administrative boundaries, and they carry no approval; sub-counties and
# facilities deliberately have none.
DEMO_POLYGONS = {
    "ACHOLI": [
        (31.95, 2.72), (32.60, 2.58), (33.18, 2.66), (33.42, 2.95), (33.30, 3.34),
        (32.96, 3.62), (32.42, 3.78), (31.98, 3.55), (31.82, 3.12),
    ],
    "TESO": [
        (33.10, 1.32), (33.72, 1.22), (34.28, 1.44), (34.44, 1.82), (34.22, 2.24),
        (33.70, 2.42), (33.18, 2.26), (32.98, 1.82),
    ],
    "PADER": [
        (32.66, 2.74), (33.16, 2.68), (33.38, 2.98), (33.24, 3.30), (32.86, 3.42), (32.60, 3.16),
    ],
    "KITGUM": [
        (32.00, 2.98), (32.52, 2.86), (32.66, 3.24), (32.48, 3.62), (32.06, 3.58), (31.88, 3.24),
    ],
    "SOROTI": [
        (33.16, 1.40), (33.78, 1.30), (34.24, 1.54), (34.30, 1.96), (33.88, 2.24), (33.32, 2.10),
    ],
}


def _geometry(session: Session, geography: dict) -> int:
    written = 0
    for code, ring in DEMO_POLYGONS.items():
        unit = _unit(session, code)
        if unit is None:
            continue
        existing = session.scalar(select(Geometry).where(Geometry.org_unit_id == unit.id, Geometry.valid_to.is_(None)))
        if existing is not None:
            continue
        session.add(
            Geometry(
                org_unit_id=unit.id,
                geojson={"type": "Polygon", "coordinates": [[list(point) for point in ring] + [list(ring[0])]]},
                geometry_kind="polygon",
                source=SOURCE_SYSTEM,
                valid_from=GEOMETRY_VALID_FROM,
            )
        )
        written += 1
    session.flush()
    return written
