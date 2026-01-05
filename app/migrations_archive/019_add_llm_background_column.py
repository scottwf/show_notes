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

def column_exists(cursor, table_name, column_name):
    """Check if a column exists in a table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns

def upgrade():
    print(f"Attempting to connect to database at: {DB_PATH}")
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Add llm_background column to episode_characters table
        if not column_exists(cursor, 'episode_characters', 'llm_background'):
            print("Adding llm_background column to episode_characters table...")
            cursor.execute('ALTER TABLE episode_characters ADD COLUMN llm_background TEXT')
            print("✓ Added llm_background column")
        else:
            print("✓ llm_background column already exists")
        
        # Update schema version
        cursor.execute('UPDATE schema_version SET version = 19')
        print("✓ Updated schema version to 19")
        
        conn.commit()
        print("✓ Migration completed successfully")
        
    except Exception as e:
        print(f"✗ Migration failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    upgrade()
