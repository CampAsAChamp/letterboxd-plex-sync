#!/usr/bin/env bash
set -euo pipefail

# Step 1: Generate letterboxd_stats config from environment
python /app/generate_config.py

touch /app/combined_log.txt

# Step 2: Optionally run sync immediately on startup
if [ "${RUN_NOW:-false}" = "true" ]; then
  echo "RUN_NOW is set to true. Running job immediately..."
  /usr/local/bin/python /app/sync_lb_to_plex.py >> /app/combined_log.txt 2>&1
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
