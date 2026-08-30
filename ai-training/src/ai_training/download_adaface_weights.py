"""AdaFace pretrained weight procurement (TR-06).

Pretrained AdaFace checkpoints are hosted by the upstream authors
(https://github.com/mk-minchul/adaface) on Google Drive, NOT in their
GitHub repo — the architecture code (`ai_training.embedding.adaface_net`)
is vendored/MIT-ported, but the WEIGHTS are downloaded on demand from
upstream's own distribution, never committed to this repo (`*.ckpt` is
gitignored — see root `.gitignore` — because they are large, not owned by
this project, and would bloat/slow every clone).

**License note** (recorded 2026-08-30 in
`documentation/research/recommendations.md`): the user has knowingly
accepted the non-commercial-license risk attached to these upstream
weights/repo, on the basis that this application is for internal use only
and is not sold. This module does not re-litigate that decision — it only
implements the mechanical download step.

Only `ir_101` (WebFace12M) is wired to a known Google Drive file ID today
— it is the project's chosen weights per recommendations.md §2 ("AdaFace
IR-101 (WebFace12M) untuk akurasi maksimal"). Other archs raise a clear
`ValueError` rather than silently downloading the wrong thing.

Usage:
    uv run ai-training download-adaface-weights
    uv run ai-training download-adaface-weights --arch ir_101 --output models/custom.ckpt

Requires the `ml` extra (`uv sync --extra ml`) for `gdown` and `torch`
(torch is used here only to validate + re-save the extracted state_dict,
see `_extract_and_normalize_state_dict`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Google Drive file IDs for upstream AdaFace pretrained checkpoints, keyed
# by the `EmbedderSettings.adaface_arch` value this project uses. Sourced
# from the official README's pretrained-model table
# (https://github.com/mk-minchul/adaface#pretrained-models); only the
# checkpoint this project actually uses is listed.
_GDRIVE_FILE_IDS: dict[str, str] = {
    # IR-101 (num_layers=100, upstream naming) trained on WebFace12M —
    # recommendations.md §2's chosen weights for maximum accuracy.
    "ir_101": "1dswnavflETcnAuplZj1IOKKP0eM8ITgT",
}

# Google Drive checkpoints store `torch.save({'state_dict': ..., ...})`
# with keys prefixed `model.` (the upstream training harness wraps the
# backbone in a lightning-style `model` attribute). `AdaFaceEmbedder`
# expects a bare backbone `state_dict` (no prefix), so we strip it once at
# download time rather than on every load.
_STATE_DICT_KEY = "state_dict"
_STATE_DICT_PREFIX = "model."


def default_weights_path(arch: str) -> Path:
    """`<ai-training project root>/models/adaface_<arch-without-underscore>_webface12m.ckpt`.

    This module lives at `src/ai_training/download_adaface_weights.py`;
    `parents[2]` from there is the `ai-training/` project root (ai_training
    -> src -> ai-training), sibling to `models/` — same resolution pattern
    as `quality.pose._default_face_landmarker_model_path`. Shared with
    `embedding.embedder.AdaFaceEmbedder` (single source of truth for the
    default path so the download location and the load location can never
    silently drift apart).
    """
    arch_tag = arch.replace("_", "")  # "ir_101" -> "ir101", matching the stated default filename
    return Path(__file__).resolve().parents[2] / "models" / f"adaface_{arch_tag}_webface12m.ckpt"


def _extract_and_normalize_state_dict(raw: Any) -> dict[str, Any]:
    """Pull the bare backbone `state_dict` out of upstream's checkpoint
    wrapper, stripping the `model.` key prefix.

    Upstream `inference.py` does exactly this before `load_state_dict`:
    `{key[6:]: val for key, val in statedict.items() if key.startswith('model.')}`
    (`len('model.') == 6`).
    """
    if isinstance(raw, dict) and _STATE_DICT_KEY in raw:
        raw = raw[_STATE_DICT_KEY]
    if not isinstance(raw, dict):
        raise ValueError(
            "downloaded AdaFace checkpoint has an unexpected format: expected a dict (optionally "
            f"wrapped under '{_STATE_DICT_KEY}'), got {type(raw)!r}"
        )
    stripped = {
        key[len(_STATE_DICT_PREFIX) :]: val
        for key, val in raw.items()
        if key.startswith(_STATE_DICT_PREFIX)
    }
    if not stripped:
        raise ValueError(
            f"downloaded AdaFace checkpoint had no keys prefixed '{_STATE_DICT_PREFIX}' — "
            "upstream's checkpoint format may have changed; inspect the raw file before retrying."
        )
    return stripped


def download_adaface_weights(arch: str = "ir_101", output_path: str | Path | None = None) -> Path:
    """Download + normalize the AdaFace pretrained checkpoint for `arch`.

    Not covered by automated tests (network + large binary download) — see
    `tests/test_embedder.py` for what IS tested (architecture shape,
    preprocessing math, and the actionable-error path when the checkpoint
    file is simply absent). Verify this function live, out-of-band, once
    weights are actually needed.
    """
    try:
        import gdown
    except ImportError as exc:  # pragma: no cover - depends on extras
        raise RuntimeError(
            "download_adaface_weights requires the 'ml' extra (uv sync --extra ml): gdown."
        ) from exc
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - depends on extras
        raise RuntimeError(
            "download_adaface_weights requires the 'ml' extra (uv sync --extra ml): torch."
        ) from exc

    try:
        file_id = _GDRIVE_FILE_IDS[arch]
    except KeyError as exc:
        raise ValueError(
            f"no known Google Drive file id for arch={arch!r}; supported: "
            f"{sorted(_GDRIVE_FILE_IDS)} (see documentation/research/recommendations.md §2)"
        ) from exc

    destination = Path(output_path) if output_path else default_weights_path(arch)
    destination.parent.mkdir(parents=True, exist_ok=True)

    # `gdown` handles Google Drive's "file too large to scan for viruses,
    # download anyway?" confirmation-page redirect transparently — this is
    # precisely why `gdown` (not a plain `requests.get`) is used for these
    # ~100-250MB upstream checkpoints. Passing `id=` (rather than a full
    # `url=`) sidesteps version differences in gdown's URL-fuzzy-matching
    # support across releases.
    raw_download_path = destination.with_suffix(destination.suffix + ".raw")
    gdown.download(id=file_id, output=str(raw_download_path), quiet=False)

    raw_checkpoint = torch.load(raw_download_path, map_location="cpu")
    normalized_state_dict = _extract_and_normalize_state_dict(raw_checkpoint)
    torch.save(normalized_state_dict, destination)
    raw_download_path.unlink(missing_ok=True)

    return destination


def main(argv: list[str] | None = None) -> int:
    """Standalone entry point, in case `uv run python -m
    ai_training.download_adaface_weights` is preferred over the `ai-training
    download-adaface-weights` CLI subcommand (both call the same function)."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arch", default="ir_101", choices=sorted(_GDRIVE_FILE_IDS))
    parser.add_argument("--output", default=None, help="Override the default output path.")
    args = parser.parse_args(argv)

    destination = download_adaface_weights(arch=args.arch, output_path=args.output)
    print(f"AdaFace weights downloaded: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
