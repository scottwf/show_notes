import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Get existing columns
    cur.execute("PRAGMA table_info(sonarr_shows)")
    existing_cols = [row[1] for row in cur.fetchall()]

    # Add end_date column (to avoid conflict with existing 'ended' BOOLEAN column)
    if 'end_date' not in existing_cols:
        cur.execute("ALTER TABLE sonarr_shows ADD COLUMN end_date TEXT")
        print("✓ Added end_date column")
    else:
        print("⊘ end_date column already exists")

    conn.commit()
    conn.close()
    print("\n✅ Migration 031 completed successfully")

if __name__ == '__main__':
    print("Running migration: 031_add_end_date_column.py")
    upgrade()
