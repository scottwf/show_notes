import requests
import time
from flask import current_app
from . import database

# Tautulli API cache to avoid blocking page loads
# Cache stores: {'key': {'data': ..., 'timestamp': ...}}
_tautulli_cache = {}
_TAUTULLI_CACHE_TTL = 30  # seconds - balance between freshness and performance

def _get_cached_tautulli(cache_key):
    """Get cached Tautulli data if still valid."""
    if cache_key in _tautulli_cache:
        cached = _tautulli_cache[cache_key]
        if time.time() - cached['timestamp'] < _TAUTULLI_CACHE_TTL:
            return cached['data']
    return None

def _set_cached_tautulli(cache_key, data):
    """Cache Tautulli data with current timestamp."""
    _tautulli_cache[cache_key] = {
        'data': data,
        'timestamp': time.time()
    }

"""
Utility functions for the ShowNotes application.

This module provides a collection of helper functions that support various operations
within the application. These utilities are designed to be reusable and encapsulate
specific functionalities, particularly for interacting with external services and
handling data transformations.

Key Functionalities:
- **Service Interaction:** Functions to communicate with external APIs such as
  Sonarr, Radarr, Bazarr, Ollama, Tautulli, and Pushover. This includes fetching
  data, synchronizing libraries, and testing service connections.
- **Data Synchronization:** Core logic for pulling library information (shows, movies,
  episodes) and watch history from services and storing it in the local database.
- **Connection Testing:** A suite of functions to validate connectivity and
  authentication with the configured external services, providing feedback to the user.
- **Image Handling:** Helper functions to construct URLs for proxying and caching
  images from external sources, ensuring consistent and efficient image delivery.
- **Data Transformation:** Utility functions for cleaning strings, formatting
  datetime objects, and other data manipulations required across the application.
"""

def sync_tautulli_watch_history(full_import=False, batch_size=1000, max_records=None):
    """
    Synchronizes watch history from Tautulli to the local database.

    This function connects to the Tautulli API to fetch watch history with pagination
    support for bulk imports. It includes duplicate detection to avoid re-inserting
    existing records.

    Args:
        full_import (bool): If True, fetches all history. If False, only fetch since last sync.
        batch_size (int): Number of records to fetch per API call (default: 1000).
        max_records (int): Maximum total records to import (None = unlimited).

    Returns:
        int: The number of new watch history events successfully inserted into the database.

    Raises:
        Exception: Propagates exceptions if Tautulli is not configured or if there's
                   an API communication error.
    """
    db_conn = database.get_db()

    with current_app.app_context():
        tautulli_url = database.get_setting('tautulli_url')
        api_key = database.get_setting('tautulli_api_key')

    if not tautulli_url or not api_key:
        current_app.logger.warning("Tautulli URL or API key not configured. Skipping sync.")
        return 0

    inserted = 0
    duplicates = 0
    errors = 0
    start_offset = 0
    total_fetched = 0

    current_app.logger.info(f"Starting Tautulli sync (full_import={full_import}, batch_size={batch_size})")

    while True:
        # Check if we've hit max_records limit
        if max_records and total_fetched >= max_records:
            current_app.logger.info(f"Reached max_records limit of {max_records}")
            break

        # Fetch batch
        params = {
            'apikey': api_key,
            'cmd': 'get_history',
            'length': batch_size,
            'start': start_offset,
            'order_column': 'date',
            'order_dir': 'desc'
        }

        try:
            resp = requests.get(f"{tautulli_url.rstrip('/')}/api/v2", params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            response_data = data.get('response', {}).get('data', {})
            history_items = response_data.get('data', [])
            total_count = response_data.get('recordsFiltered', 0)

            if not history_items:
                current_app.logger.info("No more history items to fetch")
                break

            total_fetched += len(history_items)
            current_app.logger.info(f"Fetched batch: {len(history_items)} items (offset {start_offset}/{total_count})")

        except Exception as e:
            current_app.logger.error(f"Error fetching Tautulli history at offset {start_offset}: {e}")
            break

        # Process batch
        for item in history_items:
            try:
                # Check for duplicate using session_id and timestamp
                session_id = item.get('session_id')
                event_timestamp = item.get('date')

                if session_id and event_timestamp:
                    existing = db_conn.execute(
                        'SELECT id FROM plex_activity_log WHERE session_key = ? AND event_timestamp = ?',
                        (session_id, event_timestamp)
                    ).fetchone()

                    if existing:
                        duplicates += 1
                        continue

                # Get show's TMDB ID from database
                # grandparent_rating_key is Plex's internal ID, NOT TVDB ID,
                # so we primarily match by show title
                show_tmdb_id = None
                if item.get('media_type') == 'episode':
                    show_title = item.get('grandparent_title')
                    if show_title:
                        show_record = db_conn.execute(
                            'SELECT tmdb_id FROM sonarr_shows WHERE LOWER(title) = LOWER(?)',
                            (show_title,)
                        ).fetchone()
                        if show_record:
                            show_tmdb_id = show_record['tmdb_id']

                db_conn.execute(
                    """INSERT INTO plex_activity_log (
                           event_type, plex_username, player_title, player_uuid, session_key,
                           rating_key, parent_rating_key, grandparent_rating_key, media_type,
                           title, show_title, season_episode, view_offset_ms, duration_ms, event_timestamp,
                           tmdb_id, raw_payload)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        item.get('event') or 'watched',
                        item.get('friendly_name'),
                        item.get('player'),
                        None,
                        item.get('session_id'),
                        item.get('rating_key'),
                        item.get('parent_rating_key'),
                        item.get('grandparent_rating_key'),
                        item.get('media_type'),
                        item.get('title'),
                        item.get('grandparent_title'),  # This is the show title from Tautulli
                        item.get('parent_media_index') and item.get('media_index') and f"S{int(item.get('parent_media_index')):02d}E{int(item.get('media_index')):02d}",
                        item.get('view_offset'),
                        item.get('duration'),
                        item.get('date'),
                        show_tmdb_id,
                        json.dumps(item)
                    )
                )
                inserted += 1

            except Exception as e:
                current_app.logger.warning(f"Failed to insert Tautulli history item: {e}")
                errors += 1
                continue

        # Commit this batch
        db_conn.commit()

        # Check if we've fetched everything
        if total_fetched >= total_count:
            current_app.logger.info("Fetched all available history")
            break

        # If not full import, only do one batch
        if not full_import:
            break

        # Move to next batch
        start_offset += batch_size

    # Update last sync timestamp
    db_conn.execute('UPDATE settings SET tautulli_last_sync = CURRENT_TIMESTAMP WHERE id = 1')
    db_conn.commit()

    current_app.logger.info(
        f"Tautulli sync complete. Inserted: {inserted}, Duplicates: {duplicates}, Errors: {errors}, Total fetched: {total_fetched}"
    )
    return inserted

def process_activity_log_for_watch_status():
    """
    Process plex_activity_log entries to update user_episode_progress with watch indicators.

    This function scans the plex_activity_log for 'media.stop' and 'media.scrobble' events
    for episodes and updates the user_episode_progress table to mark episodes as watched.
    This is useful for backfilling watch status from historical Tautulli imports.

    Returns:
        int: Number of episodes marked as watched
    """
    db = database.get_db()
    updated_count = 0

    current_app.logger.info("Starting to process activity log for watch status...")

    # Backfill tmdb_id for activity log entries that are missing it (e.g., from Tautulli imports)
    # This uses show_title matching against sonarr_shows to populate tmdb_id
    try:
        backfill_result = db.execute("""
            UPDATE plex_activity_log
            SET tmdb_id = (
                SELECT s.tmdb_id FROM sonarr_shows s
                WHERE LOWER(s.title) = LOWER(plex_activity_log.show_title)
                LIMIT 1
            )
            WHERE tmdb_id IS NULL
              AND show_title IS NOT NULL
              AND media_type = 'episode'
        """)
        if backfill_result.rowcount > 0:
            db.commit()
            current_app.logger.info(f"Backfilled tmdb_id for {backfill_result.rowcount} activity log entries")
    except Exception as e:
        current_app.logger.warning(f"tmdb_id backfill failed (non-critical): {e}")

    # Get all stop/scrobble/watched events for episodes
    activity_events = db.execute("""
        SELECT DISTINCT
            pal.event_type,
            pal.plex_username,
            pal.grandparent_rating_key,
            pal.parent_rating_key,
            pal.rating_key,
            pal.tmdb_id,
            pal.show_title,
            pal.season_episode,
            pal.view_offset_ms,
            pal.duration_ms,
            pal.event_timestamp,
            pal.media_type
        FROM plex_activity_log pal
        WHERE pal.media_type = 'episode'
          AND pal.event_type IN ('media.stop', 'media.scrobble', 'watched')
        ORDER BY pal.event_timestamp DESC
    """).fetchall()

    current_app.logger.info(f"Found {len(activity_events)} activity events to process")

    for event in activity_events:
        try:
            # Determine if this event represents a completed watch.
            # Tautulli-imported entries have event_type='watched' and NULL view_offset_ms,
            # so we treat those as watched directly (Tautulli only records completed watches).
            # For Plex webhook entries (media.stop/media.scrobble), use the percentage check.
            event_type = event['event_type'] if 'event_type' in event.keys() else ''

            if event_type == 'watched':
                # Tautulli imports — these are already confirmed watched
                pass
            elif event_type == 'media.scrobble':
                # Plex sends scrobble at ~90% watched — treat as watched
                pass
            else:
                # For media.stop, check watch percentage
                view_offset = event['view_offset_ms'] or 0
                duration = event['duration_ms'] or 0
                watch_percentage = (view_offset / duration * 100) if duration > 0 else 0

                # Only mark as watched if >= 95% complete
                if watch_percentage < 95:
                    continue

            # Get user ID from plex_username
            user_row = db.execute('SELECT id FROM users WHERE plex_username = ?', (event['plex_username'],)).fetchone()
            if not user_row:
                continue

            user_id = user_row['id']

            # Get show info — try tmdb_id first, then fall back to show title matching
            show_row = None
            if event['tmdb_id']:
                show_row = db.execute('SELECT id FROM sonarr_shows WHERE tmdb_id = ?', (event['tmdb_id'],)).fetchone()

            if not show_row and event['show_title']:
                show_row = db.execute(
                    'SELECT id FROM sonarr_shows WHERE LOWER(title) = LOWER(?)',
                    (event['show_title'],)
                ).fetchone()

            if not show_row:
                continue

            show_id = show_row['id']

            # Parse season and episode numbers from season_episode (e.g., "S01E05")
            season_episode = event['season_episode']
            if not season_episode:
                continue

            import re
            match = re.match(r'S(\d+)E(\d+)', season_episode)
            if not match:
                continue

            season_num = int(match.group(1))
            episode_num = int(match.group(2))

            # Get episode ID
            episode_row = db.execute('''
                SELECT e.id
                FROM sonarr_episodes e
                JOIN sonarr_seasons s ON e.season_id = s.id
                WHERE s.show_id = ? AND s.season_number = ? AND e.episode_number = ?
            ''', (show_id, season_num, episode_num)).fetchone()

            if not episode_row:
                continue

            episode_id = episode_row['id']

            # Check if already marked as watched
            existing = db.execute('''
                SELECT is_watched FROM user_episode_progress
                WHERE user_id = ? AND episode_id = ?
            ''', (user_id, episode_id)).fetchone()

            if existing and existing['is_watched']:
                # Already marked as watched
                continue

            # Insert or update episode progress
            db.execute('''
                INSERT INTO user_episode_progress (
                    user_id, episode_id, show_id, season_number, episode_number,
                    is_watched, watch_count, last_watched_at, marked_manually
                )
                VALUES (?, ?, ?, ?, ?, 1, 1, ?, 0)
                ON CONFLICT (user_id, episode_id) DO UPDATE SET
                    is_watched = 1,
                    watch_count = CASE WHEN excluded.is_watched = 1 THEN watch_count + 1 ELSE watch_count END,
                    last_watched_at = excluded.last_watched_at,
                    updated_at = CURRENT_TIMESTAMP
            ''', (user_id, episode_id, show_id, season_num, episode_num, event['event_timestamp']))

            updated_count += 1

            if updated_count % 100 == 0:
                db.commit()
                current_app.logger.info(f"Processed {updated_count} episodes so far...")

        except Exception as e:
            current_app.logger.error(f"Error processing activity event: {e}")
            continue

    db.commit()

    # Recalculate show completions for all users
    users = db.execute('SELECT DISTINCT user_id FROM user_episode_progress').fetchall()
    for user_row in users:
        user_id = user_row['user_id']
        shows = db.execute('SELECT DISTINCT show_id FROM user_episode_progress WHERE user_id = ?', (user_id,)).fetchall()
        for show_row in shows:
            try:
                from app.routes.main import _calculate_show_completion
                _calculate_show_completion(user_id, show_row['show_id'])
            except:
                pass

    db.commit()

    current_app.logger.info(f"Finished processing activity log. Marked {updated_count} episodes as watched")
    return updated_count

def get_tautulli_activity():
    """
    Get current activity (now playing) from Tautulli.

    Returns:
        int: Number of currently active streams, or 0 if unable to fetch

    Note: Reuses the activity_sessions cache to avoid a redundant HTTP call when
    get_tautulli_current_activity() has already fetched sessions this cycle.
    """
    # Reuse the sessions cache (populated by get_tautulli_current_activity)
    # so we don't make a second HTTP call on the same page load.
    cached_sessions = _get_cached_tautulli('activity_sessions')
    if cached_sessions is not None:
        return len(cached_sessions)

    # Sessions not cached yet — fetch them now and cache for both functions
    sessions = _fetch_tautulli_sessions()
    return len(sessions) if sessions else 0

def _fetch_tautulli_sessions():
    """
    Fetch and cache Tautulli activity sessions. Single HTTP call shared by both
    get_tautulli_activity() and get_tautulli_current_activity().

    Returns:
        list: Session dicts, or [] on error/no activity.
    """
    cached = _get_cached_tautulli('activity_sessions')
    if cached is not None:
        return cached

    try:
        tautulli_url = database.get_setting('tautulli_url')
        tautulli_api_key = database.get_setting('tautulli_api_key')

        if not tautulli_url or not tautulli_api_key:
            _set_cached_tautulli('activity_sessions', [])
            return []

        response = requests.get(
            f"{tautulli_url}/api/v2",
            params={'apikey': tautulli_api_key, 'cmd': 'get_activity'},
            timeout=5
        )

        if response.status_code == 200:
            data = response.json()
            if data.get('response', {}).get('result') == 'success':
                sessions = data.get('response', {}).get('data', {}).get('sessions', [])
                _set_cached_tautulli('activity_sessions', sessions)
                return sessions

    except Exception:
        pass

    _set_cached_tautulli('activity_sessions', [])
    return []

def get_tautulli_data(username=None):
    """
    Fetch Tautulli activity in a single API call, returning both the user's current
    session and the total stream count.

    Args:
        username (str, optional): Plex username to find the user's session

    Returns:
        tuple: (user_session_or_None, stream_count_int)
    """
    try:
        sessions = _fetch_tautulli_sessions()
        if sessions is None:
            return None, 0

        stream_count = len(sessions)
        user_session = None
        if username and sessions:
            for session in sessions:
                if session.get('user') == username:
                    user_session = session
                    break
        elif sessions:
            user_session = sessions[0]

        return user_session, stream_count
    except Exception:
        return None, 0

def get_tautulli_current_activity(username=None):
    """
    Get detailed current activity from Tautulli with real-time progress.

    Args:
        username (str, optional): Filter by Plex username

    Returns:
        dict or None: Session data with real-time progress, or None if no activity/error

    Note: Results are cached for 30 seconds to avoid blocking page loads.
    """
    cached_sessions = _fetch_tautulli_sessions()

    # Filter by username if provided
    if username and cached_sessions:
        for session in cached_sessions:
            if session.get('user') == username:
                return session
        return None

    # Otherwise return first session if any
    return cached_sessions[0] if cached_sessions else None

