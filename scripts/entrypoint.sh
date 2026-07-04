#!/usr/bin/env bash
set -euo pipefail

# Step 1: Generate letterboxd_stats config from environment
python /app/generate_config.py

COMBINED_LOG_PATH="${COMBINED_LOG_PATH:-/app/data/combined_log.txt}"
mkdir -p "$(dirname "$COMBINED_LOG_PATH")"
touch "$COMBINED_LOG_PATH"

# Step 2: Optionally run sync immediately on startup
if [ "${RUN_NOW:-false}" = "true" ]; then
  echo "RUN_NOW is set to true. Running job immediately..."
  # tee keeps compose/podman logs live while also appending to the persistent log file.
  # A failed sync must NOT exit this script: restart:unless-stopped would otherwise
  # immediately re-run RUN_NOW on container restart, crash-looping and hammering
  # upstream services (Letterboxd/Plex) on every failure.
  set +e
  /usr/local/bin/python /app/sync_lb_to_plex.py 2>&1 | tee -a "$COMBINED_LOG_PATH"
  sync_exit_code="${PIPESTATUS[0]}"
  set -e
  if [ "$sync_exit_code" -ne 0 ]; then
    echo "Startup sync failed (exit code $sync_exit_code). Will retry on the next scheduled run instead of restarting the container."
  fi
else
  echo "RUN_NOW is not set. Proceeding with scheduled sync."
fi

# Step 3: Start supercronic with the configured schedule
CRON_SCHEDULE=${CRON_SCHEDULE:-"0 4 */1 * *"}
sed "s|\${CRON_SCHEDULE}|${CRON_SCHEDULE}|g" /etc/cron.d/crontab_template > /etc/cron.d/crontab
chmod 0644 /etc/cron.d/crontab

echo "Starting supercronic with schedule: ${CRON_SCHEDULE}"

# tini handles signals; supercronic runs in foreground and inherits Docker env
exec tini -s -- supercronic /etc/cron.d/crontab
