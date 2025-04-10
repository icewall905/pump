import psycopg2
import sys

def test_db_connection():
    """Test connection to PostgreSQL database"""
    try:
        # Connect to the PostgreSQL database
        conn = psycopg2.connect(
            host="localhost",
            port="45432",
            user="pump",
            password="Ge3hgU07bXlBigvTbRSX",
            dbname="pump"
        )
        
        # Create a cursor
        cur = conn.cursor()
        
        # Execute a test query
        cur.execute("SELECT 1")
        result = cur.fetchone()
        
        # Close cursor and connection
        cur.close()
        conn.close()
        
        print("✅ Successfully connected to PostgreSQL!")
        print(f"Test query result: {result[0]}")
        return True
        
    except Exception as e:
        print(f"❌ Error connecting to PostgreSQL: {e}")
        return False

if __name__ == "__main__":
    success = test_db_connection()
    sys.exit(0 if success else 1)