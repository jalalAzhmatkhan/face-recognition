"""CLI entry point for the training pipeline (TR-01 scaffold).

Subcommands map 1:1 to pipeline stages; each is a stub until its task lands.
Stdlib ``argparse`` keeps the CLI dependency-free.
"""

from __future__ import annotations

import argparse
import sys

from ai_training import __version__
from ai_training.config import get_settings
from ai_training.data.snapshots import build_snapshot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-training",
        description="Face Recognition Access Control - training pipeline CLI.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("config", help="Print the resolved (non-secret) configuration.")

    snapshot = sub.add_parser("snapshot", help="Build a dataset snapshot manifest (TR-04).")
    snapshot.add_argument(
        "--filter",
        action="append",
        default=[],
        help="key=value filter, repeatable (supported keys: external_ref, "
        "created_after, created_before, kind)",
    )

    eda = sub.add_parser("eda", help="Build an EDA report for a dataset snapshot (TR-05).")
    eda.add_argument("--snapshot-id", required=True)

    finetune = sub.add_parser("finetune", help="Run a fine-tuning job (TR-06).")
    finetune.add_argument("--snapshot-id", required=True)

    evaluate = sub.add_parser("evaluate", help="Run the frozen benchmark (TR-07).")
    evaluate.add_argument("--model-version", required=True)
    evaluate.add_argument("--benchmark-id", required=True)

    return parser


def _parse_filters(raw_filters: list[str]) -> dict[str, str]:
    filters: dict[str, str] = {}
    for item in raw_filters:
        if "=" not in item:
            raise ValueError(f"--filter must be key=value, got: {item!r}")
        key, _, value = item.partition("=")
        filters[key] = value
    return filters


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "config":
        settings = get_settings()
        # DSN may carry credentials from the environment - never print it.
        printable = settings.model_dump()
        printable["db"]["dsn"] = "***" if settings.db.dsn else ""
        print(printable)
        return 0

    if args.command == "snapshot":
        settings = get_settings()
        try:
            filters = _parse_filters(args.filter)
            snapshot = build_snapshot(settings, filters)
        except ValueError as exc:
            print(f"snapshot: {exc}", file=sys.stderr)
            return 2
        print(snapshot.snapshot_id)
        return 0

    if args.command == "eda":
        from ai_training.eda.report import build_eda_report

        settings = get_settings()
        build_eda_report(settings, args.snapshot_id)
        print(f"eda report written: datasets/{args.snapshot_id}/eda_report.json and eda_report.md")
        return 0

    # Stage stubs: implemented by TR-06/TR-07.
    print(f"'{args.command}' is not implemented yet (scaffold TR-01).", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
