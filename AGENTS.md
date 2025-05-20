# Repository Guidelines for Pump

## Setup

1. Use **Python 3.9+**.
2. Create a virtual environment `pump_env` (via conda or `python -m venv`).
3. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Start the PostgreSQL database and web player with the start script:
   ```bash
   ./start_pump.sh
   ```
   The script requires Docker and Docker Compose to be available. It launches a
   PostgreSQL container on port **45432**.
5. Alternatively, ensure a PostgreSQL server is running with the credentials in
   `pump.conf` (copy `pump.conf.example` on first run) and start the app with:
   ```bash
   python web_player.py
   ```
6. To inspect the SQLite music feature database, run:
   ```bash
   python check_db.py
   ```

## Contributing

- Format Python code with **black** before committing.
- Keep functions concise and include docstrings.
- Document new configuration options in `README.md`.

## Testing

- Verify the server starts without errors:
  ```bash
  python web_player.py > /tmp/server.log 2>&1 &
  sleep 3
  pkill -f web_player.py
  ```
  Inspect `/tmp/server.log` for issues.
- If you modify database logic, run `python check_db.py` to ensure the SQLite
  database can be queried.

## Pull Request Notes

- Summarize your changes at a high level.
- List modified files.
- Mention whether you ran the server start test.
