import os
import json
import requests
import re
import sqlite3
import time
import datetime
from datetime import timezone
import urllib.parse
import logging

from flask import (
    render_template, request, redirect, url_for, session, jsonify,
    flash, current_app, Response, abort, g
)
from flask_login import login_required, current_user

from ... import database


last_plex_event = None

# ── Household member helpers ──────────────────────────────────────────────────

MEMBER_AVATAR_COLORS = [
    '#0ea5e9', '#8b5cf6', '#10b981', '#f59e0b',
    '#ef4444', '#ec4899', '#f97316', '#06b6d4',
]

def get_current_member():
    """Return the active household_member row for this session, or None."""
    member_id = session.get('member_id')
    if not member_id:
        return None
    db = database.get_db()
    return db.execute(
        'SELECT * FROM household_members WHERE id = ? AND user_id = ?',
        (member_id, session.get('user_id'))
    ).fetchone()

def get_user_members(user_id):
    """Return all household members for a user."""
    db = database.get_db()
    return db.execute(
        'SELECT * FROM household_members WHERE user_id = ? ORDER BY is_default DESC, created_at ASC',
        (user_id,)
    ).fetchall()

def set_member_session(member_id):
    """Store the chosen member_id in the Flask session and record activity time."""
    session['member_id'] = member_id
    session.modified = True
    try:
        db = database.get_db()
        db.execute('UPDATE household_members SET last_active_at = CURRENT_TIMESTAMP WHERE id = ?', (member_id,))
        db.commit()
    except Exception:
        pass


def _get_cached_value(cache_key, ttl_seconds, loader):
    now = time.time()
    with _homepage_cache_lock:
        cached = _homepage_cache.get(cache_key)
        if cached and now - cached['timestamp'] < ttl_seconds:
            return cached['value']

    value = loader()

    with _homepage_cache_lock:
        _homepage_cache[cache_key] = {
            'timestamp': now,
            'value': value,
        }

    return value

def _get_cached_image_path(image_type, tmdb_id, variant='full'):
    if variant == 'thumb':
        return os.path.join(current_app.static_folder, image_type, 'thumbs', f'{tmdb_id}.jpg')
    return os.path.join(current_app.static_folder, image_type, f'{tmdb_id}.jpg')

def _get_media_image_url(image_type, tmdb_id, variant='full'):
    if not tmdb_id:
        placeholder = f'logos/placeholder_{image_type}.png'
        if os.path.exists(os.path.join(current_app.static_folder, placeholder)):
            return url_for('static', filename=placeholder)
        return url_for('static', filename='logos/placeholder_poster.png')

    cached_filename = f'{image_type}/{tmdb_id}.jpg'
    if variant == 'thumb':
        cached_filename = f'{image_type}/thumbs/{tmdb_id}.jpg'

    cached_path = _get_cached_image_path(image_type, tmdb_id, variant=variant)
    if os.path.exists(cached_path):
        return url_for('static', filename=cached_filename)
    return url_for('main.image_proxy', type=image_type, id=tmdb_id, variant=variant)

def is_onboarding_complete():
    """
    Checks if the initial application setup has been completed.

    This function determines if onboarding is necessary by checking for the
    existence of at least one admin user and at least one settings record in the
    database.

    Returns:
        bool: True if both an admin user and a settings record exist, False otherwise.
    """
    try:
        db = database.get_db()
        admin_user = db.execute('SELECT id FROM users WHERE is_admin = 1 LIMIT 1').fetchone()
        settings_record = db.execute('SELECT id FROM settings LIMIT 1').fetchone()
        return admin_user is not None and settings_record is not None
    except sqlite3.OperationalError:
        return False

def _get_profile_stats(db, user_id=None, now_playing_count=None, member_id=None):
    """
    Helper function to get consistent statistics for profile pages.
    Returns dict with: now_playing_count, total_shows, total_episodes, total_movies,
    favorite_count (if user_id provided), unread_notification_count (if user_id provided)

    Performance optimization: Consolidated queries to reduce database round-trips.

    Args:
        now_playing_count: Pre-fetched stream count to avoid a redundant Tautulli API call.
                           If None, fetches from Tautulli directly.
        member_id: Household member to scope favorite/notification counts to.
    """
    from ..utils import get_tautulli_activity
    import pytz
    from datetime import datetime as _dt

    stats = {}

    # Now Playing: use pre-fetched count if provided, otherwise call Tautulli
    if now_playing_count is not None:
        stats['now_playing_count'] = now_playing_count
    else:
        stats['now_playing_count'] = get_tautulli_activity()

    # Compute start of today in the app's configured timezone (avoids UTC midnight mismatch)
    tz_name = db.execute("SELECT timezone FROM settings LIMIT 1").fetchone()
    tz_name = tz_name['timezone'] if tz_name and tz_name['timezone'] else 'UTC'
    try:
        tz = pytz.timezone(tz_name)
        local_now = _dt.now(tz)
        today_local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_utc_start = today_local_start.astimezone(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        today_utc_start = _dt.utcnow().strftime('%Y-%m-%d') + ' 00:00:00'

    # Consolidated query for all count statistics to reduce database round-trips
    today_filter = f"event_timestamp >= '{today_utc_start}'"
    play_events = "('media.play', 'media.scrobble')"

    if user_id:
        if member_id:
            consolidated_stats = db.execute(f'''
                SELECT
                    (SELECT COUNT(*) FROM sonarr_shows) as total_shows,
                    (SELECT COUNT(*) FROM sonarr_episodes) as total_episodes,
                    (SELECT COUNT(*) FROM radarr_movies) as total_movies,
                    (SELECT COUNT(*) FROM plex_activity_log
                     WHERE {today_filter} AND event_type IN {play_events}) as plays_today,
                    (SELECT COUNT(DISTINCT plex_username) FROM plex_activity_log
                     WHERE {today_filter}) as active_users_today,
                    (SELECT ROUND(SUM(COALESCE(view_offset_ms, duration_ms)) / 3600000.0, 1)
                     FROM plex_activity_log
                     WHERE {today_filter} AND event_type IN ('media.stop','media.scrobble')) as watch_hours_today,
                    (SELECT COUNT(*) FROM user_favorites WHERE user_id = ? AND member_id = ? AND is_dropped = 0) as favorite_count,
                    (SELECT COUNT(*) FROM user_notifications WHERE user_id = ? AND member_id = ? AND is_read = 0 AND is_dismissed = 0) as unread_notification_count
            ''', (user_id, member_id, user_id, member_id)).fetchone()
        else:
            consolidated_stats = db.execute(f'''
                SELECT
                    (SELECT COUNT(*) FROM sonarr_shows) as total_shows,
                    (SELECT COUNT(*) FROM sonarr_episodes) as total_episodes,
                    (SELECT COUNT(*) FROM radarr_movies) as total_movies,
                    (SELECT COUNT(*) FROM plex_activity_log
                     WHERE {today_filter} AND event_type IN {play_events}) as plays_today,
                    (SELECT COUNT(DISTINCT plex_username) FROM plex_activity_log
                     WHERE {today_filter}) as active_users_today,
                    (SELECT ROUND(SUM(COALESCE(view_offset_ms, duration_ms)) / 3600000.0, 1)
                     FROM plex_activity_log
                     WHERE {today_filter} AND event_type IN ('media.stop','media.scrobble')) as watch_hours_today,
                    (SELECT COUNT(*) FROM user_favorites WHERE user_id = ? AND is_dropped = 0) as favorite_count,
                    (SELECT COUNT(*) FROM user_notifications WHERE user_id = ? AND is_read = 0 AND is_dismissed = 0) as unread_notification_count
            ''', (user_id, user_id)).fetchone()
    else:
        consolidated_stats = db.execute(f'''
            SELECT
                (SELECT COUNT(*) FROM sonarr_shows) as total_shows,
                (SELECT COUNT(*) FROM sonarr_episodes) as total_episodes,
                (SELECT COUNT(*) FROM radarr_movies) as total_movies,
                (SELECT COUNT(*) FROM plex_activity_log
                 WHERE {today_filter} AND event_type IN {play_events}) as plays_today,
                (SELECT COUNT(DISTINCT plex_username) FROM plex_activity_log
                 WHERE {today_filter}) as active_users_today,
                (SELECT ROUND(SUM(COALESCE(view_offset_ms, duration_ms)) / 3600000.0, 1)
                 FROM plex_activity_log
                 WHERE {today_filter} AND event_type IN ('media.stop','media.scrobble')) as watch_hours_today
        ''').fetchone()

    stats['total_shows'] = consolidated_stats['total_shows'] or 0
    stats['total_episodes'] = consolidated_stats['total_episodes'] or 0
    stats['total_movies'] = consolidated_stats['total_movies'] or 0
    stats['plays_today'] = consolidated_stats['plays_today'] or 0
    stats['active_users_today'] = consolidated_stats['active_users_today'] or 0
    watch_h = consolidated_stats['watch_hours_today'] or 0
    stats['watch_hours_today'] = f"{watch_h:.1f}h" if watch_h else "0h"
    # Keep for backwards compat with any other templates still using players_today
    stats['players_today'] = stats['active_users_today']

    if user_id:
        stats['favorite_count'] = consolidated_stats['favorite_count'] or 0
        stats['unread_notification_count'] = consolidated_stats['unread_notification_count'] or 0
    else:
        stats['favorite_count'] = 0
        stats['unread_notification_count'] = 0

    return stats

def _get_plex_event_details(plex_event_row, db):
    """
    Enriches a Plex activity log record with detailed metadata and image URLs.

    This helper function takes a raw row from the `plex_activity_log` table and
    joins it with data from the `sonarr_shows` or `radarr_movies` tables to create
    a comprehensive dictionary of item details. It resolves the correct TMDB ID
    for linking and fetching cached posters, and constructs URLs for detail pages.

    Args:
        plex_event_row (sqlite3.Row): A row object from the `plex_activity_log` table.
        db (sqlite3.Connection): An active database connection.

    Returns:
        dict or None: An enriched dictionary containing details for the media item,
                      including title, year, poster URLs, and links. Returns None if
                      the input row is invalid.
    """
    if not plex_event_row:
        return None

    item_details = dict(plex_event_row)
    media_type = item_details.get('media_type')

    plex_tmdb_id = item_details.get('tmdb_id')
    grandparent_rating_key = item_details.get('grandparent_rating_key')

    item_details['item_type_for_url'] = None
    item_details['tmdb_id_for_poster'] = None
    item_details['link_tmdb_id'] = None

    if media_type == 'movie':
        if plex_tmdb_id:
            movie_data = db.execute(
                'SELECT title, poster_url, year, overview FROM radarr_movies WHERE tmdb_id = ?', (plex_tmdb_id,)
            ).fetchone()
            if movie_data:
                item_details.update(dict(movie_data))
            item_details['tmdb_id_for_poster'] = plex_tmdb_id
            item_details['link_tmdb_id'] = plex_tmdb_id
        else:
            # Fallback: look up by title (used when called from Tautulli live session)
            movie_title = item_details.get('title')
            if movie_title:
                movie_data = db.execute(
                    'SELECT tmdb_id, title, poster_url, year, overview FROM radarr_movies WHERE LOWER(title) = ?',
                    (movie_title.lower(),)
                ).fetchone()
                if movie_data:
                    item_details.update(dict(movie_data))
                    item_details['tmdb_id_for_poster'] = movie_data['tmdb_id']
                    item_details['link_tmdb_id'] = movie_data['tmdb_id']
        item_details['item_type_for_url'] = 'movie'

    elif media_type == 'episode':
        item_details['item_type_for_url'] = 'show'
        item_details['episode_title'] = dict(plex_event_row).get('title')
        show_info = None
        # Try TVDB ID lookup first
        if grandparent_rating_key:
            show_info = db.execute(
                'SELECT id, tmdb_id, title, poster_url, year, overview FROM sonarr_shows WHERE tvdb_id = ?', (grandparent_rating_key,)
            ).fetchone()
        # Fallback: Try to find by show title if TVDB lookup fails
        if not show_info:
            show_title = item_details.get('show_title') or item_details.get('grandparent_title') or item_details.get('title')
            if show_title:
                show_info = db.execute(
                    'SELECT id, tmdb_id, title, poster_url, year, overview FROM sonarr_shows WHERE LOWER(title) = ?', (show_title.lower(),)
                ).fetchone()
                if show_info:
                    current_app.logger.warning(f"_get_plex_event_details: Fallback to title lookup for show '{show_title}' (TVDB ID {grandparent_rating_key})")
        if show_info:
            item_details.update(dict(show_info))
            item_details['tmdb_id_for_poster'] = show_info['tmdb_id']
            item_details['link_tmdb_id'] = show_info['tmdb_id']
            item_details['show_db_id'] = show_info['id']  # Add database ID for favorites
        else:
            current_app.logger.warning(f"_get_plex_event_details: Could not find show for TVDB ID {grandparent_rating_key} or title '{item_details.get('show_title') or item_details.get('grandparent_title') or item_details.get('title')}'")

    item_details.setdefault('title', dict(plex_event_row).get('title'))
    item_details.setdefault('year', None)

    if item_details.get('season_episode') and item_details.get('link_tmdb_id'):
        match = re.match(r'S(\d+)E(\d+)', item_details['season_episode'])
        if match:
            item_details['season_number'] = int(match.group(1))
            item_details['episode_number'] = int(match.group(2))
            item_details['episode_detail_url'] = url_for('main.episode_detail', tmdb_id=item_details['link_tmdb_id'], season_number=item_details['season_number'], episode_number=item_details['episode_number'])

    if item_details.get('tmdb_id_for_poster'):
        item_details['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=item_details['tmdb_id_for_poster'])
        item_details['cached_fanart_url'] = url_for('main.image_proxy', type='background', id=item_details['tmdb_id_for_poster'])
    else:
        item_details['cached_poster_url'] = url_for('static', filename='logos/placeholder_poster.png')
        item_details['cached_fanart_url'] = url_for('static', filename='logos/placeholder_background.png')

    return item_details

def _calculate_show_completion(user_id, show_id):
    """
    Calculate and update show completion percentage.

    Args:
        user_id: User ID
        show_id: Show ID (database ID, not TMDB)
    """
    db = database.get_db()

    # Get total episodes for the show
    total_episodes = db.execute('''
        SELECT COUNT(*) FROM sonarr_episodes WHERE show_id = ?
    ''', (show_id,)).fetchone()[0]

    # Get watched episodes count
    watched_count = db.execute('''
        SELECT COUNT(*) FROM user_episode_progress
        WHERE user_id = ? AND show_id = ? AND is_watched = 1
    ''', (user_id, show_id)).fetchone()[0]

    # Calculate percentage
    percentage = (watched_count / total_episodes * 100) if total_episodes > 0 else 0

    # Update show progress
    db.execute('''
        INSERT INTO user_show_progress (user_id, show_id, total_episodes, watched_episodes, completion_percentage)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (user_id, show_id) DO UPDATE SET
            total_episodes = excluded.total_episodes,
            watched_episodes = excluded.watched_episodes,
            completion_percentage = excluded.completion_percentage,
            updated_at = CURRENT_TIMESTAMP
    ''', (user_id, show_id, total_episodes, watched_count, percentage))

    db.commit()


# ============================================================================
# Watch Progress API Endpoints
# ============================================================================

