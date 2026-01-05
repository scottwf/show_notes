import sqlite3
import os

# Determine the absolute path to the instance folder
INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')

# Determine the database path. Use the environment variable if it's set.
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    """Adds indexes to sonarr_shows and radarr_movies for faster searching."""
    print("Applying migration 007: Add search indexes")
    
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}. Skipping migration.")
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        print("Creating index on sonarr_shows(LOWER(title))...")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sonarr_shows_title_lower ON sonarr_shows(LOWER(title));")

        print("Creating index on radarr_movies(LOWER(title))...")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_radarr_movies_title_lower ON radarr_movies(LOWER(title));")

        conn.commit()
        print("Search indexes created successfully.")

    except sqlite3.Error as e:
        print(f"An error occurred during migration 007: {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()
            print("Database connection closed.")

if __name__ == '__main__':
    print(f"Running migration for database: {DB_PATH}")
    upgrade()
