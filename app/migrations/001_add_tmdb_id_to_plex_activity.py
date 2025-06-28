import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def column_exists(cursor, table_name, column_name):
    """Check if a column exists in a table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns

def upgrade(conn):
    cursor = conn.cursor()
    # Check if the table plex_activity_log exists first
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='plex_activity_log';")
    if not cursor.fetchone():
        print(f"Table 'plex_activity_log' does not exist in database. Migration unnecessary for this table.")
        return # Exit if table doesn't exist

    if not column_exists(cursor, 'plex_activity_log', 'tmdb_id'):
        print("Adding 'tmdb_id' column to 'plex_activity_log' table...")
        cursor.execute('ALTER TABLE plex_activity_log ADD COLUMN tmdb_id INTEGER')
        conn.commit()
        print("Successfully added 'tmdb_id' column.")
    else:
        print("'tmdb_id' column already exists in 'plex_activity_log'. No action taken.")

if __name__ == '__main__':
    print("Running migration: 001_add_tmdb_id_to_plex_activity.py")
    conn = sqlite3.connect(DB_PATH)
    try:
        upgrade(conn)
    finally:
        conn.close()
