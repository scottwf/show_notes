"""
Migration 048: Add granular privacy settings

Replaces single profile_is_public with separate controls for:
- profile_show_profile (show bio, photo, basic info)
- profile_show_lists (show custom lists)
- profile_show_favorites (show favorites)
- profile_show_history (show watch history)
- profile_show_progress (show watch progress)
"""

import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    print("Running migration 048: Add granular privacy settings")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Add new privacy columns
    columns_to_add = [
        ('profile_show_profile', 'BOOLEAN DEFAULT 1'),
        ('profile_show_lists', 'BOOLEAN DEFAULT 1'),
        ('profile_show_favorites', 'BOOLEAN DEFAULT 1'),
        ('profile_show_history', 'BOOLEAN DEFAULT 0'),
        ('profile_show_progress', 'BOOLEAN DEFAULT 1')
    ]

    for column_name, column_type in columns_to_add:
        try:
            cur.execute(f'ALTER TABLE users ADD COLUMN {column_name} {column_type}')
            print(f"✓ Added column {column_name}")
        except sqlite3.OperationalError as e:
            if 'duplicate column name' in str(e).lower():
                print(f"⚠ Column {column_name} already exists, skipping")
            else:
                raise

    # Migrate existing profile_is_public setting
    # If profile_is_public = 1, enable all privacy settings
    cur.execute('''
        UPDATE users
        SET profile_show_profile = profile_is_public,
            profile_show_lists = profile_is_public,
            profile_show_favorites = profile_is_public,
            profile_show_history = profile_is_public,
            profile_show_progress = profile_is_public
        WHERE profile_is_public IS NOT NULL
    ''')
    print("✓ Migrated existing privacy settings")

    conn.commit()
    conn.close()

    print("✅ Migration 048 completed successfully")

if __name__ == '__main__':
    upgrade()
