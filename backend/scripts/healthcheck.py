"""Container healthcheck for the API.

Sends an allowed Host header, because staging/production reject hosts outside ALLOWED_HOSTS.
Prints nothing on success and never prints configuration values.
"""

from __future__ import annotations

import os
import sys
import urllib.request


def main() -> int:
    host = os.environ.get("HEALTHCHECK_HOST") or os.environ.get("ALLOWED_HOSTS", "localhost").split(",")[0].strip()
    port = os.environ.get("API_PORT", "8000")
    request = urllib.request.Request(f"http://127.0.0.1:{port}/health", headers={"Host": host or "localhost"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return 0 if response.status == 200 else 1
    except Exception:  # noqa: BLE001
        return 1


if __name__ == "__main__":
    sys.exit(main())
