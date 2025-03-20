import requests
import logging
import json
import os
import time
import hashlib

class LastFMService:
    """Service for fetching metadata from Last.fm API"""
    
    def __init__(self, api_key=None, api_secret=None, cache_dir='lastfm_cache'):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "http://ws.audioscrobbler.com/2.0/"
        self.cache_dir = cache_dir
        
        # Create cache directory if it doesn't exist
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir, exist_ok=True)
            
        self.logger = logging.getLogger('lastfm_service')
    
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