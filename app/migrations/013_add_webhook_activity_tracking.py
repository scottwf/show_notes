import sqlite3
import os
import sys

# Determine the database path
INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def get_db_connection():
    # Ensure instance folder exists
    if not os.path.exists(INSTANCE_FOLDER_PATH):
        os.makedirs(INSTANCE_FOLDER_PATH, exist_ok=True)
        print(f"Created instance folder: {INSTANCE_FOLDER_PATH}")
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def table_exists(cursor, table_name):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    return cursor.fetchone() is not None

def migrate():
    print("Running migration: 013_add_webhook_activity_tracking.py")
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Create webhook_activity table
        if not table_exists(cursor, 'webhook_activity'):
            cursor.executescript("""
                CREATE TABLE webhook_activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    service_name TEXT NOT NULL,  -- 'radarr' or 'sonarr'
                    event_type TEXT NOT NULL,    -- 'Download', 'Series', 'Movie', etc.
                    received_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    payload_summary TEXT,        -- Brief summary of the webhook payload
                    processed BOOLEAN DEFAULT 1  -- Whether the webhook was successfully processed
                );
                
                CREATE INDEX idx_webhook_activity_service_time ON webhook_activity (service_name, received_at);
                CREATE INDEX idx_webhook_activity_latest ON webhook_activity (service_name, received_at DESC);
            """)
            print("Created webhook_activity table with indexes.")
        else:
            print("webhook_activity table already exists.")

        # Update schema version
        cursor.execute("UPDATE schema_version SET version = 13 WHERE id = 1")
        
        conn.commit()
        print("Migration 013 completed successfully. Webhook activity tracking added.")

    except sqlite3.Error as e:
        print(f"SQLite error during migration 013: {e}")
        if conn:
            conn.rollback()
    except Exception as e:
        print(f"An unexpected error occurred during migration 013: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    print("Starting migration 013_add_webhook_activity_tracking...")
    migrate()
    print("Migration 013_add_webhook_activity_tracking finished.") 