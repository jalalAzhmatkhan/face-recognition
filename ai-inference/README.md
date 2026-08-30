# ai-inference

Face Recognition Access Control — inference service (IN-01 scaffold).

Pipeline (per ratified research): SCRFD detection → alignment → MiniFASNet liveness → AdaFace embedding → gallery matching → decision.

## Run

```bash
uv sync                 # light deps only (FastAPI, prometheus-client, ...)
uv run pytest           # smoke tests
uv run ruff check .
uv run uvicorn ai_inference.main:app --port 8100
```

Heavy ML deps (torch, mlflow, onnxruntime) are an optional extra — all imports are lazy:

```bash
uv sync --extra ml
```

## Endpoints

- `GET /healthz` — status + loaded model versions
- `GET /metrics` — Prometheus (per-stage latency histograms, decision counters)

## Configuration

Env vars with prefix `INF_` (see `src/ai_inference/config.py`), e.g. `INF_MLFLOW_TRACKING_URI`, `INF_MODEL_LOADER=stub|mlflow`, `INF_MODEL_STAGE_OR_VERSION`. No credentials in code.

## Observability (XC-04)

- **Metrics**: `GET /metrics` (see above) — already existed from IN-01, per-stage latency histograms live in `src/ai_inference/metrics.py`.
- **Tracing (opsional/lazy)**: OTel, off by default. `uv sync --extra otel` + set `OTEL_EXPORTER_OTLP_ENDPOINT` (e.g. `http://localhost:4317`) to enable; otherwise `setup_tracing()` in `src/ai_inference/tracing.py` is a no-op so the service stays runnable in dev/CI without a collector.
