# 🎭 Letterboxd Plex Sync

A tool that syncs [Letterboxd](https://letterboxd.com/) user data (ratings, watch history, and watchlists) to a personal [Plex](https://www.plex.tv/) server. THIS IS A ONE WAY SYNC. This tool aims to enhance your Plex experience by keeping your viewing stats up to date with your Letterboxd profile! 🚀

## ⚠️ Disclaimer

This project is provided “as-is” without any guarantees or warranties of any kind. By using this tool, you accept full responsibility for any risks, including but not limited to data loss, misconfigurations, or disruptions to your Plex or Radarr server.
- Rate Limits: Frequent use of this tool may trigger API rate limits for Plex, TMDB, or Radarr. Ensure you comply with their respective terms of service.
- Letterboxd Data: This tool relies on simulating Letterboxd browser actions to download your user data. Use this tool responsibly and at your own risk, as it is unknown if this could result in account restrictions. 
- Sensitive Data: Handle your .env file carefully, as it contains sensitive credentials (e.g., Plex token, Letterboxd credentials, API keys). Do not share this file or include it in public repositories.
- Testing Recommended: Test this tool on a non-production server or with a limited dataset before deploying it to your main Plex or Radarr setup.
- Use at Your Own Risk: The authors are not responsible for **any** consequences resulting from the use of this tool.


## ⚙️ How It Works

This project simplifies syncing Letterboxd data to Plex by offering a simple Python script, as well as a Docker container wrapping that script with a cron process for easy deployment and automation. 

The script leverages:
- [Plex API wrapper](https://github.com/pkkid/python-plexapi) to interact with your Plex server.
- [letterboxd_stats](https://github.com/mBaratta96/letterboxd_stats) library to download and process Letterboxd user data.

Currently, it focuses on syncing:
- ⭐ User ratings
- 📜 Watch history
- 🗛 Watchlist (now with Radarr support)


### 🎯 The Script
The core functionality is provided by a Python script that:
1. **Fetches Data**: Downloads user data from Letterboxd using the `letterboxd_stats` library.
2. **Processes Metadata**: Maps Letterboxd data to Plex-compatible IDs using the TMDB API (cached in a local CSV).
3. **Syncs Data**: Updates the Plex server by:
   - Adding ratings from Letterboxd.
   - Marking movies as played (one-way — never un-watches).
   - Adding Letterboxd watchlist items to Plex (add-only — never removes).
   - Optionally adding watchlist movies to Radarr (add-only).

The script behavior is highly configurable through environment variables, allowing users to tailor the sync to their specific requirements.

### 📚 Library Selection

The script can sync data across all movie-type libraries in your Plex server. However, if you'd like to target a specific library, you can set the `PLEX_LIBRARY_NAME` environment variable. For example:

- If `PLEX_LIBRARY_NAME` is set (e.g., "Movies"), the script will sync data only with that library.
- If `PLEX_LIBRARY_NAME` is not set, the script will automatically iterate through all movie libraries in your Plex server, ensuring comprehensive syncing without additional configuration.

### 🎞️ Radarr Integration

For users who manage their media with Radarr, the script offers an additional integration:

- When the `SYNC_WATCHLIST_TO_RADARR` (default: `false`) environment variable is set to `true`, the script will take movies from your Letterboxd watchlist and add them to Radarr as monitored movies.
- To enable this, you must provide:
  - `RADARR_URL`: The base URL for your Radarr server.
  - `RADARR_TOKEN`: The API key for authenticating with Radarr.
  - Optionally, specify `RADARR_TAGS` to tag these movies (e.g., `letterboxd-plex-sync`), helping you organize and manage additions in Radarr.

### 🧊 Docker Container Integration
The Python script is wrapped within a lightweight Docker container that automates execution via a cron process. The container:
1. **Runs Immediately (Optional)**: With the `RUN_NOW` environment variable, the sync job can execute as soon as the container starts.
2. **Schedules Jobs**: A cron process schedules recurring sync jobs based on the `CRON_SCHEDULE` environment variable.
3. **Logs Activity**: Writes logs to stdout and appends them to `./data/combined_log.txt` on the host (via the `./data` volume mount). Each run also writes a structured `./data/latest_sync_report.txt` with per-title succeeded/failed outcomes; failed items are listed in the end-of-run summary.

### 📂 Configuration and Portability
The container is designed for ease of use:
- Configurations are passed as environment variables in a `letterboxd.env` file (copy from `letterboxd.env.example`).
- Users can choose between running the script locally or using Docker, depending on their preferences and setup.
- Behind a corporate TLS proxy (e.g. Zscaler), drop your root CA `.pem` in `certs/` before building the Docker image.

This design ensures seamless integration with your existing Plex server and minimal manual intervention once deployed.


## 🛠️ Environment Variables

The script relies on several environment variables for configuration. Here is a list of all the environment variables you need to set:

### Required Environment Variables
- **`PLEX_BASEURL`**: The base URL of your Plex server (e.g., `http://your-plex-server:32400`).
- **`PLEX_TOKEN`**: Authentication token for accessing your Plex server.
- **`LB_USERNAME`**: Your Letterboxd username.
- **`LB_PASSWORD`**: Your Letterboxd password.
- **`TMDB_API_KEY`**: Your TMDB API key, required for fetching additional metadata.

### Optional Environment Variables
- **`DEBUG`**: Set to `true` to enable debug logging. Defaults to `false`.
- **`DRY_RUN`**: Set to `true` to preview planned Plex/Radarr changes without writing. Logs `[DRY RUN] Would …` for each action. Defaults to `false`.
- **`RUN_NOW`**: Set to `true` to run the sync job immediately when the container starts. Defaults to `false`.
####  
- **`CRON_SCHEDULE`**: The schedule for the cron job (e.g., `0 4 */1 * *` for every day at 4:00AM). Defaults to `0 4 */1 * *`.
####
- **`SYNC_WATCHLIST`**: Set to `true` to sync the watchlist from Letterboxd to Plex. Defaults to `true`.
- **`SYNC_WATCHED`**: Set to `true` to sync watched status from Letterboxd to Plex. Defaults to `true`.
- **`SYNC_RATINGS`**: Set to `true` to sync user ratings from Letterboxd to Plex. Defaults to `true`.
- **`PLEX_LIBRARY_NAME`**: The Plex Movies library to use. Defaults to syncing all Movie-type libraries.
- **`PLEX_USER`**: The Plex user to use for syncing, if not the default admin.
- **`PLEX_PIN`**: The PIN associated with the Plex user, if required.
####
- **`SYNC_WATCHLIST_TO_RADARR`**: Set to `true` to sync the Letterboxd watchlist to Radarr. Defaults to `false`.
- **`RADARR_URL`**: The base URL of your Radarr server (e.g., `http://your-radarr-server:7878`). Required if syncing watchlist to Radarr.
- **`RADARR_TOKEN`**: The API key for your Radarr server. Required if syncing watchlist to Radarr.
- **`RADARR_TAGS`**: A comma-separated list of tags to assign to movies added to Radarr. Tags must exist in Radarr or will be created automatically if they don’t. Optional.
- **`RADARR_ROOT_FOLDER`**: The root folder path in Radarr where new movies will be added (e.g., `/movies`). Defaults to `/movies` if not provided. Optional.
- **`RADARR_MONITORED`**: Whether to set movies as monitored in Radarr. Defaults to `true`.
- **`RADARR_SEARCH`**: Whether to search for the movie after it is added to Radarr.  Defaults to `true`.
- **`RADARR_QUALITY_PROFILE`**: The name of the quality profile to use in Radarr (e.g., `HD - 1080p`). If not provided or not found, defaults to the profile with ID `1`. Optional.
####
- **`MAP_LETTERBOXD_TO_TMDB`**: Set to `false` to skip building/updating the Letterboxd→TMDB mapping cache. Defaults to `true`. When the cache already contains every URL from your Letterboxd exports, API lookups are skipped automatically.
- **`LB_TMDB_MAP_CSV_PATH_OVERRIDE`**: Path to the LB→TMDB mapping CSV cache. Defaults to `/app/data/lb_URL_to_tmdb_id.csv`.
- **`LETTERBOXD_RATINGS_CSV`**, **`LETTERBOXD_WATCHLIST_CSV`**, **`LETTERBOXD_WATCHED_CSV`**: Override paths to Letterboxd export CSVs. Defaults to `/tmp/static/` paths set by `letterboxd_stats`.
- **`SYNC_REPORT_PATH`**: Path for the per-run succeeded/failed report. Defaults to `/app/data/latest_sync_report.txt` (host: `./data/latest_sync_report.txt`).
- **`SYNC_REPORT_INLINE_LIMIT`**: Max failed items printed per category in the end-of-run summary. Defaults to `25`.
- **`COMBINED_LOG_PATH`**: Path for the append-only run log. Defaults to `/app/data/combined_log.txt` (host: `./data/combined_log.txt`).



### Setup: `letterboxd.env`

Copy the example templates and fill in your credentials:

```sh
cp letterboxd.env.example letterboxd.env
# edit letterboxd.env with your Plex, Letterboxd, and TMDB credentials

# optional: seed the Letterboxd→TMDB mapping cache (otherwise created empty on first sync)
cp data/lb_URL_to_tmdb_id.csv.example data/lb_URL_to_tmdb_id.csv
```

The mapping cache is one `letterboxd_short_url,tmdb_id` pair per line (no header). See [data/lb_URL_to_tmdb_id.csv.example](data/lb_URL_to_tmdb_id.csv.example).

See [letterboxd.env.example](letterboxd.env.example) for all available options with comments.

## 🛠️ Running the Script

There are multiple ways to run the `letterboxd_plex_sync` script. Start by creating your config:

```sh
cp letterboxd.env.example letterboxd.env
```

### 1. Docker Compose

Here's a sample Docker Compose setup to run the `letterboxd_plex_sync` script on a schedule:

```yaml
---
name: letterboxd-plex-sync
services:
  letterboxd-plex-sync:
    container_name: letterboxd-plex-sync
    image: treysu/letterboxd-plex-sync:latest
    restart: unless-stopped
    #platform: linux/x86_64 # typically only needed for Apple Silicon
    env_file:
      - path: letterboxd.env
        required: true
    volumes:
      - /etc/localtime:/etc/localtime:ro # optional: for accurate log times
      - ./data:/app/data:rw # persists lb_URL_to_tmdb_id.csv (copy from data/lb_URL_to_tmdb_id.csv.example)
```

To use Docker Compose:

```sh
docker compose up -d
```

### 2. Docker Run

Alternatively, you can run the container directly with Docker:

```sh
docker run -d \
  --env-file letterboxd.env \
  -v path/to/data:/app/data:rw \
  treysu/letterboxd-plex-sync:latest
```

### 3. Running Locally

If you prefer to run the script locally without Docker:

1. **Clone the Repository**:  
   ```sh
   git clone https://github.com/treysu/letterboxd-plex-sync.git
   cd letterboxd-plex-sync
   cp letterboxd.env.example letterboxd.env
   ```

2. **Install Dependencies**:  
   Ensure you have Python installed, then install the required packages:
   ```sh
   pip install -r python/requirements.txt
   ```

3. **Run the Script**:  
   From the repo root, load your env file and run:
   ```sh
   set -a && source letterboxd.env && set +a
   python python/generate_config.py
   python python/sync_lb_to_plex.py
   ```

## 🛠️ Future Improvements

- 📊 Better handling of multiple Plex users.
- 🔄 Sync additional types of data (e.g., tags, custom lists).

## 📣 Contributing

Feel free to open issues or make pull requests. This project is still a work in progress, and contributions are welcome!

