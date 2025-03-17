import os
import sqlite3
import random
import configparser
import logging
import hashlib
from flask import Flask, render_template, request, jsonify, Response, send_file
from music_analyzer import MusicAnalyzer
from werkzeug.serving import run_simple
import requests
from urllib.parse import unquote

import pathlib

from metadata_service import MetadataService

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger('web_player')

# Default configuration
default_config = {
    'server': {
        'host': '0.0.0.0',
        'port': '8080',
        'debug': 'true'
    },
    'database': {
        'path': 'pump.db'
    },
    'app': {
        'default_playlist_size': '10',
        'max_search_results': '50'
    },
    'music': {
        'folder_path': '',
        'recursive': 'true'
    }
}

# Load configuration
config = configparser.ConfigParser()
config_file = 'pump.conf'

# Check if config file exists and read it first
if os.path.exists(config_file):
    logger.info(f"Loading existing configuration from {config_file}")
    config.read(config_file)

# Add any missing sections or options from defaults
config_updated = False
for section, options in default_config.items():
    if not config.has_section(section):
        logger.info(f"Adding missing section: {section}")
        config.add_section(section)
        config_updated = True
    for option, value in options.items():
        if not config.has_option(section, option):
            logger.info(f"Adding missing option: {section}.{option}")
            config.set(section, option, value)
            config_updated = True

# Add API keys section if it doesn't exist
if not config.has_section('api_keys'):
    logger.info("Adding api_keys section")
    config.add_section('api_keys')
    config.set('api_keys', 'lastfm_api_key', '')
    config.set('api_keys', 'lastfm_api_secret', '')
    config_updated = True

# Add configuration for image caching
if not config.has_section('cache'):
    logger.info("Adding cache section")
    config.add_section('cache')
    config.set('cache', 'image_cache_dir', 'album_art_cache')
    config.set('cache', 'max_cache_size_mb', '500')  # 500MB default cache size
    config_updated = True

# Write config file only if it was changed or didn't exist
if config_updated or not os.path.exists(config_file):
    logger.info(f"Writing updated configuration to {config_file}")
    with open(config_file, 'w') as f:
        config.write(f)

# Get configuration values with fallbacks
try:
    HOST = config.get('server', 'host', fallback='0.0.0.0')
    PORT = config.getint('server', 'port', fallback=8080)
    DEBUG = config.getboolean('server', 'debug', fallback=True)
    DB_PATH = config.get('database', 'path', fallback='pump.db')
    DEFAULT_PLAYLIST_SIZE = config.getint('app', 'default_playlist_size', fallback=10)
    MAX_SEARCH_RESULTS = config.getint('app', 'max_search_results', fallback=50)
    
    logger.info(f"Configuration loaded successfully")
    logger.info(f"Server: {HOST}:{PORT} (debug={DEBUG})")
    logger.info(f"Database: {DB_PATH}")
except Exception as e:
    logger.error(f"Error processing configuration: {e}")
    logger.info("Using default values")
    HOST = '0.0.0.0'
    PORT = 8080
    DEBUG = True
    DB_PATH = 'pump.db'
    DEFAULT_PLAYLIST_SIZE = 10
    MAX_SEARCH_RESULTS = 50

# Get cache configuration
CACHE_DIR = config.get('cache', 'image_cache_dir', fallback='album_art_cache')
MAX_CACHE_SIZE_MB = config.getint('cache', 'max_cache_size_mb', fallback=500)

# Create cache directory if it doesn't exist
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)
    logger.info(f"Created album art cache directory: {CACHE_DIR}")

# Create Flask app
app = Flask(__name__)
try:
    analyzer = MusicAnalyzer(DB_PATH)
    logger.info("MusicAnalyzer initialized successfully")
except Exception as e:
    logger.error(f"Error initializing MusicAnalyzer: {e}")
    analyzer = None

@app.route('/')
def index():
    """Home page with search functionality"""
    return render_template('index.html')

@app.route('/search')
def search():
    """Search for tracks in the database"""
    query = request.args.get('query', '')
    
    if not query:
        return jsonify([])
    
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Use LIKE for case-insensitive search across multiple fields
        cursor.execute('''
            SELECT id, file_path, title, artist, album, album_art_url, duration
            FROM audio_files 
            WHERE title LIKE ? OR artist LIKE ? OR album LIKE ? 
            ORDER BY artist, album, title
            LIMIT ?
        ''', (f'%{query}%', f'%{query}%', f'%{query}%', MAX_SEARCH_RESULTS))
        
        tracks = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        logger.info(f"Search for '{query}' returned {len(tracks)} results")
        return jsonify(tracks)
        
    except Exception as e:
        logger.error(f"Error searching tracks: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/playlist')
def create_playlist():
    """Create a playlist based on a seed track"""
    seed_track_id = request.args.get('seed_track_id')
    playlist_size = request.args.get('size', DEFAULT_PLAYLIST_SIZE, type=int)
    
    if not seed_track_id:
        return jsonify({'error': 'Seed track ID required'}), 400
    
    try:
        # Create a playlist using the analyzer
        logger.info(f"Generating playlist with seed track ID {seed_track_id} and {playlist_size} tracks")
        
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get the seed track's file path
        cursor.execute('SELECT file_path FROM audio_files WHERE id = ?', (seed_track_id,))
        seed_track = cursor.fetchone()
        
        if not seed_track:
            conn.close()
            return jsonify({'error': 'Seed track not found'}), 404
        
        # Generate the playlist
        if analyzer:
            similar_tracks = analyzer.create_station(seed_track['file_path'], playlist_size)
            
            # Get the full details of the tracks
            playlist = []
            for track_path in similar_tracks:
                cursor.execute('''
                    SELECT id, file_path, title, artist, album, album_art_url, duration 
                    FROM audio_files 
                    WHERE file_path = ?
                ''', (track_path,))
                track = cursor.fetchone()
                if track:
                    playlist.append(dict(track))
            
            conn.close()
            logger.info(f"Generated playlist with {len(playlist)} tracks")
            return jsonify(playlist)
        else:
            conn.close()
            return jsonify({'error': 'Analyzer not available'}), 500
            
    except Exception as e:
        logger.error(f"Error creating playlist: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/explore')
def explore():
    """Get random tracks for exploration"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) as count FROM audio_files')
        count = cursor.fetchone()['count']
        
        # Get random tracks
        random_tracks = []
        if count > 0:
            sample_size = min(10, count)
            cursor.execute(f'''
                SELECT af.id, af.file_path, af.title, af.artist, af.album, af.album_art_url, af.duration
                FROM audio_files af
                ORDER BY RANDOM()
                LIMIT {sample_size}
            ''')
            
            random_tracks = [dict(row) for row in cursor.fetchall()]
            for track in random_tracks:
                if not track['title']:
                    track['title'] = os.path.basename(track['file_path'])
        
        conn.close()
        logger.info(f"Returning {len(random_tracks)} random tracks for exploration")
        return jsonify(random_tracks)
    
    except Exception as e:
        logger.error(f"Error exploring tracks: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/analyze', methods=['POST'])
def analyze_folder():
    """Analyze a music folder and add tracks to the database"""
    folder_path = request.form.get('folder_path')
    recursive = request.form.get('recursive') == 'true'
    
    # If no folder path provided, try to use the configured path
    if not folder_path:
        folder_path = config.get('music', 'folder_path', fallback='')
    
    logger.info(f"Analyzing music folder: {folder_path} (recursive={recursive})")
    
    if not folder_path or not os.path.isdir(folder_path):
        logger.error(f"Invalid folder path: {folder_path}")
        return jsonify({'error': 'Invalid folder path'}), 400
    
    try:
        # Ensure analyzer is initialized
        if not analyzer:
            logger.error("MusicAnalyzer not initialized")
            return jsonify({'error': 'Analyzer not available'}), 500
        
        # Process the directory
        result = analyzer.analyze_directory(folder_path, recursive)
        
        return jsonify({
            'success': True,
            'folder_path': folder_path,
            'files_processed': result.get('files_processed', 0),
            'tracks_added': result.get('tracks_added', 0)
        })
    
    except Exception as e:
        logger.error(f"Error analyzing folder: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    """Settings page for the app"""
    if request.method == 'POST':
        try:
            # Update API keys
            api_key = request.form.get('lastfm_api_key', '')
            api_secret = request.form.get('lastfm_api_secret', '')
            music_folder_path = request.form.get('music_folder_path', '')
            recursive = request.form.get('recursive') == 'on'
            
            # Load existing config
            config = configparser.ConfigParser()
            config.read(config_file)
            
            # Ensure sections exist
            if not config.has_section('api_keys'):
                config.add_section('api_keys')
                
            if not config.has_section('music'):
                config.add_section('music')
            
            # Update settings
            config.set('api_keys', 'lastfm_api_key', api_key)
            config.set('api_keys', 'lastfm_api_secret', api_secret)
            config.set('music', 'folder_path', music_folder_path)
            config.set('music', 'recursive', str(recursive).lower())
            
            # Write updated config
            with open(config_file, 'w') as f:
                config.write(f)
                
            # Reinitialize metadata service
            if analyzer and hasattr(analyzer, 'metadata_service'):
                analyzer.metadata_service = MetadataService(config_file)
            
            return render_template('settings.html', 
                                  message='Settings saved successfully!',
                                  lastfm_api_key=api_key,
                                  lastfm_api_secret=api_secret,
                                  music_folder_path=music_folder_path,
                                  recursive=recursive)
            
        except Exception as e:
            logger.error(f"Error saving settings: {e}")
            return render_template('settings.html', error=f'Error: {str(e)}')
    
    # For GET requests, load current settings
    try:
        config = configparser.ConfigParser()
        config.read(config_file)
        
        api_key = config.get('api_keys', 'lastfm_api_key', fallback='')
        api_secret = config.get('api_keys', 'lastfm_api_secret', fallback='')
        music_folder_path = config.get('music', 'folder_path', fallback='')
        recursive = config.getboolean('music', 'recursive', fallback=True)
        
        return render_template('settings.html', 
                              lastfm_api_key=api_key,
                              lastfm_api_secret=api_secret,
                              music_folder_path=music_folder_path,
                              recursive=recursive)
                              
    except Exception as e:
        logger.error(f"Error loading settings: {e}")
        return render_template('settings.html', error=f'Error: {str(e)}')

@app.route('/debug/metadata')
def debug_metadata():
    """Debug endpoint to check metadata in database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, file_path, title, artist, album, album_art_url, metadata_source
            FROM audio_files
            LIMIT 20
        ''')
        
        tracks = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify({
            'count': len(tracks),
            'tracks_with_art': sum(1 for t in tracks if t.get('album_art_url')),
            'tracks': tracks
        })
        
    except Exception as e:
        logger.error(f"Error fetching debug metadata: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/albumart/<path:url>')
def album_art_proxy(url):
    """Proxy for album art with local caching to avoid CORS issues and reduce API calls"""
    try:
        # Decode URL
        url = unquote(url)
        
        # Generate a cache filename based on URL hash
        url_hash = hashlib.md5(url.encode()).hexdigest()
        cache_path = os.path.join(CACHE_DIR, f"{url_hash}.jpg")
        
        # Check if the image is already in cache
        if os.path.exists(cache_path):
            logger.debug(f"Serving cached album art for: {url}")
            return send_file(cache_path, mimetype='image/jpeg')
        
        # If not in cache, fetch from source
        logger.info(f"Fetching album art from: {url}")
        
        # Fetch the image
        response = requests.get(url, stream=True)
        
        if response.status_code == 200:
            # Get content type from response
            content_type = response.headers.get('Content-Type', 'image/jpeg')
            
            # Read the image data
            image_data = response.raw.read()
            
            # Save to cache
            with open(cache_path, 'wb') as f:
                f.write(image_data)
            
            # Check cache size and clean if necessary (periodically)
            if random.randint(1, 100) <= 5:  # 5% chance to check cache size
                cleanup_cache()
            
            # Return the image data
            return Response(image_data, content_type=content_type)
        else:
            logger.error(f"Failed to fetch album art: HTTP {response.status_code}")
            return '', 404
            
    except Exception as e:
        logger.error(f"Error proxying album art: {e}")
        return '', 500

def cleanup_cache():
    """Cleanup the image cache if it exceeds the maximum size"""
    try:
        # Calculate current cache size
        total_size = 0
        files = []
        
        for file in os.listdir(CACHE_DIR):
            file_path = os.path.join(CACHE_DIR, file)
            if os.path.isfile(file_path):
                file_size = os.path.getsize(file_path)
                total_size += file_size
                files.append((file_path, os.path.getmtime(file_path), file_size))
        
        # Convert to MB
        total_size_mb = total_size / (1024 * 1024)
        
        if total_size_mb > MAX_CACHE_SIZE_MB:
            logger.info(f"Cache size ({total_size_mb:.2f}MB) exceeds limit ({MAX_CACHE_SIZE_MB}MB). Cleaning up...")
            
            # Sort by modification time (oldest first)
            files.sort(key=lambda x: x[1])
            
            # Remove files until we're under the limit
            space_to_free = total_size - (MAX_CACHE_SIZE_MB * 0.9 * 1024 * 1024)  # Free to 90% of limit
            space_freed = 0
            
            for file_path, _, file_size in files:
                if space_freed >= space_to_free:
                    break
                    
                try:
                    os.remove(file_path)
                    space_freed += file_size
                    logger.debug(f"Removed cached file: {file_path}")
                except Exception as e:
                    logger.error(f"Error removing cache file {file_path}: {e}")
            
            logger.info(f"Cache cleanup complete. Freed {space_freed / (1024 * 1024):.2f}MB")
    
    except Exception as e:
        logger.error(f"Error cleaning up cache: {e}")

@app.route('/cache/stats')
def cache_stats():
    """Get statistics about the album art cache"""
    try:
        # Calculate current cache size
        total_size = 0
        file_count = 0
        
        for file in os.listdir(CACHE_DIR):
            file_path = os.path.join(CACHE_DIR, file)
            if os.path.isfile(file_path):
                total_size += os.path.getsize(file_path)
                file_count += 1
        
        # Convert to MB
        total_size_mb = total_size / (1024 * 1024)
        
        return jsonify({
            'status': 'success',
            'cache_directory': CACHE_DIR,
            'file_count': file_count,
            'total_size_mb': round(total_size_mb, 2),
            'max_size_mb': MAX_CACHE_SIZE_MB,
            'usage_percent': round((total_size_mb / MAX_CACHE_SIZE_MB) * 100, 2) if MAX_CACHE_SIZE_MB > 0 else 0
        })
    
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/cache/clear', methods=['POST'])
def clear_cache():
    """Clear the album art cache"""
    try:
        file_count = 0
        for file in os.listdir(CACHE_DIR):
            file_path = os.path.join(CACHE_DIR, file)
            if os.path.isfile(file_path):
                os.remove(file_path)
                file_count += 1
        
        logger.info(f"Cache cleared. Removed {file_count} files.")
        return jsonify({
            'status': 'success',
            'message': f'Cache cleared. Removed {file_count} files.',
            'files_removed': file_count
        })
    
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        return jsonify({'error': str(e)}), 500

# Add these routes for playlist management

@app.route('/playlists', methods=['GET'])
def get_playlists():
    """Get all saved playlists"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get all playlists with track count
        cursor.execute('''
            SELECT p.id, p.name, p.description, p.created_at, p.updated_at,
                   COUNT(pi.id) as track_count
            FROM playlists p
            LEFT JOIN playlist_items pi ON p.id = pi.playlist_id
            GROUP BY p.id
            ORDER BY p.updated_at DESC
        ''')
        
        playlists = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify(playlists)
        
    except Exception as e:
        logger.error(f"Error getting playlists: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/playlists', methods=['POST'])
def save_playlist():  # RENAMED from create_playlist to save_playlist
    """Create a new playlist"""
    try:
        data = request.get_json()
        
        if not data or 'name' not in data:
            return jsonify({'error': 'Playlist name is required'}), 400
        
        name = data.get('name')
        description = data.get('description', '')
        tracks = data.get('tracks', [])
        
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Insert playlist
        cursor.execute(
            'INSERT INTO playlists (name, description) VALUES (?, ?)',
            (name, description)
        )
        playlist_id = cursor.lastrowid
        
        # Insert tracks
        for i, track_id in enumerate(tracks):
            cursor.execute(
                'INSERT INTO playlist_items (playlist_id, track_id, position) VALUES (?, ?, ?)',
                (playlist_id, track_id, i)
            )
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'id': playlist_id,
            'name': name,
            'description': description,
            'track_count': len(tracks)
        })
        
    except Exception as e:
        logger.error(f"Error creating playlist: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/playlists/<int:playlist_id>', methods=['GET'])
def get_playlist(playlist_id):
    """Get a specific playlist with its tracks"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get playlist metadata
        cursor.execute('SELECT * FROM playlists WHERE id = ?', (playlist_id,))
        playlist = dict(cursor.fetchone() or {})
        
        if not playlist:
            conn.close()
            return jsonify({'error': 'Playlist not found'}), 404
        
        # Get playlist tracks in order
        cursor.execute('''
            SELECT af.id, af.file_path, af.title, af.artist, af.album, af.album_art_url, af.duration
            FROM playlist_items pi
            JOIN audio_files af ON pi.track_id = af.id
            WHERE pi.playlist_id = ?
            ORDER BY pi.position
        ''', (playlist_id,))
        
        tracks = [dict(row) for row in cursor.fetchall()]
        playlist['tracks'] = tracks
        
        conn.close()
        return jsonify(playlist)
        
    except Exception as e:
        logger.error(f"Error getting playlist {playlist_id}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/playlists/<int:playlist_id>', methods=['PUT'])
def update_playlist(playlist_id):
    """Update an existing playlist"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Check if playlist exists
        cursor.execute('SELECT id FROM playlists WHERE id = ?', (playlist_id,))
        if not cursor.fetchone():
            conn.close()
            return jsonify({'error': 'Playlist not found'}), 404
        
        # Update metadata if provided
        if 'name' in data or 'description' in data:
            update_fields = []
            update_values = []
            
            if 'name' in data:
                update_fields.append('name = ?')
                update_values.append(data['name'])
            
            if 'description' in data:
                update_fields.append('description = ?')
                update_values.append(data['description'])
            
            update_fields.append('updated_at = CURRENT_TIMESTAMP')
            
            cursor.execute(
                f'UPDATE playlists SET {", ".join(update_fields)} WHERE id = ?',
                (*update_values, playlist_id)
            )
        
        # Update tracks if provided
        if 'tracks' in data:
            # Delete existing tracks
            cursor.execute('DELETE FROM playlist_items WHERE playlist_id = ?', (playlist_id,))
            
            # Insert new tracks
            for i, track_id in enumerate(data['tracks']):
                cursor.execute(
                    'INSERT INTO playlist_items (playlist_id, track_id, position) VALUES (?, ?, ?)',
                    (playlist_id, track_id, i)
                )
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"Error updating playlist {playlist_id}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/playlists/<int:playlist_id>', methods=['DELETE'])
def delete_playlist(playlist_id):
    """Delete a playlist"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Check if playlist exists
        cursor.execute('SELECT id FROM playlists WHERE id = ?', (playlist_id,))
        if not cursor.fetchone():
            conn.close()
            return jsonify({'error': 'Playlist not found'}), 404
        
        # Delete playlist (cascade will delete playlist items)
        cursor.execute('DELETE FROM playlists WHERE id = ?', (playlist_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"Error deleting playlist {playlist_id}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/recent')
def recent_tracks():
    """Get recently added tracks"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get most recently added tracks
        cursor.execute('''
            SELECT id, file_path, title, artist, album, album_art_url, duration
            FROM audio_files
            ORDER BY date_added DESC
            LIMIT 10
        ''')
        
        recent_tracks = [dict(row) for row in cursor.fetchall()]
        for track in recent_tracks:
            if not track['title']:
                track['title'] = os.path.basename(track['file_path'])
        
        conn.close()
        logger.info(f"Returning {len(recent_tracks)} recent tracks")
        return jsonify(recent_tracks)
        
    except Exception as e:
        logger.error(f"Error getting recent tracks: {e}")
        return jsonify({'error': str(e)}), 500

def run_server():
    """Run the Flask server"""
    logger.info(f"Starting server on {HOST}:{PORT} (debug={DEBUG})")
    try:
        # Use Werkzeug's run_simple for better error handling
        run_simple(
            hostname=HOST,
            port=PORT,
            application=app,
            use_reloader=DEBUG,
            use_debugger=DEBUG,
            threaded=True
        )
    except Exception as e:
        logger.error(f"Error running server: {e}")
        print(f"Error running server: {e}")

if __name__ == '__main__':
    run_server()