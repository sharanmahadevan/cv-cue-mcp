# CV-CUE MCP — hosted sign-in app + OAuth-protected MCP endpoint
FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install ".[http]"

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MCP_TRANSPORT=hosted \
    PORT=8080 \
    CVCUE_DB_PATH=/data/cvcue.db
COPY --from=build /install /usr/local
RUN useradd --create-home --uid 10001 mcp && mkdir -p /data && chown mcp:mcp /data
EXPOSE 8080
# Fly mounts the volume at /data owned by root: fix ownership, then drop to the
# unprivileged user before starting the server.
CMD ["sh", "-c", "chown mcp:mcp /data && exec setpriv --reuid=mcp --regid=mcp --init-groups cv-cue-mcp --hosted"]
