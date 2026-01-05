"""
Migration 051: Add announcement notification tracking

Creates a table to track which announcements users have seen/dismissed,
and adds logic to create notifications for announcements.
"""

import sqlite3
import os

def upgrade():
    db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'instance', 'shownotes.sqlite3')
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    try:
        # Create table to track announcement dismissals
        cur.execute('''
            CREATE TABLE IF NOT EXISTS user_announcement_views (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                announcement_id INTEGER NOT NULL,
                dismissed_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                FOREIGN KEY (announcement_id) REFERENCES announcements (id) ON DELETE CASCADE,
                UNIQUE (user_id, announcement_id)
            )
        ''')

        conn.commit()
        print("✓ Created user_announcement_views table")

    except Exception as e:
        conn.rollback()
        print(f"Error in migration 051: {e}")
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    upgrade()
