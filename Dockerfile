# The Linux container: the designer and its API, one origin, one image.
#
# nginx serves the built designer and proxies /api to uvicorn on loopback, so
# the browser only ever talks to one origin — no CORS, no VITE_API_BASE, and the
# session token in localStorage is never sent anywhere else. Two processes under
# supervisord because they are two halves of one thing: without either, the page
# is broken rather than degraded.
#
#   docker build -t process-engine .
#   docker run -p 8000:8080 -v process-engine-data:/data process-engine
#
# It executes nothing — not by configuration, but because the image holds no
# engine and no plugin implementation to run. Every run and every single-step
# preview goes to the shared database for an engine host to claim, so point
# PROCESS_ENGINE_DB_URL at a server a `python -m process_engine` can also reach
# — see deploy/linux-api.env.example.

# -- build the designer --------------------------------------------------------
FROM node:22-alpine AS designer

WORKDIR /designer
# lockfile first: dependencies change far less often than the source, so this
# layer survives most rebuilds
COPY designer/package.json designer/package-lock.json ./
RUN npm ci
COPY designer/ ./
# no VITE_API_BASE: the fetches stay same-origin and nginx routes them
RUN npm run build


# -- the runtime ---------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx supervisor curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Two of the three distributions, and deliberately not the third: core (what a
# process is) and the API (what serves the designer), never process-engine. That
# is what makes "nothing executes here" a property of the install rather than a
# promise — neither wheel contains an execute(). The mysql extra is the driver:
# a two-host split needs a shared server, which SQLite cannot be.
COPY packages/process_engine_core/ ./packages/process_engine_core/
COPY packages/process_engine_api/ ./packages/process_engine_api/
RUN pip install "./packages/process_engine_core[mysql]" ./packages/process_engine_api

COPY docs/ ./docs/
COPY --from=designer /designer/dist/ /srv/designer/
COPY deploy/nginx.conf /etc/nginx/nginx.conf
COPY deploy/supervisord.conf /etc/supervisor/supervisord.conf

# Absolute, so neither process depends on its working directory. The designer is
# nginx's to serve; the API is told where it is only so it can tell whether one
# is deployed here (it warns when SSO would land on a blank page).
ENV PROCESS_ENGINE_DOCS_DIR=/app/docs \
    PROCESS_ENGINE_DESIGNER_DIST=/srv/designer \
    PROCESS_ENGINE_WORK_DIR=/data/workdir \
    PROCESS_ENGINE_HOST=127.0.0.1 \
    PROCESS_ENGINE_PORT=8000

# Everything written at runtime lives here: the SQLite fallback database and the
# generated auth token and Fernet key. Mount a volume or the key is regenerated
# on every restart and stored secrets become unreadable.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data/workdir /var/lib/nginx /var/log/nginx \
    && chown -R app:app /data /var/lib/nginx /var/log/nginx /srv/designer
VOLUME ["/data"]

USER app
# 8080, not 80: an unprivileged port so the container needs no root
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD curl -fsS http://127.0.0.1:8080/api/health || exit 1

CMD ["supervisord", "-c", "/etc/supervisor/supervisord.conf"]
