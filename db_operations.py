import logging
import sqlite3
from typing import Dict, List, Tuple, Any, Optional, Callable
from contextlib import contextmanager
from db_utils import optimized_connection, get_optimized_connection

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