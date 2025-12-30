"""
Migration 042: Add custom lists tables

Creates tables for user-created custom lists and list items.
Supports both shows and movies with automatic item counting via triggers.
"""

import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    print("Running migration 042: Add custom lists tables")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Create user_lists table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_lists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            is_public BOOLEAN DEFAULT 0,
            item_count INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    """)
    print("✓ Created user_lists table")

    # Create index for user_lists
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_lists_user_id
        ON user_lists(user_id)
    """)
    print("✓ Created index idx_user_lists_user_id")

    # Create user_list_items table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_list_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            list_id INTEGER NOT NULL,
            media_type TEXT NOT NULL,
            show_id INTEGER,
            movie_id INTEGER,
            notes TEXT,
            added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            sort_order INTEGER,
            FOREIGN KEY (list_id) REFERENCES user_lists (id) ON DELETE CASCADE,
            FOREIGN KEY (show_id) REFERENCES sonarr_shows (id) ON DELETE CASCADE,
            FOREIGN KEY (movie_id) REFERENCES radarr_movies (id) ON DELETE CASCADE,
            UNIQUE (list_id, media_type, show_id, movie_id)
        )
    """)
    print("✓ Created user_list_items table")

    # Create index for user_list_items
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_list_items_list_id
        ON user_list_items(list_id, sort_order)
    """)
    print("✓ Created index idx_user_list_items_list_id")

    # Create trigger to auto-update item_count on insert
    cur.execute("""
        CREATE TRIGGER IF NOT EXISTS update_list_item_count_insert
        AFTER INSERT ON user_list_items
        BEGIN
            UPDATE user_lists
            SET item_count = (SELECT COUNT(*) FROM user_list_items WHERE list_id = NEW.list_id),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = NEW.list_id;
        END
    """)
    print("✓ Created trigger update_list_item_count_insert")

    # Create trigger to auto-update item_count on delete
    cur.execute("""
        CREATE TRIGGER IF NOT EXISTS update_list_item_count_delete
        AFTER DELETE ON user_list_items
        BEGIN
            UPDATE user_lists
            SET item_count = (SELECT COUNT(*) FROM user_list_items WHERE list_id = OLD.list_id),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = OLD.list_id;
        END
    """)
    print("✓ Created trigger update_list_item_count_delete")

    conn.commit()
    conn.close()

    print("✅ Migration 042 completed successfully")

if __name__ == '__main__':
    upgrade()
