# Hive AgentOS -- containerized REST API + control plane.
#
# Build:  docker build -t hive-agentos .
# Run:    docker run -p 8000:8000 -e ANTHROPIC_API_KEY=sk-... -v hive_state:/data hive-agentos
# Then open http://localhost:8000/ (control plane) or /docs (API).

FROM python:3.12-slim AS build

# uv for a fast, reproducible install. Pinned so builds don't drift with uv releases
# (keep in sync with the uv that resolved uv.lock).
COPY --from=ghcr.io/astral-sh/uv:0.9.3 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY profiles ./profiles
COPY skills ./skills
COPY models.yaml ./models.yaml

# Install the package (with the API extra) into a self-contained venv.
# --no-editable copies hive into site-packages (an editable install would leave a
# .pth pointing at /app/src, which the runtime stage does not carry).
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
RUN uv sync --frozen --extra api --no-dev --no-editable


FROM python:3.12-slim AS runtime

# Non-root user; agent workspaces and state live under /data.
RUN useradd --create-home --uid 1000 hive \
    && mkdir -p /data && chown hive:hive /data
COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

USER hive
WORKDIR /data

EXPOSE 8000

# Report container health via the API's readiness endpoint (urllib ships with the
# slim base, so no extra dependency). Enables `docker ps` health + service_healthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" \
    || exit 1

# The API server, with the heartbeat loop in-process. `hive init` is idempotent and
# scaffolds .hive/ in the mounted /data volume on first run. Its stderr is kept (not
# silenced) so a real init failure -- bad /data permissions, disk full -- is visible.
ENTRYPOINT ["sh", "-c", "hive init 2>&1 || true; exec hive serve --host 0.0.0.0 --port 8000 --with-daemon"]
