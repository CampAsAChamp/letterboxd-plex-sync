# Build stage: install Python deps (needs git for letterboxd_stats from GitHub)
FROM python:3.10-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY certs/ /usr/local/share/ca-certificates/extra/
RUN for f in /usr/local/share/ca-certificates/extra/*.pem; do \
      [ -f "$f" ] && cp "$f" "/usr/local/share/ca-certificates/$(basename "$f" .pem).crt"; \
    done; \
    update-ca-certificates

ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt

COPY python/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt


# Runtime stage
FROM python:3.10-slim

ARG SUPERCRONIC_VERSION=0.2.33

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates procps tini wget && \
    rm -rf /var/lib/apt/lists/*

COPY certs/ /usr/local/share/ca-certificates/extra/
RUN for f in /usr/local/share/ca-certificates/extra/*.pem; do \
      [ -f "$f" ] && cp "$f" "/usr/local/share/ca-certificates/$(basename "$f" .pem).crt"; \
    done; \
    update-ca-certificates

# Install supercronic after CA certs (needed for TLS through corporate proxies)
RUN ARCH=$(dpkg --print-architecture) && \
    wget -qO /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/v${SUPERCRONIC_VERSION}/supercronic-linux-${ARCH}" && \
    chmod +x /usr/local/bin/supercronic

ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

WORKDIR /app
RUN mkdir -p /app/data

COPY python/generate_config.py .
COPY python/sync_helpers.py .
COPY python/sync_state.py .
COPY python/sync_stats.py .
COPY python/sync_config.py .
COPY python/tmdb_mapping.py .
COPY python/plex_sync.py .
COPY python/radarr_sync.py .
COPY python/sync_lb_to_plex.py .

COPY cron/crontab_template /etc/cron.d/crontab_template
RUN chmod 0644 /etc/cron.d/crontab_template

COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

HEALTHCHECK --interval=5m --timeout=10s --start-period=30s --retries=3 \
    CMD pgrep -x supercronic > /dev/null || exit 1

ENTRYPOINT ["/entrypoint.sh"]
