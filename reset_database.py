import os
from db_operations import get_optimized_connection



# Create new database
cursor = conn.cursor()

try:
    # Create audio_files table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS audio_files (
        id INTEGER PRIMARY KEY,
        file_path TEXT UNIQUE,
        title TEXT,
        artist TEXT,
        album TEXT,
        duration REAL,
        date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        metadata_source TEXT,
        album_art_url TEXT
    )
    ''')

    # Create audio features table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS audio_features (
        file_id TEXT PRIMARY KEY,
        tempo REAL,
        loudness REAL,
        key INTEGER,
        mode INTEGER,
        time_signature INTEGER,
        energy REAL,
        danceability REAL,
        brightness REAL,
        noisiness REAL
    )
    ''')

    # Create playlists tables
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS playlists (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS playlist_items (
        id INTEGER PRIMARY KEY,
        playlist_id INTEGER NOT NULL,
        track_id INTEGER NOT NULL,
        position INTEGER NOT NULL,
        FOREIGN KEY (playlist_id) REFERENCES playlists (id) ON DELETE CASCADE,
        FOREIGN KEY (track_id) REFERENCES audio_files (id),
        UNIQUE(playlist_id, track_id)
    )
    ''')

    conn.commit()
    print("Database reset complete. Run your analysis to rebuild the database.")
except Exception as e:
    conn.rollback()
    print(f"Error resetting database: {e}")
finally:
    conn.close()