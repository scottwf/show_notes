"""
Migration 045: Add admin announcements system

Creates table for site-wide admin announcements.
"""

import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    print("Running migration 045: Add announcements system")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Create announcements table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            type TEXT DEFAULT 'info',
            is_active BOOLEAN DEFAULT 1,
            start_date DATETIME,
            end_date DATETIME,
            created_by INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE SET NULL
        )
    """)
    print("✓ Created announcements table")

    # Create index
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_announcements_active
        ON announcements(is_active, start_date, end_date)
    """)
    print("✓ Created index idx_announcements_active")

    conn.commit()
    conn.close()

    print("✅ Migration 045 completed successfully")

if __name__ == '__main__':
    upgrade()
