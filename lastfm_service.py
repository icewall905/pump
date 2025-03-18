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
            self.logger.warning(f"Missing API key or artist name")
            return None
            
        # Check cache first
        cache_file = os.path.join(self.cache_dir, f"artist_{hashlib.md5(artist_name.encode()).hexdigest()}.json")
        if os.path.exists(cache_file):
            # Delete cache file to force refresh
            os.remove(cache_file)
    
        # Make API request
        try:
            params = {
                'method': 'artist.getinfo',  # CORRECT METHOD
                'artist': artist_name,
                'api_key': self.api_key,
                'format': 'json'
            }
            
            self.logger.info(f"Making LastFM API request for artist: {artist_name}")
            
            response = requests.get(self.base_url, params=params, timeout=10)
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    
                    # Save to cache
                    with open(cache_file, 'w', encoding='utf-8') as f:
                        json.dump(data, f)
                        
                    return data
                except ValueError as e:
                    self.logger.error(f"Invalid JSON response: {e}")
                    self.logger.error(f"Response content: {response.text[:200]}...")
                    return None
            else:
                self.logger.error(f"Error fetching artist info: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Request exception fetching artist info: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Exception fetching artist info: {e}")
            return None
    
    def get_artist_image_url(self, artist_name):
        """Extract the best available artist image URL"""
        # Try standard artist info first
        artist_info = self.get_artist_info(artist_name)
        default_image = "https://lastfm.freetls.fastly.net/i/u/300x300/2a96cbd8b46e442fc41c2b86b821562f.png"
        
        try:
            if artist_info and 'artist' in artist_info:
                # Get image array
                images = artist_info['artist'].get('image', [])
                
                # Find a non-default image
                for img in images:
                    if img.get('#text') and not img.get('#text').endswith('2a96cbd8b46e442fc41c2b86b821562f.png'):
                        return img.get('#text')
            
            # If we got here, either no artist info or only default images
            # Try getting image from artist's albums instead
            album_image = self.get_artist_image_from_albums(artist_name)
            if album_image:
                return album_image
                
            return None
                
        except Exception as e:
            self.logger.error(f"Error parsing artist image URL: {e}")
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