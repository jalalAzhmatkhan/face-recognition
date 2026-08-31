# Development image for the ai-training service: a Celery worker consuming
# QC / embedding-extraction / training-evaluation / gallery-re-embed jobs
# (TR-01+), dispatched cross-service from backend's own Celery app by
# matching task NAME strings (see backend/app/worker/tasks.py's "name-only
# proxy" pattern). No FastAPI app here -- this container's only long-running
# process is the worker.
#
# Two stages, purely to keep the final image lean: `uv sync` populates
# `/app/.venv` in the `builder` stage, but also downloads every wheel into
# uv's OWN cache (outside `.venv`) -- for the `ml` extra
# (torch/opencv-python-headless/mediapipe/mlflow/gdown) that cache alone can
# rival the venv in size. The `runtime` stage copies only the finished
# `/app` (source + `.venv`), never `builder`'s cache, uv's own binary, or
# apt state. `torch` itself is pinned to PyTorch's own CPU-only wheel index
# in pyproject.toml (`[tool.uv.sources]`) -- this dev compose has no GPU
# passthrough configured, and PyPI's default `torch` wheel otherwise drags
# in ~40 transitive `nvidia-*` CUDA packages (several GB) that would just
# sit there unused.
#
# The AdaFace embedding checkpoint (~250MB, gitignored -- non-commercial
# license procured separately, see `ai_training.download_adaface_weights`)
# is deliberately NOT baked into this image either. Run once after the
# container is up:
#   docker compose exec ai-training ai-training download-adaface-weights
# (the `ai-training` executable is the console script `.venv/bin/`
# installs, per `[project.scripts]` -- the runtime stage below has no `uv`
# binary at all, by design, so this must be invoked directly, not via
# `uv run`). It lands under `models/`, which docker-compose.dev.yml
# bind-mounts back to the host, so it survives container rebuilds.

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --extra ml --no-install-project

COPY . .
RUN uv sync --frozen --extra ml

FROM python:3.12-slim AS runtime

WORKDIR /app
COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

CMD ["celery", "-A", "ai_training.worker.celery_app", "worker", "--loglevel=info"]
