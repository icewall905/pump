# In web_player.py, update the music analyzer initialization
try:
    from music_analyzer import MusicAnalyzer
    analyzer = MusicAnalyzer()  # Don't pass DB_PATH
    logger.info("Music analyzer initialized successfully")
except Exception as e:
    analyzer = None
    logger.error(f"Error initializing music analyzer: {e}")