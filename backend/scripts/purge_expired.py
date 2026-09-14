"""Delete data whose retention window has passed.

Same service as the Celery maintenance task and the scheduled Render job; there is only one
purge implementation. Prints counts and safe status codes, never deleted content or file paths.

Usage:
    python scripts/purge_expired.py                    # every policy
    python scripts/purge_expired.py --dry-run          # report only, writes nothing
    python scripts/purge_expired.py --policy mpdsr_events --policy export_files
    python scripts/purge_expired.py --json             # machine-readable summary
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.domain.retention import POLICY_ORDER, policy_summary  # noqa: E402
from app.services.purge import STATUS_FAILED, purge_expired  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Report what would be deleted; change nothing.")
    parser.add_argument(
        "--policy",
        action="append",
        choices=list(POLICY_ORDER),
        help="Limit to one or more policies (default: all).",
    )
    parser.add_argument("--source", default="cli", choices=["cli", "scheduler", "admin"])
    parser.add_argument("--json", action="store_true", help="Print a JSON summary.")
    parser.add_argument("--show-policies", action="store_true", help="Print the active windows and exit.")
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.show_policies:
        print(json.dumps(policy_summary(settings), indent=2))
        return 0

    session = get_session_factory()()
    try:
        results = purge_expired(
            session,
            policy_names=args.policy,
            settings=settings,
            dry_run=True if args.dry_run else None,
            source=args.source,
        )
    finally:
        session.close()

    if args.json:
        print(json.dumps([item.as_dict() for item in results], indent=2))
    else:
        mode = "DRY RUN (nothing written)" if any(item.dry_run for item in results) else "purge"
        print(f"Retention {mode}")
        for item in results:
            print(
                f"  {item.policy:<22} {item.status:<14} "
                f"examined={item.rows_examined:<6} deleted={item.rows_deleted:<6} "
                f"files={item.files_deleted:<4} skipped={item.rows_skipped:<4} batches={item.batches}"
                + (f" error={item.error_code}" if item.error_code else "")
            )
    return 1 if any(item.status == STATUS_FAILED for item in results) else 0


if __name__ == "__main__":
    sys.exit(main())
