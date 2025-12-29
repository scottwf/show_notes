import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS show_cast (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            show_tvmaze_id INTEGER NOT NULL,
            person_id INTEGER NOT NULL,
            person_name TEXT NOT NULL,
            character_id INTEGER,
            character_name TEXT NOT NULL,
            character_image_url TEXT,
            person_image_url TEXT,
            cast_order INTEGER,
            is_voice BOOLEAN DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (show_tvmaze_id, person_id, character_id)
        )
    """)
    print("✓ Created show_cast table")

    # Indexes for efficient querying
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_show_cast_show_tvmaze_id
        ON show_cast(show_tvmaze_id)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_show_cast_person_id
        ON show_cast(person_id)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_show_cast_person_name
        ON show_cast(person_name)
    """)
    print("✓ Created indexes")

    conn.commit()
    conn.close()
    print("\n✅ Migration 030 completed successfully")

if __name__ == '__main__':
    print("Running migration: 030_create_show_cast_table.py")
    upgrade()
