# Development image for the Core API backend (BE-01, XC-01).
#
# Single-stage: psycopg[binary]/argon2-cffi ship prebuilt wheels for
# linux/amd64+arm64, so there's no compiled build step worth discarding via
# a multi-stage build. `[tool.uv.build-backend]` in pyproject.toml means
# this project IS installed as a package by `uv sync` (module root `app/`
# at the project root, no `src/` layout) -- hence the two-step sync below:
# dependencies first (cached across rebuilds that only touch application
# code), then the project itself once the full source is present.

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .
RUN uv sync --frozen

ENV PATH="/app/.venv/bin:$PATH"
# Unbuffered stdout/stderr so `docker compose logs` shows output as it
# happens, not only once Python's internal buffer flushes.
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# `--reload` is a dev-only choice for this compose file (docker-compose.dev.yml
# bind-mounts ./backend into the container so edits on the host take effect
# without a rebuild) -- never use --reload in a production image.
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
