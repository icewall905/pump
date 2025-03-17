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
            os.makedirs(cache_dir)
            
        self.logger = logging.getLogger('lastfm_service')
    
    def get_artist_info(self, artist_name):
        """Get artist info including images from Last.fm"""
        if not self.api_key or not artist_name:
            return None
            
        # Check cache first
        cache_file = os.path.join(self.cache_dir, f"artist_{hashlib.md5(artist_name.encode()).hexdigest()}.json")
        if os.path.exists(cache_file):
            # Check if cache is less than 30 days old
            if time.time() - os.path.getmtime(cache_file) < 30 * 24 * 60 * 60:
                try:
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        return json.load(f)
                except Exception as e:
                    self.logger.error(f"Error reading artist cache: {e}")
        
        # Make API request
        try:
            params = {
                'method': 'artist.getinfo',
                'artist': artist_name,
                'api_key': self.api_key,
                'format': 'json'
            }
            
            response = requests.get(self.base_url, params=params)
            
            if response.status_code == 200:
                data = response.json()
                
                # Save to cache
                try:
                    with open(cache_file, 'w', encoding='utf-8') as f:
                        json.dump(data, f)
                except Exception as e:
                    self.logger.error(f"Error writing artist cache: {e}")
                    
                return data
            else:
                self.logger.error(f"Error fetching artist info: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            self.logger.error(f"Exception fetching artist info: {e}")
            return None
    
    def get_artist_image_url(self, artist_name):
        """Extract the largest available image URL from artist info"""
        artist_info = self.get_artist_info(artist_name)
        
        if not artist_info or 'artist' not in artist_info:
            return None
            
        try:
            # Get image array
            images = artist_info['artist'].get('image', [])
            
            # Find mega or extralarge image
            for img in images:
                if img.get('size') == 'mega' and img.get('#text'):
                    return img.get('#text')
                    
            # If no mega, try extralarge
            for img in images:
                if img.get('size') == 'extralarge' and img.get('#text'):
                    return img.get('#text')
                    
            # If still no image, get the largest available
            for size in ['large', 'medium', 'small']:
                for img in images:
                    if img.get('size') == size and img.get('#text'):
                        return img.get('#text')
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error parsing artist image URL: {e}")
            return None