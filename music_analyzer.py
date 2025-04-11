from typing import Dict, List, Tuple, Union, Optional
from pathlib import Path
import os
import numpy as np
import pandas as pd
import librosa
import sqlite3
import argparse
import logging
import threading
import time
import mutagen
from datetime import datetime
from lastfm_service import LastFMService
from spotify_service import SpotifyService
from metadata_service import MetadataService
from db_operations import get_connection, release_connection, execute_query_dict
from db_operations import optimized_connection, transaction_context, execute_query_row, execute_write
from db_operations import execute_query  # Add this import for execute_query

# Initialize logger
logger = logging.getLogger(__name__)

# Global variables to track analysis progress
analysis_thread = None
analysis_progress = {
    'is_running': False,
    'total_files': 0,
    'current_file_index': 0,
    'analyzed_count': 0,
    'failed_count': 0,
    'pending_count': 0,
    'last_run_completed': False,
    'stop_requested': False
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
    'error': None,
    'scan_complete': False
}

# Add near other global variables
scan_mutex = threading.Lock()

class MusicAnalyzer:
    """Class for analyzing audio files and extracting features"""
    
    def __init__(self, db_path=None, in_memory=False, cache_size_mb=75):
        """Initialize the analyzer with database path"""
        # These parameters are kept for compatibility but not used with PostgreSQL
        self.db_path = None  # Not used with PostgreSQL
        self.in_memory = False  # Not applicable to PostgreSQL
        self.cache_size_mb = 75  # Not applicable to PostgreSQL
        
        # Create database connection for this instance
        self.db_conn = get_connection()
        
        # Initialize database tables if they don't exist
        self._ensure_tables_exist()
        
        try:
            self.lastfm_service = LastFMService()
            self.spotify_service = SpotifyService()
            self.metadata_service = MetadataService()
        except Exception as e:
            logger.error(f"Error initializing services: {e}")
        
    def _initialize_db(self):
        """Initialize the database with necessary tables"""
        try:
            with optimized_connection(self.db_path, in_memory=self.in_memory, cache_size_mb=self.cache_size_mb) as conn:
                cursor = conn.cursor()
                
                # Create audio_files table if it doesn't exist
                cursor.execute('''
                CREATE TABLE IF NOT EXISTS audio_files (
                    id INTEGER PRIMARY KEY,
                    file_path TEXT UNIQUE,
                    title TEXT,
                    artist TEXT,
                    album TEXT,
                    duration REAL,
                    date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata_source TEXT,
                    album_art_url TEXT,
                    artist_image_url TEXT,
                    analysis_status TEXT DEFAULT 'pending',
                    liked INTEGER DEFAULT 0
                )
                ''')
                
                # Create audio_features table if it doesn't exist
                cursor.execute('''
                CREATE TABLE IF NOT EXISTS audio_features (
                    file_id INTEGER PRIMARY KEY,
                    tempo REAL,
                    key INTEGER,
                    mode INTEGER,
                    time_signature INTEGER,
                    energy REAL,
                    danceability REAL,
                    brightness REAL,
                    noisiness REAL,
                    loudness REAL,
                    FOREIGN KEY (file_id) REFERENCES audio_files (id) ON DELETE CASCADE
                )
                ''')
                
                # Check if the loudness column exists, if not add it
                cursor.execute("PRAGMA table_info(audio_features)")
                columns = [row[1] for row in cursor.fetchall()]
                if 'loudness' not in columns:
                    cursor.execute("ALTER TABLE audio_features ADD COLUMN loudness REAL")
                    logger.info("Added 'loudness' column to audio_features table")
                
                # Create playlists tables if they don't exist
                cursor.execute('''
                CREATE TABLE IF NOT EXISTS playlists (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                ''')
                
                cursor.execute('''
                CREATE TABLE IF NOT EXISTS playlist_items (
                    id INTEGER PRIMARY KEY,
                    playlist_id INTEGER NOT NULL,
                    track_id INTEGER NOT NULL,
                    position INTEGER NOT NULL,
                    FOREIGN KEY (playlist_id) REFERENCES playlists (id) ON DELETE CASCADE,
                    FOREIGN KEY (track_id) REFERENCES audio_files (id),
                    UNIQUE(playlist_id, track_id)
                )
                ''')
                
                # Ensure in-memory database changes are saved immediately after schema setup
                if self.in_memory:
                    from db_operations import trigger_db_save
                    trigger_db_save(conn, self.db_path)
                    logger.info("Schema changes saved to disk")
                    
                logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise

    def _ensure_tables_exist(self):
        """Ensure all required tables exist in the database"""
        try:
            with self.db_conn.cursor() as cursor:
                # Check and create tracks table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS tracks (
                        id SERIAL PRIMARY KEY,
                        file_path TEXT UNIQUE,
                        title TEXT,
                        artist TEXT,
                        album TEXT,
                        genre TEXT,
                        year INTEGER,
                        duration FLOAT,
                        sample_rate INTEGER,
                        bit_rate INTEGER,
                        channels INTEGER,
                        album_art_url TEXT,
                        date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        liked BOOLEAN DEFAULT FALSE,
                        analysis_status TEXT DEFAULT 'pending'
                    )
                """)
                
                # Check and create audio_features table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS audio_features (
                        track_id INTEGER PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
                        tempo FLOAT,
                        key INTEGER,
                        brightness FLOAT,
                        energy FLOAT,
                        danceability FLOAT,
                        acousticness FLOAT,
                        instrumentalness FLOAT,
                        valence FLOAT,
                        loudness FLOAT,
                        mode INTEGER,
                        time_signature INTEGER,
                        analysis_version TEXT
                    )
                """)
                
                self.db_conn.commit()
        except Exception as e:
            logger.error(f"Error ensuring tables exist: {e}")
            self.db_conn.rollback()
        
    def analyze_file(self, file_path: str, save_to_db: bool = True) -> Dict:
        """
        Analyze a music file and extract its features, but skip if it's already in the database.
        """
        conn = None
        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            # Check if file has already been analyzed
            cursor.execute("SELECT id FROM tracks WHERE file_path = %s", (file_path,))
            row = cursor.fetchone()
            
            if row is not None:
                # Already in database, skip analysis
                track_id = row[0]
                logger.info(f"Track already in database (id={track_id}): {file_path}")
                return {"id": track_id, "file_path": file_path, "status": "already_exists"}
            
            # If not found in DB, proceed with analysis
            # First, get metadata from the file itself
            metadata = self.metadata_service.get_metadata_from_file(file_path)

            # Next, try to enhance metadata from online services
            enhanced_metadata = self.metadata_service.enrich_metadata(metadata)

            # Load the audio file for analysis
            y, sr = librosa.load(file_path, sr=None)

            # Basic audio properties
            duration = librosa.get_duration(y=y, sr=sr)

            # Extract features
            features = {
                "file_path": file_path,
                "duration": duration,
                "title": enhanced_metadata.get("title", ""),
                "artist": enhanced_metadata.get("artist", ""),
                "album": enhanced_metadata.get("album", ""),
                "album_art_url": enhanced_metadata.get("album_art_url", ""),
                "metadata_source": enhanced_metadata.get("metadata_source", "unknown"),
                **self._extract_time_domain_features(y, sr),
                **self._extract_frequency_domain_features(y, sr),
                **self._extract_rhythm_features(y, sr),
                **self._extract_harmonic_features(y, sr)
            }

            # Fetch artist image if available (LastFM > Spotify fallback)
            artist_image_url = None
            if features["artist"]:
                if self.lastfm_service:
                    artist_image_url = self.lastfm_service.get_artist_image_url(features["artist"])
                if not artist_image_url and self.spotify_service:
                    artist_image_url = self.spotify_service.get_artist_image_url(features["artist"])

            features["artist_image_url"] = artist_image_url

            if save_to_db:
                self._save_to_db(features)

            return features

        except Exception as e:
            logger.error(f"Error analyzing file {file_path}: {e}")
            return {"error": str(e), "file_path": file_path, "status": "error"}
        finally:
            if conn:
                release_connection(conn)
    
    def scan_library(self, directory: str, recursive: bool = True, 
                     extensions: List[str] = ['.mp3', '.wav', '.flac', '.ogg'], 
                     batch_size: int = 100):
        """
        Analyze audio files in a directory using batch processing for DB checks.
        """
        logger.info(f"Starting quick scan of {directory} (recursive={recursive})")
        
        # Collect audio files
        audio_files = []
        
        if recursive:
            for root, dirs, files in os.walk(directory):
                for file in files:
                    if any(file.lower().endswith(ext) for ext in extensions):
                        audio_files.append(os.path.join(root, file))
        else:
            if os.path.exists(directory):
                for file in os.listdir(directory):
                    file_path = os.path.join(directory, file)
                    if os.path.isfile(file_path) and any(file.lower().endswith(ext) for ext in extensions):
                        audio_files.append(file_path)
        
        logger.info(f"Found {len(audio_files)} audio files to process")
        
        # Early return if no files found
        if not audio_files:
            logger.info(f"Quick scan complete! Processed 0 files, added 0 new tracks.")
            return {
                'files_processed': 0,
                'tracks_added': 0
            }
        
        # Process files in batches using the optimized connection
        files_processed = 0
        tracks_added = 0
        
        for i in range(0, len(audio_files), batch_size):
            batch = audio_files[i:i+batch_size]
            
            # Extract file paths for this batch
            file_paths = [path for path in batch]
            
            # Check which files are already in the database using a cursor
            conn = get_connection()
            try:
                with conn.cursor() as cursor:
                    # Convert list to string for SQL IN clause with proper escaping
                    placeholders = ','.join(['%s'] * len(file_paths))
                    
                    if placeholders:  # Only query if we have files
                        query = f"SELECT file_path FROM tracks WHERE file_path IN ({placeholders})"
                        cursor.execute(query, file_paths)
                        existing_files = {row[0] for row in cursor.fetchall()}
                    else:
                        existing_files = set()
                
                # Process files that aren't in the database
                new_files = [path for path in file_paths if path not in existing_files]
                
                for file_path in new_files:
                    try:
                        # Extract and save basic metadata
                        metadata = self._get_basic_metadata(file_path)
                        if metadata:
                            # Insert using execute_write
                            execute_write(
                                """
                                INSERT INTO tracks 
                                (file_path, title, artist, album, genre, year, duration)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (file_path) DO NOTHING
                                """, 
                                (
                                    file_path, 
                                    metadata.get('title', os.path.basename(file_path)),
                                    metadata.get('artist', 'Unknown Artist'),
                                    metadata.get('album', 'Unknown Album'),
                                    metadata.get('genre', ''),
                                    metadata.get('year', None),
                                    metadata.get('duration', 0)
                                )
                            )
                            tracks_added += 1
                    except Exception as e:
                        logger.error(f"Error processing file {file_path}: {e}")
                
                files_processed += len(batch)
                # Log progress
                if i % (batch_size * 5) == 0:
                    logger.info(f"Processed {files_processed}/{len(audio_files)} files, added {tracks_added} new tracks")
                    
            except Exception as e:
                logger.error(f"Error during batch processing: {e}")
            finally:
                release_connection(conn)
        
        logger.info(f"Quick scan complete! Processed {files_processed} files, added {tracks_added} new tracks.")
        return {
            'files_processed': files_processed,
            'tracks_added': tracks_added
        }
    
    def create_station(self, seed_track_path: str, num_tracks: int = 10) -> List[str]:
        """
        Create a music station based on a seed track.
        """
        # Get the seed track ID
        seed_track_rows = execute_query(
            self.db_path,
            "SELECT id FROM audio_files WHERE file_path = ?",
            (seed_track_path,),
            in_memory=self.in_memory,
            cache_size_mb=self.cache_size_mb
        )
        
        if not seed_track_rows:
            # If not in database, analyze it
            seed_features = self.analyze_file(seed_track_path)
            seed_track_id = None
        else:
            seed_track_id = seed_track_rows[0][0]
            # Get seed track features
            seed_feature_rows = execute_query(
                self.db_path,
                '''SELECT tempo, key, mode, energy, danceability, brightness, loudness
                   FROM audio_features 
                   WHERE file_id = ?''',
                (seed_track_id,),
                in_memory=self.in_memory,
                cache_size_mb=self.cache_size_mb
            )
            
            if seed_feature_rows:
                # Convert to dictionary with column names
                columns = ['tempo', 'key', 'mode', 'energy', 'danceability', 'brightness', 'loudness']
                seed_features = {columns[i]: seed_feature_rows[0][i] for i in range(len(columns))}
                print(f"Using seed track features from database: {seed_features}")
            else:
                print(f"Warning: No audio features found for seed track. Run analysis first.")
                return [seed_track_path]
        
        # Get all other tracks with their features
        other_tracks = execute_query(
            self.db_path,
            '''SELECT af.file_path, ft.tempo, ft.key, ft.mode, ft.energy, ft.danceability, ft.brightness, ft.loudness
               FROM audio_files af
               JOIN audio_features ft ON af.id = ft.file_id
               WHERE af.file_path != ?''',
            (seed_track_path,),
            in_memory=self.in_memory,
            cache_size_mb=self.cache_size_mb
        )
        
        if not other_tracks:
            return [seed_track_path]  # Return only seed track if no others available
        
        # Calculate similarity to seed track for each track
        similarities = []
        for track in other_tracks:
            # Convert to dictionary with column names
            columns = ['file_path', 'tempo', 'key', 'mode', 'energy', 'danceability', 'brightness', 'loudness']
            track_dict = {columns[i]: track[i] for i in range(len(columns))}
            similarity = self._calculate_similarity(seed_features, track_dict)
            similarities.append((track[0], similarity))
        
        # Sort by similarity (descending) and get top tracks
        similarities.sort(key=lambda x: x[1], reverse=True)
        station_tracks = [seed_track_path] + [t[0] for t in similarities[:num_tracks-1]]
        
        logger.info(f"Top track similarities: {similarities[:3]}")
        return station_tracks
        
    def _calculate_similarity(self, features1: Dict, features2: Dict) -> float:
        """
        Calculate similarity between two tracks based on their features.
        
        This is a simplified implementation. Production systems would use more 
        sophisticated similarity measures or machine learning models.
        """
        # Define feature weights
        weights = {
            'tempo': 0.3,
            'key': 0.1,
            'mode': 0.1,
            'energy': 0.15,
            'danceability': 0.25,
            'brightness': 0.1
        }
        
        similarity = 0.0
        
        # Tempo similarity (allow some deviation)
        tempo_diff = abs(features1.get('tempo', 0) - features2.get('tempo', 0))
        tempo_sim = max(0, 1 - tempo_diff/50)  # Normalize by 50 BPM difference
        similarity += weights['tempo'] * tempo_sim
        
        # Key similarity (circular distance on the circle of fifths)
        key_diff = min((features1.get('key', 0) - features2.get('key', 0)) % 12, 
                       (features2.get('key', 0) - features1.get('key', 0)) % 12)
        key_sim = 1 - (key_diff / 6)  # Maximum distance is 6 steps
        similarity += weights['key'] * key_sim
        
        # Mode similarity (binary - same or different)
        mode_sim = 1 if features1.get('mode', -1) == features2.get('mode', -2) else 0
        similarity += weights['mode'] * mode_sim
        
        # Continuous features similarity
        for feature in ['energy', 'danceability', 'brightness']:
            if feature in features1 and feature in features2:
                diff = abs(features1[feature] - features2[feature])
                feat_sim = max(0, 1 - diff)
                similarity += weights.get(feature, 0) * feat_sim
        
        return similarity

    def _analyze_file_without_db_check(self, file_path: str) -> Dict:
        """Analyze a file without checking the DB (used by batch processing)"""
        try:
            # Get metadata from the file itself
            metadata = self.metadata_service.get_metadata_from_file(file_path)
            
            # Try to enhance metadata from online services
            enhanced_metadata = self.metadata_service.enrich_metadata(metadata)
            
            # Load the audio file for analysis
            try:
                y, sr = librosa.load(file_path, sr=None)
            except Exception as e:
                logger.error(f"Error loading audio file {file_path}: {e}")
                y, sr = None, None

            # Ensure y and sr are defined before proceeding
            if y is None or sr is None:
                logger.warning(f"Skipping analysis for {file_path} due to missing audio data")
                return {
                    "file_path": file_path,
                    "title": enhanced_metadata.get("title", ""),
                    "artist": enhanced_metadata.get("artist", ""),
                    "album": enhanced_metadata.get("album", ""),
                    "album_art_url": enhanced_metadata.get("album_art_url", ""),
                    "metadata_source": enhanced_metadata.get("metadata_source", "unknown"),
                    "duration": 0,
                    "error": "Could not load audio data"
                }
            
            # Basic audio properties
            duration = librosa.get_duration(y=y, sr=sr)
            
            # Extract features - use the extract methods we just defined
            features = {
                "file_path": file_path,
                "duration": duration,
                "title": enhanced_metadata.get("title", ""),
                "artist": enhanced_metadata.get("artist", ""),
                "album": enhanced_metadata.get("album", ""),
                "album_art_url": enhanced_metadata.get("album_art_url", ""),
                "metadata_source": enhanced_metadata.get("metadata_source", "unknown"),
                **self._extract_time_domain_features(y, sr),
                **self._extract_frequency_domain_features(y, sr),
                **self._extract_rhythm_features(y, sr),
                **self._extract_harmonic_features(y, sr)
            }
            
            return features
            
        except Exception as e:
            logger.error(f"Error analyzing file {file_path}: {e}")
            # Return error object with meaningful fields
            return {
                "file_path": file_path,
                "error": str(e),
                "tempo": 0,
                "key": 0,
                "mode": 0,
                "time_signature": 4,
                "energy": 0,
                "danceability": 0.5,
                "brightness": 0,
                "noisiness": 0
            }
    
    def analyze_directory(self, directory: str, recursive: bool = True) -> None:
        """
        Analyze all audio files in a directory that have 'pending' status
        
        Args:
            directory: Path to the music directory
            recursive: Whether to scan recursively
        """
        global analysis_progress
        
        logger.info(f"Starting analysis of {directory} (recursive={recursive})")
        
        # Update progress
        analysis_progress['is_running'] = True
        analysis_progress['total_files'] = 0
        analysis_progress['current_file_index'] = 0
        analysis_progress['analyzed_count'] = 0
        analysis_progress['failed_count'] = 0
        analysis_progress['stop_requested'] = False
        
        # Update status
        from web_player import ANALYSIS_STATUS
        
        try:
            # Get all pending files from database
            cursor = self.db_conn.cursor()
            
            if recursive:
                # Use recursive path matching with wildcards
                query = "SELECT id, file_path FROM audio_files WHERE analysis_status = 'pending' AND file_path LIKE ?"
                cursor.execute(query, (f"{directory}%",))
            else:
                # For non-recursive, match only files directly in the directory
                query = "SELECT id, file_path FROM audio_files WHERE analysis_status = 'pending' AND file_path LIKE ? AND file_path NOT LIKE ?"
                cursor.execute(query, (f"{directory}/%", f"{directory}/%/%"))
            
            pending_files = cursor.fetchall()
            total_files = len(pending_files)
            
            # Update progress
            analysis_progress['total_files'] = total_files
            analysis_progress['pending_count'] = total_files
            
            # Update status
            ANALYSIS_STATUS.update({
                'total_files': total_files
            })
            
            logger.info(f"Found {total_files} files pending analysis")
            
            # Analyze each file
            for i, (file_id, file_path) in enumerate(pending_files):
                # Check if stop requested
                if analysis_progress['stop_requested']:
                    logger.info("Analysis stopped by user request")
                    break
                
                # Update progress
                analysis_progress['current_file_index'] = i + 1
                
                # Update status
                file_name = os.path.basename(file_path)
                ANALYSIS_STATUS.update({
                    'current_file': file_name,
                    'files_processed': i,
                    'percent_complete': (i / total_files) * 100 if total_files > 0 else 100
                })
                
                try:
                    logger.info(f"Analyzing file {i+1}/{total_files}: {file_path}")
                    
                    # Check if file exists
                    if not os.path.exists(file_path):
                        logger.warning(f"File not found: {file_path}")
                        cursor.execute("UPDATE audio_files SET analysis_status = 'missing' WHERE id = ?", (file_id,))
                        self.db_conn.commit()
                        analysis_progress['failed_count'] += 1
                        continue
                    
                    # Analyze the file and extract features
                    features = self._extract_audio_features(file_path)
                    
                    if features:
                        # Save features to database
                        self._save_features_to_db(file_id, file_path, features)
                        
                        # Update analysis status
                        cursor.execute("UPDATE audio_files SET analysis_status = 'analyzed' WHERE id = ?", (file_id,))
                        self.db_conn.commit()
                        
                        analysis_progress['analyzed_count'] += 1
                    else:
                        logger.warning(f"Failed to extract features from {file_path}")
                        cursor.execute("UPDATE audio_files SET analysis_status = 'failed' WHERE id = ?", (file_id,))
                        self.db_conn.commit()
                        analysis_progress['failed_count'] += 1
                    
                    # Save changes periodically
                    if i % 5 == 0 and self.in_memory:
                        trigger_db_save(self.db_conn, self.db_path)
                        
                except Exception as e:
                    logger.error(f"Error analyzing file {file_path}: {e}")
                    cursor.execute("UPDATE audio_files SET analysis_status = 'failed' WHERE id = ?", (file_id,))
                    self.db_conn.commit()
                    analysis_progress['failed_count'] += 1
            
            # Final commit
            self.db_conn.commit()
            
            # Update final status
            analysis_progress['is_running'] = False
            analysis_progress['last_run_completed'] = True
            
            # Update status
            ANALYSIS_STATUS.update({
                'running': False,
                'files_processed': analysis_progress['analyzed_count'],
                'percent_complete': 100
            })
            
            logger.info(f"Analysis completed. Successfully analyzed {analysis_progress['analyzed_count']} files, "
                        f"failed: {analysis_progress['failed_count']}")
            
        except Exception as e:
            logger.error(f"Error analyzing directory: {e}")
            
            # Update error status
            analysis_progress['is_running'] = False
            analysis_progress['last_run_completed'] = False
            
            # Update status
            ANALYSIS_STATUS.update({
                'running': False,
                'error': str(e)
            })
    
    def analyze_directory_thread_safe(self, directory: str, recursive: bool = True) -> None:
        """
        Thread-safe version of analyze_directory - creates its own database connection
        
        Args:
            directory: Path to the music directory
            recursive: Whether to scan recursively
        """
        global analysis_progress
        from web_player import ANALYSIS_STATUS
        
        logger.info(f"Starting thread-safe analysis of {directory} (recursive={recursive})")
        
        # Update progress
        analysis_progress['is_running'] = True
        analysis_progress['total_files'] = 0
        analysis_progress['current_file_index'] = 0
        analysis_progress['analyzed_count'] = 0
        analysis_progress['failed_count'] = 0
        analysis_progress['stop_requested'] = False
        
        # Create a new connection in this thread
        try:
            # Create thread-local connection
            thread_conn = get_connection()
            
            # Get all pending files from database
            with thread_conn.cursor() as cursor:
                if recursive:
                    # Use recursive path matching with wildcards
                    query = "SELECT id, file_path FROM tracks WHERE analysis_status = 'pending' AND file_path LIKE %s"
                    cursor.execute(query, (f"{directory}%",))
                else:
                    # For non-recursive, match only files directly in the directory
                    query = "SELECT id, file_path FROM tracks WHERE analysis_status = 'pending' AND file_path LIKE %s AND file_path NOT LIKE %s"
                    cursor.execute(query, (f"{directory}/%", f"{directory}/%/%"))
                
                pending_files = cursor.fetchall()
                total_files = len(pending_files)
            
            # Update progress
            analysis_progress['total_files'] = total_files
            analysis_progress['pending_count'] = total_files
            
            # Update status
            ANALYSIS_STATUS.update({
                'running': True,
                'total_files': total_files,
                'files_processed': 0,
                'percent_complete': 0,
                'current_file': '',
                'start_time': datetime.now().isoformat(),
                'error': None
            })
            
            logger.info(f"Found {total_files} files pending analysis")
            
            # Analyze each file
            for i, file_data in enumerate(pending_files):
                # With PostgreSQL DictCursor, we access by column name
                file_id = file_data['id'] if isinstance(file_data, dict) else file_data[0]
                file_path = file_data['file_path'] if isinstance(file_data, dict) else file_data[1]
                
                # Check if stop requested
                if analysis_progress['stop_requested']:
                    logger.info("Analysis stopped by user request")
                    break
                
                # Update progress
                analysis_progress['current_file_index'] = i + 1
                
                # Update status
                file_name = os.path.basename(file_path)
                ANALYSIS_STATUS.update({
                    'current_file': file_name,
                    'files_processed': i,
                    'percent_complete': (i / total_files) * 100 if total_files > 0 else 100
                })
                
                try:
                    logger.info(f"Analyzing file {i+1}/{total_files}: {file_path}")
                    
                    # Check if file exists
                    if not os.path.exists(file_path):
                        logger.warning(f"File not found: {file_path}")
                        with thread_conn.cursor() as cursor:
                            cursor.execute("UPDATE tracks SET analysis_status = 'missing' WHERE id = %s", (file_id,))
                        thread_conn.commit()
                        analysis_progress['failed_count'] += 1
                        continue
                    
                    # Analyze the file and extract features
                    features = self._extract_audio_features(file_path)
                    
                    if features:
                        # Save features to database directly with this connection
                        with thread_conn.cursor() as cursor:
                            cursor.execute('''
                            INSERT INTO audio_features
                            (track_id, tempo, key, mode, time_signature, brightness,
                            acousticness, danceability, energy, instrumentalness, loudness, valence)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (track_id) DO UPDATE SET
                                tempo = EXCLUDED.tempo,
                                key = EXCLUDED.key,
                                mode = EXCLUDED.mode,
                                time_signature = EXCLUDED.time_signature,
                                acousticness = EXCLUDED.acousticness,
                                brightness = EXCLUDED.brightness,
                                danceability = EXCLUDED.danceability,
                                energy = EXCLUDED.energy,
                                instrumentalness = EXCLUDED.instrumentalness,
                                loudness = EXCLUDED.loudness,
                                valence = EXCLUDED.valence
                            ''', (
                                file_id, 
                                features.get('tempo', 0), 
                                features.get('key', 0), 
                                features.get('mode', 0), 
                                features.get('time_signature', 4),
                                features.get('brightness', 0),
                                features.get('acousticness', 0), 
                                features.get('danceability', 0), 
                                features.get('energy', 0),
                                features.get('instrumentalness', 0), 
                                features.get('loudness', 0), 
                                features.get('valence', 0)
                            ))
                            
                            # Update analysis status
                            cursor.execute("UPDATE tracks SET analysis_status = 'analyzed' WHERE id = %s", (file_id,))
                        
                        thread_conn.commit()
                        analysis_progress['analyzed_count'] += 1
                    else:
                        logger.warning(f"Failed to extract features from {file_path}")
                        with thread_conn.cursor() as cursor:
                            cursor.execute("UPDATE tracks SET analysis_status = 'failed' WHERE id = %s", (file_id,))
                        thread_conn.commit()
                        analysis_progress['failed_count'] += 1
                        
                except Exception as e:
                    logger.error(f"Error analyzing file {file_path}: {e}")
                    with thread_conn.cursor() as cursor:
                        cursor.execute("UPDATE tracks SET analysis_status = 'failed' WHERE id = %s", (file_id,))
                    thread_conn.commit()
                    analysis_progress['failed_count'] += 1
            
            # Release the thread connection
            release_connection(thread_conn)
            
            # Update final status
            analysis_progress['is_running'] = False
            analysis_progress['last_run_completed'] = True
            
            # Update status
            ANALYSIS_STATUS.update({
                'running': False,
                'files_processed': analysis_progress['analyzed_count'],
                'percent_complete': 100
            })
            
            logger.info(f"Analysis completed. Successfully analyzed {analysis_progress['analyzed_count']} files, "
                        f"failed: {analysis_progress['failed_count']}")
            
        except Exception as e:
            logger.error(f"Error analyzing directory: {e}")
            
            # Update error status
            analysis_progress['is_running'] = False
            analysis_progress['last_run_completed'] = False
            
            # Update status
            ANALYSIS_STATUS.update({
                'running': False,
                'error': str(e)
            })
    
    def _get_basic_metadata(self, file_path: str) -> Dict:
        """Extract basic metadata from an audio file using mutagen"""
        metadata = {}
        
        try:
            audio = mutagen.File(file_path)
            
            if audio is None:
                return metadata
            
            # Get duration
            metadata['duration'] = audio.info.length
            
            # ID3 tags (MP3)
            if hasattr(audio, 'tags') and audio.tags:
                # Title
                if 'TIT2' in audio:
                    metadata['title'] = str(audio['TIT2'])
                
                # Artist
                if 'TPE1' in audio:
                    metadata['artist'] = str(audio['TPE1'])
                
                # Album
                if 'TALB' in audio:
                    metadata['album'] = str(audio['TALB'])
                
                # Genre
                if 'TCON' in audio:
                    metadata['genre'] = str(audio['TCON'])
            
            # FLAC/Ogg tags
            elif hasattr(audio, 'get'):
                # Title
                if 'title' in audio:
                    metadata['title'] = str(audio['title'][0])
                
                # Artist
                if 'artist' in audio:
                    metadata['artist'] = str(audio['artist'][0])
                
                # Album
                if 'album' in audio:
                    metadata['album'] = str(audio['album'][0])
                
                # Genre
                if 'genre' in audio:
                    metadata['genre'] = str(audio['genre'][0])
            
            # Parse filename if no metadata found
            if 'title' not in metadata:
                # Try to extract artist and title from filename
                file_name = os.path.basename(file_path)
                file_name_no_ext = os.path.splitext(file_name)[0]
                
                # Check for common patterns like "Artist - Title"
                if ' - ' in file_name_no_ext:
                    parts = file_name_no_ext.split(' - ', 1)
                    if 'artist' not in metadata:
                        metadata['artist'] = parts[0].strip()
                    if 'title' not in metadata:
                        metadata['title'] = parts[1].strip()
                else:
                    metadata['title'] = file_name_no_ext
            
            return metadata
            
        except Exception as e:
            logger.error(f"Error extracting metadata from {file_path}: {e}")
            return metadata
    
    def _extract_audio_features(self, file_path: str) -> Dict:
        """Extract audio features from a file"""
        features = {}
        
        try:
            # Load audio file with librosa
            try:
                y, sr = librosa.load(file_path, sr=None, mono=True, duration=60)
            except Exception as e:
                logger.error(f"Error loading audio file {file_path}: {e}")
                # Return basic features without audio analysis
                return {
                    "tempo": 0,
                    "key": 0,
                    "mode": 0,
                    "time_signature": 4,
                    "energy": 0,
                    "danceability": 0.5,  # Default value
                    "brightness": 0,
                    "noisiness": 0
                }
                
            # Now we have y and sr for sure
            if y is None or len(y) == 0:
                logger.warning(f"Empty audio data for {file_path}")
                # Return default values
                return {
                    "tempo": 0,
                    "key": 0,
                    "mode": 0,
                    "time_signature": 4,
                    "energy": 0,
                    "danceability": 0.5,
                    "brightness": 0,
                    "noisiness": 0
                }
                
            # Extract features only if we have valid audio data
            features["danceability"] = self.estimate_danceability(y=y, sr=sr)
            
            # Extract other features with proper error handling...
            try:
                tempo_data = librosa.beat.tempo(y=y, sr=sr)
                features["tempo"] = float(tempo_data[0] if hasattr(tempo_data, '__len__') else tempo_data)
            except Exception as e:
                logger.warning(f"Error estimating tempo: {e}")
                features["tempo"] = 120  # Default tempo
                
            # Add similar error handling for other feature extractions...
            
            return features
        except Exception as e:
            logger.error(f"Error extracting audio features from {file_path}: {e}")
            return {
                "tempo": 0,
                "key": 0,
                "mode": 0,
                "time_signature": 4,
                "energy": 0,
                "danceability": 0.5,
                "brightness": 0,
                "noisiness": 0
            }

    def _save_to_db_with_connection(self, features: Dict, conn, cursor):
        """Save audio features using an existing database connection"""
        # Insert audio file info
        cursor.execute('''
            INSERT OR REPLACE INTO audio_files 
            (file_path, title, artist, album, album_art_url, metadata_source, duration, artist_image_url) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            features["file_path"],
            features.get("title", ""),
            features.get("artist", ""),
            features.get("album", ""),
            features.get("album_art_url", ""),
            features.get("metadata_source", "unknown"),
            features.get("duration", 0),
            features.get("artist_image_url", "")
        ))
        
        # Get the ID of the audio file
        file_id = cursor.lastrowid
        
        # Updated to include loudness
        cursor.execute('''
            INSERT OR REPLACE INTO audio_features
            (file_id, tempo, key, mode, time_signature, energy, danceability, brightness, noisiness, loudness)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            file_id,
            features.get("tempo", 0),
            features.get("key", 0),
            features.get("mode", 0),
            features.get("time_signature", 4),
            features.get("energy", 0),
            features.get("danceability", 0),
            features.get("brightness", 0),
            features.get("noisiness", 0),
            features.get("loudness", 0)
        ))

    def analyze_pending_files(self, limit: Optional[int] = None, 
                         batch_size: int = 10, 
                         max_errors: int = 3,
                         progress_callback = None,
                         status_dict = None):
        """Analyze files that have been added to the database but not yet analyzed."""
        global analysis_progress
        from datetime import datetime  # Add import at the top
        
        analysis_progress['is_running'] = True
        analysis_progress['stop_requested'] = False
        
        # Clear previous progress
        analysis_progress['current_file_index'] = 0
        analysis_progress['analyzed_count'] = 0
        analysis_progress['failed_count'] = 0
        
        # Get count of already analyzed files
        already_analyzed = execute_query_row(
            "SELECT COUNT(*) as count FROM tracks WHERE analysis_status = 'analyzed'"
        )['count']
        
        analysis_progress['analyzed_count'] = already_analyzed

        logger.info(f"Starting full analysis of pending files - already analyzed: {already_analyzed}")
        
        # CRITICAL FIX: Get the pending files BEFORE using total_pending
        pending_files = execute_query(
            '''SELECT id, file_path
               FROM tracks
               WHERE analysis_status = 'pending'
               ORDER BY date_added DESC'''
        )
        
        # NOW calculate total_pending
        total_pending = len(pending_files)
        total_files = already_analyzed + total_pending
        
        if limit:
            pending_files = pending_files[:limit]
        
        analysis_progress['total_files'] = total_files
        analysis_progress['pending_count'] = total_pending
        
        # NOW update the status dictionary with total_pending
        if status_dict:
            status_dict.update({
                'running': True,
                'total_files': total_files,  # CHANGED: Use total files including already analyzed
                'files_processed': already_analyzed,  # ADDED: Initialize with already analyzed count
                'current_file': '',
                'percent_complete': int((already_analyzed / total_files) * 100) if total_files > 0 else 0,  # CHANGED: Calculate initial percentage
                'last_updated': datetime.now().isoformat(),
                'scan_complete': True  # Add this line to preserve the flag
            })
        
        # Initialize counters
        analyzed_count = 0
        error_count = 0
        consecutive_errors = 0
        
        # Process each file - FIXED: added proper loop structure
        for i, (file_id, file_path) in enumerate(pending_files):
            # Check if we should stop
            if analysis_progress['stop_requested']:
                logger.info("Analysis stopped by user request")
                break
            
            # Update progress before starting the analysis (for UI feedback)
            analysis_progress['current_file_index'] = i + 1
            
            # Also update the web status dictionary if provided
            if status_dict:
                status_dict.update({
                    'files_processed': already_analyzed + i + 1,  # CHANGED: Include the already analyzed files in count
                    'current_file': os.path.basename(file_path),
                    'percent_complete': int(((already_analyzed + i + 1) / total_files) * 100) if total_files > 0 else 100,  # CHANGED: Calculate percentage
                    'last_updated': datetime.now().isoformat(),
                    'scan_complete': True  # Add this line to ensure flag stays set
                })
            
            logger.info(f"Analyzing file {i+1}/{len(pending_files)}: {file_path}")
            
            try:
                # Use a separate transaction for each file
                with transaction_context() as (conn, cursor):
                    # Analyze the file
                    features = self._analyze_file_without_db_check(file_path)
                    
                    if features and 'error' not in features:
                        # Update the file's analysis status
                        cursor.execute(
                            "UPDATE tracks SET analysis_status = 'analyzed' WHERE id = %s",
                            (file_id,)
                        )
                        
                        # Insert the features - Match columns with PostgreSQL schema
                        cursor.execute(
                            '''INSERT INTO audio_features 
                               (track_id, tempo, key, mode, time_signature, energy, 
                                danceability, acousticness, brightness, instrumentalness, 
                                valence, loudness)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                               ON CONFLICT (track_id) DO UPDATE SET
                               tempo = EXCLUDED.tempo,
                               key = EXCLUDED.key,
                               mode = EXCLUDED.mode,
                               time_signature = EXCLUDED.time_signature,
                               energy = EXCLUDED.energy,
                               danceability = EXCLUDED.danceability,
                               acousticness = EXCLUDED.acousticness,
                               brightness = EXCLUDED.brightness,
                               instrumentalness = EXCLUDED.instrumentalness,
                               valence = EXCLUDED.valence,
                               loudness = EXCLUDED.loudness''',
                            (
                                file_id,
                                features.get("tempo", 0),
                                features.get("key", 0),
                                features.get("mode", 0),
                                features.get("time_signature", 4),
                                features.get("energy", 0),
                                features.get("danceability", 0),
                                features.get("acousticness", 0.5),
                                features.get("brightness", features.get("brightness", 0)),
                                features.get("instrumentalness", 0),
                                features.get("valence", 0.5),
                                features.get("loudness", 0)
                            )
                        )
                        
                        analyzed_count += 1
                        analysis_progress['analyzed_count'] += 1
                        consecutive_errors = 0
                        logger.info(f"Successfully analyzed: {os.path.basename(file_path)}")
                    else:
                        # Mark as failed
                        cursor.execute(
                            "UPDATE tracks SET analysis_status = 'failed' WHERE id = %s",
                            (file_id,)
                        )
                        error_count += 1
                        analysis_progress['failed_count'] += 1
                        consecutive_errors += 1
                        logger.warning(f"Failed to analyze: {os.path.basename(file_path)} - {features.get('error', 'Unknown error')}")
                
            except Exception as e:
                logger.error(f"Error analyzing {file_path}: {e}")
                # Use a separate transaction to update the status
                with transaction_context() as (conn, cursor):
                    cursor.execute(
                        "UPDATE tracks SET analysis_status = 'failed' WHERE id = %s",
                        (file_id,)
                    )
                error_count += 1
                analysis_progress['failed_count'] += 1
                consecutive_errors += 1
            
            # Check if we've hit too many consecutive errors
            if consecutive_errors >= max_errors:
                logger.warning(f"Stopping analysis after {consecutive_errors} consecutive errors")
                break
        
        # Get updated pending count
        remaining_pending = len(execute_query(
            '''SELECT t.id
               FROM tracks t
               LEFT JOIN audio_features feat ON t.id = feat.track_id
               WHERE feat.track_id IS NULL'''
        ))
        
        analysis_progress['pending_count'] = remaining_pending
        analysis_progress['is_running'] = False
        analysis_progress['last_run_completed'] = True
        
        logger.info(f"Analysis complete: {analyzed_count} files analyzed, {error_count} errors, {remaining_pending} still pending")
        
        return {
            'success': True,
            'analyzed': analyzed_count,
            'errors': error_count,
            'pending': remaining_pending
        }

    def _analyze_file_for_features(self, file_path: str) -> Dict:
        """Internal method that performs the actual audio analysis"""
        # Load the audio file for analysis
        y, sr = librosa.load(file_path, sr=None)
        
        # Basic audio properties
        duration = librosa.get_duration(y=y, sr=sr)
        
        # Extract features
        features = {
            "file_path": file_path,
            "duration": duration,
            **self._extract_time_domain_features(y, sr),
            **self._extract_frequency_domain_features(y, sr),
            **self._extract_rhythm_features(y, sr),
            **self._extract_harmonic_features(y, sr)
        }
        
        return features

    def _fix_database_inconsistencies(self):
        """Fix any inconsistencies between audio_files and audio_features tables"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
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
                    AND id IN (SELECT file_id FROM audio_features)
                ''')
                
                conn.commit()
                
                # Get count after fix
                cursor.execute("SELECT COUNT(*) FROM audio_files WHERE analysis_status = 'pending'")
                after_count = cursor.fetchone()[0]
                
                print(f"Database consistency check: {before_count} pending files before, {after_count} after fix")
        except Exception as e:
            print(f"Error fixing database inconsistencies: {e}")

    def _extract_metadata(self, audio, file_path):
        """Extract basic metadata from an audio file."""
        metadata = {
            'title': '',
            'artist': '',
            'album': '',
            'duration': 0
        }
        
        try:
            if (audio is None):
                return metadata
                
            # Extract metadata based on file type
            if hasattr(audio, 'tags'):  # MP3
                tags = audio.tags
                if tags:
                    if 'TIT2' in tags:
                        metadata['title'] = str(tags['TIT2'])
                    if 'TPE1' in tags:
                        metadata['artist'] = str(tags['TPE1'])
                    if 'TALB' in tags:
                        metadata['album'] = str(tags['TALB'])
            elif hasattr(audio, 'info'):  # FLAC, OGG, etc.
                if hasattr(audio, 'title') and audio.title:
                    metadata['title'] = audio.title[0] if isinstance(audio.title, list) else audio.title
                if hasattr(audio, 'artist') and audio.artist:
                    metadata['artist'] = audio.artist[0] if isinstance(audio.artist, list) else audio.artist
                if hasattr(audio, 'album') and audio.album:
                    metadata['album'] = audio.album[0] if isinstance(audio.album, list) else audio.album
                    
            # Extract duration
            if hasattr(audio, 'info') and hasattr(audio.info, 'length'):
                metadata['duration'] = float(audio.info.length)
                
            # Use filename as title if no title found
            if not metadata['title']:
                metadata['title'] = os.path.basename(file_path)
                
        except Exception as e:
            logger.error(f"Error extracting metadata from {file_path}: {e}")
            
            # Estimate key
            chroma_avg = np.mean(chroma, axis=1)
            key = np.argmax(chroma_avg)
            features["key"] = int(key)
            
            # Minor or Major mode
            minor_template = np.array([1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 1, 0])
            major_template = np.array([1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1])
            
            # Rotate templates to match the key
            minor_template = np.roll(minor_template, key)
            major_template = np.roll(major_template, key)
            
            # Correlate with chroma
            minor_corr = np.corrcoef(minor_template, chroma_avg)[0, 1]
            major_corr = np.corrcoef(major_template, chroma_avg)[0, 1]
            
            # Determine mode (0 for minor, 1 for major)
            mode = 1 if major_corr > minor_corr else 0
            features["mode"] = mode
            
            # RMS energy
            rms = librosa.feature.rms(y=y)
            features["energy"] = float(np.mean(rms))
            
            # Spectral centroid (brightness)
            cent = librosa.feature.spectral_centroid(y=y, sr=sr)
            features["acousticness"] = 1.0 - min(1.0, float(np.mean(cent)) / 5000)
            
            # MFCCs for overall spectral shape
            mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
            mfcc_mean = np.mean(mfcc, axis=1)
            
            # Use MFCCs to estimate various features
            features["danceability"] = max(0, min(1, (mfcc_mean[1] + 100) / 200))
            features["valence"] = max(0, min(1, (mfcc_mean[2] + 100) / 200))
            
            # Zero-crossing rate for noisiness
            zcr = librosa.feature.zero_crossing_rate(y=y)
            features["speechiness"] = min(1.0, float(np.mean(zcr)) * 10)
            
            # Spectral contrast for instrumentalness
            contrast = librosa.feature.spectral_contrast(y=y, sr=sr)
            features["instrumentalness"] = min(1.0, float(np.mean(contrast)) / 5)
            
            features["brightness"] = float(np.mean(cent))
            # Loudness
            features["loudness"] = float(librosa.amplitude_to_db(np.mean(rms)))
            
            # Normalize features to 0-1 range
            for key in features:
                if key != "key" and key != "mode" and key != "loudness":
                    features[key] = max(0, min(1, features[key]))
            
            return features
            
        except Exception as e:
            logger.error(f"Error extracting spectral features: {e}")
            return {
                "key": 0,
                "mode": 0,
                "acousticness": 0.5,
                "brightness": 0.5,
                "danceability": 0.5,
                "energy": 0.5,
                "instrumentalness": 0.5,
                "loudness": -20,
                "speechiness": 0.5,
                "valence": 0.5
            }
    
    def _get_enhanced_metadata(self, file_path: str) -> Dict:
        """Get enhanced metadata from external services"""
        # Get basic metadata first
        metadata = self._get_basic_metadata(file_path)
        
        # If we have a metadata service, use it
        if self.metadata_service and metadata.get('artist') and metadata.get('title'):
            try:
                enhanced = self.metadata_service.get_track_metadata(
                    metadata['artist'], 
                    metadata['title'],
                    metadata.get('album', '')
                )
                
                # Merge with existing metadata
                metadata.update(enhanced)
                
            except Exception as e:
                logger.error(f"Error getting enhanced metadata: {e}")
        
        return metadata
    
    def _save_features_to_db(self, file_id: int, file_path: str, features: Dict) -> None:
        """Save extracted features to the database"""
        try:
            cursor = self.db_conn.cursor()
            
            # Check if features already exist
            cursor.execute("SELECT id FROM audio_features WHERE file_id = ?", (file_id,))
            existing = cursor.fetchone()
            
            if existing:
                # Update existing features
                cursor.execute('''
                UPDATE audio_features SET
                tempo = ?, key = ?, mode = ?, time_signature = ?,
                acousticness = ?, danceability = ?, energy = ?, brightness = ?,
                instrumentalness = ?, loudness = ?, speechiness = ?, valence = ?
                WHERE file_id = ?
                ''', (
                    features['tempo'], features['key'], features['mode'], features['time_signature'],
                    features['acousticness'], features['danceability'], features['energy'],
                    features['instrumentalness'], features['loudness'], features['speechiness'], features['valence'],
                    file_id
                ))
            else:
                # Insert new features
                cursor.execute('''
                INSERT INTO audio_features
                (file_id, file_path, tempo, key, mode, time_signature, brightness,
                acousticness, danceability, energy, instrumentalness, loudness, speechiness, valence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    file_id, file_path, 
                    features['tempo'], features['key'], features['mode'], features['time_signature'],
                    features['acousticness'], features['danceability'], features['energy'],
                    features['instrumentalness'], features['loudness'], features['speechiness'], features['valence']
                ))
            
            self.db_conn.commit()
            
        except Exception as e:
            logger.error(f"Error saving features to database: {e}")
            raise
    
    def create_station(self, seed_file_path: str, playlist_size: int = 10) -> List[str]:
        """Create a playlist of similar tracks based on a seed track"""
        try:
            # Get features of the seed track
            cursor = self.db_conn.cursor()
            
            # First, make sure seed track has been analyzed
            cursor.execute('''
            SELECT analysis_status FROM tracks
            WHERE file_path = %s
            ''', (seed_file_path,))
            
            status = cursor.fetchone()
            if not status or status[0] != 'analyzed':
                logger.warning(f"Seed track {seed_file_path} has not been analyzed")
                return []
            
            # Get seed track's features
            cursor.execute('''
            SELECT af.* FROM audio_features af
            JOIN tracks t ON af.track_id = t.id
            WHERE t.file_path = %s
            ''', (seed_file_path,))
            
            seed_features = cursor.fetchone()
            if not seed_features:
                logger.warning(f"No audio features found for seed track {seed_file_path}")
                return []
            
            # Find similar tracks
            cursor.execute('''
            WITH seed_features AS (
                SELECT af.* 
                FROM audio_features af
                JOIN tracks t ON af.track_id = t.id
                WHERE t.file_path = %s
            ),
            track_distances AS (
                SELECT t.file_path, t.title, t.artist, t.album,
                   SQRT(POWER(af.energy - sf.energy, 2) +
                        POWER(af.danceability - sf.danceability, 2) +
                        POWER(af.valence - sf.valence, 2) +
                        POWER(af.acousticness - sf.acousticness, 2)) as distance
                FROM audio_features af
                JOIN tracks t ON af.track_id = t.id
                CROSS JOIN seed_features sf
                WHERE t.file_path != %s
            )
            SELECT file_path
            FROM track_distances
            ORDER BY distance ASC
            LIMIT %s
            ''', (seed_file_path, seed_file_path, playlist_size - 1))
            
            similar_tracks = [row[0] for row in cursor.fetchall()]
            
            # Add seed track at the beginning
            return [seed_file_path] + similar_tracks
            
        except Exception as e:
            logger.error(f"Error creating station: {e}")
            return [seed_file_path]  # Return just the seed track on error

    def analyze_audio_file(self, file_path):
        """Main analysis method with improved error handling"""
        try:
            # Load the audio file with error checking
            try:
                y, sr = librosa.load(file_path, sr=None, duration=30)
                if y is None or len(y) == 0:
                    raise ValueError("Failed to load audio data from file")
            except Exception as e:
                logger.error(f"Error loading audio file {file_path}: {e}")
                return None
                
            # Extract features with defensive programming
            features = {}
            
            # Always check values before accessing them
            try:
                tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
                features['tempo'] = float(tempo) if tempo is not None else 0.0
            except Exception as e:
                logger.warning(f"Error extracting tempo from {file_path}: {e}")
                features['tempo'] = 0.0
                
            # Similar pattern for other feature extractions...
            
            return features
        except Exception as e:
            logger.error(f"Error analyzing file {file_path}: {e}")
            return None

    def quick_scan(self, directory: str, recursive: bool = True):
        """
        Alias for scan_library for backward compatibility.
        Quickly scan directory for audio files and add them to database without analysis.
        """
        logger.info(f"Running quick scan (alias for scan_library) on {directory}")
        return self.scan_library(directory, recursive)

    def estimate_danceability(self, y=None, sr=None):
        """
        Estimate danceability based on rhythm regularity and energy.
        
        This is a simplified implementation - commercial services use more complex algorithms.
        """
        # Check if y is defined, if not return a default value
        if y is None:
            logger.warning("No audio data provided for danceability estimation, returning default value")
            return 0.5
        
        try:
            # Get onset strength
            onset_env = librosa.onset.onset_strength(y=y, sr=sr)
            
            # Calculate pulse clarity (rhythm regularity)
            ac = librosa.autocorrelate(onset_env, max_size=sr // 2)
            # Find second peak (first peak is at lag 0)
            peaks = librosa.util.peak_pick(ac, pre_max=20, post_max=20, pre_avg=20, 
                                          post_avg=20, delta=0.1, wait=1)
            if len(peaks) > 0:
                # Use the highest peak as rhythm regularity measure
                rhythm_regularity = ac[peaks[0]] / ac[0]
            else:
                rhythm_regularity = 0.1  # Low danceability if no clear rhythm
            
            # Calculate tempo - the missing piece causing the error!
            tempo_data = librosa.beat.tempo(onset_envelope=onset_env, sr=sr)
            tempo = tempo_data[0] if hasattr(tempo_data, '__len__') else tempo_data
            
            # Combine with tempo and energy information
            tempo_factor = np.clip((tempo - 60) / (180 - 60), 0, 1)  # Normalize tempo between 60-180 BPM
            energy = np.mean(librosa.feature.rms(y=y))
            energy_factor = np.clip(energy / 0.1, 0, 1)  # Normalize energy
            
            danceability = (0.5 * rhythm_regularity + 0.3 * tempo_factor + 0.2 * energy_factor)
            
            # Fix: ensure danceability is a scalar value
            return float(danceability)
        except Exception as e:
            logger.error(f"Error estimating danceability: {e}")
            return 0.5  # Return default value on error

    def _extract_time_domain_features(self, y, sr):
        """Extract features from the time domain"""
        features = {}
        try:
            # RMS energy
            rms = librosa.feature.rms(y=y)
            features["energy"] = float(np.mean(rms))
            
            # Zero crossing rate for noisiness
            zcr = librosa.feature.zero_crossing_rate(y=y)
            features["noisiness"] = float(np.mean(zcr))
            
            return features
        except Exception as e:
            logger.error(f"Error extracting time domain features: {e}")
            return {
                "energy": 0.5,
                "noisiness": 0.5
            }

    def _extract_frequency_domain_features(self, y, sr):
        """Extract features from the frequency domain"""
        features = {}
        
        try:
            # Spectral centroid (brightness)
            cent = librosa.feature.spectral_centroid(y=y, sr=sr)
            features["brightness"] = float(np.mean(cent)) / 10000.0  # Normalize to 0-1 range
            
            # Spectral contrast
            contrast = librosa.feature.spectral_contrast(y=y, sr=sr)
            features["spectral_contrast"] = float(np.mean(contrast))
            
            # Spectral bandwidth
            bandwidth = librosa.feature.spectral_bandwidth(y=y, sr=sr)
            features["spectral_bandwidth"] = float(np.mean(bandwidth))
            
            # Loudness
            S = librosa.stft(y)
            db = librosa.amplitude_to_db(abs(S))
            features["loudness"] = float(np.mean(db))
            
            # MFCCs
            mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
            features["mfcc"] = np.mean(mfcc, axis=1).tolist()
            
            return features
        except Exception as e:
            logger.error(f"Error extracting frequency domain features: {e}")
            return {
                "brightness": 0.5,
                "spectral_contrast": 0.5,
                "spectral_bandwidth": 0.5,
                "loudness": -20.0,
                "mfcc": [0.0] * 13
            }

    def _extract_rhythm_features(self, y, sr):
        """Extract rhythm-related features"""
        features = {}
        
        try:
            # Tempo
            onset_env = librosa.onset.onset_strength(y=y, sr=sr)
            tempo = librosa.beat.tempo(onset_envelope=onset_env, sr=sr)
            if hasattr(tempo, "__len__"):
                features["tempo"] = float(tempo[0])
            else:
                features["tempo"] = float(tempo)
            
            # Time signature estimation
            features["time_signature"] = 4  # Default to 4/4
            
            # Danceability estimate
            features["danceability"] = self.estimate_danceability(y=y, sr=sr)
            
            return features
        except Exception as e:
            logger.error(f"Error extracting rhythm features: {e}")
            return {
                "tempo": 120.0,
                "time_signature": 4,
                "danceability": 0.5
            }

    def _extract_harmonic_features(self, y, sr):
        """Extract harmony-related features"""
        features = {}
        
        try:
            # Chromagram
            chroma = librosa.feature.chroma_stft(y=y, sr=sr)
            
            # Key estimation
            chroma_avg = np.mean(chroma, axis=1)
            key = np.argmax(chroma_avg)
            features["key"] = int(key)
            
            # Minor or Major mode estimation
            minor_template = np.array([1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 1, 0])
            major_template = np.array([1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1])
            
            # Rotate templates to match the key
            minor_template = np.roll(minor_template, key)
            major_template = np.roll(major_template, key)
            
            # Correlate with chroma
            minor_corr = np.corrcoef(minor_template, chroma_avg)[0, 1]
            major_corr = np.corrcoef(major_template, chroma_avg)[0, 1]
            
            # Determine mode (0 for minor, 1 for major)
            mode = 1 if major_corr > minor_corr else 0
            features["mode"] = mode
            
            return features
        except Exception as e:
            logger.error(f"Error extracting harmonic features: {e}")
            return {
                "key": 0,
                "mode": 1  # Default to major
            }

def main():
    """Command line interface for music analysis"""
    parser = argparse.ArgumentParser(description='Music analysis and feature extraction')
    parser.add_argument('--directory', '-d', required=True, help='Directory with music files')
    parser.add_argument('--recursive', '-r', action='store_true', help='Scan directory recursively')
    parser.add_argument('--database', default='pump.db', help='Database file path')
    parser.add_argument('--scan-only', action='store_true', help='Only scan files, do not analyze')
    
    args = parser.parse_args()
    
    try:
        analyzer = MusicAnalyzer()
        
        if args.scan_only:
            logger.info("Performing quick scan...")
            result = analyzer.scan_library(args.directory, args.recursive)
            logger.info(f"Scan completed: {result['processed']} files processed, {result['added']} tracks added")
        else:
            logger.info("Performing full analysis...")
            analyzer.scan_library(args.directory, args.recursive)
            analyzer.analyze_directory(args.directory, args.recursive)
            logger.info("Analysis completed")
            
    except Exception as e:
        logger.error(f"Error: {e}")
        return 1
        
    return 0

if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Initialize the analyzer
    try:
        # Initialize database if needed
        from db_operations import initialize_database
        initialize_database()
        
        # Now initialize the analyzer
        analyzer = MusicAnalyzer()
        logger.info("Music analyzer initialized successfully")
    except Exception as e:
        analyzer = None
        logger.error(f"Error initializing music analyzer: {e}")
    
    exit(main())