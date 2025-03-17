import os
import sqlite3
import random
import configparser
import logging
from flask import Flask, render_template, request, jsonify, Response
from music_analyzer import MusicAnalyzer
from werkzeug.serving import run_simple
import requests
from urllib.parse import unquote

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger('web_player')

# Default configuration
default_config = {
    'server': {
        'host': '0.0.0.0',
        'port': '8080',
        'debug': 'true'
    },
    'database': {
        'path': 'pump.db'
    },
    'app': {
        'default_playlist_size': '10',
        'max_search_results': '50'
    }
}

# Load configuration
config = configparser.ConfigParser()
config_file = 'pump.conf'

# Check if config file exists and read it first
if os.path.exists(config_file):
    logger.info(f"Loading existing configuration from {config_file}")
    config.read(config_file)

# Add any missing sections or options from defaults
config_updated = False
for section, options in default_config.items():
    if not config.has_section(section):
        logger.info(f"Adding missing section: {section}")
        config.add_section(section)
        config_updated = True
    for option, value in options.items():
        if not config.has_option(section, option):
            logger.info(f"Adding missing option: {section}.{option}")
            config.set(section, option, value)
            config_updated = True

# Add API keys section if it doesn't exist
if not config.has_section('api_keys'):
    logger.info("Adding api_keys section")
    config.add_section('api_keys')
    config.set('api_keys', 'lastfm_api_key', '')
    config.set('api_keys', 'lastfm_api_secret', '')
    config_updated = True

# Write config file only if it was changed or didn't exist
if config_updated or not os.path.exists(config_file):
    logger.info(f"Writing updated configuration to {config_file}")
    with open(config_file, 'w') as f:
        config.write(f)

# Get configuration values with fallbacks
try:
    HOST = config.get('server', 'host', fallback='0.0.0.0')
    PORT = config.getint('server', 'port', fallback=8080)
    DEBUG = config.getboolean('server', 'debug', fallback=True)
    DB_PATH = config.get('database', 'path', fallback='pump.db')
    DEFAULT_PLAYLIST_SIZE = config.getint('app', 'default_playlist_size', fallback=10)
    MAX_SEARCH_RESULTS = config.getint('app', 'max_search_results', fallback=50)
    
    logger.info(f"Configuration loaded successfully")
    logger.info(f"Server: {HOST}:{PORT} (debug={DEBUG})")
    logger.info(f"Database: {DB_PATH}")
except Exception as e:
    logger.error(f"Error processing configuration: {e}")
    logger.info("Using default values")
    HOST = '0.0.0.0'
    PORT = 8080
    DEBUG = True
    DB_PATH = 'pump.db'
    DEFAULT_PLAYLIST_SIZE = 10
    MAX_SEARCH_RESULTS = 50

# Create Flask app
app = Flask(__name__)
try:
    analyzer = MusicAnalyzer(DB_PATH)
    logger.info("MusicAnalyzer initialized successfully")
except Exception as e:
    logger.error(f"Error initializing MusicAnalyzer: {e}")
    analyzer = None

@app.route('/')
def index():
    """Home page with search functionality"""
    return render_template('index.html')

@app.route('/search')
def search():
    """Search for tracks in the database"""
    query = request.args.get('query', '')
    
    if not query:
        return jsonify([])
    
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Use LIKE for case-insensitive search across multiple fields
        cursor.execute('''
            SELECT id, file_path, title, artist, album, album_art_url, duration
            FROM audio_files 
            WHERE title LIKE ? OR artist LIKE ? OR album LIKE ? 
            ORDER BY artist, album, title
            LIMIT ?
        ''', (f'%{query}%', f'%{query}%', f'%{query}%', MAX_SEARCH_RESULTS))
        
        tracks = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        logger.info(f"Search for '{query}' returned {len(tracks)} results")
        return jsonify(tracks)
        
    except Exception as e:
        logger.error(f"Error searching tracks: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/playlist')
def create_playlist():
    """Create a playlist based on a seed track"""
    seed_track_id = request.args.get('seed_track_id')
    playlist_size = request.args.get('size', DEFAULT_PLAYLIST_SIZE, type=int)
    
    if not seed_track_id:
        return jsonify({'error': 'Seed track ID required'}), 400
    
    try:
        # Create a playlist using the analyzer
        logger.info(f"Generating playlist with seed track ID {seed_track_id} and {playlist_size} tracks")
        
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get the seed track's file path
        cursor.execute('SELECT file_path FROM audio_files WHERE id = ?', (seed_track_id,))
        seed_track = cursor.fetchone()
        
        if not seed_track:
            conn.close()
            return jsonify({'error': 'Seed track not found'}), 404
        
        # Generate the playlist
        if analyzer:
            similar_tracks = analyzer.create_station(seed_track['file_path'], playlist_size)
            
            # Get the full details of the tracks
            playlist = []
            for track_path in similar_tracks:
                cursor.execute('''
                    SELECT id, file_path, title, artist, album, album_art_url, duration 
                    FROM audio_files 
                    WHERE file_path = ?
                ''', (track_path,))
                track = cursor.fetchone()
                if track:
                    playlist.append(dict(track))
            
            conn.close()
            logger.info(f"Generated playlist with {len(playlist)} tracks")
            return jsonify(playlist)
        else:
            conn.close()
            return jsonify({'error': 'Analyzer not available'}), 500
            
    except Exception as e:
        logger.error(f"Error creating playlist: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/explore')
def explore():
    """Get random tracks for exploration"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) as count FROM audio_files')
        count = cursor.fetchone()['count']
        
        # Get random tracks
        random_tracks = []
        if count > 0:
            sample_size = min(10, count)
            cursor.execute(f'''
                SELECT af.id, af.file_path, af.title, af.artist, af.album, af.album_art_url, af.duration
                FROM audio_files af
                ORDER BY RANDOM()
                LIMIT {sample_size}
            ''')
            
            random_tracks = [dict(row) for row in cursor.fetchall()]
            for track in random_tracks:
                if not track['title']:
                    track['title'] = os.path.basename(track['file_path'])
        
        conn.close()
        logger.info(f"Returning {len(random_tracks)} random tracks for exploration")
        return jsonify(random_tracks)
    
    except Exception as e:
        logger.error(f"Error exploring tracks: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/analyze', methods=['POST'])
def analyze_folder():
    """Analyze a music folder and add tracks to the database"""
    folder_path = request.form.get('folder_path')
    recursive = request.form.get('recursive') == 'true'
    
    logger.info(f"Analyzing music folder: {folder_path} (recursive={recursive})")
    
    if not folder_path or not os.path.isdir(folder_path):
        logger.error(f"Invalid folder path: {folder_path}")
        return jsonify({'error': 'Invalid folder path'}), 400
    
    try:
        # Ensure analyzer is initialized
        if not analyzer:
            logger.error("MusicAnalyzer not initialized")
            return jsonify({'error': 'Analyzer not available'}), 500
        
        # Process the directory
        result = analyzer.analyze_directory(folder_path, recursive)
        
        return jsonify({
            'success': True,
            'folder_path': folder_path,
            'files_processed': result.get('files_processed', 0),
            'tracks_added': result.get('tracks_added', 0)
        })
    
    except Exception as e:
        logger.error(f"Error analyzing folder: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    """Settings page for the app"""
    if request.method == 'POST':
        try:
            # Update API keys
            api_key = request.form.get('lastfm_api_key', '')
            api_secret = request.form.get('lastfm_api_secret', '')
            
            # Load existing config
            config = configparser.ConfigParser()
            config.read(config_file)
            
            # Ensure sections exist
            if not config.has_section('api_keys'):
                config.add_section('api_keys')
                
            # Update API keys
            config.set('api_keys', 'lastfm_api_key', api_key)
            config.set('api_keys', 'lastfm_api_secret', api_secret)
            
            # Write updated config
            with open(config_file, 'w') as f:
                config.write(f)
                
            # Reinitialize metadata service
            if analyzer and hasattr(analyzer, 'metadata_service'):
                analyzer.metadata_service = MetadataService(config_file)
            
            return render_template('settings.html', message='Settings saved successfully!')
            
        except Exception as e:
            logger.error(f"Error saving settings: {e}")
            return render_template('settings.html', error=f'Error: {str(e)}')
    
    # For GET requests, load current settings
    try:
        config = configparser.ConfigParser()
        config.read(config_file)
        
        api_key = config.get('api_keys', 'lastfm_api_key', fallback='')
        api_secret = config.get('api_keys', 'lastfm_api_secret', fallback='')
        
        return render_template('settings.html', 
                              lastfm_api_key=api_key,
                              lastfm_api_secret=api_secret)
                              
    except Exception as e:
        logger.error(f"Error loading settings: {e}")
        return render_template('settings.html', error=f'Error: {str(e)}')

@app.route('/debug/metadata')
def debug_metadata():
    """Debug endpoint to check metadata in database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, file_path, title, artist, album, album_art_url, metadata_source
            FROM audio_files
            LIMIT 20
        ''')
        
        tracks = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify({
            'count': len(tracks),
            'tracks_with_art': sum(1 for t in tracks if t.get('album_art_url')),
            'tracks': tracks
        })
        
    except Exception as e:
        logger.error(f"Error fetching debug metadata: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/albumart/<path:url>')
def album_art_proxy(url):
    """Proxy for album art to avoid CORS issues"""
    try:
        # Decode URL
        url = unquote(url)
        logger.info(f"Fetching album art from: {url}")
        
        # Fetch the image
        response = requests.get(url, stream=True)
        
        if response.status_code == 200:
            # Get content type from response
            content_type = response.headers.get('Content-Type', 'image/jpeg')
            
            # Return the image data
            return Response(
                response.raw.read(),
                content_type=content_type
            )
        else:
            logger.error(f"Failed to fetch album art: HTTP {response.status_code}")
            return '', 404
            
    except Exception as e:
        logger.error(f"Error proxying album art: {e}")
        return '', 500

def run_server():
    """Run the Flask server"""
    logger.info(f"Starting server on {HOST}:{PORT} (debug={DEBUG})")
    try:
        # Use Werkzeug's run_simple for better error handling
        run_simple(
            hostname=HOST,
            port=PORT,
            application=app,
            use_reloader=DEBUG,
            use_debugger=DEBUG,
            threaded=True
        )
    except Exception as e:
        logger.error(f"Error running server: {e}")
        print(f"Error running server: {e}")

if __name__ == '__main__':
    run_server()