#!/usr/bin/env python3
"""
Backfill script for watch progress tracking

This script processes the existing plex_activity_log to populate the
user_episode_progress and user_show_progress tables. It identifies
episodes that users have watched (>= 95% completion) and updates
their progress accordingly.

Usage:
    python3 backfill_watch_progress.py
"""

import sqlite3
import os
import sys
from datetime import datetime

# Add parent directory to path to import app modules
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
sys.path.insert(0, parent_dir)

INSTANCE_FOLDER_PATH = os.path.join(parent_dir, 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))


def calculate_show_completion(conn, user_id, show_id):
    """Calculate and update show completion percentage."""
    cur = conn.cursor()

    # Get total episodes for the show via seasons
    total_episodes = cur.execute('''
        SELECT COUNT(*)
        FROM sonarr_episodes e
        JOIN sonarr_seasons s ON e.season_id = s.id
        WHERE s.show_id = ?
    ''', (show_id,)).fetchone()[0]

    # Get watched episode count
    watched_count = cur.execute('''
        SELECT COUNT(*) FROM user_episode_progress
        WHERE user_id = ? AND show_id = ? AND is_watched = 1
    ''', (user_id, show_id)).fetchone()[0]

    # Calculate percentage
    percentage = (watched_count / total_episodes * 100) if total_episodes > 0 else 0

    # Update or insert show progress
    cur.execute('''
        INSERT INTO user_show_progress (
            user_id, show_id, total_episodes, watched_episodes, completion_percentage, updated_at
        )
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT (user_id, show_id) DO UPDATE SET
            total_episodes = excluded.total_episodes,
            watched_episodes = excluded.watched_episodes,
            completion_percentage = excluded.completion_percentage,
            updated_at = CURRENT_TIMESTAMP
    ''', (user_id, show_id, total_episodes, watched_count, percentage))

    return watched_count, total_episodes, percentage


def backfill_user_progress(conn, user_id, plex_username):
    """Backfill watch progress for a single user."""
    cur = conn.cursor()

    print(f"\nProcessing user: {plex_username} (ID: {user_id})")

    # Get all episode watch events for this user from plex_activity_log
    # We want media.stop, media.scrobble, and watched events for episodes
    watch_events = cur.execute('''
        SELECT
            show_title,
            season_episode,
            view_offset_ms,
            duration_ms,
            event_type,
            MAX(id) as latest_event_id,
            MAX(event_timestamp) as last_watched_at
        FROM plex_activity_log
        WHERE plex_username = ?
            AND event_type IN ('media.stop', 'media.scrobble', 'watched')
            AND media_type = 'episode'
            AND show_title IS NOT NULL
            AND season_episode IS NOT NULL
        GROUP BY show_title, season_episode
        ORDER BY show_title, season_episode
    ''', (plex_username,)).fetchall()

    print(f"Found {len(watch_events)} unique episode watch events")

    episodes_marked = 0
    shows_updated = set()
    shows_not_found = set()
    seasons_not_found = 0
    episodes_not_found = 0
    skipped_percentage = 0

    for event in watch_events:
        show_title = event[0]
        season_episode = event[1]  # Format: S01E01
        view_offset_ms = event[2] or 0
        duration_ms = event[3] or 0
        event_type = event[4]
        last_watched_at = event[6]

        # Calculate watch percentage
        # Mark as watched if:
        # 1. It's a scrobble event (Plex sends this when >= 90% watched), OR
        # 2. Watch percentage >= 95%, OR
        # 3. No duration info (assume fully watched)
        is_scrobble = (event_type == 'media.scrobble')

        if view_offset_ms > 0 and duration_ms > 0:
            # If we have both, calculate percentage
            watch_percentage = (view_offset_ms / duration_ms * 100)

            # Only process if >= 95% watched (unless it's a scrobble)
            if not is_scrobble and watch_percentage < 95:
                skipped_percentage += 1
                continue
        else:
            # For scrobble events or events without view_offset, assume fully watched
            watch_percentage = 100.0

        # Parse season and episode numbers
        try:
            season_num = int(season_episode[1:3])
            episode_num = int(season_episode[4:6])
        except (ValueError, IndexError):
            print(f"  Warning: Could not parse season_episode: {season_episode}")
            continue

        # Get show's internal ID by title
        show_row = cur.execute('SELECT id FROM sonarr_shows WHERE title = ?', (show_title,)).fetchone()
        if not show_row:
            # Try case-insensitive search
            show_row = cur.execute('SELECT id FROM sonarr_shows WHERE LOWER(title) = LOWER(?)', (show_title,)).fetchone()
            if not show_row:
                # Silently skip - this is expected for shows not in Sonarr
                shows_not_found.add(show_title)
                continue

        show_id = show_row[0]

        # Get season's internal ID
        season_row = cur.execute('''
            SELECT id FROM sonarr_seasons
            WHERE show_id = ? AND season_number = ?
        ''', (show_id, season_num)).fetchone()

        if not season_row:
            # Silently skip - season doesn't exist in Sonarr
            seasons_not_found += 1
            continue

        season_id = season_row[0]

        # Get episode's internal ID
        episode_row = cur.execute('''
            SELECT id FROM sonarr_episodes
            WHERE season_id = ? AND episode_number = ?
        ''', (season_id, episode_num)).fetchone()

        if not episode_row:
            # Silently skip - episode doesn't exist in Sonarr
            episodes_not_found += 1
            continue

        episode_id = episode_row[0]

        # Insert or update episode progress
        cur.execute('''
            INSERT INTO user_episode_progress (
                user_id, show_id, episode_id, season_number, episode_number,
                is_watched, watch_count, last_watched_at, marked_manually
            )
            VALUES (?, ?, ?, ?, ?, 1, 1, ?, 0)
            ON CONFLICT (user_id, episode_id) DO UPDATE SET
                is_watched = 1,
                last_watched_at = CASE
                    WHEN excluded.last_watched_at > last_watched_at THEN excluded.last_watched_at
                    ELSE last_watched_at
                END,
                watch_count = watch_count + 1,
                updated_at = CURRENT_TIMESTAMP
        ''', (user_id, show_id, episode_id, season_num, episode_num, last_watched_at))

        episodes_marked += 1
        shows_updated.add(show_id)

    conn.commit()
    print(f"  Marked {episodes_marked} episodes as watched")
    print(f"  Skipped: {skipped_percentage} (< 95% watched), {len(shows_not_found)} shows not in Sonarr, {seasons_not_found} seasons not found, {episodes_not_found} episodes not found")

    # Update show completion for all affected shows
    print(f"  Updating completion for {len(shows_updated)} shows...")
    for show_id in shows_updated:
        watched, total, percentage = calculate_show_completion(conn, user_id, show_id)
        if total > 0:
            show_name = cur.execute('SELECT title FROM sonarr_shows WHERE id = ?', (show_id,)).fetchone()[0]
            print(f"    - {show_name}: {watched}/{total} episodes ({percentage:.1f}%)")

    conn.commit()
    print(f"✓ Completed backfill for {plex_username}")


def main():
    """Main backfill process."""
    print("=" * 70)
    print("Watch Progress Backfill Script")
    print("=" * 70)

    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}")
        sys.exit(1)

    print(f"Database: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Check if required tables exist
    tables_check = cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name IN ('user_episode_progress', 'user_show_progress')
    """).fetchall()

    if len(tables_check) < 2:
        print("Error: Required tables not found. Please run migration 043 first.")
        conn.close()
        sys.exit(1)

    # Get all users with Plex usernames
    users = cur.execute('''
        SELECT id, username, plex_username
        FROM users
        WHERE plex_username IS NOT NULL AND plex_username != ''
    ''').fetchall()

    if not users:
        print("No users with Plex usernames found.")
        conn.close()
        return

    print(f"\nFound {len(users)} user(s) with Plex usernames")

    # Process each user
    total_start = datetime.now()
    for user in users:
        user_id = user[0]
        username = user[1]
        plex_username = user[2]

        try:
            backfill_user_progress(conn, user_id, plex_username)
        except Exception as e:
            print(f"Error processing user {username}: {e}")
            import traceback
            traceback.print_exc()
            continue

    total_time = (datetime.now() - total_start).total_seconds()

    conn.close()

    print("\n" + "=" * 70)
    print(f"✅ Backfill completed in {total_time:.2f} seconds")
    print("=" * 70)


if __name__ == '__main__':
    main()
