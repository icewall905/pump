import os
import time
import logging
import configparser
import psycopg2
from psycopg2 import pool
from psycopg2.extras import DictCursor, execute_values
from contextlib import contextmanager
import json
import re

# Removed sqlite3 import since we are now using PostgreSQL exclusively

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
            'port': '45432',
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
    if pg_pool is not None:
        return pg_pool

    config = get_config()
    db_config = config['DATABASE']

    try:
        pg_pool = psycopg2.pool.SimpleConnectionPool(
            minconn=int(db_config.get('min_connections', 1)),
            maxconn=int(db_config.get('max_connections', 10)),
            host=db_config.get('host', 'localhost'),
            port=db_config.get('port', '45432'),
            user=db_config.get('user', 'pump'),
            password=db_config.get('password', 'Ge3hgU07bXlBigvTbRSX'),
            dbname=db_config.get('dbname', 'pump')
        )
        logger.info(f"PostgreSQL connection pool initialized on port {db_config.get('port', '45432')}")
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
        # Validate query is not empty
        if not query or not query.strip():
            logger.error("Cannot execute empty query")
            return None
            
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        
        if fetchone:
            result = cursor.fetchone()
        else:
            result = cursor.fetchall()
        
        if commit:
            conn.commit()
            
        return result
    except Exception as e:
        logger.error(f"Error executing query: {e}")
        return None
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

            # Create playlist_items table (note: using playlist_items in all queries)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS playlist_items (
                    playlist_id INTEGER REFERENCES playlists(id) ON DELETE CASCADE,
                    track_id INTEGER REFERENCES tracks(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    PRIMARY KEY (playlist_id, track_id)
                )
            """)

            # Optionally, create additional tables if they don't exist
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS artist_images (
                    artist TEXT PRIMARY KEY,
                    image_url TEXT,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS metadata_cache (
                    artist TEXT,
                    album TEXT,
                    title TEXT,
                    source TEXT,
                    data TEXT,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (artist, album, title, source)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cache_stats (
                    cache_type TEXT PRIMARY KEY,
                    total_entries INTEGER DEFAULT 0,
                    hits INTEGER DEFAULT 0,
                    misses INTEGER DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            logger.info("Database initialized")
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error initializing database: {e}")
        raise
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
        params = None
        if limit is not None:
            query += " LIMIT %s"
            params = (limit,)
            if offset is not None:
                query += " OFFSET %s"
                params = (limit, offset)
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
def optimized_connection():
    """Context manager for PostgreSQL connections"""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
    finally:
        release_connection(conn)

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
        SELECT p.*, COUNT(pi.track_id) as track_count
        FROM playlists p
        LEFT JOIN playlist_items pi ON p.id = pi.playlist_id
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
        position_query = """
            SELECT COALESCE(MAX(position), 0) + 1 AS next_position
            FROM playlist_items
            WHERE playlist_id = %s
        """
        result = execute_query(position_query, (playlist_id,), fetchone=True)
        position = result['next_position'] if result else 1

    query = """
        INSERT INTO playlist_items (playlist_id, track_id, position)
        VALUES (%s, %s, %s)
        ON CONFLICT (playlist_id, track_id) DO UPDATE SET position = EXCLUDED.position
    """
    try:
        execute_query(query, (playlist_id, track_id, position), commit=True)
        return True
    except Exception as e:
        logger.error(f"Error adding track to playlist: {e}")
        return False

def get_playlist_tracks(playlist_id):
    """Get all tracks in a playlist ordered by position"""
    query = """
        SELECT t.*, pi.position
        FROM playlist_items pi
        JOIN tracks t ON pi.track_id = t.id
        LEFT JOIN audio_features af ON t.id = af.track_id
        WHERE pi.playlist_id = %s
        ORDER BY pi.position
    """
    try:
        return execute_query(query, (playlist_id,))
    except Exception as e:
        logger.error(f"Error getting playlist tracks: {e}")
        return []

def remove_track_from_playlist(playlist_id, track_id):
    """Remove a track from a playlist"""
    query = """
        DELETE FROM playlist_items
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
        if result and result['total_duration']:
            result['total_duration_hours'] = round(result['total_duration'] / 3600, 1)
        return result if result else {}
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
    In PostgreSQL transactions are already persisted, so this is a no-op.
    """
    logger.info("PostgreSQL compatibility: save_memory_db_to_disk called (no-op)")
    if in_memory_conn and hasattr(in_memory_conn, 'cursor'):
        try:
            in_memory_conn.commit()
            release_connection(in_memory_conn)
            logger.info("PostgreSQL connection committed and released")
        except Exception as e:
            logger.error(f"Error releasing PostgreSQL connection: {e}")
    return True

def import_disk_db_to_memory():
    """
    Compatibility function for PostgreSQL that returns a database connection.
    In PostgreSQL we simply return a connection from the pool.
    """
    logger.info("PostgreSQL compatibility: import_disk_db_to_memory called (returning regular connection)")
    try:
        return get_connection()
    except Exception as e:
        logger.error(f"Error in import_disk_db_to_memory compatibility function: {e}")
        raise

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

def execute_query_dict(query, params=None, fetchone=False):
    """Execute a query and return results as a list of dictionaries or a single dictionary."""
    try:
        conn = get_connection()
        try:
            with conn.cursor(cursor_factory=DictCursor) as cursor:
                cursor.execute(query, params if params else [])
                
                if fetchone:
                    result = cursor.fetchone()
                    return dict(result) if result else None
                else:
                    results = cursor.fetchall()
                    return [dict(row) for row in results]
        finally:
            release_connection(conn)
    except Exception as e:
        logger.error(f"Error executing query: {e}", exc_info=True)
        if fetchone:
            return None
        return []

def transaction_context():
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

def execute_query_row(query, params=None, **kwargs):
    """
    Execute a query and return a single row result
    
    This version ignores legacy SQLite parameters like in_memory for PostgreSQL compatibility
    """
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params or ())
        result = cursor.fetchone()
        return result
    except Exception as e:
        logger.error(f"Error executing query: {e}")
        return None
    finally:
        if conn:
            release_connection(conn)

def sanitize_for_postgres(value):
    """Remove null bytes and other problematic characters from strings for PostgreSQL"""
    if isinstance(value, str):
        return value.replace('\x00', '')
    return value

def execute_write(query, params=None):
    """Execute a write operation (INSERT, UPDATE, DELETE)"""
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            # Sanitize parameters if they're a dict or list
            if isinstance(params, dict):
                sanitized_params = {k: sanitize_for_postgres(v) for k, v in params.items()}
            elif isinstance(params, (list, tuple)):
                sanitized_params = [sanitize_for_postgres(p) for p in params]
            else:
                sanitized_params = params
                
            cursor.execute(query, sanitized_params)
            conn.commit()
    except Exception as e:
        logger.error(f"Error executing write query: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            release_connection(conn)

def reset_database_locks():
    """
    Reset any database locks (PostgreSQL compatibility function)
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
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
    In PostgreSQL, transactions are already persisted, so this is a no-op.
    """
    logger.debug("trigger_db_save called (no-op in PostgreSQL)")
    return True

def check_database_stats():
    """Get database statistics"""
    stats = {
        'track_count': 0,
        'db_size': '0 MB'
    }
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tracks")
        result = cursor.fetchone()
        stats['track_count'] = result[0] if result else 0
        cursor.execute("""
            SELECT pg_size_pretty(pg_database_size(current_database())) as size
        """)
        result = cursor.fetchone()
        stats['db_size'] = result[0] if result else '0 MB'
        release_connection(conn)
        return stats
    except Exception as e:
        logger.error(f"Error checking database stats: {e}")
        if conn:
            release_connection(conn)
        return stats

def set_db_config(db_path=None, in_memory=False, cache_size_mb=75):
    """
    Set global database configuration variables
    This function now accepts parameters for backward compatibility,
    but ignores them for PostgreSQL since these settings are specific to SQLite
    """
    global pg_pool
    logger.info(f"PostgreSQL compatibility: set_db_config called (ignoring SQLite-specific parameters)")
    if pg_pool is not None:
        try:
            for conn in pg_pool._used:
                try:
                    conn.close()
                except Exception:
                    pass
            pg_pool.closeall()
            pg_pool = None
            logger.info("Closed existing database connection pool")
        except Exception as e:
            logger.error(f"Error closing connection pool: {e}")
    try:
        pg_pool = initialize_connection_pool()
        logger.info("Database configuration updated and connection pool reinitialized")
        return True
    except Exception as e:
        logger.error(f"Failed to reinitialize connection pool: {e}")
        return False

def get_optimized_connection(*args, **kwargs):
    """
    Compatibility function to maintain backward compatibility with SQLite code
    that used get_optimized_connection.
    
    This simply returns a regular PostgreSQL connection.
    """
    logger.debug("get_optimized_connection called (returning standard PostgreSQL connection)")
    return get_connection()

# Initialize the database when the module is imported
try:
    initialize_connection_pool()
    initialize_database()
except Exception as e:
    logger.error(f"Database initialization error: {e}")
