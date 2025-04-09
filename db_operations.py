import os
import json
import logging
import time
from pathlib import Path
import psycopg2
from psycopg2 import pool
from psycopg2.extras import DictCursor, execute_values
import configparser
import sqlite3
from contextlib import contextmanager  # Add this import
import re

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# PostgreSQL connection pool
pg_pool = None

def get_config():
    """Read database configuration from pump.conf"""
    config = configparser.ConfigParser()
    config_path = os.path.join(os.path.dirname(__file__), 'pump.conf')
    if os.path.exists(config_path):
        config.read(config_path)
    else:
        # Use default configuration
        config['DATABASE'] = {
            'host': 'localhost',
            'port': '5432',
            'user': 'pump',
            'password': 'Ge3hgU07bXlBigvTbRSX',
            'dbname': 'pump',
            'min_connections': '1',
            'max_connections': '10'
        }
    
    return config

def initialize_connection_pool():
    """Initialize PostgreSQL connection pool"""
    global pg_pool
    
    if (pg_pool is not None):
        return pg_pool
    
    config = get_config()
    db_config = config['DATABASE']
    
    try:
        pg_pool = psycopg2.pool.SimpleConnectionPool(
            minconn=int(db_config.get('min_connections', 1)),
            maxconn=int(db_config.get('max_connections', 10)),
            host=db_config.get('host', 'localhost'),
            port=db_config.get('port', '5432'),
            user=db_config.get('user', 'pump'),
            password=db_config.get('password', 'Ge3hgU07bXlBigvTbRSX'),
            dbname=db_config.get('dbname', 'pump')
        )
        logger.info("PostgreSQL connection pool initialized")
        return pg_pool
    except Exception as e:
        logger.error(f"Error initializing PostgreSQL connection pool: {e}")
        raise

def get_connection():
    """Get a connection from the pool with retry logic"""
    global pg_pool
    
    if pg_pool is None:
        pg_pool = initialize_connection_pool()
    
    max_retries = 5
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            conn = pg_pool.getconn()
            return conn
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"Failed to get connection (attempt {attempt+1}/{max_retries}): {e}")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                logger.error(f"Failed to get connection after {max_retries} attempts: {e}")
                raise
    
    raise Exception("Failed to get database connection")

def release_connection(conn):
    """Return a connection to the pool"""
    global pg_pool
    
    if pg_pool is not None and conn is not None:
        pg_pool.putconn(conn)

def execute_query(query, params=None, fetchone=False, commit=False):
    """Execute a query and return results"""
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute(query, params)
            
            if commit:
                conn.commit()
            
            if cursor.description:
                if fetchone:
                    result = dict(cursor.fetchone()) if cursor.rowcount > 0 else None
                else:
                    result = [dict(row) for row in cursor.fetchall()]
                return result
            
            return None
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        if conn:
            release_connection(conn)

def execute_many(query, params_list, commit=True):
    """Execute many operations in a single transaction"""
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            execute_values(cursor, query, params_list)
            
            if commit:
                conn.commit()
            
            return cursor.rowcount
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Database error in execute_many: {e}")
        raise
    finally:
        if conn:
            release_connection(conn)

def initialize_database():
    """Initialize the database with required tables"""
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            # Create tracks table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tracks (
                    id SERIAL PRIMARY KEY,
                    file_path TEXT UNIQUE,
                    title TEXT,
                    artist TEXT,
                    album TEXT,
                    genre TEXT,
                    year INTEGER,
                    duration FLOAT,
                    sample_rate INTEGER,
                    bit_rate INTEGER,
                    channels INTEGER,
                    album_art_url TEXT,
                    date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    liked BOOLEAN DEFAULT FALSE,
                    analysis_status TEXT DEFAULT 'pending',
                    metadata_source TEXT,
                    metadata_updated_at TIMESTAMP
                )
            """)
            
            # Create audio_features table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audio_features (
                    track_id INTEGER PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
                    tempo FLOAT,
                    key INTEGER,
                    energy FLOAT,
                    danceability FLOAT,
                    acousticness FLOAT,
                    instrumentalness FLOAT,
                    valence FLOAT,
                    loudness FLOAT,
                    mode INTEGER,
                    time_signature INTEGER,
                    analysis_version TEXT
                )
            """)
            
            # Create playlists table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS playlists (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create playlist_items table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS playlist_items (
                    playlist_id INTEGER REFERENCES playlists(id) ON DELETE CASCADE,
                    track_id INTEGER REFERENCES tracks(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    PRIMARY KEY (playlist_id, track_id)
                )
            """)
            
            conn.commit()
            logger.info("Database initialized")
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error initializing database: {e}")
    finally:
        if conn:
            release_connection(conn)

def insert_track(track_data):
    """Insert a new track into the database"""
    query = """
        INSERT INTO tracks (
            file_path, title, artist, album, genre, year, duration,
            sample_rate, bit_rate, channels, album_art_url
        ) VALUES (
            %(file_path)s, %(title)s, %(artist)s, %(album)s, %(genre)s, %(year)s, %(duration)s,
            %(sample_rate)s, %(bit_rate)s, %(channels)s, %(album_art_url)s
        ) ON CONFLICT (file_path) DO UPDATE SET
            title = EXCLUDED.title,
            artist = EXCLUDED.artist,
            album = EXCLUDED.album,
            genre = EXCLUDED.genre,
            year = EXCLUDED.year,
            duration = EXCLUDED.duration,
            sample_rate = EXCLUDED.sample_rate,
            bit_rate = EXCLUDED.bit_rate,
            channels = EXCLUDED.channels,
            album_art_url = EXCLUDED.album_art_url
        RETURNING id
    """
    try:
        result = execute_query(query, track_data, fetchone=True, commit=True)
        return result['id'] if result else None
    except Exception as e:
        logger.error(f"Error inserting track: {e}")
        raise

def update_track_audio_features(track_id, features):
    """Update audio features for a track"""
    features['track_id'] = track_id
    
    query = """
        INSERT INTO audio_features (
            track_id, tempo, key, energy, danceability, acousticness,
            instrumentalness, valence, loudness, mode, time_signature, analysis_version
        ) VALUES (
            %(track_id)s, %(tempo)s, %(key)s, %(energy)s, %(danceability)s, %(acousticness)s,
            %(instrumentalness)s, %(valence)s, %(loudness)s, %(mode)s, %(time_signature)s, %(analysis_version)s
        ) ON CONFLICT (track_id) DO UPDATE SET
            tempo = EXCLUDED.tempo,
            key = EXCLUDED.key,
            energy = EXCLUDED.energy,
            danceability = EXCLUDED.danceability,
            acousticness = EXCLUDED.acousticness,
            instrumentalness = EXCLUDED.instrumentalness,
            valence = EXCLUDED.valence,
            loudness = EXCLUDED.loudness,
            mode = EXCLUDED.mode,
            time_signature = EXCLUDED.time_signature,
            analysis_version = EXCLUDED.analysis_version
    """
    try:
        execute_query(query, features, commit=True)
    except Exception as e:
        logger.error(f"Error updating audio features: {e}")
        raise

def get_track_by_id(track_id):
    """Get track information by ID"""
    query = """
        SELECT t.*, af.*
        FROM tracks t
        LEFT JOIN audio_features af ON t.id = af.track_id
        WHERE t.id = %s
    """
    try:
        return execute_query(query, (track_id,), fetchone=True)
    except Exception as e:
        logger.error(f"Error getting track by ID: {e}")
        return None

def get_track_by_path(file_path):
    """Get track information by file path"""
    query = """
        SELECT t.*, af.*
        FROM tracks t
        LEFT JOIN audio_features af ON t.id = af.track_id
        WHERE t.file_path = %s
    """
    try:
        return execute_query(query, (file_path,), fetchone=True)
    except Exception as e:
        logger.error(f"Error getting track by path: {e}")
        return None

def search_tracks(search_term, limit=50, offset=0):
    """Search tracks by title, artist or album"""
    search_pattern = f"%{search_term}%"
    query = """
        SELECT t.*, af.energy, af.danceability, af.valence
        FROM tracks t
        LEFT JOIN audio_features af ON t.id = af.track_id
        WHERE 
            t.title ILIKE %s OR 
            t.artist ILIKE %s OR 
            t.album ILIKE %s
        ORDER BY t.title
        LIMIT %s OFFSET %s
    """
    
    params = (search_pattern, search_pattern, search_pattern, limit, offset)
    try:
        return execute_query(query, params)
    except Exception as e:
        logger.error(f"Error searching tracks: {e}")
        return []

def get_all_tracks(limit=None, offset=None):
    """Get all tracks with optional pagination"""
    try:
        query = """
            SELECT t.*, af.energy, af.danceability, af.valence
            FROM tracks t
            LEFT JOIN audio_features af ON t.id = af.track_id
            ORDER BY t.artist, t.album, t.title
        """
        
        # Add pagination if specified
        if limit is not None:
            query += " LIMIT %s"
            params = (limit,)
            
            if offset is not None:
                query += " OFFSET %s"
                params = (limit, offset)
        else:
            params = None
            
        return execute_query(query, params)
    except Exception as e:
        logger.error(f"Error getting all tracks: {e}")
        return []

def get_recent_tracks(limit=20):
    """Get recently added tracks"""
    query = """
        SELECT t.*, af.energy, af.danceability, af.valence
        FROM tracks t
        LEFT JOIN audio_features af ON t.id = af.track_id
        ORDER BY t.date_added DESC
        LIMIT %s
    """
    try:
        return execute_query(query, (limit,))
    except Exception as e:
        logger.error(f"Error getting recent tracks: {e}")
        return []

def get_liked_tracks():
    """Get liked tracks"""
    query = """
        SELECT t.*, af.energy, af.danceability, af.valence
        FROM tracks t
        LEFT JOIN audio_features af ON t.id = af.track_id
        WHERE t.liked = TRUE
        ORDER BY t.artist, t.album, t.title
    """
    try:
        return execute_query(query)
    except Exception as e:
        logger.error(f"Error getting liked tracks: {e}")
        return []

def toggle_track_like(track_id):
    """Toggle the liked status of a track"""
    query = """
        UPDATE tracks
        SET liked = NOT liked
        WHERE id = %s
        RETURNING liked
    """
    try:
        result = execute_query(query, (track_id,), fetchone=True, commit=True)
        return result['liked'] if result else False
    except Exception as e:
        logger.error(f"Error toggling track like status: {e}")
        return False

@contextmanager
def optimized_connection(db_path, in_memory=False, cache_size_mb=75):
    """Context manager that provides an optimized SQLite connection"""
    conn = None
    try:
        # If in-memory mode is requested and a connection exists in thread-local storage, use that
        if in_memory and hasattr(_thread_local, 'conn'):
            conn = _thread_local.conn
            # Verify connection is still valid
            try:
                conn.execute("SELECT 1")
            except sqlite3.Error:
                # Connection is invalid, create a new one
                logger.warning("In-memory connection was invalid, creating new connection")
                conn = get_optimized_connection(db_path, in_memory, cache_size_mb)
                _thread_local.conn = conn
        else:
            # Create a new connection
            conn = get_optimized_connection(db_path, in_memory, cache_size_mb)
            
        yield conn
    finally:
        # Only close the connection if it's not in-memory
        # This is the key fix - don't close in-memory connections
        if conn and not in_memory:
            conn.close()

def create_playlist(name, description=""):
    """Create a new playlist"""
    query = """
        INSERT INTO playlists (name, description)
        VALUES (%s, %s)
        RETURNING id
    """
    try:
        result = execute_query(query, (name, description), fetchone=True, commit=True)
        return result['id'] if result else None
    except Exception as e:
        logger.error(f"Error creating playlist: {e}")
        raise

def get_playlist(playlist_id):
    """Get playlist details by ID"""
    query = "SELECT * FROM playlists WHERE id = %s"
    try:
        return execute_query(query, (playlist_id,), fetchone=True)
    except Exception as e:
        logger.error(f"Error getting playlist: {e}")
        return None

def get_all_playlists():
    """Get all playlists"""
    query = """
        SELECT p.*, COUNT(pt.track_id) as track_count
        FROM playlists p
        LEFT JOIN playlist_tracks pt ON p.id = pt.playlist_id
        GROUP BY p.id
        ORDER BY p.name
    """
    try:
        return execute_query(query)
    except Exception as e:
        logger.error(f"Error getting all playlists: {e}")
        return []

def add_track_to_playlist(playlist_id, track_id, position=None):
    """Add a track to a playlist"""
    if position is None:
        # Get the highest position and add 1
        position_query = """
            SELECT COALESCE(MAX(position), 0) + 1 AS next_position
            FROM playlist_tracks
            WHERE playlist_id = %s
        """
        result = execute_query(position_query, (playlist_id,), fetchone=True)
        position = result['next_position'] if result else 1
    
    query = """
        INSERT INTO playlist_tracks (playlist_id, track_id, position)
        VALUES (%s, %s, %s)
        ON CONFLICT (playlist_id, track_id) DO UPDATE SET position = EXCLUDED.position
        RETURNING id
    """
    try:
        result = execute_query(query, (playlist_id, track_id, position), fetchone=True, commit=True)
        return result['id'] if result else None
    except Exception as e:
        logger.error(f"Error adding track to playlist: {e}")
        return None

def get_playlist_tracks(playlist_id):
    """Get all tracks in a playlist ordered by position"""
    query = """
        SELECT t.*, pt.position
        FROM playlist_tracks pt
        JOIN tracks t ON pt.track_id = t.id
        LEFT JOIN audio_features af ON t.id = af.track_id
        WHERE pt.playlist_id = %s
        ORDER BY pt.position
    """
    try:
        return execute_query(query, (playlist_id,))
    except Exception as e:
        logger.error(f"Error getting playlist tracks: {e}")
        return []

def remove_track_from_playlist(playlist_id, track_id):
    """Remove a track from a playlist"""
    query = """
        DELETE FROM playlist_tracks
        WHERE playlist_id = %s AND track_id = %s
    """
    try:
        execute_query(query, (playlist_id, track_id), commit=True)
        return True
    except Exception as e:
        logger.error(f"Error removing track from playlist: {e}")
        return False

def delete_playlist(playlist_id):
    """Delete a playlist and its track associations"""
    query = "DELETE FROM playlists WHERE id = %s"
    try:
        execute_query(query, (playlist_id,), commit=True)
        return True
    except Exception as e:
        logger.error(f"Error deleting playlist: {e}")
        return False

def update_artist_image(artist, image_url):
    """Update or insert artist image URL"""
    query = """
        INSERT INTO artist_images (artist, image_url)
        VALUES (%s, %s)
        ON CONFLICT (artist) DO UPDATE SET
            image_url = EXCLUDED.image_url,
            last_updated = CURRENT_TIMESTAMP
    """
    try:
        execute_query(query, (artist, image_url), commit=True)
        return True
    except Exception as e:
        logger.error(f"Error updating artist image: {e}")
        return False

def get_artist_image(artist):
    """Get artist image URL"""
    query = "SELECT image_url FROM artist_images WHERE artist = %s"
    try:
        result = execute_query(query, (artist,), fetchone=True)
        return result['image_url'] if result else None
    except Exception as e:
        logger.error(f"Error getting artist image: {e}")
        return None

def get_all_artists():
    """Get all artists with track counts and image URLs"""
    query = """
        SELECT 
            t.artist,
            COUNT(t.id) AS track_count,
            ai.image_url AS artist_image_url
        FROM tracks t
        LEFT JOIN artist_images ai ON t.artist = ai.artist
        WHERE t.artist IS NOT NULL AND t.artist != ''
        GROUP BY t.artist, ai.image_url
        ORDER BY t.artist
    """
    try:
        return execute_query(query)
    except Exception as e:
        logger.error(f"Error getting all artists: {e}")
        return []

def get_all_albums():
    """Get all albums with track counts and album art URLs"""
    query = """
        SELECT 
            t.album,
            t.artist,
            COUNT(t.id) AS track_count,
            MIN(t.album_art_url) AS album_art_url,
            MIN(t.id) AS sample_track
        FROM tracks t
        WHERE t.album IS NOT NULL AND t.album != ''
        GROUP BY t.album, t.artist
        ORDER BY t.artist, t.album
    """
    try:
        return execute_query(query)
    except Exception as e:
        logger.error(f"Error getting all albums: {e}")
        return []

def get_album_tracks(album, artist=None):
    """Get all tracks from an album, optionally filtered by artist"""
    if artist:
        query = """
            SELECT t.*
            FROM tracks t
            WHERE t.album = %s AND t.artist = %s
            ORDER BY t.title
        """
        params = (album, artist)
    else:
        query = """
            SELECT t.*
            FROM tracks t
            WHERE t.album = %s
            ORDER BY t.title
        """
        params = (album,)
    
    try:
        return execute_query(query, params)
    except Exception as e:
        logger.error(f"Error getting album tracks: {e}")
        return []

def get_artist_tracks(artist):
    """Get all tracks by an artist"""
    query = """
        SELECT t.*
        FROM tracks t
        WHERE t.artist = %s
        ORDER BY t.album, t.title
    """
    try:
        return execute_query(query, (artist,))
    except Exception as e:
        logger.error(f"Error getting artist tracks: {e}")
        return []

def get_library_stats():
    """Get statistics about the music library"""
    stats_query = """
        SELECT
            (SELECT COUNT(*) FROM tracks) AS total_tracks,
            (SELECT COUNT(DISTINCT artist) FROM tracks WHERE artist IS NOT NULL AND artist != '') AS total_artists,
            (SELECT COUNT(DISTINCT album) FROM tracks WHERE album IS NOT NULL AND album != '') AS total_albums,
            (SELECT COUNT(*) FROM tracks WHERE liked = TRUE) AS liked_tracks,
            (SELECT SUM(duration) FROM tracks) AS total_duration,
            (SELECT COUNT(*) FROM tracks WHERE audio_features.track_id IS NOT NULL) AS analyzed_tracks
        FROM tracks
        LEFT JOIN audio_features ON tracks.id = audio_features.track_id
        LIMIT 1
    """
    try:
        result = execute_query(stats_query, fetchone=True)
        if result:
            # Convert total_duration from seconds to hours
            if result['total_duration']:
                result['total_duration_hours'] = round(result['total_duration'] / 3600, 1)
            return result
        return {}
    except Exception as e:
        logger.error(f"Error getting library stats: {e}")
        return {}

def save_metadata_cache(artist, album, title, source, data):
    """Save metadata to the cache"""
    query = """
        INSERT INTO metadata_cache (artist, album, title, source, data)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (artist, album, title, source) DO UPDATE SET
            data = EXCLUDED.data,
            last_updated = CURRENT_TIMESTAMP
    """
    try:
        execute_query(query, (artist, album, title, source, json.dumps(data)), commit=True)
        return True
    except Exception as e:
        logger.error(f"Error saving metadata cache: {e}")
        return False

def get_metadata_cache(artist, album, title, source):
    """Get metadata from the cache"""
    query = """
        SELECT data
        FROM metadata_cache
        WHERE artist = %s AND album = %s AND title = %s AND source = %s
    """
    try:
        result = execute_query(query, (artist, album, title, source), fetchone=True)
        return json.loads(result['data']) if result else None
    except Exception as e:
        logger.error(f"Error getting metadata cache: {e}")
        return None

def update_cache_stats(cache_type, hit=False):
    """Update cache statistics"""
    query = """
        INSERT INTO cache_stats (cache_type, total_entries, hits, misses)
        VALUES (%s, 1, %s, %s)
        ON CONFLICT (cache_type) DO UPDATE SET
            total_entries = cache_stats.total_entries + 1,
            hits = cache_stats.hits + %s,
            misses = cache_stats.misses + %s,
            last_updated = CURRENT_TIMESTAMP
    """
    hit_val = 1 if hit else 0
    miss_val = 0 if hit else 1
    try:
        execute_query(query, (cache_type, hit_val, miss_val, hit_val, miss_val), commit=True)
    except Exception as e:
        logger.error(f"Error updating cache stats: {e}")

def get_cache_stats():
    """Get cache statistics"""
    query = "SELECT * FROM cache_stats"
    try:
        return execute_query(query)
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        return []

def clear_cache(cache_type=None):
    """Clear cache entries and reset stats"""
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            # Clear cache entries
            if cache_type:
                cursor.execute("DELETE FROM metadata_cache WHERE source = %s", (cache_type,))
                cursor.execute("UPDATE cache_stats SET total_entries=0, hits=0, misses=0 WHERE cache_type = %s", (cache_type,))
            else:
                cursor.execute("DELETE FROM metadata_cache")
                cursor.execute("UPDATE cache_stats SET total_entries=0, hits=0, misses=0")
            
            conn.commit()
        return True
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error clearing cache: {e}")
        return False
    finally:
        if conn:
            release_connection(conn)

def save_setting(key, value):
    """Save a setting to the database"""
    query = """
        INSERT INTO settings (key, value)
        VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET
            value = EXCLUDED.value,
            last_updated = CURRENT_TIMESTAMP
    """
    try:
        execute_query(query, (key, value), commit=True)
        return True
    except Exception as e:
        logger.error(f"Error saving setting: {e}")
        return False

def get_setting(key, default=None):
    """Get a setting from the database"""
    query = "SELECT value FROM settings WHERE key = %s"
    try:
        result = execute_query(query, (key,), fetchone=True)
        return result['value'] if result else default
    except Exception as e:
        logger.error(f"Error getting setting: {e}")
        return default

def get_all_settings():
    """Get all settings as a dictionary"""
    query = "SELECT key, value FROM settings"
    try:
        settings = {}
        results = execute_query(query)
        for row in results:
            settings[row['key']] = row['value']
        return settings
    except Exception as e:
        logger.error(f"Error getting all settings: {e}")
        return {}

def get_similar_tracks(track_id, limit=20):
    """Find similar tracks based on audio features"""
    # First get the audio features of the reference track
    features_query = """
        SELECT 
            track_id,
            energy,
            danceability,
            acousticness,
            instrumentalness,
            valence
        FROM audio_features
        WHERE track_id = %s
    """
    
    try:
        ref_features = execute_query(features_query, (track_id,), fetchone=True)
        if not ref_features:
            return []
        
        # Then find similar tracks using a weighted Euclidean distance
        similar_query = """
            WITH track_distances AS (
                SELECT 
                    t.id,
                    t.title,
                    t.artist,
                    t.album,
                    t.album_art_url,
                    t.liked,
                    SQRT(
                        POWER(af.energy - %s, 2) * 1.0 +
                        POWER(af.danceability - %s, 2) * 1.0 +
                        POWER(af.acousticness - %s, 2) * 0.8 +
                        POWER(af.instrumentalness - %s, 2) * 0.8 +
                        POWER(af.valence - %s, 2) * 1.2
                    ) AS distance
                FROM audio_features af
                JOIN tracks t ON af.track_id = t.id
                WHERE af.track_id != %s
            )
            SELECT 
                id, 
                title, 
                artist, 
                album, 
                album_art_url,
                liked,
                distance
            FROM track_distances
            ORDER BY distance ASC
            LIMIT %s
        """
        
        params = (
            ref_features['energy'], 
            ref_features['danceability'],
            ref_features['acousticness'],
            ref_features['instrumentalness'],
            ref_features['valence'],
            track_id,
            limit
        )
        
        return execute_query(similar_query, params)
    except Exception as e:
        logger.error(f"Error finding similar tracks: {e}")
        return []

def save_memory_db_to_disk(in_memory_conn, disk_path=None):
    """
    Compatibility function for PostgreSQL (no-op).
    
    In SQLite, this would save an in-memory database to disk, but in PostgreSQL
    all changes are already persisted through transactions.
    
    Args:
        in_memory_conn: Connection object (will be properly released)
        disk_path: Ignored (kept for compatibility with SQLite)
    
    Returns:
        bool: Always returns True for compatibility
    """
    logger.info("PostgreSQL compatibility: save_memory_db_to_disk called (no-op)")
    
    # Properly release the connection if it's a valid connection
    if in_memory_conn:
        try:
            release_connection(in_memory_conn)
        except Exception as e:
            logger.error(f"Error releasing connection in save_memory_db_to_disk: {e}")
    
    return True

def import_disk_db_to_memory(disk_path=None, in_memory_conn=None):
    """
    Compatibility function for PostgreSQL that returns a database connection.
    
    In SQLite, this would import a disk database to memory, but in PostgreSQL
    we simply return a connection from the pool since PostgreSQL doesn't have
    a concept of in-memory databases.
    
    Args:
        disk_path: Ignored (kept for compatibility with SQLite)
        in_memory_conn: Ignored (kept for compatibility with SQLite)
        
    Returns:
        psycopg2.extensions.connection: A PostgreSQL connection
    """
    logger.info("PostgreSQL compatibility: import_disk_db_to_memory called (returning regular connection)")
    try:
        # Just return a standard connection from the pool
        return get_connection()
    except Exception as e:
        logger.error(f"Error in import_disk_db_to_memory compatibility function: {e}")
        raise

# Add this function to db_operations.py
def execute_query_dict(connection, query, params=None):
    """
    Execute a query and return results as a list of dictionaries.
    
    Args:
        connection: Database connection object
        query: SQL query string
        params: Optional parameters for the query
        
    Returns:
        List of dictionaries, where each dictionary represents a row with column names as keys
    """
    cursor = connection.cursor()
    try:
        if (params):
            cursor.execute(query, params)
        else:
            cursor.execute(query)
            
        # Get column names from cursor description
        columns = [col[0] for col in cursor.description] if cursor.description else []
        
        # Convert results to list of dictionaries
        result = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return result
    except Exception as e:
        print(f"Error executing query: {e}")
        raise
    finally:
        cursor.close()

def execute_with_retry(query, params=None, max_retries=3, retry_delay=1, commit=False):
    """Execute a query with retry logic if it fails"""
    conn = None
    retries = 0
    
    while retries < max_retries:
        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute(query, params)
            
            if commit:
                conn.commit()
                
            if cursor.description:
                result = cursor.fetchall()
                return result
            return None
                
        except Exception as e:
            retries += 1
            logger.warning(f"Database operation failed, retry {retries}/{max_retries}: {e}")
            
            if conn:
                conn.rollback()
                
            if retries >= max_retries:
                logger.error(f"Max retries reached, operation failed: {e}")
                raise
                
            time.sleep(retry_delay)
        finally:
            if conn:
                release_connection(conn)

def execute_query_dict(query, params=None, fetchone=False, in_memory=False, cache_size_mb=None):
    """Execute a query and return results as a list of dictionaries
    
    Args:
        query: SQL query string
        params: Optional parameters for the query
        fetchone: Whether to fetch only one row
        in_memory: Ignored (kept for compatibility with SQLite)
        cache_size_mb: Ignored (kept for compatibility with SQLite)
        
    Returns:
        A list of dictionaries (or single dictionary if fetchone=True)
    """
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor(cursor_factory=DictCursor)
        
        cursor.execute(query, params)
        
        if fetchone:
            result = cursor.fetchone()
            return dict(result) if result else None
        else:
            results = cursor.fetchall()
            return [dict(row) for row in results]
            
    except Exception as e:
        logger.error(f"Error executing query: {e}")
        raise
    finally:
        if conn:
            release_connection(conn)

def transaction_context(db_path=None, in_memory=False, cache_size_mb=None):
    """Context manager for transactions"""
    class TransactionContextManager:
        def __enter__(self):
            self.conn = get_connection()
            self.cursor = self.conn.cursor()
            return self.conn, self.cursor
            
        def __exit__(self, exc_type, exc_val, exc_tb):
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
            release_connection(self.conn)
            
    return TransactionContextManager()

def get_optimized_connection(db_path=None, in_memory=False, cache_size_mb=None, check_same_thread=None):
    """Get an optimized database connection (PostgreSQL compatibility function)
    
    This function provides compatibility with code that was written for SQLite
    but now works with PostgreSQL.
    
    Args:
        db_path: Ignored (kept for compatibility)
        in_memory: Ignored (kept for compatibility)
        cache_size_mb: Ignored (kept for compatibility)
        check_same_thread: Ignored (kept for compatibility with SQLite)
        
    Returns:
        A database connection from the pool
    """
    # Simply get a connection from the pool
    return get_connection()

def optimized_connection(db_path=None, in_memory=False, cache_size_mb=None):
    """Context manager for database connections (PostgreSQL compatibility)
    
    This function provides compatibility with code that was written for SQLite
    but now works with PostgreSQL. It ignores SQLite-specific parameters.
    
    Args:
        db_path: Ignored (kept for compatibility)
        in_memory: Ignored (kept for compatibility)
        cache_size_mb: Ignored (kept for compatibility)
        
    Returns:
        A context manager that yields a database connection
    """
    class ConnectionContextManager:
        def __enter__(self):
            self.conn = get_connection()
            return self.conn
            
        def __exit__(self, exc_type, exc_val, exc_tb):
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
            release_connection(self.conn)
    
    return ConnectionContextManager()

def execute_query_row(query, params=None, in_memory=False, cache_size_mb=None):
    """Execute a query and return a single row of results
    
    Args:
        query: SQL query string
        params: Optional parameters for the query
        in_memory: Ignored (kept for compatibility with SQLite)
        cache_size_mb: Ignored (kept for compatibility with SQLite)
        
    Returns:
        A single row of results or None if no results
    """
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute(query, params)
        result = cursor.fetchone()
        
        return result
    except Exception as e:
        logger.error(f"Error executing query for single row: {e}")
        return None
    finally:
        if conn:
            release_connection(conn)

def sanitize_for_postgres(value):
    """Remove null bytes and other problematic characters from strings for PostgreSQL"""
    if isinstance(value, str):
        # Replace NUL bytes with spaces
        return value.replace('\x00', ' ')
    return value

def execute_write(query, params=None, in_memory=False, cache_size_mb=None):
    """Execute a write query using the appropriate database connection
    
    This handles both SQLite and PostgreSQL connections properly
    """
    try:
        conn = get_connection()
        # Check if this is a PostgreSQL connection
        if hasattr(conn, 'cursor'):
            # PostgreSQL connection - use cursor to execute
            cursor = conn.cursor()
            cursor.execute(query, params or ())
            conn.commit()
            result = True
        else:
            # SQLite connection - direct execution
            if params:
                conn.execute(query, params)
            else:
                conn.execute(query)
            conn.commit()
            result = True
        
        release_connection(conn)
        return result
    except Exception as e:
        logger.error(f"Error executing write query: {e}")
        if conn:
            release_connection(conn)
        return False

def reset_database_locks():
    """
    Reset any database locks (PostgreSQL compatibility function)
    
    In a PostgreSQL environment, this primarily involves ensuring connections
    are properly released back to the pool and any hanging transactions are
    terminated.
    
    Returns:
        bool: True if successful
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            # Check for long-running transactions and terminate if needed
            cursor.execute("""
                SELECT pg_terminate_backend(pid) 
                FROM pg_stat_activity 
                WHERE datname = current_database()
                AND state = 'idle in transaction'
                AND (now() - state_change) > interval '30 minutes'
            """)
        conn.commit()
        logger.info("Database locks reset successfully")
        return True
    except Exception as e:
        logger.error(f"Error resetting database locks: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            release_connection(conn)

def trigger_db_save():
    """
    Trigger a database save (compatibility function for PostgreSQL)
    
    In SQLite with in-memory databases, this would save to disk.
    In PostgreSQL, transactions are already persisted, so this is a no-op.
    
    Returns:
        bool: Always returns True for compatibility
    """
    logger.debug("trigger_db_save called (no-op in PostgreSQL)")
    return True

def check_database_stats(db_path=None, in_memory=False, cache_size_mb=None):
    """Get database statistics
    
    Args:
        db_path: Ignored (kept for compatibility)
        in_memory: Ignored (kept for compatibility) 
        cache_size_mb: Ignored (kept for compatibility)
        
    Returns:
        dict: Database statistics
    """
    stats = {
        'track_count': 0,
        'db_size': '0 MB'
    }
    
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Count total tracks
        cursor.execute("SELECT COUNT(*) FROM tracks")
        result = cursor.fetchone()
        stats['track_count'] = result[0] if result else 0
        
        # Get database size
        cursor.execute("""
            SELECT pg_size_pretty(pg_database_size(current_database())) as size
        """)
        result = cursor.fetchone()
        stats['db_size'] = result[0] if result else '0 MB'
        
        release_connection(conn)
        return stats
    except Exception as e:
        logger.error(f"Error checking database stats: {e}")
        if 'conn' in locals() and conn:
            release_connection(conn)
        return stats

# Add this function at the end of the file

def set_db_config(db_path=None, in_memory=False, cache_size_mb=None):
    """Configure global database settings
    
    Args:
        db_path: Path to database file
        in_memory: Whether to use in-memory database
        cache_size_mb: Cache size for database
    """
    global DB_PATH, DB_IN_MEMORY, DB_CACHE_SIZE_MB
    DB_PATH = db_path
    DB_IN_MEMORY = in_memory
    DB_CACHE_SIZE_MB = cache_size_mb
    logger.info(f"Database configuration set: path={db_path}, in_memory={in_memory}, cache_size={cache_size_mb}MB")

# Initialize the database when the module is imported
try:
    initialize_connection_pool()
    initialize_database()
except Exception as e:
    logger.error(f"Database initialization error: {e}")