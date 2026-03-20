#!/usr/bin/env python3
"""
Migration 026: Add unique index to sonarr_episodes.sonarr_episode_id

This fixes the Sonarr sync which uses ON CONFLICT (sonarr_episode_id)
to update existing episodes, but requires a UNIQUE constraint to work.
"""

import sqlite3
import os

def upgrade():
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'instance', 'shownotes.sqlite3')

    print(f"Connecting to database at: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Check if unique index already exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_sonarr_episodes_sonarr_episode_id'")
        if cursor.fetchone():
            print("Unique index idx_sonarr_episodes_sonarr_episode_id already exists")
        else:
            # First, check for duplicates that would prevent creating a unique index
            cursor.execute("""
                SELECT sonarr_episode_id, COUNT(*) as cnt
                FROM sonarr_episodes
                WHERE sonarr_episode_id IS NOT NULL
                GROUP BY sonarr_episode_id
                HAVING COUNT(*) > 1
            """)
            duplicates = cursor.fetchall()

            if duplicates:
                print(f"Found {len(duplicates)} duplicate sonarr_episode_ids. Cleaning up...")
                for ep_id, count in duplicates:
                    # Keep only the most recent entry (highest id)
                    cursor.execute("""
                        DELETE FROM sonarr_episodes
                        WHERE sonarr_episode_id = ?
                        AND id NOT IN (
                            SELECT MAX(id) FROM sonarr_episodes WHERE sonarr_episode_id = ?
                        )
                    """, (ep_id, ep_id))
                    print(f"  Removed {count - 1} duplicate(s) for sonarr_episode_id {ep_id}")

            # Now create the unique index
            print("Creating unique index on sonarr_episodes.sonarr_episode_id...")
            cursor.execute("""
                CREATE UNIQUE INDEX idx_sonarr_episodes_sonarr_episode_id
                ON sonarr_episodes(sonarr_episode_id)
            """)
            print("Successfully created unique index")

        conn.commit()
        print("Migration 026 completed successfully")

    except Exception as e:
        conn.rollback()
        print(f"Error during migration: {e}")
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    upgrade()
