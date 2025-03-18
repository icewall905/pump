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
from lastfm_service import LastFMService
from spotify_service import SpotifyService  # Add this import at the top
from datetime import datetime
from flask import redirect, url_for
import time  # For sleep between API calls

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
app.config['DATABASE_PATH'] = DB_PATH  # Add this line to set the config
try:
    analyzer = MusicAnalyzer(DB_PATH)
    logger.info("MusicAnalyzer initialized successfully")
except Exception as e:
    logger.error(f"Error initializing MusicAnalyzer: {e}")
    analyzer = None

# Add these global variables near the top of the file

# Analysis status tracking
ANALYSIS_STATUS = {
    'running': False,
    'start_time': None,
    'files_processed': 0,
    'total_files': 0,
    'current_file': '',
    'percent_complete': 0,
    'last_updated': None,
    'error': None
}

@app.route('/')
def index():
    """Home page with search functionality"""
    view = request.args.get('view', '')
    return render_template('index.html', view=view)

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
    global ANALYSIS_STATUS
    
    # Don't start another analysis if one is already running
    if ANALYSIS_STATUS['running']:
        return jsonify({
            'error': 'Analysis already in progress',
            'status': ANALYSIS_STATUS
        }), 409
    
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
        
        # Reset analysis status
        ANALYSIS_STATUS.update({
            'running': True,
            'start_time': datetime.now().isoformat(),
            'files_processed': 0,
            'total_files': 0,
            'current_file': '',
            'percent_complete': 0,
            'last_updated': datetime.now().isoformat(),
            'error': None
        })
        
        # Start analysis in background thread
        import threading
        analysis_thread = threading.Thread(
            target=run_analysis,
            args=(folder_path, recursive)
        )
        analysis_thread.daemon = True
        analysis_thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Analysis started in background',
            'status': ANALYSIS_STATUS
        })
    
    except Exception as e:
        logger.error(f"Error analyzing folder: {e}")
        ANALYSIS_STATUS.update({
            'running': False,
            'error': str(e),
            'last_updated': datetime.now().isoformat()
        })
        return jsonify({'error': str(e)}), 500

# Add this function to run analysis in background
def run_analysis(folder_path, recursive):
    """Run the analysis in a background thread"""
    global ANALYSIS_STATUS
    
    try:
        # First count total files for progress tracking
        total_files = 0
        for root, _, files in os.walk(folder_path):
            if not recursive and root != folder_path:
                continue
                
            for file in files:
                if file.lower().endswith(('.mp3', '.flac', '.ogg', '.m4a', '.wav')):
                    total_files += 1
        
        ANALYSIS_STATUS['total_files'] = total_files
        
        # Now process the files and update status as we go
        result = {'files_processed': 0, 'tracks_added': 0}
        
        for root, _, files in os.walk(folder_path):
            if not recursive and root != folder_path:
                continue
                
            for file in files:
                if file.lower().endswith(('.mp3', '.flac', '.ogg', '.m4a', '.wav')):
                    file_path = os.path.join(root, file)
                    
                    # Update status
                    ANALYSIS_STATUS.update({
                        'current_file': file,
                        'files_processed': ANALYSIS_STATUS['files_processed'] + 1,
                        'percent_complete': int((ANALYSIS_STATUS['files_processed'] / total_files) * 100),
                        'last_updated': datetime.now().isoformat()
                    })
                    
                    # Process file
                    try:
                        was_added = analyzer.analyze_file(file_path)
                        result['files_processed'] += 1
                        if was_added:
                            result['tracks_added'] += 1
                    except Exception as e:
                        logger.error(f"Error analyzing file {file_path}: {e}")
        
        # Analysis complete
        ANALYSIS_STATUS.update({
            'running': False,
            'files_processed': result['files_processed'],
            'tracks_added': result.get('tracks_added', 0),
            'percent_complete': 100,
            'last_updated': datetime.now().isoformat()
        })
        
        logger.info(f"Background analysis complete: {result['files_processed']} files processed, {result.get('tracks_added', 0)} tracks added")
    
    except Exception as e:
        logger.error(f"Error in background analysis: {e}")
        ANALYSIS_STATUS.update({
            'running': False,
            'error': str(e),
            'last_updated': datetime.now().isoformat()
        })

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    """Settings page"""
    global config  # Access the module-level config variable
    
    if request.method == 'POST':
        # Handle form submission
        music_folder_path = request.form.get('music_folder_path', '')
        recursive = request.form.get('recursive') == 'on'
        lastfm_api_key = request.form.get('lastfm_api_key', '')
        lastfm_api_secret = request.form.get('lastfm_api_secret', '')
        spotify_client_id = request.form.get('spotify_client_id', '')
        spotify_client_secret = request.form.get('spotify_client_secret', '')
        
        # Get the default playlist size
        default_playlist_size = request.form.get('default_playlist_size', '10')
        
        # Update config
        if not config.has_section('music'):
            config.add_section('music')
        config.set('music', 'folder_path', music_folder_path)
        config.set('music', 'recursive', 'true' if recursive else 'false')
        
        if not config.has_section('lastfm'):
            config.add_section('lastfm')
        config.set('lastfm', 'api_key', lastfm_api_key)
        config.set('lastfm', 'api_secret', lastfm_api_secret)
        
        if not config.has_section('spotify'):
            config.add_section('spotify')
        config.set('spotify', 'client_id', spotify_client_id)
        config.set('spotify', 'client_secret', spotify_client_secret)
        
        # Add app section if doesn't exist
        if not config.has_section('app'):
            config.add_section('app')
        # Save the default playlist size
        config.set('app', 'default_playlist_size', default_playlist_size)
        
        # Save config
        with open(config_file, 'w') as f:
            config.write(f)
        
        logger.info("Settings updated successfully")
        return redirect(url_for('settings', message='Settings saved successfully'))
    
    # Get settings from config
    music_folder_path = config.get('music', 'folder_path', fallback='')
    recursive = config.getboolean('music', 'recursive', fallback=True)
    lastfm_api_key = config.get('lastfm', 'api_key', fallback='')
    lastfm_api_secret = config.get('lastfm', 'api_secret', fallback='')
    spotify_client_id = config.get('spotify', 'client_id', fallback='')
    spotify_client_secret = config.get('spotify', 'client_secret', fallback='')
    # Get the default playlist size
    default_playlist_size = config.get('app', 'default_playlist_size', fallback='10')
    
    return render_template(
        'settings.html',
        music_folder_path=music_folder_path,
        recursive=recursive,
        lastfm_api_key=lastfm_api_key,
        lastfm_api_secret=lastfm_api_secret,
        spotify_client_id=spotify_client_id,
        spotify_client_secret=spotify_client_secret,
        default_playlist_size=default_playlist_size,
        message=request.args.get('message'),
        error=request.args.get('error')
    )

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
        
        if (response.status_code == 200):
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

@app.route('/artistimg/<path:url>')
def artist_image_proxy(url):
    """Proxy for artist images with local caching"""
    try:
        # Decode URL
        url = unquote(url)
        
        # Generate a cache filename based on URL hash
        url_hash = hashlib.md5(url.encode()).hexdigest()
        cache_path = os.path.join(CACHE_DIR, f"artist_{url_hash}.jpg")
        
        # Check if the image is already in cache
        if os.path.exists(cache_path):
            return send_file(cache_path, mimetype='image/jpeg')
        
        # If not in cache, fetch from source
        logger.info(f"Fetching artist image from: {url}")
        
        # Fetch the image
        response = requests.get(url, stream=True)
        
        if (response.status_code == 200):
            # Get content type from response
            content_type = response.headers.get('Content-Type', 'image/jpeg')
            
            # Read the image data
            image_data = response.raw.read()
            
            # Save to cache
            with open(cache_path, 'wb') as f:
                f.write(image_data)
            
            # Return the image data
            return Response(image_data, content_type=content_type)
        else:
            logger.error(f"Failed to fetch artist image: HTTP {response.status_code}")
            return '', 404
            
    except Exception as e:
        logger.error(f"Error proxying artist image: {e}")
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

@app.route('/api/analysis/status')
def get_analysis_status():
    """Return the current status of music library analysis"""
    global ANALYSIS_STATUS
    return jsonify(ANALYSIS_STATUS)

@app.route('/track/<int:track_id>')
def get_track_info(track_id):
    """Get track information for playback"""
    # Use the connection from the active app context
    conn = sqlite3.connect(DB_PATH)  # Changed to use DB_PATH directly
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get track data from database
    cursor.execute(
        '''
        SELECT t.id, t.title, t.artist, t.album, t.file_path, t.album_art_url
        FROM audio_files t  /* Changed from "tracks" to "audio_files" */
        WHERE t.id = ?
        ''',
        (track_id,)
    )
    
    track = cursor.fetchone()
    if not track:
        conn.close()
        return jsonify({'error': 'Track not found'}), 404
        
    # Convert to dict for JSON response
    track_data = {
        'id': track['id'],
        'title': track['title'],
        'artist': track['artist'],
        'album': track['album'],
        'album_art_url': track['album_art_url']
    }
    
    conn.close()
    return jsonify(track_data)

@app.route('/stream/<int:track_id>')
def stream_track(track_id):
    """Stream audio file for a track"""
    # Use the connection from the active app context
    conn = sqlite3.connect(DB_PATH)  # Changed to use DB_PATH directly
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get track file path from database
    cursor.execute(
        'SELECT file_path FROM audio_files WHERE id = ?',  # Changed from "tracks" to "audio_files"
        (track_id,)
    )
    
    track = cursor.fetchone()
    if not track:
        conn.close()
        return jsonify({'error': 'Track not found'}), 404
    
    file_path = track['file_path']
    conn.close()
    
    if not os.path.exists(file_path):
        return jsonify({'error': 'Audio file not found'}), 404
        
    return send_file(file_path)

# Add these routes to your web_player.py file

@app.route('/library')
def library_page():
    """Render the library page"""
    return render_template('library.html')


@app.route('/api/library/album/<path:album>/tracks')
def get_album_tracks(album):
    """Get all tracks from a specific album"""
    try:
        artist = request.args.get('artist')
        
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if (artist):
            cursor.execute('''
                SELECT id, file_path, title, artist, album, album_art_url, duration
                FROM audio_files 
                WHERE album = ? AND artist = ?
                ORDER BY title COLLATE NOCASE
            ''', (album, artist))
        else:
            cursor.execute('''
                SELECT id, file_path, title, artist, album, album_art_url, duration
                FROM audio_files 
                WHERE album = ?
                ORDER BY title COLLATE NOCASE
            ''', (album,))
        
        tracks = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify(tracks)
    except Exception as e:
        logger.error(f"Error getting album tracks: {e}")
        return jsonify({"error": str(e)}), 500

# Add this route with your other route definitions

@app.route('/library')
def library():
    """Display the music library page"""
    return render_template('library.html')

# Add these API routes to fetch library data

@app.route('/api/library/artists')
def get_artists():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                artist, 
                COUNT(*) as track_count,
                artist_image_url,
                SUM(duration) as total_duration
            FROM audio_files
            WHERE artist IS NOT NULL AND artist != ''
            GROUP BY artist
            ORDER BY artist COLLATE NOCASE
        ''')
        
        artists = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        # Log the first few artists to see if they have images
        if artists and len(artists) > 0:
            logger.info(f"Sample artists: {artists[:2]}")
        
        return jsonify(artists)
    except Exception as e:
        logger.error(f"Error getting artists: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/library/albums')
def get_albums():
    """Get all albums in the library"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT DISTINCT album, artist, COUNT(*) as track_count,
                   (SELECT album_art_url FROM audio_files WHERE album=a.album AND artist=a.artist LIMIT 1) as album_art_url,
                   (SELECT file_path FROM audio_files WHERE album=a.album AND artist=a.artist LIMIT 1) as sample_track
            FROM audio_files a
            WHERE album IS NOT NULL AND album != ''
            GROUP BY album, artist
            ORDER BY album COLLATE NOCASE
        ''')
        
        albums = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify(albums)
    except Exception as e:
        logger.error(f"Error getting albums: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/library/songs')
def get_songs():
    """Get all songs in the library"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Increase limit to get more songs by default
        cursor.execute('''
            SELECT id, file_path, title, artist, album, album_art_url, duration
            FROM audio_files
            ORDER BY title COLLATE NOCASE
            LIMIT 50
        ''')
        
        # Make sure to convert the rows to dictionaries
        songs = [dict(row) for row in cursor.fetchall()]
        
        # Set default title for songs without title
        for song in songs:
            if not song['title']:
                song['title'] = os.path.basename(song['file_path'])
                
        conn.close()
        
        logger.info(f"Returning {len(songs)} songs for library view")
        return jsonify(songs)
    except Exception as e:
        logger.error(f"Error getting songs: {e}")
        return jsonify([]), 500  # Return empty array instead of error object

# Add this route to handle updating artist images

@app.route('/api/update-artist-images', methods=['POST'])
def update_artist_images():
    """Update artist images using LastFM"""
    try:
        # Get Last.fm API key from config
        api_key = config.get('lastfm', 'api_key', fallback=None)
        api_secret = config.get('lastfm', 'api_secret', fallback=None)
        
        # Use fallback keys if needed
        if not api_key:
            api_key = 'b21e44890bc788b52879506873d5ac33'
            api_secret = 'bc5e07063a9e09401386a78bfd1350f9'
            logger.info("Using fallback LastFM API key")
            
        lastfm = LastFMService(api_key, api_secret)
        
        # Get artists WITHOUT images only
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        default_image = "https://lastfm.freetls.fastly.net/i/u/300x300/2a96cbd8b46e442fc41c2b86b821562f.png"
        
        cursor.execute('''
            SELECT DISTINCT artist FROM audio_files 
            WHERE artist IS NOT NULL AND artist != '' 
            AND (artist_image_url IS NULL OR artist_image_url = '' OR artist_image_url = ?)
            ORDER BY artist
        ''', (default_image,))
        
        artists = [row['artist'] for row in cursor.fetchall()]
        conn.close()
        
        if not artists:
            return jsonify({'message': 'No artists without images found'}), 200
        
        # Dictionary to collect images before DB updates
        artist_images = {}
        
        # First fetch all images without touching DB
        total = len(artists)
        for artist in artists:
            try:
                logger.info(f"Fetching image for artist: {artist}")
                image_url = lastfm.get_artist_image_url(artist)
                if image_url:
                    logger.info(f"Found image for {artist}: {image_url}")
                    artist_images[artist] = image_url
                else:
                    logger.warning(f"No image found for {artist}")
            except Exception as e:
                logger.error(f"Error processing artist {artist}: {e}")

        # Now update the database in a single transaction
        updated_count = 0
        if artist_images:
            try:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                conn.execute('BEGIN')
                
                for artist, image_url in artist_images.items():
                    cursor.execute(
                        'UPDATE audio_files SET artist_image_url = ? WHERE artist = ?', 
                        (image_url, artist)
                    )
                    updated_count += 1
                
                conn.commit()
                conn.close()
                logger.info(f"Updated {updated_count} artist images in database")
            except Exception as e:
                logger.error(f"Database update error: {e}")
                if 'conn' in locals():
                    conn.rollback()
                    conn.close()

        return jsonify({
            'success': True, 
            'message': f'Updated images for {updated_count} of {total} artists',
            'updated': updated_count,
            'total': total
        })
        
    except Exception as e:
        logger.error(f"Error updating artist images: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/test-lastfm/<artist_name>')
def test_lastfm(artist_name):
    """Test lastfm API directly"""
    try:
        api_key = config.get('lastfm', 'api_key', fallback=None)
        api_secret = config.get('lastfm', 'api_secret', fallback=None)
        
        if not api_key:
            return jsonify({'error': 'LastFM API key not configured'}), 400
        
        # Make direct API request
        import requests
        base_url = "http://ws.audioscrobbler.com/2.0/"
        params = {
            'method': 'artist.getinfo',
            'artist': artist_name,
            'api_key': api_key,
            'format': 'json'
        }
        
        response = requests.get(base_url, params=params, timeout=10)
        data = response.json()
        
        # Check for errors
        if 'error' in data:
            return jsonify({
                'success': False,
                'error': data.get('message', 'Unknown LastFM error'),
                'code': data.get('error')
            }), 400
        
        # Extract image URLs
        artist_data = data.get('artist', {})
        images = artist_data.get('image', [])
        image_urls = {img.get('size'): img.get('#text') for img in images}
        
        return jsonify({
            'success': True,
            'artist': artist_name,
            'images': image_urls,
            'mbid': artist_data.get('mbid'),
            'url': artist_data.get('url')
        })
        
    except Exception as e:
        logger.error(f"Error testing LastFM API: {e}")
        return jsonify({'error': str(e)}), 500

# filepath: /home/hnyg/git/pump/pump/web_player.py
@app.route('/api/test-lastfm-key')
def test_lastfm_key():
    """Test if the LastFM API key is valid"""
    try:
        # Try both API keys
        main_key = config.get('lastfm', 'api_key', fallback=None)
        backup_key = config.get('api_keys', 'lastfm_api_key', fallback=None)
        
        results = {}
        
        # Test first key
        if main_key:
            import requests
            base_url = "http://ws.audioscrobbler.com/2.0/"
            params = {
                'method': 'auth.getSession',
                'api_key': main_key,
                'format': 'json'
            }
            
            response = requests.get(base_url, params=params, timeout=10)
            results['main_key'] = {
                'key': main_key[:5] + '...',
                'status_code': response.status_code,
                'response': response.text[:100]
            }
        
        # Test second key
        if backup_key:
            import requests
            base_url = "http://ws.audioscrobbler.com/2.0/"
            params = {
                'method': 'auth.getSession',
                'api_key': backup_key,
                'format': 'json'
            }
            
            response = requests.get(base_url, params=params, timeout=10)
            results['backup_key'] = {
                'key': backup_key[:5] + '...',
                'status_code': response.status_code,
                'response': response.text[:100]
            }
        
        return jsonify(results)
        
    except Exception as e:
        logger.error(f"Error testing LastFM API keys: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/update-artist-images/spotify', methods=['POST'])
def update_artist_images_spotify():
    """Update artist images using Spotify"""
    try:
        # Get Spotify API credentials
        client_id = config.get('spotify', 'client_id', fallback=None)
        client_secret = config.get('spotify', 'client_secret', fallback=None)
        
        # Use fallback keys if needed
        if not client_id or not client_secret:
            client_id = '5de01599b1ec493ea7fc3d0c4b1ec977'
            client_secret = 'be8bb04ebb9c447484f62320bfa9b4cc'
            logger.info("Using fallback Spotify API credentials")
            
        # Initialize Spotify service
        spotify = SpotifyService(client_id, client_secret)
        
        # Get artists WITHOUT images only
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        default_image = "https://lastfm.freetls.fastly.net/i/u/300x300/2a96cbd8b46e442fc41c2b86b821562f.png"
        
        cursor.execute('''
            SELECT DISTINCT artist FROM audio_files 
            WHERE artist IS NOT NULL AND artist != '' 
            AND (artist_image_url IS NULL OR artist_image_url = '' OR artist_image_url = ?)
            ORDER BY artist
        ''', (default_image,))
        
        artists = [row['artist'] for row in cursor.fetchall()]
        conn.close()
        
        if not artists:
            return jsonify({'message': 'No artists without images found'}), 200

        # Dictionary to collect images before DB updates
        artist_images = {}
        
        # First fetch all images without touching DB
        total = len(artists)
        for artist in artists:
            try:
                logger.info(f"Fetching Spotify image for artist: {artist}")
                image_url = spotify.get_artist_image_url(artist)
                if image_url:
                    logger.info(f"Found Spotify image for {artist}: {image_url}")
                    artist_images[artist] = image_url
                else:
                    logger.warning(f"No Spotify image found for {artist}")
            except Exception as e:
                logger.error(f"Error processing artist {artist} with Spotify: {e}")

        # Now update the database in a single transaction
        updated_count = 0
        if artist_images:
            try:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                conn.execute('BEGIN')
                
                for artist, image_url in artist_images.items():
                    cursor.execute(
                        'UPDATE audio_files SET artist_image_url = ? WHERE artist = ?', 
                        (image_url, artist)
                    )
                    updated_count += 1
                
                conn.commit()
                conn.close()
                logger.info(f"Updated {updated_count} artist images in database")
            except Exception as e:
                logger.error(f"Database update error: {e}")
                if 'conn' in locals():
                    conn.rollback()
                    conn.close()

        return jsonify({
            'success': True,
            'message': f'Updated images for {updated_count} of {total} artists using Spotify',
            'updated': updated_count,
            'total': total
        })
        
    except Exception as e:
        logger.error(f"Error updating artist images with Spotify: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/test-spotify/<artist_name>')
def test_spotify(artist_name):
    """Test Spotify API directly"""
    try:
        client_id = config.get('spotify', 'client_id', fallback=None)
        client_secret = config.get('spotify', 'client_secret', fallback=None)
        
        if not client_id or not client_secret:
            return jsonify({'error': 'Spotify API credentials not configured'}), 400
        
        # Initialize and test
        from spotify_service import SpotifyService
        spotify = SpotifyService(client_id, client_secret)
        
        # Get token
        token = spotify.get_token()
        if not token:
            return jsonify({'error': 'Failed to get Spotify access token'}), 500
            
        # Search for artist
        artist = spotify.search_artist(artist_name)
        
        if not artist:
            return jsonify({'error': 'Artist not found on Spotify'}), 404
            
        # Extract image URLs
        images = artist.get('images', [])
        image_urls = [{'url': img.get('url'), 'width': img.get('width'), 'height': img.get('height')} 
                      for img in images]
        
        return jsonify({
            'success': True,
            'artist_name': artist_name,
            'spotify_name': artist.get('name'),
            'popularity': artist.get('popularity'),
            'spotify_id': artist.get('id'),
            'image_count': len(image_urls),
            'images': image_urls,
            'external_url': artist.get('external_urls', {}).get('spotify')
        })
        
    except Exception as e:
        logger.error(f"Error testing Spotify API: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/station/<track_id>')
def create_station(track_id):
    """Create a playlist based on a seed track"""
    try:
        # Get the default playlist size from config
        playlist_size = int(config.get('app', 'default_playlist_size', fallback='10'))
        logger.info(f"Creating station with {playlist_size} tracks")
        
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get the seed track
        cursor.execute('SELECT * FROM audio_files WHERE id = ?', (track_id,))
        seed_track = cursor.fetchone()
        
        if not seed_track:
            return jsonify({'error': 'Seed track not found'})
        
        # Use the actual audio analyzer for similarity matching
        station_tracks = []
        if analyzer:
            # Get the seed track as the first item
            station_tracks.append(dict(seed_track))
            
            # Create a station based on audio similarity
            similar_file_paths = analyzer.create_station(seed_track['file_path'], playlist_size)
            
            # Get the full details of the similar tracks
            for file_path in similar_file_paths:
                cursor.execute('''
                    SELECT * FROM audio_files WHERE file_path = ?
                ''', (file_path,))
                track = cursor.fetchone()
                if track:
                    station_tracks.append(dict(track))
                    
            logger.info(f"Created station with {len(station_tracks)} tracks using audio similarity")
        else:
            # Fallback to random selection if analyzer not available
            logger.warning("Analyzer not available, using random selection")
            cursor.execute('''
                SELECT * FROM audio_files
                WHERE id != ?
                ORDER BY RANDOM()
                LIMIT ?
            ''', (track_id, playlist_size))
            
            similar_tracks = [dict(track) for track in cursor.fetchall()]
            station_tracks = [dict(seed_track)] + similar_tracks
            
        return jsonify(station_tracks)
        
    except Exception as e:
        logger.error(f"Error creating station: {e}")
        return jsonify({'error': str(e)})
    
    finally:
        if conn:
            conn.close()

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