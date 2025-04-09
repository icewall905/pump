# Replace all DB_PATH references with database connection handling

# For setting up liked tracks column
def setup_liked_tracks_column():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Check if the column exists
        cursor.execute("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'tracks' AND column_name = 'liked'
        """)
        
        if not cursor.fetchone():
            cursor.execute("""
                ALTER TABLE tracks ADD COLUMN liked BOOLEAN DEFAULT FALSE
            """)
            conn.commit()
            logger.info("Added 'liked' column to tracks table")
        
        release_connection(conn)
        return True
    except Exception as e:
        logger.error(f"Error setting up liked tracks column: {e}")
        return False

# For creating database indexes
def create_database_indexes():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Create common indexes for performance
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_tracks_title ON tracks(title)",
            "CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist)",
            "CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(album)",
            "CREATE INDEX IF NOT EXISTS idx_audio_features_track_id ON audio_features(track_id)"
        ]
        
        for index_sql in indexes:
            cursor.execute(index_sql)
        
        conn.commit()
        release_connection(conn)
        logger.info("Database indexes created successfully")
        return True
    except Exception as e:
        logger.error(f"Error creating database indexes: {e}")
        return False