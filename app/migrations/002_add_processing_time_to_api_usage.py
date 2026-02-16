"""
Migration 002: Add processing_time_ms column to api_usage table.

The llm_services.py module already inserts processing_time_ms but the column
was missing from both init_db() and the original schema.
"""
import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))


def get_db_connection():
    if not os.path.exists(INSTANCE_FOLDER_PATH):
        os.makedirs(INSTANCE_FOLDER_PATH, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def upgrade():
    conn = get_db_connection()
    cursor = conn.cursor()

    print(f"Migration 002: Connecting to {DB_PATH}")

    # Add processing_time_ms to api_usage
    try:
        cursor.execute("ALTER TABLE api_usage ADD COLUMN processing_time_ms INTEGER")
        print("  + Added api_usage.processing_time_ms")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            print("  . api_usage.processing_time_ms already exists")
        else:
            raise

    conn.commit()
    conn.close()
    print("\nMigration 002 completed successfully!")


if __name__ == '__main__':
    upgrade()
