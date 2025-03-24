from db_utils import optimized_connection

def query_db(db_path: str):
    with optimized_connection(db_path) as conn:
        cursor = conn.cursor()
        
        # Query audio files
        cursor.execute("SELECT * FROM audio_files")
        audio_files = cursor.fetchall()
        print("Audio Files:")
        for row in audio_files:
            print(row)
        
        # Query audio features
        cursor.execute("SELECT * FROM audio_features")
        audio_features = cursor.fetchall()
        print("\nAudio Features:")
        for row in audio_features:
            print(row)

if __name__ == "__main__":
    query_db("music_features.db")