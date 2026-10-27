# The `offball` image (PRD 11.4): every Python service, one command each (`offball serve api`, `offball serve mcp`,
# or both with `offball serve all`). Built from the locked dependencies with the extras the VM needs (OPS-11).
# Match data is mounted at /app/datasets, and caches go to /app/replays.

FROM ghcr.io/astral-sh/uv:0.9.22@sha256:2320e6c239737dc73cccce393a8bb89eba2383d17018ee91a59773df802c20e6 AS uv

FROM python:3.12-slim-trixie@sha256:5b8b1421ccb6a525860a77863c049eab5847076cda34e030c75a80c58faf3f3c AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first, so a change to the code alone doesn't reinstall them.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project --extra vm --extra azure
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra vm --extra azure

FROM python:3.12-slim-trixie@sha256:5b8b1421ccb6a525860a77863c049eab5847076cda34e030c75a80c58faf3f3c
RUN groupadd --system --gid 10001 offball \
    && useradd --system --uid 10001 --gid offball --home-dir /app --shell /usr/sbin/nologin offball
COPY --from=build /app /app
RUN mkdir -p /app/datasets /app/replays && chown offball:offball /app/replays
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /app
USER offball
EXPOSE 8000 8001
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]
CMD ["offball", "serve", "all", "--host", "0.0.0.0"]
