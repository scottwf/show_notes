import sqlite3
import os

# Determine the database path
INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

TABLE_SCHEMA = '''
CREATE TABLE IF NOT EXISTS image_cache_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_type TEXT NOT NULL,
    item_db_id INTEGER NOT NULL,
    image_url TEXT NOT NULL,
    image_kind TEXT NOT NULL,
    target_filename TEXT NOT NULL,
    status TEXT DEFAULT 'pending' NOT NULL, -- pending, processing, completed, failed
    attempts INTEGER DEFAULT 0 NOT NULL,
    last_attempt_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
);
'''

def upgrade():
    print(f"Attempting to connect to database at: {DB_PATH}")
    if not os.path.exists(INSTANCE_FOLDER_PATH):
        print(f"Error: Instance folder {INSTANCE_FOLDER_PATH} does not exist. Migration cannot proceed.")
        return
    if not os.path.exists(os.path.dirname(DB_PATH)):
        print(f"Error: Directory for DB_PATH {os.path.dirname(DB_PATH)} does not exist. Migration cannot proceed.")
        return

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        print("Successfully connected to the database.")

        # Check if the table already exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='image_cache_queue';")
        if cursor.fetchone():
            print("'image_cache_queue' table already exists.")
        else:
            print("Creating 'image_cache_queue' table...")
            cursor.executescript(TABLE_SCHEMA) # Use executescript for CREATE TABLE IF NOT EXISTS
            conn.commit()
            print("'image_cache_queue' table created successfully.")
            
    except sqlite3.Error as e:
        print(f"SQLite error during migration: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
            print("Database connection closed.")

if __name__ == '__main__':
    if not os.path.exists(INSTANCE_FOLDER_PATH):
        try:
            os.makedirs(INSTANCE_FOLDER_PATH)
            print(f"Created instance folder: {INSTANCE_FOLDER_PATH}")
        except OSError as e:
            print(f"Error creating instance folder {INSTANCE_FOLDER_PATH}: {e}")
            exit(1)
            
    upgrade()
