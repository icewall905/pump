import os
import re
import requests
import json
import mutagen
import logging
import musicbrainzngs
import pylast
import configparser
from urllib.parse import quote_plus
import hashlib
import requests
from io import BytesIO
from PIL import Image
import sqlite3  # Add this import
from datetime import datetime  # Add this import
import shutil
from db_operations import get_connection, release_connection, execute_query, execute_query_dict, execute_write
# Add this import
from lastfm_service import LastFMService

logger = logging.getLogger('metadata_service')

class MetadataService:
    """Service for fetching music metadata from various sources"""
    
    def __init__(self, config_file='pump.conf'):
        """Initialize the metadata service"""
        self.config_file = config_file
        self._load_config()
        
        # Initialize LastFM network if API key is available
        if self.lastfm_api_key:
            try:
                import pylast
                self.lastfm_network = pylast.LastFMNetwork(
                    api_key=self.lastfm_api_key, 
                    api_secret=self.lastfm_api_secret
                )
                # Make sure to pass the API keys to the LastFMService
                self.lastfm_service = LastFMService(
                    api_key=self.lastfm_api_key,
                    api_secret=self.lastfm_api_secret
                )
                logger.info(f"LastFM service initialized with API key: {self.lastfm_api_key[:5]}...")
            except ImportError:
                logger.warning("pylast module not found - LastFM features will be disabled")
                self.lastfm_network = None
                self.lastfm_service = None
            except Exception as e:
                logger.error(f"Error initializing LastFM: {e}")
                self.lastfm_network = None
                self.lastfm_service = None
        else:
            logger.warning("Last.fm API not configured")
            self.lastfm_network = None
            self.lastfm_service = None
        
        # Set Spotify service to None since we're not using it
        self.spotify_service = None
    
    def _load_config(self):
        """Load API keys from config file"""
        config = configparser.ConfigParser()
        
        # Check if config exists and create with defaults if not
        if not os.path.exists(self.config_file):
            config['lastfm'] = {
                'api_key': '',
                'api_secret': ''
            }
            config['musicbrainz'] = {
                'user': 'pump_app',
                'app': 'PUMP Music Player'
            }
            with open(self.config_file, 'w') as f:
                config.write(f)
        
        # Load config
        config.read(self.config_file)
        self.lastfm_api_key = config.get('lastfm', 'api_key', fallback='')
        self.lastfm_api_secret = config.get('lastfm', 'api_secret', fallback='')
        
        # Add fallback keys if not configured
        if not self.lastfm_api_key or not self.lastfm_api_secret:
            # Updated default keys
            self.lastfm_api_key = 'b8b4d3c72ac643dbd9e069c6474a0b0b'
            self.lastfm_api_secret = 'de0459d5ee5c5dd9f838735774d41f9e'
            logger.info("Using fallback Last.fm API credentials")
        
        self.musicbrainz_user = config.get('musicbrainz', 'user', fallback='pump_app')
        self.musicbrainz_app = config.get('musicbrainz', 'app', fallback='PUMP Music Player')
    
    def _setup_services(self):
        """Initialize API connections"""
        # Set up MusicBrainz
        musicbrainzngs.set_useragent(
            self.musicbrainz_app,
            "1.0",
            contact="https://github.com/your-username/pump"
        )
        
        # Set up Last.fm
        if self.lastfm_api_key and self.lastfm_api_secret:
            self.lastfm_network = pylast.LastFMNetwork(
                api_key=self.lastfm_api_key,
                api_secret=self.lastfm_api_secret
            )
        else:
            self.lastfm_network = None
            logger.warning("Last.fm API keys not configured")
    
    def get_metadata_from_file(self, file_path):
        """Extract metadata from audio file tags"""
        try:
            audio = mutagen.File(file_path)
            if not audio:
                return {}
            
            # Different file types have different tag structures
            metadata = {}
            
            # Handle MP3 files (ID3)
            if isinstance(audio, mutagen.mp3.MP3):
                if 'TIT2' in audio:
                    metadata['title'] = str(audio['TIT2'])
                if 'TPE1' in audio:
                    metadata['artist'] = str(audio['TPE1'])
                if 'TALB' in audio:
                    metadata['album'] = str(audio['TALB'])
                # Extract album art if present
                if 'APIC:' in audio:
                    apic = audio['APIC:']
                    metadata['embedded_album_art'] = apic.data
            
            # Handle FLAC files
            elif isinstance(audio, mutagen.flac.FLAC):
                if 'title' in audio:
                    metadata['title'] = audio['title'][0]
                if 'artist' in audio:
                    metadata['artist'] = audio['artist'][0]
                if 'album' in audio:
                    metadata['album'] = audio['album'][0]
                # Extract album art if present
                if audio.pictures:
                    metadata['embedded_album_art'] = audio.pictures[0].data
            
            # Handle Ogg Vorbis
            elif isinstance(audio, mutagen.oggvorbis.OggVorbis):
                if 'title' in audio:
                    metadata['title'] = audio['title'][0]
                if 'artist' in audio:
                    metadata['artist'] = audio['artist'][0]
                if 'album' in audio:
                    metadata['album'] = audio['album'][0]
            
            # If we couldn't extract proper metadata, try to get from filename
            if 'title' not in metadata or not metadata['title']:
                filename = os.path.basename(file_path)
                name, _ = os.path.splitext(filename)
                
                # Try to extract artist - title pattern (common in downloaded files)
                match = re.match(r'(.+)\s*[-–_]\s*(.+)', name)
                if match:
                    if 'artist' not in metadata or not metadata['artist']:
                        metadata['artist'] = match.group(1).strip()
                    if 'title' not in metadata or not metadata['title']:
                        metadata['title'] = match.group(2).strip()
                else:
                    metadata['title'] = name
            
            metadata['metadata_source'] = 'local_file'
            return metadata
            
        except Exception as e:
            logger.error(f"Error extracting metadata from {file_path}: {e}")
            return {}
    
    def search_last_fm(self, title=None, artist=None, album=None):
        """Search Last.fm for track metadata"""
        if not self.lastfm_network:
            logger.warning("Last.fm API not configured")
            return {}
        
        try:
            result = {}
            
            # If we have both artist and title
            if artist and title:
                try:
                    track = self.lastfm_network.get_track(artist, title)
                    result['title'] = track.get_title()
                    result['artist'] = track.get_artist().get_name()
                    
                    # Try to get album
                    try:
                        album_obj = track.get_album()
                        if album_obj:
                            result['album'] = album_obj.get_title()
                            
                            # Get album cover - more explicit approach
                            album_info = self.lastfm_network.get_album(track.get_artist().get_name(), album_obj.get_title())
                            images = album_info.get_cover_image(size=3)  # Get medium-sized image
                            if images:
                                result['album_art_url'] = images
                                logger.info(f"Got album art URL from Last.fm: {images}")
                    except Exception as album_error:
                        logger.error(f"Error getting album info: {album_error}")
                    
                    result['metadata_source'] = 'last.fm'
                    return result
                except Exception as e:
                    logger.error(f"Last.fm track search error: {e}")
                    return {}
            
            # If only title is available, try a track search
            elif title:
                tracks = self.lastfm_network.search_for_track("", title).get_next_page()
                if tracks and len(tracks) > 0:
                    track = tracks[0]
                    result['title'] = track.get_title()
                    result['artist'] = track.get_artist().get_name()
                    result['metadata_source'] = 'last.fm'
            
            return result
            
        except Exception as e:
            logger.error(f"Error searching Last.fm: {e}")
            return {}
    
    def search_musicbrainz(self, title=None, artist=None, album=None):
        """Search MusicBrainz for track metadata"""
        try:
            result = {}
            
            # If we have both artist and title
            if artist and title:
                # Search for recordings (tracks)
                search_term = f'recording:"{title}" AND artist:"{artist}"'
                search_results = musicbrainzngs.search_recordings(query=search_term, limit=1)
                
                if search_results['recording-list']:
                    recording = search_results['recording-list'][0]
                    result['title'] = recording['title']
                    result['artist'] = recording['artist-credit'][0]['artist']['name']
                    
                    # Check if recording has a release (album)
                    if 'release-list' in recording and recording['release-list']:
                        release = recording['release-list'][0]
                        result['album'] = release['title']
                        
                        # Try to get cover art
                        try:
                            cover_art = musicbrainzngs.get_image_list(release['id'])
                            if 'images' in cover_art and cover_art['images']:
                                result['album_art_url'] = cover_art['images'][0]['thumbnails']['large']
                        except:
                            pass
                    
                    result['metadata_source'] = 'musicbrainz'
            
            # If only title is available
            elif title:
                search_term = f'recording:"{title}"'
                search_results = musicbrainzngs.search_recordings(query=search_term, limit=1)
                
                if search_results['recording-list']:
                    recording = search_results['recording-list'][0]
                    result['title'] = recording['title']
                    result['artist'] = recording['artist-credit'][0]['artist']['name']
                    result['metadata_source'] = 'musicbrainz'
            
            return result
            
        except Exception as e:
            logger.error(f"Error searching MusicBrainz: {e}")
            return {}
    
    def enrich_metadata(self, basic_metadata, cache_dir=None):
        """Try to enrich basic metadata with additional information from APIs"""
        title = basic_metadata.get('title')
        artist = basic_metadata.get('artist')
        album = basic_metadata.get('album')
        
        logger.info(f"Attempting to enrich metadata for '{artist} - {title}'")
        
        # First try Last.fm
        logger.info(f"Searching Last.fm for '{artist} - {title}'")
        enhanced = self.search_last_fm(title, artist, album)
        if enhanced and ('title' in enhanced and 'artist' in enhanced):
            logger.info(f"Found enhanced metadata from Last.fm for '{artist} - {title}'")
            
            # If we have a cache directory and album art URL, download it
            if cache_dir and 'album_art_url' in enhanced and enhanced['album_art_url']:
                cached_path = self.download_and_cache_image(
                    enhanced['album_art_url'], 
                    cache_dir, 
                    prefix='album_'
                )
                if cached_path:
                    # Update to use local path instead of URL
                    enhanced['album_art_url'] = cached_path
                    logger.info(f"Cached album art to {cached_path}")
            
            return enhanced
        
        # If Last.fm doesn't have it, try MusicBrainz
        logger.info(f"Searching MusicBrainz for '{artist} - {title}'")
        enhanced = self.search_musicbrainz(title, artist, album)
        if enhanced and ('title' in enhanced and 'artist' in enhanced):
            logger.info(f"Found enhanced metadata from MusicBrainz for '{artist} - {title}'")
            
            # If we have a cache directory and album art URL, download it
            if cache_dir and 'album_art_url' in enhanced and enhanced['album_art_url']:
                cached_path = self.download_and_cache_image(
                    enhanced['album_art_url'], 
                    cache_dir, 
                    prefix='album_'
                )
                if cached_path:
                    # Update to use local path instead of URL
                    enhanced['album_art_url'] = cached_path
                    logger.info(f"Cached album art to {cached_path}")
            
            return enhanced
        
        # Return original if nothing found
        logger.info(f"No enhanced metadata found for '{artist} - {title}'")
        return basic_metadata

    def download_and_cache_image(self, image_url, cache_dir, prefix='album_'):
        """Download an image and save it to the cache directory"""
        if not image_url:
            logger.warning("No image URL provided for download")
            return None
            
        try:
            # Create a hash of the URL for the filename
            url_hash = hashlib.md5(image_url.encode()).hexdigest()
            cache_filename = f"{prefix}{url_hash}.jpg"
            cache_path = os.path.join(cache_dir, cache_filename)
            
            # If already cached, return the web-accessible path
            if os.path.exists(cache_path):
                logger.debug(f"Using cached image: {cache_path}")
                return f"/cache/{cache_filename}"  # Return web-accessible path
                
            # Create cache directory if it doesn't exist
            if not os.path.exists(cache_dir):
                logger.info(f"Creating missing cache directory: {cache_dir}")
                os.makedirs(cache_dir, exist_ok=True)
                
            # Only download if it's a URL
            if image_url.startswith(('http://', 'https://')):
                # Otherwise download and save it
                logger.info(f"Downloading image from {image_url}")
                response = requests.get(image_url, timeout=10)
                if response.status_code == 200:
                    with open(cache_path, 'wb') as f:
                        f.write(response.content)
                    logger.info(f"Successfully saved image to {cache_path}")
                    return f"/cache/{cache_filename}"  # Return web-accessible path
                else:
                    logger.error(f"Failed to download image. Status code: {response.status_code}")
                    return image_url  # Fall back to original URL
            elif os.path.exists(image_url) and os.path.isfile(image_url):
                # If it's a local file path, copy it to cache
                try:
                    shutil.copy(image_url, cache_path)
                    return f"/cache/{cache_filename}"  # Return web-accessible path
                except Exception as copy_error:
                    logger.error(f"Error copying local file to cache: {copy_error}")
                    return image_url
            else:
                logger.error(f"Image URL is neither a valid URL nor a file path: {image_url}")
                return None
        except Exception as e:
            logger.error(f"Error downloading/saving image from {image_url}: {e}")
            return image_url  # Return original URL as fallback

    def update_all_metadata(self, status_tracker=None, skip_existing=False):
        """Update metadata for all tracks in the database"""
        try:
            # Configure PostgreSQL connection directly without relying on db_path
            conn = get_connection()
            cursor = conn.cursor()
            
            processed = 0
            updated = 0
            
            # Check if metadata_source column exists
            try:
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name = 'tracks' AND column_name = 'metadata_source'
                    )
                """)
                has_metadata_source = cursor.fetchone()[0]
                
                if not has_metadata_source:
                    logger.warning("metadata_source column doesn't exist, adding it now")
                    cursor.execute("""
                        ALTER TABLE tracks ADD COLUMN IF NOT EXISTS metadata_source TEXT;
                        ALTER TABLE tracks ADD COLUMN IF NOT EXISTS metadata_updated_at TIMESTAMP;
                    """)
                    conn.commit()
            except Exception as e:
                logger.error(f"Error checking/creating metadata columns: {e}")
                # Continue with the function even if this fails
            
            # Get total number of tracks
            cursor.execute("SELECT COUNT(*) FROM tracks")
            total_tracks = cursor.fetchone()[0]
            
            # Update status tracker if provided
            if status_tracker:
                status_tracker['running'] = True
                status_tracker['start_time'] = datetime.now()
                status_tracker['total_tracks'] = total_tracks
                status_tracker['processed_tracks'] = 0
                status_tracker['updated_tracks'] = 0
                status_tracker['percent_complete'] = 0
                status_tracker['error'] = None
                
            # Get tracks to process
            if skip_existing:
                logger.info("Metadata update: Skipping tracks with existing metadata")
                if has_metadata_source:
                    cursor.execute("""
                        SELECT id, file_path, title, artist, album 
                        FROM tracks 
                        WHERE metadata_source IS NULL OR metadata_source = ''
                    """)
                else:
                    cursor.execute("SELECT id, file_path, title, artist, album FROM tracks")
            else:
                logger.info("Metadata update: Processing all tracks")
                cursor.execute("SELECT id, file_path, title, artist, album FROM tracks")
                
            tracks = cursor.fetchall()
            total_tracks = len(tracks)
            
            # Release this connection as we'll use a new one per batch
            release_connection(conn)
            
            # Process tracks in batches
            batch_size = 50
            for i in range(0, len(tracks), batch_size):
                batch = tracks[i:i+batch_size]
                
                for track in batch:
                    track_id, file_path, title, artist, album = track
                    
                    try:
                        # Update status
                        if status_tracker:
                            status_tracker['current_track'] = f"{artist} - {title}"
                            status_tracker['processed_tracks'] = processed
                            status_tracker['updated_tracks'] = updated
                            status_tracker['percent_complete'] = min(100, int((processed / total_tracks) * 100))
                        
                        # Get metadata from external service
                        metadata = self.get_track_metadata(artist, title, album)
                        
                        if metadata:
                            # Update track metadata
                            conn = get_connection()
                            cursor = conn.cursor()
                            
                            # Prepare update values
                            update_fields = []
                            update_values = []
                            
                            if 'genre' in metadata and metadata['genre']:
                                update_fields.append("genre = %s")
                                update_values.append(metadata['genre'])
                                
                            if 'album_art_url' in metadata and metadata['album_art_url']:
                                update_fields.append("album_art_url = %s")
                                update_values.append(metadata['album_art_url'])
                                
                            if 'metadata_source' in metadata and metadata['metadata_source']:
                                update_fields.append("metadata_source = %s")
                                update_values.append(metadata['metadata_source'])
                                
                            if update_fields:
                                # Add the track_id to values
                                update_values.append(track_id)
                                
                                # Build and execute update query
                                update_query = f"""
                                    UPDATE tracks 
                                    SET {', '.join(update_fields)},
                                        metadata_updated_at = NOW()
                                    WHERE id = %s
                                """
                                
                                cursor.execute(update_query, update_values)
                                conn.commit()
                                updated += 1
                            
                            release_connection(conn)
                        
                    except Exception as e:
                        logger.error(f"Error updating metadata for {artist} - {title}: {e}")
                        
                    processed += 1
                    
                    # Periodically update status
                    if processed % 10 == 0 and status_tracker:
                        logger.info(f"Metadata update progress: {processed}/{total_tracks} tracks processed")
            
            # Final status update
            if status_tracker:
                status_tracker['processed_tracks'] = processed
                status_tracker['updated_tracks'] = updated
                status_tracker['percent_complete'] = 100
                status_tracker['running'] = False
                status_tracker['last_updated'] = datetime.now()
                
            logger.info(f"Metadata update complete: {processed}/{total_tracks} tracks processed, {updated} updated")
            
            return {
                'processed': processed,
                'updated': updated,
                'total': total_tracks
            }
        except Exception as e:
            logger.error(f"Error during metadata update: {e}")
            if status_tracker:
                status_tracker['running'] = False
                status_tracker['error'] = str(e)
                status_tracker['last_updated'] = datetime.now()
            return {
                'processed': 0,
                'updated': 0,
                'total': 0,
                'error': str(e)
            }
        finally:
            if 'conn' in locals() and conn:
                release_connection(conn)

    def _update_track_metadata_with_retry(self, track_id, artist, title, album, metadata):
        """Update a track's metadata with retry logic for database locks"""
        from db_operations import with_transaction
        
        def do_update(conn, track_id, artist, title, album, metadata):
            cursor = conn.cursor()
            
            # Start with basic fields to update
            update_fields = []
            update_values = []
            
            # Add metadata fields
            if 'album_art_url' in metadata and metadata['album_art_url']:
                update_fields.append('album_art_url = ?')
                update_values.append(metadata['album_art_url'])
                
            if 'artist_image_url' in metadata and metadata['artist_image_url']:
                update_fields.append('artist_image_url = ?')
                update_values.append(metadata['artist_image_url'])
                
            if 'genre' in metadata and metadata['genre']:
                update_fields.append('genre = ?')
                update_values.append(metadata['genre'])
                
            # Only update if we have fields to update
            if update_fields:
                cursor.execute(
                    f"UPDATE audio_files SET {', '.join(update_fields)} WHERE id = ?",
                    update_values + [track_id]
                )
                
            return cursor.rowcount > 0
        
        with optimized_connection(self.db_path, self.in_memory, self.cache_size_mb) as conn:
            return with_transaction(conn, do_update, track_id, artist, title, album, metadata)

    def _update_track_metadata(self, track_id, artist, title, album, metadata):
        """Update a track's metadata in the database"""
        try:
            # Mark the connection as modified so it gets saved to disk
            from flask import g
            if hasattr(g, 'db_modified'):
                g.db_modified = True
                
            # Create direct DB connection instead of using optimized_connection
            # which creates circular import problems
            import sqlite3
            db_path = self.config_file.replace('pump.conf', 'pump.db')
            
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                
                # Start with basic fields to update
                update_fields = []
                update_values = []
                
                # Add metadata fields that need updating
                if 'album_art_url' in metadata and metadata['album_art_url']:
                    update_fields.append('album_art_url = ?')
                    update_values.append(metadata['album_art_url'])
                    
                if 'artist_image_url' in metadata and metadata['artist_image_url']:
                    update_fields.append('artist_image_url = ?')
                    update_values.append(metadata['artist_image_url'])
                    
                if 'genre' in metadata and metadata['genre']:
                    update_fields.append('genre = ?')
                    update_values.append(metadata['genre'])
                    
                # Only update if we have fields to update
                if update_fields:
                    query = f"UPDATE audio_files SET {', '.join(update_fields)} WHERE id = ?"
                    cursor.execute(query, update_values + [track_id])
                    conn.commit()  # Add explicit commit
                    
                    # Log the update for debugging
                    if cursor.rowcount > 0:
                        logger.info(f"Updated metadata for track {track_id}: {', '.join(update_fields)}")
                    else:
                        logger.warning(f"No rows updated for track {track_id}")
                    
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating track metadata: {e}")
            return False

    def get_track_metadata(self, artist, title, album=''):
        """Get metadata for a track from external services"""
        metadata = {}
        
        # Only use LastFM for metadata
        if self.lastfm_service:
            try:
                lastfm_data = self.lastfm_service.get_track_info(artist, title)
                if lastfm_data:
                    # Extract relevant metadata
                    if 'album' in lastfm_data:
                        metadata['album'] = lastfm_data['album']
                    if 'image' in lastfm_data:
                        metadata['album_art_url'] = lastfm_data['image']
                    if 'genre' in lastfm_data:
                        metadata['genre'] = lastfm_data['genre']
                    if 'year' in lastfm_data:
                        metadata['year'] = lastfm_data['year']
                    metadata['source'] = 'lastfm'
                    logger.info(f"Retrieved metadata for {artist} - {title} from LastFM")
            except Exception as e:
                logger.error(f"Error getting LastFM metadata for {artist} - {title}: {e}")
        else:
            logger.debug(f"LastFM service not available for {artist} - {title}")
        
        return metadata

