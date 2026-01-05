"""
Migration 043: Add watch progress tables

Creates tables for tracking user watch progress at show and episode levels.
Includes triggers for automatic progress updates.
"""

import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    print("Running migration 043: Add watch progress tables")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Create user_show_progress table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_show_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            show_id INTEGER NOT NULL,
            total_episodes INTEGER,
            watched_episodes INTEGER DEFAULT 0,
            completion_percentage REAL DEFAULT 0.0,
            last_watched_episode_id INTEGER,
            last_watched_at DATETIME,
            status TEXT DEFAULT 'watching',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY (show_id) REFERENCES sonarr_shows (id) ON DELETE CASCADE,
            UNIQUE (user_id, show_id)
        )
    """)
    print("✓ Created user_show_progress table")

    # Create index for user_show_progress
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_show_progress_user_status
        ON user_show_progress(user_id, status)
    """)
    print("✓ Created index idx_user_show_progress_user_status")

    # Create user_episode_progress table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_episode_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            show_id INTEGER NOT NULL,
            episode_id INTEGER NOT NULL,
            season_number INTEGER NOT NULL,
            episode_number INTEGER NOT NULL,
            is_watched BOOLEAN DEFAULT 0,
            watch_count INTEGER DEFAULT 0,
            last_watched_at DATETIME,
            watch_percentage REAL,
            marked_manually BOOLEAN DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY (show_id) REFERENCES sonarr_shows (id) ON DELETE CASCADE,
            FOREIGN KEY (episode_id) REFERENCES sonarr_episodes (id) ON DELETE CASCADE,
            UNIQUE (user_id, episode_id)
        )
    """)
    print("✓ Created user_episode_progress table")

    # Create index for user_episode_progress
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_episode_progress_user_show
        ON user_episode_progress(user_id, show_id, season_number, episode_number)
    """)
    print("✓ Created index idx_user_episode_progress_user_show")

    # Create trigger to update show progress when episode marked watched
    cur.execute("""
        CREATE TRIGGER IF NOT EXISTS update_show_progress_after_episode
        AFTER UPDATE OF is_watched ON user_episode_progress
        WHEN NEW.is_watched = 1 AND OLD.is_watched = 0
        BEGIN
            INSERT INTO user_show_progress (user_id, show_id, watched_episodes, last_watched_episode_id, last_watched_at)
            VALUES (NEW.user_id, NEW.show_id, 1, NEW.episode_id, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id, show_id) DO UPDATE SET
                watched_episodes = watched_episodes + 1,
                last_watched_episode_id = NEW.episode_id,
                last_watched_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP;
        END
    """)
    print("✓ Created trigger update_show_progress_after_episode")

    # Create trigger to update show progress when episode marked unwatched
    cur.execute("""
        CREATE TRIGGER IF NOT EXISTS update_show_progress_after_episode_unwatched
        AFTER UPDATE OF is_watched ON user_episode_progress
        WHEN NEW.is_watched = 0 AND OLD.is_watched = 1
        BEGIN
            UPDATE user_show_progress
            SET watched_episodes = CASE
                    WHEN watched_episodes > 0 THEN watched_episodes - 1
                    ELSE 0
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = NEW.user_id AND show_id = NEW.show_id;
        END
    """)
    print("✓ Created trigger update_show_progress_after_episode_unwatched")

    conn.commit()
    conn.close()

    print("✅ Migration 043 completed successfully")

if __name__ == '__main__':
    upgrade()
