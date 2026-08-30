# ai-training

Face Recognition Access Control — training pipeline (TR-01 scaffold).

Stages: data (S3 snapshot manifests) → preprocessing (frames, pose bins, EDA) → embedding (AdaFace, gallery upsert) → training (fine-tune + MLflow) → evaluation (Recall → F1 → Precision + latency ms).

## Run

```bash
uv sync                 # light deps only (pydantic, pydantic-settings)
uv run pytest           # smoke tests
uv run ruff check .
uv run ai-training --help
```

Heavy deps (torch, mlflow, boto3, numpy) are an optional extra — all imports are lazy:

```bash
uv sync --extra ml
```

## Configuration

Env vars with prefix `TRN_`, nested with `__` (see `src/ai_training/config.py`):
`TRN_S3__BUCKET`, `TRN_MLFLOW__TRACKING_URI`, `TRN_DB__DSN`, `TRN_TRAINING__DEVICE`, …
No credentials in code; AWS uses the standard credential chain.

## Rules

- Media never rests on local disk (in-memory/tmpfs streaming only, NFR-SEC-02).
- Metric priority: Recall → F1 → Precision, plus latency in ms.
