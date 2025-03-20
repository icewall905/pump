import requests
import base64
import json
import os
import time
import logging
import hashlib

class SpotifyService:
    def __init__(self, client_id=None, client_secret=None, cache_dir='spotify_cache'):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = None
        self.token_expiry = 0
        self.cache_dir = cache_dir
        
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
            
        self.logger = logging.getLogger('spotify_service')
    
    def get_token(self):
        """Get or refresh Spotify API token"""
        current_time = time.time()
        
        # Return existing token if it's still valid
        if self.token and current_time < self.token_expiry - 60:
            return self.token
            
        if not self.client_id or not self.client_secret:
            self.logger.error("Missing Spotify client credentials")
            return None
            
        try:
            auth_header = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
            
            headers = {
                'Authorization': f'Basic {auth_header}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            data = {'grant_type': 'client_credentials'}
            
            response = requests.post('https://accounts.spotify.com/api/token', 
                                    headers=headers, 
                                    data=data)
            
            if response.status_code == 200:
                token_data = response.json()
                self.token = token_data.get('access_token')
                expires_in = token_data.get('expires_in', 3600)
                self.token_expiry = current_time + expires_in
                return self.token
            else:
                self.logger.error(f"Failed to get Spotify token: {response.text}")
                return None
                
        except Exception as e:
            self.logger.error(f"Exception getting Spotify token: {e}")
            return None
    
    def search_artist(self, artist_name):
        """Search for an artist on Spotify"""
        token = self.get_token()
        if not token:
            return None
        
        # Check cache first
        cache_file = os.path.join(self.cache_dir, f"artist_{hashlib.md5(artist_name.encode()).hexdigest()}.json")
        if os.path.exists(cache_file):
            # Use cache if less than 30 days old
            if time.time() - os.path.getmtime(cache_file) < 30 * 24 * 60 * 60:
                try:
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        return json.load(f)
                except Exception as e:
                    self.logger.error(f"Error reading artist cache: {e}")
        
        # Clean artist name - remove potentially problematic characters or split on common separators
        clean_artist = artist_name
        for separator in ["feat.", "ft.", "featuring", "with", "vs", "x", "&"]:
            if separator in clean_artist.lower():
                clean_artist = clean_artist.split(separator, 1)[0].strip()
        
        try:
            headers = {'Authorization': f'Bearer {token}'}
            params = {
                'q': clean_artist,
                'type': 'artist',
                'limit': 1
            }
            
            self.logger.info(f"Searching Spotify for artist: {clean_artist}")
            response = requests.get('https://api.spotify.com/v1/search',
                                   headers=headers,
                                   params=params)
            
            if response.status_code == 200:
                data = response.json()
                artists = data.get('artists', {}).get('items', [])
                
                if artists:
                    artist = artists[0]
                    # Save to cache
                    try:
                        with open(cache_file, 'w', encoding='utf-8') as f:
                            json.dump(artist, f)
                    except Exception as e:
                        self.logger.error(f"Error writing artist cache: {e}")
                        
                    return artist
                    
                self.logger.warning(f"No artist found on Spotify for: {clean_artist}")
                return None
            else:
                self.logger.error(f"Error searching Spotify: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            self.logger.error(f"Exception searching Spotify: {e}")
            return None
    
    # Update get_artist_image_url to support caching
    def get_artist_image_url(self, artist_name, cache_dir=None):
        """Get artist image URL from Spotify or download to cache"""
        artist = self.search_artist(artist_name)
        if not artist:
            return None
            
        # Get images array, sorted by size (largest first)
        images = artist.get('images', [])
        if images:
            # Get the largest image URL
            image_url = images[0].get('url')
            self.logger.info(f"Found Spotify image for {artist_name}: {image_url}")
            
            # If we have a cache directory, download the image
            if cache_dir and image_url:
                try:
                    # Create a hash of the URL for the filename
                    url_hash = hashlib.md5(image_url.encode()).hexdigest()
                    cache_path = os.path.join(cache_dir, f"artist_{url_hash}.jpg")
                    
                    # If already cached, return the path
                    if os.path.exists(cache_path):
                        self.logger.debug(f"Artist image already in cache: {cache_path}")
                        return cache_path
                    
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
        
        self.logger.warning(f"No images found for artist {artist_name} on Spotify")    
        return None