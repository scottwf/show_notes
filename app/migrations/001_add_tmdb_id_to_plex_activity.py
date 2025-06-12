import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def column_exists(cursor, table_name, column_name):
    """Check if a column exists in a table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns

def upgrade():
    print(f"Attempting to upgrade database at: {DB_PATH}")
    db_dir = os.path.dirname(DB_PATH)
    if db_dir: # Ensure db_dir is not an empty string (e.g. if DB_PATH is just 'dbname.db')
        try:
            os.makedirs(db_dir, exist_ok=True) # exist_ok=True prevents error if dir exists
            if not os.path.exists(db_dir): # Should not happen if makedirs worked unless permissions issue
                 print(f"Warning: Directory {db_dir} was not created, proceeding with connect attempt.")
            else:
                 print(f"Ensured directory exists: {db_dir}")
        except OSError as e:
            print(f"Error creating directory {db_dir}: {e}. Proceeding with connect attempt.")

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Check if the table plex_activity_log exists first
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='plex_activity_log';")
        if not cursor.fetchone():
            print(f"Table 'plex_activity_log' does not exist in database {DB_PATH}. Migration unnecessary for this table.")
            return # Exit if table doesn't exist

        if not column_exists(cursor, 'plex_activity_log', 'tmdb_id'):
            print("Adding 'tmdb_id' column to 'plex_activity_log' table...")
            cursor.execute('ALTER TABLE plex_activity_log ADD COLUMN tmdb_id INTEGER')
            conn.commit()
            print("Successfully added 'tmdb_id' column.")
        else:
            print("'tmdb_id' column already exists in 'plex_activity_log'. No action taken.")

    except sqlite3.OperationalError as e:
        # Specific handling for "duplicate column name" which can happen if migration runs again after manual add
        if "duplicate column name: tmdb_id" in str(e).lower():
            print(f"'tmdb_id' column likely already exists (caught OperationalError): {e}")
        else:
            print(f"SQLite OperationalError during migration: {e}")
        if conn:
            conn.rollback()
    except sqlite3.Error as e:
        print(f"General SQLite error during migration: {e}")
        if conn:
            conn.rollback()
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
        print(f"Migration script finished for {DB_PATH}.")

if __name__ == '__main__':
    print("Running migration: 001_add_tmdb_id_to_plex_activity.py")
    upgrade()
