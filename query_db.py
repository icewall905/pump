from db_operations import get_connection, release_connection

def query_db():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Query tracks
        cursor.execute("SELECT * FROM tracks LIMIT 10")
        tracks = cursor.fetchall()
        print("Tracks:")
        for row in tracks:
            print(row)
        
        # Query audio features
        cursor.execute("SELECT * FROM track_features LIMIT 10")
        features = cursor.fetchall()
        print("\nFeatures:")
        for row in features:
            print(row)
            
        release_connection(conn)
        
    except Exception as e:
        print(f"Error querying database: {e}")

if __name__ == "__main__":
    query_db()