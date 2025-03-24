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
                raise
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

def execute_with_retry(db_path, query, params=(), max_attempts=5, in_memory=False, cache_size_mb=75, return_results=False):
    """Execute a database query with retry logic for handling locks"""
    import time
    import random
    
    for attempt in range(1, max_attempts + 1):
        try:
            with optimized_connection(db_path, in_memory=in_memory, cache_size_mb=cache_size_mb) as conn:
                conn.row_factory = sqlite3.Row if return_results else None
                cursor = conn.cursor()
                cursor.execute(query, params)
                
                # Handle different return types based on the operation
                if return_results:
                    results = cursor.fetchall()
                    conn.commit()
                    return [dict(row) for row in results]
                else:
                    conn.commit()
                    return cursor.rowcount
                
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < max_attempts:
                # Calculate backoff with jitter
                sleep_time = (2 ** attempt) * 0.1 + (random.random() * 0.1)
                logger.warning(f"Database locked, retry {attempt}/{max_attempts} after {sleep_time:.2f}s")
                time.sleep(sleep_time)
            else:
                logger.error(f"Database error after {attempt} attempts: {e}")
                raise
                
        except Exception as e:
            logger.error(f"Error executing query: {e}")
            raise
    
    # If we get here, all retries failed
    raise sqlite3.OperationalError(f"Failed to execute query after {max_attempts} attempts")