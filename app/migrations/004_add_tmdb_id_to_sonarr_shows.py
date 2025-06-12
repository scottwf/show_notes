import sqlite3
import os

# Determine the database path
INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def column_exists(cursor, table_name, column_name):
    """Check if a column exists in a table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns

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

        table_name = 'sonarr_shows'
        column_name = 'tmdb_id'

        if not column_exists(cursor, table_name, column_name):
            print(f"Adding '{column_name}' column to '{table_name}' table...")
            cursor.execute(f'ALTER TABLE {table_name} ADD COLUMN {column_name} INTEGER')
            conn.commit()
            print(f"Successfully added '{column_name}' column to '{table_name}'.")
        else:
            print(f"'{column_name}' column already exists in '{table_name}'. No action taken.")
            
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
