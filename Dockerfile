# syntax=docker/dockerfile:1
# Optional image for the blender-forge MCP server. Blender itself always runs on the host with the
# blender-forge extension (or `blender -b --python serve.py`); the container reaches its loopback
# bridge through BLENDER_FORGE_BRIDGE_HOST, and BLENDER_FORGE_PATH_MAP translates /work paths to
# the host folder Blender reads and writes. See docs/DOCKER.md.
FROM python:3.12-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY mcp/blender-forge/pyproject.toml mcp/blender-forge/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project
COPY mcp/blender-forge/src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-editable

FROM python:3.12-slim-bookworm
RUN groupadd --gid 10001 forge && useradd --uid 10001 --gid forge --create-home forge \
    && mkdir -p /work /workspace /config && chown forge:forge /work
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONUTF8=1 \
    BLENDER_FORGE_CONFIG=/config/bridge.json \
    BLENDER_FORGE_WORKSPACE=/workspace \
    BLENDER_FORGE_CACHE=/work/.blender-forge/cache
USER forge
WORKDIR /work
EXPOSE 8080
ENTRYPOINT ["blender-forge"]
CMD ["--stdio"]
