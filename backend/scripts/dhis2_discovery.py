"""Read-only DHIS2 metadata discovery and mapping-proposal generation.

The command uses the operator's configured endpoint and credentials only after explicit network
confirmation. A successful request proves that host's capability at that time; it does not approve
or apply any discovered mapping.

Safety properties:
  * refuses unless DHIS2_ENABLED=true and the configuration is complete;
  * refuses to touch the network without --confirm-network-access (default is --dry-run);
  * GET only, with bounded pagination, timeouts and a response-size limit;
  * metadata only: identifiers, names and structures, never patient or event data;
  * redacted logging: no credentials, no raw response bodies;
  * output is a mapping *proposal* for review, never an applied mapping.

Usage once authorised:
    python scripts/dhis2_discovery.py --resource org-unit-levels --dry-run
    python scripts/dhis2_discovery.py --resource data-elements --confirm-network-access --out proposals.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings, validate_runtime_settings  # noqa: E402
from app.integrations.dhis2.errors import Dhis2Error, Dhis2ValidationError  # noqa: E402
from app.integrations.dhis2.http import Dhis2HttpClient  # noqa: E402

# Read-only metadata endpoints, with the fields discovery needs and nothing more.
RESOURCES: dict[str, dict] = {
    "me": {"path": "/me", "fields": "id,username,displayName,authorities", "singleton": True},
    "system-info": {"path": "/system/info", "fields": None},
    "org-unit-levels": {
        "path": "/organisationUnitLevels",
        "fields": "id,name,level",
        "collection": "organisationUnitLevels",
    },
    "org-units": {
        "path": "/organisationUnits",
        "fields": "id,code,name,shortName,level,path,parent[id,name],openingDate,closedDate",
        "collection": "organisationUnits",
    },
    "data-elements": {
        "path": "/dataElements",
        "fields": "id,code,name,shortName,valueType,domainType,aggregationType,categoryCombo[id,name]",
        "collection": "dataElements",
    },
    "indicators": {
        "path": "/indicators",
        "fields": "id,code,name,shortName,numeratorDescription,denominatorDescription,annualized",
        "collection": "indicators",
    },
    "category-combos": {
        "path": "/categoryCombos",
        "fields": "id,code,name,categories[id,name]",
        "collection": "categoryCombos",
    },
    "category-options": {
        "path": "/categoryOptionCombos",
        "fields": "id,code,name,categoryOptions[id,name]",
        "collection": "categoryOptionCombos",
    },
    "programs": {
        "path": "/programs",
        "fields": "id,code,name,shortName,programType,trackedEntityType[id,name]",
        "collection": "programs",
    },
    "program-stages": {
        "path": "/programStages",
        "fields": "id,code,name,program[id,name]",
        "collection": "programStages",
    },
    "program-stage-data-elements": {
        "path": "/programStageDataElements",
        "fields": "id,programStage[id,name],dataElement[id,name,valueType]",
        "collection": "programStageDataElements",
    },
}


def _blocked_reasons(settings) -> list[str]:
    reasons: list[str] = []
    if not settings.dhis2_enabled:
        reasons.append("DHIS2_ENABLED is false: DHIS2 access is switched off for this deployment.")
    reasons.extend(
        error for error in validate_runtime_settings(settings) if "DHIS2" in error
    )
    return reasons


def _fetch_resource(
    client: Dhis2HttpClient,
    *,
    api_prefix: str,
    name: str,
    page_size: int,
    max_pages: int,
) -> dict:
    spec = RESOURCES[name]
    path = f"{api_prefix.rstrip('/')}{spec['path']}"
    fields = spec.get("fields")
    if spec.get("singleton") or "collection" not in spec:
        params = {"fields": fields} if fields else None
        return {"items": [client.get_json(path, params=params)], "pages": 1, "truncated": False}

    collection = str(spec["collection"])
    items: list[dict] = []
    page = 1
    fetched_pages = 0
    truncated = False
    while page <= max_pages:
        params: dict[str, object] = {"page": page, "pageSize": page_size, "paging": "true"}
        if fields:
            params["fields"] = fields
        payload = client.get_json(path, params=params)
        rows = payload.get(collection)
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise Dhis2ValidationError(f"DHIS2 metadata response for {name} has no valid {collection} collection.")
        items.extend(rows)
        fetched_pages += 1
        pager = payload.get("pager") if isinstance(payload.get("pager"), dict) else {}
        page_count = int(pager.get("pageCount") or page)
        if page >= page_count:
            break
        page += 1
    else:
        truncated = True
    if page >= max_pages and page < int((pager or {}).get("pageCount") or page):
        truncated = True
    return {"items": items, "pages": fetched_pages, "truncated": truncated}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--resource", choices=sorted(RESOURCES), action="append")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument(
        "--confirm-network-access",
        action="store_true",
        help="Required for any request to leave this machine. Without it nothing is sent.",
    )
    parser.add_argument("--out", type=Path, help="Write the proposal document to this path.")
    args = parser.parse_args(argv)
    if args.page_size < 1 or args.max_pages < 1:
        parser.error("--page-size and --max-pages must both be positive integers")

    settings = get_settings()
    resources = args.resource or ["me", "system-info", "org-unit-levels"]
    plan = {
        "mode": "dry_run",
        "base_url": settings.dhis2_base_url or "(not configured)",
        "auth_method": settings.dhis2_auth_method,
        "http_methods": ["GET"],
        "page_size": min(args.page_size, settings.dhis2_page_size),
        "max_pages": min(args.max_pages, settings.dhis2_max_pages),
        "timeout_seconds": settings.dhis2_timeout_seconds,
        "max_response_bytes": settings.dhis2_max_response_bytes,
        "requests": [
            {
                "resource": name,
                "path": f"{settings.dhis2_api_path_prefix}{RESOURCES[name]['path']}",
                "fields": RESOURCES[name]["fields"],
            }
            for name in resources
        ],
        "output": "mapping proposals for review; nothing is applied or approved automatically",
        "credentials_in_output": False,
    }

    blocked = _blocked_reasons(settings)
    if blocked:
        plan["mode"] = "blocked"
        plan["blocked_reasons"] = blocked
        print(json.dumps(plan, indent=2))
        return 3
    if not args.confirm_network_access:
        plan["note"] = "Dry run only. Re-run with --confirm-network-access to contact DHIS2."
        print(json.dumps(plan, indent=2))
        return 0

    proposal = {
        "schema": "hpip.dhis2.metadata-proposal.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "base_url": settings.dhis2_base_url,
        "applied": False,
        "approval_required": True,
        "resources": {},
    }
    try:
        with Dhis2HttpClient(settings) as client:
            for name in resources:
                proposal["resources"][name] = _fetch_resource(
                    client,
                    api_prefix=settings.dhis2_api_path_prefix,
                    name=name,
                    page_size=plan["page_size"],
                    max_pages=plan["max_pages"],
                )
    except Dhis2Error as exc:
        print(json.dumps({**plan, "mode": "failed", "error_code": exc.code, "error": exc.message}, indent=2))
        return 4

    truncated = [name for name, result in proposal["resources"].items() if result["truncated"]]
    summary = {
        "mode": "completed" if not truncated else "partial",
        "output": str(args.out) if args.out else "stdout",
        "resource_counts": {
            name: len(result["items"]) for name, result in proposal["resources"].items()
        },
        "truncated_resources": truncated,
        "credentials_in_output": False,
        "applied": False,
    }
    document = json.dumps(proposal, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(document + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2))
    else:
        print(document)
    return 5 if truncated else 0


if __name__ == "__main__":
    raise SystemExit(main())
