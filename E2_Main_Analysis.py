"""E2-1A campaign: run the full RESA pipeline and write all report artifacts.

Thin wrapper around the campaign runner — see campaigns/E2-1A/e2_1a.yaml.
"""
from __future__ import annotations

import sys

from resa.campaign import run_campaign


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    run_campaign("campaigns/E2-1A/e2_1a.yaml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
