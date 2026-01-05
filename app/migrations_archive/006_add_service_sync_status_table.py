import sqlite3
import os

# Determine the correct database path
# Based on the project structure, migrations are in app/migrations/
# INSTANCE_FOLDER_PATH should be ../../instance relative to this script
try:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    INSTANCE_FOLDER_PATH = os.path.join(BASE_DIR, 'instance')
    if not os.path.exists(INSTANCE_FOLDER_PATH):
        # This case might occur if the script is run before the instance folder is created by Flask itself
        # For migrations, it's safer to assume it might need creation if accessed directly.
        os.makedirs(INSTANCE_FOLDER_PATH)
except Exception:
    # Fallback for environments where __file__ might not be reliable or for simpler structures
    # This assumes the script is run from a context where 'instance' is a sibling of 'app' or CWD is project root
    INSTANCE_FOLDER_PATH = os.path.join(os.getcwd(), 'instance')
    print(f"Warning: Could not reliably determine instance folder relative to script. Using CWD-based path: {INSTANCE_FOLDER_PATH}.")

DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    print(f"Attempting to connect to database at: {DB_PATH}")
    # Ensure the directory for the database file exists
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir)
            print(f"Created directory for database: {db_dir}")
        except OSError as e:
            print(f"Error creating database directory {db_dir}: {e}")
            return # Cannot proceed if DB directory cannot be created

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Create the service_sync_status table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS service_sync_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_name TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL, -- e.g., 'success', 'in_progress', 'failed_api_error'
            last_successful_sync_at DATETIME,
            last_attempted_sync_at DATETIME NOT NULL,
            message TEXT -- For storing error messages or other details
        );
        """)
        
        conn.commit()
        print("Successfully created 'service_sync_status' table (if it didn't exist).")

    except sqlite3.Error as e:
        print(f"Database error during migration: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
            print("Database connection closed.")

if __name__ == '__main__':
    print("Running migration: 006_add_service_sync_status_table.py")
    upgrade()
    print("Migration 006_add_service_sync_status_table.py completed.")
