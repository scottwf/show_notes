"""
Migration 040: Add remaining columns to radarr_movies

Adds all remaining columns that the Radarr sync expects.
"""

import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    print("Running migration 040: Add remaining Radarr columns")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Check existing columns
    cur.execute("PRAGMA table_info(radarr_movies)")
    existing_cols = [row[1] for row in cur.fetchall()]

    # Add missing columns
    columns_to_add = [
        ('popularity', 'REAL'),
        ('original_title', 'TEXT'),
        ('ratings_imdb_value', 'REAL'),
        ('ratings_imdb_votes', 'INTEGER'),
        ('ratings_tmdb_value', 'REAL'),
        ('ratings_tmdb_votes', 'INTEGER'),
        ('ratings_rottenTomatoes_value', 'REAL'),
        ('ratings_rottenTomatoes_votes', 'INTEGER'),
    ]

    for col_name, col_type in columns_to_add:
        if col_name not in existing_cols:
            cur.execute(f"ALTER TABLE radarr_movies ADD COLUMN {col_name} {col_type}")
            print(f"✓ Added {col_name} column")
        else:
            print(f"✓ {col_name} column already exists")

    conn.commit()
    conn.close()

    print("✅ Migration 040 completed successfully")

if __name__ == '__main__':
    upgrade()
