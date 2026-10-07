# Design DNA dashboard container: web app + API (serve) and the job worker (worker) from one image.
# Build from the repository root:  docker build -f dashboard/Dockerfile -t design-dna-dashboard .
# Run both processes with persistent data:  see dashboard/docker-compose.yml

ARG PLAYWRIGHT_VERSION=1.56.0

FROM node:22-bookworm-slim AS web
WORKDIR /src/dashboard/web
COPY dashboard/web/package.json dashboard/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY dashboard/web/ ./
RUN npm run build

# Playwright's official image: Ubuntu 24.04, Python 3.12, Chromium and every system library it needs.
# The Python package version must match the image tag so the browser revision matches.
FROM mcr.microsoft.com/playwright/python:v${PLAYWRIGHT_VERSION}-noble
ARG PLAYWRIGHT_VERSION
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    DNA_DATA_DIR=/data DNA_HOST=0.0.0.0 DNA_PORT=8765
WORKDIR /app
COPY skills/reverse-design/requirements.txt skills/reverse-design/requirements.txt
COPY dashboard/requirements.txt dashboard/requirements.txt
RUN python -m pip install -r dashboard/requirements.txt "playwright==${PLAYWRIGHT_VERSION}"
COPY skills/ skills/
COPY dashboard/server/ dashboard/server/
COPY docs/images/ docs/images/
COPY --from=web /src/dashboard/web/dist dashboard/web/dist
RUN mkdir -p /data && chown pwuser:pwuser /data
USER pwuser
WORKDIR /app/dashboard/server
VOLUME ["/data"]
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=4)" || exit 1
# A non-loopback bind refuses to start without DNA_AUTH_TOKEN (workspace authentication).
CMD ["python", "-m", "dna_dashboard", "serve"]
