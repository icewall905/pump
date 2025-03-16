import os
import sqlite3
import random
import configparser
import logging
from flask import Flask, render_template, request, jsonify
from music_analyzer import MusicAnalyzer
from werkzeug.serving import run_simple

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
        'path': 'music_features.db'
    },
    'app': {
        'default_playlist_size': '10',
        'max_search_results': '50'
    }
}

# Load configuration
config = configparser.ConfigParser()
config_file = 'pump.conf'

# Always write a fresh config file to ensure all required sections exist
logger.info(f"Creating configuration file {config_file}")
for section, options in default_config.items():
    if not config.has_section(section):
        config.add_section(section)
    for option, value in options.items():
        config.set(section, option, value)

# Write default config file
with open(config_file, 'w') as f:
    config.write(f)

logger.info(f"Loading configuration from {config_file}")
config.read(config_file)

# Get configuration values with fallbacks
try:
    HOST = config.get('server', 'host', fallback='0.0.0.0')
    PORT = config.getint('server', 'port', fallback=8080)
    DEBUG = config.getboolean('server', 'debug', fallback=True)
    DB_PATH = config.get('database', 'path', fallback='music_features.db')
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
    DB_PATH = 'music_features.db'
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
    logger.info(f"Search query: {query}")
    
    try:
        # Connect to the database
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Search for tracks matching the query
        cursor.execute(f'''
            SELECT af.id, af.file_path, af.title, af.artist, af.album, af.duration
            FROM audio_files af
            WHERE 
                af.title LIKE ? OR
                af.artist LIKE ? OR
                af.album LIKE ? OR
                af.file_path LIKE ?
            LIMIT {MAX_SEARCH_RESULTS}
        ''', (f'%{query}%', f'%{query}%', f'%{query}%', f'%{query}%'))
        
        tracks = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        # Extract filenames for display if title is empty
        for track in tracks:
            if not track['title']:
                track['title'] = os.path.basename(track['file_path'])
        
        logger.info(f"Found {len(tracks)} tracks matching '{query}'")
        return jsonify(tracks)
    
    except Exception as e:
        logger.error(f"Error during search: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/playlist')
def generate_playlist():
    """Generate a playlist based on a seed track"""
    seed_track_id = request.args.get('seed_track_id')
    num_tracks = int(request.args.get('num_tracks', DEFAULT_PLAYLIST_SIZE))
    
    logger.info(f"Generating playlist with seed track ID {seed_track_id} and {num_tracks} tracks")
    
    try:
        # Get the seed track path
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('SELECT file_path FROM audio_files WHERE id = ?', (seed_track_id,))
        result = cursor.fetchone()
        
        if not result:
            logger.warning(f"Seed track ID {seed_track_id} not found")
            return jsonify({'error': 'Seed track not found'}), 404
        
        seed_track_path = result['file_path']
        
        if not analyzer:
            logger.error("MusicAnalyzer not initialized")
            return jsonify({'error': 'Analyzer not available'}), 500
        
        # Generate the playlist
        station_tracks = analyzer.create_station(seed_track_path, num_tracks)
        
        # Get details for each track
        playlist = []
        for track_path in station_tracks:
            cursor.execute('''
                SELECT af.id, af.file_path, af.title, af.artist, af.album, af.duration,
                       ft.tempo, ft.energy, ft.danceability
                FROM audio_files af
                LEFT JOIN audio_features ft ON af.id = ft.file_id
                WHERE af.file_path = ?
            ''', (track_path,))
            
            track_info = cursor.fetchone()
            if track_info:
                track_dict = dict(track_info)
                if not track_dict['title']:
                    track_dict['title'] = os.path.basename(track_path)
                playlist.append(track_dict)
        
        conn.close()
        logger.info(f"Generated playlist with {len(playlist)} tracks")
        return jsonify(playlist)
    
    except Exception as e:
        logger.error(f"Error generating playlist: {e}")
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
                SELECT af.id, af.file_path, af.title, af.artist, af.album, af.duration
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