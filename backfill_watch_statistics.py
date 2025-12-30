#!/usr/bin/env python3
"""
Backfill Watch Statistics Script

This script populates the user_watch_statistics tables with historical data
from the plex_activity_log table. Run this once to initialize statistics for
existing users with watch history.

Usage:
    python3 backfill_watch_statistics.py
"""

import os
import sys
import sqlite3
import datetime
import json
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent))

# Set up database path
INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
DB_PATH = os.environ.get('SHOWNOTES_DB', os.path.join(INSTANCE_FOLDER_PATH, 'shownotes.sqlite3'))


def get_db_connection():
    """Get a database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def calculate_watch_statistics(conn, user_id, plex_username, start_date, end_date):
    """
    Calculate watch statistics from plex_activity_log for a date range.

    Args:
        conn: Database connection
        user_id: User ID
        plex_username: Plex username
        start_date: Start date (datetime.date)
        end_date: End date (datetime.date)

    Returns:
        dict: Statistics for each date in the range
    """
    cur = conn.cursor()
    stats_by_date = {}
    current_date = start_date

    while current_date <= end_date:
        date_start = datetime.datetime.combine(current_date, datetime.time.min)
        date_end = datetime.datetime.combine(current_date, datetime.time.max)

        # Get all watch events for this date
        events = cur.execute('''
            SELECT
                media_type,
                tmdb_id,
                duration_ms,
                view_offset_ms
            FROM plex_activity_log
            WHERE plex_username = ?
                AND event_timestamp >= ?
                AND event_timestamp <= ?
                AND event_type IN ('media.stop', 'media.scrobble')
        ''', (plex_username, date_start, date_end)).fetchall()

        # Calculate stats for this date
        total_watch_time_ms = 0
        episode_count = 0
        movie_count = 0
        unique_shows = set()

        for event in events:
            # Calculate watch time (use view_offset if available, otherwise duration)
            watch_time = event['view_offset_ms'] or event['duration_ms'] or 0
            total_watch_time_ms += watch_time

            if event['media_type'] == 'episode':
                episode_count += 1
                if event['tmdb_id']:
                    # For episodes, tmdb_id is the show's TMDB ID
                    unique_shows.add(event['tmdb_id'])
            elif event['media_type'] == 'movie':
                movie_count += 1

        # Only store if there was activity
        if total_watch_time_ms > 0 or episode_count > 0 or movie_count > 0:
            stats_by_date[current_date.isoformat()] = {
                'total_watch_time_ms': total_watch_time_ms,
                'episode_count': episode_count,
                'movie_count': movie_count,
                'unique_shows_count': len(unique_shows)
            }

        current_date += datetime.timedelta(days=1)

    return stats_by_date


def calculate_current_streak(conn, user_id):
    """
    Calculate the current watch streak for a user.

    Args:
        conn: Database connection
        user_id: User ID

    Returns:
        tuple: (streak_length, streak_start_date, streak_end_date)
    """
    cur = conn.cursor()

    # Get all dates with watch activity, ordered by date descending
    dates = cur.execute('''
        SELECT stat_date
        FROM user_watch_statistics
        WHERE user_id = ?
            AND (episode_count > 0 OR movie_count > 0)
        ORDER BY stat_date DESC
    ''', (user_id,)).fetchall()

    if not dates:
        return (0, None, None)

    # Check if there's activity today or yesterday
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)

    most_recent_date = datetime.date.fromisoformat(dates[0]['stat_date'])

    if most_recent_date not in [today, yesterday]:
        # Streak is broken
        return (0, None, None)

    # Count consecutive days
    streak_length = 1
    expected_date = most_recent_date - datetime.timedelta(days=1)

    for i in range(1, len(dates)):
        current_date = datetime.date.fromisoformat(dates[i]['stat_date'])

        if current_date == expected_date:
            streak_length += 1
            expected_date -= datetime.timedelta(days=1)
        else:
            # Gap found, streak ends
            break

    streak_start = most_recent_date - datetime.timedelta(days=streak_length - 1)
    streak_end = most_recent_date

    return (streak_length, streak_start, streak_end)


def backfill_user(conn, user_id, plex_username):
    """
    Backfill statistics for a single user.

    Args:
        conn: Database connection
        user_id: User ID
        plex_username: Plex username
    """
    cur = conn.cursor()

    print(f"\n  Processing user: {plex_username} (ID: {user_id})")

    # Find the date range of watch history
    date_range = cur.execute('''
        SELECT
            DATE(MIN(event_timestamp)) as first_date,
            DATE(MAX(event_timestamp)) as last_date
        FROM plex_activity_log
        WHERE plex_username = ?
            AND event_type IN ('media.stop', 'media.scrobble')
    ''', (plex_username,)).fetchone()

    if not date_range['first_date'] or not date_range['last_date']:
        print(f"    No watch history found")
        return

    start_date = datetime.date.fromisoformat(date_range['first_date'])
    end_date = datetime.date.today()

    print(f"    Date range: {start_date} to {end_date}")

    # Calculate statistics for all dates
    print(f"    Calculating statistics...")
    stats = calculate_watch_statistics(conn, user_id, plex_username, start_date, end_date)

    if not stats:
        print(f"    No statistics to insert")
        return

    print(f"    Inserting {len(stats)} days of statistics...")

    # Insert statistics
    for date_str, date_stats in stats.items():
        cur.execute('''
            INSERT OR REPLACE INTO user_watch_statistics
            (user_id, stat_date, total_watch_time_ms, episode_count, movie_count, unique_shows_count)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            date_str,
            date_stats['total_watch_time_ms'],
            date_stats['episode_count'],
            date_stats['movie_count'],
            date_stats['unique_shows_count']
        ))

    conn.commit()
    print(f"    ✓ Inserted statistics")

    # Calculate and insert streak
    print(f"    Calculating watch streak...")
    streak_length, streak_start, streak_end = calculate_current_streak(conn, user_id)

    if streak_length > 0:
        # Mark all existing streaks as not current
        cur.execute('''
            UPDATE user_watch_streaks
            SET is_current = 0
            WHERE user_id = ?
        ''', (user_id,))

        # Insert current streak
        cur.execute('''
            INSERT INTO user_watch_streaks
            (user_id, streak_start_date, streak_end_date, streak_length_days, is_current)
            VALUES (?, ?, ?, ?, 1)
        ''', (user_id, streak_start.isoformat(), streak_end.isoformat(), streak_length))

        conn.commit()
        print(f"    ✓ Current streak: {streak_length} days")
    else:
        print(f"    No active streak")


def main():
    """Main backfill function"""
    print("=" * 70)
    print("Backfill Watch Statistics")
    print("=" * 70)

    if not os.path.exists(DB_PATH):
        print(f"\nError: Database not found at {DB_PATH}")
        return

    conn = get_db_connection()
    cur = conn.cursor()

    # Check if tables exist
    tables_check = cur.execute('''
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='user_watch_statistics'
    ''').fetchone()

    if not tables_check:
        print("\nError: user_watch_statistics table not found.")
        print("Please run migration 041 first.")
        conn.close()
        return

    # Get all users with plex_username
    users = cur.execute('''
        SELECT id, username, plex_username
        FROM users
        WHERE plex_username IS NOT NULL AND plex_username != ''
    ''').fetchall()

    if not users:
        print("\nNo users with Plex accounts found.")
        conn.close()
        return

    print(f"\nFound {len(users)} user(s) with Plex accounts")

    # Backfill each user
    for user in users:
        try:
            backfill_user(conn, user['id'], user['plex_username'])
        except Exception as e:
            print(f"    Error processing user {user['username']}: {e}")
            import traceback
            traceback.print_exc()

    conn.close()

    print("\n" + "=" * 70)
    print("Backfill complete!")
    print("=" * 70)


if __name__ == '__main__':
    main()
