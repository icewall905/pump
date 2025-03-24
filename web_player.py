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
from datetime import datetime, timedelta
from flask import redirect, url_for
import time  # For sleep between API calls
import threading  # Add this import
from flask import jsonify, request, g  # Add this import
import re
from db_utils import get_optimized_connection, optimized_connection
from db_operations import execute_query_dict, execute_query_row, execute_write, execute_batch

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

# Add scheduler configuration section if needed
if not config.has_section('scheduler'):
    config.add_section('scheduler')
    config.set('scheduler', 'startup_action', 'nothing')
    config.set('scheduler', 'schedule_frequency', 'never')
    config.set('scheduler', 'last_run', '')
    config_updated = True

# Add database performance configuration section if needed
if not config.has_section('database_performance'):
    config.add_section('database_performance')
    config.set('database_performance', 'in_memory', 'false')  # Keep in memory?
    config.set('database_performance', 'cache_size_mb', '75')  # Cache size in MB
    config.set('database_performance', 'optimize_connections', 'true')  # Apply optimizations?
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


# Quick Scan status tracking
QUICK_SCAN_STATUS = {
    'running': False,
    'start_time': None,
    'files_processed': 0,
    'tracks_added': 0,
    'total_files': 0,
    'current_file': '',
    'percent_complete': 0,
    'last_updated': None,
    'error': None
}


# Scheduler variables
SCHEDULER_TIMER = None
SCHEDULER_RUNNING = False

# Create cache directory if it doesn't exist
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)
    logger.info(f"Created album art cache directory: {CACHE_DIR}")

# Get database performance settings
DB_IN_MEMORY = config.getboolean('database_performance', 'in_memory', fallback=False)
DB_CACHE_SIZE_MB = config.getint('database_performance', 'cache_size_mb', fallback=75)
DB_OPTIMIZE = config.getboolean('database_performance', 'optimize_connections', fallback=True)

# Add this code after your DB performance settings, around line 175-200

# Create a global connection for in-memory mode
if DB_IN_MEMORY:
    try:
        # Instead of creating a global connection object directly,
        # we'll use a thread-specific connection store
        from db_utils import get_optimized_connection, save_memory_db_to_disk
        import atexit
        
        # Create connection in main thread
        main_thread_conn = get_optimized_connection(
            DB_PATH, in_memory=True, cache_size_mb=DB_CACHE_SIZE_MB, check_same_thread=False)
        
        # Register function to save at exit
        def save_db_at_exit():
            logger.info("Application shutting down. Saving in-memory database to disk...")
            save_memory_db_to_disk(main_thread_conn, DB_PATH)
        
        atexit.register(save_db_at_exit)
        
        # Use a different approach for request teardown - use a hook function
        # that saves after each request completes (only if changes were made)
        from flask import g
        
        @app.before_request
        def setup_db_connection():
            g.db_modified = False
        
        @app.teardown_request
        def save_if_modified(exception):
            """Save in-memory database to disk if modified during request"""
            if hasattr(g, 'db_modified') and g.db_modified and DB_IN_MEMORY and main_thread_conn:
                try:
                    logger.info("Saving in-memory database to disk after request...")
                    from db_utils import save_memory_db_to_disk
                    save_memory_db_to_disk(main_thread_conn, DB_PATH)
                except Exception as e:
                    logger.error(f"Error saving in-memory database to disk: {e}")
        
        logger.info("In-memory database mode initialized")
    except Exception as e:
        logger.error(f"Failed to initialize in-memory database: {e}")
        DB_IN_MEMORY = False
else:
    main_thread_conn = None

import signal
import atexit
import sys

# Variable to track if we're already shutting down
_is_shutting_down = False
main_thread_conn = None

def save_db_before_exit(signum=None, frame=None):
    """Save in-memory database to disk before application exits"""
    global _is_shutting_down, main_thread_conn
    
    # Prevent multiple shutdown handlers from running
    if _is_shutting_down:
        return
    
    _is_shutting_down = True
    
    if DB_IN_MEMORY and main_thread_conn:
        try:
            logger.info("Saving in-memory database to disk before exit...")
            from db_utils import trigger_db_save
            trigger_db_save(main_thread_conn, DB_PATH)
            logger.info("Database saved successfully before exit")
        except Exception as e:
            logger.error(f"Error saving database before exit: {e}")
    
    # Force exit after short delay if we get stuck
    if signum in (signal.SIGINT, signal.SIGTERM):
        def force_exit():
            sys.exit(0)
        
        # Schedule force exit in 2 seconds if still running
        import threading
        threading.Timer(2.0, force_exit).start()

# Register exit handlers
atexit.register(save_db_before_exit)
signal.signal(signal.SIGTERM, save_db_before_exit)
signal.signal(signal.SIGINT, save_db_before_exit)

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
        # Use execute_query_dict instead of direct connection handling
        tracks = execute_query_dict(
            DB_PATH,
            '''SELECT id, file_path, title, artist, album, album_art_url, duration
               FROM audio_files 
               WHERE title LIKE ? OR artist LIKE ? OR album LIKE ? 
               ORDER BY artist, album, title
               LIMIT ?''',
            (f'%{query}%', f'%{query}%', f'%{query}%', MAX_SEARCH_RESULTS),
            in_memory=DB_IN_MEMORY,
            cache_size_mb=DB_CACHE_SIZE_MB
        )
        
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
        
        # Get the seed track's file path
        seed_track = execute_query_row(
            DB_PATH,
            'SELECT file_path FROM audio_files WHERE id = ?', 
            (seed_track_id,),
            in_memory=DB_IN_MEMORY,
            cache_size_mb=DB_CACHE_SIZE_MB
        )
        
        if not seed_track:
            return jsonify({'error': 'Seed track not found'}), 404
        
        # Generate the playlist
        if analyzer:
            similar_tracks = analyzer.create_station(seed_track['file_path'], playlist_size)
            
            # Get the full details of the tracks
            playlist = []
            for track_path in similar_tracks:
                track = execute_query_row(
                    DB_PATH,
                    '''SELECT id, file_path, title, artist, album, album_art_url, duration 
                       FROM audio_files 
                       WHERE file_path = ?''',
                    (track_path,),
                    in_memory=DB_IN_MEMORY,
                    cache_size_mb=DB_CACHE_SIZE_MB
                )
                if track:
                    playlist.append(track)
            
            logger.info(f"Generated playlist with {len(playlist)} tracks")
            return jsonify(playlist)
        else:
            return jsonify({'error': 'Analyzer not available'}), 500
            
    except Exception as e:
        logger.error(f"Error creating playlist: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/explore')
def explore():
    """Get random tracks for exploration"""
    try:
        # Get count of total tracks
        count_result = execute_query_row(
            DB_PATH,
            'SELECT COUNT(*) as count FROM audio_files',
            in_memory=DB_IN_MEMORY,
            cache_size_mb=DB_CACHE_SIZE_MB
        )
        count = count_result['count'] if count_result else 0
        
        # Get random tracks - changed from 10 to 6
        random_tracks = []
        if count > 0:
            sample_size = min(6, count)  # Changed from 10 to 6
            random_tracks = execute_query_dict(
                DB_PATH,
                f'''SELECT af.id, af.file_path, af.title, af.artist, af.album, af.album_art_url, af.duration
                   FROM audio_files af
                   ORDER BY RANDOM()
                   LIMIT {sample_size}''',
                in_memory=DB_IN_MEMORY,
                cache_size_mb=DB_CACHE_SIZE_MB
            )
            
            # Set default titles for tracks without titles
            for track in random_tracks:
                if not track['title']:
                    track['title'] = os.path.basename(track['file_path'])
        
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

        # Indicate the database will be modified (actual modification happens in the thread)
        g.db_modified = True

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


def _fix_database_inconsistencies(self):
    """Fix any inconsistencies between audio_files and audio_features tables"""
    try:
        with transaction_context(self.db_path, self.in_memory, self.cache_size_mb) as (conn, cursor):
            # Get count before fix
            cursor.execute("SELECT COUNT(*) FROM audio_files WHERE analysis_status = 'pending'")
            before_count = cursor.fetchone()[0]
            
            # Check for inconsistencies - files marked as analyzed but missing features
            cursor.execute('''
                UPDATE audio_files 
                SET analysis_status = 'pending'
                WHERE analysis_status = 'analyzed' 
                AND id NOT IN (SELECT file_id FROM audio_features)
            ''')
            
            # Check for inconsistencies - files with features but not marked as analyzed
            cursor.execute('''
                UPDATE audio_files 
                SET analysis_status = 'analyzed'
                WHERE analysis_status = 'pending' 
                AND id IN (SELECT file_id FROM audio_features WHERE 
                           tempo > 0 OR energy > 0 OR danceability > 0)
            ''')
            
            # Get count after fix
            cursor.execute("SELECT COUNT(*) FROM audio_files WHERE analysis_status = 'pending'")
            after_count = cursor.fetchone()[0]
            
            logger.info(f"Database consistency check: {before_count} pending files before, {after_count} after fix")
            
            # Save changes immediately if in-memory
            if self.in_memory:
                from db_utils import trigger_db_save
                trigger_db_save(conn, self.db_path)
    except Exception as e:
        logger.error(f"Error fixing database inconsistencies: {e}")

# Update the run_analysis function

def run_analysis(folder_path, recursive):
    """Run full analysis in a background thread"""
    global analysis_thread
    
    try:
        # Make sure analyzer exists
        if not analyzer:
            logger.error("Cannot run analysis: Music analyzer not available")
            return

        # CRITICAL FIX: Check and fix database consistency first
        analyzer._fix_database_inconsistencies()    
        
        # First count the total number of files to be analyzed
        db_stats = execute_query_row(
            DB_PATH,
            '''SELECT 
                COUNT(*) as total_in_db,
                COALESCE(SUM(CASE WHEN analysis_status = 'analyzed' THEN 1 ELSE 0 END), 0) as already_analyzed
               FROM audio_files''',
            in_memory=DB_IN_MEMORY,
            cache_size_mb=DB_CACHE_SIZE_MB
        )
        
        total_in_db = db_stats['total_in_db'] if db_stats else 0
        already_analyzed = db_stats['already_analyzed'] if db_stats else 0
        pending_count = total_in_db - already_analyzed
            
        # Log counts
        logger.info(f"Database status: {total_in_db} total files, {already_analyzed} already analyzed, {pending_count} pending analysis")
            
        # Update status with these counts *before* starting analysis
        ANALYSIS_STATUS.update({
            'running': True,
            'start_time': datetime.now().isoformat(),
            'files_processed': already_analyzed,
            'total_files': total_in_db,
            'current_file': '',
            'percent_complete': 0,
            'last_updated': datetime.now().isoformat(),
            'error': None,
            'scan_complete': True  # ADD THIS LINE to change the display text
        })
        
        # Run analysis, passing the ANALYSIS_STATUS dictionary
        logger.info(f"Starting full analysis of pending files...")
        
        # Store the start time to calculate progress accurately
        start_time = time.time()
        
        # FIXED: Pass ANALYSIS_STATUS instead of importing it
        result = analyzer.analyze_pending_files(batch_size=5, status_dict=ANALYSIS_STATUS)
        
        # Update final status
        ANALYSIS_STATUS.update({
            'running': False,
            'percent_complete': 100,
            'last_updated': datetime.now().isoformat(),
            'error': None
        })
        
        # Save database changes if in-memory mode is active
        if DB_IN_MEMORY and main_thread_conn:
            from db_utils import trigger_db_save
            trigger_db_save(main_thread_conn, DB_PATH)
            
        logger.info(f"Analysis completed successfully. Total files: {total_in_db}, Analyzed: {result.get('analyzed', 0)}, Errors: {result.get('errors', 0)}, Pending: {result.get('pending', 0)}")
        
    except Exception as e:
        logger.error(f"Error running analysis: {e}")
        # Update status with error
        ANALYSIS_STATUS.update({
            'running': False,
            'error': str(e),
            'last_updated': datetime.now().isoformat()
        })
        
        # Save any partial changes to database
        if DB_IN_MEMORY and main_thread_conn:
            from db_utils import trigger_db_save
            trigger_db_save(main_thread_conn, DB_PATH)

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
            
            # Get scheduler settings
            startup_action = request.form.get('startup_action', 'nothing')
            schedule_frequency = request.form.get('schedule_frequency', 'never')
            
            # Make sure sections exist
            if not config.has_section('music'):
                config.add_section('music')
            if not config.has_section('lastfm'):
                config.add_section('lastfm')
            if not config.has_section('spotify'):
                config.add_section('spotify')
            if not config.has_section('app'):
                config.add_section('app')
            if not config.has_section('scheduler'):
                config.add_section('scheduler')
            
            # Update configuration
            config.set('music', 'folder_path', music_folder_path)
            config.set('music', 'recursive', 'true' if recursive else 'false')
            
            config.set('lastfm', 'api_key', lastfm_api_key)
            config.set('lastfm', 'api_secret', lastfm_api_secret)
            
            config.set('spotify', 'client_id', spotify_client_id)
            config.set('spotify', 'client_secret', spotify_client_secret)
            
            config.set('app', 'default_playlist_size', default_playlist_size)
            
            # Update scheduler configuration
            config.set('scheduler', 'startup_action', startup_action)
            config.set('scheduler', 'schedule_frequency', schedule_frequency)
            
            # If schedule is active, update the last run time to now
            if schedule_frequency != 'never':
                config.set('scheduler', 'last_run', datetime.now().isoformat())
            
            # Database performance settings
            if 'in_memory' in request.form:
                config.set('database_performance', 'in_memory', 
                         'true' if request.form.get('in_memory') == 'on' else 'false')
            
            if 'cache_size_mb' in request.form:
                cache_size = request.form.get('cache_size_mb', '75')
                # Validate it's a number between 10 and 1000
                try:
                    cache_size_int = int(cache_size)
                    if 10 <= cache_size_int <= 1000:
                        config.set('database_performance', 'cache_size_mb', cache_size)
                except ValueError:
                    # If not a valid number, keep existing value
                    pass
            
            # Save changes
            with open(config_file, 'w') as f:
                config.write(f)
            
            # Update the scheduler
            update_scheduler()
            
            # Mark database as modified (in case config db is stored in memory)
            if hasattr(g, 'db_modified'):  # Check if g exists
                g.db_modified = True
            
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
    
    # Get scheduler settings
    startup_action = config.get('scheduler', 'startup_action', fallback='nothing')
    schedule_frequency = config.get('scheduler', 'schedule_frequency', fallback='never')
    
    # Get database performance settings
    in_memory = config.getboolean('database_performance', 'in_memory', fallback=False)
    cache_size_mb = config.get('database_performance', 'cache_size_mb', fallback='75')
    
    # Calculate next scheduled run time for display
    next_run_time = calculate_next_run_time()
    
    # Get message and error from query parameters
    message = request.args.get('message', '')
    error = request.args.get('error', '')
    
    return render_template('settings.html',
        music_folder_path=music_folder_path,
        recursive=recursive,
        lastfm_api_key=lastfm_api_key,
        lastfm_api_secret=lastfm_api_secret,
        spotify_client_id=spotify_client_id,
        spotify_client_secret=spotify_client_secret,
        default_playlist_size=default_playlist_size,
        startup_action=startup_action,
        schedule_frequency=schedule_frequency,
        next_run_time=next_run_time,
        in_memory=in_memory,
        cache_size_mb=cache_size_mb,
        message=message,
        error=error
    )

@app.route('/debug/metadata')
def debug_metadata():
    """Debug endpoint to check metadata in database"""
    try:
        tracks = execute_query_dict(
            DB_PATH,
            '''SELECT id, file_path, title, artist, album, album_art_url, metadata_source
               FROM audio_files
               LIMIT 20''',
            in_memory=DB_IN_MEMORY,
            cache_size_mb=DB_CACHE_SIZE_MB
        )
        
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
    try:
        # Ensure the cache directory exists
        if not os.path.exists(CACHE_DIR):
            return jsonify({"status": "success", "message": "Cache is already empty"})
        
        # Get all files in the cache directory
        file_count = 0
        total_size = 0
        
        for filename in os.listdir(CACHE_DIR):
            file_path = os.path.join(CACHE_DIR, filename)
            if os.path.isfile(file_path):
                file_size = os.path.getsize(file_path)
                total_size += file_size
                os.remove(file_path)
                file_count += 1
        
        # Also clear artist image cache if it exists
        artist_cache_dir = 'artist_image_cache'
        if os.path.exists(artist_cache_dir):
            for filename in os.listdir(artist_cache_dir):
                file_path = os.path.join(artist_cache_dir, filename)
                if os.path.isfile(file_path):
                    file_size = os.path.getsize(file_path)
                    total_size += file_size
                    os.remove(file_path)
                    file_count += 1
        
        # Format sizes for display
        if total_size < 1024:
            size_str = f"{total_size} bytes"
        elif total_size < 1024 * 1024:
            size_str = f"{total_size / 1024:.1f} KB"
        else:
            size_str = f"{total_size / (1024 * 1024):.1f} MB"
        
        # Remove cache records from database if applicable
        with optimized_connection(DB_PATH, DB_IN_MEMORY, DB_CACHE_SIZE_MB) as conn:
            cursor = conn.cursor()
            
            # Update album_art_url to null for all tracks
            cursor.execute("UPDATE audio_files SET album_art_url = NULL WHERE album_art_url LIKE '/cache/%'")
            cursor.execute("UPDATE audio_files SET artist_image_url = NULL WHERE artist_image_url LIKE '/cache/%'")
            
            conn.commit()
            
            # Mark database as modified
            g.db_modified = True
        
        return jsonify({
            "status": "success",
            "message": f"Cache cleared. Removed {file_count} files ({size_str})."
        })
    
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

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
def save_playlist():
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data or 'name' not in data or 'tracks' not in data:
            return jsonify({'error': 'Missing required fields'}), 400
            
        name = data['name']
        description = data.get('description', '')
        tracks = data['tracks']
        
        # Validate tracks format
        if not isinstance(tracks, list):
            return jsonify({'error': 'Tracks must be a list'}), 400
            
        # Connect to database
        with optimized_connection(DB_PATH, DB_IN_MEMORY, DB_CACHE_SIZE_MB) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Insert playlist
            cursor.execute(
                'INSERT INTO playlists (name, description) VALUES (?, ?)',
                (name, description)
            )
            
            # Get the new playlist ID
            playlist_id = cursor.lastrowid
            
            # Insert tracks
            for i, track_id in enumerate(tracks):
                cursor.execute(
                    'INSERT INTO playlist_items (playlist_id, track_id, position) VALUES (?, ?, ?)',
                    (playlist_id, track_id, i)
                )
                
            conn.commit()
            
        # Mark database as modified
        g.db_modified = True
            
        return jsonify({
            'id': playlist_id,
            'name': name,
            'description': description,
            'track_count': len(tracks)
        })
        
    except Exception as e:
        logger.error(f"Error saving playlist: {e}")
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
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data:
            return jsonify({'error': 'No data provided'}), 400
            
        name = data.get('name')
        description = data.get('description')
        tracks = data.get('tracks')
        
        # Connect to database
        with optimized_connection(DB_PATH, DB_IN_MEMORY, DB_CACHE_SIZE_MB) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Check if playlist exists
            cursor.execute('SELECT id FROM playlists WHERE id = ?', (playlist_id,))
            if not cursor.fetchone():
                return jsonify({'error': 'Playlist not found'}), 404
                
            # Update playlist details if provided
            if name or description is not None:
                update_fields = []
                update_values = []
                
                if name:
                    update_fields.append('name = ?')
                    update_values.append(name)
                    
                if description is not None:
                    update_fields.append('description = ?')
                    update_values.append(description)
                    
                update_fields.append('updated_at = CURRENT_TIMESTAMP')
                
                cursor.execute(
                    f'UPDATE playlists SET {", ".join(update_fields)} WHERE id = ?',
                    update_values + [playlist_id]
                )
                
            # Update tracks if provided
            if tracks is not None:
                # First delete existing tracks
                cursor.execute('DELETE FROM playlist_items WHERE playlist_id = ?', (playlist_id,))
                
                # Then insert new tracks
                for i, track_id in enumerate(tracks):
                    cursor.execute(
                        'INSERT INTO playlist_items (playlist_id, track_id, position) VALUES (?, ?, ?)',
                        (playlist_id, track_id, i)
                    )
                    
            conn.commit()
            
        # Mark database as modified
        g.db_modified = True
            
        return jsonify({'message': 'Playlist updated successfully'})
        
    except Exception as e:
        logger.error(f"Error updating playlist: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/playlists/<int:playlist_id>', methods=['DELETE'])
def delete_playlist(playlist_id):
    try:
        # Connect to database
        with optimized_connection(DB_PATH, DB_IN_MEMORY, DB_CACHE_SIZE_MB) as conn:
            cursor = conn.cursor()
            
            # Check if playlist exists
            cursor.execute('SELECT id FROM playlists WHERE id = ?', (playlist_id,))
            if not cursor.fetchone():
                return jsonify({'error': 'Playlist not found'}), 404
                
            # Delete playlist (cascade will delete playlist items)
            cursor.execute('DELETE FROM playlists WHERE id = ?', (playlist_id,))
            conn.commit()
            
        # Mark database as modified
        g.db_modified = True
            
        return jsonify({'message': 'Playlist deleted successfully'})
        
    except Exception as e:
        logger.error(f"Error deleting playlist: {e}")
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
    try:
        # Get track data from database
        track = execute_query_row(
            DB_PATH,
            '''SELECT t.id, t.title, t.artist, t.album, t.file_path, t.album_art_url
               FROM audio_files t
               WHERE t.id = ?''',
            (track_id,),
            in_memory=DB_IN_MEMORY,
            cache_size_mb=DB_CACHE_SIZE_MB
        )
        
        if not track:
            return jsonify({'error': 'Track not found'}), 404
            
        # Track data is already in dict format
        return jsonify(track)
    except Exception as e:
        logger.error(f"Error getting track info for {track_id}: {e}")
        return jsonify({'error': str(e)}), 500

# Add caching headers to streaming route to improve playback

@app.route('/stream/<int:track_id>')
def stream(track_id):
    try:
        # Get the track information
        result = execute_query_row(
            DB_PATH,
            "SELECT file_path FROM audio_files WHERE id = ?",
            (track_id,),
            in_memory=DB_IN_MEMORY,
            cache_size_mb=DB_CACHE_SIZE_MB
        )
        
        if not result:
            return jsonify({"error": "Track not found"}), 404
            
        file_path = result['file_path']
        
        # Check if file exists
        if not os.path.exists(file_path):
            return jsonify({"error": "Audio file not found"}), 404
            
        # Add cache-control headers for better streaming performance
        response = send_file(file_path, conditional=True)
        response.headers['Accept-Ranges'] = 'bytes'
        response.headers['Cache-Control'] = 'public, max-age=3600'  # Cache for 1 hour
        
        return response
        
    except Exception as e:
        logger.error(f"Error streaming track {track_id}: {e}")
        return jsonify({"error": str(e)}), 500

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
        artists = execute_query_dict(
            DB_PATH,
            '''SELECT 
                artist, 
                COUNT(*) as track_count,
                artist_image_url,
                SUM(duration) as total_duration
            FROM audio_files
            WHERE artist IS NOT NULL AND artist != ''
            GROUP BY artist
            ORDER BY artist COLLATE NOCASE''',
            in_memory=DB_IN_MEMORY,
            cache_size_mb=DB_CACHE_SIZE_MB
        )
        
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
    # Initialize LastFM service
    lastfm_api_key = config.get('lastfm', 'api_key', fallback='')
    lastfm_api_secret = config.get('lastfm', 'api_secret', fallback='')
    
    if not lastfm_api_key or not lastfm_api_secret:
        return jsonify({"status": "error", "message": "LastFM API keys not configured"}), 400
        
    service_name = request.args.get('service', 'lastfm')
    
    if service_name == 'lastfm':
        service = LastFMService(lastfm_api_key, lastfm_api_secret)
    else:
        return jsonify({"status": "error", "message": f"Unknown service: {service_name}"}), 400
    
    try:
        # Connect to database
        with optimized_connection(DB_PATH, DB_IN_MEMORY, DB_CACHE_SIZE_MB) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Get distinct artists without images
            cursor.execute('''
                SELECT DISTINCT artist
                FROM audio_files
                WHERE artist IS NOT NULL AND artist != '' AND artist_image_url IS NULL OR artist_image_url = ''
                LIMIT 50
            ''')
            
            artists = [row['artist'] for row in cursor.fetchall()]
            
            if not artists:
                return jsonify({"status": "success", "message": "No artists need images"})
                
            # Create cache directory if it doesn't exist
            artist_cache_dir = 'artist_image_cache'
            if not os.path.exists(artist_cache_dir):
                os.makedirs(artist_cache_dir)
                
            updated_count = 0
            
            # Get images for each artist
            for artist in artists:
                try:
                    # Check if we already have an image for this artist (might have been added in a previous run)
                    if artist_has_image(artist):
                        continue
                        
                    # Clean artist name
                    clean_artist = sanitize_artist_name(artist)
                    
                    # Get image from service
                    image_url = service.get_artist_image_url(clean_artist, cache_dir=artist_cache_dir)
                    
                    if image_url:
                        # Update all tracks for this artist
                        cursor.execute('''
                            UPDATE audio_files
                            SET artist_image_url = ?
                            WHERE artist = ?
                        ''', (image_url, artist))
                        
                        updated_count += cursor.rowcount
                        
                except Exception as e:
                    logger.error(f"Error getting image for artist '{artist}': {e}")
                    continue
                    
            # Commit changes
            conn.commit()
            
            # Mark database as modified
            g.db_modified = True
                
            return jsonify({
                "status": "success",
                "message": f"Updated {updated_count} tracks with artist images",
                "artists_processed": len(artists),
                "updated_count": updated_count
            })
            
    except Exception as e:
        logger.error(f"Error updating artist images: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

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
    # Initialize Spotify service
    spotify_client_id = config.get('spotify', 'client_id', fallback='')
    spotify_client_secret = config.get('spotify', 'client_secret', fallback='')
    
    if not spotify_client_id or not spotify_client_secret:
        return jsonify({"status": "error", "message": "Spotify API keys not configured"}), 400
        
    service = SpotifyService(spotify_client_id, spotify_client_secret)
    
    try:
        # Connect to database
        with optimized_connection(DB_PATH, DB_IN_MEMORY, DB_CACHE_SIZE_MB) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Get distinct artists without images
            cursor.execute('''
                SELECT DISTINCT artist
                FROM audio_files
                WHERE artist IS NOT NULL AND artist != '' 
                AND (artist_image_url IS NULL OR artist_image_url = '')
                LIMIT 50
            ''')
            
            artists = [row['artist'] for row in cursor.fetchall()]
            
            if not artists:
                return jsonify({"status": "success", "message": "No artists need images"})
                
            # Create cache directory if it doesn't exist
            artist_cache_dir = 'artist_image_cache'
            if not os.path.exists(artist_cache_dir):
                os.makedirs(artist_cache_dir)
                
            updated_count = 0
            
            # Get images for each artist
            for artist in artists:
                try:
                    # Check if we already have an image for this artist (might have been added in a previous run)
                    if artist_has_image(artist):
                        continue
                        
                    # Clean artist name
                    clean_artist = sanitize_artist_name(artist)
                    
                    # Get image from service
                    image_url = service.get_artist_image_url(clean_artist, cache_dir=artist_cache_dir)
                    
                    if image_url:
                        # Update all tracks for this artist
                        cursor.execute('''
                            UPDATE audio_files
                            SET artist_image_url = ?
                            WHERE artist = ?
                        ''', (image_url, artist))
                        
                        updated_count += cursor.rowcount
                        
                except Exception as e:
                    logger.error(f"Error getting image for artist '{artist}': {e}")
                    continue
                    
            # Commit changes
            conn.commit()
            
            # Mark database as modified
            g.db_modified = True
                
            return jsonify({
                "status": "success",
                "message": f"Updated {updated_count} tracks with artist images via Spotify",
                "artists_processed": len(artists),
                "updated_count": updated_count
            })
            
    except Exception as e:
        logger.error(f"Error updating artist images via Spotify: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

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
def scan_library_endpoint():
    """Start a quick scan of the music library without analyzing audio features"""
    try:
        data = request.get_json()
        directory = data.get('directory')
        recursive = data.get('recursive', True)
        
        if not directory:
            return jsonify({"success": False, "error": "No directory specified"}), 400
            
        # Don't start if already running
        global QUICK_SCAN_STATUS
        if QUICK_SCAN_STATUS['running']:
            return jsonify({
                "success": False, 
                "error": "A scan is already in progress"
            })
            
        # Start quick scan in a background thread
        thread = threading.Thread(
            target=run_quick_scan,
            args=(directory, recursive)
        )
        thread.daemon = True
        thread.start()
        
        logger.info(f"Started quick scan for directory: {directory} (recursive={recursive})")
        
        return jsonify({"success": True})
        
    except Exception as e:
        logger.error(f"Error starting quick scan: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/start_background_analysis', methods=['POST'])
def start_background_analysis():
    try:
        # Check if already running
        if analysis_progress['is_running']:
            return jsonify({
                'status': 'error',
                'message': 'Analysis is already running'
            }), 409
        
        # Get folder path from config
        folder_path = config.get('music', 'folder_path', fallback='')
        recursive = config.getboolean('music', 'recursive', fallback=True)
        
        if not folder_path:
            return jsonify({
                'status': 'error',
                'message': 'Music folder path not configured'
            }), 400
        
        if not os.path.exists(folder_path):
            return jsonify({
                'status': 'error',
                'message': f'Music folder path does not exist: {folder_path}'
            }), 400
        
        # Start analysis in a background thread
        analysis_thread = threading.Thread(
            target=run_analysis,
            args=(folder_path, recursive)
        )
        analysis_thread.daemon = True
        analysis_thread.start()
        
        # Mark database as modified (actual modification happens in thread)
        g.db_modified = True
        
        return jsonify({
            'status': 'success',
            'message': f'Background analysis started for {folder_path}'
        })
        
    except Exception as e:
        logger.error(f"Error starting background analysis: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

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
    if not metadata_service:
        return jsonify({"status": "error", "message": "Metadata service not available"}), 500
        
    # Get skip_existing parameter
    skip_existing = request.form.get('skip_existing', 'false') == 'true'
    
    # Check if metadata update is already running
    if METADATA_UPDATE_STATUS['running']:
        return jsonify({"status": "error", "message": "Metadata update already in progress"}), 409
    
    # Update status
    METADATA_UPDATE_STATUS.update({
        'running': True,
        'start_time': datetime.now().isoformat(),
        'total_tracks': 0,
        'processed_tracks': 0,
        'updated_tracks': 0,
        'current_track': '',
        'percent_complete': 0,
        'last_updated': datetime.now().isoformat(),
        'error': None
    })
    
    # Start metadata update in a background thread
    metadata_thread = threading.Thread(target=run_metadata_update, args=(skip_existing,))
    metadata_thread.daemon = True
    metadata_thread.start()
    
    # Mark database as modified (actual modification happens in thread)
    g.db_modified = True
    
    return jsonify({"status": "started", "message": "Metadata update started"})

# Add this function to run metadata update in background
def run_metadata_update(skip_existing=False):
    """Run metadata update in a background thread"""
    try:
        if not metadata_service:
            logger.error("Cannot update metadata: Metadata service not available")
            return
            
        # Run metadata update
        logger.info(f"Starting metadata update (skip_existing={skip_existing})")
        metadata_service.update_all_metadata(status_tracker=METADATA_UPDATE_STATUS, skip_existing=skip_existing)
        
        # Update final status
        METADATA_UPDATE_STATUS.update({
            'running': False,
            'percent_complete': 100,
            'last_updated': datetime.now().isoformat()
        })
        
        # Save database changes if in-memory mode is active
        if DB_IN_MEMORY and main_thread_conn:
            from db_utils import trigger_db_save
            trigger_db_save(main_thread_conn, DB_PATH)
        
        logger.info("Metadata update completed successfully")
        
    except Exception as e:
        logger.error(f"Error updating metadata: {e}")
        # Update status with error
        METADATA_UPDATE_STATUS.update({
            'running': False,
            'error': str(e),
            'last_updated': datetime.now().isoformat()
        })
        
        # Save any partial changes to database
        if DB_IN_MEMORY and main_thread_conn:
            from db_utils import trigger_db_save
            trigger_db_save(main_thread_conn, DB_PATH)

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
def metadata_update_status():
    """Get the current status of a metadata update"""
    try:
        is_running = METADATA_UPDATE_STATUS['running']
        
        # Calculate elapsed time if running
        elapsed_seconds = 0
        if is_running and METADATA_UPDATE_STATUS['start_time']:
            # Parse the ISO format string back to datetime
            start_time = datetime.fromisoformat(METADATA_UPDATE_STATUS['start_time'])
            elapsed = datetime.now() - start_time
            elapsed_seconds = elapsed.total_seconds()
            
        # Calculate estimated time remaining if possible
        remaining_seconds = 0
        if is_running and METADATA_UPDATE_STATUS['percent_complete'] > 0:
            # Avoid division by zero
            percent = max(0.1, METADATA_UPDATE_STATUS['percent_complete'])
            remaining_seconds = (elapsed_seconds / percent) * (100 - percent)
            
        return jsonify({
            'running': is_running,
            'total_tracks': METADATA_UPDATE_STATUS['total_tracks'],
            'processed_tracks': METADATA_UPDATE_STATUS['processed_tracks'],
            'updated_tracks': METADATA_UPDATE_STATUS['updated_tracks'],
            'current_track': METADATA_UPDATE_STATUS['current_track'],
            'percent_complete': METADATA_UPDATE_STATUS['percent_complete'],
            'elapsed_seconds': round(elapsed_seconds),
            'remaining_seconds': round(remaining_seconds),
            'error': METADATA_UPDATE_STATUS['error']
        })
    except Exception as e:
        logger.error(f"Error getting metadata update status: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/status')
def analysis_status():
    """Get the current status of an analysis"""
    try:
        is_running = ANALYSIS_STATUS['running']
        
        # Calculate elapsed time if running
        elapsed_seconds = 0
        if is_running and ANALYSIS_STATUS['start_time']:
            # Parse the ISO format string back to datetime
            start_time = datetime.fromisoformat(ANALYSIS_STATUS['start_time'])
            elapsed = datetime.now() - start_time
            elapsed_seconds = elapsed.total_seconds()
            
        # Calculate estimated time remaining if possible
        remaining_seconds = 0
        if is_running and ANALYSIS_STATUS['percent_complete'] > 0:
            # Avoid division by zero
            percent = max(0.1, ANALYSIS_STATUS['percent_complete'])
            remaining_seconds = (elapsed_seconds / percent) * (100 - percent)
            
        return jsonify({
            'running': is_running,
            'files_processed': ANALYSIS_STATUS['files_processed'],
            'total_files': ANALYSIS_STATUS['total_files'],
            'current_file': ANALYSIS_STATUS['current_file'],
            'percent_complete': ANALYSIS_STATUS['percent_complete'],
            'elapsed_seconds': round(elapsed_seconds),
            'remaining_seconds': round(remaining_seconds),
            'error': ANALYSIS_STATUS['error'],
            'scan_complete': ANALYSIS_STATUS.get('scan_complete', False)  # ADD THIS LINE
        })
    except Exception as e:
        logger.error(f"Error getting analysis status: {e}")
        return jsonify({'error': str(e)}), 500

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
        with optimized_connection(DB_PATH, DB_IN_MEMORY, DB_CACHE_SIZE_MB) as conn:
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


def run_quick_scan(folder_path, recursive=True):
    """Run quick scan in a background thread"""
    try:
        # Make sure analyzer exists
        if not analyzer:
            logger.error("Cannot run quick scan: Music analyzer not available")
            return
            
        # Update status
        QUICK_SCAN_STATUS.update({
            'running': True,
            'start_time': datetime.now().isoformat(),
            'files_processed': 0,
            'tracks_added': 0,
            'total_files': 0,
            'current_file': '',
            'percent_complete': 0,
            'last_updated': datetime.now().isoformat(),
            'error': None
        })
        
        # Run scan
        logger.info(f"Starting quick scan of {folder_path} (recursive={recursive})")
        result = analyzer.scan_library(folder_path, recursive=recursive)
        
        # Update final status
        QUICK_SCAN_STATUS.update({
            'running': False,
            'percent_complete': 100,
            'files_processed': result.get('processed', 0),
            'tracks_added': result.get('added', 0),
            'last_updated': datetime.now().isoformat()
        })
        
        # Save database changes if in-memory mode is active
        if DB_IN_MEMORY and main_thread_conn:
            from db_utils import trigger_db_save
            trigger_db_save(main_thread_conn, DB_PATH)
            
        logger.info(f"Quick scan completed successfully. Processed {result.get('processed', 0)} files, added {result.get('added', 0)} tracks.")
        
    except Exception as e:
        logger.error(f"Error running quick scan: {e}")
        # Update status with error
        QUICK_SCAN_STATUS.update({
            'running': False,
            'error': str(e),
            'last_updated': datetime.now().isoformat()
        })
        
        # Save any partial changes to database
        if DB_IN_MEMORY and main_thread_conn:
            from db_utils import trigger_db_save
            trigger_db_save(main_thread_conn, DB_PATH)

@app.route('/api/quick-scan/status')
def quick_scan_status():
    """Get the current status of a quick scan"""
    try:
        is_running = QUICK_SCAN_STATUS['running']
        
        # Calculate elapsed time if running
        elapsed_seconds = 0
        if is_running and QUICK_SCAN_STATUS['start_time']:
            # Parse the ISO format string back to datetime
            start_time = datetime.fromisoformat(QUICK_SCAN_STATUS['start_time'])
            elapsed = datetime.now() - start_time
            elapsed_seconds = elapsed.total_seconds()
            
        # Calculate estimated time remaining if possible
        remaining_seconds = 0
        if is_running and QUICK_SCAN_STATUS['percent_complete'] > 0:
            # Avoid division by zero
            percent = max(0.1, QUICK_SCAN_STATUS['percent_complete'])
            remaining_seconds = (elapsed_seconds / percent) * (100 - percent)
            
        return jsonify({
            'running': is_running,
            'files_processed': QUICK_SCAN_STATUS['files_processed'],
            'tracks_added': QUICK_SCAN_STATUS['tracks_added'],
            'total_files': QUICK_SCAN_STATUS['total_files'],
            'current_file': QUICK_SCAN_STATUS['current_file'],
            'percent_complete': QUICK_SCAN_STATUS['percent_complete'],
            'elapsed_seconds': round(elapsed_seconds),
            'remaining_seconds': round(remaining_seconds),
            'error': QUICK_SCAN_STATUS['error']
        })
    except Exception as e:
        logger.error(f"Error getting quick scan status: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/quick-scan', methods=['POST'])
def quick_scan_api():
    """API endpoint for quick scanning music library"""
    try:
        data = request.get_json()
        folder_path = data.get('folder_path', '')
        recursive = data.get('recursive', True)
        
        if not folder_path:
            return jsonify({"success": False, "error": "No folder path specified"}), 400
            
        # Don't start if already running
        if QUICK_SCAN_STATUS['running']:
            return jsonify({
                "success": False, 
                "error": "A scan is already in progress"
            })
            
        # Start quick scan in a background thread
        thread = threading.Thread(
            target=run_quick_scan,
            args=(folder_path, recursive)
        )
        thread.daemon = True
        thread.start()
        
        # Mark database as modified
        g.db_modified = True
        
        logger.info(f"Started quick scan for directory: {folder_path} (recursive={recursive})")
        
        return jsonify({
            "success": True,
            "message": "Quick scan started in background"
        })
        
    except Exception as e:
        logger.error(f"Error starting quick scan: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

def update_scheduler():
    """Update the scheduler based on current configuration"""
    global SCHEDULER_TIMER, SCHEDULER_RUNNING
    
    # Cancel any existing timer
    if SCHEDULER_TIMER:
        SCHEDULER_TIMER.cancel()
        SCHEDULER_TIMER = None
    
    # Get current settings
    frequency = config.get('scheduler', 'schedule_frequency', fallback='never')
    
    # If schedule is disabled, just return
    if frequency == 'never':
        logger.info("Scheduler disabled")
        return
    
    # Calculate interval in seconds
    interval = get_interval_seconds(frequency)
    
    # Schedule the next run
    SCHEDULER_TIMER = threading.Timer(interval, run_scheduled_tasks)
    SCHEDULER_TIMER.daemon = True
    SCHEDULER_TIMER.start()
    
    logger.info(f"Scheduler set to run every {frequency}")

def get_interval_seconds(frequency):
    """Convert frequency string to seconds"""
    if frequency == '15min':
        return 15 * 60
    elif frequency == '1hour':
        return 60 * 60
    elif frequency == '6hours':
        return 6 * 60 * 60
    elif frequency == '12hours':
        return 12 * 60 * 60
    elif frequency == '24hours':
        return 24 * 60 * 60  # Default to 24 hours

def calculate_next_run_time():
    """Calculate when the next scheduled run will happen"""
    frequency = config.get('scheduler', 'schedule_frequency', fallback='never')
    
    if frequency == 'never':
        return "Not scheduled"
    
    # Get last run time
    last_run_str = config.get('scheduler', 'last_run', fallback=None)
    
    if not last_run_str:
        # If never run, schedule from now
        last_run = datetime.now()
    else:
        try:
            last_run = datetime.fromisoformat(last_run_str)
        except (ValueError, TypeError):
            last_run = datetime.now()
    
    # Calculate next run time
    interval = get_interval_seconds(frequency)
    next_run = last_run + timedelta(seconds=interval)
    
    # Format for display
    now = datetime.now()
    if next_run < now:
        # If we're past due, reschedule from now
        next_run = now + timedelta(seconds=interval)
    
    # Format the time
    if (next_run - now).total_seconds() < 60:
        return "Less than a minute"
    elif (next_run - now).total_seconds() < 3600:
        minutes = int((next_run - now).total_seconds() / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    else:
        return next_run.strftime("%Y-%m-%d %H:%M")

def run_scheduled_tasks():
    """Run the configured tasks on schedule"""
    global SCHEDULER_RUNNING
    
    if SCHEDULER_RUNNING:
        logger.warning("Scheduled tasks already running, skipping this run")
        # Reschedule for next time
        update_scheduler()
        return
    
    try:
        SCHEDULER_RUNNING = True
        logger.info("Starting scheduled tasks")
        
        # Get the action to perform
        action = config.get('scheduler', 'startup_action', fallback='nothing')
        
        # Update last run time
        config.set('scheduler', 'last_run', datetime.now().isoformat())
        with open(config_file, 'w') as f:
            config.write(f)
        
        # Run the appropriate action(s)
        if action == 'nothing':
            logger.info("No action configured for scheduler")
        elif action == 'quick_scan':
            run_quick_scan_task()
        elif action == 'quick_scan_metadata':
            run_quick_scan_task()
            run_metadata_update_task()
        elif action == 'full_analysis':
            run_quick_scan_task()
            run_metadata_update_task()
            run_full_analysis_task()
        
        logger.info("Scheduled tasks completed")
    except Exception as e:
        logger.error(f"Error running scheduled tasks: {e}")
    finally:
        SCHEDULER_RUNNING = False
        # Reschedule for next time
        update_scheduler()

def run_quick_scan_task():
    """Run quick scan as a scheduled task"""
    logger.info("Running scheduled quick scan")
    
    # Get folder path from config
    folder_path = config.get('music', 'folder_path', fallback='')
    recursive = config.getboolean('music', 'recursive', fallback=True)
    
    if not folder_path:
        logger.error("Music folder path not configured")
        return False
        
    if not os.path.exists(folder_path):
        logger.error(f"Music folder path does not exist: {folder_path}")
        return False
        
    try:
        result = run_quick_scan(folder_path, recursive)
        logger.info("Scheduled quick scan completed")
        
        # Add this line to save changes if in-memory mode is active
        if DB_IN_MEMORY and main_thread_conn:
            from db_utils import trigger_db_save
            trigger_db_save(main_thread_conn, DB_PATH)
            
        return result
    except Exception as e:
        logger.error(f"Error running scheduled quick scan: {e}")
        return False

def run_metadata_update_task():
    """Run metadata update task for scheduler"""
    global METADATA_UPDATE_STATUS
    
    logger.info("Running scheduled metadata update")
    
    # Update status to trigger UI update
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
    
    # Use existing metadata update function
    try:
        # Skip existing metadata to avoid unnecessary updates
        metadata_service.update_all_metadata(status_tracker=METADATA_UPDATE_STATUS, skip_existing=True)
        logger.info("Scheduled metadata update completed")
    except Exception as e:
        logger.error(f"Error during scheduled metadata update: {e}")
        METADATA_UPDATE_STATUS.update({
            'running': False,
            'error': str(e),
            'last_updated': datetime.now()
        })

def run_full_analysis_task():
    """Run full analysis as a scheduled task"""
    logger.info("Running scheduled full analysis")
    
    # Get folder path from config
    folder_path = config.get('music', 'folder_path', fallback='')
    recursive = config.getboolean('music', 'recursive', fallback=True)
    
    if not folder_path:
        logger.error("Music folder path not configured")
        return False
        
    if not os.path.exists(folder_path):
        logger.error(f"Music folder path does not exist: {folder_path}")
        return False
        
    try:
        run_analysis(folder_path, recursive)
        logger.info("Scheduled full analysis completed")
        
        # Add this line to save changes if in-memory mode is active
        if DB_IN_MEMORY and main_thread_conn:
            from db_utils import trigger_db_save
            trigger_db_save(main_thread_conn, DB_PATH)
            
        return True
    except Exception as e:
        logger.error(f"Error running scheduled full analysis: {e}")
        return False

def run_startup_actions():
    """Run configured startup actions when the app starts"""
    action = config.get('scheduler', 'startup_action', fallback='nothing')
    
    if action == 'nothing':
        logger.info("No startup actions configured")
        return
    
    logger.info(f"Running startup action: {action}")
    
    # Add a short delay to ensure UI has loaded before starting tasks
    def run_actions():
        try:
            # Give UI time to initialize
            time.sleep(2)
            
            if action == 'quick_scan':
                logger.info("Starting quick scan as startup action")
                run_quick_scan_task()
            elif action == 'quick_scan_metadata':
                logger.info("Starting quick scan and metadata update as startup action")
                run_quick_scan_task()
                # Only start metadata update after quick scan completes
                while QUICK_SCAN_STATUS['running']:
                    time.sleep(1)
                run_metadata_update_task()
            elif action == 'full_analysis':
                logger.info("Starting full analysis workflow as startup action")
                run_quick_scan_task()
                # Wait for quick scan to complete
                while QUICK_SCAN_STATUS['running']:
                    time.sleep(1)
                
                # Start both metadata update and analysis concurrently
                logger.info("Starting both metadata update and analysis concurrently")
                metadata_thread = threading.Thread(target=run_metadata_update_task)
                metadata_thread.daemon = True
                metadata_thread.start()
                
                # Start analysis without waiting for metadata to complete
                time.sleep(1)  # Small delay to let metadata initialize
                run_full_analysis_task()
            
            logger.info("Startup actions initiated")
        except Exception as e:
            logger.error(f"Error running startup actions: {e}")
    
    thread = threading.Thread(target=run_actions)
    thread.daemon = True
    thread.start()

# Add this API endpoint for next run time
@app.route('/api/next-scheduled-run')
def get_next_scheduled_run():
    """Get the next scheduled run time"""
    next_run = calculate_next_run_time()
    return jsonify({'next_run': next_run})

def setup_liked_tracks_column():
    """Ensure the database has the necessary liked column"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Check if the liked column exists
        cursor.execute("PRAGMA table_info(audio_files)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'liked' not in columns:
            logger.info("Adding 'liked' column to audio_files table")
            cursor.execute("ALTER TABLE audio_files ADD COLUMN liked INTEGER DEFAULT 0")
            conn.commit()
            
        conn.close()
        logger.info("Database setup for liked tracks complete")
    except Exception as e:
        logger.error(f"Error setting up liked tracks column: {e}")

# Then call it during app initialization (add this near where you create your app)
with app.app_context():
    setup_liked_tracks_column()

# Add these routes for liked tracks functionality

@app.route('/api/liked-tracks')
def get_liked_tracks():
    """Get all liked tracks"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, file_path, title, artist, album, duration, album_art_url
            FROM audio_files
            WHERE liked = 1
            ORDER BY artist, album, title
        """)
        
        tracks = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify(tracks)
    except Exception as e:
        logger.error(f"Error getting liked tracks: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/tracks/<int:track_id>/like', methods=['POST'])
def like_track(track_id):
    try:
        data = request.get_json()
        liked = data.get('liked', False)
        
        # Connect to database
        with optimized_connection(DB_PATH, DB_IN_MEMORY, DB_CACHE_SIZE_MB) as conn:
            cursor = conn.cursor()
            
            # Check if track exists
            cursor.execute('SELECT id FROM audio_files WHERE id = ?', (track_id,))
            if not cursor.fetchone():
                return jsonify({'error': 'Track not found'}), 404
                
            # Update liked status
            cursor.execute(
                'UPDATE audio_files SET liked = ? WHERE id = ?',
                (1 if liked else 0, track_id)
            )
            
            conn.commit()
            
            # Mark database as modified
            g.db_modified = True
                
            return jsonify({
                'success': True,
                'track_id': track_id,
                'liked': liked
            })
            
    except Exception as e:
        logger.error(f"Error updating liked status: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/tracks/<int:track_id>/liked')
def is_track_liked(track_id):
    """Check if a track is liked"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT liked FROM audio_files WHERE id = ?", (track_id,))
        result = cursor.fetchone()
        
        conn.close()
        
        if not result:
            return jsonify({"liked": False}), 404
            
        return jsonify({"liked": result[0] == 1})
    except Exception as e:
        logger.error(f"Error checking liked status for track {track_id}: {e}")
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/all-status')
def get_all_status():
    """Single endpoint to get all statuses at once to reduce API calls"""
    return jsonify({
        'analysis': {
            'running': ANALYSIS_STATUS.get('running', False),
            'percent': ANALYSIS_STATUS.get('percent_complete', 0),
            'files_processed': ANALYSIS_STATUS.get('files_processed', 0),
            'total_files': ANALYSIS_STATUS.get('total_files', 0),
            'error': ANALYSIS_STATUS.get('error')
        },
        'metadata': {
            'running': METADATA_UPDATE_STATUS.get('running', False),
            'percent': METADATA_UPDATE_STATUS.get('percent_complete', 0),
            'processed': METADATA_UPDATE_STATUS.get('processed_tracks', 0),
            'updated': METADATA_UPDATE_STATUS.get('updated_tracks', 0),
            'total': METADATA_UPDATE_STATUS.get('total_tracks', 0),
            'error': METADATA_UPDATE_STATUS.get('error')
        },
        'quickScan': {
            'running': QUICK_SCAN_STATUS.get('running', False),
            'percent': QUICK_SCAN_STATUS.get('percent_complete', 0),
            'files_processed': QUICK_SCAN_STATUS.get('files_processed', 0),
            'tracks_added': QUICK_SCAN_STATUS.get('tracks_added', 0),
            'error': QUICK_SCAN_STATUS.get('error')
        }
    })


# Add this function near the end of the file

def create_indexes():
    """Create indexes for commonly searched fields"""
    try:
        with optimized_connection(DB_PATH, DB_IN_MEMORY, DB_CACHE_SIZE_MB) as conn:
            cursor = conn.cursor()
            
            # Create indexes if they don't exist
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_artist ON audio_files(artist)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_album ON audio_files(album)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_title ON audio_files(title)")
            
            logger.info("Database indexes created successfully")
    except Exception as e:
        logger.error(f"Error creating database indexes: {e}")

# Then call it directly during app initialization:
# Add this near line 270-300 where you initialize other components
create_indexes()

# Add this route

@app.route('/api/db-status')
def get_db_status():
    """Get database performance statistics"""
    try:
        with optimized_connection(DB_PATH, DB_IN_MEMORY, DB_CACHE_SIZE_MB) as conn:
            cursor = conn.cursor()
            
            # Get database size
            if os.path.exists(DB_PATH):
                db_size = os.path.getsize(DB_PATH) / (1024 * 1024)  # Size in MB
            else:
                db_size = 0
                
            # Get table counts
            cursor.execute("SELECT COUNT(*) FROM audio_files")
            track_count = cursor.fetchone()[0]
            
            try:
                cursor.execute("SELECT COUNT(*) FROM audio_features")
                feature_count = cursor.fetchone()[0]
            except:
                feature_count = 0
            
            # Get SQLite's cache statistics
            cursor.execute("PRAGMA cache_size")
            cache_size = cursor.fetchone()[0]
            
            cursor.execute("PRAGMA page_size")
            page_size = cursor.fetchone()[0]
            
            # Calculate memory usage
            approx_memory_usage = (abs(cache_size) * page_size) / (1024 * 1024)  # in MB
            
            return jsonify({
                'db_size_mb': round(db_size, 2),
                'track_count': track_count,
                'feature_count': feature_count,
                'in_memory_mode': DB_IN_MEMORY,
                'cache_size_mb': DB_CACHE_SIZE_MB,
                'approx_memory_usage_mb': round(approx_memory_usage, 2),
                'page_size_bytes': page_size
            })
            
    except Exception as e:
        logger.error(f"Error getting DB status: {e}")
        return jsonify({'error': str(e)}), 500



@app.route('/api/analysis/database-status')
def analysis_database_status():
    """Get the analysis status directly from the database"""
    try:
        with optimized_connection(DB_PATH, DB_IN_MEMORY, DB_CACHE_SIZE_MB) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Get count of analyzed vs non-analyzed tracks - FIXED COLUMN NAME AND NULL HANDLING
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_in_db,
                    COALESCE(SUM(CASE WHEN analysis_status = 'analyzed' THEN 1 ELSE 0 END), 0) as already_analyzed
                FROM audio_files
            ''')
            result = cursor.fetchone()
            
            total_in_db = result['total_in_db'] if result else 0
            already_analyzed = result['already_analyzed'] if result else 0
            pending_count = total_in_db - already_analyzed
            
            return jsonify({
                'total': total_in_db,
                'analyzed': already_analyzed,
                'pending': pending_count,
                'percent_complete': round((already_analyzed / total_in_db) * 100, 2) if total_in_db > 0 else 0
            })
    except Exception as e:
        logger.error(f"Error getting database analysis status: {e}")
        return jsonify({'error': str(e)}), 500


# Updated run_server function that initializes scheduler and runs startup actions
def run_server():
    """Run the Flask server"""
    logger.info(f"Starting server on {HOST}:{PORT} (debug={DEBUG})")
    
    # Initialize the scheduler
    update_scheduler()
    
    # Run startup actions
    run_startup_actions()
    
    try:
        # Use Werkzeug's run_simple for better error handling
        run_simple(hostname=HOST, port=PORT, application=app, use_reloader=DEBUG, use_debugger=DEBUG)
    except Exception as e:
        logger.error(f"Error running server: {e}")

if __name__ == '__main__':
    run_server()