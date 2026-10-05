"""Operator recovery for queued/unpublished work. Does not itself extract DHIS2 data."""

import argparse
import json

from app.db.session import get_session_factory
from app.services.sync_recovery import recover_sync_dispatch


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)
    with get_session_factory()() as session:
        result = recover_sync_dispatch(session, limit=args.limit)
    print(json.dumps(result, sort_keys=True))
    return 1 if result["publication_failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
