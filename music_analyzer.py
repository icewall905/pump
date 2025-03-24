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
from datetime import datetime  # Add this missing import
from lastfm_service import LastFMService
from spotify_service import SpotifyService
from metadata_service import MetadataService
from db_utils import get_optimized_connection, optimized_connection, trigger_db_save

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

class MusicAnalyzer:
    """Class for analyzing audio files and extracting features"""
    
    def __init__(self, db_path, in_memory=False, cache_size_mb=75):
        """Initialize the analyzer with database path"""
        self.db_path = db_path
        self.in_memory = in_memory
        self.cache_size_mb = cache_size_mb
        self.lastfm_service = None
        self.spotify_service = None
        self.metadata_service = None
        
        # Create database connection for this instance
        self.db_conn = get_optimized_connection(db_path, in_memory, cache_size_mb)
        
        # Initialize database tables if they don't exist
        self._ensure_tables_exist()
        
        try:
            # Initialize LastFM and Spotify services if available
            import configparser
            config = configparser.ConfigParser()
            if os.path.exists('pump.conf'):
                config.read('pump.conf')
                
                # LastFM service
                lastfm_key = config.get('lastfm', 'api_key', fallback='')
                lastfm_secret = config.get('lastfm', 'api_secret', fallback='')
                if lastfm_key and lastfm_secret:
                    self.lastfm_service = LastFMService(lastfm_key, lastfm_secret)
                
                # Spotify service
                spotify_id = config.get('spotify', 'client_id', fallback='')
                spotify_secret = config.get('spotify', 'client_secret', fallback='')
                if spotify_id and spotify_secret:
                    self.spotify_service = SpotifyService(spotify_id, spotify_secret)
                    
                # Metadata service for getting album art, etc.
                self.metadata_service = MetadataService(config_file='pump.conf')
        except Exception as e:
            logger.error(f"Error initializing services: {e}")
    
    def _ensure_tables_exist(self):
        """Make sure the database tables for analysis exist"""
        try:
            cursor = self.db_conn.cursor()
            
            # Table for audio files
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
                metadata_source TEXT,
                analysis_status TEXT DEFAULT 'pending', 
                liked INTEGER DEFAULT 0
            )
            ''')
            
            # Table for audio features
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS audio_features (
                id INTEGER PRIMARY KEY,
                file_id INTEGER,
                file_path TEXT,
                tempo REAL,
                key INTEGER,
                mode INTEGER,
                time_signature INTEGER,
                acousticness REAL,
                danceability REAL,
                energy REAL,
                instrumentalness REAL,
                loudness REAL,
                speechiness REAL,
                valence REAL,
                date_analyzed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (file_id) REFERENCES audio_files(id)
            )
            ''')
            
            # Indexes for performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_path ON audio_files(file_path)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_analysis_status ON audio_files(analysis_status)")
            
            self.db_conn.commit()
            logger.info("Database tables initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing database tables: {e}")
    
    def scan_library(self, directory: str, recursive: bool = True) -> Dict:
        """
        Scan a directory for audio files and add them to the database.
        Only detects files, does not perform full analysis.
        
        Args:
            directory: Path to the music directory
            recursive: Whether to scan recursively
            
        Returns:
            Dict with results: {processed: int, added: int}
        """
        logger.info(f"Starting quick scan of {directory} (recursive={recursive})")
        
        processed = 0
        added = 0
        
        supported_extensions = ['.mp3', '.flac', '.wav', '.ogg', '.m4a', '.aac']
        
        # Update scan status
        from web_player import QUICK_SCAN_STATUS
        QUICK_SCAN_STATUS.update({
            'running': True,
            'files_processed': 0,
            'tracks_added': 0,
            'total_files': 0,
            'current_file': '',
            'percent_complete': 0
        })
        
        try:
            # Count files first to give accurate progress
            total_files = 0
            
            if recursive:
                for root, _, files in os.walk(directory):
                    for file in files:
                        if os.path.splitext(file)[1].lower() in supported_extensions:
                            total_files += 1
            else:
                for file in os.listdir(directory):
                    if os.path.isfile(os.path.join(directory, file)) and \
                       os.path.splitext(file)[1].lower() in supported_extensions:
                        total_files += 1
            
            # Update status with total files
            QUICK_SCAN_STATUS.update({
                'total_files': total_files
            })
            
            # Process files
            def process_file(file_path):
                nonlocal processed, added
                nonlocal QUICK_SCAN_STATUS
                
                # Update status with current file
                file_name = os.path.basename(file_path)
                QUICK_SCAN_STATUS.update({
                    'current_file': file_name,
                    'files_processed': processed
                })
                
                # Check if file is already in database
                cursor = self.db_conn.cursor()
                cursor.execute("SELECT id FROM audio_files WHERE file_path = ?", (file_path,))
                if cursor.fetchone():
                    processed += 1
                    return
                
                try:
                    # Basic info from file path
                    file_name = os.path.basename(file_path)
                    file_name_no_ext = os.path.splitext(file_name)[0]
                    
                    # Get metadata from file
                    metadata = self._get_basic_metadata(file_path)
                    
                    # Insert into database
                    cursor.execute('''
                    INSERT INTO audio_files 
                    (file_path, title, artist, album, genre, duration, analysis_status)
                    VALUES (?, ?, ?, ?, ?, ?, 'pending')
                    ''', (
                        file_path,
                        metadata.get('title', file_name_no_ext),
                        metadata.get('artist', ''),
                        metadata.get('album', ''),
                        metadata.get('genre', ''),
                        metadata.get('duration', 0)
                    ))
                    
                    processed += 1
                    added += 1
                    
                    # Update status with progress
                    if total_files > 0:
                        percent = (processed / total_files) * 100
                    else:
                        percent = 100
                        
                    QUICK_SCAN_STATUS.update({
                        'files_processed': processed,
                        'tracks_added': added,
                        'percent_complete': percent
                    })
                    
                except Exception as e:
                    logger.error(f"Error processing file {file_path}: {e}")
                    processed += 1
            
            # Walk directory and process files
            if recursive:
                for root, _, files in os.walk(directory):
                    for file in files:
                        file_path = os.path.join(root, file)
                        if os.path.splitext(file)[1].lower() in supported_extensions:
                            process_file(file_path)
                            
                            # Save changes periodically
                            if processed % 10 == 0 and self.in_memory:
                                trigger_db_save(self.db_conn, self.db_path)
            else:
                for file in os.listdir(directory):
                    file_path = os.path.join(directory, file)
                    if os.path.isfile(file_path) and \
                       os.path.splitext(file)[1].lower() in supported_extensions:
                        process_file(file_path)
                        
                        # Save changes periodically
                        if processed % 10 == 0 and self.in_memory:
                            trigger_db_save(self.db_conn, self.db_path)
            
            # Commit changes
            self.db_conn.commit()
            
            # Update final status
            QUICK_SCAN_STATUS.update({
                'running': False,
                'files_processed': processed,
                'tracks_added': added,
                'percent_complete': 100
            })
            
            logger.info(f"Quick scan completed. Processed {processed} files, added {added} tracks to database.")
            
            return {
                'processed': processed,
                'added': added
            }
            
        except Exception as e:
            logger.error(f"Error scanning library: {e}")
            
            # Update error status
            QUICK_SCAN_STATUS.update({
                'running': False,
                'error': str(e)
            })
            
            return {
                'processed': processed,
                'added': added,
                'error': str(e)
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
            from db_utils import get_optimized_connection
            thread_conn = get_optimized_connection(self.db_path, self.in_memory, self.cache_size_mb)
            
            # Get all pending files from database
            thread_conn.row_factory = sqlite3.Row
            cursor = thread_conn.cursor()
            
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
                file_id = file_data['id']
                file_path = file_data['file_path']
                
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
                        thread_conn.commit()
                        analysis_progress['failed_count'] += 1
                        continue
                    
                    # Analyze the file and extract features
                    features = self._extract_audio_features(file_path)
                    
                    if features:
                        # Save features to database directly with this connection
                        cursor.execute('''
                        INSERT INTO audio_features
                        (file_id, file_path, tempo, key, mode, time_signature,
                        acousticness, danceability, energy, instrumentalness, loudness, speechiness, valence)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            file_id, file_path, 
                            features['tempo'], features['key'], features['mode'], features['time_signature'],
                            features['acousticness'], features['danceability'], features['energy'],
                            features['instrumentalness'], features['loudness'], features['speechiness'], features['valence']
                        ))
                        
                        # Update analysis status
                        cursor.execute("UPDATE audio_files SET analysis_status = 'analyzed' WHERE id = ?", (file_id,))
                        thread_conn.commit()
                        
                        analysis_progress['analyzed_count'] += 1
                    else:
                        logger.warning(f"Failed to extract features from {file_path}")
                        cursor.execute("UPDATE audio_files SET analysis_status = 'failed' WHERE id = ?", (file_id,))
                        thread_conn.commit()
                        analysis_progress['failed_count'] += 1
                    
                    # Save changes periodically
                    if i % 5 == 0 and self.in_memory:
                        from db_utils import trigger_db_save
                        trigger_db_save(thread_conn, self.db_path)
                        
                except Exception as e:
                    logger.error(f"Error analyzing file {file_path}: {e}")
                    cursor.execute("UPDATE audio_files SET analysis_status = 'failed' WHERE id = ?", (file_id,))
                    thread_conn.commit()
                    analysis_progress['failed_count'] += 1
            
            # Final commit
            thread_conn.commit()
            
            # Final database save
            if self.in_memory:
                from db_utils import trigger_db_save
                trigger_db_save(thread_conn, self.db_path)
            
            # Close thread connection
            thread_conn.close()
            
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
        """Extract audio features from a file using librosa"""
        try:
            # Limit duration to first 60 seconds for faster processing
            y, sr = librosa.load(file_path, duration=60)
            
            # Extract basic features
            tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
            
            # Get enhanced metadata
            enhanced_metadata = self._get_enhanced_metadata(file_path)
            
            # Extract spectral features
            spectral_features = self._extract_spectral_features(y, sr)
            
            # Combine features
            features = {
                "tempo": tempo,
                "key": spectral_features.get("key", 0),
                "mode": spectral_features.get("mode", 0),
                "time_signature": 4,  # Default to 4/4
                "acousticness": spectral_features.get("acousticness", 0.5),
                "danceability": spectral_features.get("danceability", 0.5),
                "energy": spectral_features.get("energy", 0.5),
                "instrumentalness": spectral_features.get("instrumentalness", 0.5),
                "loudness": spectral_features.get("loudness", -20),
                "speechiness": spectral_features.get("speechiness", 0.5),
                "valence": spectral_features.get("valence", 0.5)
            }
            
            return features
            
        except Exception as e:
            logger.error(f"Error extracting audio features from {file_path}: {e}")
            return None
    
    def _extract_spectral_features(self, y, sr) -> Dict:
        """Extract spectral features from audio signal"""
        features = {}
        
        try:
            # Chromagram
            chroma = librosa.feature.chroma_stft(y=y, sr=sr)
            
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
                acousticness = ?, danceability = ?, energy = ?,
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
                (file_id, file_path, tempo, key, mode, time_signature,
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
            SELECT af.analysis_status FROM audio_files af
            WHERE af.file_path = ?
            ''', (seed_file_path,))
            
            status = cursor.fetchone()
            if not status or status[0] != 'analyzed':
                logger.warning(f"Seed track {seed_file_path} has not been analyzed")
                return []
            
            # Get seed track's features
            cursor.execute('''
            SELECT f.* FROM audio_features f
            JOIN audio_files af ON f.file_path = af.file_path
            WHERE af.file_path = ?
            ''', (seed_file_path,))
            
            seed_features = cursor.fetchone()
            if not seed_features:
                logger.warning(f"No features found for seed track {seed_file_path}")
                return []
            
            # Get all analyzed tracks
            cursor.execute('''
            SELECT af.file_path, f.tempo, f.key, f.mode, f.acousticness, f.danceability,
                   f.energy, f.instrumentalness, f.loudness, f.speechiness, f.valence
            FROM audio_files af
            JOIN audio_features f ON af.file_path = f.file_path
            WHERE af.analysis_status = 'analyzed'
            ''')
            
            tracks = cursor.fetchall()
            
            # Calculate similarity scores
            similarities = []
            for track in tracks:
                if track[0] == seed_file_path:
                    continue  # Skip seed track
                
                # Calculate feature-based similarity
                tempo_diff = abs(track[1] - seed_features[3]) / 200  # Tempo difference
                key_diff = abs(track[2] - seed_features[4]) / 12  # Key difference
                mode_match = 1 if track[3] == seed_features[5] else 0  # Mode match
                
                # Acoustic characteristics
                acousticness_diff = abs(track[4] - seed_features[7])
                danceability_diff = abs(track[5] - seed_features[8])
                energy_diff = abs(track[6] - seed_features[9])
                instrumentalness_diff = abs(track[7] - seed_features[10])
                loudness_diff = abs(track[8] - seed_features[11]) / 60  # Normalize loudness
                speechiness_diff = abs(track[9] - seed_features[12])
                valence_diff = abs(track[10] - seed_features[13])
                
                # Overall similarity score (lower is more similar)
                similarity = (
                    (tempo_diff * 0.1) +
                    (key_diff * 0.1) +
                    ((1 - mode_match) * 0.1) +
                    (acousticness_diff * 0.1) +
                    (danceability_diff * 0.15) +
                    (energy_diff * 0.15) +
                    (instrumentalness_diff * 0.1) +
                    (loudness_diff * 0.05) +
                    (speechiness_diff * 0.05) +
                    (valence_diff * 0.1)
                )
                
                similarities.append((track[0], similarity))
            
            # Sort by similarity (ascending)
            similarities.sort(key=lambda x: x[1])
            
            # Include seed track as first item
            similar_tracks = [seed_file_path] + [track[0] for track in similarities[:playlist_size - 1]]
            
            return similar_tracks
            
        except Exception as e:
            logger.error(f"Error creating station: {e}")
            return []


def main():
    """Command line interface for music analysis"""
    parser = argparse.ArgumentParser(description='Music analysis and feature extraction')
    parser.add_argument('--directory', '-d', required=True, help='Directory with music files')
    parser.add_argument('--recursive', '-r', action='store_true', help='Scan directory recursively')
    parser.add_argument('--database', default='pump.db', help='Database file path')
    parser.add_argument('--scan-only', action='store_true', help='Only scan files, do not analyze')
    
    args = parser.parse_args()
    
    try:
        analyzer = MusicAnalyzer(args.database)
        
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
    
    exit(main())