# Use a slim Python base image to reduce size
FROM python:3.10-slim

# Install dependencies in one layer
RUN apt-get update && apt-get install -y --no-install-recommends \
    git cron vim ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Trust any local corporate TLS proxy root CA present in certs/ (e.g. Zscaler),
# so pip/git can reach external hosts when building behind a TLS-intercepting proxy.
# certs/ is empty by default; drop a .pem there if your network requires it.
COPY certs/ /usr/local/share/ca-certificates/extra/
RUN for f in /usr/local/share/ca-certificates/extra/*.pem; do \
      [ -f "$f" ] && cp "$f" "/usr/local/share/ca-certificates/$(basename "$f" .pem).crt"; \
    done; \
    update-ca-certificates

# Point pip/requests at the system CA bundle (rather than certifi's bundled one)
# so the extra CA above is actually honored during package installs.
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt

# Set working directory
WORKDIR /app

# Copy application files
COPY ./python/generate_config.py .  
COPY ./python/sync_lb_to_plex.py .
COPY ./python/requirements.txt .
COPY ./scripts/sync_job_wrapper.sh .

RUN chmod +x sync_job_wrapper.sh

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy cron placeholder
COPY cron/crontab_template /etc/cron.d/crontab_template
RUN chmod 0644 /etc/cron.d/crontab_template

# Add an entrypoint script to check RUN_NOW and run the job if needed
COPY ./scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh



# Use the entrypoint script to handle RUN_NOW logic
ENTRYPOINT ["/entrypoint.sh"]