import os
from db_operations import optimized_connection
import sqlite3

def check_database():
    db_path = "music_features.db"
    
    # Check if database file exists
    if not os.path.exists(db_path):
        print(f"Database file '{db_path}' does not exist!")
        return
    
    print(f"Database file '{db_path}' exists (size: {os.path.getsize(db_path)} bytes)")
    
    # Connect to the database using optimized_connection context manager
    with optimized_connection(db_path) as conn:
        cursor = conn.cursor()
        
        # Check tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        print(f"Tables in database: {[table[0] for table in tables]}")
        
        # Check audio_files table
        try:
            cursor.execute("SELECT COUNT(*) FROM audio_files")
            count = cursor.fetchone()[0]
            print(f"Number of entries in audio_files table: {count}")
            
            if count > 0:
                cursor.execute("SELECT * FROM audio_files LIMIT 5")
                rows = cursor.fetchall()
                print("Sample audio_files entries:")
                for row in rows:
                    print(f"  {row}")
        except sqlite3.OperationalError as e:
            print(f"Error querying audio_files: {e}")
        
        # Check audio_features table
        try:
            cursor.execute("SELECT COUNT(*) FROM audio_features")
            count = cursor.fetchone()[0]
            print(f"Number of entries in audio_features table: {count}")
            
            if count > 0:
                cursor.execute("SELECT * FROM audio_features LIMIT 5")
                rows = cursor.fetchall()
                print("Sample audio_features entries:")
                for row in rows:
                    print(f"  {row}")
        except sqlite3.OperationalError as e:
            print(f"Error querying audio_features: {e}")

if __name__ == "__main__":
    check_database()