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

import librosa.display
import matplotlib.pyplot as plt
from metadata_service import MetadataService

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


class MusicAnalyzer:
    """
    A class for analyzing music files and extracting audio features for music categorization.
    """

    def __init__(self, db_path: str = "pump.db"):
        """
        Initialize the MusicAnalyzer.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
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
        """Create database tables if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create table for audio files with analysis_status field
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS audio_files (
            id INTEGER PRIMARY KEY,
            file_path TEXT UNIQUE,
            title TEXT,
            artist TEXT,
            album TEXT,
            album_art_url TEXT,
            metadata_source TEXT,
            duration REAL,
            date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            analysis_status TEXT DEFAULT 'pending'
        )
        ''')
        
        # Add analysis_status column if it doesn't exist
        try:
            cursor.execute("PRAGMA table_info(audio_files)")
            columns = [column[1] for column in cursor.fetchall()]
            if 'analysis_status' not in columns:
                cursor.execute('ALTER TABLE audio_files ADD COLUMN analysis_status TEXT DEFAULT "pending"')
                conn.commit()
        except Exception as e:
            logging.error(f"Error adding analysis_status column: {e}")
        
        # Add artist_image_url column if it doesn't exist
        try:
            cursor.execute("PRAGMA table_info(audio_files)")
            columns = [column[1] for column in cursor.fetchall()]
            if 'artist_image_url' not in columns:
                cursor.execute('''
                ALTER TABLE audio_files ADD COLUMN artist_image_url TEXT
                ''')
                conn.commit()
        except Exception as e:
            logging.error(f"Error adding artist_image_url column: {e}")
        
        # Create table for audio features
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
            FOREIGN KEY (file_id) REFERENCES audio_files (id)
        )
        ''')
        
        # Create table for playlists
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS playlists (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Create table for playlist items
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
        
        conn.commit()
        conn.close()
    
    def analyze_file(self, file_path: str, save_to_db: bool = True) -> Dict:
        """
        Analyze a music file and extract its features, but skip if it's already in the database.
        """
        # 1) Check if file has already been analyzed
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM audio_files WHERE file_path = ?", (file_path,))
        row = cursor.fetchone()
        conn.close()

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
        """Save audio features to the database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
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
        
        # Insert audio features
        cursor.execute('''
            INSERT OR REPLACE INTO audio_features
            (file_id, tempo, key, mode, time_signature, energy, danceability, brightness, noisiness)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            file_id,
            features.get("tempo", 0),
            features.get("key", 0),
            features.get("mode", 0),
            features.get("time_signature", 4),
            features.get("energy", 0),
            features.get("danceability", 0),
            features.get("brightness", 0),
            features.get("noisiness", 0)
        ))
        
        conn.commit()
        conn.close()
    
    def analyze_directory(self, directory: str, recursive: bool = True, extensions: List[str] = ['.mp3', '.wav', '.flac', '.ogg'], batch_size: int = 100):
        """
        Analyze audio files in a directory using batch processing for DB checks.
        
        Args:
            directory: Directory path containing audio files
            recursive: Whether to analyze subdirectories
            extensions: List of file extensions to process
            batch_size: Number of files to check against DB at once
            
        Returns:
            Dict with statistics about processed files
        """
        files_processed = 0
        tracks_added = 0
        
        # First, collect all valid audio files
        audio_files = []
        
        if os.path.exists(directory):
            if recursive:
                for root, _, files in os.walk(directory):
                    for file in files:
                        if any(file.lower().endswith(ext) for ext in extensions):
                            file_path = os.path.join(root, file)
                            audio_files.append(file_path)
            else:
                for file in os.listdir(directory):
                    file_path = os.path.join(directory, file)
                    if os.path.isfile(file_path) and any(file.lower().endswith(ext) for ext in extensions):
                        audio_files.append(file_path)
        else:
            print(f"WARNING: Folder '{directory}' does not exist. Skipping.")
            return {'files_processed': 0, 'tracks_added': 0}
        
        if not audio_files:
            print(f"No audio files found in '{directory}'. Skipping.")
            return {'files_processed': 0, 'tracks_added': 0}
        
        print(f"Found {len(audio_files)} audio files in '{directory}'")
        
        # Process files in batches to avoid too many DB connections
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for i in range(0, len(audio_files), batch_size):
            batch = audio_files[i:i+batch_size]
            
            # Check which files in this batch already exist in the DB
            placeholders = ','.join(['?'] * len(batch))
            cursor.execute(f"SELECT file_path FROM audio_files WHERE file_path IN ({placeholders})", batch)
            existing_files = {row[0] for row in cursor.fetchall()}
            
            # Process only new files
            for file_path in batch:
                files_processed += 1
                
                if file_path in existing_files:
                    print(f"Skipping {file_path}, it already exists in the database.")
                    continue
                
                print(f"Analyzing {file_path}...")
                try:
                    # Analyze the file using the existing method but with our open connection
                    features = self._analyze_file_without_db_check(file_path)
                    if features and 'error' not in features:
                        self._save_to_db_with_connection(features, conn, cursor)
                        tracks_added += 1
                except Exception as e:
                    print(f"Error analyzing {file_path}: {e}")
        
        # Commit all changes and close the connection
        conn.commit()
        conn.close()
        
        print(f"Processed {files_processed} files, added {tracks_added} new tracks.")
        return {
            'files_processed': files_processed,
            'tracks_added': tracks_added
        }
    
    def create_station(self, seed_track_path: str, num_tracks: int = 10) -> List[str]:
        """
        Create a music station based on a seed track.
        
        Args:
            seed_track_path: Path to the seed track
            num_tracks: Number of tracks to include in the station
            
        Returns:
            List of file paths for the station playlist
        """
        # First analyze the seed track if not already in DB
        seed_features = self.analyze_file(seed_track_path)
        
        # Connect to the database
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get all tracks from the database
        cursor.execute('''
        SELECT af.file_path, ft.*
        FROM audio_files af
        JOIN audio_features ft ON af.id = ft.file_id
        WHERE af.file_path != ?
        ''', (seed_track_path,))
        
        tracks = cursor.fetchall()
        conn.close()
        
        if not tracks:
            return [seed_track_path]  # Return only seed track if no others available
        
        # Calculate similarity to seed track for each track
        similarities = []
        for track in tracks:
            similarity = self._calculate_similarity(seed_features, dict(track))
            similarities.append((track['file_path'], similarity))
        
        # Sort by similarity (descending) and get top tracks
        similarities.sort(key=lambda x: x[1], reverse=True)
        station_tracks = [seed_track_path] + [t[0] for t in similarities[:num_tracks-1]]
        
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
        
        # Insert audio features
        cursor.execute('''
            INSERT OR REPLACE INTO audio_features
            (file_id, tempo, key, mode, time_signature, energy, danceability, brightness, noisiness)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            file_id,
            features.get("tempo", 0),
            features.get("key", 0),
            features.get("mode", 0),
            features.get("time_signature", 4),
            features.get("energy", 0),
            features.get("danceability", 0),
            features.get("brightness", 0),
            features.get("noisiness", 0)
        ))
        
        # Note: We don't commit here as it will be done in batches by the calling function

    def scan_library(self, directory: str, recursive: bool = True, 
                     extensions: List[str] = ['.mp3', '.wav', '.flac', '.ogg'], 
                     batch_size: int = 100):
        """
        Quickly scan a directory and add files to the library without full audio analysis.
        Only reads basic metadata from files.
        
        Args:
            directory: Directory path containing audio files
            recursive: Whether to scan subdirectories
            extensions: List of file extensions to process
            batch_size: Number of files to check against DB at once
                
        Returns:
            Dict with statistics about processed files
        """
        files_processed = 0
        tracks_added = 0
        
        # First, collect all valid audio files (same as your analyze_directory method)
        audio_files = []
        
        if os.path.exists(directory):
            if recursive:
                for root, _, files in os.walk(directory):
                    for file in files:
                        if any(file.lower().endswith(ext) for ext in extensions):
                            file_path = os.path.join(root, file)
                            audio_files.append(file_path)
            else:
                for file in os.listdir(directory):
                    file_path = os.path.join(directory, file)
                    if os.path.isfile(file_path) and any(file.lower().endswith(ext) for ext in extensions):
                        audio_files.append(file_path)
        else:
            print(f"WARNING: Folder '{directory}' does not exist. Skipping.")
            return {'files_processed': 0, 'tracks_added': 0}
        
        if not audio_files:
            print(f"No audio files found in '{directory}'. Skipping.")
            return {'files_processed': 0, 'tracks_added': 0}
        
        print(f"Found {len(audio_files)} audio files in '{directory}'")
        
        # Process files in batches to avoid too many DB connections
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for i in range(0, len(audio_files), batch_size):
            batch = audio_files[i:i+batch_size]
            
            # Check which files in this batch already exist in the DB
            placeholders = ','.join(['?'] * len(batch))
            cursor.execute(f"SELECT file_path FROM audio_files WHERE file_path IN ({placeholders})", batch)
            existing_files = {row[0] for row in cursor.fetchall()}
            
            # Process only new files
            for file_path in batch:
                files_processed += 1
                
                if file_path in existing_files:
                    print(f"Skipping {file_path}, it already exists in the database.")
                    continue
                
                print(f"Indexing {file_path}...")
                try:
                    # Only extract metadata from the file (lightweight operation)
                    metadata = self.metadata_service.get_metadata_from_file(file_path)
                    
                    # Save basic metadata to DB with 'pending' analysis status
                    cursor.execute('''
                        INSERT OR IGNORE INTO audio_files 
                        (file_path, title, artist, album, metadata_source, analysis_status) 
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (
                        file_path,
                        metadata.get("title", ""),
                        metadata.get("artist", ""),
                        metadata.get("album", ""),
                        "file",  # Source is just the file metadata
                        "pending"  # Mark as pending full analysis
                    ))
                    
                    if cursor.rowcount > 0:
                        tracks_added += 1
                        
                except Exception as e:
                    print(f"Error scanning {file_path}: {e}")
        
        # Commit all changes and close the connection
        conn.commit()
        conn.close()
        
        print(f"Processed {files_processed} files, added {tracks_added} new tracks.")
        return {
            'files_processed': files_processed,
            'tracks_added': tracks_added
        }

    def analyze_pending_files(self, limit: Optional[int] = None, 
                              batch_size: int = 10, 
                              max_errors: int = 3,
                              progress_callback = None):
        """
        Analyze files that have been indexed but not yet analyzed.
        Can be run as a background task.
        
        Args:
            limit: Maximum number of files to analyze (None for all)
            batch_size: Number of files to process in each batch
            max_errors: Maximum consecutive errors before stopping
            progress_callback: Function to call to report progress (optional)
                
        Returns:
            Dict with statistics about processed files
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get count of pending files
        cursor.execute("SELECT COUNT(*) FROM audio_files WHERE analysis_status = 'pending'")
        total_pending = cursor.fetchone()[0]
        
        if limit:
            total_pending = min(total_pending, limit)
        
        if total_pending == 0:
            print("No pending files to analyze.")
            conn.close()
            return {'analyzed': 0, 'failed': 0, 'remaining': 0}
        
        print(f"Found {total_pending} files pending analysis")
        
        # Process in batches
        query = "SELECT file_path FROM audio_files WHERE analysis_status = 'pending'"
        if limit:
            query += f" LIMIT {limit}"
        
        cursor.execute(query)
        pending_files = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        analyzed_count = 0
        failed_count = 0
        consecutive_errors = 0
        
        # Check for stop flag in the global state
        def should_stop():
            global analysis_progress
            return analysis_progress.get('stop_requested', False)
        
        for i, file_path in enumerate(pending_files):
            # Check if we should stop
            if should_stop():
                print("Analysis stopped by user request")
                break
                
            try:
                print(f"Analyzing {i+1}/{len(pending_files)}: {file_path}")
                
                # Skip files that don't exist
                if not os.path.exists(file_path):
                    raise FileNotFoundError(f"[Errno 2] No such file or directory: '{file_path}'")
                
                # Report progress if callback provided
                if progress_callback:
                    progress_callback(i+1, 'processing')
                
                # Use the full analysis method
                features = self._analyze_file_for_features(file_path)
                
                # Update the database with analysis results and status
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                # Update analysis status
                cursor.execute(
                    "UPDATE audio_files SET analysis_status = ? WHERE file_path = ?", 
                    ("analyzed", file_path)
                )
                
                # Get the ID of the audio file
                cursor.execute("SELECT id FROM audio_files WHERE file_path = ?", (file_path,))
                file_id = cursor.fetchone()[0]
                
                # Insert audio features
                cursor.execute('''
                    INSERT OR REPLACE INTO audio_features
                    (file_id, tempo, key, mode, time_signature, energy, danceability, brightness, noisiness)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    file_id,
                    features.get("tempo", 0),
                    features.get("key", 0),
                    features.get("mode", 0),
                    features.get("time_signature", 4),
                    features.get("energy", 0),
                    features.get("danceability", 0),
                    features.get("brightness", 0),
                    features.get("noisiness", 0)
                ))
                
                conn.commit()
                conn.close()
                
                analyzed_count += 1
                consecutive_errors = 0  # Reset error counter on success
                
                # Report success if callback provided
                if progress_callback:
                    progress_callback(i+1, 'analyzed')
                
            except Exception as e:
                print(f"Error analyzing {file_path}: {e}")
                
                # Mark as failed in DB
                try:
                    conn = sqlite3.connect(self.db_path)
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE audio_files SET analysis_status = ? WHERE file_path = ?", 
                        ("failed", file_path)
                    )
                    conn.commit()
                    conn.close()
                except Exception as db_error:
                    print(f"Error updating DB status: {db_error}")
                    
                failed_count += 1
                consecutive_errors += 1
                
                # Report failure if callback provided
                if progress_callback:
                    progress_callback(i+1, 'failed')
                
                # Stop if too many consecutive errors
                if consecutive_errors >= max_errors:
                    print(f"Too many consecutive errors ({max_errors}). Stopping analysis.")
                    break
        
        # Get count of remaining pending files
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM audio_files WHERE analysis_status = 'pending'")
        remaining = cursor.fetchone()[0]
        conn.close()
        
        print(f"Analysis complete: {analyzed_count} analyzed, {failed_count} failed, {remaining} remaining")
        return {
            'analyzed': analyzed_count,
            'failed': failed_count,
            'remaining': remaining
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