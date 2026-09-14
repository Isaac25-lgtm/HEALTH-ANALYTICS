"""Read-only DHIS2 metadata discovery. PREPARED, NOT RUN.

The host is known (https://hmis.health.go.ug) but nothing is connected: there are no
credentials, no verified mappings and no authenticated capability check. This command exists so
that discovery, when it is finally authorised, is bounded, auditable and read-only.

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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings, validate_runtime_settings  # noqa: E402

# Read-only metadata endpoints, with the fields discovery needs and nothing more.
RESOURCES: dict[str, dict] = {
    "me": {"path": "/me", "fields": "id,username,authorities"},
    "system-info": {"path": "/system/info", "fields": None},
    "org-unit-levels": {"path": "/organisationUnitLevels", "fields": "id,name,level"},
    "org-units": {"path": "/organisationUnits", "fields": "id,name,level,parent[id,name]"},
    "data-elements": {"path": "/dataElements", "fields": "id,name,shortName,valueType,domainType"},
    "indicators": {"path": "/indicators", "fields": "id,name,numeratorDescription,denominatorDescription"},
    "category-combos": {"path": "/categoryCombos", "fields": "id,name,categories[id,name]"},
    "category-options": {"path": "/categoryOptionCombos", "fields": "id,name"},
    "programs": {"path": "/programs", "fields": "id,name,programType"},
    "program-stages": {"path": "/programStages", "fields": "id,name,program[id,name]"},
    "program-stage-data-elements": {
        "path": "/programStageDataElements",
        "fields": "id,programStage[id,name],dataElement[id,name,valueType]",
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

    # Authorised discovery would execute here, through the bounded, redacting HTTP client in
    # app/integrations/dhis2/http.py. It is deliberately not implemented as an automatic path:
    # the first authenticated call must be made by the owner, with the proposal reviewed
    # afterwards.
    plan["mode"] = "not_executed"
    plan["note"] = (
        "Network access was confirmed, but automated discovery is intentionally not enabled in "
        "this build. Run it only under owner supervision once credentials are issued."
    )
    print(json.dumps(plan, indent=2))
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
