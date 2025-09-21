# Harmony Backend

Prototype FastAPI backend that connects placeholder integrations for Spotify, Plex, Soulseek (`slskd`), and Beets. It exposes REST endpoints for searching Spotify and Soulseek, triggering Beets imports, querying Plex artists, and matching Spotify tracks to Plex library candidates.

## Development

```bash
uvicorn app.main:app --reload
```

## Soulseek configuration

The Soulseek client reads connection details from either environment variables or an optional JSON configuration file. The following values are supported:

| Environment variable      | JSON key          | Description                               |
|---------------------------|-------------------|-------------------------------------------|
| `SLSKD_URL`               | `slskd_url`       | Base URL of the running slskd instance.   |
| `SLSKD_API_KEY`           | `api_key`         | API key used to authenticate with slskd.  |
| `SLSKD_DOWNLOAD_PATH`     | `download_path`   | Directory where downloads are written.    |

By default the service looks for a `config.json` file (configurable through `HARMONY_CONFIG`). Soulseek-related settings can be provided under a `"soulseek"` object and will be merged with the values coming from the environment.
