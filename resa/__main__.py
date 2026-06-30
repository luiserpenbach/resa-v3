"""RESA command line.

    python -m resa run       configs/e2_c1/design.yaml
    python -m resa report    configs/e2_c1/design.yaml
    python -m resa campaign  campaigns/e2.yaml
    python -m resa diff      out/A_xxx out/B_yyy
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from .campaign import run_campaign
from .config.loader import load_config
from .pipeline import run
from .reporting.diff import diff_folders
from .reporting.report import write_report


def _cmd_run(args) -> None:
    res = run(load_config(args.config))
    print(json.dumps(res.summary(), indent=2))


def _cmd_report(args) -> None:
    rollup = []
    for cfg_path in args.configs:
        cfg = load_config(cfg_path)
        res = run(cfg)
        outdir, res = write_report(res, cfg, cfg_path, out_root=args.out)
        print(f"  {cfg_path} -> {outdir}")
        rollup.append(res.summary())

    if len(rollup) > 1:
        keys = list({k for row in rollup for k in row})
        rollup_path = Path(args.out) / "campaign_rollup.csv"
        with rollup_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rollup)
        print(f"\nrollup -> {rollup_path}")


def _cmd_campaign(args) -> None:
    run_campaign(args.campaign, out_root=args.out, verbose=not args.quiet)


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="resa")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="run pipeline, print summary")
    pr.add_argument("config")
    pr.set_defaults(func=_cmd_run)

    pd = sub.add_parser("diff", help="compare two report folders")
    pd.add_argument("folder_a")
    pd.add_argument("folder_b")
    pd.set_defaults(func=lambda a: print(diff_folders(a.folder_a, a.folder_b)))

    pp = sub.add_parser("report", help="run pipeline, write report folder(s)")
    pp.add_argument("configs", nargs="+")
    pp.add_argument("--out", default="out", help="output root (default: out/)")
    pp.set_defaults(func=_cmd_report)

    pc = sub.add_parser("campaign", help="run a campaign YAML (multi-config reports)")
    pc.add_argument("campaign", help="path to campaigns/*.yaml")
    pc.add_argument("--out", default=None, help="override campaign output directory")
    pc.add_argument("-q", "--quiet", action="store_true", help="less console output")
    pc.set_defaults(func=_cmd_campaign)

    args = p.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
