import requests
import logging
import json
import os
import time
import hashlib
import configparser

class LastFMService:
    """Service for fetching metadata from Last.fm API"""
    
    def __init__(self, api_key=None, api_secret=None, cache_dir='lastfm_cache'):
        # If no API key provided, try to load from config
        if not api_key or not api_secret:
            self._load_config_keys()
        else:
            self.api_key = api_key
            self.api_secret = api_secret
            
        self.base_url = "http://ws.audioscrobbler.com/2.0/"
        self.cache_dir = cache_dir
        
        # Create cache directory if it doesn't exist
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir, exist_ok=True)
            
        self.logger = logging.getLogger('lastfm_service')
        
        # Log API key status for debugging
        if self.api_key:
            self.logger.info(f"LastFM service initialized with API key: {self.api_key[:5]}...")
        else:
            self.logger.warning("LastFM service initialized without API key")
    
    def _load_config_keys(self):
        """Load API keys from pump.conf file"""
        try:
            config = configparser.ConfigParser()
            config_path = os.path.join(os.path.dirname(__file__), 'pump.conf')
            if os.path.exists(config_path):
                config.read(config_path)
                if config.has_section('lastfm'):
                    self.api_key = config.get('lastfm', 'api_key', fallback='')
                    self.api_secret = config.get('lastfm', 'api_secret', fallback='')
                    return
            
            # Fallback to hardcoded keys if needed
            self.api_key = 'b8b4d3c72ac643dbd9e069c6474a0b0b'
            self.api_secret = 'de0459d5ee5c5dd9f838735774d41f9e'
        except Exception as e:
            # Default keys if there's any error
            self.api_key = 'b8b4d3c72ac643dbd9e069c6474a0b0b'
            self.api_secret = 'de0459d5ee5c5dd9f838735774d41f9e'
            logging.error(f"Error loading LastFM config: {e}, using default keys")

    def get_artist_info(self, artist_name):
        """Get artist info including images from Last.fm"""
        if not self.api_key or not artist_name:
            self.logger.warning(f"Missing API key or artist name")
            return None
            
        # Check cache first
        cache_file = os.path.join(self.cache_dir, f"artist_{hashlib.md5(artist_name.encode()).hexdigest()}.json")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                    self.logger.info(f"Using cached Last.fm data for: {artist_name}")
                    return cached_data
            except Exception as e:
                self.logger.error(f"Error reading cache file: {e}")
                # Continue to API request if cache read fails
    
        # Make API request
        try:
            params = {
                'method': 'artist.getinfo',
                'artist': artist_name,
                'api_key': self.api_key,
                'format': 'json'
            }
            
            self.logger.info(f"Making LastFM API request for artist: {artist_name}")
            
            response = requests.get(self.base_url, params=params, timeout=10)
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    
                    # Check if the response contains artist data
                    if 'artist' in data:
                        self.logger.info(f"Received Last.fm data for {artist_name}")
                        # Save to cache
                        try:
                            with open(cache_file, 'w', encoding='utf-8') as f:
                                json.dump(data, f, indent=2)
                        except Exception as cache_err:
                            self.logger.error(f"Error writing cache: {cache_err}")
                        return data
                    else:
                        self.logger.warning(f"No artist data found for {artist_name}")
                        if 'error' in data:
                            self.logger.error(f"Last.fm API error: {data.get('message', 'Unknown error')}")
                except ValueError as e:
                    self.logger.error(f"Error parsing Last.fm response: {e}")
            else:
                self.logger.error(f"Last.fm request failed with status {response.status_code}: {response.text}")
                
        except Exception as e:
            self.logger.error(f"Exception fetching artist info: {e}")
        
        return None
    
    def get_artist_image_url(self, artist_name, cache_dir=None):
        """Extract the best available artist image URL or download to cache"""
        # Try standard artist info first
        artist_info = self.get_artist_info(artist_name)
        default_image = "https://lastfm.freetls.fastly.net/i/u/300x300/2a96cbd8b46e442fc41c2b86b821562f.png"
        
        try:
            if artist_info and 'artist' in artist_info:
                # Get image array
                images = artist_info['artist'].get('image', [])
                
                # Find a non-default image by checking the largest ones first
                for img in reversed(images):
                    image_url = img.get('#text', '')
                    if image_url and not image_url.endswith('2a96cbd8b46e442fc41c2b86b821562f.png'):
                        self.logger.info(f"Found good image for {artist_name}: {image_url}")
                        
                        # If we have a cache directory, download the image
                        if cache_dir:
                            try:
                                # Create a hash of the URL for the filename
                                url_hash = hashlib.md5(image_url.encode()).hexdigest()
                                cache_path = os.path.join(cache_dir, f"artist_{url_hash}.jpg")
                                
                                # If already cached, return the path
                                if os.path.exists(cache_path):
                                    self.logger.debug(f"Artist image already in cache: {cache_path}")
                                    return cache_path
                                
                                # Create cache directory if it doesn't exist
                                if not os.path.exists(cache_dir):
                                    self.logger.info(f"Creating artist image cache directory: {cache_dir}")
                                    os.makedirs(cache_dir, exist_ok=True)
                                
                                # Otherwise download and save it
                                response = requests.get(image_url, timeout=10)
                                if response.status_code == 200:
                                    # Save the image to cache
                                    with open(cache_path, 'wb') as f:
                                        f.write(response.content)
                                    self.logger.info(f"Saved artist image to {cache_path}")
                                    return cache_path
                            except Exception as e:
                                self.logger.error(f"Error caching artist image: {e}")
                                # Fall back to returning the URL if caching fails
                        
                        return image_url
                
                # If we get here, we only found default images, return the largest one
                if images and images[-1].get('#text'):
                    return images[-1].get('#text')
                
            # If we couldn't find anything good, try the similar artists
            similar_artists = self.get_similar_artists(artist_name)
            if similar_artists and len(similar_artists) > 0:
                # Check the first similar artist's image
                similar_artist = similar_artists[0].get('name')
                if similar_artist:
                    self.logger.info(f"Trying image from similar artist: {similar_artist}")
                    return self.get_artist_image_url(similar_artist, cache_dir)  # Recursive call
            
            return None  # No suitable image found
        
        except Exception as e:
            self.logger.error(f"Error extracting artist image: {e}")
            return None

    def get_artist_image_from_albums(self, artist_name):
        """Get artist image from their top albums as fallback"""
        if not self.api_key or not artist_name:
            return None
            
        try:
            params = {
                'method': 'artist.getTopAlbums',
                'artist': artist_name,
                'api_key': self.api_key,
                'format': 'json',
                'limit': 5  # Check top 5 albums
            }
            
            response = requests.get(self.base_url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if 'topalbums' in data and 'album' in data['topalbums']:
                    albums = data['topalbums']['album']
                    
                    # Try to get an album image
                    for album in albums:
                        images = album.get('image', [])
                        for img in images:
                            if img.get('size') in ['extralarge', 'large'] and img.get('#text'):
                                if not img.get('#text').endswith('2a96cbd8b46e442fc41c2b86b821562f.png'):
                                    return img.get('#text')
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting artist image from albums: {e}")
            return None

    def get_track_info(self, artist, title, album=''):
        """Get track information from LastFM API"""
        if not self.api_key or not artist or not title:
            self.logger.warning(f"Missing API key or track info: {artist} - {title}")
            return None
            
        # Check cache first
        cache_key = f"{artist}_{title}".lower().replace(' ', '_')
        cache_file = os.path.join(self.cache_dir, f"track_{hashlib.md5(cache_key.encode()).hexdigest()}.json")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                    self.logger.info(f"Using cached LastFM data for: {artist} - {title}")
                    return cached_data
            except Exception as e:
                self.logger.error(f"Error reading cache file: {e}")
        
        # Make API request
        try:
            params = {
                'method': 'track.getInfo',
                'artist': artist,
                'track': title,
                'api_key': self.api_key,
                'format': 'json'
            }
            
            # Add album if we have it
            if album:
                params['album'] = album
                
            self.logger.info(f"Making LastFM API request for track: {artist} - {title}")
            
            response = requests.get(self.base_url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                # Check if we have track data
                if 'track' not in data:
                    self.logger.warning(f"No track data found for {artist} - {title}")
                    if 'error' in data:
                        self.logger.error(f"LastFM API error: {data.get('message', 'Unknown error')}")
                    return None
                    
                # Extract relevant info
                track_data = data['track']
                result = {
                    'title': track_data.get('name', title),
                    'artist': track_data.get('artist', {}).get('name', artist),
                    'album': track_data.get('album', {}).get('title', album),
                    'source': 'lastfm'
                }
                
                # Extract images if available
                if 'album' in track_data and 'image' in track_data['album']:
                    images = track_data['album']['image']
                    # Get the largest image (last in the list)
                    for img in reversed(images):
                        if img.get('#text'):
                            result['image'] = img.get('#text')
                            break
                
                # Extract genre if available
                if 'toptags' in track_data and 'tag' in track_data['toptags']:
                    tags = track_data['toptags']['tag']
                    if tags and len(tags) > 0:
                        result['genre'] = tags[0]['name']
                
                # Save to cache
                try:
                    with open(cache_file, 'w', encoding='utf-8') as f:
                        json.dump(result, f, indent=2)
                except Exception as cache_err:
                    self.logger.error(f"Error writing cache: {cache_err}")
                
                return result
                
            else:
                self.logger.error(f"LastFM request failed with status {response.status_code}: {response.text}")
                return None
                
        except Exception as e:
            self.logger.error(f"Error getting track info: {e}")
            return None