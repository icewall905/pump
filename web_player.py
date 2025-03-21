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
import threading  # Add this import
from flask import jsonify, request  # Add this import
import re

# Import logging configuration
try:
    import logging_config
except ImportError:
    print("Warning: logging_config module not found. Using basic logging configuration.")
    # Set up basic logging if the module doesn't exist
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )

# Initialize logging with settings from config.ini if available
def init_logging(config):
    try:
        log_level = config.get('logging', 'level', fallback='info')
        log_to_file = config.getboolean('logging', 'log_to_file', fallback=True)
        log_dir = config.get('logging', 'log_dir', fallback='logs')
        max_size_mb = config.getint('logging', 'max_size_mb', fallback=10)
        backup_count = config.getint('logging', 'backup_count', fallback=5)
        
        # Use the imported module instead of relative import
        logging_config.configure_logging(
            level=log_level,
            log_to_file=log_to_file,
            log_dir=log_dir,
            max_size_mb=max_size_mb,
            backup_count=backup_count
        )
        
        return logging_config.get_logger('web_player')
    except (AttributeError, KeyError, ImportError) as e:
        print(f"Error setting up logging: {e}")
        logger = logging.getLogger('web_player')
        logger.setLevel(logging.INFO)
        return logger

# Initialize a placeholder logger that will be properly configured later
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
    },
    # Add logging configuration defaults
    'logging': {
        'level': 'info',
        'log_to_file': 'true',
        'log_dir': 'logs',
        'max_size_mb': '10',
        'backup_count': '5'
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

# Now properly initialize logging with the loaded config
logger = init_logging(config)

logger.info("Logging system initialized")

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
    logger.info("Music analyzer initialized successfully")
except Exception as e:
    analyzer = None
    logger.error(f"Error initializing music analyzer: {e}")

# Initialize metadata service
try:
    metadata_service = MetadataService(config_file=config_file)
    logger.info("Metadata service initialized successfully")
except Exception as e:
    logger.error(f"Error initializing metadata service: {e}")
    metadata_service = None

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

# Global variables to track analysis progress
analysis_thread = None
analysis_progress = {
    'is_running': False,
    'total_files': 0,
    'current_file_index': 0,
    'analyzed_count': 0,
    'failed_count': 0,
    'pending_count': 0,
    'last_run_completed': False
}

# Add this near the top where the other global variables are defined
METADATA_UPDATE_STATUS = {
    'running': False,
    'start_time': None,
    'total_tracks': 0,
    'processed_tracks': 0,
    'updated_tracks': 0,
    'current_track': '',
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
        
        # Get random tracks - changed from 10 to 6
        random_tracks = []
        if count > 0:
            sample_size = min(6, count)  # Changed from 10 to 6
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
def analyze_music():
    """Analyze music directory - Step 1: Quick scan, Step 2: Feature extraction"""
    global analyzer, ANALYSIS_STATUS
    
    if not analyzer:
        return jsonify({"success": False, "error": "Analyzer not initialized"})
    
    data = request.get_json()
    folder_path = data.get('folder_path', '')
    recursive = data.get('recursive', True)
    
    # Don't start another analysis if one is already running
    if ANALYSIS_STATUS['running']:
        return jsonify({
            'success': False,
            'message': 'Analysis is already running'
        })
    
    try:
        # Reset status
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
        analysis_thread = threading.Thread(
            target=run_analysis, 
            args=(folder_path, recursive)
        )
        analysis_thread.daemon = True
        analysis_thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Analysis started in background. This is a two-step process: 1) Quick scan to identify files, 2) Analysis of audio features',
            'status': ANALYSIS_STATUS
        })
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error starting analysis: {error_msg}")
        ANALYSIS_STATUS.update({
            'running': False,
            'error': error_msg,
            'last_updated': datetime.now().isoformat()
        })
        return jsonify({
            'success': False,
            'error': error_msg
        })

# Update the run_analysis function

def run_analysis(folder_path, recursive):
    """Run the analysis in a background thread"""
    global analyzer, ANALYSIS_STATUS
    
    try:
        logger.info(f"Starting audio analysis for {folder_path} (recursive={recursive})")
        
        # Initialize status with empty values
        ANALYSIS_STATUS.update({
            'running': True,
            'start_time': datetime.now().isoformat(),
            'files_processed': 0,
            'total_files': 0,
            'current_file': '',
            'percent_complete': 0,
            'last_updated': datetime.now().isoformat(),
            'error': None,
            'last_run_completed': False,
            'scan_complete': False  # Add a flag to track scan completion
        })
        
        # Step 1: Quick scan to identify files and add to database
        logger.info("Step 1/2: Quick scanning music files...")
        result = analyzer.scan_library(folder_path, recursive)
        
        # Connect to database to get accurate counts
        conn = sqlite3.connect(analyzer.db_path)
        cursor = conn.cursor()
        
        # Count total files in database
        cursor.execute("SELECT COUNT(*) FROM audio_files")
        total_in_db = cursor.fetchone()[0]
        
        # Count already analyzed files (status = 'analyzed')
        cursor.execute("SELECT COUNT(*) FROM audio_files WHERE analysis_status = 'analyzed'")
        already_analyzed = cursor.fetchone()[0]
        
        # Count pending files
        cursor.execute("SELECT COUNT(*) FROM audio_files WHERE analysis_status = 'pending'")
        pending_count = cursor.fetchone()[0]
        
        conn.close()
        
        logger.info(f"Database status: {total_in_db} total files, {already_analyzed} already analyzed, {pending_count} pending analysis")
        
        # Update status after scan - IMPORTANT: Set percent_complete to 0 for analysis phase
        ANALYSIS_STATUS.update({
            'files_processed': already_analyzed,  # Start count from already analyzed files
            'total_files': total_in_db,
            'current_file': "Starting analysis...",
            'percent_complete': 0,  # Start at 0% for analysis phase
            'last_updated': datetime.now().isoformat(),
            'scan_complete': True   # Mark scan as complete
        })
        
        # Define a progress callback function that properly tracks files
        def analysis_progress_callback(file_id, file_path, success):
            # Increment processed count
            processed_count = ANALYSIS_STATUS.get('files_processed', already_analyzed) + 1
            
            # Calculate progress percentage from 0-100% for analysis phase
            analysis_percent = (processed_count - already_analyzed) / pending_count * 100 if pending_count > 0 else 0
            
            ANALYSIS_STATUS.update({
                'files_processed': processed_count,
                'current_file': file_path,
                'percent_complete': analysis_percent,  # Use full 0-100% range for analysis
                'last_updated': datetime.now().isoformat()
            })
            
            logger.debug(f"Analysis progress: {processed_count}/{total_in_db} files ({analysis_percent:.1f}%)")
        
        # Step 2: Analyze audio features with progress callback
        logger.info(f"Step 2/2: Analyzing {pending_count} pending files...")
        feature_result = analyzer.analyze_pending_files(
            progress_callback=analysis_progress_callback
        )
        
        # Update final status
        ANALYSIS_STATUS.update({
            'running': False,
            'percent_complete': 100,
            'last_updated': datetime.now().isoformat(),
            'last_run_completed': True
        })
        
        # Combine results
        full_result = {
            'files_processed': total_in_db,
            'tracks_added': result.get('files_added', 0),
            'tracks_updated': result.get('files_updated', 0),
            'features_analyzed': feature_result.get('analyzed', 0),
            'errors': feature_result.get('errors', 0),
            'pending_features': feature_result.get('pending', 0)
        }
        
        logger.info(f"Background analysis complete: {full_result['files_processed']} files processed, {full_result['tracks_added']} tracks added, {full_result['features_analyzed']} features analyzed")
    
    except Exception as e:
        logger.error(f"Background analysis error: {e}")
        ANALYSIS_STATUS.update({
            'running': False,
            'error': str(e),
            'last_updated': datetime.now().isoformat()
        })

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        try:
            # Get form data
            music_folder_path = request.form.get('music_folder_path', '')
            recursive = request.form.get('recursive') == 'on'
            
            # Update Last.fm API keys
            lastfm_api_key = request.form.get('lastfm_api_key', '')
            lastfm_api_secret = request.form.get('lastfm_api_secret', '')
            
            # Update Spotify API keys
            spotify_client_id = request.form.get('spotify_client_id', '')
            spotify_client_secret = request.form.get('spotify_client_secret', '')
            
            # Get default playlist size
            default_playlist_size = request.form.get('default_playlist_size', '10')
            
            # Make sure sections exist
            if not config.has_section('music'):
                config.add_section('music')
            if not config.has_section('lastfm'):
                config.add_section('lastfm')
            if not config.has_section('spotify'):
                config.add_section('spotify')
            if not config.has_section('app'):
                config.add_section('app')
            
            # Update configuration
            config.set('music', 'folder_path', music_folder_path)
            config.set('music', 'recursive', 'true' if recursive else 'false')
            
            config.set('lastfm', 'api_key', lastfm_api_key)
            config.set('lastfm', 'api_secret', lastfm_api_secret)
            
            config.set('spotify', 'client_id', spotify_client_id)
            config.set('spotify', 'client_secret', spotify_client_secret)
            
            config.set('app', 'default_playlist_size', default_playlist_size)
            
            # Save changes
            with open(config_file, 'w') as f:
                config.write(f)
            
            logger.info("Settings saved successfully")
            return redirect(url_for('settings', message='Settings saved successfully'))
            
        except Exception as e:
            logger.error(f"Error updating settings: {e}")
            return redirect(url_for('settings', error=str(e)))
    
    # For GET request or after POST, render the template with current settings
    music_folder_path = config.get('music', 'folder_path', fallback='')
    recursive = config.getboolean('music', 'recursive', fallback=True)
    
    lastfm_api_key = config.get('lastfm', 'api_key', fallback='')
    lastfm_api_secret = config.get('lastfm', 'api_secret', fallback='')
    
    spotify_client_id = config.get('spotify', 'client_id', fallback='')
    spotify_client_secret = config.get('spotify', 'client_secret', fallback='')
    
    default_playlist_size = config.get('app', 'default_playlist_size', fallback='10')
    
    return render_template('settings.html',
        music_folder_path=music_folder_path,
        recursive=recursive,
        lastfm_api_key=lastfm_api_key,
        lastfm_api_secret=lastfm_api_secret,
        spotify_client_id=spotify_client_id,
        spotify_client_secret=spotify_client_secret,
        default_playlist_size=default_playlist_size,
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
    """Proxy for album art images - checks local cache first"""
    url = unquote(url)
    
    # If URL starts with /cache/, redirect to the cache route
    if url.startswith('/cache/'):
        return redirect(url)
    
    # Create a hash of the URL for caching
    url_hash = hashlib.md5(url.encode()).hexdigest()
    
    # Generate a cache filename based on URL hash
    cache_filename = f"album_{url_hash}.jpg"
    cache_path = os.path.join(CACHE_DIR, cache_filename)
    
    # Check if the image is already in cache
    if (os.path.exists(cache_path)):
        logger.debug(f"Serving cached album art for: {url}")
        return redirect(f"/cache/{cache_filename}")
    
    # If not in cache, fetch from source
    try:
        # Only download if it's a URL
        if url.startswith(('http://', 'https://')):
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                # Save to cache
                with open(cache_path, 'wb') as f:
                    f.write(response.content)
                
                logger.info(f"Downloaded and cached album art from {url}")
                return redirect(f"/cache/{cache_filename}")
            else:
                return send_file('static/images/default-album-art.png', mimetype='image/jpeg')
        else:
            # If it's not a URL and not in cache, return default image
            return send_file('static/images/default-album-art.png', mimetype='image/jpeg')
    except Exception as e:
        logger.error(f"Error proxying album art: {e}")
        return send_file('static/images/default-album-art.png', mimetype='image/jpeg')

# Update the artist_image_proxy function

@app.route('/artistimg/<path:url>')
def artist_image_proxy(url):
    """Proxy for artist images - checks local cache first"""
    url = unquote(url)
    
    # If URL starts with /cache/, redirect to the cache route
    if url.startswith('/cache/'):
        return redirect(url)
    
    # Create a hash of the URL for caching
    url_hash = hashlib.md5(url.encode()).hexdigest()
    
    # Generate a cache filename based on URL hash
    cache_filename = f"artist_{url_hash}.jpg"
    cache_path = os.path.join(CACHE_DIR, cache_filename)
    
    # Check if the image is already in cache
    if os.path.exists(cache_path):
        logger.debug(f"Serving cached artist image for: {url}")
        return redirect(f"/cache/{cache_filename}")
    
    # If not in cache, fetch from source
    try:
        # Only download if it's a URL
        if url.startswith(('http://', 'https://')):
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                # Save to cache
                with open(cache_path, 'wb') as f:
                    f.write(response.content)
                
                return redirect(f"/cache/{cache_filename}")
            else:
                return send_file('static/images/default-artist-image.png', mimetype='image/jpeg')
        else:
            # If it's not a URL and not in cache, return default image
            return send_file('static/images/default-artist-image.png', mimetype='image/jpeg')
    except Exception as e:
        logger.error(f"Error proxying artist image: {e}")
        return send_file('static/images/default-artist-image.png', mimetype='image/jpeg')

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
        
        # Get most recently added tracks - changed from 10 to 6
        cursor.execute('''
            SELECT id, file_path, title, artist, album, album_art_url, duration
            FROM audio_files
            ORDER BY date_added DESC
            LIMIT 6
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
def library():
    """Display the music library page"""
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
    global analyzer
    
    if not analyzer:
        return jsonify({"success": False, "error": "Analyzer not initialized"})
    
    try:
        # Configure LastFM API service
        lastfm_api_key = config.get('lastfm', 'api_key', fallback='')
        lastfm_api_secret = config.get('lastfm', 'api_secret', fallback='')
        lastfm = LastFMService(lastfm_api_key, lastfm_api_secret)
        
        if not lastfm_api_key or not lastfm_api_secret:
            return jsonify({"success": False, "error": "LastFM API keys not configured"})
            
        # Get artists without images
        conn = sqlite3.connect(analyzer.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT DISTINCT artist FROM audio_files 
            WHERE artist IS NOT NULL AND artist != '' 
            AND (artist_image_url IS NULL OR artist_image_url = '' OR artist_image_url = ?)
            LIMIT 100
        ''', ('',))
        
        artists = [row[0] for row in cursor.fetchall()]
        
        if not artists:
            return jsonify({"success": True, "message": "No artists without images found"})
            
        logger.info(f"Found {len(artists)} artists without images. Updating...")
        
        updated_count = 0
        
        # Update each artist
        for artist in artists:
            # Clean artist name
            artist = sanitize_artist_name(artist)
            
            if not artist:
                continue
                
            # Check if artist already has image
            if artist_has_image(artist):
                continue
                
            # Get image URL from LastFM
            image_url = lastfm.get_artist_image_url(artist, CACHE_DIR)  # Pass cache directory
            
            if image_url:
                logger.info(f"Got image for artist: {artist}")
                
                # Update database
                try:
                    cursor.execute(
                        'UPDATE audio_files SET artist_image_url = ? WHERE artist = ?', 
                        (image_url, artist)
                    )
                    conn.commit()
                    updated_count += 1
                except Exception as db_error:
                    logger.error(f"Database error updating artist image: {db_error}")
            
            # Add a small delay to avoid overwhelming the API
            time.sleep(0.5)
            
        conn.close()
        
        return jsonify({
            "success": True, 
            "message": f"Updated {updated_count} artist images via LastFM",
            "updated_count": updated_count,
            "total_artists": len(artists)
        })
        
    except Exception as e:
        logger.error(f"Error updating artist images: {e}")
        return jsonify({"success": False, "error": str(e)})

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
                    updated_count += cursor.rowcount
                
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
        
        # Check if analyzer is available
        if analyzer is None:
            logger.error("Analyzer not available - check logs for initialization errors")
            return jsonify({'error': 'Audio analyzer is not initialized. Check server logs for details.'})
        
        # Check if the track has been analyzed
        cursor.execute('''
            SELECT COUNT(*) as count FROM audio_features 
            WHERE file_id = ?
        ''', (seed_track['id'],))
        has_features = cursor.fetchone()['count'] > 0
        
        if not has_features:
            logger.warning(f"Track {seed_track['title']} has not been analyzed yet. Run analysis first.")
            return jsonify({
                'error': 'This track has not been analyzed yet. Please run analysis from Settings page first.'
            })
            
        # Get the seed track as the first item
        station_tracks.append(dict(seed_track))
        
        # Create a station based on audio similarity
        similar_file_paths = analyzer.create_station(seed_track['file_path'], playlist_size)
        
        # Get full details for similar tracks
        for file_path in similar_file_paths:
            if file_path == seed_track['file_path']:
                continue  # Skip seed track as it's already added
                
            cursor.execute('''
                SELECT * FROM audio_files WHERE file_path = ?
            ''', (file_path,))
            track = cursor.fetchone()
            if track:
                station_tracks.append(dict(track))
        
        logger.info(f"Created station with {len(station_tracks)} tracks using audio similarity")
        return jsonify(station_tracks)
        
    except Exception as e:
        logger.error(f"Error creating station: {e}")
        return jsonify({'error': str(e)})
    finally:
        if conn:
            conn.close()

# Add this with your other routes

@app.route('/api/settings/change_log_level', methods=['POST'])
def change_log_level():
    try:
        data = request.get_json()
        level = data.get('level')
        
        if not level:
            return jsonify({"error": "No log level provided"}), 400
        
        # Update config file
        if not config.has_section('logging'):
            config.add_section('logging')
        config.set('logging', 'level', level.lower())
        
        # Save to config file
        with open(config_file, 'w') as f:
            config.write(f)
        
        # Change log level at runtime
        logging_config.set_log_level(level.lower())
        logger.info(f"Log level changed to {level}")
        return jsonify({"message": f"Log level changed to {level}"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error changing log level: {e}")
        return jsonify({"error": "Failed to change log level"}), 500

@app.route('/api/settings/get_log_level', methods=['GET'])
def get_log_level():
    """Get current log level"""
    try:
        level = config.get('logging', 'level', fallback='info')
        return jsonify({"level": level})
    except Exception as e:
        logger.error(f"Error getting log level: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/logs/view', methods=['GET'])
def view_logs():
    try:
        lines = request.args.get('lines', default=100, type=int)
        log_dir = config.get('logging', 'log_dir', fallback='logs')
        log_file = os.path.join(log_dir, 'pump.log')
        
        if not os.path.exists(log_file):
            return jsonify({"error": "Log file not found"}), 404
        
        with open(log_file, 'r') as f:
            # Get the last 'lines' lines
            log_lines = f.readlines()[-lines:]
        
        return jsonify({"logs": log_lines})
    except Exception as e:
        logger.error(f"Error viewing logs: {e}")
        return jsonify({"error": "Failed to view logs"}), 500

# Add this with your other routes

@app.route('/logs')
def logs_page():
    return render_template('logs.html', active_page='logs')

@app.route('/api/logs/download')
def download_logs():
    try:
        log_dir = config.get('logging', 'log_dir', fallback='logs')
        log_file = os.path.join(log_dir, 'pump.log')
        
        if not os.path.exists(log_file):
            return jsonify({"error": "Log file not found"}), 404
        
        return send_file(log_file, 
                         mimetype='text/plain', 
                         as_attachment=True, 
                         download_name=f'pump_logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    except Exception as e:
        logger.error(f"Error downloading logs: {e}")
        return jsonify({"error": "Failed to download logs"}), 500

@app.route('/scan_library', methods=['POST'])
def scan_library():
    global analyzer
    
    data = request.get_json()
    directory = data.get('directory')
    recursive = data.get('recursive', True)
    
    if not directory:
        return jsonify({'success': False, 'message': 'No directory specified'})
    
    try:
        result = analyzer.scan_library(directory, recursive=recursive)
        return jsonify({'success': True, **result})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/start_background_analysis', methods=['POST'])
def start_background_analysis():
    global analyzer, analysis_thread, analysis_progress
    
    # If analysis is already running, don't start a new one
    if analysis_progress['is_running']:
        return jsonify({'status': 'already_running'})
    
    data = request.get_json()
    limit = data.get('limit')
    batch_size = data.get('batch_size', 10)
    
    # Get initial counts
    conn = sqlite3.connect(analyzer.db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM audio_files WHERE analysis_status = 'pending'")
    pending_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM audio_files WHERE analysis_status = 'analyzed'")
    analyzed_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM audio_files WHERE analysis_status = 'failed'")
    failed_count = cursor.fetchone()[0]
    conn.close()
    
    # Update progress tracking instead of redefining
    analysis_progress.update({
        'is_running': True,
        'total_files': min(pending_count, limit) if limit else pending_count,
        'current_file_index': 0,
        'analyzed_count': analyzed_count,
        'failed_count': failed_count,
        'pending_count': pending_count,
        'last_run_completed': False,
        'stop_requested': False  # Reset stop flag
    })
    
    # Start analysis in a background thread
    def background_task():
        global analysis_progress
        
        print(f"Starting background analysis of {analysis_progress['total_files']} files")
        
        # Define a callback to update progress
        def update_progress(index, status):
            if status == 'analyzed':
                analysis_progress['analyzed_count'] += 1
            elif status == 'failed':
                analysis_progress['failed_count'] += 1
            analysis_progress['current_file_index'] = index
        
        try:
            # Run the analyzer
            result = analyzer.analyze_pending_files(
                limit=limit,
                batch_size=batch_size,
                progress_callback=update_progress
            )
            
            # Update the progress with the final results
            analysis_progress.update({
                'is_running': False,
                'last_run_completed': True,
                'pending_count': result.get('remaining', 0)
            })
            
            print(f"Background analysis complete: {result}")
            
        except Exception as e:
            print(f"Error in background analysis: {e}")
            analysis_progress.update({
                'is_running': False,
                'error': str(e)
            })
    
    analysis_thread = threading.Thread(target=background_task)
    analysis_thread.daemon = True
    analysis_thread.start()
    
    return jsonify({'status': 'started'})

@app.route('/stop_background_analysis', methods=['POST'])
def stop_background_analysis():
    global analysis_progress
    
    # Set flag to stop the analysis in the next iteration
    analysis_progress['stop_requested'] = True
    
    return jsonify({'status': 'stopped'})

@app.route('/analysis_progress')
def get_analysis_progress():
    global analysis_progress
    
    # Calculate progress percentage
    progress = 0
    if analysis_progress['total_files'] > 0:
        progress = analysis_progress['current_file_index'] / analysis_progress['total_files']
    
    return jsonify({
        **analysis_progress,
        'progress': progress
    })

@app.route('/analysis_status')
def get_analysis_count_status():  # Changed function name
    global analyzer
    
    conn = sqlite3.connect(analyzer.db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM audio_files WHERE analysis_status = 'pending'")
    pending = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM audio_files WHERE analysis_status = 'analyzed'")
    analyzed = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM audio_files WHERE analysis_status = 'failed'")
    failed = cursor.fetchone()[0]
    conn.close()
    
    return jsonify({
        'pending': pending,
        'analyzed': analyzed,
        'failed': failed
    })

def should_stop():
    global analysis_progress
    return analysis_progress.get('stop_requested', False)

@app.route('/api/settings/save_music_path', methods=['POST'])
def save_music_path():
    """Save music folder path to config file"""
    try:
        data = request.get_json()
        
        if not data or 'path' not in data:
            return jsonify({"success": False, "message": "No path provided"}), 400
        
        music_path = data['path']
        recursive = data.get('recursive', True)
        
        # Make sure music section exists
        if not config.has_section('music'):
            config.add_section('music')
            
        # Update configuration
        config.set('music', 'folder_path', music_path)
        config.set('music', 'recursive', str(recursive).lower())
        
        # Write to config file
        with open(config_file, 'w') as f:
            config.write(f)
        
        logger.info(f"Saved music folder path: {music_path} (recursive={recursive})")
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error saving music path: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/update-metadata', methods=['POST'])
def update_metadata():
    """Start background metadata update process"""
    try:
        # Get skip_existing parameter, default to False if not provided
        data = request.get_json() or {}
        skip_existing = data.get('skip_existing', False)
        
        # Update global tracking variable
        global METADATA_UPDATE_STATUS
        
        # Don't start if already running
        if METADATA_UPDATE_STATUS['running']:
            return jsonify({
                'success': False,
                'message': 'Metadata update already in progress'
            })
        
        # Reset status
        METADATA_UPDATE_STATUS.update({
            'running': True,
            'start_time': datetime.now(),
            'total_tracks': 0,
            'processed_tracks': 0,
            'updated_tracks': 0,
            'current_track': '',
            'percent_complete': 0,
            'last_updated': datetime.now(),
            'error': None
        })
        
        # Start in background thread
        thread = threading.Thread(
            target=metadata_service.update_all_metadata,
            kwargs={
                'status_tracker': METADATA_UPDATE_STATUS,
                'skip_existing': skip_existing  # Pass the parameter
            }
        )
        thread.daemon = True
        thread.start()
        
        logger.info(f"Started metadata update (skip_existing={skip_existing})")
        
        return jsonify({
            'success': True
        })
    except Exception as e:
        logger.error(f"Error starting metadata update: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        })

# Add this function to run metadata update in background
def run_metadata_update():
    """Run the metadata update in a background thread"""
    global analyzer, METADATA_UPDATE_STATUS
    
    try:
        conn = sqlite3.connect(analyzer.db_path)
        cursor = conn.cursor()
        
        # Get all tracks
        cursor.execute("SELECT id, artist, title, file_path FROM audio_files")
        tracks = cursor.fetchall()
        conn.close()
        
        # Smaller batch size for more responsive UI updates
        batch_size = 3  # Process 3 tracks at a time
        updated_count = 0
        images_updated = 0
        track_count = len(tracks)
        
        # Initialize the metadata service if not already done
        metadata_service = analyzer.metadata_service
        
        METADATA_UPDATE_STATUS['total_tracks'] = track_count
        
        # Process tracks in small chunks to allow UI to be responsive
        for i in range(0, track_count, batch_size):
            # Get the next batch of tracks
            batch = tracks[i:i+batch_size]
            
            # Update status
            METADATA_UPDATE_STATUS.update({
                'processed_tracks': i,
                'percent_complete': int((i / track_count) * 100) if track_count > 0 else 0,
                'last_updated': datetime.now().isoformat()
            })
            
            # Process each track in the batch
            for track_id, artist, title, file_path in batch:
                track_name = f"{artist} - {title}" if artist and title else file_path
                METADATA_UPDATE_STATUS['current_track'] = track_name
                
                try:
                    # Get existing metadata
                    basic_metadata = {
                        'title': title,
                        'artist': artist,
                        'file_path': file_path
                    }
                    
                    # Try to enhance with online services - pass the CACHE_DIR
                    enhanced_metadata = metadata_service.enrich_metadata(basic_metadata, CACHE_DIR)
                    
                    # Check if we got improved metadata - inspect what we actually got
                    was_enhanced = enhanced_metadata.get('metadata_source') in ['last.fm', 'musicbrainz']
                    if was_enhanced:
                        logger.info(f"Found enhanced metadata for '{artist} - {title}' from {enhanced_metadata.get('metadata_source')}")
                        
                        # Update database with enhanced metadata
                        conn = sqlite3.connect(analyzer.db_path)
                        cursor = conn.cursor()
                        
                        try:
                            # Update track metadata
                            cursor.execute('''
                                UPDATE audio_files SET 
                                title = ?, 
                                artist = ?, 
                                album = ?, 
                                album_art_url = ?,
                                metadata_source = ?
                                WHERE id = ?
                            ''', (
                                enhanced_metadata.get('title', title),
                                enhanced_metadata.get('artist', artist),
                                enhanced_metadata.get('album', ''),
                                enhanced_metadata.get('album_art_url', ''),
                                enhanced_metadata.get('metadata_source', 'unknown'),
                                track_id
                            ))
                            
                            # Check if any rows were actually updated
                            if cursor.rowcount > 0:
                                updated_count += 1
                                logger.info(f"Successfully updated database for '{artist} - {title}'")
                                
                                # Check if we got album art
                                if enhanced_metadata.get('album_art_url'):
                                    images_updated += 1
                                    logger.info(f"Added album art for '{artist} - {title}'")
                            else:
                                logger.warning(f"No rows updated for '{artist} - {title}' despite finding metadata")
                                
                            conn.commit()
                        except Exception as db_error:
                            logger.error(f"Database error updating '{artist} - {title}': {db_error}")
                            conn.rollback()
                        finally:
                            conn.close()
                    else:
                        logger.info(f"No enhanced metadata found for '{artist} - {title}'")
                except Exception as e:
                    logger.error(f"Error updating metadata for {track_name}: {e}")
        
        # Update status when complete
        METADATA_UPDATE_STATUS.update({
            'running': False,
            'percent_complete': 100,
            'processed_tracks': track_count,
            'updated_tracks': updated_count,
            'last_updated': datetime.now().isoformat()
        })
        
        logger.info(f"Background metadata update complete: {updated_count} tracks updated, {images_updated} images updated")
    
    except Exception as e:
        logger.error(f"Background metadata update error: {e}")
        METADATA_UPDATE_STATUS.update({
            'running': False,
            'error': str(e),
            'last_updated': datetime.now().isoformat()
        })

# Add this helper function to check if an artist already has an image
def artist_has_image(artist_name):
    """Check if artist already has an image in the database"""
    if not artist_name:
        return False
        
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT artist_image_url FROM audio_files WHERE artist = ? AND artist_image_url IS NOT NULL AND artist_image_url != '' LIMIT 1", 
            (artist_name,)
        )
        result = cursor.fetchone()
        conn.close()
        return result is not None and result[0]
    except Exception as e:
        logger.error(f"Error checking artist image: {e}")
        return False

# Add this helper function to sanitize artist names
def sanitize_artist_name(artist_name):
    """Clean artist names that might contain multiple artists"""
    if not artist_name:
        return ""
        
    # Split on common separators that might indicate multiple artists
    separators = ["feat.", "ft.", "featuring", "with", "vs", "x", "&"]
    
    for sep in separators:
        if (sep in artist_name.lower()):
            # Take only the main artist (before the separator)
            return artist_name.split(sep, 1)[0].strip()
    
    # Check for patterns like "ArtistA ArtistB" (where names are concatenated)
    # This is harder to detect reliably, but we can check for common cases
    if len(artist_name) > 20 and not " and " in artist_name.lower() and not " & " in artist_name.lower():
        # Look for potential CamelCase splitting points
        camel_case_match = re.search(r'([a-z])([A-Z])', artist_name)
        if camel_case_match:
            split_point = camel_case_match.start() + 1
            return artist_name[:split_point]
    
    return artist_name

@app.route('/api/metadata-update/status')
def get_metadata_update_status():
    """Get the current status of the metadata update"""
    global METADATA_UPDATE_STATUS
    return jsonify(METADATA_UPDATE_STATUS)

@app.route('/api/analysis/status')
def get_analysis_status():
    """Return the current analysis status"""
    global ANALYSIS_STATUS
    return jsonify(ANALYSIS_STATUS)

@app.route('/api/test-credentials', methods=['GET'])
def test_credentials():
    results = {}
    
    # Test Last.fm
    lastfm_key = config.get('lastfm', 'api_key', fallback='')
    lastfm_secret = config.get('lastfm', 'api_secret', fallback='')
    
    results['lastfm'] = {
        'has_key': bool(lastfm_key),
        'has_secret': bool(lastfm_secret)
    }
    
    if lastfm_key:
        try:
            test_url = f"http://ws.audioscrobbler.com/2.0/?method=artist.getinfo&artist=Metallica&api_key={lastfm_key}&format=json"
            response = requests.get(test_url, timeout=10)
            results['lastfm']['connection'] = response.status_code == 200
            results['lastfm']['status'] = response.status_code
        except Exception as e:
            results['lastfm']['connection'] = False
            results['lastfm']['error'] = str(e)
    
    # Similar test for Spotify
    spotify_id = config.get('spotify', 'client_id', fallback='')
    spotify_secret = config.get('spotify', 'client_secret', fallback='')
    
    results['spotify'] = {
        'has_key': bool(spotify_id),
        'has_secret': bool(spotify_secret)
    }
    
    return jsonify(results)

@app.route('/cache/<path:filename>')
def serve_cache_file(filename):
    """Serve a file directly from the cache directory"""
    try:
        # Ensure no path traversal vulnerability
        if ".." in filename:
            return "Invalid path", 400
            
        # Full path to the cached file
        cache_path = os.path.join(CACHE_DIR, filename)
        
        if os.path.exists(cache_path) and os.path.isfile(cache_path):
            logger.debug(f"Serving cached file: {filename}")
            return send_file(cache_path, mimetype='image/jpeg')
        else:
            logger.warning(f"Cache file not found: {filename}")
            return send_file('static/images/default-album-art.png', mimetype='image/jpeg')
    except Exception as e:
        logger.error(f"Error serving cache file {filename}: {e}")
        return send_file('static/images/default-album-art.png', mimetype='image/jpeg')

@app.route('/api/library/stats')
def get_library_stats():
    """Get statistics about the music library"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Get total tracks count
        cursor.execute("SELECT COUNT(*) FROM audio_files")
        total_tracks = cursor.fetchone()[0]
        
        # Get tracks with metadata count
        cursor.execute("SELECT COUNT(*) FROM audio_files WHERE metadata_source IS NOT NULL")
        tracks_with_metadata = cursor.fetchone()[0]
        
        # Get analyzed tracks count 
        cursor.execute("SELECT COUNT(*) FROM audio_files WHERE analysis_status = 'analyzed'")
        analyzed_tracks = cursor.fetchone()[0]
        
        # Calculate DB size
        db_size_bytes = os.path.getsize(DB_PATH)
        db_size_mb = round(db_size_bytes / (1024 * 1024), 2)  # Convert to MB
        
        # Calculate cache size
        cache_dir = config.get('cache', 'image_cache_dir', fallback='album_art_cache')
        cache_size_bytes = 0
        if os.path.exists(cache_dir):
            for file in os.listdir(cache_dir):
                file_path = os.path.join(cache_dir, file)
                if os.path.isfile(file_path):
                    cache_size_bytes += os.path.getsize(file_path)
        cache_size_mb = round(cache_size_bytes / (1024 * 1024), 2)  # Convert to MB
        
        conn.close()
        
        return jsonify({
            'status': 'success',
            'stats': {
                'total_tracks': total_tracks,
                'tracks_with_metadata': tracks_with_metadata,
                'analyzed_tracks': analyzed_tracks,
                'db_size_mb': db_size_mb,
                'cache_size_mb': cache_size_mb
            }
        })
    except Exception as e:
        logger.error(f"Error getting library stats: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        })

def run_server():
    """Run the Flask server"""
    logger.info(f"Starting server on {HOST}:{PORT} (debug={DEBUG})")
    try:
        # Use Werkzeug's run_simple for better error handling
        run_simple(hostname=HOST, port=PORT, application=app, use_reloader=DEBUG, use_debugger=DEBUG)
    except Exception as e:
        logger.error(f"Error running server: {e}")
        print(f"Error running server: {e}")

if __name__ == '__main__':
    run_server()