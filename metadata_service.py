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

logger = logging.getLogger('metadata_service')

class MetadataService:
    """Service for fetching music metadata from various sources"""
    
    def __init__(self, config_file='pump.conf'):
        self.config_file = config_file
        self._load_config()
        self._setup_services()
    
    def _load_config(self):
        """Load API keys from config file"""
        config = configparser.ConfigParser()
        
        # Check if config exists and create with defaults if not
        if not os.path.exists(self.config_file):
            config['api_keys'] = {
                'lastfm_api_key': '',
                'lastfm_api_secret': '',
                'musicbrainz_user': 'pump_app',
                'musicbrainz_app': 'PUMP Music Player'
            }
            with open(self.config_file, 'w') as f:
                config.write(f)
        
        # Load config
        config.read(self.config_file)
        self.lastfm_api_key = config.get('api_keys', 'lastfm_api_key', fallback='')
        self.lastfm_api_secret = config.get('api_keys', 'lastfm_api_secret', fallback='')
        self.musicbrainz_user = config.get('api_keys', 'musicbrainz_user', fallback='pump_app')
        self.musicbrainz_app = config.get('api_keys', 'musicbrainz_app', fallback='PUMP Music Player')
    
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
                            
                            # Get album cover - use this approach
                            try:
                                album_info = self.lastfm_network.get_album(track.get_artist().get_name(), album_obj.get_title())
                                images = album_info.get_cover_image(size=3)  # Get medium-sized image
                                if images:
                                    result['album_art_url'] = images
                                    logger.info(f"Got album art URL: {images}")
                            except Exception as e:
                                logger.error(f"Error getting album art: {e}")
                    
                    except pylast.WSError:
                        # If we can't get album from track, try direct album search if name is provided
                        if album:
                            try:
                                album_obj = self.lastfm_network.get_album(artist, album)
                                images = album_obj.get_cover_image(size=3)
                                if images:
                                    result['album_art_url'] = images
                                    logger.info(f"Got album art URL: {images}")
                            except:
                                pass
                    
                    result['metadata_source'] = 'last.fm'
                except pylast.WSError as e:
                    logger.error(f"Last.fm error: {e}")
                    pass
            
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
    
    def enrich_metadata(self, basic_metadata):
        """Try to enrich basic metadata with additional information from APIs"""
        title = basic_metadata.get('title')
        artist = basic_metadata.get('artist')
        album = basic_metadata.get('album')
        
        # First try Last.fm
        enhanced = self.search_last_fm(title, artist, album)
        if enhanced and ('title' in enhanced and 'artist' in enhanced):
            return enhanced
        
        # If Last.fm doesn't have it, try MusicBrainz
        enhanced = self.search_musicbrainz(title, artist, album)
        if enhanced and ('title' in enhanced and 'artist' in enhanced):
            return enhanced
        
        # Return original if nothing found
        return basic_metadata