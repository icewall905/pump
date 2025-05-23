import os
import sqlite3
import random
import configparser
import logging
import hashlib
import glob  # Add missing glob import
import threading
import queue
import signal
import atexit
import sys
import re
import time
import psycopg2  # Add this import for PostgreSQL
from psycopg2.extras import DictCursor
from flask import Flask, render_template, request, jsonify, Response, send_file, g, session, redirect, url_for
from music_analyzer import MusicAnalyzer
from werkzeug.serving import run_simple
import requests
from urllib.parse import unquote
import pathlib
from metadata_service import MetadataService
from lastfm_service import LastFMService
from spotify_service import SpotifyService  # Add this import at the top
from datetime import datetime, timedelta
from db_operations import (
    save_memory_db_to_disk, import_disk_db_to_memory, 
    execute_query_dict, execute_with_retry, execute_query_row,
    get_optimized_connection, trigger_db_save, optimized_connection, reset_database_locks
)

# Add near the top of your file
import os
import atexit
import signal
import threading

# Add near the top of your file after other imports
from db_operations import (
    get_connection, execute_query, execute_query_dict, execute_write,
    optimized_connection, trigger_db_save, reset_database_locks,
    transaction_context, release_connection
)

# Initialize a placeholder logger EARLY, this will be configured properly later
logger = logging.getLogger('web_player')


import os
import logging
import sqlite3
import configparser
import threading
import queue

def initialize_config():
    """Initialize configuration with defaults but preserve user settings"""
    config = configparser.ConfigParser()
    config_file = 'pump.conf'  # Define config_file inside the function
    
    # Default configuration
    default_config = {
        'server': {
            'host': '0.0.0.0',
            'port': '8080',
            'debug': 'true'
        },
#        'database': {
#            'path': 'pump.db'
#        },
        'app': {
            'default_playlist_size': '10',
            'max_search_results': '50'
        },
        'music': {
            'folder_path': './music',
            'recursive': 'true'
        },
        'logging': {
            'level': 'info',
            'log_to_file': 'true',
            'log_dir': 'logs',
            'max_size_mb': '10',
            'backup_count': '5'
        },
        'DATABASE': {
            'host': 'localhost',
            'port': '45432',
            'user': 'pump',
            'password': 'Ge3hgU07bXlBigvTbRSX',
            'dbname': 'pump',
            'min_connections': '1',
            'max_connections': '10'
        },
        'lastfm': {
            'api_key': 'b8b4d3c72ac643dbd9e069c6474a0b0b',
            'api_secret': 'de0459d5ee5c5dd9f838735774d41f9e'
        },
        'cache': {
            'image_cache_dir': 'album_art_cache',
            'max_cache_size_mb': '500'
        },
        'scheduler': {
            'startup_action': 'none',
            'schedule_frequency': 'never',
            'last_run': ''
        },
        'database_performance': {
            'in_memory': 'false',
            'cache_size_mb': '75',
            'optimize_connections': 'true'
        }
    }
    
    # Load existing config if it exists
    config_updated = False
    if os.path.exists(config_file):
        print(f"Loading existing configuration from {config_file}")
        config.read(config_file)
    else:
        print(f"Configuration file {config_file} does not exist, creating with defaults")
        config_updated = True
        
    # Add missing sections and options but NEVER overwrite existing values
    for section, options in default_config.items():
        if not config.has_section(section):
            print(f"Adding missing section: {section}")
            config.add_section(section)
            config_updated = True
        
        for option, value in options.items():
            if not config.has_option(section, option):
                print(f"Adding missing option: {section}.{option} = {value}")
                config.set(section, option, value)
                config_updated = True
    
    # Add API keys section if it doesn't exist
    if not config.has_section('api_keys'):
        print("Adding api_keys section")
        config.add_section('api_keys')
        config.set('api_keys', 'lastfm_api_key', 'b8b4d3c72ac643dbd9e069c6474a0b0b')
        config.set('api_keys', 'lastfm_api_secret', 'de0459d5ee5c5dd9f838735774d41f9e')
        config_updated = True

    # Add configuration for image caching
    if not config.has_section('cache'):
        print("Adding cache section")
        config.add_section('cache')
        config.set('cache', 'image_cache_dir', 'album_art_cache')
        config.set('cache', 'max_cache_size_mb', '500')  # 500MB default cache size
        config_updated = True

    # Write config file only if it was changed or didn't exist
    if config_updated:
        try:
            with open(config_file, 'w') as f:
                config.write(f)
                print(f"Configuration file saved to {config_file}")
        except Exception as e:
            print(f"Failed to save configuration: {e}")
    
    # Return the configuration, whether it was updated, and the file path
    return config, config_updated, config_file

# Then when you call the function, capture all three return values:
config, config_updated, config_file = initialize_config()

# Define DB_PATH from configuration or use default
DB_PATH = config.get('database', 'path', fallback='pump.db')
DB_IN_MEMORY = config.getboolean('database_performance', 'in_memory', fallback=False)
DB_CACHE_SIZE_MB = config.getint('database_performance', 'cache_size_mb', fallback=75)

# Set db_operations module variables after DB_PATH is defined
from db_operations import set_db_config
if 'set_db_config' in dir():
    try:
        set_db_config(DB_PATH, DB_IN_MEMORY, DB_CACHE_SIZE_MB)
        logger.info(f"Database configuration set: in_memory={DB_IN_MEMORY}, cache_size={DB_CACHE_SIZE_MB}MB")
    except Exception as e:
        logger.error(f"Error setting database configuration: {e}")

# Define a location for lock files
LOCK_FILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'locks')
# Create the directory if it doesn't exist
if not os.path.exists(LOCK_FILE_DIR):
    os.makedirs(LOCK_FILE_DIR, exist_ok=True)

# Set a watchdog timer to force exit if Ctrl+C fails
def setup_exit_watchdog():
    def handler(signum, frame):
        print("\nForce quitting (watchdog triggered)")
    # Register the watchdog to run on SIGINT
    def sigint_watchdog(signum, frame):
        print("\nCtrl+C detected, shutting down...")
        threading.Thread(target=watchdog_exit, daemon=True).start()
        # Let the normal handlers run
        clean_shutdown(signum, frame)
        
    # Override SIGINT handler
    signal.signal(signal.SIGINT, sigint_watchdog)

# Call this function at the end of your imports
setup_exit_watchdog()

# Database queue and thread management
DB_WRITE_QUEUE = queue.Queue()
DB_WRITE_THREAD = None
DB_WRITE_RUNNING = False

# Lock for analysis operations
ANALYSIS_LOCK = threading.Lock()

# Variables for database saving
DB_SAVE_LOCK = threading.Lock()
DB_SAVE_IN_PROGRESS = False
LAST_SAVE_TIME = 0
MIN_SAVE_INTERVAL = 60  # Seconds between saves



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


# Add this function to check if analysis is already running
def is_analysis_running():
    """Check if an analysis is already running based on status"""
    # First, check the status object
    if ANALYSIS_STATUS['running']:
        return True
        
    # Second, check if the lock file exists
    lock_file = os.path.join(LOCK_FILE_DIR, '.analysis_lock')
    if os.path.exists(lock_file):
        try:
            with open(lock_file, 'r') as f:
                pid = int(f.read().strip())
            
            # Try to check if process exists
            try:
                os.kill(pid, 0)  # This will raise an exception if process doesn't exist
                return True
            except OSError:
                # Process doesn't exist, remove stale lock
                os.remove(lock_file)
                return False
        except:
            # Invalid lock file, remove it
            os.remove(lock_file)
            return False
            
    return False

def check_database_stats():
    """Check database statistics for PostgreSQL"""
    try:
        # Get track count
        result = execute_query("SELECT COUNT(*) FROM tracks")
        track_count = result[0][0] if result else 0
        
        # Get size information using PostgreSQL system tables
        result = execute_query("""
            SELECT pg_size_pretty(pg_database_size(current_database())) 
            FROM pg_database 
            WHERE datname = current_database()
        """)
        db_size = result[0][0] if result else "Unknown"
        
        logger.info(f"Database stats: PostgreSQL, Size: {db_size}, Audio files: {track_count}")
        return {
            'db_size': db_size,
            'track_count': track_count
        }
    except Exception as e:
        logger.error(f"Error checking database stats: {e}")
        return None
   

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
    DEFAULT_PLAYLIST_SIZE = config.getint('app', 'default_playlist_size', fallback=10)
    MAX_SEARCH_RESULTS = config.getint('app', 'max_search_results', fallback=50)
    
    logger.info(f"Configuration loaded successfully")
    logger.info(f"Server: {HOST}:{PORT} (debug={DEBUG})")
except Exception as e:
    logger.error(f"Error processing configuration: {e}")
    logger.info("Using default values")
    HOST = '0.0.0.0'
    PORT = 8080
    DEBUG = True
    DEFAULT_PLAYLIST_SIZE = 10
    MAX_SEARCH_RESULTS = 50

# Get cache configuration
CACHE_DIR = config.get('cache', 'image_cache_dir', fallback='album_art_cache')
MAX_CACHE_SIZE_MB = config.getint('cache', 'max_cache_size_mb', fallback=500)




# Create Flask app
app = Flask(__name__)

try:
    # Initialize music analyzer with PostgreSQL compatibility
    analyzer = MusicAnalyzer()  # Don't pass a database path
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


# Add this function to coordinate database saves using your existing functions
def throttled_save_to_disk(force=False):
    """Throttled version of save_memory_db_to_disk with better error handling"""
    global DB_SAVE_IN_PROGRESS, LAST_SAVE_TIME, main_thread_conn
    
    # Only proceed if we're using in-memory mode
    if not DB_IN_MEMORY:
        return False
        
    # Ensure we have a valid connection
    if main_thread_conn is None:
        logger.warning("Cannot save database: main_thread_conn is None")
        return False
        
    # Verify connection is still valid
    try:
        main_thread_conn.execute("SELECT 1")
    except sqlite3.Error:
        logger.error("Cannot save database: main_thread_conn is closed or invalid")
        # Try to recreate the connection
        try:
            from db_operations import get_optimized_connection
            main_thread_conn = get_optimized_connection(
                DB_PATH, in_memory=True, cache_size_mb=DB_CACHE_SIZE_MB, check_same_thread=False
            )
            logger.info("Main thread connection recreated successfully")
        except Exception as conn_error:
            logger.error(f"Failed to recreate main thread connection: {conn_error}")
            return False
    
    # Check if a save is already in progress
    if DB_SAVE_IN_PROGRESS:
        logger.debug("Skipping save - another save is already in progress")
        return False
        
    # Check if we've saved recently (unless forced)
    current_time = time.time()
    if not force and (current_time - LAST_SAVE_TIME) < MIN_SAVE_INTERVAL:
        logger.debug("Skipping save - throttled (last save was less than 60 seconds ago)")
        return False
    
    # Try to acquire lock without blocking
    if not DB_SAVE_LOCK.acquire(blocking=False):
        logger.debug("Skipping save - couldn't acquire lock")
        return False
        
    try:
        DB_SAVE_IN_PROGRESS = True
        logger.info("Saving in-memory database to disk (throttled)...")
        
        # Use your existing function from db_operations
        success = save_memory_db_to_disk(main_thread_conn, DB_PATH)
        
        if (success):
            LAST_SAVE_TIME = current_time
            logger.info("Throttled database save completed successfully")
        else:
            logger.warning("Throttled database save failed")
            
        return success
            
    except Exception as e:
        logger.error(f"Error in throttled database save: {e}")
        return False
    finally:
        DB_SAVE_IN_PROGRESS = False
        DB_SAVE_LOCK.release()

def db_write_worker():
    """Worker thread that processes database write operations serially"""
    global DB_WRITE_RUNNING
    
    DB_WRITE_RUNNING = True
    logger.info("Database write worker started")
    
    try:
        while DB_WRITE_RUNNING:
            try:
                # Get next write operation with timeout
                operation = DB_WRITE_QUEUE.get(timeout=5)
                
                if (operation is None):  # None is a signal to stop
                    logger.info("Received stop signal for DB write worker")
                    break
                    
                # Rest of function remains the same...
                    
                # Unpack the operation
                sql, params, callback = operation
                
                # Use the enhanced function with retries
                from db_operations import execute_with_retry
                result = execute_with_retry(
                    DB_PATH, 
                    sql, 
                    params, 
                    in_memory=DB_IN_MEMORY,
                    cache_size_mb=DB_CACHE_SIZE_MB
                )
                
                # If there's a callback with results
                if callback:
                    callback(result)
                    
                # Mark task as done
                DB_WRITE_QUEUE.task_done()
                
                # Occasionally save memory DB to disk if needed
                if random.random() < 0.01 and DB_IN_MEMORY:  # 1% chance per operation
                    throttled_save_to_disk()
                
            except queue.Empty:
                # Queue timeout, just continue waiting
                pass
                
    except Exception as e:
        logger.error(f"Error in DB write worker: {e}")
    finally:
        DB_WRITE_RUNNING = False
        logger.info("Database write worker stopped")


# Start DB write worker
def start_db_write_worker():
    global DB_WRITE_THREAD, DB_WRITE_RUNNING
    
    # Don't start if already running
    if DB_WRITE_THREAD is not None and DB_WRITE_THREAD.is_alive():
        return
        
    DB_WRITE_RUNNING = True
    DB_WRITE_THREAD = threading.Thread(target=db_write_worker)
    DB_WRITE_THREAD.daemon = True  # Make sure it's a daemon thread
    DB_WRITE_THREAD.start()
    logger.info("Started database write worker thread")

# Call near the end of initialization
start_db_write_worker()

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

# Set main_thread_conn to None by default
main_thread_conn = None

# Create a global connection for in-memory mode
if DB_IN_MEMORY:
    try:
        # PostgreSQL doesn't need special in-memory handling
        main_thread_conn = get_connection()
        logger.info("Database connection initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize in-memory database: {e}")

# Now check the database after the connection is established
logger.info("Checking database stats at startup...")
try:
    db_stats = check_database_stats()
    if (db_stats):
        logger.info(f"Database stats: Size: {db_stats.get('db_size', 'unknown')}, Tracks: {db_stats.get('track_count', 0)}")
    else:
        logger.warning("Database stats check returned no data")
except Exception as e:
    logger.error(f"Error checking database stats at startup: {e}")



# Variable to track if we're already shutting down
_is_shutting_down = False

def ensure_single_instance(process_name):
    """Ensure only one instance of a process is running"""
    # Use LOCK_FILE_DIR instead of DB_PATH directory
    lock_file = os.path.join(LOCK_FILE_DIR, f'.{process_name}_lock')
    
    if os.path.exists(lock_file):
        try:
            with open(lock_file, 'r') as f:
                pid = int(f.read().strip())
            
            # Try to check if process exists
            try:
                os.kill(pid, 0)  # This will raise an exception if process doesn't exist
                logger.warning(f"Another {process_name} process is already running")
                return False
            except OSError:
                # Process doesn't exist, remove stale lock
                os.remove(lock_file)
        except:
            # Invalid lock file, remove it
            if os.path.exists(lock_file):
                os.remove(lock_file)
    
    # Create new lock file
    with open(lock_file, 'w') as f:
        f.write(str(os.getpid()))
    
    return True

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
            # Use throttled_save_to_disk with force=True to ensure it runs
            throttled_save_to_disk(force=True)
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

@app.route('/search')  # Missing route decorator
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


# Replace your current save_db_before_exit function with this improved version
def clean_shutdown(signum=None, frame=None):
    """Improved shutdown handler with timeout and forced exit"""
    global _is_shutting_down, main_thread_conn, DB_WRITE_RUNNING
    
    # Prevent multiple shutdown handlers from running simultaneously
    if _is_shutting_down:
        logger.info("Shutdown already in progress, forcing exit")
        os._exit(0)  # Force immediate exit if called twice
    
    _is_shutting_down = True
    logger.info("Application shutting down gracefully...")
    
    try:
        # Stop background threads first
        DB_WRITE_RUNNING = False
        
        # Signal the queue to stop by adding None
        try:
            DB_WRITE_QUEUE.put(None)  # Signal worker to stop
        except:
            pass
            
        # Only try to save if we have a valid in-memory database
        if DB_IN_MEMORY and main_thread_conn:
            try:
                # Verify connection is still valid before trying to save
                # Use cursor for PostgreSQL connections instead of direct execute
                try:
                    # Check if this is a PostgreSQL connection
                    if hasattr(main_thread_conn, 'cursor'):
                        # PostgreSQL connection - use cursor
                        cursor = main_thread_conn.cursor()
                        cursor.execute("SELECT 1")
                        cursor.close()
                    else:
                        # SQLite connection - direct execute
                        main_thread_conn.execute("SELECT 1")
                        
                    logger.info("Saving in-memory database to disk before exit...")
                    save_memory_db_to_disk(main_thread_conn, DB_PATH)
                    logger.info("Database saved successfully")
                except Exception as conn_err:
                    logger.warning(f"Database connection error: {conn_err}")
            except Exception as e:
                logger.error(f"Error during database shutdown: {e}")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")
    
    # Force exit after short delay if we're handling a signal
    if signum is not None:
        logger.info("Forcing exit in 3 seconds if still running...")
        
        def force_exit():
            logger.info("Forced exit triggered")
            os._exit(0)  # Use os._exit which can't be caught or blocked
        
        # Schedule force exit with shorter timeout (3 seconds)
        t = threading.Timer(3.0, force_exit)
        t.daemon = True  # Make sure the timer itself doesn't block shutdown
        t.start()

# Update your signal handlers
atexit.register(clean_shutdown)
signal.signal(signal.SIGINT, clean_shutdown)
signal.signal(signal.SIGTERM, clean_shutdown)

def update_analysis_progress(files_processed, total_files, current_file, error=None):
    """Update the global analysis status with current progress"""
    global ANALYSIS_STATUS
    
    # Calculate percent complete
    percent = (files_processed / total_files) * 100 if total_files > 0 else 0
    percent = round(percent, 1)
    
    # Update the global status dictionary
    ANALYSIS_STATUS['files_processed'] = files_processed
    ANALYSIS_STATUS['total_files'] = total_files
    ANALYSIS_STATUS['current_file'] = current_file
    ANALYSIS_STATUS['percent_complete'] = percent
    ANALYSIS_STATUS['last_updated'] = datetime.now()
    
    if error:
        ANALYSIS_STATUS['error'] = str(error)
        logger.error(f"Analysis error: {error}")


def analyze_directory_worker(folder_path, recursive):
    """Worker thread that performs analysis with thread-safe DB access"""
    
    # Acquire lock to ensure only one analysis runs at a time
    if not ANALYSIS_LOCK.acquire(blocking=False):
        logger.warning("Another analysis is already running, skipping...")
        return
        
    try:
        # Reset the global status
        global ANALYSIS_STATUS
        ANALYSIS_STATUS = {
            'running': True,
            'start_time': datetime.now(),
            'files_processed': 0,
            'total_files': 0,
            'current_file': '',
            'percent_complete': 0,
            'last_updated': datetime.now(),
            'error': None
        }
        
        logger.info(f"Starting analysis of {folder_path} (recursive={recursive})")
        
        try:
            # Import necessary modules here to avoid circular imports
            import numpy as np
            import librosa
            
            # Create a dummy y variable in case it's needed
            y = None
            
            # Now call the analyzer
            result = analyzer.analyze_directory(folder_path, recursive=recursive)
            
            # Update ANALYSIS_STATUS with result
            if result is None:
                logger.warning("Analysis returned no result - folder may be empty or contain no audio files")
                update_analysis_progress(0, 0, "", "No audio files found or folder is empty")
            else:
                # Handle successful analysis
                files_processed = result.get('files_processed', 0)
                tracks_added = result.get('tracks_added', 0)
                logger.info(f"Analysis complete! Processed {files_processed} files, added {tracks_added} new tracks.")
                
        except NameError as e:
            if "name 'y' is not defined" in str(e):
                logger.error(f"Error running analysis: {e}")
                update_analysis_progress(0, 0, "", "Analysis error: missing audio data variable")
            else:
                logger.error(f"Error running analysis: {e}")
                update_analysis_progress(0, 0, "", str(e))
        except Exception as e:
            logger.error(f"Error running analysis: {e}")
            update_analysis_progress(0, 0, "", str(e))
    finally:
        # Update status when done
        ANALYSIS_STATUS['running'] = False
        ANALYSIS_STATUS['last_updated'] = datetime.now()
        
        # Release the lock
        ANALYSIS_LOCK.release()

# Add after initialize_memory_db() function
def setup_playlist_tables():
    """Create playlist tables if they don't exist"""
    logger.info("Setting up playlist tables")
    try:
        with optimized_connection(DB_PATH, DB_IN_MEMORY, DB_CACHE_SIZE_MB) as conn:
            cursor = conn.cursor()
            
            # Create playlists table with PostgreSQL syntax
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS playlists (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create playlist items table with PostgreSQL syntax
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS playlist_items (
                    id SERIAL PRIMARY KEY,
                    playlist_id INTEGER NOT NULL,
                    track_id INTEGER NOT NULL,
                    position INTEGER NOT NULL,
                    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
                    FOREIGN KEY (track_id) REFERENCES audio_files(id) ON DELETE CASCADE
                )
            ''')
            
            conn.commit()
            
            # Check if tables were created successfully
            cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND (table_name='playlists' OR table_name='playlist_items')")
            tables = cursor.fetchall()
            
            if len(tables) == 2:
                logger.info("Playlist tables created successfully")
                return True
            else:
                logger.warning(f"Not all playlist tables were created. Found: {tables}")
                return False
                
    except Exception as e:
        logger.error(f"Error setting up playlist tables: {e}")
        return False

@app.route('/api/playlists', methods=['GET', 'POST'])
def api_playlists():
    if request.method == 'GET':
        try:
            logger.info("API: Getting all playlists via /api/playlists (GET)")
            
            playlists_data = execute_query_dict(
                """
                SELECT p.id, p.name, p.description, p.created_at, p.updated_at
                FROM playlists p
                ORDER BY p.updated_at DESC
                """
            )
            logger.debug(f"Raw playlists_data from execute_query_dict: {playlists_data}")

            if not playlists_data:
                logger.info("API: No playlists found in database.")
                return jsonify([])

            # Ensure playlists_data is a list of dicts
            if isinstance(playlists_data, list) and len(playlists_data) > 0 and not isinstance(playlists_data[0], dict):
                logger.warning(f"API: execute_query_dict did not return a list of dictionaries. Got: {type(playlists_data[0])}. Attempting conversion.")
                try:
                    # Assuming column order from the SELECT query
                    column_names = ['id', 'name', 'description', 'created_at', 'updated_at']
                    converted_data = []
                    for row_index, row in enumerate(playlists_data):
                        if len(row) == len(column_names):
                            converted_data.append(dict(zip(column_names, row)))
                        else:
                            logger.error(f"API: Row {row_index} has mismatched column count for conversion: {row}")
                            # Add a placeholder or skip
                            converted_data.append({'id': None, 'name': 'Conversion Error', 'description': '', 'track_count': 0})
                    playlists_data = converted_data
                    logger.info("API: Successfully converted playlist data to list of dicts.")
                except Exception as conversion_error:
                    logger.error(f"API: Failed to convert playlist data to dicts: {conversion_error}")
                    return jsonify({'error': 'Internal server error: playlist data format issue'}), 500
            elif not isinstance(playlists_data, list):
                 logger.error(f"API: execute_query_dict did not return a list. Got: {type(playlists_data)}")
                 return jsonify({'error': 'Internal server error: playlist data type issue'}), 500

            processed_playlists = []
            for p_data in playlists_data:
                if not isinstance(p_data, dict):
                    logger.warning(f"API: Skipping track count for non-dict playlist item: {p_data}")
                    # If p_data was from a failed conversion, it might have an ID already
                    if 'id' not in p_data: p_data['id'] = None 
                    if 'name' not in p_data: p_data['name'] = 'Invalid Data'
                    p_data['track_count'] = 0 
                    processed_playlists.append(p_data)
                    continue

                playlist_item_id = p_data.get('id')
                if playlist_item_id is None: # Could happen if conversion failed or ID was genuinely null
                    logger.warning(f"API: Playlist item missing 'id' or id is None: {p_data}")
                    p_data['track_count'] = 0 # Ensure track_count exists
                    # Don't skip, allow it to be returned so frontend can decide based on ID
                    processed_playlists.append(p_data)
                    continue
                
                try:
                    count_query_result = execute_query(
                        "SELECT COUNT(*) FROM playlist_items WHERE playlist_id = %s",
                        (playlist_item_id,)
                    )
                    if count_query_result and len(count_query_result) > 0 and len(count_query_result[0]) > 0:
                        p_data['track_count'] = count_query_result[0][0]
                    else:
                        p_data['track_count'] = 0
                except Exception as count_exc:
                    logger.error(f"API: Error getting track count for playlist_id {playlist_item_id}: {count_exc}")
                    p_data['track_count'] = -1 # Indicate error in count
                processed_playlists.append(p_data)
            
            logger.info(f"API: Found and processed {len(processed_playlists)} playlists")
            return jsonify(processed_playlists)
            
        except Exception as e:
            logger.error(f"API: Error getting playlists: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500
            
    elif request.method == 'POST':
        try:
            data = request.get_json()
            if not data:
                return jsonify({"error": "No data provided"}), 400

            playlist_name = data.get('name')
            playlist_description = data.get('description', '')
            tracks = data.get('tracks', [])

            if not playlist_name:
                return jsonify({"error": "Playlist name is required"}), 400
            
            # Use the optimized_connection context manager
            # Assuming optimized_connection is available and configured for psycopg2
            with optimized_connection() as conn: # Ensure this context manager is correctly set up for psycopg2
                cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
                
                # Create the new playlist
                cursor.execute(
                    "INSERT INTO playlists (name, description) VALUES (%s, %s) RETURNING id",
                    (playlist_name, playlist_description)
                )
                playlist_id = cursor.fetchone()['id']
                
                # Add tracks to the playlist
                for i, track_id in enumerate(tracks):
                    cursor.execute(
                        "INSERT INTO playlist_items (playlist_id, track_id, position) VALUES (%s, %s, %s)",
                        (playlist_id, track_id, i)
                    )
                
                conn.commit()
                    
                return jsonify({
                    "status": "success",
                    "playlist_id": playlist_id,
                    "message": f"Playlist '{playlist_name}' created with {len(tracks)} tracks"
                })
        
        except Exception as e:
            logger.error(f"API: Error saving playlist: {str(e)}") # Changed app.logger to logger
            return jsonify({"error": str(e)}), 500

@app.route('/playlists/<int:playlist_id>', methods=['GET'])
def get_playlist(playlist_id):
    logger.info(f"API: Getting details for playlist_id: {playlist_id}")
    try:
        # Fetch playlist details (id, name, description)
        playlist_query = "SELECT id, name, description, created_at, updated_at FROM playlists WHERE id = %s"
        
        conn = get_connection()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(playlist_query, (playlist_id,))
                playlist_details_row = cur.fetchone()
        finally:
            release_connection(conn)

        if not playlist_details_row:
            logger.warning(f"API: Playlist with id {playlist_id} not found.")
            return jsonify({'error': 'Playlist not found'}), 404

        playlist_data = dict(playlist_details_row)
        logger.debug(f"API: Playlist details fetched: {playlist_data}")

        # Try to fetch and process tracks for the playlist
        try:
            # CORRECTED QUERY: Only included columns that definitely exist according to schema
            tracks_query = """
                SELECT 
                    t.id, t.title, t.artist, t.album, t.duration, t.file_path, t.genre,
                    t.album_art_url, t.year, t.liked,
                    pi.position
                FROM tracks t 
                JOIN playlist_items pi ON t.id = pi.track_id
                WHERE pi.playlist_id = %s
                ORDER BY pi.position
            """
            # Removed last_played which doesn't exist in the schema

            logger.debug(f"API: Executing tracks query for playlist_id {playlist_id} using 'tracks' table.")
            tracks_list_raw = execute_query_dict(tracks_query, (playlist_id,))
            logger.debug(f"API: Raw tracks_list from execute_query_dict for playlist_id {playlist_id}: {str(tracks_list_raw)[:500]} (Type: {type(tracks_list_raw)})")

            if tracks_list_raw is None:
                logger.warning(f"API: No tracks found for playlist_id {playlist_id} (execute_query_dict returned None). Initializing tracks as empty list.")
                playlist_data['tracks'] = []
            elif isinstance(tracks_list_raw, list):
                processed_tracks = []
                if not tracks_list_raw: # Empty list
                    logger.info(f"API: execute_query_dict returned an empty list for tracks in playlist_id {playlist_id}.")
                for track_row in tracks_list_raw:
                    if isinstance(track_row, dict):
                        processed_tracks.append(track_row)
                    elif hasattr(track_row, 'keys'): # Handle DictRow or other dict-like objects
                        processed_tracks.append(dict(track_row))
                    else:
                        logger.warning(f"API: Track item for playlist {playlist_id} is not a dict or DictRow: {type(track_row)}. Skipping.")
                playlist_data['tracks'] = processed_tracks
            elif hasattr(tracks_list_raw, 'keys'): # A single dict-like item (e.g. DictRow) was returned
                logger.info(f"API: tracks_list_raw for playlist {playlist_id} was a single item ({type(tracks_list_raw)}). Processing as one track.")
                playlist_data['tracks'] = [dict(tracks_list_raw)] # Convert to dict and wrap in a list
            else: # tracks_list_raw is some other unexpected type
                logger.error(f"API: tracks_list_raw for playlist {playlist_id} is unexpected type: {type(tracks_list_raw)}. Setting tracks to empty list.")
                playlist_data['tracks'] = []

        except Exception as e_track_processing: 
            logger.error(f"API: Error occurred while fetching or processing tracks for playlist {playlist_id}: {e_track_processing}", exc_info=True)
            playlist_data['tracks'] = [] 

        logger.info(f"API: Responding for playlist {playlist_id} with {len(playlist_data.get('tracks', []))} tracks.")
        return jsonify(playlist_data)

    except KeyError as e: 
        key_error_msg = e.args[0] if e.args else "Unknown Key"
        logger.error(f"API: KeyError encountered in get_playlist for {playlist_id}: '{key_error_msg}'", exc_info=True)
        return jsonify({'error': f"Internal server error (KeyError: '{key_error_msg}')"}), 500
    except Exception as e:
        logger.error(f"API: Unexpected error in get_playlist for {playlist_id}: {str(e)}", exc_info=True)
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

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
def get_recent_tracks():
    """Get recently added tracks"""
    try:
        limit = request.args.get('limit', default=10, type=int)
        
        # Use PostgreSQL-compatible query
        recent_tracks = execute_query_dict(
            """SELECT id, file_path, title, artist, album, album_art_url, date_added, duration 
               FROM tracks 
               ORDER BY date_added DESC 
               LIMIT %s""", 
            (limit,)
        )
        
        # Set default titles
        for track in recent_tracks:
            if not track['title']:
                track['title'] = os.path.basename(track['file_path'])
                
        return jsonify(recent_tracks)
    except Exception as e:
        logger.error(f"Error getting recent tracks: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/tracks/<int:track_id>')
def get_track_info(track_id):
    """Get track information by ID"""
    try:
        # Get track from database
        track = execute_query_row("SELECT * FROM tracks WHERE id = %s", (track_id,))
        
        if not track:
            return jsonify({"error": "Track not found"}), 404
            
        # Return track data as JSON
        return jsonify(track)
    except Exception as e:
        logger.error(f"Error getting track info: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/stream/<int:track_id>')
def stream(track_id):
    try:
        # Get the track information with all metadata
        result = execute_query_row(
            """SELECT t.file_path, t.title, t.artist, t.album, t.album_art_url, t.duration 
               FROM tracks t 
               WHERE t.id = %s""",
            (track_id,)
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
        
        # Add metadata headers for the frontend
        response.headers['X-Track-Id'] = str(track_id)
        response.headers['X-Track-Title'] = result.get('title', os.path.basename(file_path))
        response.headers['X-Track-Artist'] = result.get('artist', 'Unknown Artist')
        response.headers['X-Track-Album'] = result.get('album', 'Unknown Album')
        
        # Include album art URL if available
        if result.get('album_art_url'):
            response.headers['X-Track-Art'] = result.get('album_art_url')
            
        # Include duration if available
        if result.get('duration'):
            response.headers['X-Track-Duration'] = str(result.get('duration'))
        
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
        
        if (artist):
            tracks = execute_query_dict(
                """SELECT id, file_path, title, artist, album, album_art_url, duration
                   FROM tracks
                   WHERE album = %s AND artist = %s
                   ORDER BY title""",
                (album, artist)
            )
        else:
            tracks = execute_query_dict(
                """SELECT id, file_path, title, artist, album, album_art_url, duration
                   FROM tracks
                   WHERE album = %s
                   ORDER BY title""",
                (album,)
            )
        
        return jsonify(tracks)
    except Exception as e:
        logger.error(f"Error getting album tracks: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/library/artists')
def get_artists():
    """Get all artists in the library"""
    try:
        # Use PostgreSQL-compatible query
        artists = execute_query_dict(
            """SELECT DISTINCT artist, 
                  COUNT(*) as track_count,
                  MAX(album_art_url) as artist_image_url
               FROM tracks 
               WHERE artist IS NOT NULL AND artist != ''
               GROUP BY artist 
               ORDER BY artist"""
        )
        
        return jsonify(artists)
    except Exception as e:
        logger.error(f"Error getting artists: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/library/albums')
def get_albums():
    """Get all albums in the library"""
    try:
        # Use PostgreSQL-compatible query
        albums = execute_query_dict(
            """SELECT DISTINCT album, artist, COUNT(*) as track_count,
                   (SELECT album_art_url FROM tracks WHERE album=a.album AND artist=a.artist LIMIT 1) as album_art_url,
                   (SELECT file_path FROM tracks WHERE album=a.album AND artist=a.artist LIMIT 1) as sample_track
            FROM tracks a
            WHERE album IS NOT NULL AND album != ''
            GROUP BY album, artist
            ORDER BY album"""
        )
        
        return jsonify(albums)
    except Exception as e:
        logger.error(f"Error getting albums: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/library/songs')
def get_songs():
    """Get all songs in the library"""
    try:
        # Use PostgreSQL-compatible query
        songs = execute_query_dict(
            """SELECT id, file_path, title, artist, album, album_art_url, duration
               FROM tracks
               ORDER BY title
               LIMIT 50"""
        )
        
        # Set default title for songs without title
        for song in songs:
            if not song.get('title'):
                song['title'] = os.path.basename(song.get('file_path', 'Unknown'))
                
        logger.info(f"Returning {len(songs)} songs for library view")
        return jsonify(songs)
    except Exception as e:
        logger.error(f"Error getting songs: {e}")
        return jsonify([])  # Return empty array instead of error object

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


def run_scheduled_full_analysis():
    """Run full analysis of pending files on schedule"""
    try:
        logger.info("Running scheduled full analysis")
        # Quick scan first to identify new files
        try:
            music_directory = config.get('music', 'folder_path')
            recursive = config.getboolean('music', 'recursive', fallback=True)
            
            if music_directory:
                analyzer = MusicAnalyzer()  # Don't pass DB_PATH parameter here
                analyzer.scan_library(music_directory, recursive)
            else:
                logger.warning("No music directory configured, skipping quick scan")
        except Exception as e:
            logger.error(f"Error running quick scan: {e}")

        # Then full analysis
        try:
            conn = get_connection()
            try:
                cursor = conn.cursor()
                
                # Get count of files with no analysis
                cursor.execute("""
                    SELECT COUNT(*) FROM tracks 
                    WHERE id NOT IN (SELECT track_id FROM audio_features)
                """)
                pending_count = cursor.fetchone()
                
                if (pending_count and pending_count[0] > 0):
                    logger.info(f"Found {pending_count[0]} tracks needing audio analysis")
                    # Start analysis in a background thread
                    analyzer = MusicAnalyzer()
                    analyzer.analyze_pending_files()
            finally:
                release_connection(conn)
        except Exception as e:
            logger.error(f"Error in full analysis: {e}")
            
    except Exception as e:
        logger.error(f"Error in scheduled analysis: {e}")
    
    logger.info("Scheduled full analysis completed")

@app.route('/station/<int:seed_track_id>')
def create_station(seed_track_id):
    """Create a station from a seed track"""
    try:
        # Get number of tracks from query string or default
        num_tracks = request.args.get('num_tracks', 
                                    config.get('app', 'default_playlist_size', fallback=10), 
                                    type=int)
        
        logger.info(f"Creating station with {num_tracks} tracks")
        
        # Get seed track
        seed_track = execute_query_dict(
            "SELECT * FROM tracks WHERE id = %s",
            (seed_track_id,),
            fetchone=True
        )
        
        if not seed_track:
            return jsonify({'error': 'Seed track not found'}), 404
        
        # Get audio features for the seed track
        seed_features = execute_query_dict(
            """SELECT * FROM audio_features WHERE track_id = %s""",
            (seed_track_id,),
            fetchone=True
        )
        
        if not seed_features:
            return jsonify({'error': 'No audio features available for this seed track'}), 400
        
        # Find similar tracks based on audio features
        similar_tracks = execute_query_dict(
            """
            SELECT t.*, af.*
            FROM audio_features af
            JOIN tracks t ON af.track_id = t.id
            WHERE t.id != %s
            ORDER BY 
                POWER(af.energy - %s, 2) +
                POWER(af.danceability - %s, 2) +
                POWER(af.valence - %s, 2) +
                POWER(af.acousticness - %s, 2)
            LIMIT %s
            """,
            (
                seed_track_id, 
                seed_features.get('energy', 0),
                seed_features.get('danceability', 0),
                seed_features.get('valence', 0),
                seed_features.get('acousticness', 0),
                num_tracks - 1  # -1 because we add the seed track at first position
            )
        )
        
        # Add seed track to the beginning of the result set
        station = [seed_track] + similar_tracks
        
        return jsonify(station)
        
    except Exception as e:
        logger.error(f"Error creating station: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/station/<int:seed_track_id>')
def create_station_api(seed_track_id):
    """Create a station from a seed track - API endpoint"""
    try:
        # Get number of tracks from query string or default
        num_tracks = request.args.get('num_tracks', 
                                     config.get('app', 'default_playlist_size', fallback=10), 
                                     type=int)
        
        logger.info(f"Creating station API with {num_tracks} tracks from seed {seed_track_id}")
        
        # Get seed track
        seed_track = execute_query_dict(
            "SELECT * FROM tracks WHERE id = %s",
            (seed_track_id,),
            fetchone=True
        )
        
        if not seed_track:
            logger.error(f"Seed track not found for ID: {seed_track_id}")
            return jsonify({"error": "Seed track not found"}), 404
        
        # Get audio features for the seed track
        seed_features = execute_query_dict(
            """SELECT * FROM audio_features WHERE track_id = %s""",
            (seed_track_id,),
            fetchone=True
        )
        
        if not seed_features:
            logger.error(f"No audio features found for seed track: {seed_track_id}")
            
            # Return a fallback station with random tracks if no audio features
            random_tracks = execute_query_dict(
                """
                SELECT t.*
                FROM tracks t
                WHERE t.id != %s
                ORDER BY RANDOM()
                LIMIT %s
                """,
                (seed_track_id, num_tracks - 1)
            )
            
            station = [seed_track] + random_tracks
            logger.info(f"Created fallback random station with {len(station)} tracks")
            return jsonify(station)
        
        # Find similar tracks based on audio features
        similar_tracks = execute_query_dict(
            """
            SELECT t.*
            FROM audio_features af
            JOIN tracks t ON af.track_id = t.id
            WHERE t.id != %s
            ORDER BY 
                POWER(af.energy - %s, 2) +
                POWER(af.danceability - %s, 2) +
                POWER(af.valence - %s, 2) +
                POWER(af.acousticness - %s, 2)
            LIMIT %s
            """,
            (
                seed_track_id, 
                seed_features.get('energy', 0),
                seed_features.get('danceability', 0),
                seed_features.get('valence', 0),
                seed_features.get('acousticness', 0),
                num_tracks - 1  # -1 because we add the seed track at first position
            )
        )
        
        # Add seed track to the beginning of the result set
        station = [seed_track] + similar_tracks
        logger.info(f"Successfully created station with {len(station)} tracks")
        return jsonify(station)
        
    except Exception as e:
        logger.error(f"Error creating station: {e}")
        return jsonify({'error': str(e)}), 500

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
            logger.error(f"Log file not found: {log_file}")
            return jsonify({"error": "Log file not found"}), 404
        
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                # Use safe approach to read logs in case file is large
                all_lines = []
                for line in f:
                    all_lines.append(line)
                    # Keep only the last 'lines' number of entries
                    if len(all_lines) > lines:
                        all_lines.pop(0)
                log_lines = all_lines
            
            return jsonify({"logs": log_lines})
        except UnicodeDecodeError:
            # Try with different encoding if UTF-8 fails
            logger.warning(f"Unicode decode error, trying with latin-1 encoding")
            with open(log_file, 'r', encoding='latin-1') as f:
                all_lines = []
                for line in f:
                    all_lines.append(line)
                    if len(all_lines) > lines:
                        all_lines.pop(0)
                log_lines = all_lines
            
            return jsonify({"logs": log_lines})
            
    except Exception as e:
        logger.error(f"Error viewing logs: {e}", exc_info=True)
        return jsonify({"error": f"Failed to view logs: {str(e)}"}), 500

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
    try:
        # Add more verbose debugging
        logger.debug(f"Scan library request received: {request.get_data(as_text=True)}")
        
        # Support both JSON and form data
        if request.is_json:
            data = request.get_json()
            logger.debug(f"JSON data received: {data}")
        else:
            data = request.form.to_dict()
            logger.debug(f"Form data received: {data}")
        
        # Get folder path from POST data
        folder_path = data.get('folder_path')
        logger.debug(f"Extracted folder_path: {folder_path}")
        
        # If folder_path is not in the request, try to get it from configuration
        if not folder_path:
            folder_path = config.get('music', 'folder_path', fallback=None)
            logger.debug(f"Using folder_path from config: {folder_path}")
            
            if not folder_path:
                logger.warning("No music folder path specified in request or config")
                return jsonify({
                    'status': 'error',
                    'message': 'No music folder path specified. Please configure a music folder first.'
                }), 400
        
        # Check if folder exists
        if not os.path.exists(folder_path):
            return jsonify({
                'status': 'error',
                'message': f'Music folder not found: {folder_path}'
            }), 404
        
        # Get recursive parameter with proper type handling
        recursive_param = data.get('recursive', True)
        
        # Handle both string and boolean values
        if isinstance(recursive_param, str):
            recursive = recursive_param.lower() in ('true', '1', 't', 'y', 'yes')
        else:
            recursive = bool(recursive_param)
        
        # Start the scan process
        analyzer = MusicAnalyzer()
        result = analyzer.scan_library(folder_path, recursive)
        
        # Return success response
        return jsonify({
            'status': 'success',
            'message': f"Scan complete: {result.get('files_processed', 0)} files processed",
            'files_processed': result.get('files_processed', 0),
            'tracks_added': result.get('tracks_added', 0)
        })
        
    except Exception as e:
        logger.error(f"Error scanning library: {e}")
        return jsonify({
            'status': 'error',
            'message': f"Error scanning library: {str(e)}"
        }), 500

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
def get_analysis_count_status():
    """Get counts of pending, analyzed, and failed tracks"""
    try:
        conn = get_connection()  # Use PostgreSQL connection
        cursor = conn.cursor()
        
        # Get counts for different analysis statuses
        cursor.execute("SELECT COUNT(*) FROM tracks WHERE id NOT IN (SELECT track_id FROM audio_features)")
        pending = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM audio_features")
        analyzed = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM tracks WHERE analysis_error IS NOT NULL")
        failed = cursor.fetchone()[0]
        
        # Make sure to release the connection
        release_connection(conn)
        
        return jsonify({
            'pending': pending,
            'analyzed': analyzed,
            'failed': failed
        })
    except Exception as e:
        logger.error(f"Error getting analysis status: {e}")
        return jsonify({
            'pending': 0,
            'analyzed': 0,
            'failed': 0,
            'error': str(e)
        })

def should_stop():
    global analysis_progress
    return analysis_progress.get('stop_requested', False)

@app.route('/api/settings/save_music_path', methods=['POST'])
def save_music_path():
    """Save music folder path setting"""
    try:
        # Get path from JSON request
        data = request.get_json()
        if not data or 'path' not in data:
            return jsonify({
                'status': 'error',
                'message': 'No path provided'
            }), 400
        
        path = data['path']
        recursive = data.get('recursive', True)
        
        logger.info(f"Saving music path: {path}, recursive: {recursive}")
        
        # Convert to absolute path if it's a relative path
        if not os.path.isabs(path):
            path = os.path.abspath(path)
            logger.info(f"Converted to absolute path: {path}")
            
        # Ensure the path exists, create if needed
        if not os.path.exists(path):
            try:
                os.makedirs(path)
                logger.info(f"Created music directory: {path}")
            except Exception as e:
                return jsonify({
                    'status': 'error',
                    'message': f"Failed to create directory: {str(e)}"
                }), 500
        
        # Update configuration
        config.set('music', 'folder_path', path)
        config.set('music', 'recursive', str(recursive).lower())
        
        # Save to file
        with open('pump.conf', 'w') as f:
            config.write(f)
        
        return jsonify({
            'status': 'success',
            'message': 'Music folder path saved successfully',
            'path': path,
            'recursive': recursive
        })
    except Exception as e:
        logger.error(f"Error saving music path: {e}")
        return jsonify({
            'status': 'error',
            'message': f"Error saving music path: {str(e)}"
        }), 500

@app.route('/api/update-metadata', methods=['POST'])
def update_metadata():
    """Handle metadata update request"""
    try:
        if not metadata_service:
            logger.error("Metadata update failed: Metadata service not available")
            return jsonify({"status": "error", "message": "Metadata service not available"}), 500
            
        # Extract skip_existing from form data with proper debugging
        try:
            skip_existing = request.form.get('skip_existing', 'false') == 'true'
            logger.info(f"Received form data: {dict(request.form)}")
        except Exception as form_error:
            logger.error(f"Error parsing form data: {form_error}")
            # Fallback to JSON if form parsing fails
            data = request.get_json(silent=True) or {}
            skip_existing = data.get('skip_existing', False)
        
        logger.info(f"Metadata update requested with skip_existing={skip_existing}")
        
        # Check if metadata update is already running
        if METADATA_UPDATE_STATUS.get('running', False):
            logger.info("Metadata update already in progress")
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
            'error': None,
            'scan_complete': True  # Add this for UI consistency
        })
        
        # Start metadata update in a background thread
        metadata_thread = threading.Thread(target=run_metadata_update, args=(skip_existing,))
        metadata_thread.daemon = True
        metadata_thread.start()
        
        # Mark database as modified for the request context
        g.db_modified = True
        
        logger.info("Metadata update thread started successfully")
        return jsonify({"status": "started", "message": "Metadata update started"})
    except Exception as e:
        logger.error(f"Error starting metadata update: {e}")
        # Update status with error
        METADATA_UPDATE_STATUS.update({
            'running': False,
            'error': str(e),
            'last_updated': datetime.now().isoformat()
        })
        return jsonify({"status": "error", "message": str(e)}), 500

# Add this function to run metadata update in background
def run_metadata_update(skip_existing=False):
    """Run metadata update in a background thread"""
    try:
        if not metadata_service:
            logger.error("Cannot update metadata: Metadata service not available")
            return
            
        # Run metadata update
        logger.info(f"Starting metadata update (skip_existing={skip_existing})")
        result = metadata_service.update_all_metadata(status_tracker=METADATA_UPDATE_STATUS, skip_existing=skip_existing)
        
        # Update final status
        METADATA_UPDATE_STATUS.update({
            'running': False,
            'percent_complete': 100,
            'last_updated': datetime.now().isoformat()
        })
        

        
        logger.info(f"Metadata update completed successfully: {result.get('processed', 0)} processed, {result.get('updated', 0)} updated")
        
    except Exception as e:
        logger.error(f"Error updating metadata: {e}")
        # Update status with error
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
def metadata_update_status():
    """Get the current status of a metadata update"""
    try:
        is_running = METADATA_UPDATE_STATUS['running']
        
        # Calculate elapsed time if running
        elapsed_seconds = 0
        if is_running and METADATA_UPDATE_STATUS['start_time']:
            try:
                # Handle both string and datetime start_time
                if isinstance(METADATA_UPDATE_STATUS['start_time'], str):
                    start_time = datetime.fromisoformat(METADATA_UPDATE_STATUS['start_time'])
                else:
                    start_time = METADATA_UPDATE_STATUS['start_time']
                    
                elapsed = datetime.now() - start_time
                elapsed_seconds = elapsed.total_seconds()
            except Exception as e:
                logger.error(f"Error calculating elapsed time: {e}")
            
        # Calculate estimated time remaining
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
def get_analysis_status():
    """Get the current analysis status"""
    try:
        # Create a copy of the status to avoid race conditions
        status = dict(ANALYSIS_STATUS)
        
        # Ensure proper percent calculation - don't show 100% unless actually complete
        if status.get('running') == False and status.get('error') is not None:
            # If there was an error and not running, calculate actual percentage
            if status.get('total_files', 0) > 0:
                status['percent_complete'] = min(99, round((status.get('files_processed', 0) / status.get('total_files', 0)) * 100, 1))
            else:
                status['percent_complete'] = 0
        
        # Convert datetime objects to ISO format strings or handle None values
        if status.get('start_time') is not None:
            if isinstance(status['start_time'], datetime):
                status['start_time'] = status['start_time'].isoformat()
        
        if status.get('last_updated') is not None:
            if isinstance(status['last_updated'], datetime):
                status['last_updated'] = status['last_updated'].isoformat()
        
        return jsonify(status)
    except Exception as e:
        logger.error(f"Error getting analysis status: {e}")
        return jsonify({
            'running': False,
            'error': f"Failed to get status: {str(e)}"
        })

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
        

            
        logger.info(f"Quick scan completed successfully. Processed {result.get('processed', 0)} files, added {result.get('added', 0)} tracks.")
        
    except Exception as e:
        logger.error(f"Error running quick scan: {e}")
        # Update status with error
        QUICK_SCAN_STATUS.update({
            'running': False,
            'error': str(e),
            'last_updated': datetime.now().isoformat()
        })
        


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
            throttled_save_to_disk()
            
        return result
    except Exception as e:
        logger.error(f"Error running scheduled quick scan: {e}")
        return False


def create_similar_playlist(seed_track_id, limit=10):
    """Create a playlist of similar tracks based on audio features"""
    try:
        # Get seed track features
        seed_features = execute_query_dict(
            """
            SELECT af.* 
            FROM audio_features af
            WHERE af.track_id = %s
            """,
            (seed_track_id,),
            fetchone=True
        )
        
        if not seed_features:
            return []
            
        # Find similar tracks based on audio features
        similar_tracks = execute_query_dict(
            """
            SELECT t.*, af.*
            FROM tracks t
            JOIN audio_features af ON t.id = af.track_id
            WHERE t.id != %s
            ORDER BY 
                POWER(af.energy - %s, 2) +
                POWER(af.danceability - %s, 2) +
                POWER(af.valence - %s, 2) +
                POWER(af.acousticness - %s, 2)
            LIMIT %s
            """,
            (
                seed_track_id, 
                seed_features.get('energy', 0),
                seed_features.get('danceability', 0),
                seed_features.get('valence', 0),
                seed_features.get('acousticness', 0),
                limit
            )
        )
        
        return similar_tracks
    except Exception as e:
        logger.error(f"Error creating similar playlist: {e}")
        return []


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
            throttled_save_to_disk()
            
        return True
    except Exception as e:
        logger.error(f"Error running scheduled full analysis: {e}")
        return False

def run_startup_actions():
    """Run configured startup actions when the app starts"""
    if not ensure_single_instance('startup_actions'):
        logger.warning("Another startup process is running, skipping")
        return
        
    # Prevent duplicate startup actions
    if is_analysis_running() or QUICK_SCAN_STATUS['running'] or METADATA_UPDATE_STATUS['running']:
        logger.warning("Background tasks already running, skipping startup actions")
        return
        
    action = config.get('scheduler', 'startup_action', fallback='nothing')
    
    if (action == 'nothing'):
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
    """Add a 'liked' column to the tracks table if it doesn't exist"""
    try:
        logger.info("Adding 'liked' column to tracks table")
        # Use direct execute_write function instead of connection/DB_PATH
        execute_write(
            "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS liked BOOLEAN DEFAULT FALSE"
        )
        return True
    except Exception as e:
        logger.error(f"Error setting up liked tracks column: {e}")
        return False

# Then call it during app initialization (add this near where you create your app)
with app.app_context():
    setup_liked_tracks_column()

# Add these routes for liked tracks functionality

@app.route('/api/liked-tracks')
def get_liked_tracks():
    """Get all liked tracks"""
    try:
        # Use PostgreSQL-compatible query
        liked_tracks = execute_query_dict(
            """SELECT id, file_path, title, artist, album, album_art_url, duration, liked 
               FROM tracks 
               WHERE liked = TRUE 
               ORDER BY title"""
        )
        
        # Set default titles
        for track in liked_tracks:
            if not track['title']:
                track['title'] = os.path.basename(track['file_path'])
                
        return jsonify(liked_tracks)
    except Exception as e:
        logger.error(f"Error getting liked tracks: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/tracks/<int:track_id>/like', methods=['POST'])
def like_track(track_id):
    """Toggle like status for a track"""
    try:
        # Query current like status
        track = execute_query_dict(
            "SELECT liked FROM tracks WHERE id = %s", 
            (track_id,), 
            fetchone=True
        )
        
        if not track:
            return jsonify({"error": "Track not found"}), 404
        
        # Toggle the liked status
        new_status = not track.get('liked', False)
        
        # Update the track
        execute_write(
            "UPDATE tracks SET liked = %s WHERE id = %s",
            (new_status, track_id)
        )
        
        return jsonify({
            'status': 'success',
            'liked': new_status
        })
    except Exception as e:
        logger.error(f"Error updating liked status: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/tracks/<int:track_id>/liked')
def is_track_liked(track_id):
    """Check if a track is liked"""
    try:
        track = execute_query_dict(
            "SELECT liked FROM tracks WHERE id = %s",
            (track_id,),
            fetchone=True
        )
        
        if not track:
            return jsonify({"error": "Track not found"})
            
        return jsonify({"liked": track.get('liked', False)})
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
    """Create database indexes for better performance"""
    try:
        logger.info("Creating database indexes")
        
        # Use transaction_context from db_operations
        conn = get_connection()
        try:
            with conn.cursor() as cursor:
                # Create indexes for tracks table
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(album)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_title ON tracks(title)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_date_added ON tracks(date_added)")
                
                # First check if playlist_items table exists
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = 'playlist_items'
                    )
                """)
                table_exists = cursor.fetchone()[0]
                
                # Only create indexes if the table exists
                if table_exists:
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_playlist_items_playlist_id ON playlist_items(playlist_id)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_playlist_items_track_id ON playlist_items(track_id)")
                    
            conn.commit()
            logger.info("Database indexes created successfully")
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            release_connection(conn)
        return True
    except Exception as e:
        logger.error(f"Error creating database indexes: {e}")
        return False

# Then call it directly during app initialization:
# Add this near line 270-300 where you initialize other components
create_indexes()

# Add this route

@app.route('/api/db-status')
def get_db_status():
    """Get database performance statistics"""
    try:
        stats = check_database_stats()
        
        return jsonify({
            'db_size_mb': stats['db_size'],
            'track_count': stats['track_count'],
            'environment': {
                'python_version': sys.version,
                'working_directory': os.getcwd()
            }
        })
            
    except Exception as e:
        logger.error(f"Error getting DB status: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/tracks/<int:track_id>/playlist')
def get_track_playlists(track_id):
    """Get all playlists containing a specific track"""
    try:
        playlists = execute_query_dict(
            """
            SELECT p.id, p.name, p.description, p.created_at
            FROM playlists p
            JOIN playlist_items pi ON p.id = pi.playlist_id
            WHERE pi.track_id = %s
            ORDER BY p.name
            """,
            (track_id,)
        )
        
        return jsonify(playlists)
    except Exception as e:
        logger.error(f"Error getting playlists for track {track_id}: {e}")
        return jsonify({'error': str(e)}), 500

def print_database_schema():
    """
    Print the database schema to the logs at startup
    This helps with troubleshooting column name and table structure issues
    """
    logger.info("Printing database schema for troubleshooting")
    
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cursor:
                # Get list of tables
                cursor.execute("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema='public' AND table_type='BASE TABLE'
                    ORDER BY table_name
                """)
                
                tables = [row[0] for row in cursor.fetchall()]
                logger.info(f"Database tables: {tables}")
                
                # For each table, get column information
                for table in tables:
                    cursor.execute(f"""
                        SELECT column_name, data_type, is_nullable
                        FROM information_schema.columns
                        WHERE table_schema='public' AND table_name='{table}'
                        ORDER BY ordinal_position
                    """)
                    
                    columns = cursor.fetchall()
                    logger.info(f"Table '{table}' structure:")
                    for col in columns:
                        col_name, col_type, nullable = col
                        logger.info(f"  - {col_name} ({col_type}, {'NULL' if nullable == 'YES' else 'NOT NULL'})")
        finally:
            release_connection(conn)
            
        return True
    except Exception as e:
        logger.error(f"Error printing database schema: {e}")
        return False

# Call the function early in the initialization to help with troubleshooting
print_database_schema()

@app.route('/albumart/<path:image_url>')
def album_art_proxy(image_url):
    """
    Proxy for album art URLs. This handles album art URLs that are external links
    by either redirecting to them or downloading and serving them.
    """
    try:
        logger.debug(f"Album art request for: {image_url}")
        
        # Check if URL is properly formatted
        if not image_url.startswith('http'):
            # If it doesn't start with http, it might be URL encoded
            try:
                from urllib.parse import unquote
                decoded_url = unquote(image_url)
                if decoded_url.startswith('http'):
                    image_url = decoded_url
            except Exception as e:
                logger.error(f"Error decoding URL: {e}")
                
        # For LastFM and other trusted sources, just redirect
        if 'lastfm' in image_url or 'spotify' in image_url:
            logger.debug(f"Redirecting to external album art: {image_url}")
            return redirect(image_url)
        
        # For other sources, we might want to download and cache
        # But for now, just redirect to everything
        return redirect(image_url)
        
    except Exception as e:
        logger.error(f"Error handling album art proxy request: {e}")
        # Return default album art
        return send_file('static/images/default-album-art.png', mimetype='image/jpeg')

@app.route('/api/db-diagnostic')
def db_diagnostic():
    """Return database diagnostics for PostgreSQL"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Get PostgreSQL version
        cursor.execute("SELECT version();")
        version = cursor.fetchone()[0]
        
        # Get database size
        cursor.execute("SELECT pg_size_pretty(pg_database_size(current_database())) as size")
        size_info = cursor.fetchone()
        
        # Get table counts 
        tables_query = """
            SELECT table_name, 
                   (SELECT count(*) FROM information_schema.columns WHERE table_name=t.table_name) as column_count
            FROM information_schema.tables t
            WHERE table_schema='public' AND table_type='BASE TABLE'
            ORDER BY table_name;
        """
        cursor.execute(tables_query)
        table_info = cursor.fetchall()
        
        # Build table structure
        tables = []
        counts = {}
        
        for table in table_info:
            table_name = table[0]
            column_count = table[1]
            
            # Count rows in this table
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            row_count = cursor.fetchone()[0]
            
            tables.append({
                'name': table_name,
                'columns': column_count,
                'rows': row_count
            })
            
            counts[table_name] = row_count
        
        release_connection(conn)
        
        return jsonify({
            'postgres_version': version,
            'database': {
                'name': conn.info.dbname,
                'size_pretty': size_info[0] if size_info else '0 KB'
            },
            'tables': tables,
            'counts': counts,
            'environment': {
                'python_version': sys.version,
                'working_directory': os.getcwd()
            }
        })
    except Exception as e:
        logger.error(f"Error in db diagnostic: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/explore')
def explore_view():
    """Handle explore view requests (playlists, discover, etc)"""
    logger.info("Explore view requested")
    
    # Return the main index page with view=explore parameter
    # The frontend JavaScript will handle showing the right content
    return render_template('index.html', view='explore')

@app.route('/api/analysis/database-status', methods=['GET'])
def get_analysis_database_status():
    """Get database analysis status (how many tracks are analyzed vs pending)"""
    try:
        # Get counts from database
        analyzed_count = execute_query_row(
            "SELECT COUNT(*) as count FROM tracks WHERE analysis_status = 'analyzed'"
        )['count']
        
        pending_count = execute_query_row(
            "SELECT COUNT(*) as count FROM tracks WHERE analysis_status = 'pending'"
        )['count']
        
        failed_count = execute_query_row(
            "SELECT COUNT(*) as count FROM tracks WHERE analysis_status = 'failed'"
        )['count']
        
        total_count = execute_query_row(
            "SELECT COUNT(*) as count FROM tracks"
        )['count']
        
        return jsonify({
            'status': 'success',
            'analyzed': analyzed_count,
            'pending': pending_count,
            'failed': failed_count,
            'total': total_count
        })
    except Exception as e:
        logger.error(f"Error getting database analysis status: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/api/discover')
def discover_tracks():
    """Return a selection of tracks for the Discover view"""
    try:
        logger.info("API: Discover tracks requested")
        
        # Initialize an empty list for each category
        dance_tracks = []
        recent_tracks = []
        random_tracks = []
        
        # Try to get some tracks with high danceability if audio features exist
        try:
            dance_tracks = execute_query_dict(
                """
                SELECT t.* FROM tracks t
                JOIN audio_features af ON t.id = af.track_id
                WHERE af.danceability > 0.7
                ORDER BY RANDOM()
                LIMIT 5
                """
            ) or []
            logger.debug(f"Retrieved {len(dance_tracks)} dance tracks")
        except Exception as dance_error:
            logger.warning(f"Failed to get dance tracks: {dance_error}")
            # Continue execution even if this query fails
        
        # Get some recently added tracks
        try:
            recent_tracks = execute_query_dict(
                """
                SELECT * FROM tracks
                ORDER BY date_added DESC
                LIMIT 10
                """
            ) or []
            logger.debug(f"Retrieved {len(recent_tracks)} recent tracks")
        except Exception as recent_error:
            logger.warning(f"Failed to get recent tracks: {recent_error}")
        
        # Get a few random tracks for variety
        try:
            random_tracks = execute_query_dict(
                """
                SELECT * FROM tracks
                ORDER BY RANDOM()
                LIMIT 15
                """
            ) or []
            logger.debug(f"Retrieved {len(random_tracks)} random tracks")
        except Exception as random_error:
            logger.warning(f"Failed to get random tracks: {random_error}")
        
        # Combine all tracks and remove duplicates by ID
        all_tracks = {}
        for track in dance_tracks + recent_tracks + random_tracks:
            if track and 'id' in track and track['id'] not in all_tracks:
                # Ensure all tracks have the expected fields
                processed_track = {
                    'id': track.get('id'),
                    'title': track.get('title', 'Unknown Title'),
                    'artist': track.get('artist', 'Unknown Artist'),
                    'album': track.get('album', 'Unknown Album'),
                    'album_art_url': track.get('album_art_url'),
                    'file_path': track.get('file_path', ''),
                    'duration': track.get('duration', 0),
                    'liked': bool(track.get('liked', False))
                }
                all_tracks[track['id']] = processed_track
        
        discover_tracks = list(all_tracks.values())
        
        logger.info(f"API: Returning {len(discover_tracks)} tracks for discover view")
        return jsonify(discover_tracks)
    except Exception as e:
        logger.error(f"API: Error in discover tracks: {e}", exc_info=True)
        return jsonify([])  # Return empty array instead of error for better UI handling

@app.route('/settings')
def settings():
    """Settings page for the web player"""
    logger.info("Settings page requested")
    
    # Get current settings from config file
    try:
        library_path = config.get('library', 'path', fallback='')
        music_directory = config.get('library', 'music_directory', fallback='')
        rescan_interval = config.get('library', 'rescan_interval', fallback='60')
        debug_mode = config.get('app', 'debug', fallback='False') == 'True'
        log_level = config.get('app', 'log_level', fallback='INFO')
        
        settings_data = {
            'library_path': library_path,
            'music_directory': music_directory,
            'rescan_interval': rescan_interval,
            'debug_mode': debug_mode,
            'log_level': log_level
        }
        
        return render_template('settings.html', settings=settings_data)
    except Exception as e:
        logger.error(f"Error loading settings page: {e}", exc_info=True)
        return render_template('settings.html', settings={}, error=str(e))

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

