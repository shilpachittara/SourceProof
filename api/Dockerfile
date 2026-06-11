FROM python:3.12-slim-bookworm

# Modern Docker CLI (static binary). The Debian `docker.io` package ships an old
# client (API 1.41) that is rejected by newer daemons such as Colima (min 1.44).
ARG DOCKER_CLI_VERSION=27.3.1
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && arch="$(uname -m)" \
    && case "$arch" in \
         aarch64|arm64) dl_arch="aarch64" ;; \
         x86_64|amd64)  dl_arch="x86_64" ;; \
         *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
       esac \
    && curl -fsSL "https://download.docker.com/linux/static/stable/${dl_arch}/docker-${DOCKER_CLI_VERSION}.tgz" -o /tmp/docker.tgz \
    && tar -xzf /tmp/docker.tgz -C /tmp \
    && mv /tmp/docker/docker /usr/local/bin/docker \
    && rm -rf /tmp/docker /tmp/docker.tgz \
    && docker --version

WORKDIR /app

COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/app ./app
COPY demo/ui ./demo/ui

RUN mkdir -p /app/data/sources

ENV PYTHONUNBUFFERED=1
ENV DATABASE_URL=postgresql+psycopg://postgres:postgres@pglite:5432/postgres
ENV STORAGE_DIR=/app/data/sources
ENV BUILDER_IMAGE=soroban-verify-builder:local

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
