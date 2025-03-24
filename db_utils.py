import sqlite3
import os
import threading
import logging
from contextlib import contextmanager

logger = logging.getLogger('db_utils')

# Thread-local storage for database connections
_thread_local = threading.local()

def get_optimized_connection(db_path, in_memory=False, cache_size_mb=75, check_same_thread=True):
    """
    Create an optimized SQLite connection with performance settings.
    
    Args:
        db_path (str): Path to the SQLite database
        in_memory (bool): If True, load database into memory
        cache_size_mb (int): Size of SQLite cache in MB
        check_same_thread (bool): Whether to enforce thread checking
        
    Returns:
        sqlite3.Connection: Optimized database connection
    """
    if in_memory:
        # For in-memory mode, we need to handle thread safety differently
        # We'll use a shared cache approach with URI connection string
        conn = sqlite3.connect('file::memory:?cache=shared', 
                             uri=True, 
                             check_same_thread=check_same_thread)
        
        # If the file exists, load its contents into memory
        if os.path.exists(db_path):
            try:
                # Load the database content into memory
                disk_conn = sqlite3.connect(db_path)
                disk_conn.backup(conn)
                disk_conn.close()
                logger.info(f"Loaded database {db_path} into memory")
            except Exception as e:
                logger.error(f"Error loading database into memory: {e}")
    else:
        # Create a file-based connection
        conn = sqlite3.connect(db_path, check_same_thread=check_same_thread)
    
    # Apply optimizations
    conn.execute(f"PRAGMA cache_size = -{cache_size_mb * 1024}")  # Convert MB to KB
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute(f"PRAGMA mmap_size = {cache_size_mb * 1024 * 1024}")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    
    # Enable foreign keys
    conn.execute("PRAGMA foreign_keys = ON")
    
    return conn

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
    This creates a new connection in the current thread.
    """
    try:
        # Open a disk database connection in this thread
        disk_conn = sqlite3.connect(db_path)
        
        # Back up the in-memory database to disk
        memory_conn.backup(disk_conn)
        
        # Close the disk connection
        disk_conn.close()
        
        logger.info("In-memory database successfully saved to disk")
        return True
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