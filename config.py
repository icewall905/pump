import os
import configparser
import logging

logger = logging.getLogger('config')

def load_config():
    """Load configuration from pump.conf"""
    config = configparser.ConfigParser()
    
    # Default configuration
    default_config = {
        'SERVER': {
            'host': '127.0.0.1',
            'port': '8080',
            'debug': 'false'
        },
        'DATABASE': {
            'host': 'localhost',
            'port': '45432',
            'user': 'pump',
            'password': 'Ge3hgU07bXlBigvTbRSX',
            'dbname': 'pump',
            'min_connections': '1',
            'max_connections': '10'
        },
        'CACHE': {
            'directory': 'cache',
            'max_size_mb': '500'
        },
        'MUSIC': {
            'library': '',
            'recursive': 'true'
        },
        'API': {
            'lastfm_api_key': '',
            'lastfm_api_secret': '',
            'spotify_client_id': '',
            'spotify_client_secret': ''
        },
        'SCANNER': {
            'exclude_dirs': '["node_modules", "__pycache__", ".git", "$RECYCLE.BIN"]'
        }
    }
    
    # Set defaults
    for section, options in default_config.items():
        if not config.has_section(section):
            config.add_section(section)
        for key, value in options.items():
            config.set(section, key, value)
    
    # Load from file if it exists
    config_path = os.path.join(os.path.dirname(__file__), 'pump.conf')
    if os.path.exists(config_path):
        logger.info(f"Loading configuration from {config_path}")
        config.read(config_path)
    else:
        logger.warning(f"Configuration file not found at {config_path}, using defaults")
        
    return config
