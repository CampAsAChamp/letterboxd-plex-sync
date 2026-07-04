#!/usr/bin/env python3

import os
import sys

from sync_config import require_env

config_path = os.path.expanduser("~/.config/letterboxd_stats/config.toml")


def main() -> None:
    """Generate letterboxd_stats config.toml from environment variables."""
    env = require_env("LB_USERNAME", "LB_PASSWORD", "TMDB_API_KEY")

    import toml

    config = {
        "root_folder": "/tmp/",
        "poster_columns": 0,
        "TMDB": {"api_key": env["TMDB_API_KEY"]},
        "Letterboxd": {
            "username": env["LB_USERNAME"],
            "password": env["LB_PASSWORD"],
        },
    }

    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as config_file:
        toml.dump(config, config_file)

    print(
        f"Config file generated at: {config_path}. "
        "You can ignore this if you are running in a container.",
        file=sys.stdout,
    )


if __name__ == "__main__":
    main()
