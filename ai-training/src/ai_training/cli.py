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

    slice_catalog = sub.add_parser(
        "slice-catalog",
        help="List the edge-case benchmark slice catalog (EC-TR-01, TSD-EC D-7.1).",
    )
    slice_catalog.add_argument(
        "--slice", default=None, help="Print detail (spec + skeleton manifest) for one slice."
    )

    build_synthetic_slice = sub.add_parser(
        "build-synthetic-slice",
        help="Build + upload a SMALL synthetic placeholder slice manifest (EC-TR-01). "
        "Proves the harness plumbing works; NOT a substitute for EC-OPS-02 real data - "
        "see ai_training.evaluation.synthetic_slices module docstring.",
    )
    build_synthetic_slice.add_argument(
        "--slice", required=True, choices=["dark", "blur", "low-res", "masked-sintetis"]
    )
    build_synthetic_slice.add_argument("--version", required=True)
    build_synthetic_slice.add_argument("--n-identities", type=int, default=8)
    build_synthetic_slice.add_argument("--probes-per-identity", type=int, default=3)

    download_weights = sub.add_parser(
        "download-adaface-weights",
        help="Download + normalize the AdaFace pretrained checkpoint (TR-06). "
        "Requires the 'ml' extra (gdown, torch).",
    )
    download_weights.add_argument(
        "--arch", default="ir_101", help="AdaFace arch tag, e.g. ir_101 (default) or ir_50."
    )
    download_weights.add_argument(
        "--output", default=None, help="Override the default ai-training/models/... output path."
    )

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

    if args.command == "evaluate":
        from ai_training.evaluation.metrics import evaluate_candidate

        settings = get_settings()
        report = evaluate_candidate(settings, args.model_version, args.benchmark_id)
        print(report.model_dump_json(indent=2))
        return 0

    if args.command == "slice-catalog":
        from ai_training.evaluation.slices import SLICE_CATALOG, skeleton_manifest

        if args.slice:
            if args.slice not in SLICE_CATALOG:
                print(f"slice-catalog: unknown slice {args.slice!r}", file=sys.stderr)
                return 2
            spec = SLICE_CATALOG[args.slice]
            print(spec.model_dump_json(indent=2))
            print(skeleton_manifest(args.slice).model_dump_json(indent=2))
            return 0
        for name, spec in SLICE_CATALOG.items():
            tag = "GATE" if spec.is_gate else ("SMOKE" if spec.is_smoke_test else "report-only")
            data = "synthesizable" if spec.synthesizable else "needs-real-data(EC-OPS-02)"
            print(f"{name:20s} [{tag:11s}] [{data}] - {spec.description}")
        return 0

    if args.command == "build-synthetic-slice":
        from ai_training.evaluation.slices import SLICE_CATALOG, SliceManifest, save_slice_manifest
        from ai_training.evaluation.synthetic_slices import build_synthetic_slice_crops

        settings = get_settings()
        spec = SLICE_CATALOG[args.slice]
        genuine, impostor = build_synthetic_slice_crops(
            args.slice,
            n_identities=args.n_identities,
            probes_per_identity=args.probes_per_identity,
        )
        genuine_probe_count = sum(len(crops) for crops in genuine.values())
        # Every genuine probe compared against every OTHER identity's
        # gallery template, plus every impostor probe vs every identity -
        # a crude pairwise comparison count for reporting purposes only
        # (the real evaluate_slice_e2e run computes actual FPIR directly).
        impostor_comparisons = len(impostor) * len(genuine)
        manifest = SliceManifest(
            slice_name=args.slice,
            version=args.version,
            category=args.slice,
            is_gate=spec.is_gate,
            is_smoke_test=spec.is_smoke_test,
            report_only=spec.report_only,
            data_status="synthetic_placeholder",
            generation={
                "method": "ai_training.evaluation.synthetic_slices",
                "n_identities": args.n_identities,
                "probes_per_identity": args.probes_per_identity,
            },
            genuine_identity_count=len(genuine),
            genuine_probe_count=genuine_probe_count,
            impostor_comparison_count=impostor_comparisons,
            notes="SYNTHETIC PLACEHOLDER - proof-of-concept scale only, not "
            "rule-of-30 compliant, not a real robustness measurement. See "
            "ai_training.evaluation.synthetic_slices module docstring.",
        )
        save_slice_manifest(settings, manifest)
        print(manifest.model_dump_json(indent=2))
        rule = manifest.rule_of_30()
        print(f"rule_of_30.passes={rule.passes} (expected False at this scale)", file=sys.stderr)
        return 0

    if args.command == "download-adaface-weights":
        from ai_training.download_adaface_weights import download_adaface_weights

        try:
            destination = download_adaface_weights(arch=args.arch, output_path=args.output)
        except (RuntimeError, ValueError) as exc:
            print(f"download-adaface-weights: {exc}", file=sys.stderr)
            return 2
        print(f"AdaFace weights downloaded: {destination}")
        return 0

    # Stage stubs: implemented by TR-07.
    print(f"'{args.command}' is not implemented yet (scaffold TR-01).", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
