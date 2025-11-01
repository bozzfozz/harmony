# Harmony

## Running with Docker

1. Build the image:

   ```bash
   docker compose build
   ```

2. Start the service in the background:

   ```bash
   docker compose up -d
   ```

The compose file maps the application to port `8080` and stores persistent data under the `./data` directory. On first startup the application initialises its SQLite database at `/config/harmony.db` automatically, ensuring the file exists before use.
