"""Authorised global search for the dashboard header.

Results are restricted in the database query itself:

- organisation units: only active units inside the caller's current geography grants (path
  prefix), never siblings or ancestors outside them;
- indicators: only active catalogue indicators whose programme the caller may access, returned
  with the module that displays them.

It never searches MPDSR events, users, populations, mappings or free text, and the query is
treated as a literal (SQL wildcards are escaped). Short queries return nothing.
"""

from __future__ import annotations

import re

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.domain.enums import ActionPermission
from app.domain.modules import MODULE_INDICATORS
from app.models import Indicator, OrgUnit, Programme, User
from app.services.authorization import (
    authorised_programme_ids,
    geography_scope_units,
    require_action,
)
from app.services.geography import escape_like

MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 60
MAX_RESULTS = 8

MODULE_FOR_INDICATOR = {code: module for module, codes in MODULE_INDICATORS.items() for code in codes}


def _literal_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped.lower()}%"


def normalise_query(raw: str | None) -> str:
    return re.sub(r"\s+", " ", (raw or "")).strip()[:MAX_QUERY_LENGTH]


def scoped_search(session: Session, user: User, raw_query: str | None, *, limit: int = MAX_RESULTS) -> dict:
    require_action(session, user, ActionPermission.VIEW)
    query = normalise_query(raw_query)
    limit = max(1, min(limit, MAX_RESULTS))
    result: dict = {"query": query, "org_units": [], "indicators": []}
    if len(query) < MIN_QUERY_LENGTH:
        return result
    pattern = _literal_pattern(query)

    unit_filter = [
        OrgUnit.active.is_(True),
        or_(
            func.lower(OrgUnit.name).like(pattern, escape="\\"),
            func.lower(OrgUnit.code).like(pattern, escape="\\"),
        ),
    ]
    if not user.is_system_admin:
        scopes = geography_scope_units(session, user)
        if not scopes:
            unit_filter.append(OrgUnit.id.is_(None))
        else:
            unit_filter.append(
                or_(
                    *[
                        or_(
                            OrgUnit.path == scope.path,
                            OrgUnit.path.like(escape_like(scope.path.rstrip("/") + "/") + "%", escape="\\"),
                        )
                        for scope in scopes
                    ]
                )
            )
    units = session.scalars(select(OrgUnit).where(*unit_filter).order_by(OrgUnit.name, OrgUnit.code).limit(limit)).all()
    result["org_units"] = [
        {"id": str(unit.id), "code": unit.code, "name": unit.name, "level_type": unit.level_type} for unit in units
    ]

    programme_ids = authorised_programme_ids(session, user)
    if programme_ids:
        rows = session.execute(
            select(Indicator.code, Indicator.name, Programme.code)
            .join(Programme, Programme.id == Indicator.programme_id)
            .where(
                Indicator.active.is_(True),
                Indicator.programme_id.in_(programme_ids),
                or_(
                    func.lower(Indicator.name).like(pattern, escape="\\"),
                    func.lower(Indicator.code).like(pattern, escape="\\"),
                ),
            )
            .order_by(Indicator.name)
            .limit(limit * 2)
        ).all()
        result["indicators"] = [
            {"code": code, "name": name, "programme": programme, "module": MODULE_FOR_INDICATOR[code]}
            for code, name, programme in rows
            if code in MODULE_FOR_INDICATOR
        ][:limit]
    return result
