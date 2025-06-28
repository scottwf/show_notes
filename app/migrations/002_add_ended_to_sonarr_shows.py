import sqlite3
import os

# Determine the database path similarly to how your app does it
# This might need adjustment based on your project structure if run standalone
INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade(conn):
    cursor = conn.cursor()
    # Check if the column already exists
    cursor.execute("PRAGMA table_info(sonarr_shows);")
    columns = [info[1] for info in cursor.fetchall()]
    if 'ended' not in columns:
        print("Adding 'ended' column to 'sonarr_shows' table...")
        cursor.execute("ALTER TABLE sonarr_shows ADD COLUMN ended BOOLEAN;")
        conn.commit()
        print("'ended' column added successfully.")
    else:
        print("'ended' column already exists in 'sonarr_shows' table.")

if __name__ == '__main__':
    # Ensure the instance folder exists before trying to connect
    if not os.path.exists(INSTANCE_FOLDER_PATH):
        try:
            os.makedirs(INSTANCE_FOLDER_PATH)
            print(f"Created instance folder: {INSTANCE_FOLDER_PATH}")
        except OSError as e:
            print(f"Error creating instance folder {INSTANCE_FOLDER_PATH}: {e}")
            # Exit if instance folder cannot be created, as DB connection will fail
            exit(1)
            
    conn = sqlite3.connect(DB_PATH)
    try:
        upgrade(conn)
    finally:
        conn.close()
