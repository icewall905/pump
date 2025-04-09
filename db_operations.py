import logging
import sqlite3
from typing import Dict, List, Tuple, Any, Optional, Callable
from contextlib import contextmanager
import os
import threading
import time
import random
import shutil

# Thread-local storage for database connections
_thread_local = threading.local()

# Database paths - these can be set by the application
DB_PATH = None
DB_IN_MEMORY = False
DB_CACHE_SIZE_MB = 75


logger = logging.getLogger('db_operations')

def execute_query_dict(db_path: str, query: str, params: Tuple = (), in_memory: bool = False, 
                      cache_size_mb: int = 75) -> List[Dict]:
    """Execute a SELECT query and return results as dictionaries using Row factory"""
    results = []
    with optimized_connection(db_path, in_memory=in_memory, cache_size_mb=cache_size_mb) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            cursor.execute(query, params)
            results = [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Database query error: {e}, Query: {query}")
            raise
    return results

def execute_query_row(db_path: str, query: str, params: Tuple = (), in_memory: bool = False, 
                     cache_size_mb: int = 75) -> Optional[Dict]:
    """Execute a query and return the first row as a dictionary"""
    with optimized_connection(db_path, in_memory=in_memory, cache_size_mb=cache_size_mb) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            cursor.execute(query, params)
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        except sqlite3.Error as e:
            logger.error(f"Database query error: {e}, Query: {query}")
            raise

def execute_query(db_path: str, query: str, params: Tuple = (), in_memory: bool = False, 
                 cache_size_mb: int = 75) -> List[Tuple]:
    """Execute a SELECT query and return results as tuples"""
    results = []
    with optimized_connection(db_path, in_memory=in_memory, cache_size_mb=cache_size_mb) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(query, params)
            results = cursor.fetchall()
        except sqlite3.Error as e:
            logger.error(f"Database query error: {e}, Query: {query}")
            raise
    return results

def execute_write(db_path: str, query: str, params: Tuple = (), in_memory: bool = False,
                 cache_size_mb: int = 75) -> int:
    """Execute a write operation (INSERT, UPDATE, DELETE) and return affected row count or last row ID"""
    with optimized_connection(db_path, in_memory=in_memory, cache_size_mb=cache_size_mb) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN")
            cursor.execute(query, params)
            row_id = cursor.lastrowid
            conn.commit()
            return row_id
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Database write error: {e}, Query: {query}")
            raise

def execute_batch(db_path: str, query: str, param_list: List[Tuple], in_memory: bool = False,
                 cache_size_mb: int = 75) -> int:
    """Execute a batch of write operations with the same query but different parameters"""
    with optimized_connection(db_path, in_memory=in_memory, cache_size_mb=cache_size_mb) as conn:
        cursor = conn.cursor()
        count = 0
        try:
            cursor.execute("BEGIN")
            for params in param_list:
                cursor.execute(query, params)
                count += 1
            conn.commit()
            return count
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Database batch error: {e}, Query: {query}")
            raise

@contextmanager
def transaction_context(db_path: str, in_memory: bool = False, cache_size_mb: int = 75):
    """Create a transaction context with auto-commit/rollback"""
    with optimized_connection(db_path, in_memory=in_memory, cache_size_mb=cache_size_mb) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN")
            yield conn, cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Transaction error: {e}")
            raise

def validate_database_schema():
    """Verify database tables and create them if missing"""
    try:
        # Check if audio_files table exists
        result = execute_query(
            DB_PATH,
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audio_files'",
            in_memory=DB_IN_MEMORY,
            cache_size_mb=DB_CACHE_SIZE_MB
        )
        
        if not result:
            logger.warning("Database tables missing - initializing fresh database")
            # Call initialization function here
        else:
            logger.info("Database schema validated")
            
    except Exception as e:
        logger.error(f"Error validating database schema: {e}")

def execute_with_retry(db_path: str, query: str, params: Tuple = (), max_attempts=5, 
                      in_memory: bool = False, cache_size_mb: int = 75, 
                      operation_type="write") -> Any:
    """Execute a database operation with retry logic for handling locks"""
    import time
    import random
    
    for attempt in range(1, max_attempts + 1):
        try:
            if operation_type == "write":
                return execute_write(db_path, query, params, in_memory, cache_size_mb)
            elif operation_type == "query_dict":
                return execute_query_dict(db_path, query, params, in_memory, cache_size_mb)
            elif operation_type == "query_row":
                return execute_query_row(db_path, query, params, in_memory, cache_size_mb)
            elif operation_type == "query":
                return execute_query(db_path, query, params, in_memory, cache_size_mb)
            else:
                raise ValueError(f"Unknown operation type: {operation_type}")
                
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < max_attempts:
                # Calculate backoff with jitter
                sleep_time = (2 ** attempt) * 0.1 + (random.random() * 0.1)
                logger.warning(f"Database locked, retry {attempt}/{max_attempts} after {sleep_time:.2f}s")
                time.sleep(sleep_time)
            else:
                logger.error(f"Database error after {attempt} attempts: {e}")
                raise
                
    # If we get here, all retries failed
    raise sqlite3.OperationalError(f"Failed to execute query after {max_attempts} attempts")

def reset_connections():
    """Reset any active database connections and clear locks"""
    try:
        # Use the local function instead of importing
        reset_success = reset_database_locks()
        
        # Additional cleanup for transaction contexts
        # (Add any specific cleanup needed)
        
        return reset_success
    except Exception as e:
        logger.error(f"Error resetting database connections: {e}")
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

def get_optimized_connection(db_path, in_memory=False, cache_size_mb=75, check_same_thread=True):
    """Get an optimized SQLite connection with performance settings"""
    # If in-memory mode is requested and a connection exists in thread-local storage
    if in_memory and hasattr(_thread_local, 'conn'):
        return _thread_local.conn
        
    # Regular file-based connection
    conn = sqlite3.connect(db_path, check_same_thread=check_same_thread)
    
    # Optimize connection
    conn.execute(f"PRAGMA cache_size = {cache_size_mb * 1024}")  # Convert MB to KB
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA mmap_size = 30000000")
    
    # If this is an in-memory connection, store it in thread local storage
    if in_memory:
        _thread_local.conn = conn
        
    return conn

def validate_connection_state(conn):
    """Verify connection is still valid and open"""
    if conn is None:
        return False
        
    try:
        # Try a simple operation to verify connection is active
        conn.execute("SELECT 1")
        return True
    except sqlite3.Error:
        return False

def get_or_create_connection(db_path, in_memory=False, cache_size_mb=75):
    """Get existing connection or create a new one if needed"""
    if in_memory and hasattr(_thread_local, 'conn'):
        # Verify connection is still valid
        if validate_connection_state(_thread_local.conn):
            return _thread_local.conn
        else:
            # Connection is invalid, remove it
            delattr(_thread_local, 'conn')
    
    # Create new connection
    conn = get_optimized_connection(db_path, in_memory, cache_size_mb)
    return conn

def save_memory_db_to_disk(memory_conn, db_path):
    """Save in-memory database to disk file"""
    try:
        # Make sure we have a connection
        if not memory_conn:
            logger.error("Cannot save database: Memory connection is None")
            return False
            
        # Create backup of existing file
        if os.path.exists(db_path):
            backup_path = f"{db_path}.bak"
            try:
                shutil.copy2(db_path, backup_path)
                logger.debug(f"Created backup at {backup_path}")
            except Exception as e:
                logger.warning(f"Failed to create backup: {e}")
        
        # Create a new disk database connection
        try:
            # Use the backup API for robust saving
            with sqlite3.connect(db_path) as disk_conn:
                memory_conn.backup(disk_conn)
                logger.info(f"In-memory database successfully saved to {db_path}")
                return True
                
        except Exception as e:
            logger.error(f"Error during database save operation: {e}")
            return False
            
    except Exception as e:
        logger.error(f"Error saving in-memory database to disk: {e}")
        return False

def trigger_db_save(conn, db_path):
    """Force save the in-memory database to disk."""
    try:
        logger.info("Saving in-memory database to disk from background task...")
        
        # Check if connection is None
        if conn is None:
            logger.error("Cannot save database: Connection is None")
            return False
        
        # Create a new disk database connection
        disk_conn = sqlite3.connect(db_path)
        
        try:
            # First attempt: Use the connection's iterdump
            for line in conn.iterdump():
                if line not in ("BEGIN;", "COMMIT;"):  # Skip transaction statements
                    disk_conn.execute(line)
            
            # Ensure changes are committed
            disk_conn.commit()
            logger.info("In-memory database successfully saved to disk")
        except Exception as e:
            logger.error(f"Error during database dump: {e}")
            # Try backup method as fallback
            try:
                conn.backup(disk_conn)
                logger.info("Database saved using backup method")
            except Exception as backup_error:
                logger.error(f"Backup method also failed: {backup_error}")
                return False
        finally:
            disk_conn.close()
            
        logger.info("Background task database save complete")
        return True
    except Exception as e:
        logger.error(f"Error saving in-memory database to disk: {e}")
        return False

def import_disk_db_to_memory(memory_conn, db_path):
    """Import a disk database into an in-memory database"""
    try:
        # Check if memory_conn is valid
        if not memory_conn:
            logger.error("Memory connection is None")
            return False
            
        # Check if disk database exists
        if not os.path.exists(db_path):
            logger.error(f"Disk database does not exist: {db_path}")
            return False
            
        # Create a new disk connection
        disk_conn = sqlite3.connect(db_path)
        
        try:
            # Copy all data from disk to memory
            disk_conn.backup(memory_conn)
            logger.info(f"Loaded database {db_path} into memory")
            return True
        finally:
            disk_conn.close()
    except Exception as e:
        logger.error(f"Error importing disk database to memory: {e}")
        return False

def import_disk_db_to_memory_with_timeout(memory_conn, db_path, timeout_seconds=30):
    """Import a disk database into memory with a timeout to prevent deadlocks"""
    import threading
    import time
    
    result = {"success": False, "error": None}
    
    def import_worker():
        try:
            # Check if memory_conn is valid
            if not memory_conn:
                result["error"] = "Memory connection is None"
                return
                
            # Check if disk database exists
            if not os.path.exists(db_path):
                result["error"] = f"Disk database does not exist: {db_path}"
                return
                
            # Create a new disk connection
            disk_conn = sqlite3.connect(db_path)
            
            try:
                # Copy all data from disk to memory
                disk_conn.backup(memory_conn)
                logger.info(f"Loaded database {db_path} into memory")
                result["success"] = True
            finally:
                disk_conn.close()
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Error importing disk database to memory: {e}")
    
    # Create and start worker thread
    import_thread = threading.Thread(target=import_worker)
    import_thread.daemon = True
    import_thread.start()
    
    # Wait for completion with timeout
    start_time = time.time()
    while import_thread.is_alive():
        if time.time() - start_time > timeout_seconds:
            logger.error(f"Database import timed out after {timeout_seconds} seconds")
            return False
        time.sleep(0.1)
    
    # Check result
    if result["success"]:
        return True
    else:
        if result["error"]:
            logger.error(f"Import failed: {result['error']}")
        return False

def reset_database_locks():
    """Reset any stuck database locks by closing connections"""
    try:
        # Close any thread-local connections
        if hasattr(_thread_local, 'conn'):
            try:
                _thread_local.conn.close()
            except:
                pass
            delattr(_thread_local, 'conn')
        
        # If using WAL mode, try to checkpoint the database
        if DB_PATH and os.path.exists(DB_PATH):
            try:
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute("PRAGMA wal_checkpoint(FULL)")
            except:
                pass
                
        return True
    except Exception as e:
        logger.error(f"Error resetting database locks: {e}")
        return False

def initialize_database(db_path):
    """Initialize the database with all required tables and indexes"""
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            
            # Create audio_files table with all needed columns
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS audio_files (
                id INTEGER PRIMARY KEY,
                file_path TEXT UNIQUE,
                title TEXT,
                artist TEXT,
                album TEXT,
                genre TEXT,
                duration REAL,
                date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_played TIMESTAMP,
                play_count INTEGER DEFAULT 0,
                album_art_url TEXT,
                artist_image_url TEXT,
                metadata_source TEXT DEFAULT 'local_file',
                analysis_status TEXT DEFAULT 'pending', 
                liked INTEGER DEFAULT 0
            )''')
            
            # Create audio_features table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS audio_features (
                id INTEGER PRIMARY KEY,
                file_id INTEGER,
                tempo REAL,
                key INTEGER,
                mode INTEGER,
                time_signature INTEGER,
                energy REAL,
                danceability REAL,
                brightness REAL,
                noisiness REAL,
                loudness REAL,
                date_analyzed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (file_id) REFERENCES audio_files(id)
            )''')
            
            # Create playlists tables
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS playlists (
                id INTEGER PRIMARY KEY,
                name TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS playlist_items (
                id INTEGER PRIMARY KEY,
                playlist_id INTEGER,
                track_id INTEGER,
                position INTEGER,
                FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
                FOREIGN KEY (track_id) REFERENCES audio_files(id)
            )''')
            
            # Create indexes for better performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_path ON audio_files(file_path)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_artist ON audio_files(artist)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_album ON audio_files(album)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_title ON audio_files(title)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_id ON audio_features(file_id)")
            
            conn.commit()
            logger.info(f"Database {db_path} initialized successfully with all tables and indexes")
            return True
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        return False