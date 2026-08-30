"""Pure-numpy unit tests for the TR-03 Umeyama alignment transform."""

import numpy as np

from ai_training.embedding.alignment import ARC_FACE_112_TEMPLATE, estimate_similarity_transform


def test_identity_when_landmarks_match_template() -> None:
    matrix = estimate_similarity_transform(ARC_FACE_112_TEMPLATE, ARC_FACE_112_TEMPLATE)
    np.testing.assert_allclose(matrix[:2, :2], np.eye(2), atol=1e-6)
    np.testing.assert_allclose(matrix[:, 2], np.zeros(2), atol=1e-6)


def test_recovers_known_scale_rotation_translation() -> None:
    theta = np.radians(15.0)
    scale = 1.8
    rotation = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
    translation = np.array([12.0, -7.0])

    # Synthesize "detected" landmarks by applying a KNOWN transform to the
    # template, then invert it back and confirm we get near-identity onto
    # the template again (round trip through the estimator).
    detected = (scale * (ARC_FACE_112_TEMPLATE @ rotation.T)) + translation

    matrix = estimate_similarity_transform(detected, ARC_FACE_112_TEMPLATE)
    warped = (matrix[:, :2] @ detected.T).T + matrix[:, 2]
    np.testing.assert_allclose(warped, ARC_FACE_112_TEMPLATE, atol=1e-3)


def test_output_shape_is_2x3_affine_matrix() -> None:
    matrix = estimate_similarity_transform(ARC_FACE_112_TEMPLATE, ARC_FACE_112_TEMPLATE)
    assert matrix.shape == (2, 3)
