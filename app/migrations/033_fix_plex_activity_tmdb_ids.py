"""
Migration 033: Fix TMDB IDs in plex_activity_log

This migration updates existing plex_activity_log entries to use the show's TMDB ID
instead of the episode's TMDB ID. This is necessary for episode detail links to work.
"""

import sqlite3
import os

INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))

def upgrade():
    print("Running migration 033: Fix TMDB IDs in plex_activity_log")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Get all plex activity log entries with a grandparent_rating_key (TVDB ID)
    entries = cur.execute("""
        SELECT id, grandparent_rating_key
        FROM plex_activity_log
        WHERE grandparent_rating_key IS NOT NULL
        AND media_type = 'episode'
    """).fetchall()

    updated_count = 0
    for entry in entries:
        try:
            tvdb_id = int(entry['grandparent_rating_key'])

            # Look up the show's TMDB ID from sonarr_shows
            show_record = cur.execute(
                'SELECT tmdb_id FROM sonarr_shows WHERE tvdb_id = ?',
                (tvdb_id,)
            ).fetchone()

            if show_record:
                show_tmdb_id = show_record['tmdb_id']

                # Update the plex_activity_log entry
                cur.execute(
                    'UPDATE plex_activity_log SET tmdb_id = ? WHERE id = ?',
                    (show_tmdb_id, entry['id'])
                )
                updated_count += 1
        except (ValueError, TypeError) as e:
            print(f"  Warning: Could not parse TVDB ID from entry {entry['id']}: {e}")
            continue

    conn.commit()
    conn.close()

    print(f"✅ Migration 033 completed: Updated {updated_count} plex activity log entries")

if __name__ == '__main__':
    upgrade()
