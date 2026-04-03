#!/usr/bin/env python3
"""
Migration 029: Add homepage query indexes

This migration adds a composite Plex activity index to improve the homepage
tracked-show lookup for a specific user and media type.
"""

import os
import sqlite3


def upgrade():
    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'instance',
        'shownotes.sqlite3',
    )

    print(f"Connecting to database at: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    index_name = 'idx_plex_activity_user_media_grandparent'
    index_sql = """
        CREATE INDEX idx_plex_activity_user_media_grandparent
        ON plex_activity_log(plex_username, media_type, grandparent_rating_key)
    """

    try:
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
            (index_name,),
        )
        if cursor.fetchone():
            print(f"  [skip] {index_name} already exists")
            return

        cursor.execute(index_sql)
        conn.commit()
        print(f"  [ok] Created {index_name}")
    except Exception as e:
        conn.rollback()
        print(f"Error during migration: {e}")
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    upgrade()
