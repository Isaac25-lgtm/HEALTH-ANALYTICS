"""Synthetic boundary fixtures shared by the SQLite and PostgreSQL governance tests.

All names, codes and coordinates are invented. They exercise the approval gate only and are not
Uganda boundaries.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from app.domain.enums import OrgUnitLevel
from app.models import OrgUnit
from app.services.geography import create_org_unit

APPROVAL = "TEST-ONLY-BOUNDARY-HIERARCHY-APPROVAL"
EFFECTIVE_DATE_REFERENCE = "TEST-ONLY-EFFECTIVE-DATE-APPROVAL"
MAPPING_REFERENCE = "TEST-ONLY-MAPPING-DECISION"
PARTIAL_REFERENCE = "TEST-ONLY-PARTIAL-ACTIVATION"


def district_names(count: int = 146) -> list[str]:
    return [f"Boundary District {index:03d}" for index in range(count)]


def create_cohort(session, count: int = 146) -> list[str]:
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    names = district_names(count)
    for index, name in enumerate(names):
        create_org_unit(
            session, code=f"TEST_BND_{index:03d}", name=name, level_type=OrgUnitLevel.DISTRICT, parent=uganda
        )
    session.commit()
    return names


def polygon(index: int) -> dict:
    x = 30.0 + (index % 20) * 0.1
    y = 0.0 + (index // 20) * 0.1
    return {"type": "Polygon", "coordinates": [[[x, y], [x + 0.05, y], [x + 0.05, y + 0.05], [x, y]]]}


def write_geojson(path: Path, names: list[str], *, property_name: str = "District", extra: dict | None = None) -> Path:
    features = []
    for index, name in enumerate(names):
        properties = {property_name: name, **(extra or {})}
        features.append({"type": "Feature", "properties": properties, "geometry": polygon(index)})
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    return path
