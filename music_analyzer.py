import os
import numpy as np
import pandas as pd
import librosa
import sqlite3
import argparse
from typing import Dict, List, Tuple, Union, Optional
from pathlib import Path
from lastfm_service import LastFMService
from spotify_service import SpotifyService
import configparser
import logging
import threading
import mutagen  # Make sure this is imported

import librosa.display
import matplotlib.pyplot as plt
from metadata_service import MetadataService
from db_utils import get_optimized_connection, optimized_connection
from db_operations import execute_query, execute_query_dict, execute_query_row, execute_write, execute_batch, transaction_context

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

# Add near other global variables
scan_mutex = threading.Lock()

class MusicAnalyzer:
    """
    A class for analyzing music files and extracting audio features for music categorization.
    """

    def __init__(self, db_path: str = "pump.db", in_memory=False, cache_size_mb=75):
        """
        Initialize the MusicAnalyzer.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self.in_memory = in_memory
        self.cache_size_mb = cache_size_mb
        self._initialize_db()
        self.metadata_service = MetadataService()
        
        # Initialize services with API keys from config
        self.lastfm_service = None
        self.spotify_service = None
        self._initialize_services()
    
    def _initialize_services(self):
        """Initialize LastFM and Spotify services with API keys from config"""
        try:
            config = configparser.ConfigParser()
            if os.path.exists('pump.conf'):
                config.read('pump.conf')
                print(f"Config file found at: {os.path.abspath('pump.conf')}")
            else:
                print("Config file 'pump.conf' not found")
                
            # Initialize LastFM - first try user's key, then fallback key
            api_key = config.get('lastfm', 'api_key', fallback=None)
            api_secret = config.get('lastfm', 'api_secret', fallback=None)
            
            print(f"LastFM config found: api_key exists: {bool(api_key)}, api_secret exists: {bool(api_secret)}")
            
            # If user's key is missing, try fallback key
            if not api_key:
                api_key = 'b21e44890bc788b52879506873d5ac33'  # Fallback key
                api_secret = 'bc5e07063a9e09401386a78bfd1350f9'  # Fallback secret
                print("Using fallback LastFM API key")
            
            try:
                print("Attempting to initialize LastFM service...")
                self.lastfm_service = LastFMService(api_key, api_secret)
                # Verify the service works with a simple test
                test_artist = "The Beatles"
                print(f"Testing LastFM with artist: {test_artist}")
                test_url = self.lastfm_service.get_artist_image_url(test_artist)
                print(f"LastFM test result: {'Success' if test_url else 'Failed'}")
                logging.info("LastFM service initialized successfully")
            except Exception as e:
                print(f"LastFM service initialization error: {e}")
                self.lastfm_service = None
            
            # Initialize Spotify - first try user's credentials, then fallback
            client_id = config.get('spotify', 'client_id', fallback=None)
            client_secret = config.get('spotify', 'client_secret', fallback=None)
            
            # If user's credentials are missing, try fallback
            if not client_id or not client_secret:
                client_id = '5de01599b1ec493ea7fc3d0c4b1ec977'  # Fallback ID
                client_secret = 'be8bb04ebb9c447484f62320bfa9b4cc'  # Fallback secret
                logging.info("Using fallback Spotify API credentials")
                
            self.spotify_service = SpotifyService(client_id, client_secret)
            logging.info("Spotify service initialized successfully")
                
        except Exception as e:
            print(f"Error in _initialize_services: {e}")
            logging.error(f"Error initializing services: {e}")
        
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
                    from db_utils import trigger_db_save
                    trigger_db_save(conn, self.db_path)
                    logger.info("Schema changes saved to disk")
                    
                logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise
        
    def analyze_file(self, file_path: str, save_to_db: bool = True) -> Dict:
        """
        Analyze a music file and extract its features, but skip if it's already in the database.
        """
        # 1) Check if file has already been analyzed
        row = execute_query_row(
            self.db_path,
            "SELECT id FROM audio_files WHERE file_path = ?",
            (file_path,),
            in_memory=self.in_memory,
            cache_size_mb=self.cache_size_mb
        )

        if row is not None:
            # The file already exists in the database; skip re-analysis
            print(f"Skipping {file_path}, it already exists in the database.")
            return {"status": "skipped"}

        # 2) If not found in DB, proceed with the usual analysis
        try:
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
            print(f"Error analyzing {file_path}: {e}")
            return {"error": str(e)}

    
    def _extract_time_domain_features(self, y: np.ndarray, sr: int) -> Dict:
        """Extract time-domain features."""
        # Zero-crossing rate
        zcr = librosa.feature.zero_crossing_rate(y).mean()
        
        # RMS energy
        rms = librosa.feature.rms(y=y).mean()
        
        return {
            "zero_crossing_rate": float(zcr),
            "rms_energy": float(rms),
            "energy": float(np.mean(y**2)),
        }
    
    def _extract_frequency_domain_features(self, y: np.ndarray, sr: int) -> Dict:
        """Extract frequency-domain features."""
        # Spectral centroid (brightness)
        centroid = librosa.feature.spectral_centroid(y=y, sr=sr).mean()
        
        # Spectral rolloff
        rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr).mean()
        
        # MFCCs
        mfccs = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
        mfcc_means = mfccs.mean(axis=1)
        
        features = {
            "spectral_centroid": float(centroid),
            "spectral_rolloff": float(rolloff),
            "brightness": float(centroid / (sr/2)),  # Normalized brightness
        }
        
        # Add MFCCs
        for i, mfcc_val in enumerate(mfcc_means):
            features[f"mfcc_{i+1}"] = float(mfcc_val)
            
        return features
    
    def _extract_rhythm_features(self, y: np.ndarray, sr: int) -> Dict:
        """Extract rhythm-related features."""
        # Tempo and beat frames
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        tempo, _ = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
        
        # Fix: ensure tempo is a scalar value
        tempo_value = tempo.item() if hasattr(tempo, 'item') else float(tempo)
        
        return {
            "tempo": tempo_value,
            "danceability": self._estimate_danceability(y, sr, tempo_value)
        }

    def _extract_harmonic_features(self, y: np.ndarray, sr: int) -> Dict:
        """Extract harmonic features (key, mode, etc.)."""
        # Chroma features
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        
        # Key detection (simplified)
        chromagram = librosa.feature.chroma_stft(y=y, sr=sr)
        chroma_vals = np.mean(chromagram, axis=1)
        key = int(np.argmax(chroma_vals))
        
        # Mode detection (simplified - major vs minor)
        major_profile = np.array([1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1])
        minor_profile = np.array([1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 1, 0])
        
        key_shifted_chroma = np.roll(chroma_vals, -key)
        major_correlation = np.corrcoef(key_shifted_chroma, major_profile)[0, 1]
        minor_correlation = np.corrcoef(key_shifted_chroma, minor_profile)[0, 1]
        
        mode = 1 if major_correlation > minor_correlation else 0  # 1 for major, 0 for minor
        
        return {
            "key": key,
            "mode": mode
        }
    
    def _estimate_danceability(self, y: np.ndarray, sr: int, tempo: float) -> float:
        """
        Estimate danceability based on rhythm regularity and energy.
        
        This is a simplified implementation - commercial services use more complex algorithms.
        """
        # Get onset strength
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        
        # Calculate pulse clarity (rhythm regularity)
        ac = librosa.autocorrelate(onset_env, max_size=sr // 2)
        # Find second peak (first peak is at lag 0)
        peaks = librosa.util.peak_pick(ac, pre_max=20, post_max=20, pre_avg=20, 
                                      post_avg=20, delta=0.1, wait=1)
        if len(peaks) > 0:
            # Use height of second peak as rhythm regularity indicator
            rhythm_regularity = ac[peaks[0]] / ac[0] if peaks[0] > 0 else 0
        else:
            rhythm_regularity = 0
            
        # Combine with tempo and energy information
        tempo_factor = np.clip((tempo - 60) / (180 - 60), 0, 1)  # Normalize tempo between 60-180 BPM
        energy = np.mean(librosa.feature.rms(y=y))
        energy_factor = np.clip(energy / 0.1, 0, 1)  # Normalize energy
        
        danceability = (0.5 * rhythm_regularity + 0.3 * tempo_factor + 0.2 * energy_factor)
        
        # Fix: ensure danceability is a scalar value
        danceability_value = danceability.item() if hasattr(danceability, 'item') else float(danceability)
        return danceability_value
    
    def _save_to_db(self, features: Dict):
        """Save audio features to database using the new db_operations module"""
        try:
            # First, save or update the file metadata in audio_files table
            file_path = features["file_path"]
            
            # Insert or replace the audio file info
            file_id = execute_write(
                self.db_path,
                '''INSERT OR REPLACE INTO audio_files 
                   (file_path, title, artist, album, album_art_url, metadata_source, duration, artist_image_url) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    file_path,
                    features.get("title", ""),
                    features.get("artist", ""),
                    features.get("album", ""),
                    features.get("album_art_url", ""),
                    features.get("metadata_source", "unknown"),
                    features.get("duration", 0),
                    features.get("artist_image_url", "")
                ),
                in_memory=self.in_memory,
                cache_size_mb=self.cache_size_mb
            )
            
            # Insert or replace the audio features
            execute_write(
                self.db_path,
                '''INSERT OR REPLACE INTO audio_features
                   (file_id, tempo, key, mode, time_signature, energy, danceability, brightness, noisiness)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    file_id,
                    features.get("tempo", 0),
                    features.get("key", 0),
                    features.get("mode", 0),
                    features.get("time_signature", 4),
                    features.get("energy", 0),
                    features.get("danceability", 0),
                    features.get("brightness", 0),
                    features.get("noisiness", 0)
                ),
                in_memory=self.in_memory,
                cache_size_mb=self.cache_size_mb
            )
            
            return file_id
        except Exception as e:
            logger.error(f"Error saving features to database: {e}")
            raise
    
    def analyze_directory(self, directory: str, recursive: bool = True, extensions: List[str] = ['.mp3', '.wav', '.flac', '.ogg'], batch_size: int = 100):
        """
        Analyze audio files in a directory using batch processing for DB checks.
        """
        files_processed = 0
        tracks_added = 0
        
        # Collect audio files
        audio_files = []
        
        # [existing code to collect files]
        
        # Process files in batches using the optimized connection
        for i in range(0, len(audio_files), batch_size):
            batch = audio_files[i:i+batch_size]
            
            # Check which files already exist in the database
            placeholders = ','.join(['?'] * len(batch))
            existing_files = execute_query(
                self.db_path,
                f"SELECT file_path FROM audio_files WHERE file_path IN ({placeholders})",
                batch,
                in_memory=self.in_memory,
                cache_size_mb=self.cache_size_mb
            )
            existing_file_paths = {row[0] for row in existing_files}
            
            # Process only new files
            for file_path in batch:
                files_processed += 1
                
                if file_path in existing_file_paths:
                    print(f"Skipping {file_path}, it already exists in the database.")
                    continue
                
                print(f"Analyzing {file_path}...")
                try:
                    # Analyze the file
                    features = self._analyze_file_without_db_check(file_path)
                    if features and 'error' not in features:
                        # Save to database directly using execute_write
                        self._save_to_db(features)
                        tracks_added += 1
                except Exception as e:
                    print(f"Error analyzing {file_path}: {e}")
        
        print(f"Processed {files_processed} files, added {tracks_added} new tracks.")
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
            
            # Fetch artist image if available
            artist_image_url = None
            if features["artist"]:
                if self.lastfm_service:
                    artist_image_url = self.lastfm_service.get_artist_image_url(features["artist"])
                if not artist_image_url and self.spotify_service:
                    artist_image_url = self.spotify_service.get_artist_image_url(features["artist"])
            
            features["artist_image_url"] = artist_image_url
            
            return features
            
        except Exception as e:
            print(f"Error analyzing {file_path}: {e}")
            return {"error": str(e)}

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

    def scan_library(self, directory: str, recursive: bool = True, 
                     extensions: List[str] = ['.mp3', '.wav', '.flac', '.ogg'], 
                     batch_size: int = 100):
        """Scan a directory for audio files and add them to the database."""
        global analysis_progress
        
        # Try to acquire the lock, but don't block if we can't
        if not scan_mutex.acquire(blocking=False):
            logger.warning("Another scan is already running. Skipping this scan request.")
            return {
                'files_processed': 0,
                'files_added': 0,
                'files_updated': 0,
                'files_skipped': 0,
                'errors': 0,
                'status': 'skipped'
            }
        
        try:
            # DEBUGGING logs 
            logger.info(f"Starting scan_library with directory: {directory}")
            logger.info(f"Directory exists: {os.path.exists(directory)}")
            logger.info(f"Directory is dir: {os.path.isdir(directory)}")
            logger.info(f"Looking for extensions: {extensions}")
            
            # Get valid audio files
            all_files = []
            
            # Debug the file collection process
            try:
                if recursive:
                    # Recursive scan
                    for root, dirs, files in os.walk(directory):
                        # Debug first few directories found
                        if len(all_files) == 0:
                            logger.info(f"Walking directory: {root}, found {len(files)} files")
                        
                        for file in files:
                            file_path = os.path.join(root, file)
                            file_ext = os.path.splitext(file_path)[1].lower()
                            
                            if file_ext in extensions:
                                all_files.append(file_path)
                                
                                # Log the first few files found for debugging
                                if len(all_files) <= 5:
                                    logger.info(f"Found audio file: {file_path}")
                else:
                    # Non-recursive scan - just files in the top directory
                    for file in os.listdir(directory):
                        file_path = os.path.join(directory, file)
                        if os.path.isfile(file_path):
                            file_ext = os.path.splitext(file_path)[1].lower()
                            
                            if file_ext in extensions:
                                all_files.append(file_path)
                                
                                # Log the first few files found for debugging
                                if len(all_files) <= 5:
                                    logger.info(f"Found audio file: {file_path}")
                                    
                logger.info(f"Total files found with extensions {extensions}: {len(all_files)}")
            except Exception as e:
                logger.error(f"Error collecting audio files: {e}")
            
            # Update progress tracking
            analysis_progress['total_files'] = len(all_files)
            analysis_progress['is_running'] = True
            analysis_progress['stop_requested'] = False
            analysis_progress['analyzed_count'] = 0
            analysis_progress['failed_count'] = 0
            
            logger.info(f"Found {len(all_files)} audio files to process")
            
            # Create tables if they don't exist
            execute_write(
                self.db_path,
                '''CREATE TABLE IF NOT EXISTS audio_files (
                    id INTEGER PRIMARY KEY,
                    file_path TEXT UNIQUE,
                    title TEXT,
                    artist TEXT,
                    album TEXT,
                    duration REAL,
                    date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata_source TEXT DEFAULT 'local_file',
                    album_art_url TEXT,
                    artist_image_url TEXT
                )''',
                in_memory=self.in_memory,
                cache_size_mb=self.cache_size_mb
            )
            
            execute_write(
                self.db_path,
                '''CREATE TABLE IF NOT EXISTS audio_features (
                    file_id INTEGER PRIMARY KEY,
                    tempo REAL,
                    loudness REAL,
                    key INTEGER,
                    mode INTEGER,
                    time_signature INTEGER,
                    energy REAL,
                    danceability REAL,
                    brightness REAL,
                    noisiness REAL,
                    FOREIGN KEY (file_id) REFERENCES audio_files(id)
                )''',
                in_memory=self.in_memory,
                cache_size_mb=self.cache_size_mb
            )
            
            # Create index on file_path for faster lookups
            execute_write(
                self.db_path,
                'CREATE INDEX IF NOT EXISTS idx_file_path ON audio_files(file_path)',
                in_memory=self.in_memory,
                cache_size_mb=self.cache_size_mb
            )
            
            # Batch process files
            processed_count = 0
            added_count = 0
            updated_count = 0
            skipped_count = 0
            error_count = 0
            
            for i in range(0, len(all_files), batch_size):
                batch = all_files[i:i+batch_size]
                
                # Skip empty batches
                if not batch:
                    continue
                    
                # Process the batch using a transaction context
                with transaction_context(self.db_path, self.in_memory, self.cache_size_mb) as (conn, cursor):
                    # Get existing files in this batch
                    placeholders = ','.join(['?'] * len(batch))
                    cursor.execute(
                        f"SELECT id, file_path FROM audio_files WHERE file_path IN ({placeholders})",
                        batch
                    )
                    existing_files = cursor.fetchall()
                    existing_file_dict = {row[1]: row[0] for row in existing_files}
                    
                    for file_path in batch:
                        if analysis_progress['stop_requested']:
                            logger.info("Analysis stopped by user request")
                            break
                            
                        # Update progress
                        analysis_progress['current_file_index'] = i + batch.index(file_path)
                        
                        try:
                            # Check if file is already in database
                            file_id = existing_file_dict.get(file_path)
                            
                            # Check for features if file exists
                            has_features = False
                            if file_id:
                                cursor.execute('SELECT file_id FROM audio_features WHERE file_id = ?', (file_id,))
                                has_features = cursor.fetchone() is not None
                            
                            if file_id and has_features:
                                # Skip if file already exists and has features
                                logger.debug(f"Skipping {file_path}, it already exists with features")
                                skipped_count += 1
                            else:
                                # Extract basic metadata
                                try:
                                    audio = mutagen.File(file_path)
                                    metadata = self._extract_metadata(audio, file_path)
                                    
                                    if file_id:
                                        # Update existing entry
                                        cursor.execute('''
                                            UPDATE audio_files SET 
                                            title = ?, artist = ?, album = ?, duration = ?
                                            WHERE id = ?
                                        ''', (
                                            metadata.get('title', ''),
                                            metadata.get('artist', ''),
                                            metadata.get('album', ''),
                                            metadata.get('duration', 0),
                                            file_id
                                        ))
                                        updated_count += 1
                                    else:
                                        # Add new entry
                                        cursor.execute('''
                                            INSERT INTO audio_files (file_path, title, artist, album, duration)
                                            VALUES (?, ?, ?, ?, ?)
                                        ''', (
                                            file_path,
                                            metadata.get('title', ''),
                                            metadata.get('artist', ''),
                                            metadata.get('album', ''),
                                            metadata.get('duration', 0)
                                        ))
                                        file_id = cursor.lastrowid
                                        added_count += 1
                                    
                                    # Add placeholder features if needed
                                    if not has_features:
                                        # Insert placeholder features
                                        cursor.execute('''
                                            INSERT OR REPLACE INTO audio_features 
                                            (file_id, tempo, loudness, key, mode, time_signature, 
                                            energy, danceability, brightness, noisiness)
                                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                        ''', (
                                            file_id, 0.0, 0.0, 0, 0, 4, 0.0, 0.0, 0.0, 0.0
                                        ))
                                    
                                    analysis_progress['analyzed_count'] += 1
                                    
                                except Exception as e:
                                    logger.error(f"Error processing file {file_path}: {e}")
                                    error_count += 1
                                    analysis_progress['failed_count'] += 1
                                    continue
                                
                            processed_count += 1
                            
                        except Exception as e:
                            logger.error(f"Error processing {file_path}: {e}")
                            error_count += 1
                            analysis_progress['failed_count'] += 1
                
                # Check if we need to stop after each batch
                if analysis_progress['stop_requested']:
                    break
            
            # If using in-memory database, explicitly save to disk
                if self.in_memory:
                    with optimized_connection(self.db_path, in_memory=self.in_memory, cache_size_mb=self.cache_size_mb) as conn:
                        from db_utils import trigger_db_save
                        trigger_db_save(conn, self.db_path)
                        logger.info("Explicitly saved in-memory database to disk after scan")

                # Get the in-memory connection if it exists in thread local storage
                from threading import local
                thread_data = local()
                
                if hasattr(thread_data, 'conn'):
                    trigger_db_save(thread_data.conn, self.db_path)
                    logger.info("Explicitly saved in-memory database to disk after scan")
            
            # Update progress
            analysis_progress['is_running'] = False
            analysis_progress['last_run_completed'] = True
            
            logger.info(f"Scan complete: {processed_count} processed, {added_count} added, {updated_count} updated, {skipped_count} skipped, {error_count} errors")
            
            return {
                'files_processed': processed_count,
                'files_added': added_count,
                'files_updated': updated_count,
                'files_skipped': skipped_count,
                'errors': error_count
            }
        finally:
            # Always release the lock, even if an exception occurs
            scan_mutex.release()

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
            self.db_path,
            "SELECT COUNT(*) as count FROM audio_files WHERE analysis_status = 'analyzed'",
            in_memory=self.in_memory,
            cache_size_mb=self.cache_size_mb
        )['count']
        
        analysis_progress['analyzed_count'] = already_analyzed

        logger.info(f"Starting full analysis of pending files - already analyzed: {already_analyzed}")
        
        # CRITICAL FIX: Get the pending files BEFORE using total_pending
        pending_files = execute_query(
            self.db_path,
            '''SELECT id, file_path
               FROM audio_files
               WHERE analysis_status = 'pending'
               ORDER BY date_added DESC''',
            in_memory=self.in_memory,
            cache_size_mb=self.cache_size_mb
        )
        
        # NOW calculate total_pending
        total_pending = len(pending_files)
        
        if limit:
            pending_files = pending_files[:limit]
        
        analysis_progress['total_files'] = already_analyzed + total_pending
        analysis_progress['pending_count'] = total_pending
        
        # NOW update the status dictionary with total_pending
        if status_dict:
            status_dict.update({
                'running': True,
                'total_files': total_pending,
                'current_file': '',
                'percent_complete': 0,
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
                    'files_processed': i + 1,
                    'current_file': os.path.basename(file_path),
                    'percent_complete': int(((i + 1) / total_pending) * 100) if total_pending > 0 else 100,
                    'last_updated': datetime.now().isoformat(),
                    'scan_complete': True  # Add this line to ensure flag stays set
                })
            
            logger.info(f"Analyzing file {i+1}/{len(pending_files)}: {file_path}")
            
            try:
                # Use a separate transaction for each file
                with transaction_context(self.db_path, self.in_memory, self.cache_size_mb) as (conn, cursor):
                    # Analyze the file
                    features = self._analyze_file_without_db_check(file_path)
                    
                    if features and 'error' not in features:
                        # Update the file's analysis status
                        cursor.execute(
                            "UPDATE audio_files SET analysis_status = 'analyzed' WHERE id = ?",
                            (file_id,)
                        )
                        
                        # Insert the features
                        cursor.execute(
                            '''INSERT OR REPLACE INTO audio_features
                               (file_id, tempo, key, mode, time_signature, energy, danceability, brightness, noisiness, loudness)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                            (
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
                            )
                        )
                        
                        analyzed_count += 1
                        analysis_progress['analyzed_count'] += 1
                        consecutive_errors = 0
                        logger.info(f"Successfully analyzed: {os.path.basename(file_path)}")
                    else:
                        # Mark as failed
                        cursor.execute(
                            "UPDATE audio_files SET analysis_status = 'failed' WHERE id = ?",
                            (file_id,)
                        )
                        error_count += 1
                        analysis_progress['failed_count'] += 1
                        consecutive_errors += 1
                        logger.warning(f"Failed to analyze: {os.path.basename(file_path)} - {features.get('error', 'Unknown error')}")
                
                # Save in-memory database every 5 files
                if self.in_memory and analyzed_count % 5 == 0:
                    with optimized_connection(self.db_path, in_memory=self.in_memory, cache_size_mb=self.cache_size_mb) as conn:
                        from db_utils import trigger_db_save
                        trigger_db_save(conn, self.db_path)
                        logger.info(f"Saved in-memory database after {analyzed_count} files")
                    
            except Exception as e:
                logger.error(f"Error analyzing {file_path}: {e}")
                # Use a separate transaction to update the status
                with transaction_context(self.db_path, self.in_memory, self.cache_size_mb) as (conn, cursor):
                    cursor.execute(
                        "UPDATE audio_files SET analysis_status = 'failed' WHERE id = ?",
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
            self.db_path,
            '''SELECT af.id
               FROM audio_files af
               LEFT JOIN audio_features feat ON af.id = feat.file_id
               WHERE feat.file_id IS NULL''',
            in_memory=self.in_memory,
            cache_size_mb=self.cache_size_mb
        ))
        
        analysis_progress['pending_count'] = remaining_pending
        analysis_progress['is_running'] = False
        analysis_progress['last_run_completed'] = True
        
        logger.info(f"Analysis complete: {analyzed_count} files analyzed, {error_count} errors, {remaining_pending} still pending")
        
        # Final save of in-memory database
        if self.in_memory:
            with optimized_connection(self.db_path, in_memory=self.in_memory, cache_size_mb=self.cache_size_mb) as conn:
                from db_utils import trigger_db_save
                trigger_db_save(conn, self.db_path)
                logger.info("Saved in-memory database after completing analysis")
        
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
            with transaction_context(self.db_path, self.in_memory, self.cache_size_mb) as (conn, cursor):
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
                    AND id IN (SELECT file_id FROM audio_features WHERE 
                               tempo > 0 OR energy > 0 OR danceability > 0)
                ''')
                
                # Get count after fix
                cursor.execute("SELECT COUNT(*) FROM audio_files WHERE analysis_status = 'pending'")
                after_count = cursor.fetchone()[0]
                
                logger.info(f"Database consistency check: {before_count} pending files before, {after_count} after fix")
                
                # Save changes immediately if in-memory
                if self.in_memory:
                    from db_utils import trigger_db_save
                    trigger_db_save(conn, self.db_path)
        except Exception as e:
            logger.error(f"Error fixing database inconsistencies: {e}")

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
            
        return metadata

def main():
    """Main function to demonstrate usage of the MusicAnalyzer."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Analyze music files and create playlists.')
    parser.add_argument('folders', nargs='+', default=["90s Happy Hits"], 
                      help='Path to folders containing audio files')
    parser.add_argument('-r', '--recursive', action='store_true', 
                      help='Recursively analyze subfolders')
    parser.add_argument('-n', '--num-tracks', type=int, default=5,
                      help='Number of tracks to include in created station')
    args = parser.parse_args()
    
    analyzer = MusicAnalyzer()
    all_audio_files = []
    
    # Process each specified folder
    for folder_path in args.folders:
        if not os.path.exists(folder_path):
            print(f"WARNING: Folder '{folder_path}' does not exist. Skipping.")
            continue
        
        # Get list of audio files
        audio_extensions = ['.mp3', '.wav', '.flac', '.ogg']
        audio_files = []
        
        # Use os.walk for recursive or os.listdir for non-recursive
        if args.recursive:
            for root, _, files in os.walk(folder_path):
                for file in files:
                    if any(file.lower().endswith(ext) for ext in audio_extensions):
                        audio_files.append(os.path.join(root, file))
        else:
            for file in os.listdir(folder_path):
                file_path = os.path.join(folder_path, file)
                if os.path.isfile(file_path) and any(file.lower().endswith(ext) for ext in audio_extensions):
                    audio_files.append(file_path)
        
        if not audio_files:
            print(f"No audio files found in '{folder_path}'. Skipping.")
            continue
        
        print(f"Found {len(audio_files)} audio files in '{folder_path}'")
        all_audio_files.extend(audio_files)
        
        # Analyze the folder
        print(f"Starting analysis of '{folder_path}'...")
        analyzer.analyze_directory(folder_path, recursive=args.recursive)
    
    if not all_audio_files:
        print("No audio files found in any of the specified folders.")
        return
        
    print("Analysis complete! Database saved to music_features.db")
    
    # Create a station from the first track
    first_track = all_audio_files[0] if all_audio_files else None
    if (first_track):
        print(f"Creating a station based on: {os.path.basename(first_track)}")
        station = analyzer.create_station(first_track, num_tracks=args.num_tracks)
        print(f"\nStation based on {os.path.basename(first_track)}:")
        for i, track in enumerate(station, 1):
            print(f"{i}. {os.path.basename(track)}")
    else:
        print("No tracks found, cannot create a station.")


if __name__ == "__main__":
    main()