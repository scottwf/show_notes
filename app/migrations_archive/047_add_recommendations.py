"""
Migration 047: Add recommendations system

Creates table for user recommendations (separate from favorites).
"""

import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    print("Running migration 047: Add recommendations system")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Create user_recommendations table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            show_id INTEGER,
            movie_id INTEGER,
            recommendation_text TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY (show_id) REFERENCES sonarr_shows (id) ON DELETE CASCADE,
            FOREIGN KEY (movie_id) REFERENCES radarr_movies (id) ON DELETE CASCADE,
            UNIQUE (user_id, show_id, movie_id)
        )
    """)
    print("✓ Created user_recommendations table")

    # Create index
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_recommendations_user
        ON user_recommendations(user_id)
    """)
    print("✓ Created index idx_user_recommendations_user")

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_recommendations_show
        ON user_recommendations(show_id)
    """)
    print("✓ Created index idx_user_recommendations_show")

    conn.commit()
    conn.close()

    print("✅ Migration 047 completed successfully")

if __name__ == '__main__':
    upgrade()
