"""E2-C1 campaign with high-fidelity regen cooling analysis.

Thin wrapper around the campaign runner — see campaigns/e2_c1/e2_regen.yaml.
"""
from __future__ import annotations

import sys

from resa.campaign import run_campaign


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    run_campaign("campaigns/e2_c1/e2_regen.yaml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
