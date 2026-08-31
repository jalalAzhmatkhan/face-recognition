# Development image for the inference service (IN-01+).
#
# BUILD CONTEXT IS THE REPO ROOT, not ./ai-inference (see
# docker-compose.dev.yml: `context: .`, `dockerfile: ai-inference/Dockerfile`)
# -- this service's `ml` extra takes a uv PATH dependency on the SIBLING
# `ai-training` package (`[tool.uv.sources] ai-training = { path =
# "../ai-training", editable = true }`), so ai-training's full source tree
# must be visible in the same build context, and the two projects are kept
# as siblings under /app inside the image too, so that relative path
# resolves exactly like it does on the host.
#
# Two stages, purely to keep the final image lean: `uv sync` populates
# `/app/ai-inference/.venv` in the `builder` stage, but also downloads every
# wheel into uv's OWN cache (outside `.venv`) -- for the `ml` extra
# (torch/mediapipe/opencv/mlflow/onnxruntime, plus ai-training's own `ml`
# extra pulled in transitively) that cache alone can rival the venv in
# size. The `runtime` stage copies only the finished `/app` (both source
# trees + the venv), never `builder`'s cache, uv's own binary, or apt
# state. `torch` itself is pinned to PyTorch's own CPU-only wheel index in
# both projects' pyproject.toml (`[tool.uv.sources]`) -- this dev compose
# has no GPU passthrough configured, and PyPI's default `torch` wheel
# otherwise drags in ~40 transitive `nvidia-*` CUDA packages (several GB)
# that would just sit there unused.

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# ai-training's FULL source (not just its manifest) is needed up front:
# resolving ai-inference's `ml` extra installs `ai-training[ml]` as an
# editable path dependency, which needs its real `src/` tree and
# README.md (declared as the package's `readme`) to already exist.
COPY ai-training/ /app/ai-training/

COPY ai-inference/pyproject.toml ai-inference/uv.lock /app/ai-inference/
WORKDIR /app/ai-inference
RUN uv sync --frozen --extra ml --no-install-project

COPY ai-inference/ /app/ai-inference/
RUN uv sync --frozen --extra ml

FROM python:3.12-slim AS runtime

WORKDIR /app
COPY --from=builder /app /app

ENV PATH="/app/ai-inference/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

WORKDIR /app/ai-inference
EXPOSE 8100

# `--reload` is a dev-only choice (docker-compose.dev.yml bind-mounts BOTH
# ./ai-inference and ./ai-training so host edits to either take effect
# without a rebuild) -- never use --reload in a production image.
CMD ["uvicorn", "ai_inference.main:app", "--host", "0.0.0.0", "--port", "8100", "--reload"]
