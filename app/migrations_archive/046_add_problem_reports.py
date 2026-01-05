"""
Migration 046: Add problem reporting system

Creates table for user-submitted problem reports.
"""

import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    print("Running migration 046: Add problem reporting system")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Create problem_reports table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS problem_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT DEFAULT 'open',
            priority TEXT DEFAULT 'normal',
            show_id INTEGER,
            movie_id INTEGER,
            episode_id INTEGER,
            admin_notes TEXT,
            resolved_by INTEGER,
            resolved_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY (show_id) REFERENCES sonarr_shows (id) ON DELETE SET NULL,
            FOREIGN KEY (movie_id) REFERENCES radarr_movies (id) ON DELETE SET NULL,
            FOREIGN KEY (resolved_by) REFERENCES users (id) ON DELETE SET NULL
        )
    """)
    print("✓ Created problem_reports table")

    # Create indexes
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_problem_reports_user
        ON problem_reports(user_id)
    """)
    print("✓ Created index idx_problem_reports_user")

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_problem_reports_status
        ON problem_reports(status, created_at DESC)
    """)
    print("✓ Created index idx_problem_reports_status")

    conn.commit()
    conn.close()

    print("✅ Migration 046 completed successfully")

if __name__ == '__main__':
    upgrade()
