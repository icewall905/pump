import sqlite3
import os
import threading
import logging
from contextlib import contextmanager

logger = logging.getLogger('db_utils')

# Thread-local storage for database connections
_thread_local = threading.local()

def get_optimized_connection(db_path, in_memory=False, cache_size_mb=75, check_same_thread=True):
    """Get an optimized SQLite connection with performance settings."""
    try:
        # For in-memory database
        if in_memory:
            conn = sqlite3.connect('file::memory:?cache=shared', 
                                  uri=True, 
                                  check_same_thread=check_same_thread)
            
            # Load database content into memory if not already loaded
            if not getattr(sqlite3, '_pump_db_loaded', False):
                # Check if the disk database exists
                if os.path.exists(db_path):
                    # Load from disk to memory
                    disk_conn = sqlite3.connect(db_path)
                    disk_conn.backup(conn)
                    disk_conn.close()
                    sqlite3._pump_db_loaded = True
                    logger.info(f"Loaded database {db_path} into memory")
                else:
                    logger.warning(f"In-memory mode requested but database file {db_path} not found")
        else:
            # Regular disk-based connection
            conn = sqlite3.connect(db_path, check_same_thread=check_same_thread)
        
        # Add this line to wait instead of failing on locks (30 seconds)
        conn.execute("PRAGMA busy_timeout = 30000")
        
        # Memory optimization
        conn.execute(f"PRAGMA cache_size = {-1 * cache_size_mb * 1024}")
        
        # Other optimizations
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA temp_store = MEMORY")
        
        # WAL mode for better concurrency
        if not in_memory:
            conn.execute("PRAGMA journal_mode = WAL")
            
        return conn
    except Exception as e:
        logger.error(f"Error creating database connection: {e}")
        # Fallback to a basic connection
        return sqlite3.connect(db_path, check_same_thread=check_same_thread)

@contextmanager
def optimized_connection(db_path, in_memory=False, cache_size_mb=75):
    """Context manager for optimized SQLite connections"""
    # Get thread ID for debugging
    thread_id = threading.get_ident()
    
    # For in-memory mode we'll reuse the same connection per thread
    if in_memory:
        if not hasattr(_thread_local, 'conn'):
            _thread_local.conn = get_optimized_connection(
                db_path, in_memory=True, cache_size_mb=cache_size_mb)
            logger.debug(f"Created new in-memory connection for thread {thread_id}")
        conn = _thread_local.conn
    else:
        conn = get_optimized_connection(db_path, in_memory=False, cache_size_mb=cache_size_mb)
    
    try:
        yield conn
    finally:
        if not in_memory:
            conn.close()

def save_memory_db_to_disk(memory_conn, db_path):
    """
    Save in-memory database to disk safely from any thread.
    """
    try:
        # Make sure we have a valid memory connection
        if not memory_conn:
            logger.error("Cannot save null memory connection to disk")
            return False
            
        # Make a backup of the existing file if it exists
        if os.path.exists(db_path):
            backup_path = f"{db_path}.bak"
            try:
                import shutil
                shutil.copy2(db_path, backup_path)
                logger.info(f"Created backup of database at {backup_path}")
            except Exception as e:
                logger.warning(f"Could not create database backup: {e}")
        
        try:
            # Open a new connection to disk database
            disk_conn = sqlite3.connect(db_path)
            
            # Reset any problematic PRAGMA settings
            disk_conn.execute("PRAGMA journal_mode=DELETE")
            disk_conn.execute("PRAGMA synchronous=FULL")
            
            # First, vacuum the disk database to ensure it's in good shape
            disk_conn.execute("VACUUM")
            disk_conn.commit()
            
            # Close and reopen to ensure clean state
            disk_conn.close()
            disk_conn = sqlite3.connect(db_path)
            
            # Perform the backup without any active transactions
            memory_conn.backup(disk_conn)
            
            # Ensure data is committed
            disk_conn.commit()
            
            # Close the connection
            disk_conn.close()
            
            # Verify the file exists and has a reasonable size
            file_size = os.path.getsize(db_path)
            logger.info(f"Database successfully saved to disk (size: {file_size / 1024:.1f} KB)")
            return True
            
        except Exception as e:
            logger.error(f"Error during database save operation: {e}")
            return False
            
    except Exception as e:
        logger.error(f"Error saving in-memory database to disk: {e}")
        return False

def trigger_db_save(memory_conn, db_path):
    """Save in-memory database to disk from background threads"""
    if memory_conn:
        try:
            logger.info("Saving in-memory database to disk from background task...")
            save_memory_db_to_disk(memory_conn, db_path)
            logger.info("Background task database save complete")
            return True
        except Exception as e:
            logger.error(f"Error saving in-memory database from background task: {e}")
            return False
    return False

def execute_with_retry(conn, query, params=None, max_retries=5, retry_delay=0.1):
    """Execute a query with retry logic for database locks"""
    retries = 0
    while retries < max_retries:
        try:
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            return cursor
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and retries < max_retries - 1:
                retries += 1
                time.sleep(retry_delay * (2 ** retries))  # Exponential backoff
                logger.warning(f"Database locked, retrying ({retries}/{max_retries})...")
            else:
                raise

def with_transaction(conn, func, *args, max_retries=5, retry_delay=0.1, **kwargs):
    """
    Execute a function within a transaction with retry logic for lock errors
    
    Args:
        conn: SQLite connection
        func: Function to execute within transaction
        *args: Arguments to pass to func
        max_retries: Maximum number of retries on lock
        retry_delay: Initial delay between retries (doubles each retry)
        **kwargs: Keyword arguments to pass to func
    
    Returns:
        Result of func
    """
    retries = 0
    while retries < max_retries:
        try:
            conn.isolation_level = None  # Start manual transaction management
            conn.execute('BEGIN IMMEDIATE')  # Get exclusive lock
            
            try:
                result = func(conn, *args, **kwargs)
                conn.execute('COMMIT')
                return result
            except Exception as e:
                conn.execute('ROLLBACK')
                raise e
                
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and retries < max_retries - 1:
                retries += 1
                # Exponential backoff with jitter
                sleep_time = retry_delay * (2 ** retries) * (0.5 + random.random())
                logger.warning(f"Database locked, retrying ({retries}/{max_retries}) after {sleep_time:.2f}s...")
                time.sleep(sleep_time)
            else:
                raise
        finally:
            conn.isolation_level = ''  # Reset to default
            
    raise sqlite3.OperationalError(f"Database still locked after {max_retries} retries")

def save_db_at_exit():
    logger.info("Application shutting down. Saving in-memory database to disk...")
    check_database_stats(DB_PATH, DB_IN_MEMORY, main_thread_conn)
    save_memory_db_to_disk(main_thread_conn, DB_PATH)
    check_database_stats(DB_PATH)  # Check disk DB after save

def check_database_stats(db_path, in_memory=False, memory_conn=None):
    """Check database statistics to verify data existence"""
    try:
        if in_memory and memory_conn:
            conn = memory_conn
        else:
            conn = sqlite3.connect(db_path)
        
        cursor = conn.cursor()
        
        # Get table counts
        cursor.execute("SELECT COUNT(*) FROM audio_files")
        audio_files_count = cursor.fetchone()[0]
        
        try:
            cursor.execute("SELECT COUNT(*) FROM audio_features")
            features_count = cursor.fetchone()[0]
        except:
            features_count = 0
        
        # Get storage info if it's a disk DB
        if not in_memory:
            file_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
            logger.info(f"Database stats: {db_path}, Size: {file_size/1024:.1f} KB, Audio files: {audio_files_count}, Features: {features_count}")
        else:
            logger.info(f"In-memory database stats: Audio files: {audio_files_count}, Features: {features_count}")
        
        if not in_memory:
            conn.close()
            
        return audio_files_count
    except Exception as e:
        logger.error(f"Error checking database stats: {e}")
        return 0

def import_disk_db_to_memory(memory_conn, db_path):
    """Import the disk database into an existing memory connection"""
    try:
        if os.path.exists(db_path):
            disk_conn = sqlite3.connect(db_path)
            disk_conn.backup(memory_conn)
            disk_conn.close()
            logger.info(f"Successfully imported {db_path} into memory connection")
            return True
        else:
            logger.warning(f"Cannot import: database file {db_path} not found")
            return False
    except Exception as e:
        logger.error(f"Error importing database from disk to memory: {e}")
        return False