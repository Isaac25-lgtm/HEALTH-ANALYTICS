"""Scheduled DHIS2 refresh. PREPARED BUT INERT.

The owner's refresh decision is a six-hourly pass over recent, still-open periods, never
continuous polling and never a repeated sweep of closed historical periods. This command is the
scheduled entry point for that, and it is wired into render.yaml.

It cannot contact DHIS2 until DHIS2_ENABLED and SYNC_ENABLED are both true and the DHIS2
configuration is complete. Until then it reports what it would do and exits 0, so a scheduled
job on a pre-DHIS2 deployment is quiet rather than noisy or misleading.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings, validate_runtime_settings  # noqa: E402
from app.domain.periods import uganda_fy_key  # noqa: E402

# Refresh only periods that can still change.
RECENT_MONTHS = 3


def _recent_periods(today: date) -> list[str]:
    periods: list[str] = []
    year, month = today.year, today.month
    for _ in range(RECENT_MONTHS):
        periods.append(f"{year}{month:02d}")
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    periods.append(uganda_fy_key(today))
    return periods


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scheduled", action="store_true", help="Run as the scheduled six-hourly job.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    today = datetime.now(UTC).date()
    plan = {
        "mode": "inert",
        "scheduled": bool(args.scheduled),
        "cadence": "every six hours for recent, still-open periods",
        "periods_that_would_refresh": _recent_periods(today),
        "closed_periods_refreshed": False,
        "continuous_polling": False,
        "dhis2_enabled": settings.dhis2_enabled,
        "sync_enabled": settings.sync_enabled,
        "blocked_reasons": [],
    }
    if not settings.dhis2_enabled:
        plan["blocked_reasons"].append("DHIS2_ENABLED is false.")
    if not settings.sync_enabled:
        plan["blocked_reasons"].append("SYNC_ENABLED is false.")
    plan["blocked_reasons"].extend(error for error in validate_runtime_settings(settings) if "DHIS2" in error)

    if plan["blocked_reasons"]:
        print(json.dumps(plan, indent=2) if args.json else
              "DHIS2 refresh is not enabled; nothing was contacted. " + "; ".join(plan["blocked_reasons"]))
        return 0

    # Authorised synchronisation would enqueue bounded sync jobs here, through the existing
    # queue. It stays unimplemented on purpose: live DHIS2 access is not authorised, and the
    # first real run must be an owner-supervised bounded validation.
    plan["mode"] = "not_executed"
    plan["note"] = (
        "DHIS2 is enabled in configuration, but automatic scheduled synchronisation is not "
        "switched on in this build. Run a bounded validation under owner supervision first."
    )
    print(json.dumps(plan, indent=2) if args.json else plan["note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
