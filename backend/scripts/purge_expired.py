"""Delete data whose retention window has passed.

Same service as the Celery maintenance task and the scheduled Render job; there is only one
purge implementation. Prints counts and safe status codes, never deleted content or file paths.

Usage:
    python scripts/purge_expired.py                    # every policy
    python scripts/purge_expired.py --dry-run          # report only, writes nothing
    python scripts/purge_expired.py --policy mpdsr_events --policy export_files
    python scripts/purge_expired.py --json             # machine-readable summary
    python scripts/purge_expired.py --source scheduler --max-attempts 3 --retry-delay-seconds 120

Exit status is non-zero when any requested policy is still failed after the last attempt. A
policy skipped because another process holds its lease is not a failure.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.domain.retention import POLICY_ORDER, policy_summary  # noqa: E402
from app.services.purge import failed_results, purge_expired  # noqa: E402


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
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=1,
        choices=range(1, 6),
        metavar="{1..5}",
        help="Retry failed policies up to this many attempts in total (default 1).",
    )
    parser.add_argument("--retry-delay-seconds", type=int, default=60, help="Wait between attempts (default 60).")
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.show_policies:
        print(json.dumps(policy_summary(settings), indent=2))
        return 0

    names = args.policy
    everything: list = []
    failed: list = []
    for attempt in range(1, args.max_attempts + 1):
        session = get_session_factory()()
        try:
            results = purge_expired(
                session,
                policy_names=names,
                settings=settings,
                dry_run=True if args.dry_run else None,
                source=args.source,
                attempt=attempt,
            )
        finally:
            session.close()
        everything.extend(results)
        _report(results, attempt, as_json=args.json)
        failed = failed_results(results)
        if not failed or attempt == args.max_attempts:
            break
        names = [item.policy for item in failed]
        time.sleep(max(args.retry_delay_seconds, 0))
    if failed:
        print(f"Retention purge failed after {args.max_attempts} attempt(s): {', '.join(i.policy for i in failed)}")
        return 1
    return 0


def _report(results: list, attempt: int, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps([item.as_dict() for item in results], indent=2))
        return
    mode = "DRY RUN (nothing written)" if any(item.dry_run for item in results) else "purge"
    print(f"Retention {mode}, attempt {attempt}")
    for item in results:
        print(
            f"  {item.policy:<22} {item.status:<14} "
            f"examined={item.rows_examined:<6} deleted={item.rows_deleted:<6} "
            f"files={item.files_deleted:<4} absent={item.files_absent:<4} failed_files={item.files_failed:<4} "
            f"skipped={item.rows_skipped:<4} batches={item.batches}"
            + (f" error={item.error_code}" if item.error_code else "")
        )


if __name__ == "__main__":
    sys.exit(main())
