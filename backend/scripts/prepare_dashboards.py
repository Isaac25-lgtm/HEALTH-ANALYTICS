"""Warm authorised default dashboards from stored governed data, never from a demo fixture.

Run from backend: python -m scripts.prepare_dashboards [--programme MNCH|EPI|MPDSR].
This writes derived runs/private snapshots and may queue scoped facility loads when enabled.
Apply and verify migrations first; it does not bootstrap users, populations or source mappings.
"""

import argparse
import json

from app.services.dashboard_precompute import prepare_default_dashboards


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--programme", choices=["MNCH", "EPI", "MPDSR"])
    args = parser.parse_args(argv)
    print(json.dumps(prepare_default_dashboards(args.programme)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
