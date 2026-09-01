"""Own-model classifiers (as opposed to `ai_training.embedding`/`liveness`,
which vendor or load third-party architectures/weights).

Currently: `mask_sunglasses` (EC-IN-03, TSD-edge-cases.md C-2/OQ-4) -- the
masked/sunglasses/none 3-class (2-output multi-label) crop classifier that
replaces EC-IN-01's placeholder landmark-intensity heuristic.
"""
