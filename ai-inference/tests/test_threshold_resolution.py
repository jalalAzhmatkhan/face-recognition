"""Unit tests for `ai_inference.pipeline.threshold_resolution` (EC-IN-04,
TSD-edge-cases.md D-4.2/OQ-6) against a fake DB-API cursor -- no real
Postgres needed, mirrors `tests/test_gallery.py`'s `FakeCursor` idiom."""

from ai_inference.config import Settings
from ai_inference.pipeline.threshold_resolution import (
    ResolvedThreshold,
    artefact_defaults,
    resolve_mode_params,
)


class _FakeCursor:
    """Serves `get_recognition_config_override`'s two possible queries;
    `None` (the default) for a scope means "no matching row"."""

    def __init__(self, *, device_class_row=None, global_row=None) -> None:
        self.device_class_row = device_class_row
        self.global_row = global_row
        self.executed: list[tuple[str, tuple]] = []
        self._fetch_one = None

    def execute(self, query: str, params: tuple = ()) -> None:
        self.executed.append((query, params))
        if "scope = 'device_class'" in query:
            self._fetch_one = self.device_class_row
        else:
            self._fetch_one = self.global_row

    def fetchone(self):
        return self._fetch_one

    def fetchall(self):  # pragma: no cover - not used by this module
        return []


def test_artefact_defaults_normal_mode_matches_pre_ec_in_04_settings_fields() -> None:
    settings = Settings(
        similarity_threshold=0.35, margin_threshold=0.1, min_frames_for_grant=2
    )
    assert artefact_defaults(settings, "normal") == {
        "similarity_threshold": 0.35,
        "margin": 0.1,
        "min_frames": 2,
    }


def test_artefact_defaults_unrecognized_mode_falls_back_to_normal() -> None:
    settings = Settings(similarity_threshold=0.35, margin_threshold=0.1, min_frames_for_grant=2)
    assert artefact_defaults(settings, "dark") == artefact_defaults(settings, "normal")


def test_artefact_defaults_masked_mode_uses_masked_settings_fields() -> None:
    settings = Settings(
        similarity_threshold_masked=0.28,
        margin_threshold_masked=0.02,
        min_frames_for_grant_masked=3,
    )
    assert artefact_defaults(settings, "masked") == {
        "similarity_threshold": 0.28,
        "margin": 0.02,
        "min_frames": 3,
    }


def test_resolve_mode_params_falls_through_to_artefact_default_when_no_override_at_all() -> None:
    settings = Settings(
        similarity_threshold_masked=0.28, margin_threshold_masked=0.0, min_frames_for_grant_masked=2
    )
    cursor = _FakeCursor(device_class_row=None, global_row=None)
    resolved = resolve_mode_params(cursor, settings, mode="masked", device_class="door_entry")
    assert resolved == ResolvedThreshold(similarity_threshold=0.28, margin=0.0, min_frames=2)


def test_resolve_mode_params_device_class_override_wins() -> None:
    settings = Settings(
        similarity_threshold_masked=0.28,
        margin_threshold_masked=0.0,
        min_frames_for_grant_masked=2,
    )
    # Only similarity_threshold overridden at DEVICE_CLASS scope -- margin/
    # min_frames NULL there, must fall through to the artefact default, NOT
    # to the (also present) GLOBAL row.
    cursor = _FakeCursor(
        device_class_row=(0.20, None, None, None),
        global_row=(0.5, 0.2, 0.6, 5),
    )
    resolved = resolve_mode_params(cursor, settings, mode="masked", device_class="door_entry")
    assert resolved == ResolvedThreshold(similarity_threshold=0.20, margin=0.0, min_frames=2)


def test_resolve_mode_params_global_override_used_when_no_device_class_row() -> None:
    settings = Settings(similarity_threshold=0.35, margin_threshold=0.0, min_frames_for_grant=2)
    cursor = _FakeCursor(device_class_row=None, global_row=(0.4, 0.05, None, 3))
    resolved = resolve_mode_params(cursor, settings, mode="normal", device_class="attendance")
    assert resolved == ResolvedThreshold(similarity_threshold=0.4, margin=0.05, min_frames=3)


def test_resolve_mode_params_no_device_class_skips_that_query() -> None:
    settings = Settings(similarity_threshold=0.35, margin_threshold=0.0, min_frames_for_grant=2)
    cursor = _FakeCursor(global_row=None)
    resolve_mode_params(cursor, settings, mode="normal", device_class=None)
    assert len(cursor.executed) == 1
    assert "scope = 'global'" in cursor.executed[0][0]
