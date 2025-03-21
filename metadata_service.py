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
                logger.info("LastFM service initialized successfully")
            except ImportError:
                logger.warning("pylast module not found. LastFM support will be limited.")
                self.lastfm_network = None
            except Exception as e:
                logger.error(f"Error initializing LastFM service: {e}")
                self.lastfm_network = None
        else:
            logger.warning("Last.fm API not configured")
            self.lastfm_network = None
    
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
            # These are example keys - you should replace with valid ones
            self.lastfm_api_key = '5ae3c562f8e41f790c8f5503d98f9108'
            self.lastfm_api_secret = '95a1a83537706b56c0d322361841e8b0'
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
        """
        Update metadata for all tracks in the database
        
        Args:
            status_tracker: Dictionary to track update status
            skip_existing: If True, skip tracks that already have metadata
        """
        try:
            # Connect to database
            conn = sqlite3.connect(self.config_file.replace('pump.conf', 'pump.db'))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Get all tracks
            if skip_existing:
                # Skip tracks that already have metadata
                cursor.execute('''
                    SELECT id, file_path, title, artist, album
                    FROM audio_files 
                    WHERE metadata_source IS NULL OR metadata_source = ''
                ''')
                logger.info("Metadata update: Skipping tracks with existing metadata")
            else:
                # Update all tracks
                cursor.execute('''
                    SELECT id, file_path, title, artist, album
                    FROM audio_files
                ''')
                logger.info("Metadata update: Processing all tracks")
            
            tracks = cursor.fetchall()
            total_tracks = len(tracks)
            
            # Update status
            if status_tracker:
                status_tracker['total_tracks'] = total_tracks
                status_tracker['processed_tracks'] = 0
                status_tracker['updated_tracks'] = 0
            
            # Create cache directory if it doesn't exist
            cache_dir = os.path.join(os.path.dirname(self.config_file), 'album_art_cache')
            if not os.path.exists(cache_dir):
                os.makedirs(cache_dir, exist_ok=True)
            
            # Process each track
            processed = 0
            updated = 0
            
            for track in tracks:
                track_id = track['id']
                file_path = track['file_path']
                
                try:
                    if status_tracker:
                        status_tracker['current_track'] = os.path.basename(file_path)
                    
                    logger.debug(f"Processing track: {file_path}")
                    
                    # Get basic metadata from file
                    basic_metadata = self.get_metadata_from_file(file_path)
                    
                    # If we don't have title and artist, use what's in the database
                    if not basic_metadata.get('title'):
                        basic_metadata['title'] = track['title']
                    if not basic_metadata.get('artist'):
                        basic_metadata['artist'] = track['artist']
                    
                    # Only proceed if we have at least title or artist
                    if basic_metadata.get('title') or basic_metadata.get('artist'):
                        # Enrich metadata from online sources
                        enriched = self.enrich_metadata(basic_metadata, cache_dir)
                        
                        # Update database
                        cursor.execute('''
                            UPDATE audio_files SET
                                title = ?,
                                artist = ?,
                                album = ?,
                                album_art_url = ?,
                                metadata_source = ?
                            WHERE id = ?
                        ''', (
                            enriched.get('title') or track['title'],
                            enriched.get('artist') or track['artist'],
                            enriched.get('album') or track['album'],
                            enriched.get('album_art_url', ''),
                            enriched.get('metadata_source', 'local_file'),
                            track_id
                        ))
                        conn.commit()
                        updated += 1
                    
                    processed += 1
                    
                    # Update status
                    if status_tracker:
                        status_tracker['processed_tracks'] = processed
                        status_tracker['updated_tracks'] = updated
                        status_tracker['percent_complete'] = int((processed / total_tracks) * 100)
                        status_tracker['last_updated'] = datetime.now()
                    
                    # Log progress periodically
                    if processed % 10 == 0:
                        logger.info(f"Metadata update progress: {processed}/{total_tracks} tracks processed")
                    
                except Exception as e:
                    logger.error(f"Error updating metadata for {file_path}: {e}")
                    # Continue with next track
            
            # Update final status
            if status_tracker:
                status_tracker['running'] = False
                status_tracker['percent_complete'] = 100
                status_tracker['last_updated'] = datetime.now()
            
            logger.info(f"Metadata update complete: {processed}/{total_tracks} tracks processed, {updated} updated")
            
            return {
                'processed': processed,
                'updated': updated
            }
            
        except Exception as e:
            logger.error(f"Error during metadata update: {e}")
            if status_tracker:
                status_tracker['running'] = False
                status_tracker['error'] = str(e)
                status_tracker['last_updated'] = datetime.now()
        finally:
            if conn:
                conn.close()

