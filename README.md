
![logo copy 2](https://github.com/user-attachments/assets/d531b729-c97b-4de2-92e5-f631f4630227)

PUMP is a web-based music player that analyzes your music collection and creates personalized playlists based on audio features and similarity.

## Running PUMP

### 1. Using the Start Script (Recommended):

The start script will check dependencies, create the environment if needed, and start the application:

```bash
chmod +x start_pump.sh
./start_pump.sh
```

### 2. Manual Start:

If you prefer to run the application manually:

```bash
# Activate your environment if not already active
conda activate pump_env  # or source venv/bin/activate

# Run the application
python web_player.py
```

### 3. Access the Web Interface

Open your browser and navigate to:
```
http://localhost:8080
```

## Configuration

On first run, PUMP creates a pump.conf file where you can configure:

- Server settings (port, host)
- Music library location
- API keys for music services (LastFM, Spotify)
- Cache settings

Edit this file before starting the application again or use the Settings page in the app.

## Adding Your Music

1. Go to Settings in the application
2. Set your music folder path
3. Check "Scan recursively" if you want to include subdirectories
4. Click "Start Analysis"

The analysis process may take time depending on your library size as it extracts audio features for playlist generation.

## Features

- Music library management
- Audio signal analysis
- Smart playlist generation
- Metadata enrichment
- Recently added tracking
- Advanced audio search

## Troubleshooting

### Common Issues:

1. **Audio dependencies errors**: If you encounter issues with audio libraries, try installing system dependencies mentioned above.

2. **Pygame/PortAudio errors**: Some systems might need additional dependencies:
   ```bash
   sudo apt install -y libportmidi-dev
   pip install pygame
   ```

3. **Permissions issues**: Ensure you have read access to your music files and write access to the application directory.

4. **Database errors**: If the application fails to start due to database issues, remove the pump.db file and restart to create a fresh database.

---

For more details, please see the [full documentation](https://github.com/icewall905/pump/wiki) or open an issue on GitHub.
