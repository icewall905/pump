import logging
import sqlite3
from typing import Dict, List, Tuple, Any, Optional, Callable
from contextlib import contextmanager
from db_utils import optimized_connection, get_optimized_connection
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
    """Execute a SELECT query and return a single row as dictionary or None"""
    with optimized_connection(db_path, in_memory=in_memory, cache_size_mb=cache_size_mb) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            cursor.execute(query, params)
            row = cursor.fetchone()
            return dict(row) if row else None
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
        # Call the reset function from db_utils
        from db_utils import reset_database_locks
        reset_success = reset_database_locks()
        
        # Additional cleanup for transaction contexts
        # (Add any specific cleanup needed)
        
        return reset_success
    except Exception as e:
        logger.error(f"Error resetting database connections: {e}")
        return False

def optimized_connection(db_path, in_memory=False, cache_size_mb=75):
    """Context manager that provides an optimized SQLite connection"""
    conn = get_optimized_connection(db_path, in_memory, cache_size_mb)
    try:
        yield conn
    finally:
        conn.close()

def get_optimized_connection(db_path, in_memory=False, cache_size_mb=75):
    """Get an optimized SQLite connection with performance settings"""
    # If in-memory mode is requested but no global connection exists
    if in_memory and hasattr(_thread_local, 'conn'):
        return _thread_local.conn
        
    # Regular file-based connection
    conn = sqlite3.connect(db_path)
    
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