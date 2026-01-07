"""
Main Blueprint for ShowNotes User Interface

This module defines the primary user-facing routes for the ShowNotes application.
It handles core functionalities like user authentication (via Plex OAuth), the
homepage display, search, and detailed views for movies, shows, and episodes.

Key Features:
- **Onboarding:** A flow to guide the administrator through initial setup if the
  application is unconfigured.
- **Plex Integration:** Includes the webhook endpoint to receive real-time updates
  from Plex, and a robust login system using Plex's OAuth mechanism.
- **Homepage:** A dynamic homepage that displays the user's current and previously
  watched media based on their Plex activity.
- **Detailed Views:** Routes to display comprehensive information about specific
  movies, TV shows, and individual episodes, pulling data from the local database
  that has been synced from services like Sonarr and Radarr.
- **Image Proxy:** An endpoint to securely proxy and cache images from external
  sources, preventing mixed content issues and improving performance.
"""
import os
import json
import requests
import re
import sqlite3
import time
import datetime # Added
from datetime import timezone # Added
import urllib.parse
import logging
import markdown as md

from flask import (
    Blueprint, render_template, request, redirect, url_for, session, jsonify,
    flash, current_app, Response, abort
)
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from .. import database

main_bp = Blueprint('main', __name__)

last_plex_event = None

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

@main_bp.before_app_request
def check_onboarding():
    """
    Redirects to the onboarding page if the application is not yet configured.

    This function is registered with `before_app_request` and runs before each
    request. It ensures that unauthenticated users are directed to the onboarding
    page to create an admin account and configure initial settings. It exempts
    critical endpoints like the onboarding page itself, login/logout routes, and
    static file requests to prevent a redirect loop.
    """
    if request.endpoint and 'static' not in request.endpoint:
        # Allow access to specific endpoints even if onboarding is not complete
        exempt_endpoints = [
            'main.onboarding', # Onboarding Step 1 (admin account)
            'main.onboarding_services', # Onboarding Step 2 (service config)
            'main.onboarding_test_service', # Onboarding service testing
            'main.login',
            'main.callback',
            'main.logout',
            'main.plex_webhook'
        ]
        if not is_onboarding_complete() and request.endpoint not in exempt_endpoints:
            flash('Initial setup required. Please complete the onboarding process.', 'info')
            return redirect(url_for('main.onboarding'))

@main_bp.before_app_request
def update_session_profile_photo():
    """
    Update session with profile photo URL if it has changed.
    This ensures the session always reflects the current profile photo from the database,
    even when users upload a new photo.
    """
    if session.get('user_id'):
        try:
            db = database.get_db()
            user_record = db.execute('SELECT profile_photo_url FROM users WHERE id = ?', (session['user_id'],)).fetchone()
            if user_record:
                db_photo_url = user_record['profile_photo_url']
                session_photo_url = session.get('profile_photo_url')
                # Update session if database value is different
                if db_photo_url != session_photo_url:
                    session['profile_photo_url'] = db_photo_url
        except Exception:
            pass  # Silently fail to avoid breaking the request

def _get_profile_stats(db, user_id=None):
    """
    Helper function to get consistent statistics for profile pages.
    Returns dict with: now_playing_count, total_shows, total_episodes, total_movies,
    favorite_count (if user_id provided), unread_notification_count (if user_id provided)
    """
    from ..utils import get_tautulli_activity

    stats = {}

    # Now Playing: get real-time activity from Tautulli
    stats['now_playing_count'] = get_tautulli_activity()

    # Total shows
    stats['total_shows'] = db.execute('SELECT COUNT(*) FROM sonarr_shows').fetchone()[0] or 0

    # Total episodes
    stats['total_episodes'] = db.execute('SELECT COUNT(DISTINCT id) FROM sonarr_episodes').fetchone()[0] or 0

    # Total movies
    stats['total_movies'] = db.execute('SELECT COUNT(*) FROM radarr_movies').fetchone()[0] or 0

    # User-specific stats
    if user_id:
        stats['favorite_count'] = db.execute(
            'SELECT COUNT(*) FROM user_favorites WHERE user_id = ? AND is_dropped = 0',
            (user_id,)
        ).fetchone()[0] or 0

        stats['unread_notification_count'] = db.execute(
            'SELECT COUNT(*) FROM user_notifications WHERE user_id = ? AND is_read = 0',
            (user_id,)
        ).fetchone()[0] or 0
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

@main_bp.route('/')
@login_required
def home():
    """
    User's profile page (watch history with now playing).

    This is the homepage/landing page displaying currently playing media and watch history.
    """
    user_id = session.get('user_id')
    if not user_id:
        flash('Please log in to view your profile.', 'warning')
        return redirect(url_for('main.login'))

    db = database.get_db()

    # Get user info
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

    # Convert user row to dict so we can add the plex_member_since field
    user_dict = dict(user)
    # Use the plex_joined_at from Plex API if available, otherwise fall back to created_at
    user_dict['plex_member_since'] = user_dict.get('plex_joined_at') or user_dict.get('created_at')

    # Get currently playing/paused item from Tautulli (real-time data)
    from ..utils import get_tautulli_current_activity

    current_plex_event = None
    s_username = user['plex_username'] if user['plex_username'] else user['username']

    tautulli_session = get_tautulli_current_activity(username=s_username)

    if tautulli_session:
        # Convert Tautulli session data to our expected format
        # Safely convert numeric values to int
        parent_index = int(tautulli_session.get('parent_media_index', 0) or 0)
        media_index = int(tautulli_session.get('media_index', 0) or 0)
        view_offset = int(tautulli_session.get('view_offset', 0) or 0)
        duration = int(tautulli_session.get('duration', 0) or 0)
        progress_percent = int(tautulli_session.get('progress_percent', 0) or 0)

        current_plex_event = {
            'title': tautulli_session.get('full_title') or tautulli_session.get('title'),
            'media_type': tautulli_session.get('media_type'),
            'show_title': tautulli_session.get('grandparent_title'),
            'season_episode': f"S{parent_index:02d}E{media_index:02d}" if tautulli_session.get('media_type') == 'episode' else None,
            'view_offset_ms': view_offset * 1000,  # Tautulli returns seconds
            'duration_ms': duration * 1000,  # Tautulli returns seconds
            'state': tautulli_session.get('state'),  # playing, paused, buffering
            'progress_percent': progress_percent,
            'year': tautulli_session.get('year'),
            'rating_key': tautulli_session.get('rating_key'),
            'grandparent_rating_key': tautulli_session.get('grandparent_rating_key'),
            'poster_url': tautulli_session.get('thumb'),
        }

        # Try to get TMDB ID from our database
        if current_plex_event['media_type'] == 'movie':
            movie = db.execute('SELECT tmdb_id FROM radarr_movies WHERE title = ?',
                             (current_plex_event['title'],)).fetchone()
            if movie:
                current_plex_event['tmdb_id'] = movie['tmdb_id']
                current_plex_event['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=movie['tmdb_id'])
        elif current_plex_event['media_type'] == 'episode' and current_plex_event['show_title']:
            show = db.execute('SELECT tmdb_id FROM sonarr_shows WHERE LOWER(title) = ?',
                            (current_plex_event['show_title'].lower(),)).fetchone()
            if show:
                current_plex_event['show_tmdb_id'] = show['tmdb_id']
                current_plex_event['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=show['tmdb_id'])

    # Get profile statistics using helper function
    stats = _get_profile_stats(db, user_id)

    # Get watch history (recent 50 unique items)
    # Group by unique episode/movie to show only one entry per item
    # Filter out trailers (duration < 10 minutes = 600000ms)
    watch_history = db.execute("""
        SELECT
            id, event_type, plex_username, media_type, title, show_title,
            season_episode, view_offset_ms, duration_ms, event_timestamp,
            tmdb_id, grandparent_rating_key,
            MAX(event_timestamp) as latest_timestamp
        FROM plex_activity_log
        WHERE plex_username = ?
        AND event_type IN ('media.stop', 'media.scrobble')
        AND (duration_ms IS NULL OR duration_ms >= 600000)
        GROUP BY
            CASE
                WHEN media_type = 'episode' THEN show_title || '-' || season_episode
                WHEN media_type = 'movie' THEN 'movie-' || COALESCE(tmdb_id, title)
                ELSE title
            END
        ORDER BY latest_timestamp DESC
        LIMIT 50
    """, (s_username,)).fetchall()

    # Enrich watch history with show/movie data
    enriched_history = []
    for item in watch_history:
        item_dict = dict(item)

        # Try to get additional metadata
        if item_dict['media_type'] == 'movie' and item_dict.get('tmdb_id'):
            movie = db.execute(
                'SELECT title, year, poster_url FROM radarr_movies WHERE tmdb_id = ?',
                (item_dict['tmdb_id'],)
            ).fetchone()

            if movie:
                item_dict['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=item_dict['tmdb_id'])
                item_dict['detail_url'] = url_for('main.movie_detail', tmdb_id=item_dict['tmdb_id'])

        elif item_dict['media_type'] == 'episode' and item_dict.get('show_title'):
            show = db.execute(
                'SELECT tmdb_id, title, poster_url FROM sonarr_shows WHERE LOWER(title) = ?',
                (item_dict['show_title'].lower(),)
            ).fetchone()

            if show:
                item_dict['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=show['tmdb_id'])
                item_dict['detail_url'] = url_for('main.show_detail', tmdb_id=show['tmdb_id'])

                # Try to find episode detail link
                if item_dict.get('season_episode'):
                    match = re.match(r'S(\d+)E(\d+)', item_dict['season_episode'])
                    if match:
                        season_num = int(match.group(1))
                        episode_num = int(match.group(2))
                        item_dict['episode_detail_url'] = url_for('main.episode_detail',
                                                                    tmdb_id=show['tmdb_id'],
                                                                    season_number=season_num,
                                                                    episode_number=episode_num)


        # Keep raw timestamp for client-side timezone conversion
        # JavaScript will handle displaying in user's local timezone

        enriched_history.append(item_dict)

    return render_template('profile_history.html',
                         user=user_dict,
                         current_plex_event=current_plex_event,
                         watch_history=enriched_history,
                         **stats,
                         active_tab='history')

# ============================================================================
# WEBHOOK ENDPOINTS
# ============================================================================

@main_bp.route('/plex/webhook', methods=['POST'])
def plex_webhook():
    """
    Handles incoming webhook events from a Plex Media Server.

    This endpoint is designed to receive POST requests from Plex. It parses the
    webhook payload for media events (play, pause, stop, scrobble) and logs the
    relevant details into the `plex_activity_log` table. This log is the primary
    source of data for the user-facing homepage.

    It validates the webhook secret if one is configured in the settings to ensure
    the request is coming from the configured Plex server.

    Returns:
        A JSON response indicating success or an error, along with an appropriate
        HTTP status code.
    """
    try:
        if request.is_json:
            payload = request.get_json()
        else:
            payload = json.loads(request.form.get('payload'))
        
        current_app.logger.info(f"Webhook payload: {json.dumps(payload, indent=2)}")
        
        global last_plex_event
        last_plex_event = payload

        event_type = payload.get('event')
        activity_event_types = ['media.play', 'media.pause', 'media.resume', 'media.stop', 'media.scrobble']

        if event_type in activity_event_types:
            db = database.get_db()
            metadata = payload.get('Metadata', {})
            account = payload.get('Account', {})
            player = payload.get('Player', {})

            # Skip trailers and short content (less than 10 minutes)
            duration_ms = metadata.get('duration', 0)
            if duration_ms and duration_ms < 600000:  # 10 minutes in milliseconds
                current_app.logger.info(f"Skipping short content (likely trailer): '{metadata.get('title')}' ({duration_ms}ms)")
                return jsonify({'status': 'skipped', 'reason': 'trailer or short content'}), 200

            tmdb_id = None
            tvdb_id = None
            guids = metadata.get('Guid')
            if isinstance(guids, list):
                for guid_item in guids:
                    guid_str = guid_item.get('id', '')
                    if guid_str.startswith('tmdb://'):
                        try:
                            tmdb_id = int(guid_str.split('//')[1])
                        except Exception:
                            tmdb_id = None
                    if guid_str.startswith('tvdb://'):
                        try:
                            tvdb_id = int(guid_str.split('//')[1])
                        except Exception:
                            tvdb_id = None
            # Fallback: try to get TVDB ID from grandparentRatingKey if not found
            if not tvdb_id:
                try:
                    tvdb_id = int(metadata.get('grandparentRatingKey'))
                except Exception:
                    tvdb_id = None

            # Get the show's TMDB ID from our database using TVDB ID
            show_tmdb_id = None
            if tvdb_id:
                show_record = db.execute('SELECT tmdb_id FROM sonarr_shows WHERE tvdb_id = ?', (tvdb_id,)).fetchone()
                if show_record:
                    show_tmdb_id = show_record['tmdb_id']

            season_num = metadata.get('parentIndex')
            episode_num = metadata.get('index')
            season_episode_str = None
            if metadata.get('type') == 'episode':
                if season_num is not None and episode_num is not None:
                    season_episode_str = f"S{str(season_num).zfill(2)}E{str(episode_num).zfill(2)}"

            sql_insert = """
                INSERT INTO plex_activity_log (
                    event_type, plex_username, player_title, player_uuid, session_key,
                    rating_key, parent_rating_key, grandparent_rating_key, media_type,
                    title, show_title, season_episode, view_offset_ms, duration_ms, tmdb_id, raw_payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            params = (
                event_type, account.get('title'), player.get('title'), player.get('uuid'), metadata.get('sessionKey'),
                metadata.get('ratingKey'), metadata.get('parentRatingKey'), metadata.get('grandparentRatingKey'), metadata.get('type'),
                metadata.get('title'), metadata.get('grandparentTitle'), season_episode_str, metadata.get('viewOffset'),
                metadata.get('duration'), show_tmdb_id, json.dumps(payload)
            )
            db.execute(sql_insert, params)
            db.commit()
            current_app.logger.info(f"Logged event '{event_type}' for '{metadata.get('title')}' to plex_activity_log.")

            # Update user watch statistics for stop/scrobble events
            if event_type in ['media.stop', 'media.scrobble']:
                plex_username = account.get('title')
                if plex_username:
                    user = db.execute('SELECT id FROM users WHERE plex_username = ?', (plex_username,)).fetchone()
                    if user:
                        try:
                            today = datetime.date.today()
                            _update_daily_statistics(user['id'], today)
                            _update_watch_streak(user['id'])
                            current_app.logger.info(f"Updated watch statistics for user {user['id']}")
                        except Exception as stats_error:
                            current_app.logger.error(f"Error updating watch statistics: {stats_error}", exc_info=True)

                        # Update episode watch progress for episodes
                        if metadata.get('type') == 'episode':
                            try:
                                view_offset_ms = metadata.get('viewOffset', 0)
                                duration_ms = metadata.get('duration', 0)
                                watch_percentage = (view_offset_ms / duration_ms * 100) if duration_ms > 0 else 0

                                # Mark as watched if >= 95% complete
                                if watch_percentage >= 95:
                                    # Find the episode in our database
                                    if show_tmdb_id and season_num is not None and episode_num is not None:
                                        # Get the show's internal ID
                                        show_row = db.execute('SELECT id FROM sonarr_shows WHERE tmdb_id = ?', (show_tmdb_id,)).fetchone()
                                        if show_row:
                                            show_id = show_row['id']
                                            # Get the episode's internal ID
                                            episode_row = db.execute('''
                                                SELECT e.id
                                                FROM sonarr_episodes e
                                                JOIN sonarr_seasons s ON e.season_id = s.id
                                                WHERE s.show_id = ? AND s.season_number = ? AND e.episode_number = ?
                                            ''', (show_id, season_num, episode_num)).fetchone()

                                            if episode_row:
                                                episode_id = episode_row['id']

                                                # Insert or update episode progress
                                                db.execute('''
                                                    INSERT INTO user_episode_progress (
                                                        user_id, episode_id, season_number, episode_number,
                                                        is_watched, watch_count, last_watched_at, watch_percentage, marked_manually
                                                    )
                                                    VALUES (?, ?, ?, ?, 1, 1, CURRENT_TIMESTAMP, ?, 0)
                                                    ON CONFLICT (user_id, episode_id) DO UPDATE SET
                                                        is_watched = 1,
                                                        watch_count = watch_count + 1,
                                                        last_watched_at = CURRENT_TIMESTAMP,
                                                        watch_percentage = excluded.watch_percentage,
                                                        updated_at = CURRENT_TIMESTAMP
                                                ''', (user['id'], episode_id, season_num, episode_num, watch_percentage))
                                                db.commit()

                                                # Update show completion
                                                _calculate_show_completion(user['id'], show_id)

                                                current_app.logger.info(f"Marked episode {season_episode_str} as watched for user {user['id']}")
                                            else:
                                                current_app.logger.warning(f"Episode not found in database: show_id={show_id}, S{season_num}E{episode_num}")
                                        else:
                                            current_app.logger.warning(f"Show not found in database with TMDB ID: {show_tmdb_id}")
                            except Exception as progress_error:
                                current_app.logger.error(f"Error updating episode progress: {progress_error}", exc_info=True)

            # --- Store episode character data if available ---
            if metadata.get('type') == 'episode' and 'Role' in metadata:
                episode_rating_key = metadata.get('ratingKey')

                # --- Correctly identify the show's TMDB ID ---
                show_tvdb_id_from_plex = None
                try:
                    show_tvdb_id_from_plex = int(metadata.get('grandparentRatingKey'))
                except (ValueError, TypeError):
                    current_app.logger.warning(f"Could not parse grandparentRatingKey: {metadata.get('grandparentRatingKey')}")

                correct_show_tmdb_id = None
                if show_tvdb_id_from_plex:
                    show_record = db.execute('SELECT tmdb_id FROM sonarr_shows WHERE tvdb_id = ?', (show_tvdb_id_from_plex,)).fetchone()
                    if show_record:
                        correct_show_tmdb_id = show_record['tmdb_id']
                    else:
                        current_app.logger.warning(f"Could not find show in DB with TVDB ID: {show_tvdb_id_from_plex}")

                if not correct_show_tmdb_id:
                    # Fallback to the tmdb_id from the episode's own GUID if show lookup fails
                    correct_show_tmdb_id = tmdb_id
                    current_app.logger.warning(f"Falling back to using episode's TMDB ID ({tmdb_id}) for show, as show lookup failed.")


                # Remove old character rows for this episode
                db.execute('DELETE FROM episode_characters WHERE episode_rating_key = ?', (episode_rating_key,))
                roles = metadata['Role']
                for role in roles:
                    db.execute(
                        'INSERT INTO episode_characters (show_tmdb_id, show_tvdb_id, season_number, episode_number, episode_rating_key, character_name, actor_name, actor_id, actor_thumb) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (
                            correct_show_tmdb_id, # Use the corrected show TMDB ID
                            show_tvdb_id_from_plex, # Use the show's TVDB ID
                            season_num,
                            episode_num,
                            episode_rating_key,
                            role.get('role'),
                            role.get('tag'),
                            role.get('id'),
                            role.get('thumb')
                        )
                    )
                db.commit()
                current_app.logger.info(f"Stored {len(roles)} episode characters for episode {episode_rating_key} (S{season_num}E{episode_num}) with correct show TMDB ID {correct_show_tmdb_id}")
        
        return '', 200
    except Exception as e:
        current_app.logger.error(f"Error processing Plex webhook: {e}", exc_info=True)
        return 'error', 400


@main_bp.route('/sonarr/webhook', methods=['POST'])
def sonarr_webhook():
    """
    Handles incoming webhook events from Sonarr.

    This endpoint receives webhook notifications from Sonarr when shows, seasons,
    or episodes are added, updated, or removed. It automatically triggers a
    library sync to keep the ShowNotes database up to date.

    Supported events:
    - Download: When episodes are downloaded
    - Series: When series are added/updated
    - Episode: When episodes are added/updated
    - Rename: When files are renamed

    Returns:
        A JSON response indicating success or an error.
    """
    from app.system_logger import syslog, SystemLogger

    current_app.logger.info("Sonarr webhook received.")
    try:
        if request.is_json:
            payload = request.get_json()
        else:
            payload = json.loads(request.form.get('payload', '{}'))

        current_app.logger.info(f"Sonarr webhook received: {json.dumps(payload, indent=2)}")

        event_type = payload.get('eventType')
        series_title = payload.get('series', {}).get('title', 'Unknown')

        # Log webhook receipt
        syslog.info(SystemLogger.WEBHOOK, f"Sonarr webhook received: {event_type}", {
            'event_type': event_type,
            'series': series_title
        })
        
        # Record webhook activity in database
        try:
            db = database.get_db()
            payload_summary = f"Event: {event_type}"
            if event_type == 'Download' and payload.get('series'):
                payload_summary += f" - {payload['series'].get('title', 'Unknown')}"
            elif event_type == 'Series' and payload.get('series'):
                payload_summary += f" - {payload['series'].get('title', 'Unknown')}"
            
            db.execute(
                'INSERT INTO webhook_activity (service_name, event_type, payload_summary) VALUES (?, ?, ?)',
                ('sonarr', event_type, payload_summary)
            )
            db.commit()
        except Exception as e:
            current_app.logger.error(f"Failed to record Sonarr webhook activity: {e}")
        
        # Events that should trigger a library sync
        sync_events = [
            'Download',           # Episode downloaded
            'Series',             # Series added/updated (generic)
            'SeriesAdd',          # Series added (Sonarr v3+)
            'SeriesDelete',       # Series deleted
            'Episode',            # Episode added/updated
            'EpisodeFileDelete',  # Episode file deleted
            'Rename',             # Files renamed
            'Delete',             # Files deleted
            'Health',             # Health check (good for periodic syncs)
            'Test'                # Test event
        ]
        
        if event_type == 'Download':
            current_app.logger.info(f"Sonarr webhook event 'Download' detected, triggering targeted episode update.")
            try:
                # Extract necessary info from the payload
                series_id = payload.get('series', {}).get('id')
                series_title = payload.get('series', {}).get('title', 'Unknown Show')
                episode_ids = [ep.get('id') for ep in payload.get('episodes', [])]
                episodes_info = payload.get('episodes', [])

                if not series_id or not episode_ids:
                    current_app.logger.error("Webhook 'Download' event missing series_id or episode_ids.")
                else:
                    from ..utils import update_sonarr_episode
                    import threading

                    # Capture the real application object to pass to the thread
                    app_instance = current_app._get_current_object()

                    def sync_in_background(app):
                        with app.app_context():
                            from app.system_logger import syslog, SystemLogger

                            current_app.logger.info(f"Starting background targeted Sonarr sync for series {series_id}.")
                            syslog.info(SystemLogger.SYNC, f"Starting targeted sync: {series_title}", {
                                'series_id': series_id,
                                'episode_count': len(episode_ids)
                            })

                            try:
                                update_sonarr_episode(series_id, episode_ids)
                                current_app.logger.info(f"Targeted episode sync for series {series_id} completed.")
                                syslog.success(SystemLogger.SYNC, f"Episode sync complete: {series_title}")

                                # TVMaze enrichment for the show
                                try:
                                    from app.tvmaze_enrichment import tvmaze_enrichment_service
                                    db_temp = database.get_db()

                                    show_row = db_temp.execute(
                                        'SELECT * FROM sonarr_shows WHERE sonarr_id = ?',
                                        (series_id,)
                                    ).fetchone()

                                    if show_row and tvmaze_enrichment_service.should_enrich_show(dict(show_row)):
                                        syslog.info(SystemLogger.ENRICHMENT, f"Starting TVMaze enrichment: {series_title}")
                                        success = tvmaze_enrichment_service.enrich_show(dict(show_row))
                                        if success:
                                            syslog.success(SystemLogger.ENRICHMENT, f"TVMaze enrichment complete: {series_title}")
                                        else:
                                            syslog.warning(SystemLogger.ENRICHMENT, f"TVMaze enrichment failed: {series_title}")
                                except Exception as e_enrich:
                                    syslog.error(SystemLogger.ENRICHMENT, f"TVMaze enrichment error: {series_title}", {
                                        'error': str(e_enrich)
                                    })
                                    current_app.logger.error(f"TVMaze enrichment failed: {e_enrich}")

                                # Create notifications for users who favorited this show
                                try:
                                    db = database.get_db()

                                    # Find the show in our database
                                    show = db.execute(
                                        'SELECT id, tmdb_id, title FROM sonarr_shows WHERE sonarr_id = ?',
                                        (series_id,)
                                    ).fetchone()

                                    if show:
                                        # Find users who favorited this show
                                        favorited_users = db.execute('''
                                            SELECT user_id FROM user_favorites
                                            WHERE show_id = ? AND is_dropped = 0
                                        ''', (show['id'],)).fetchall()

                                        # Create notification for each user
                                        for user in favorited_users:
                                            for episode in episodes_info:
                                                season_num = episode.get('seasonNumber')
                                                episode_num = episode.get('episodeNumber')
                                                episode_title = episode.get('title', f'Episode {episode_num}')

                                                notification_title = f"New Episode: {series_title}"
                                                notification_message = f"S{season_num:02d}E{episode_num:02d}: {episode_title} is now available!"

                                                db.execute('''
                                                    INSERT INTO user_notifications
                                                    (user_id, show_id, notification_type, title, message, season_number, episode_number)
                                                    VALUES (?, ?, ?, ?, ?, ?, ?)
                                                ''', (
                                                    user['user_id'],
                                                    show['id'],
                                                    'new_episode',
                                                    notification_title,
                                                    notification_message,
                                                    season_num,
                                                    episode_num
                                                ))

                                        db.commit()
                                        current_app.logger.info(f"Created notifications for {len(favorited_users)} users about {len(episodes_info)} new episodes")
                                        syslog.success(SystemLogger.NOTIFICATION, f"Created {len(favorited_users)} notifications for {series_title}", {
                                            'user_count': len(favorited_users),
                                            'episode_count': len(episodes_info)
                                        })
                                    else:
                                        current_app.logger.warning(f"Show with sonarr_id {series_id} not found in database")
                                        syslog.warning(SystemLogger.SYNC, f"Show not found in database: sonarr_id {series_id}")

                                except Exception as e:
                                    current_app.logger.error(f"Error creating notifications: {e}", exc_info=True)
                                    syslog.error(SystemLogger.NOTIFICATION, f"Failed to create notifications for {series_title}", {
                                        'error': str(e)
                                    })

                            except Exception as e:
                                current_app.logger.error(f"Error in background targeted Sonarr sync: {e}", exc_info=True)

                    sync_thread = threading.Thread(target=sync_in_background, args=(app_instance,))
                    sync_thread.daemon = True
                    sync_thread.start()
                    current_app.logger.info(f"Initiated targeted background sync for series {series_id}, episodes {episode_ids}")

            except Exception as e:
                current_app.logger.error(f"Failed to trigger targeted Sonarr sync from webhook: {e}", exc_info=True)
        
        elif event_type in sync_events:
            current_app.logger.info(f"Sonarr webhook event '{event_type}' detected, triggering full library sync as a fallback.")
            
            # Import here to avoid circular imports
            from ..utils import sync_sonarr_library
            
            try:
                # Trigger the sync in a background thread to avoid blocking the webhook response
                import threading
                
                # Capture the real application object to pass to the thread
                app_instance = current_app._get_current_object()

                def sync_in_background(app):
                    with app.app_context():
                        from app.system_logger import syslog, SystemLogger

                        current_app.logger.info("Starting background Sonarr library sync.")
                        syslog.info(SystemLogger.SYNC, f"Starting full library sync (event: {event_type})")

                        try:
                            count = sync_sonarr_library()
                            current_app.logger.info(f"Sonarr webhook-triggered sync completed: {count} shows processed")
                            syslog.success(SystemLogger.SYNC, f"Full library sync complete: {count} shows processed", {
                                'show_count': count,
                                'event_type': event_type
                            })
                        except Exception as e:
                            current_app.logger.error(f"Error in background Sonarr sync: {e}", exc_info=True)
                            syslog.error(SystemLogger.SYNC, "Full library sync failed", {
                                'error': str(e),
                                'event_type': event_type
                            })
                
                # Start background sync
                sync_thread = threading.Thread(target=sync_in_background, args=(app_instance,))
                sync_thread.daemon = True
                sync_thread.start()
                
                current_app.logger.info("Sonarr library sync initiated in background")
                
            except Exception as e:
                current_app.logger.error(f"Failed to trigger Sonarr sync from webhook: {e}", exc_info=True)
        else:
            current_app.logger.debug(f"Sonarr webhook event '{event_type}' received but no sync needed")
        
        return jsonify({'status': 'success', 'message': f'Processed {event_type} event'}), 200
        
    except Exception as e:
        current_app.logger.error(f"Error processing Sonarr webhook: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@main_bp.route('/radarr/webhook', methods=['POST'])
def radarr_webhook():
    """
    Handles incoming webhook events from Radarr.

    This endpoint receives webhook notifications from Radarr when movies are
    added, updated, or removed. It automatically triggers a library sync to
    keep the ShowNotes database up to date.

    Supported events:
    - Download: When movies are downloaded
    - Movie: When movies are added/updated
    - Rename: When files are renamed
    - Delete: When files are deleted

    Returns:
        A JSON response indicating success or an error.
    """
    current_app.logger.info("Radarr webhook received.")
    try:
        if request.is_json:
            payload = request.get_json()
        else:
            payload = json.loads(request.form.get('payload', '{}'))
        
        current_app.logger.info(f"Radarr webhook received: {json.dumps(payload, indent=2)}")
        
        event_type = payload.get('eventType')
        
        # Record webhook activity in database
        try:
            db = database.get_db()
            payload_summary = f"Event: {event_type}"
            if event_type == 'Download' and payload.get('movie'):
                payload_summary += f" - {payload['movie'].get('title', 'Unknown')}"
            elif event_type == 'Movie' and payload.get('movie'):
                payload_summary += f" - {payload['movie'].get('title', 'Unknown')}"
            
            db.execute(
                'INSERT INTO webhook_activity (service_name, event_type, payload_summary) VALUES (?, ?, ?)',
                ('radarr', event_type, payload_summary)
            )
            db.commit()
        except Exception as e:
            current_app.logger.error(f"Failed to record Radarr webhook activity: {e}")
        
        # Events that should trigger a library sync
        sync_events = [
            'Download',           # Movie downloaded
            'Movie',              # Movie added/updated (generic)
            'MovieAdded',         # Movie added (Radarr v3+)
            'MovieDelete',        # Movie deleted
            'MovieFileDelete',    # Movie file deleted
            'Rename',             # Files renamed
            'Delete',             # Files deleted
            'Health',             # Health check (good for periodic syncs)
            'Test'                # Test event
        ]
        
        if event_type in sync_events:
            current_app.logger.info(f"Radarr webhook event '{event_type}' detected, triggering library sync")
            
            # Import here to avoid circular imports
            from ..utils import sync_radarr_library
            
            try:
                # Trigger the sync in a background thread to avoid blocking the webhook response
                import threading

                # Capture the real application object to pass to the thread
                app_instance = current_app._get_current_object()

                def sync_in_background(app):
                    with app.app_context():
                        current_app.logger.info("Starting background Radarr library sync.")
                        try:
                            result = sync_radarr_library()
                            current_app.logger.info(f"Radarr webhook-triggered sync completed: {result}")
                        except Exception as e:
                            current_app.logger.error(f"Error in background Radarr sync: {e}", exc_info=True)
                
                # Start background sync
                sync_thread = threading.Thread(target=sync_in_background, args=(app_instance,))
                sync_thread.daemon = True
                sync_thread.start()
                
                current_app.logger.info("Radarr library sync initiated in background")
                
            except Exception as e:
                current_app.logger.error(f"Failed to trigger Radarr sync from webhook: {e}", exc_info=True)
        else:
            current_app.logger.debug(f"Radarr webhook event '{event_type}' received but no sync needed")
        
        return jsonify({'status': 'success', 'message': f'Processed {event_type} event'}), 200
        
    except Exception as e:
        current_app.logger.error(f"Error processing Radarr webhook: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    Handles user login via username/password.

    On ``GET`` requests, renders the login page.
    On ``POST`` requests, validates admin credentials and logs the user in.
    """
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        db = database.get_db()
        user_record = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if user_record and user_record['is_admin'] and user_record['password_hash']:
            if check_password_hash(user_record['password_hash'], password):
                user_obj = current_app.login_manager._user_callback(user_record['id'])
                if user_obj:
                    login_user(user_obj, remember=True)  # Enable persistent login for admin too
                    session['user_id'] = user_obj.id
                    session['username'] = user_obj.username
                    session['is_admin'] = user_obj.is_admin
                    session['profile_photo_url'] = user_record['profile_photo_url'] if user_record['profile_photo_url'] else None
                    db.execute('UPDATE users SET last_login_at=CURRENT_TIMESTAMP WHERE id=?', (user_obj.id,))
                    db.commit()
                    flash(f'Welcome back, {user_obj.username}!', 'success')
                    return redirect(url_for('main.home'))
        flash('Invalid admin credentials.', 'danger')
        return redirect(url_for('main.login'))

    # GET request - render login page
    return render_template('login.html')

@main_bp.route('/login/plex/start')
def plex_login_start():
    """
    Initiates the Plex OAuth flow by creating a PIN and returning the auth URL.

    Returns:
        JSON response with the Plex auth URL for the user to authenticate.
    """
    client_id = database.get_setting('plex_client_id')
    if not client_id:
        return jsonify({'error': 'Plex OAuth is not configured'}), 500

    # Create a PIN for Plex OAuth
    headers = {
        'X-Plex-Client-Identifier': client_id,
        'X-Plex-Product': 'ShowNotes',
        'X-Plex-Version': '1.0',
        'X-Plex-Platform': 'Web',
        'X-Plex-Platform-Version': '1.0',
        'X-Plex-Device': 'Browser',
        'X-Plex-Device-Name': 'ShowNotes Web',
        'Accept': 'application/json'
    }

    try:
        response = requests.post('https://plex.tv/api/v2/pins?strong=true', headers=headers)
        response.raise_for_status()
        pin_data = response.json()

        pin_id = pin_data.get('id')
        pin_code = pin_data.get('code')

        if not pin_id or not pin_code:
            return jsonify({'error': 'Failed to generate Plex PIN'}), 500

        # Store PIN ID in session for later polling
        session['plex_pin_id'] = pin_id

        # Build auth URL - don't use forwardUrl since localhost URLs may not be accepted
        # The user will manually close the window after auth, and we'll poll for completion
        auth_url = f'https://app.plex.tv/auth#?clientID={client_id}&code={pin_code}'

        return jsonify({'authUrl': auth_url})

    except Exception as e:
        current_app.logger.error(f"Error starting Plex OAuth: {e}")
        return jsonify({'error': 'Failed to start Plex authentication'}), 500

@main_bp.route('/login/plex/poll')
def plex_login_poll():
    """
    Polls the Plex API to check if the user has authorized the PIN.

    Returns:
        JSON response indicating whether authorization is complete.
    """
    pin_id = session.get('plex_pin_id')
    client_id = database.get_setting('plex_client_id')

    if not pin_id or not client_id:
        return jsonify({'authorized': False, 'error': 'No active PIN session'}), 400

    headers = {
        'X-Plex-Client-Identifier': client_id,
        'Accept': 'application/json'
    }

    try:
        response = requests.get(f'https://plex.tv/api/v2/pins/{pin_id}', headers=headers)
        response.raise_for_status()
        data = response.json()

        auth_token = data.get('authToken')

        if auth_token:
            # Get user info from Plex
            headers['X-Plex-Token'] = auth_token
            user_response = requests.get('https://plex.tv/api/v2/user', headers=headers)
            user_response.raise_for_status()
            user_info = user_response.json()

            plex_user_id = user_info.get('id')
            plex_username = user_info.get('username') or user_info.get('title')
            plex_joined_at_timestamp = user_info.get('joinedAt')  # Get Plex account creation date (Unix timestamp)

            # Convert Unix timestamp to ISO datetime string
            plex_joined_at = None
            if plex_joined_at_timestamp:
                plex_joined_at = datetime.datetime.fromtimestamp(plex_joined_at_timestamp, tz=timezone.utc).isoformat()

            # Check if user exists in database
            db = database.get_db()
            user_record = db.execute('SELECT * FROM users WHERE plex_user_id = ?', (plex_user_id,)).fetchone()

            if user_record:
                # Log in the user
                user_obj = current_app.login_manager._user_callback(user_record['id'])
                if user_obj:
                    login_user(user_obj, remember=True)
                    session['user_id'] = user_obj.id
                    session['username'] = user_obj.username
                    session['is_admin'] = user_obj.is_admin
                    user_record = db.execute('SELECT profile_photo_url FROM users WHERE id = ?', (user_obj.id,)).fetchone()
                    session['profile_photo_url'] = user_record['profile_photo_url'] if user_record and user_record['profile_photo_url'] else None

                    # Update plex token, last login, and Plex join date
                    if plex_joined_at:
                        db.execute('UPDATE users SET plex_token=?, last_login_at=CURRENT_TIMESTAMP, plex_joined_at=? WHERE id=?',
                                  (auth_token, plex_joined_at, user_obj.id))
                    else:
                        db.execute('UPDATE users SET plex_token=?, last_login_at=CURRENT_TIMESTAMP WHERE id=?',
                                  (auth_token, user_obj.id))
                    db.commit()
                    return jsonify({'authorized': True, 'username': user_obj.username})
            else:
                # If admin is already logged in, link their account to Plex
                if current_user.is_authenticated and current_user.is_admin:
                    if plex_joined_at:
                        db.execute('UPDATE users SET plex_user_id=?, plex_username=?, plex_token=?, plex_joined_at=? WHERE id=?',
                                  (plex_user_id, plex_username, auth_token, plex_joined_at, current_user.id))
                    else:
                        db.execute('UPDATE users SET plex_user_id=?, plex_username=?, plex_token=? WHERE id=?',
                                  (plex_user_id, plex_username, auth_token, current_user.id))
                    db.commit()
                    return jsonify({'authorized': True, 'username': current_user.username, 'linked': True})
                else:
                    return jsonify({'authorized': False, 'error': f'Plex user {plex_username} is not registered in this application'})

        return jsonify({'authorized': False})

    except Exception as e:
        current_app.logger.error(f"Error polling Plex auth status: {e}")
        return jsonify({'authorized': False, 'error': str(e)}), 500

@main_bp.route('/callback')
def callback():
    """
    Handles the callback from the Plex OAuth authentication process.

    After the user authenticates with Plex, Plex redirects them back to this
    endpoint. This function checks the status of the PIN associated with the
    client ID. If the PIN has been authorized, it retrieves the user's Plex
    auth token, username, and other details.

    It then either finds an existing user in the database or creates a new one,
    logs the user in, and redirects them to the homepage.

    Returns:
        A redirect to the homepage on successful login, or an error page/message
        on failure.
    """
    pin_id = session.get('plex_pin_id')
    client_id = database.get_setting('plex_client_id')
    if not pin_id or not client_id:
        flash('Plex OAuth is not configured. Please use username/password login.', 'info')
        return redirect(url_for('main.login'))

    # Poll for auth token
    poll_url = f'https://plex.tv/api/v2/pins/{pin_id}'
    headers = {'X-Plex-Client-Identifier': client_id, 'Accept': 'application/json'}
    start_time = time.time()
    auth_token = None
    while time.time() - start_time < 120: # 2 minute timeout
        r = requests.get(poll_url, headers=headers)
        if r.status_code == 200:
            data = r.json()
            if data.get('authToken'):
                auth_token = data['authToken']
                break
        time.sleep(2)
    
    if not auth_token:
        flash('Plex login failed or timed out.', 'danger')
        return redirect(url_for('main.home'))

    # Get user info from Plex
    headers['X-Plex-Token'] = auth_token
    r = requests.get('https://plex.tv/api/v2/user', headers=headers)
    if r.status_code != 200:
        flash('Failed to retrieve user information from Plex.', 'danger')
        return redirect(url_for('main.home'))
    
    user_info = r.json()
    plex_user_id = user_info.get('id')
    plex_joined_at_timestamp = user_info.get('joinedAt')  # Get Plex account creation date (Unix timestamp)

    # Convert Unix timestamp to ISO datetime string
    plex_joined_at = None
    if plex_joined_at_timestamp:
        plex_joined_at = datetime.datetime.fromtimestamp(plex_joined_at_timestamp, tz=timezone.utc).isoformat()

    db = database.get_db()
    user_record = db.execute('SELECT * FROM users WHERE plex_user_id = ?', (plex_user_id,)).fetchone()

    if not user_record:
        flash(f"Plex user {user_info.get('username')} is not registered in this application.", 'warning')
        return redirect(url_for('main.home'))

    # Log in the user
    user_obj = current_app.login_manager._user_callback(user_record['id'])
    if user_obj:
        login_user(user_obj, remember=True)  # Enable persistent login
        session['user_id'] = user_obj.id
        session['username'] = user_obj.username
        session['is_admin'] = user_obj.is_admin
        user_record = db.execute('SELECT profile_photo_url FROM users WHERE id = ?', (user_obj.id,)).fetchone()
        session['profile_photo_url'] = user_record['profile_photo_url'] if user_record and user_record['profile_photo_url'] else None

        # Update last login and Plex join date
        if plex_joined_at:
            db.execute('UPDATE users SET last_login_at=CURRENT_TIMESTAMP, plex_joined_at=? WHERE id=?',
                      (plex_joined_at, user_obj.id))
        else:
            db.execute('UPDATE users SET last_login_at=CURRENT_TIMESTAMP WHERE id=?', (user_obj.id,))
        db.commit()
        flash(f'Welcome back, {user_obj.username}!', 'success')
    else:
        flash('Could not log you in. Please contact an administrator.', 'danger')

    return redirect(url_for('main.home'))

@main_bp.route('/logout')
@login_required
def logout():
    """
    Logs the current user out.

    This route clears the user's session data and logs them out using Flask-Login's
    `logout_user` function. It then redirects the user to the homepage.

    Returns:
        A redirect to the homepage.
    """
    logout_user()
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.home'))

@main_bp.route('/onboarding', methods=['GET', 'POST'])
def onboarding():
    """
    Step 1 of onboarding: Create admin account.

    If onboarding is already complete, redirects to homepage.
    On POST, creates admin user and redirects to Step 2 (service configuration).
    """
    if is_onboarding_complete():
        return redirect(url_for('main.home'))

    if request.method == 'POST':
        db = database.get_db()
        try:
            # Create admin user
            pw_hash = generate_password_hash(request.form['password'])
            db.execute(
                'INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)',
                (request.form['username'], pw_hash)
            )
            db.commit()

            # Store username in session for Step 2
            session['onboarding_username'] = request.form['username']

            flash('Admin account created! Now configure your services.', 'success')
            return redirect(url_for('main.onboarding_services'))
        except Exception as e:
            db.rollback()
            flash(f'An error occurred: {e}', 'danger')
            current_app.logger.error(f"Onboarding Step 1 error: {e}", exc_info=True)

    return render_template('onboarding.html')

@main_bp.route('/onboarding/services', methods=['GET', 'POST'])
def onboarding_services():
    """
    Step 2 of onboarding: Configure services (Radarr, Sonarr, Tautulli, etc.)

    Requires that Step 1 (admin account creation) has been completed.
    On POST, creates settings record and completes onboarding.
    On GET, pre-populates form fields from .env file if available.
    """
    # Check if Step 1 is complete (admin user exists)
    db = database.get_db()
    admin_user = db.execute('SELECT id FROM users WHERE is_admin = 1 LIMIT 1').fetchone()

    if not admin_user:
        flash('Please create an admin account first.', 'warning')
        return redirect(url_for('main.onboarding'))

    # Check if onboarding is already complete (settings exist)
    settings_record = db.execute('SELECT id FROM settings LIMIT 1').fetchone()
    if settings_record:
        flash('Onboarding already complete. Please log in.', 'info')
        return redirect(url_for('main.login'))

    # Load environment variables for pre-populating form
    env_settings = {
        'base_url': os.getenv('BASE_URL', ''),
        'radarr_url': os.getenv('RADARR_URL', ''),
        'radarr_api_key': os.getenv('RADARR_API_KEY', ''),
        'radarr_remote_url': os.getenv('RADARR_REMOTE_URL', ''),
        'sonarr_url': os.getenv('SONARR_URL', ''),
        'sonarr_api_key': os.getenv('SONARR_API_KEY', ''),
        'sonarr_remote_url': os.getenv('SONARR_REMOTE_URL', ''),
        'bazarr_url': os.getenv('BAZARR_URL', ''),
        'bazarr_api_key': os.getenv('BAZARR_API_KEY', ''),
        'tautulli_url': os.getenv('TAUTULLI_URL', ''),
        'tautulli_api_key': os.getenv('TAUTULLI_API_KEY', ''),
        'jellyseer_url': os.getenv('JELLYSEER_URL', ''),
        'jellyseer_api_key': os.getenv('JELLYSEER_API_KEY', ''),
        'ollama_url': os.getenv('OLLAMA_URL', 'http://localhost:11434'),
        'ollama_model': os.getenv('OLLAMA_MODEL', ''),
        'openai_api_key': os.getenv('OPENAI_API_KEY', ''),
        'openai_model': os.getenv('OPENAI_MODEL', ''),
        'pushover_key': os.getenv('PUSHOVER_USER_KEY', ''),
        'pushover_token': os.getenv('PUSHOVER_API_TOKEN', ''),
        'plex_client_id': os.getenv('PLEX_CLIENT_ID', '')
    }

    if request.method == 'POST':
        try:
            # Get timezone from form, or use browser-detected timezone if available
            timezone = request.form.get('timezone', '')
            
            # Create settings record with service configurations
            db.execute(
                '''INSERT INTO settings (radarr_url, radarr_api_key, radarr_remote_url,
                   sonarr_url, sonarr_api_key, sonarr_remote_url,
                   bazarr_url, bazarr_api_key,
                   tautulli_url, tautulli_api_key,
                   jellyseer_url, jellyseer_api_key,
                   ollama_url, ollama_model_name,
                   openai_api_key, openai_model_name,
                   pushover_key, pushover_token, plex_client_id,
                   timezone)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    request.form.get('radarr_url', ''),
                    request.form.get('radarr_api_key', ''),
                    request.form.get('radarr_remote_url', ''),
                    request.form.get('sonarr_url', ''),
                    request.form.get('sonarr_api_key', ''),
                    request.form.get('sonarr_remote_url', ''),
                    request.form.get('bazarr_url', ''),
                    request.form.get('bazarr_api_key', ''),
                    request.form.get('tautulli_url', ''),
                    request.form.get('tautulli_api_key', ''),
                    request.form.get('jellyseer_url', ''),
                    request.form.get('jellyseer_api_key', ''),
                    request.form.get('ollama_url', ''),
                    request.form.get('ollama_model', ''),
                    request.form.get('openai_api_key', ''),
                    request.form.get('openai_model', ''),
                    request.form.get('pushover_key', ''),
                    request.form.get('pushover_token', ''),
                    request.form.get('plex_client_id', ''),
                    timezone
                )
            )
            db.commit()

            # Clear onboarding session data
            session.pop('onboarding_username', None)

            # Capture form values before starting background thread
            has_radarr = bool(request.form.get('radarr_url') and request.form.get('radarr_api_key'))
            has_sonarr = bool(request.form.get('sonarr_url') and request.form.get('sonarr_api_key'))
            has_tautulli = bool(request.form.get('tautulli_url') and request.form.get('tautulli_api_key'))

            # Automatically queue library imports in background
            import threading
            from ..utils import sync_radarr_library, sync_sonarr_library, sync_tautulli_watch_history

            def run_background_imports(radarr, sonarr, tautulli):
                """Run all initial library imports in sequence"""
                with current_app.app_context():
                    try:
                        # Import Radarr library
                        if radarr:
                            current_app.logger.info("Starting automatic Radarr import after onboarding")
                            sync_radarr_library()

                        # Import Sonarr library
                        if sonarr:
                            current_app.logger.info("Starting automatic Sonarr import after onboarding")
                            sync_sonarr_library()

                        # Import Tautulli history
                        if tautulli:
                            current_app.logger.info("Starting automatic Tautulli import after onboarding")
                            sync_tautulli_watch_history(full_import=False, max_records=1000)

                        current_app.logger.info("All automatic imports completed")
                    except Exception as e:
                        current_app.logger.error(f"Error during automatic imports: {e}", exc_info=True)

            # Start background thread for imports
            import_thread = threading.Thread(
                target=run_background_imports,
                args=(has_radarr, has_sonarr, has_tautulli),
                daemon=True
            )
            import_thread.start()

            flash('Onboarding complete! Your media libraries are being imported in the background. Check the Event Logs to monitor progress.', 'success')
            return redirect(url_for('main.login'))
        except Exception as e:
            db.rollback()
            flash(f'An error occurred during service configuration: {e}', 'danger')
            current_app.logger.error(f"Onboarding Step 2 error: {e}", exc_info=True)

    return render_template('onboarding_services.html', env_settings=env_settings)

@main_bp.route('/onboarding/test-service', methods=['POST'])
def onboarding_test_service():
    """
    Test service connections during onboarding (no login required).

    Expects JSON payload with 'service', 'url', and 'key' (API key).
    Returns JSON indicating success or failure.
    """
    from ..utils import (
        test_sonarr_connection_with_params,
        test_radarr_connection_with_params,
        test_bazarr_connection_with_params,
        test_ollama_connection_with_params,
        test_tautulli_connection_with_params,
        test_jellyseer_connection_with_params,
        test_pushover_notification_with_params
    )

    data = request.json
    service = data.get('service')
    url = data.get('url')
    api_key = data.get('key')  # JavaScript sends 'key', not 'api_key'

    current_app.logger.info(f'Onboarding test for {service} at {url}')

    success = False
    error_message = 'Invalid service specified.'

    try:
        if service == 'sonarr':
            success, error_message = test_sonarr_connection_with_params(url, api_key)
        elif service == 'radarr':
            success, error_message = test_radarr_connection_with_params(url, api_key)
        elif service == 'bazarr':
            success, error_message = test_bazarr_connection_with_params(url, api_key)
        elif service == 'ollama':
            success, error_message = test_ollama_connection_with_params(url)
        elif service == 'tautulli':
            success, error_message = test_tautulli_connection_with_params(url, api_key)
        elif service == 'jellyseer':
            success, error_message = test_jellyseer_connection_with_params(url, api_key)
        elif service == 'pushover':
            # For pushover, 'url' is user_key and 'key' is token
            success, error_message = test_pushover_notification_with_params(api_key, url)

        if success:
            return jsonify({'success': True, 'message': 'Connection successful!'})
        else:
            return jsonify({'success': False, 'message': error_message or 'Connection test failed'})
    except Exception as e:
        current_app.logger.error(f"Service test error for {service}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})

@main_bp.route('/search')
@login_required
def search():
    """
    Provides search results for the main user-facing search bar.

    This API endpoint is called by the JavaScript search functionality. It takes
    a query parameter 'q' and searches the `sonarr_shows` and `radarr_movies`
    tables for matching titles.

    Args:
        q (str): The search term, provided as a URL query parameter.

    Returns:
        flask.Response: A JSON response containing a list of search results,
                        including title, type, year, and a URL to the detail page.
    """
    query = request.args.get('q', '').lower()
    if not query:
        return jsonify([])

    db = database.get_db()
    
    # Search Sonarr
    sonarr_results = db.execute(
        "SELECT title, 'show' as type, tmdb_id, year, poster_url, fanart_url FROM sonarr_shows WHERE title LIKE ?", ('%' + query + '%',)
    ).fetchall()

    # Search Radarr
    radarr_results = db.execute(
        "SELECT title, 'movie' as type, tmdb_id, year, poster_url, fanart_url FROM radarr_movies WHERE title LIKE ?", ('%' + query + '%',)
    ).fetchall()

    results = []
    for row in sonarr_results + radarr_results:
        item = dict(row)
        if item.get('tmdb_id'):
            item['poster_url'] = url_for('main.image_proxy', type='poster', id=item['tmdb_id'])
            item['fanart_url'] = url_for('main.image_proxy', type='background', id=item['tmdb_id'])
        else:
            # Set to placeholder or None if no tmdb_id, so templates don't break
            item['poster_url'] = url_for('static', filename='logos/placeholder_poster.png')
            item['fanart_url'] = url_for('static', filename='logos/placeholder_background.png')
        results.append(item)
    
    # Sort results by title
    results.sort(key=lambda x: x['title'])
    
    return jsonify(results)

@main_bp.route('/movie/<int:tmdb_id>')
@login_required
def movie_detail(tmdb_id):
    """
    Displays the detail page for a specific movie.

    It fetches the movie's metadata from the `radarr_movies` table using the
    provided TMDB ID. It also retrieves related watch history for the logged-in
    user from the `plex_activity_log` table to show view count and last watched date.

    Args:
        tmdb_id (int): The The Movie Database (TMDB) ID for the movie.

    Returns:
        A rendered HTML template for the movie detail page, or a 404 error
        if the movie is not found in the database.
    """
    db = database.get_db()
    movie = db.execute('SELECT * FROM radarr_movies WHERE tmdb_id = ?', (tmdb_id,)).fetchone()
    if not movie:
        abort(404)
    movie_dict = dict(movie)
    if movie_dict.get('tmdb_id'):
        movie_dict['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=movie_dict['tmdb_id'])
        movie_dict['cached_fanart_url'] = url_for('main.image_proxy', type='background', id=movie_dict['tmdb_id'])
    else:
        movie_dict['cached_poster_url'] = url_for('static', filename='logos/placeholder_poster.png')
        movie_dict['cached_fanart_url'] = url_for('static', filename='logos/placeholder_background.png')
    return render_template('movie_detail.html', movie=movie_dict)

def _calculate_year_display(show_dict: dict) -> str:
    """Calculate year display string (2016-2019 or 2016-Present)"""
    premiered = show_dict.get('premiered')
    end_date = show_dict.get('end_date')

    if premiered:
        start_year = premiered[:4]
        if end_date:
            end_year = end_date[:4]
            return f"{start_year}-{end_year}" if start_year != end_year else start_year
        return f"{start_year}-Present"

    return str(show_dict['year']) if show_dict.get('year') else "Unknown"

@main_bp.route('/show/<int:tmdb_id>')
@login_required
def show_detail(tmdb_id):
    """
    Displays the detail page for a specific TV show.

    This function gathers comprehensive information for a show, including:
    - Basic metadata from the `sonarr_shows` table.
    - A list of all seasons and episodes from the `sonarr_seasons` and
      `sonarr_episodes` tables.
    - The user's watch history for the show from `plex_activity_log`.
    - A "featured episode" card, which highlights either the most recently
      watched episode or the next unwatched episode.

    Args:
        tmdb_id (int): The The Movie Database (TMDB) ID for the show.

    Returns:
        A rendered HTML template for the show detail page, or a 404 error
        if the show is not found.
    """
    db = database.get_db()
    s_username = session.get('username')
    show_dict = None

    show_row = db.execute('SELECT * FROM sonarr_shows WHERE tmdb_id = ?', (tmdb_id,)).fetchone()
    if not show_row:
        current_app.logger.warning(f"Show with TMDB ID {tmdb_id} not found in sonarr_shows.")
        abort(404)
    show_dict = dict(show_row)
    show_dict['year_display'] = _calculate_year_display(show_dict)

    # Parse genres from JSON
    genres_list = []
    if show_dict.get('genres'):
        try:
            genres_list = json.loads(show_dict['genres'])
        except json.JSONDecodeError:
            pass
    show_dict['genres_list'] = genres_list

    # Fetch cast information
    cast_members = []
    if show_dict.get('tvmaze_id'):
        cast_rows = db.execute("""
            SELECT * FROM show_cast
            WHERE show_tvmaze_id = ?
            ORDER BY cast_order ASC
            LIMIT 20
        """, (show_dict['tvmaze_id'],)).fetchall()
        cast_members = [dict(row) for row in cast_rows]

    if show_dict.get('tmdb_id'):
        show_dict['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=show_dict['tmdb_id'])
        show_dict['cached_fanart_url'] = url_for('main.image_proxy', type='background', id=show_dict['tmdb_id'])
    else:
        show_dict['cached_poster_url'] = url_for('static', filename='logos/placeholder_poster.png')
        show_dict['cached_fanart_url'] = url_for('static', filename='logos/placeholder_background.png')
    show_db_id = show_dict['id']

    seasons_rows = db.execute(
        'SELECT * FROM sonarr_seasons WHERE show_id = ? ORDER BY season_number DESC', (show_db_id,)
    ).fetchall()

    seasons_with_episodes = []
    all_show_episodes_for_next_aired_check = []

    for season_row in seasons_rows:
        if season_row['season_number'] == 0:
            # Skip specials/Season 0 from main listing
            continue
        season_dict = dict(season_row)
        season_db_id = season_dict['id']

        episodes_rows = db.execute(
            'SELECT * FROM sonarr_episodes WHERE season_id = ? ORDER BY episode_number DESC', (season_db_id,)
        ).fetchall()

        current_season_episodes = [dict(ep_row) for ep_row in episodes_rows]
        season_dict['episodes'] = current_season_episodes
        seasons_with_episodes.append(season_dict)
        all_show_episodes_for_next_aired_check.extend(current_season_episodes)

    next_aired_episode_info = None
    if show_dict.get('status', '').lower() == 'continuing' or show_dict.get('status', '').lower() == 'upcoming': # Only look for next_aired if show is active
        try:
            now_utc = datetime.datetime.now(timezone.utc)
            relevant_episodes = [ep for ep in all_show_episodes_for_next_aired_check if ep.get('air_date_utc')]
            relevant_episodes.sort(key=lambda ep: ep['air_date_utc'])

            for episode in relevant_episodes:
                air_date_str = episode['air_date_utc']
                try:
                    air_date = datetime.datetime.fromisoformat(air_date_str.replace('Z', '+00:00'))
                    if air_date > now_utc:
                        season_number_for_next_aired = None
                        # Find season number for this episode
                        for s_dict in seasons_with_episodes:
                            if s_dict['id'] == episode['season_id']:
                                season_number_for_next_aired = s_dict['season_number']
                                break

                        if season_number_for_next_aired is not None: # Ensure season number was found
                            next_aired_episode_info = {
                                'title': episode['title'],
                                'season_number': season_number_for_next_aired,
                                'episode_number': episode['episode_number'],
                                'air_date_utc': air_date_str,
                                'season_episode_str': f"S{str(season_number_for_next_aired).zfill(2)}E{str(episode['episode_number']).zfill(2)}"
                            }
                            break # Found the earliest next aired episode
                except (ValueError, TypeError) as e_parse:
                    current_app.logger.debug(f"Could not parse air_date_utc '{air_date_str}' for episode ID {episode.get('id')}: {e_parse}")
                    continue
        except Exception as e_next_aired:
            current_app.logger.error(f"Error determining next aired episode for show TMDB ID {tmdb_id}: {e_next_aired}")

    currently_watched_episode_info = None
    last_watched_episode_info = None
    plex_username = session.get('username')
    show_tvdb_id = show_dict.get('tvdb_id') # This is from sonarr_shows.tvdb_id

    if plex_username and show_tvdb_id:
        try:
            # grandparent_rating_key in plex_activity_log is Plex's internal key, often related to tvdb_id but might be string.
            # Convert show_tvdb_id to string for safer comparison if Plex stores it as string.
            plex_activity_row = db.execute(
                """
                SELECT title, season_episode, view_offset_ms, duration_ms, event_timestamp
                FROM plex_activity_log
                WHERE plex_username = ?
                  AND grandparent_rating_key = ?
                  AND media_type = 'episode'
                  AND event_type IN ('media.play', 'media.pause', 'media.resume')
                ORDER BY event_timestamp DESC
                LIMIT 1
                """,
                (plex_username, str(show_tvdb_id))
            ).fetchone()

            if plex_activity_row:
                currently_watched_episode_info = dict(plex_activity_row)
                if currently_watched_episode_info.get('view_offset_ms') is not None and \
                   currently_watched_episode_info.get('duration_ms') is not None and \
                   currently_watched_episode_info['duration_ms'] > 0:
                    progress = (currently_watched_episode_info['view_offset_ms'] / currently_watched_episode_info['duration_ms']) * 100
                    currently_watched_episode_info['progress_percent'] = round(progress)
        except sqlite3.Error as e_sql: # More specific for DB errors
            current_app.logger.error(f"SQLite error fetching currently watched episode for show TVDB ID {show_tvdb_id} and user {plex_username}: {e_sql}")
        except Exception as e_watched:
            current_app.logger.error(f"Generic error fetching currently watched episode for show TVDB ID {show_tvdb_id} and user {plex_username}: {e_watched}")

        if not currently_watched_episode_info:
            last_row = db.execute(
                """
                SELECT title, season_episode, event_timestamp
                FROM plex_activity_log
                WHERE plex_username = ?
                  AND grandparent_rating_key = ?
                  AND media_type = 'episode'
                  AND event_type IN ('media.stop', 'media.scrobble')
                ORDER BY event_timestamp DESC
                LIMIT 1
                """,
                (plex_username, str(show_tvdb_id))
            ).fetchone()
            if last_row:
                last_watched_episode_info = dict(last_row)

    next_up_episode = get_next_up_episode(
        currently_watched_episode_info,
        last_watched_episode_info,
        show_dict,
        seasons_with_episodes
    )

    # Get Jellyseer URL for request button
    settings = db.execute('SELECT jellyseer_url FROM settings LIMIT 1').fetchone()
    jellyseer_url = settings['jellyseer_url'] if settings and settings['jellyseer_url'] else None

    return render_template('show_detail.html',
                           show=show_dict,
                           seasons_with_episodes=seasons_with_episodes,
                           next_aired_episode_info=next_aired_episode_info,
                           next_up_episode=next_up_episode,
                           cast_members=cast_members,
                           jellyseer_url=jellyseer_url
                           )

def get_next_up_episode(currently_watched, last_watched, show_info, seasons_with_episodes, user_prefs=None):
    """
    Determines the "Next Up" episode for a show's detail page with enhanced logic.
    """
    if user_prefs is None:
        user_prefs = {'skip_specials': True, 'order': 'default'}

    db = database.get_db()
    source_info = None
    is_currently_watching = False
    is_next_unwatched = False

    if currently_watched:
        source_info = currently_watched
        is_currently_watching = True
    elif last_watched:
        last_season_episode_str = last_watched.get('season_episode')
        match = re.match(r'S(\d+)E(\d+)', last_season_episode_str) if last_season_episode_str else None
        if match:
            last_season_num = int(match.group(1))
            last_episode_num = int(match.group(2))

            all_episodes = []
            for season in sorted(seasons_with_episodes, key=lambda s: s['season_number']):
                if user_prefs['skip_specials'] and season['season_number'] == 0:
                    continue
                # Sort episodes within the season
                sorted_episodes = sorted(season['episodes'], key=lambda e: e['episode_number'])
                for episode in sorted_episodes:
                    all_episodes.append({
                        'season_number': season['season_number'],
                        **episode
                    })

            last_watched_index = -1
            for i, ep in enumerate(all_episodes):
                if ep['season_number'] == last_season_num and ep['episode_number'] == last_episode_num:
                    last_watched_index = i
                    break

            if last_watched_index != -1:
                # Search for the next available episode, considering multi-part episodes
                for i in range(last_watched_index + 1, len(all_episodes)):
                    next_ep = all_episodes[i]
                    if next_ep.get('has_file'):
                        # Check for multi-part episode logic (e.g., if the title is the same as the previous)
                        if i > 0 and all_episodes[i-1]['title'] == next_ep['title']:
                            # This might be the second part of a multi-part episode, let's see if we should skip it
                            # For now, we assume the user wants to see the next file regardless.
                            # More complex logic could be added here.
                            pass

                        source_info = {
                            'title': next_ep['title'],
                            'season_episode': f"S{str(next_ep['season_number']).zfill(2)}E{str(next_ep['episode_number']).zfill(2)}",
                            'event_timestamp': last_watched.get('event_timestamp')
                        }
                        is_next_unwatched = True
                        break

        if not source_info:
            source_info = last_watched

    if not source_info:
        return None

    season_episode_str = source_info.get('season_episode')
    match = re.match(r'S(\d+)E(\d+)', season_episode_str) if season_episode_str else None
    if not match:
        return None
    season_number, episode_number = map(int, match.groups())

    episode_detail_url = url_for('main.episode_detail',
                                 tmdb_id=show_info['tmdb_id'],
                                 season_number=season_number,
                                 episode_number=episode_number)

    raw_timestamp = source_info.get('event_timestamp')
    formatted_timestamp = "Unknown"
    if raw_timestamp:
        try:
            dt_obj = datetime.datetime.fromisoformat(str(raw_timestamp).replace('Z', '+00:00'))
            formatted_timestamp = dt_obj.strftime("%b %d, %Y at %I:%M %p")
        except (ValueError, TypeError):
            formatted_timestamp = str(raw_timestamp)

    return {
        'title': source_info.get('title'),
        'season_episode_str': season_episode_str,
        'season_number': season_number,
        'episode_number': episode_number,
        'poster_url': show_info.get('cached_poster_url'),
        'event_timestamp': raw_timestamp,
        'formatted_timestamp': formatted_timestamp,
        'progress_percent': source_info.get('progress_percent') if is_currently_watching else None,
        'episode_detail_url': episode_detail_url,
        'is_currently_watching': is_currently_watching,
        'is_next_unwatched': is_next_unwatched,
        'overview': source_info.get('overview', '')
    }

@main_bp.route('/show/<int:tmdb_id>/season/<int:season_number>/episode/<int:episode_number>')
@login_required
def episode_detail(tmdb_id, season_number, episode_number):
    """
    Displays the detail page for a single TV episode.

    It fetches metadata for the episode, its parent season, and its parent show
    from the database to provide a comprehensive view. This includes details
    like air date, summary, and a link back to the main show page.

    Args:
        tmdb_id (int): The TMDB ID of the parent show.
        season_number (int): The season number of the episode.
        episode_number (int): The episode number.

    Returns:
        A rendered HTML template for the episode detail page, or a 404 error
        if the show or episode cannot be found.
    """
    db = database.get_db()

    # Fetch show, season, and episode details in one go if possible
    show_row = db.execute('SELECT id, title, tmdb_id, tvdb_id, poster_url, fanart_url FROM sonarr_shows WHERE tmdb_id = ?', (tmdb_id,)).fetchone()
    if not show_row:
        abort(404)
    show_dict = dict(show_row)
    # Use consistent names for cached URLs as expected by the new template.
    if show_dict.get('tmdb_id'):
        show_dict['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=show_dict['tmdb_id'])
        show_dict['cached_fanart_url'] = url_for('main.image_proxy', type='background', id=show_dict['tmdb_id']) # Optional for episode page bg
    else:
        show_dict['cached_poster_url'] = url_for('static', filename='logos/placeholder_poster.png')
        show_dict['cached_fanart_url'] = url_for('static', filename='logos/placeholder_background.png')

    show_id = show_dict['id']
    show_tvdb_id = show_dict.get('tvdb_id')
    show_tmdb_id = show_dict.get('tmdb_id')
    show_title = show_dict.get('title')
    season_row = db.execute('SELECT id FROM sonarr_seasons WHERE show_id=? AND season_number=?', (show_id, season_number)).fetchone()
    if not season_row:
        abort(404)

    # Fetch all columns for the episode
    episode_row = db.execute('SELECT * FROM sonarr_episodes WHERE season_id=? AND episode_number=?', (season_row['id'], episode_number)).fetchone()
    if not episode_row:
        abort(404)

    episode_dict = dict(episode_row)

    # Try all possible IDs for cast lookup
    episode_characters = []
    # 1. Sonarr TVDB ID
    if show_tvdb_id:
        episode_characters = db.execute(
            'SELECT * FROM episode_characters WHERE show_tvdb_id = ? AND season_number = ? AND episode_number = ? ORDER BY id',
            (show_tvdb_id, season_number, episode_number)
        ).fetchall()
        episode_characters = [dict(row) for row in episode_characters]
    # 2. Sonarr TMDB ID
    if not episode_characters and show_tmdb_id:
        episode_characters = db.execute(
            'SELECT * FROM episode_characters WHERE show_tmdb_id = ? AND season_number = ? AND episode_number = ? ORDER BY id',
            (show_tmdb_id, season_number, episode_number)
        ).fetchall()
        episode_characters = [dict(row) for row in episode_characters]
    # 3. Try Plex webhook IDs from most recent plex_activity_log for this episode
    if not episode_characters:
        # Try to find the most recent plex_activity_log for this show/season/episode
        # We'll match by show title and season/episode string (season_episode)
        season_episode_str = f"S{str(season_number).zfill(2)}E{str(episode_number).zfill(2)}"
        plex_row = db.execute(
            'SELECT raw_payload FROM plex_activity_log WHERE show_title = ? AND season_episode = ? ORDER BY event_timestamp DESC LIMIT 1',
            (show_title, season_episode_str)
        ).fetchone()
        plex_tmdb_id = None
        plex_tvdb_id = None
        if plex_row:
            import json
            try:
                payload = json.loads(plex_row['raw_payload'])
                guids = payload.get('Metadata', {}).get('Guid', [])
                for guid_item in guids:
                    guid_str = guid_item.get('id', '')
                    if guid_str.startswith('tmdb://'):
                        try:
                            plex_tmdb_id = int(guid_str.split('//')[1])
                        except Exception:
                            plex_tmdb_id = None
                    if guid_str.startswith('tvdb://'):
                        try:
                            plex_tvdb_id = int(guid_str.split('//')[1])
                        except Exception:
                            plex_tvdb_id = None
            except Exception:
                pass
        # 3a. Plex TVDB ID
        if plex_tvdb_id:
            episode_characters = db.execute(
                'SELECT * FROM episode_characters WHERE show_tvdb_id = ? AND season_number = ? AND episode_number = ? ORDER BY id',
                (plex_tvdb_id, season_number, episode_number)
            ).fetchall()
            episode_characters = [dict(row) for row in episode_characters]
        # 3b. Plex TMDB ID
        if not episode_characters and plex_tmdb_id:
            episode_characters = db.execute(
                'SELECT * FROM episode_characters WHERE show_tmdb_id = ? AND season_number = ? AND episode_number = ? ORDER BY id',
                (plex_tmdb_id, season_number, episode_number)
            ).fetchall()
            episode_characters = [dict(row) for row in episode_characters]

    # Format air date
    if episode_dict.get('air_date_utc'):
        try:
            # Ensure Z is handled for UTC parsing if present
            air_date_str = episode_dict['air_date_utc']
            if 'Z' in air_date_str.upper() and not '+' in air_date_str and not '-' in air_date_str[10:]: # Simple check for Zulu time
                 air_date_str = air_date_str.upper().replace('Z', '+00:00')

            air_dt = datetime.datetime.fromisoformat(air_date_str)
            episode_dict['formatted_air_date'] = air_dt.strftime('%B %d, %Y')
        except ValueError as e:
            current_app.logger.warning(f"Could not parse air_date_utc '{episode_dict['air_date_utc']}' for episode: {e}")
            episode_dict['formatted_air_date'] = episode_dict['air_date_utc'] # Fallback
    else:
        episode_dict['formatted_air_date'] = 'N/A'

    # Ensure 'is_available' based on 'has_file'
    episode_dict['is_available'] = episode_dict.get('has_file', False)

    # Add runtime if available (example field name, adjust if different in your schema)
    # episode_dict['runtime_minutes'] = episode_dict.get('runtime', None)


    # Debug episode_characters before rendering
    current_app.logger.info(f"[DEBUG] Episode {tmdb_id} S{season_number}E{episode_number} found {len(episode_characters)} characters:")
    for char in episode_characters:
        current_app.logger.info(f"[DEBUG] Character: ID={char.get('id')}, Name={char.get('character_name')}, Actor={char.get('actor_name')}")
    
    return render_template('episode_detail.html',
                           show=show_dict,
                           episode=episode_dict,
                           season_number=season_number,
                           episode_characters=episode_characters)

@main_bp.route('/image_proxy/<string:type>/<int:id>')
@login_required
def image_proxy(type, id):
    """
    Securely proxies and caches images from external services (Sonarr/Radarr).

    This endpoint is responsible for fetching images (posters or backgrounds),
    caching them locally, and serving them to the client. It prevents mixed-content
    warnings and improves performance by reducing redundant external requests.

    - It first checks if the requested image already exists in the local cache.
    - If found, it serves the cached file directly.
    - If not found, it queries the database for the original image URL from
      Sonarr or Radarr based on the provided TMDB ID.
    - It then fetches the image from the external URL, saves it to the appropriate
      local cache directory (`/static/poster` or `/static/background`), and then
      serves the image.

    Args:
        type (str): The type of image to fetch ('poster' or 'background').
        id (int): The The Movie Database (TMDB) ID for the movie or show.

    Returns:
        flask.Response: The image data with the correct content type, a placeholder
                        image if the original is not found, or a 404 error for
                        invalid requests.
    """
    # Validate type
    if type not in ['poster', 'background']:
        abort(404)

    # Define cache path
    cache_folder = os.path.join(current_app.static_folder, type)
    # Sanitize ID to prevent directory traversal
    safe_filename = f"{str(id)}.jpg"
    cached_image_path = os.path.join(cache_folder, safe_filename)

    # Create directory if it doesn't exist
    os.makedirs(cache_folder, exist_ok=True)

    # 1. Check if image is already cached
    if os.path.exists(cached_image_path):
        return current_app.send_static_file(f'{type}/{safe_filename}')

    # 2. If not cached, find the image URL from the database
    db = database.get_db()
    external_url = None
    source = None # To determine which service's URL to use for relative paths

    # Check Radarr (movies) first
    movie_record = db.execute(f"SELECT {'poster_url' if type == 'poster' else 'fanart_url'} as url FROM radarr_movies WHERE tmdb_id = ?", (id,)).fetchone()
    if movie_record and movie_record['url']:
        external_url = movie_record['url']
        source = 'radarr'
    else:
        # Check Sonarr (shows)
        show_record = db.execute(f"SELECT {'poster_url' if type == 'poster' else 'fanart_url'} as url FROM sonarr_shows WHERE tmdb_id = ?", (id,)).fetchone()
        if show_record and show_record['url']:
            external_url = show_record['url']
            source = 'sonarr'

    if not external_url:
        # Return a placeholder if no URL is found in the database
        placeholder_path = f'logos/placeholder_{type}.png' if os.path.exists(os.path.join(current_app.static_folder, f'logos/placeholder_{type}.png')) else 'logos/placeholder_poster.png'
        return current_app.send_static_file(placeholder_path)


    # 3. Fetch the image from the external URL
    try:
        # Handle relative URLs from Sonarr/Radarr
        if external_url.startswith('/'):
            service_url = database.get_setting(f'{source}_url')
            if service_url:
                external_url = f"{service_url.rstrip('/')}{external_url}"
            else:
                raise ValueError(f"{source} URL not configured, cannot resolve relative image path.")

        # Use a session for potential keep-alive and other benefits
        with requests.Session() as s:
            # Add API key if the source requires it for media assets
            api_key = database.get_setting(f'{source}_api_key')
            if api_key:
                s.headers.update({'X-Api-Key': api_key})
            
            resp = s.get(external_url, stream=True, timeout=10)
            resp.raise_for_status() # Raise an exception for bad status codes

        # 4. Save the image to the cache
        with open(cached_image_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        
        current_app.logger.info(f"Cached image: {cached_image_path}")

        # 5. Serve the newly cached image
        return current_app.send_static_file(f'{type}/{safe_filename}')

    except (requests.RequestException, ValueError, IOError) as e:
        current_app.logger.error(f"Failed to fetch or cache image for {type}/{id} from {external_url}. Error: {e}")
        # If fetching fails, serve the placeholder
        placeholder_path = f'logos/placeholder_{type}.png' if os.path.exists(os.path.join(current_app.static_folder, f'logos/placeholder_{type}.png')) else 'logos/placeholder_poster.png'
        return current_app.send_static_file(placeholder_path)

@main_bp.route('/image_proxy/cast/<int:person_id>')
@login_required
def cast_image_proxy(person_id):
    """Proxy and cache cast member photos from TVMaze"""
    cache_folder = os.path.join(current_app.static_folder, 'cast')
    safe_filename = f"{str(person_id)}.jpg"
    cached_image_path = os.path.join(cache_folder, safe_filename)
    os.makedirs(cache_folder, exist_ok=True)

    if os.path.exists(cached_image_path):
        return current_app.send_static_file(f'cast/{safe_filename}')

    db = database.get_db()
    cast_record = db.execute("""
        SELECT person_image_url FROM show_cast
        WHERE person_id = ? LIMIT 1
    """, (person_id,)).fetchone()

    if not cast_record or not cast_record['person_image_url']:
        return current_app.send_static_file('logos/placeholder_poster.png')

    try:
        with requests.Session() as s:
            resp = s.get(cast_record['person_image_url'], stream=True, timeout=10)
            resp.raise_for_status()
        with open(cached_image_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return current_app.send_static_file(f'cast/{safe_filename}')
    except Exception as e:
        current_app.logger.error(f"Failed to fetch cast photo {person_id}: {e}")
        return current_app.send_static_file('logos/placeholder_poster.png')

@main_bp.route('/character/<int:show_id>/<int:season_number>/<int:episode_number>/<int:character_id>')
def character_detail(show_id, season_number, episode_number, character_id):
    """
    Display character detail page showing actor information and other appearances.
    """
    db = database.get_db()

    # Get character information
    character = db.execute('''
        SELECT ec.*
        FROM episode_characters ec
        WHERE ec.id = ?
        LIMIT 1
    ''', (character_id,)).fetchone()

    if not character:
        flash('Character not found.', 'danger')
        return redirect(url_for('main.episode_detail', tmdb_id=show_id, season_number=season_number, episode_number=episode_number))

    # Get show information
    show = db.execute('SELECT title, overview, year FROM sonarr_shows WHERE tmdb_id = ?', (show_id,)).fetchone()
    show_title = show['title'] if show else "Unknown Show"

    # Get all episodes this character appears in for this show
    character_episodes = db.execute('''
        SELECT DISTINCT ec.season_number, ec.episode_number, se.title, se.air_date_utc
        FROM episode_characters ec
        LEFT JOIN sonarr_episodes se ON ec.episode_number = se.episode_number
        LEFT JOIN sonarr_seasons ss ON se.season_id = ss.id AND ec.season_number = ss.season_number
        LEFT JOIN sonarr_shows sshow ON ss.show_id = sshow.id
        WHERE ec.show_tmdb_id = ?
        AND ec.character_name = ?
        AND sshow.tmdb_id = ?
        ORDER BY ec.season_number, ec.episode_number
    ''', (show_id, character['character_name'], show_id)).fetchall()

    # Get other shows this actor appears in (same actor name)
    other_shows = []
    if character['actor_name']:
        other_shows = db.execute('''
            SELECT DISTINCT ss.tmdb_id, ss.title, ec.character_name, COUNT(DISTINCT ec.episode_number) as episode_count
            FROM episode_characters ec
            JOIN sonarr_shows ss ON ec.show_tmdb_id = ss.tmdb_id
            WHERE ec.actor_name = ?
            AND ss.tmdb_id != ?
            GROUP BY ss.tmdb_id, ss.title, ec.character_name
            ORDER BY episode_count DESC
            LIMIT 10
        ''', (character['actor_name'], show_id)).fetchall()

    return render_template('character_detail.html',
                           show_id=show_id,
                           season_number=season_number,
                           episode_number=episode_number,
                           character_id=character_id,
                           character=character,
                           show_title=show_title,
                           character_episodes=character_episodes,
                           other_shows=other_shows)

@main_bp.route('/report_issue/<string:media_type>/<int:media_id>', methods=['GET', 'POST'])
@login_required
def report_issue(media_type, media_id):
    db = database.get_db()
    if request.method == 'POST':
        issue_types = request.form.getlist('issue_type')
        comment = request.form.get('comment', '')
        show_id = request.form.get('show_id')
        title = request.form.get('title', '')
        cursor = db.execute(
            'INSERT INTO issue_reports (user_id, media_type, media_id, show_id, title, issue_type, comment) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (session.get('user_id'), media_type, media_id, show_id, title, ','.join(issue_types), comment)
        )
        report_id = cursor.lastrowid
        db.commit()

        # NOTE: Admin notifications disabled - admins can view reports on dedicated admin page
        # Issue reports no longer create in-app notifications to avoid clutter
        # Pushover notifications (below) still sent for immediate awareness

        # Send Pushover notification to admins
        try:
            from ..utils import send_pushover_notification

            # Build notification message
            push_title = f"Issue Report: {title}"
            push_message = f"User reported: {', '.join(issue_types)}"
            if comment:
                push_message += f"\n\nComment: {comment[:200]}"

            # Send with Sonarr/Radarr link if available
            url_title = "View in Sonarr" if media_type == 'episode' else "View in Radarr" if service_link else None
            success, error = send_pushover_notification(
                title=push_title,
                message=push_message,
                url=service_link,
                url_title=url_title,
                priority=1  # Requires confirmation from admin (high priority)
            )

            if success:
                current_app.logger.info(f"Pushover notification sent for issue report {report_id}")
            elif error and error != "Pushover not configured":
                current_app.logger.error(f"Failed to send Pushover for issue {report_id}: {error}")

        except Exception as e:
            current_app.logger.error(f"Error sending Pushover notification: {e}", exc_info=True)
            # Don't fail the request if Pushover fails - notification is optional

        flash('Issue reported. Thank you!', 'success')
        return redirect(url_for('main.home'))

    issues = [
        'Wrong language', 'No audio', 'Audio out of sync', 'Bad video quality',
        'Wrong episode playing', 'Missing subtitles', 'Other'
    ]
    show_id = request.args.get('show_id', '')
    title = request.args.get('title', '')
    return render_template('report_issue.html', media_type=media_type, media_id=media_id, show_id=show_id, title=title, issues=issues)

# ============================================================================
# USER PROFILE ROUTES
# ============================================================================

@main_bp.route('/profile')
@main_bp.route('/profile/history')
def profile_history():
    """Redirect to homepage (backwards compatibility)"""
    return redirect(url_for('main.home'))


@main_bp.route('/profile/favorites')
@login_required
def profile_favorites():
    """Display user's favorite shows"""
    user_id = session.get('user_id')
    if not user_id:
        flash('Please log in to view your profile.', 'warning')
        return redirect(url_for('main.login'))
    
    db = database.get_db()
    
    # Get user info
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

    # Convert user row to dict so we can add the plex_member_since field
    user_dict = dict(user)
    # Use the plex_joined_at from Plex API if available, otherwise fall back to created_at
    user_dict['plex_member_since'] = user_dict.get('plex_joined_at') or user_dict.get('created_at')

    # Get favorited shows
    favorites = db.execute("""
        SELECT 
            uf.id as favorite_id,
            uf.added_at,
            s.id as show_db_id,
            s.tmdb_id,
            s.title,
            s.year,
            s.status,
            s.poster_url,
            s.overview
        FROM user_favorites uf
        JOIN sonarr_shows s ON s.id = uf.show_id
        WHERE uf.user_id = ? AND uf.is_dropped = 0
        ORDER BY uf.added_at DESC
    """, (user_id,)).fetchall()
    
    # Enrich favorites with next episode info
    enriched_favorites = []
    for fav in favorites:
        fav_dict = dict(fav)
        fav_dict['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=fav_dict['tmdb_id'])
        fav_dict['detail_url'] = url_for('main.show_detail', tmdb_id=fav_dict['tmdb_id'])
        
        # Format added date
        if fav_dict.get('added_at'):
            try:
                dt = datetime.datetime.fromisoformat(str(fav_dict['added_at']).replace('Z', '+00:00'))
                fav_dict['formatted_added_date'] = dt.strftime('%B %d, %Y')
            except:
                fav_dict['formatted_added_date'] = 'Unknown'
        
        enriched_favorites.append(fav_dict)

    # Get profile statistics using helper function
    stats = _get_profile_stats(db, user_id)

    return render_template('profile_favorites.html',
                         user=user_dict,
                         favorites=enriched_favorites,
                         **stats,
                         active_tab='favorites')


@main_bp.route('/profile/notifications')
@login_required
def profile_notifications():
    """Display user's notifications"""
    user_id = session.get('user_id')
    if not user_id:
        flash('Please log in to view your profile.', 'warning')
        return redirect(url_for('main.login'))

    db = database.get_db()

    # Get user info
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

    # Convert user row to dict so we can add the plex_member_since field
    user_dict = dict(user)
    # Use the plex_joined_at from Plex API if available, otherwise fall back to created_at
    user_dict['plex_member_since'] = user_dict.get('plex_joined_at') or user_dict.get('created_at')

    # Get notifications (recent 50)
    notifications = db.execute("""
        SELECT
            n.id, n.user_id, n.show_id, n.notification_type, n.title, n.message,
            n.episode_id, n.season_number, n.episode_number, n.is_read, n.created_at, n.read_at,
            n.issue_report_id, n.service_url,
            s.tmdb_id as show_tmdb_id, s.title as show_title
        FROM user_notifications n
        LEFT JOIN sonarr_shows s ON n.show_id = s.id
        WHERE n.user_id = ?
        ORDER BY n.created_at DESC
        LIMIT 50
    """, (user_id,)).fetchall()

    # Get profile statistics using helper function
    stats = _get_profile_stats(db, user_id)

    return render_template('profile_notifications.html',
                         user=user_dict,
                         notifications=notifications,
                         **stats,
                         active_tab='notifications')


@main_bp.route('/api/profile/favorite/<int:show_id>', methods=['POST', 'DELETE'])
@login_required
def toggle_favorite(show_id):
    """Add or remove a show from favorites"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    db = database.get_db()
    
    # Verify show exists
    show = db.execute('SELECT id FROM sonarr_shows WHERE id = ?', (show_id,)).fetchone()
    if not show:
        return jsonify({'success': False, 'error': 'Show not found'}), 404
    
    if request.method == 'POST':
        # Add to favorites
        try:
            db.execute(
                'INSERT OR IGNORE INTO user_favorites (user_id, show_id) VALUES (?, ?)',
                (user_id, show_id)
            )
            db.commit()
            return jsonify({'success': True, 'action': 'added'})
        except Exception as e:
            current_app.logger.error(f"Error adding favorite: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    elif request.method == 'DELETE':
        # Remove from favorites
        try:
            db.execute(
                'DELETE FROM user_favorites WHERE user_id = ? AND show_id = ?',
                (user_id, show_id)
            )
            db.commit()
            return jsonify({'success': True, 'action': 'removed'})
        except Exception as e:
            current_app.logger.error(f"Error removing favorite: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

@main_bp.route('/api/profile/favorite/<int:show_id>', methods=['GET'])
@login_required
def check_favorite(show_id):
    """Check if a show is favorited"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    db = database.get_db()
    
    favorite = db.execute(
        'SELECT id FROM user_favorites WHERE user_id = ? AND show_id = ? AND is_dropped = 0',
        (user_id, show_id)
    ).fetchone()

    return jsonify({
        'success': True,
        'is_favorite': favorite is not None
    })


@main_bp.route('/api/profile/notification/<int:notification_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    """Mark a notification as read"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = database.get_db()

    # Verify the notification belongs to this user
    notification = db.execute(
        'SELECT user_id FROM user_notifications WHERE id = ?',
        (notification_id,)
    ).fetchone()

    if not notification:
        return jsonify({'success': False, 'error': 'Notification not found'}), 404

    if notification['user_id'] != user_id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    # Mark as read
    db.execute(
        'UPDATE user_notifications SET is_read = 1, read_at = CURRENT_TIMESTAMP WHERE id = ?',
        (notification_id,)
    )
    db.commit()

    return jsonify({'success': True})


@main_bp.route('/api/profile/notifications/read-all', methods=['POST'])
@login_required
def mark_all_notifications_read():
    """Mark all notifications as read for the current user"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = database.get_db()

    # Mark all unread notifications as read
    db.execute(
        'UPDATE user_notifications SET is_read = 1, read_at = CURRENT_TIMESTAMP WHERE user_id = ? AND is_read = 0',
        (user_id,)
    )
    db.commit()

    return jsonify({'success': True})


@main_bp.route('/api/profile/notification/<int:notification_id>/resolve', methods=['POST'])
@login_required
def resolve_notification_issue(notification_id):
    """Resolve an issue from a notification and notify the original reporter"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = database.get_db()

    # Verify the notification belongs to this user and get issue_report_id
    notification = db.execute(
        'SELECT user_id, issue_report_id FROM user_notifications WHERE id = ?',
        (notification_id,)
    ).fetchone()

    if not notification:
        return jsonify({'success': False, 'error': 'Notification not found'}), 404

    if notification['user_id'] != user_id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    if not notification['issue_report_id']:
        return jsonify({'success': False, 'error': 'No associated issue report'}), 400

    # Get issue report details
    report = db.execute(
        'SELECT user_id, title, show_id, issue_type FROM issue_reports WHERE id = ?',
        (notification['issue_report_id'],)
    ).fetchone()

    if not report:
        return jsonify({'success': False, 'error': 'Issue report not found'}), 404

    # Get resolution notes from request
    data = request.get_json() or {}
    notes = data.get('resolution_notes', '')

    # Resolve the issue report
    db.execute(
        "UPDATE issue_reports SET status='resolved', resolved_by_admin_id=?, resolved_at=CURRENT_TIMESTAMP, resolution_notes=? WHERE id=?",
        (user_id, notes, notification['issue_report_id'])
    )

    # Mark the admin notification as read
    db.execute(
        'UPDATE user_notifications SET is_read = 1, read_at = CURRENT_TIMESTAMP WHERE id = ?',
        (notification_id,)
    )

    db.commit()

    # Create notification for the user who reported
    try:
        import re

        # Parse episode info from title
        season_num = None
        episode_num = None
        if ' - S' in report['title']:
            match = re.search(r'S(\d+)E(\d+)', report['title'])
            if match:
                season_num = int(match.group(1))
                episode_num = int(match.group(2))

        notification_title = f"Issue Resolved: {report['title']}"
        notification_message = f"Your reported issue ({report['issue_type']}) has been resolved."
        if notes:
            notification_message += f" Resolution: {notes}"

        db.execute('''
            INSERT INTO user_notifications
            (user_id, show_id, notification_type, title, message, season_number, episode_number)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            report['user_id'],
            report['show_id'],
            'issue_resolved',
            notification_title,
            notification_message,
            season_num,
            episode_num
        ))

        db.commit()
        current_app.logger.info(f"Created resolution notification for user {report['user_id']}")
    except Exception as e:
        current_app.logger.error(f"Error creating resolution notification: {e}", exc_info=True)

    return jsonify({'success': True})


# ============================================================================
# Watch Statistics Helper Functions
# ============================================================================

def _calculate_watch_statistics(user_id, start_date, end_date):
    """
    Calculate watch statistics from plex_activity_log for a date range.

    Args:
        user_id: User ID
        start_date: Start date (datetime.date)
        end_date: End date (datetime.date)

    Returns:
        dict: Statistics for each date in the range
    """
    db = database.get_db()

    # Get user's plex username
    user = db.execute('SELECT plex_username FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user or not user['plex_username']:
        return {}

    plex_username = user['plex_username']

    # Query activity log for the date range
    stats_by_date = {}
    current_date = start_date

    while current_date <= end_date:
        date_start = datetime.datetime.combine(current_date, datetime.time.min)
        date_end = datetime.datetime.combine(current_date, datetime.time.max)

        # Get all watch events for this date
        events = db.execute('''
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

        stats_by_date[current_date.isoformat()] = {
            'total_watch_time_ms': total_watch_time_ms,
            'episode_count': episode_count,
            'movie_count': movie_count,
            'unique_shows_count': len(unique_shows)
        }

        current_date += datetime.timedelta(days=1)

    return stats_by_date


def _update_daily_statistics(user_id, date):
    """
    Update daily watch statistics for a user and date.
    Called by webhook after watch events.

    Args:
        user_id: User ID
        date: Date to update (datetime.date)
    """
    db = database.get_db()

    # Calculate stats for this date
    stats = _calculate_watch_statistics(user_id, date, date)
    if not stats or date.isoformat() not in stats:
        return

    date_stats = stats[date.isoformat()]

    # Insert or update daily statistics
    db.execute('''
        INSERT INTO user_watch_statistics
        (user_id, stat_date, total_watch_time_ms, episode_count, movie_count, unique_shows_count)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (user_id, stat_date) DO UPDATE SET
            total_watch_time_ms = excluded.total_watch_time_ms,
            episode_count = excluded.episode_count,
            movie_count = excluded.movie_count,
            unique_shows_count = excluded.unique_shows_count,
            updated_at = CURRENT_TIMESTAMP
    ''', (
        user_id,
        date.isoformat(),
        date_stats['total_watch_time_ms'],
        date_stats['episode_count'],
        date_stats['movie_count'],
        date_stats['unique_shows_count']
    ))

    db.commit()


def _calculate_current_streak(user_id):
    """
    Calculate the current watch streak for a user.

    Args:
        user_id: User ID

    Returns:
        int: Current streak length in days
    """
    db = database.get_db()

    # Get all dates with watch activity, ordered by date descending
    dates = db.execute('''
        SELECT stat_date
        FROM user_watch_statistics
        WHERE user_id = ?
            AND (episode_count > 0 OR movie_count > 0)
        ORDER BY stat_date DESC
    ''', (user_id,)).fetchall()

    if not dates:
        return 0

    # Check if there's activity today or yesterday
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)

    most_recent_date = datetime.date.fromisoformat(dates[0]['stat_date'])

    if most_recent_date not in [today, yesterday]:
        # Streak is broken
        return 0

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

    return streak_length


def _update_watch_streak(user_id):
    """
    Update the watch streak record for a user.

    Args:
        user_id: User ID
    """
    db = database.get_db()

    current_streak = _calculate_current_streak(user_id)

    if current_streak == 0:
        # Mark all streaks as not current
        db.execute('''
            UPDATE user_watch_streaks
            SET is_current = 0
            WHERE user_id = ? AND is_current = 1
        ''', (user_id,))
        db.commit()
        return

    # Get the most recent streak record
    recent_streak = db.execute('''
        SELECT id, streak_length_days, streak_start_date
        FROM user_watch_streaks
        WHERE user_id = ? AND is_current = 1
        ORDER BY streak_end_date DESC
        LIMIT 1
    ''', (user_id,)).fetchone()

    today = datetime.date.today()

    if recent_streak:
        # Update existing streak
        streak_start = datetime.date.fromisoformat(recent_streak['streak_start_date'])

        db.execute('''
            UPDATE user_watch_streaks
            SET streak_end_date = ?,
                streak_length_days = ?
            WHERE id = ?
        ''', (today.isoformat(), current_streak, recent_streak['id']))
    else:
        # Create new streak record
        streak_start = today - datetime.timedelta(days=current_streak - 1)

        db.execute('''
            INSERT INTO user_watch_streaks
            (user_id, streak_start_date, streak_end_date, streak_length_days, is_current)
            VALUES (?, ?, ?, ?, 1)
        ''', (user_id, streak_start.isoformat(), today.isoformat(), current_streak))

    db.commit()


def _get_genre_distribution(user_id):
    """
    Get genre distribution from watched shows and movies.

    Args:
        user_id: User ID

    Returns:
        list: List of dicts with genre and watch_count
    """
    db = database.get_db()

    # Get user's plex username
    user = db.execute('SELECT plex_username FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user or not user['plex_username']:
        return []

    plex_username = user['plex_username']

    # Get all watched shows and movies from activity log
    watched_media = db.execute('''
        SELECT DISTINCT
            pal.media_type,
            pal.tmdb_id,
            COUNT(*) as watch_count
        FROM plex_activity_log pal
        WHERE pal.plex_username = ?
            AND pal.event_type IN ('media.stop', 'media.scrobble')
            AND pal.tmdb_id IS NOT NULL
        GROUP BY pal.media_type, pal.tmdb_id
    ''', (plex_username,)).fetchall()

    # Collect genres
    genre_counts = {}

    for media in watched_media:
        genres = []

        if media['media_type'] == 'episode' and media['tmdb_id']:
            # For episodes, tmdb_id is the show's TMDB ID
            show = db.execute('''
                SELECT genres
                FROM sonarr_shows
                WHERE tmdb_id = ?
            ''', (media['tmdb_id'],)).fetchone()

            if show and show['genres']:
                try:
                    genres = json.loads(show['genres']) if isinstance(show['genres'], str) else show['genres']
                except:
                    pass

        elif media['media_type'] == 'movie' and media['tmdb_id']:
            # For movies, tmdb_id is the movie's TMDB ID
            movie = db.execute('''
                SELECT genres
                FROM radarr_movies
                WHERE tmdb_id = ?
            ''', (media['tmdb_id'],)).fetchone()

            if movie and movie['genres']:
                try:
                    genres = json.loads(movie['genres']) if isinstance(movie['genres'], str) else movie['genres']
                except:
                    pass

        # Count genres
        for genre in genres:
            if genre:
                genre_counts[genre] = genre_counts.get(genre, 0) + media['watch_count']

    # Convert to list and sort by count
    genre_list = [{'genre': genre, 'count': count} for genre, count in genre_counts.items()]
    genre_list.sort(key=lambda x: x['count'], reverse=True)

    return genre_list


# ============================================================================
# Watch Statistics API Endpoints
# ============================================================================

@main_bp.route('/api/profile/statistics/overview')
@login_required
def api_statistics_overview():
    """Get overview statistics for the current user"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = database.get_db()

    # Get total watch time and counts (all time)
    total_stats = db.execute('''
        SELECT
            COALESCE(SUM(total_watch_time_ms), 0) as total_watch_time_ms,
            COALESCE(SUM(episode_count), 0) as total_episodes,
            COALESCE(SUM(movie_count), 0) as total_movies
        FROM user_watch_statistics
        WHERE user_id = ?
    ''', (user_id,)).fetchone()

    # Get current streak
    current_streak = _calculate_current_streak(user_id)

    # Convert milliseconds to hours
    total_hours = (total_stats['total_watch_time_ms'] or 0) / (1000 * 60 * 60)

    return jsonify({
        'success': True,
        'total_watch_time_hours': round(total_hours, 1),
        'total_episodes': total_stats['total_episodes'] or 0,
        'total_movies': total_stats['total_movies'] or 0,
        'current_streak_days': current_streak
    })


@main_bp.route('/api/profile/statistics/watch-time')
@login_required
def api_statistics_watch_time():
    """Get daily watch time data for charts"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    # Get period parameter (default 30 days)
    period = request.args.get('period', '30')
    try:
        days = int(period)
        if days not in [30, 90, 365]:
            days = 30
    except:
        days = 30

    db = database.get_db()

    # Get daily stats for the period
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=days - 1)

    daily_stats = db.execute('''
        SELECT
            stat_date,
            total_watch_time_ms,
            episode_count,
            movie_count
        FROM user_watch_statistics
        WHERE user_id = ?
            AND stat_date >= ?
            AND stat_date <= ?
        ORDER BY stat_date ASC
    ''', (user_id, start_date.isoformat(), end_date.isoformat())).fetchall()

    # Fill in missing dates with zeros
    data = []
    current_date = start_date
    stats_dict = {row['stat_date']: row for row in daily_stats}

    while current_date <= end_date:
        date_str = current_date.isoformat()
        if date_str in stats_dict:
            row = stats_dict[date_str]
            watch_hours = (row['total_watch_time_ms'] or 0) / (1000 * 60 * 60)
            data.append({
                'date': date_str,
                'watch_hours': round(watch_hours, 2),
                'episode_count': row['episode_count'] or 0,
                'movie_count': row['movie_count'] or 0
            })
        else:
            data.append({
                'date': date_str,
                'watch_hours': 0,
                'episode_count': 0,
                'movie_count': 0
            })

        current_date += datetime.timedelta(days=1)

    return jsonify({
        'success': True,
        'data': data
    })


@main_bp.route('/api/profile/statistics/genres')
@login_required
def api_statistics_genres():
    """Get genre distribution for pie chart"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    genres = _get_genre_distribution(user_id)

    return jsonify({
        'success': True,
        'genres': genres[:10]  # Limit to top 10 genres
    })


@main_bp.route('/api/profile/statistics/viewing-patterns')
@login_required
def api_statistics_viewing_patterns():
    """Get viewing patterns by hour and day of week"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = database.get_db()

    # Get user's plex username
    user = db.execute('SELECT plex_username FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user or not user['plex_username']:
        return jsonify({'success': True, 'patterns': []})

    plex_username = user['plex_username']

    # Get all watch events
    events = db.execute('''
        SELECT event_timestamp
        FROM plex_activity_log
        WHERE plex_username = ?
            AND event_type IN ('media.stop', 'media.scrobble')
    ''', (plex_username,)).fetchall()

    # Count by hour and day of week
    hour_counts = [0] * 24
    day_counts = [0] * 7  # 0=Monday, 6=Sunday

    for event in events:
        try:
            # Parse timestamp
            if isinstance(event['event_timestamp'], str):
                timestamp = datetime.datetime.fromisoformat(event['event_timestamp'].replace('Z', '+00:00'))
            else:
                timestamp = event['event_timestamp']

            hour_counts[timestamp.hour] += 1
            day_counts[timestamp.weekday()] += 1
        except:
            pass

    return jsonify({
        'success': True,
        'by_hour': hour_counts,
        'by_day': day_counts
    })


@main_bp.route('/api/profile/statistics/top-shows')
@login_required
def api_statistics_top_shows():
    """Get top watched shows or movies"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    # Get parameters
    media_type = request.args.get('type', 'show')
    limit = request.args.get('limit', '10')

    try:
        limit = int(limit)
        if limit > 50:
            limit = 50
    except:
        limit = 10

    db = database.get_db()

    # Get user's plex username
    user = db.execute('SELECT plex_username FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user or not user['plex_username']:
        return jsonify({'success': True, 'items': []})

    plex_username = user['plex_username']

    if media_type == 'show':
        # Get top shows
        top_items = db.execute('''
            SELECT
                s.id,
                s.title,
                s.poster_url as poster_path,
                COUNT(*) as watch_count,
                SUM(pal.duration_ms) as total_watch_time_ms
            FROM plex_activity_log pal
            JOIN sonarr_shows s ON pal.tmdb_id = s.tmdb_id
            WHERE pal.plex_username = ?
                AND pal.media_type = 'episode'
                AND pal.event_type IN ('media.stop', 'media.scrobble')
            GROUP BY s.id, s.title, s.poster_url
            ORDER BY watch_count DESC
            LIMIT ?
        ''', (plex_username, limit)).fetchall()
    else:
        # Get top movies
        top_items = db.execute('''
            SELECT
                m.id,
                m.title,
                m.poster_url as poster_path,
                COUNT(*) as watch_count,
                SUM(pal.duration_ms) as total_watch_time_ms
            FROM plex_activity_log pal
            JOIN radarr_movies m ON pal.tmdb_id = m.tmdb_id
            WHERE pal.plex_username = ?
                AND pal.media_type = 'movie'
                AND pal.event_type IN ('media.stop', 'media.scrobble')
            GROUP BY m.id, m.title, m.poster_url
            ORDER BY watch_count DESC
            LIMIT ?
        ''', (plex_username, limit)).fetchall()

    # Format results
    items = []
    for item in top_items:
        watch_hours = (item['total_watch_time_ms'] or 0) / (1000 * 60 * 60)
        items.append({
            'id': item['id'],
            'title': item['title'],
            'poster_path': item['poster_path'],
            'watch_count': item['watch_count'],
            'watch_hours': round(watch_hours, 1)
        })

    return jsonify({
        'success': True,
        'items': items
    })


@main_bp.route('/profile/statistics')
@login_required
def profile_statistics():
    """Display user watch statistics and viewing trends"""
    user_id = session.get('user_id')
    if not user_id:
        flash('Please log in to view your statistics.', 'error')
        return redirect(url_for('main.login'))

    # Get basic counts for the tab navigation
    db = database.get_db()

    # Get user info
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

    # Convert user row to dict so we can add the plex_member_since field
    user_dict = dict(user)
    # Use the plex_joined_at from Plex API if available, otherwise fall back to created_at
    user_dict['plex_member_since'] = user_dict.get('plex_joined_at') or user_dict.get('created_at')

    # Get profile statistics using helper function
    stats = _get_profile_stats(db, user_id)

    return render_template('profile_statistics.html',
                         user=user_dict,
                         **stats,
                         active_tab='statistics')


# ============================================================================
# Custom Lists API Endpoints
# ============================================================================

@main_bp.route('/api/profile/lists', methods=['GET'])
@login_required
def api_get_lists():
    """Get lists - supports filter param: 'mine', 'public', 'shared'"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = database.get_db()
    filter_type = request.args.get('filter', 'mine')

    if filter_type == 'public':
        # Get all public lists from all users
        lists = db.execute('''
            SELECT l.id, l.name, l.description, l.item_count, l.is_public,
                   l.created_at, l.updated_at, l.user_id,
                   u.username as owner_username
            FROM user_lists l
            JOIN users u ON l.user_id = u.id
            WHERE l.is_public = 1
            ORDER BY l.updated_at DESC
        ''').fetchall()
    elif filter_type == 'shared':
        # Get public lists from other users
        lists = db.execute('''
            SELECT l.id, l.name, l.description, l.item_count, l.is_public,
                   l.created_at, l.updated_at, l.user_id,
                   u.username as owner_username
            FROM user_lists l
            JOIN users u ON l.user_id = u.id
            WHERE l.is_public = 1 AND l.user_id != ?
            ORDER BY l.updated_at DESC
        ''', (user_id,)).fetchall()
    else:  # 'mine' or default
        # Get only current user's lists (public and private)
        lists = db.execute('''
            SELECT l.id, l.name, l.description, l.item_count, l.is_public,
                   l.created_at, l.updated_at, l.user_id,
                   u.username as owner_username
            FROM user_lists l
            JOIN users u ON l.user_id = u.id
            WHERE l.user_id = ?
            ORDER BY l.updated_at DESC
        ''', (user_id,)).fetchall()

    lists_data = []
    for lst in lists:
        lists_data.append({
            'id': lst['id'],
            'name': lst['name'],
            'description': lst['description'],
            'item_count': lst['item_count'] or 0,
            'is_public': bool(lst['is_public']),
            'is_owner': lst['user_id'] == user_id,
            'owner_username': lst['owner_username'],
            'created_at': lst['created_at'],
            'updated_at': lst['updated_at']
        })

    return jsonify({
        'success': True,
        'lists': lists_data
    })


@main_bp.route('/api/profile/lists', methods=['POST'])
@login_required
def api_create_list():
    """Create a new list"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    data = request.get_json()
    name = data.get('name', '').strip()
    description = data.get('description', '').strip()
    is_public = data.get('is_public', False)

    if not name:
        return jsonify({'success': False, 'error': 'List name is required'}), 400

    db = database.get_db()

    try:
        cur = db.execute('''
            INSERT INTO user_lists (user_id, name, description, is_public)
            VALUES (?, ?, ?, ?)
        ''', (user_id, name, description, is_public))
        db.commit()

        return jsonify({
            'success': True,
            'list_id': cur.lastrowid
        })
    except Exception as e:
        current_app.logger.error(f"Error creating list: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@main_bp.route('/api/profile/lists/<int:list_id>', methods=['GET'])
@login_required
def api_get_list(list_id):
    """Get a specific list with all its items"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = database.get_db()

    # Get list info - allow access to public lists or owned lists
    lst = db.execute('''
        SELECT l.id, l.name, l.description, l.item_count, l.created_at, l.updated_at,
               l.user_id, l.is_public, u.username as owner_username
        FROM user_lists l
        JOIN users u ON l.user_id = u.id
        WHERE l.id = ? AND (l.user_id = ? OR l.is_public = 1)
    ''', (list_id, user_id)).fetchone()

    if not lst:
        return jsonify({'success': False, 'error': 'List not found or not accessible'}), 404

    # Get list items with metadata
    items = db.execute('''
        SELECT
            li.id,
            li.media_type,
            li.show_id,
            li.movie_id,
            li.notes,
            li.added_at,
            li.sort_order,
            COALESCE(s.title, m.title) as title,
            COALESCE(s.poster_url, m.poster_url) as poster_path,
            COALESCE(s.tmdb_id, m.tmdb_id) as tmdb_id,
            s.year as show_year,
            m.year as movie_year
        FROM user_list_items li
        LEFT JOIN sonarr_shows s ON li.show_id = s.id AND li.media_type = 'show'
        LEFT JOIN radarr_movies m ON li.movie_id = m.id AND li.media_type = 'movie'
        WHERE li.list_id = ?
        ORDER BY COALESCE(li.sort_order, li.id) ASC
    ''', (list_id,)).fetchall()

    items_data = []
    for item in items:
        items_data.append({
            'id': item['id'],
            'media_type': item['media_type'],
            'show_id': item['show_id'],
            'movie_id': item['movie_id'],
            'title': item['title'],
            'poster_path': item['poster_path'],
            'tmdb_id': item['tmdb_id'],
            'year': item['show_year'] or item['movie_year'],
            'notes': item['notes'],
            'added_at': item['added_at'],
            'sort_order': item['sort_order']
        })

    return jsonify({
        'success': True,
        'list': {
            'id': lst['id'],
            'name': lst['name'],
            'description': lst['description'],
            'item_count': lst['item_count'] or 0,
            'is_public': bool(lst['is_public']),
            'is_owner': lst['user_id'] == user_id,
            'owner_username': lst['owner_username'],
            'created_at': lst['created_at'],
            'updated_at': lst['updated_at']
        },
        'items': items_data
    })


@main_bp.route('/api/profile/lists/<int:list_id>', methods=['PATCH'])
@login_required
def api_update_list(list_id):
    """Update list name/description"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = database.get_db()

    # Verify ownership
    lst = db.execute('''
        SELECT id FROM user_lists WHERE id = ? AND user_id = ?
    ''', (list_id, user_id)).fetchone()

    if not lst:
        return jsonify({'success': False, 'error': 'List not found'}), 404

    data = request.get_json()
    name = data.get('name', '').strip()
    description = data.get('description', '').strip()
    is_public = data.get('is_public')

    if not name:
        return jsonify({'success': False, 'error': 'List name is required'}), 400

    try:
        if is_public is not None:
            db.execute('''
                UPDATE user_lists
                SET name = ?, description = ?, is_public = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (name, description, is_public, list_id))
        else:
            db.execute('''
                UPDATE user_lists
                SET name = ?, description = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (name, description, list_id))
        db.commit()

        return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"Error updating list: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@main_bp.route('/api/profile/lists/<int:list_id>', methods=['DELETE'])
@login_required
def api_delete_list(list_id):
    """Delete a list"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = database.get_db()

    # Verify ownership
    lst = db.execute('''
        SELECT id FROM user_lists WHERE id = ? AND user_id = ?
    ''', (list_id, user_id)).fetchone()

    if not lst:
        return jsonify({'success': False, 'error': 'List not found'}), 404

    try:
        db.execute('DELETE FROM user_lists WHERE id = ?', (list_id,))
        db.commit()

        return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"Error deleting list: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@main_bp.route('/api/profile/lists/<int:list_id>/items', methods=['POST'])
@login_required
def api_add_list_item(list_id):
    """Add an item to a list"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = database.get_db()

    # Verify ownership
    lst = db.execute('''
        SELECT id FROM user_lists WHERE id = ? AND user_id = ?
    ''', (list_id, user_id)).fetchone()

    if not lst:
        return jsonify({'success': False, 'error': 'List not found'}), 404

    data = request.get_json()
    media_type = data.get('media_type')
    show_id = data.get('show_id')
    movie_id = data.get('movie_id')
    notes = data.get('notes', '').strip()

    if media_type not in ['show', 'movie']:
        return jsonify({'success': False, 'error': 'Invalid media type'}), 400

    if media_type == 'show' and not show_id:
        return jsonify({'success': False, 'error': 'show_id required for shows'}), 400

    if media_type == 'movie' and not movie_id:
        return jsonify({'success': False, 'error': 'movie_id required for movies'}), 400

    try:
        # Get the next sort order
        max_sort = db.execute('''
            SELECT MAX(sort_order) as max_sort FROM user_list_items WHERE list_id = ?
        ''', (list_id,)).fetchone()

        next_sort = (max_sort['max_sort'] or 0) + 1

        db.execute('''
            INSERT INTO user_list_items (list_id, media_type, show_id, movie_id, notes, sort_order)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (list_id, media_type, show_id, movie_id, notes, next_sort))
        
        # Update item_count on the list
        db.execute('''
            UPDATE user_lists 
            SET item_count = (SELECT COUNT(*) FROM user_list_items WHERE list_id = ?),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (list_id, list_id))
        
        db.commit()

        return jsonify({'success': True})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'error': 'Item already in list'}), 400
    except Exception as e:
        current_app.logger.error(f"Error adding item to list: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@main_bp.route('/api/profile/lists/<int:list_id>/items/<int:item_id>', methods=['DELETE'])
@login_required
def api_remove_list_item(list_id, item_id):
    """Remove an item from a list"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = database.get_db()

    # Verify list ownership
    lst = db.execute('''
        SELECT id FROM user_lists WHERE id = ? AND user_id = ?
    ''', (list_id, user_id)).fetchone()

    if not lst:
        return jsonify({'success': False, 'error': 'List not found'}), 404

    try:
        db.execute('''
            DELETE FROM user_list_items
            WHERE id = ? AND list_id = ?
        ''', (item_id, list_id))
        
        # Update item_count on the list
        db.execute('''
            UPDATE user_lists 
            SET item_count = (SELECT COUNT(*) FROM user_list_items WHERE list_id = ?),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (list_id, list_id))
        
        db.commit()

        return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"Error removing item from list: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@main_bp.route('/api/profile/lists/<int:list_id>/items/<int:item_id>', methods=['PATCH'])
@login_required
def api_update_list_item(list_id, item_id):
    """Update list item notes or order"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = database.get_db()

    # Verify list ownership
    lst = db.execute('''
        SELECT id FROM user_lists WHERE id = ? AND user_id = ?
    ''', (list_id, user_id)).fetchone()

    if not lst:
        return jsonify({'success': False, 'error': 'List not found'}), 404

    data = request.get_json()
    notes = data.get('notes')
    sort_order = data.get('sort_order')

    if notes is None and sort_order is None:
        return jsonify({'success': False, 'error': 'No update data provided'}), 400

    try:
        if notes is not None and sort_order is not None:
            db.execute('''
                UPDATE user_list_items
                SET notes = ?, sort_order = ?
                WHERE id = ? AND list_id = ?
            ''', (notes, sort_order, item_id, list_id))
        elif notes is not None:
            db.execute('''
                UPDATE user_list_items
                SET notes = ?
                WHERE id = ? AND list_id = ?
            ''', (notes, item_id, list_id))
        elif sort_order is not None:
            db.execute('''
                UPDATE user_list_items
                SET sort_order = ?
                WHERE id = ? AND list_id = ?
            ''', (sort_order, item_id, list_id))

        db.commit()

        return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"Error updating list item: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@main_bp.route('/api/profile/check-in-lists/<media_type>/<int:media_id>', methods=['GET'])
@login_required
def api_check_in_lists(media_type, media_id):
    """Check which lists contain a specific item"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    if media_type not in ['show', 'movie']:
        return jsonify({'success': False, 'error': 'Invalid media type'}), 400

    db = database.get_db()

    if media_type == 'show':
        lists_with_item = db.execute('''
            SELECT ul.id, ul.name
            FROM user_lists ul
            JOIN user_list_items uli ON ul.id = uli.list_id
            WHERE ul.user_id = ?
                AND uli.media_type = 'show'
                AND uli.show_id = ?
        ''', (user_id, media_id)).fetchall()
    else:
        lists_with_item = db.execute('''
            SELECT ul.id, ul.name
            FROM user_lists ul
            JOIN user_list_items uli ON ul.id = uli.list_id
            WHERE ul.user_id = ?
                AND uli.media_type = 'movie'
                AND uli.movie_id = ?
        ''', (user_id, media_id)).fetchall()

    lists_data = [{'id': lst['id'], 'name': lst['name']} for lst in lists_with_item]

    return jsonify({
        'success': True,
        'lists': lists_data
    })


@main_bp.route('/profile/lists')
@login_required
def profile_lists():
    """Display user's custom lists"""
    user_id = session.get('user_id')
    if not user_id:
        flash('Please log in to view your lists.', 'error')
        return redirect(url_for('main.login'))

    db = database.get_db()

    # Get user info
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

    # Convert user row to dict so we can add the plex_member_since field
    user_dict = dict(user)
    # Use the plex_joined_at from Plex API if available, otherwise fall back to created_at
    user_dict['plex_member_since'] = user_dict.get('plex_joined_at') or user_dict.get('created_at')

    # Get profile statistics using helper function
    stats = _get_profile_stats(db, user_id)

    return render_template('profile_lists.html',
                         user=user_dict,
                         **stats,
                         active_tab='lists')


@main_bp.route('/profile/lists/<int:list_id>')
@login_required
def profile_list_detail(list_id):
    """Display a specific list with all its items"""
    user_id = session.get('user_id')
    if not user_id:
        flash('Please log in to view this list.', 'error')
        return redirect(url_for('main.login'))

    db = database.get_db()

    # Get user info
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

    # Convert user row to dict so we can add the plex_member_since field
    user_dict = dict(user)
    # Use the plex_joined_at from Plex API if available, otherwise fall back to created_at
    user_dict['plex_member_since'] = user_dict.get('plex_joined_at') or user_dict.get('created_at')

    # Get list info and verify ownership
    lst = db.execute('''
        SELECT id, name, description, item_count, created_at, updated_at
        FROM user_lists
        WHERE id = ? AND user_id = ?
    ''', (list_id, user_id)).fetchone()

    if not lst:
        flash('List not found.', 'error')
        return redirect(url_for('main.profile_lists'))

    # Get profile statistics using helper function
    stats = _get_profile_stats(db, user_id)

    return render_template('profile_list_detail.html',
                         user=user_dict,
                         list=lst,
                         **stats,
                         active_tab='lists')


# ============================================================================
# Watch Progress Helper Functions
# ============================================================================

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

@main_bp.route('/api/profile/progress/shows', methods=['GET'])
@login_required
def api_get_progress_shows():
    """Get shows with progress filtered by status"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    status = request.args.get('status', 'watching')

    db = database.get_db()

    shows = db.execute('''
        SELECT
            usp.id,
            usp.show_id,
            usp.watched_episodes,
            usp.total_episodes,
            usp.completion_percentage,
            usp.status,
            usp.last_watched_at,
            s.title,
            s.poster_url as poster_path,
            s.tmdb_id,
            s.year
        FROM user_show_progress usp
        JOIN sonarr_shows s ON usp.show_id = s.id
        WHERE usp.user_id = ? AND usp.status = ?
        ORDER BY usp.last_watched_at DESC
    ''', (user_id, status)).fetchall()

    shows_data = []
    for show in shows:
        shows_data.append({
            'id': show['id'],
            'show_id': show['show_id'],
            'title': show['title'],
            'poster_path': show['poster_path'],
            'tmdb_id': show['tmdb_id'],
            'year': show['year'],
            'watched_episodes': show['watched_episodes'] or 0,
            'total_episodes': show['total_episodes'] or 0,
            'completion_percentage': round(show['completion_percentage'] or 0, 1),
            'status': show['status'],
            'last_watched_at': show['last_watched_at']
        })

    return jsonify({
        'success': True,
        'shows': shows_data
    })


@main_bp.route('/api/profile/progress/show/<int:show_id>', methods=['GET'])
@login_required
def api_get_show_progress(show_id):
    """Get detailed progress for a specific show"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = database.get_db()

    # Get show info
    show = db.execute('SELECT * FROM sonarr_shows WHERE id = ?', (show_id,)).fetchone()
    if not show:
        return jsonify({'success': False, 'error': 'Show not found'}), 404

    # Get episode progress
    episodes = db.execute('''
        SELECT
            e.id,
            s.season_number,
            e.episode_number,
            e.title,
            e.air_date_utc,
            COALESCE(uep.is_watched, 0) as is_watched,
            uep.watch_count,
            uep.last_watched_at
        FROM sonarr_episodes e
        JOIN sonarr_seasons s ON e.season_id = s.id
        LEFT JOIN user_episode_progress uep ON e.id = uep.episode_id AND uep.user_id = ?
        WHERE s.show_id = ?
        ORDER BY s.season_number ASC, e.episode_number ASC
    ''', (user_id, show_id)).fetchall()

    episodes_data = []
    for ep in episodes:
        episodes_data.append({
            'episode_id': ep['id'],
            'season_number': ep['season_number'],
            'episode_number': ep['episode_number'],
            'title': ep['title'],
            'air_date': ep['air_date_utc'],
            'is_watched': bool(ep['is_watched']),
            'watch_count': ep['watch_count'] or 0,
            'last_watched_at': ep['last_watched_at']
        })

    return jsonify({
        'success': True,
        'episodes': episodes_data
    })


@main_bp.route('/api/profile/progress/episode/<int:episode_id>/toggle', methods=['POST'])
@login_required
def api_toggle_episode_watched(episode_id):
    """Toggle episode watched status"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    data = request.get_json() or {}
    is_watched = data.get('is_watched', True)

    db = database.get_db()

    # Get episode info
    episode = db.execute('''
        SELECT e.id, s.show_id, s.season_number, e.episode_number
        FROM sonarr_episodes e
        JOIN sonarr_seasons s ON e.season_id = s.id
        WHERE e.id = ?
    ''', (episode_id,)).fetchone()

    if not episode:
        return jsonify({'success': False, 'error': 'Episode not found'}), 404

    try:
        # Insert or update episode progress
        db.execute('''
            INSERT INTO user_episode_progress
            (user_id, show_id, episode_id, season_number, episode_number, is_watched, marked_manually, last_watched_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id, episode_id) DO UPDATE SET
                is_watched = excluded.is_watched,
                marked_manually = 1,
                last_watched_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
        ''', (user_id, episode['show_id'], episode_id, episode['season_number'], episode['episode_number'], is_watched))

        db.commit()

        # Recalculate show completion
        _calculate_show_completion(user_id, episode['show_id'])

        return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"Error toggling episode watched: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@main_bp.route('/api/profile/progress/show/<int:show_id>/status', methods=['PATCH'])
@login_required
def api_update_show_status(show_id):
    """Update show status (watching, completed, dropped, plan_to_watch)"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    data = request.get_json()
    status = data.get('status')

    if status not in ['watching', 'completed', 'dropped', 'plan_to_watch']:
        return jsonify({'success': False, 'error': 'Invalid status'}), 400

    db = database.get_db()

    try:
        # Ensure show progress record exists
        db.execute('''
            INSERT INTO user_show_progress (user_id, show_id, status)
            VALUES (?, ?, ?)
            ON CONFLICT (user_id, show_id) DO UPDATE SET
                status = excluded.status,
                updated_at = CURRENT_TIMESTAMP
        ''', (user_id, show_id, status))

        db.commit()

        return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"Error updating show status: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@main_bp.route('/api/profile/progress/season/<int:show_id>/<int:season_number>/mark-all', methods=['POST'])
@login_required
def api_mark_season_watched(show_id, season_number):
    """Mark all episodes in a season as watched or unwatched"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    data = request.get_json() or {}
    is_watched = data.get('is_watched', True)

    db = database.get_db()

    try:
        # Get all episodes in the season
        episodes = db.execute('''
            SELECT e.id, s.season_number, e.episode_number
            FROM sonarr_episodes e
            JOIN sonarr_seasons s ON e.season_id = s.id
            WHERE s.show_id = ? AND s.season_number = ?
        ''', (show_id, season_number)).fetchall()

        if not episodes:
            return jsonify({'success': False, 'error': 'No episodes found'}), 404

        # Mark each episode
        for episode in episodes:
            db.execute('''
                INSERT INTO user_episode_progress
                (user_id, episode_id, season_number, episode_number, is_watched, marked_manually, last_watched_at)
                VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id, episode_id) DO UPDATE SET
                    is_watched = excluded.is_watched,
                    marked_manually = 1,
                    last_watched_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
            ''', (user_id, episode['id'], episode['season_number'], episode['episode_number'], is_watched))

        db.commit()

        # Recalculate show completion
        _calculate_show_completion(user_id, show_id)

        return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"Error marking season: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@main_bp.route('/profile/progress')
@login_required
def profile_progress():
    """Display user's watch progress"""
    user_id = session.get('user_id')
    if not user_id:
        flash('Please log in to view your progress.', 'error')
        return redirect(url_for('main.login'))

    db = database.get_db()

    # Get user info
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

    # Convert user row to dict so we can add the plex_member_since field
    user_dict = dict(user)
    # Use the plex_joined_at from Plex API if available, otherwise fall back to created_at
    user_dict['plex_member_since'] = user_dict.get('plex_joined_at') or user_dict.get('created_at')

    # Get profile statistics using helper function
    stats = _get_profile_stats(db, user_id)

    return render_template('profile_progress.html',
                         user=user_dict,
                         **stats,
                         active_tab='progress')

@main_bp.route('/profile/settings')
@login_required
def profile_settings():
    """Display user profile settings page"""
    user_id = session.get('user_id')
    if not user_id:
        flash('Please log in to view your settings.', 'error')
        return redirect(url_for('main.login'))

    db = database.get_db()

    # Get user info
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

    # Convert user row to dict so we can add the plex_member_since field
    user_dict = dict(user)
    # Use the plex_joined_at from Plex API if available, otherwise fall back to created_at
    user_dict['plex_member_since'] = user_dict.get('plex_joined_at') or user_dict.get('created_at')

    # Get profile statistics using helper function
    stats = _get_profile_stats(db, user_id)

    return render_template('profile_settings.html',
                         user=user_dict,
                         **stats,
                         active_tab='settings')

@main_bp.route('/help')
def help():
    """Display user manual and help documentation"""
    return render_template('help.html')

@main_bp.route('/discover')
def discover():
    """Display trending and upcoming content from Jellyseerr"""
    db = database.get_db()
    settings = db.execute('SELECT jellyseer_url FROM settings LIMIT 1').fetchone()
    jellyseer_url = settings['jellyseer_url'] if settings and settings['jellyseer_url'] else None

    return render_template('discover.html', jellyseer_url=jellyseer_url)

@main_bp.route('/calendar')
@login_required
def calendar():
    """
    Display TV Countdown calendar showing:
    - Upcoming episodes from favorited shows
    - Upcoming episodes from watched shows
    - Upcoming series premieres (shows in library but not yet available)
    """
    user_id = session.get('user_id')
    if not user_id:
        flash('Please log in to view the calendar.', 'warning')
        return redirect(url_for('main.login'))

    db = database.get_db()
    
    # Get current date/time for filtering
    now = datetime.datetime.now(timezone.utc).isoformat()
    
    # Get favorited show IDs
    favorited_show_ids = db.execute("""
        SELECT show_id FROM user_favorites
        WHERE user_id = ? AND is_dropped = 0
    """, (user_id,)).fetchall()
    favorited_ids = [row['show_id'] for row in favorited_show_ids]
    
    # Get watched show IDs from plex_activity_log
    watched_show_ids = db.execute("""
        SELECT DISTINCT s.id
        FROM plex_activity_log pal
        JOIN sonarr_shows s ON s.tvdb_id = CAST(pal.grandparent_rating_key AS INTEGER)
        WHERE pal.plex_username = (SELECT plex_username FROM users WHERE id = ?)
            AND pal.media_type = 'episode'
    """, (user_id,)).fetchall()
    watched_ids = [row['id'] for row in watched_show_ids]
    
    # Combine favorited and watched show IDs (unique)
    tracked_show_ids = list(set(favorited_ids + watched_ids))
    
    # Get upcoming episodes for tracked shows
    upcoming_episodes = []
    if tracked_show_ids:
        placeholders = ','.join('?' * len(tracked_show_ids))
        upcoming_episodes = db.execute(f"""
            SELECT 
                e.id as episode_id,
                e.episode_number,
                e.title as episode_title,
                e.air_date_utc,
                e.has_file,
                e.overview,
                ss.season_number,
                s.id as show_db_id,
                s.tmdb_id,
                s.title as show_title,
                s.poster_url,
                s.year
            FROM sonarr_episodes e
            JOIN sonarr_seasons ss ON e.season_id = ss.id
            JOIN sonarr_shows s ON ss.show_id = s.id
            WHERE s.id IN ({placeholders})
                AND e.air_date_utc IS NOT NULL
                AND e.air_date_utc >= ?
                AND ss.season_number > 0
            ORDER BY e.air_date_utc ASC
            LIMIT 100
        """, (*tracked_show_ids, now)).fetchall()
    
    # Get upcoming series premieres (shows in library with no available episodes yet)
    series_premieres = db.execute("""
        SELECT 
            s.id as show_db_id,
            s.tmdb_id,
            s.title as show_title,
            s.poster_url,
            s.year,
            s.overview,
            MIN(e.air_date_utc) as premiere_date
        FROM sonarr_shows s
        JOIN sonarr_seasons ss ON ss.show_id = s.id
        JOIN sonarr_episodes e ON e.season_id = ss.id
        WHERE s.episode_file_count = 0
            AND e.air_date_utc IS NOT NULL
            AND e.air_date_utc >= ?
            AND ss.season_number > 0
        GROUP BY s.id
        ORDER BY premiere_date ASC
        LIMIT 50
    """, (now,)).fetchall()
    
    # Format the data for template
    formatted_upcoming = []
    for ep in upcoming_episodes:
        ep_dict = dict(ep)
        ep_dict['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=ep['tmdb_id'])
        ep_dict['show_url'] = url_for('main.show_detail', tmdb_id=ep['tmdb_id'])
        ep_dict['episode_url'] = url_for('main.episode_detail', 
                                         tmdb_id=ep['tmdb_id'],
                                         season_number=ep['season_number'],
                                         episode_number=ep['episode_number'])
        ep_dict['is_favorited'] = ep['show_db_id'] in favorited_ids
        ep_dict['is_watched'] = ep['show_db_id'] in watched_ids
        
        # Check if this is a season premiere
        season_first_ep = db.execute("""
            SELECT MIN(episode_number) as first_ep
            FROM sonarr_episodes
            WHERE season_id = (
                SELECT id FROM sonarr_seasons 
                WHERE show_id = ? AND season_number = ?
            )
        """, (ep['show_db_id'], ep['season_number'])).fetchone()
        ep_dict['is_season_premiere'] = (ep['episode_number'] == season_first_ep['first_ep'])
        
        formatted_upcoming.append(ep_dict)
    
    formatted_premieres = []
    for show in series_premieres:
        show_dict = dict(show)
        show_dict['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=show['tmdb_id'])
        show_dict['show_url'] = url_for('main.show_detail', tmdb_id=show['tmdb_id'])
        formatted_premieres.append(show_dict)
    
    return render_template('calendar.html',
                         upcoming_episodes=formatted_upcoming,
                         series_premieres=formatted_premieres)

@main_bp.route('/api/profile/settings', methods=['POST'])
@login_required
def update_profile_settings():
    """Update user profile settings (bio, privacy, photo)"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    db = database.get_db()

    try:
        # Get form data
        bio = request.form.get('bio', '').strip()
        profile_show_profile = request.form.get('profile_show_profile') == 'true'
        profile_show_lists = request.form.get('profile_show_lists') == 'true'
        profile_show_favorites = request.form.get('profile_show_favorites') == 'true'
        profile_show_history = request.form.get('profile_show_history') == 'true'
        profile_show_progress = request.form.get('profile_show_progress') == 'true'

        # Validate bio length
        if len(bio) > 500:
            return jsonify({'success': False, 'error': 'Bio must be 500 characters or less'}), 400

        # Handle photo upload if present
        photo_url = None
        if 'photo' in request.files:
            photo = request.files['photo']
            if photo and photo.filename:
                # Validate file size (5MB)
                photo.seek(0, 2)  # Seek to end
                file_size = photo.tell()
                photo.seek(0)  # Seek back to start

                if file_size > 5 * 1024 * 1024:
                    return jsonify({'success': False, 'error': 'File size must be less than 5MB'}), 400

                # Validate file type
                allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
                file_ext = os.path.splitext(photo.filename)[1].lower()
                if file_ext not in allowed_extensions:
                    return jsonify({'success': False, 'error': 'Invalid file type. Use JPG, PNG, GIF, or WEBP'}), 400

                # Save photo to uploads directory
                upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'profiles')
                os.makedirs(upload_dir, exist_ok=True)

                # Generate unique filename
                filename = f"{user_id}_{int(time.time())}{file_ext}"
                filepath = os.path.join(upload_dir, filename)
                photo.save(filepath)

                # Store relative URL
                photo_url = f"/static/uploads/profiles/{filename}"

        # Update user profile
        if photo_url:
            db.execute('''
                UPDATE users
                SET bio = ?, profile_photo_url = ?,
                    profile_show_profile = ?, profile_show_lists = ?,
                    profile_show_favorites = ?, profile_show_history = ?,
                    profile_show_progress = ?
                WHERE id = ?
            ''', (bio, photo_url, profile_show_profile, profile_show_lists,
                  profile_show_favorites, profile_show_history, profile_show_progress, user_id))
        else:
            db.execute('''
                UPDATE users
                SET bio = ?, profile_show_profile = ?, profile_show_lists = ?,
                    profile_show_favorites = ?, profile_show_history = ?,
                    profile_show_progress = ?
                WHERE id = ?
            ''', (bio, profile_show_profile, profile_show_lists,
                  profile_show_favorites, profile_show_history, profile_show_progress, user_id))

        db.commit()

        return jsonify({'success': True, 'photo_url': photo_url})

    except Exception as e:
        db.rollback()
        current_app.logger.error(f"Error updating profile settings: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@main_bp.route('/api/profile/settings/photo', methods=['DELETE'])
@login_required
def delete_profile_photo():
    """Remove user's profile photo"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    db = database.get_db()

    try:
        # Get current photo URL
        user = db.execute('SELECT profile_photo_url FROM users WHERE id = ?', (user_id,)).fetchone()

        if user and user['profile_photo_url']:
            # Delete file from filesystem
            photo_path = user['profile_photo_url']
            if photo_path.startswith('/static/'):
                full_path = os.path.join(current_app.root_path, photo_path.lstrip('/'))
                if os.path.exists(full_path):
                    try:
                        os.remove(full_path)
                    except Exception as e:
                        current_app.logger.warning(f"Could not delete photo file: {str(e)}")

        # Remove from database
        db.execute('UPDATE users SET profile_photo_url = NULL WHERE id = ?', (user_id,))
        db.commit()

        return jsonify({'success': True})

    except Exception as e:
        db.rollback()
        current_app.logger.error(f"Error deleting profile photo: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ========================================
# RECOMMENDATIONS
# ========================================

@main_bp.route('/api/profile/recommendations', methods=['POST'])
@login_required
def create_recommendation():
    """Submit a recommendation for a show or movie"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    data = request.get_json()
    media_type = data.get('media_type')
    media_id = data.get('media_id')
    title = data.get('title', '')
    note = data.get('note', '').strip()

    if not media_type or not media_id:
        return jsonify({'success': False, 'error': 'Missing required fields'}), 400

    if media_type not in ['show', 'movie']:
        return jsonify({'success': False, 'error': 'Invalid media type'}), 400

    db = database.get_db()

    try:
        # Insert recommendation
        db.execute('''
            INSERT INTO user_recommendations (user_id, media_type, media_id, title, note)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, media_type, media_id, title, note))
        db.commit()

        return jsonify({'success': True})

    except Exception as e:
        db.rollback()
        current_app.logger.error(f"Error creating recommendation: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ========================================
# JELLYSEER INTEGRATION
# ========================================

@main_bp.route('/api/jellyseer/request-season', methods=['POST'])
@login_required
def jellyseer_request_season():
    """Request a specific season on Jellyseerr"""
    data = request.get_json()
    tmdb_id = data.get('tmdb_id')
    season_number = data.get('season_number')

    if not tmdb_id or season_number is None:
        return jsonify({'success': False, 'error': 'Missing required fields'}), 400

    db = database.get_db()
    settings = db.execute('SELECT jellyseer_url, jellyseer_api_key FROM settings LIMIT 1').fetchone()

    if not settings or not settings['jellyseer_url'] or not settings['jellyseer_api_key']:
        return jsonify({'success': False, 'error': 'Jellyseerr not configured'}), 400

    jellyseer_url = settings['jellyseer_url'].rstrip('/')
    api_key = settings['jellyseer_api_key']

    try:
        import requests

        # Request the season via Jellyseerr API
        response = requests.post(
            f'{jellyseer_url}/api/v1/request',
            headers={
                'X-Api-Key': api_key,
                'Content-Type': 'application/json'
            },
            json={
                'mediaType': 'tv',
                'mediaId': int(tmdb_id),
                'seasons': [int(season_number)]
            },
            timeout=10
        )

        if response.status_code in [200, 201]:
            return jsonify({'success': True, 'message': f'Season {season_number} requested successfully'})
        else:
            error_msg = response.json().get('message', 'Unknown error') if response.headers.get('content-type', '').startswith('application/json') else response.text
            return jsonify({'success': False, 'error': f'Jellyseerr error: {error_msg}'}), response.status_code

    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Jellyseerr request failed: {str(e)}")
        return jsonify({'success': False, 'error': f'Connection error: {str(e)}'}), 500
    except Exception as e:
        current_app.logger.error(f"Error requesting season: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@main_bp.route('/api/jellyseer/trending', methods=['GET'])
def jellyseer_trending():
    """Fetch trending content from Jellyseerr"""
    db = database.get_db()
    settings = db.execute('SELECT jellyseer_url, jellyseer_api_key FROM settings LIMIT 1').fetchone()

    if not settings or not settings['jellyseer_url'] or not settings['jellyseer_api_key']:
        return jsonify({'success': False, 'error': 'Jellyseerr not configured'}), 400

    jellyseer_url = settings['jellyseer_url'].rstrip('/')
    api_key = settings['jellyseer_api_key']

    try:
        import requests

        # Fetch trending content from Jellyseerr
        response = requests.get(
            f'{jellyseer_url}/api/v1/discover/trending',
            headers={
                'X-Api-Key': api_key,
                'Content-Type': 'application/json'
            },
            params={
                'page': 1,
                'language': 'en'
            },
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            # Transform the data to include only what we need
            trending = []
            for item in data.get('results', [])[:12]:  # Limit to 12 items
                trending.append({
                    'id': item.get('id'),
                    'tmdb_id': item.get('id'),
                    'title': item.get('title') or item.get('name'),
                    'overview': item.get('overview'),
                    'poster_path': item.get('posterPath'),
                    'backdrop_path': item.get('backdropPath'),
                    'media_type': item.get('mediaType'),
                    'vote_average': item.get('voteAverage'),
                    'release_date': item.get('releaseDate') or item.get('firstAirDate'),
                    'year': (item.get('releaseDate') or item.get('firstAirDate', ''))[:4] if (item.get('releaseDate') or item.get('firstAirDate')) else None
                })

            return jsonify({
                'success': True,
                'trending': trending
            })
        else:
            error_msg = response.json().get('message', 'Unknown error') if response.headers.get('content-type', '').startswith('application/json') else response.text
            return jsonify({'success': False, 'error': f'Jellyseerr error: {error_msg}'}), response.status_code

    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Jellyseerr trending fetch failed: {str(e)}")
        return jsonify({'success': False, 'error': f'Connection error: {str(e)}'}), 500
    except Exception as e:
        current_app.logger.error(f"Error fetching trending: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@main_bp.route('/api/jellyseer/upcoming', methods=['GET'])
def jellyseer_upcoming():
    """Fetch upcoming content from Jellyseerr"""
    db = database.get_db()
    settings = db.execute('SELECT jellyseer_url, jellyseer_api_key FROM settings LIMIT 1').fetchone()

    if not settings or not settings['jellyseer_url'] or not settings['jellyseer_api_key']:
        return jsonify({'success': False, 'error': 'Jellyseerr not configured'}), 400

    jellyseer_url = settings['jellyseer_url'].rstrip('/')
    api_key = settings['jellyseer_api_key']

    try:
        import requests

        # Fetch upcoming movies from Jellyseerr
        response = requests.get(
            f'{jellyseer_url}/api/v1/discover/movies/upcoming',
            headers={
                'X-Api-Key': api_key,
                'Content-Type': 'application/json'
            },
            params={
                'page': 1,
                'language': 'en'
            },
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            # Transform the data to include only what we need
            upcoming = []
            for item in data.get('results', [])[:12]:  # Limit to 12 items
                upcoming.append({
                    'id': item.get('id'),
                    'tmdb_id': item.get('id'),
                    'title': item.get('title'),
                    'overview': item.get('overview'),
                    'poster_path': item.get('posterPath'),
                    'backdrop_path': item.get('backdropPath'),
                    'media_type': 'movie',
                    'vote_average': item.get('voteAverage'),
                    'release_date': item.get('releaseDate'),
                    'year': item.get('releaseDate', '')[:4] if item.get('releaseDate') else None
                })

            return jsonify({
                'success': True,
                'upcoming': upcoming
            })
        else:
            error_msg = response.json().get('message', 'Unknown error') if response.headers.get('content-type', '').startswith('application/json') else response.text
            return jsonify({'success': False, 'error': f'Jellyseerr error: {error_msg}'}), response.status_code

    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Jellyseerr upcoming fetch failed: {str(e)}")
        return jsonify({'success': False, 'error': f'Connection error: {str(e)}'}), 500
    except Exception as e:
        current_app.logger.error(f"Error fetching upcoming: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ========================================
# ANNOUNCEMENTS
# ========================================

@main_bp.route('/api/announcements/active', methods=['GET'])
def api_active_announcements():
    """Get active announcements for current user (excluding dismissed ones)"""
    try:
        db = database.get_db()
        user_id = session.get('user_id')
        now = datetime.datetime.now(timezone.utc).isoformat()

        # Get announcements that are active and not dismissed by this user
        if user_id:
            announcements = db.execute('''
                SELECT a.id, a.title, a.message, a.type, a.created_at
                FROM announcements a
                LEFT JOIN user_announcement_views uav ON a.id = uav.announcement_id AND uav.user_id = ?
                WHERE a.is_active = 1
                  AND (a.start_date IS NULL OR a.start_date <= ?)
                  AND (a.end_date IS NULL OR a.end_date >= ?)
                  AND uav.dismissed_at IS NULL
                ORDER BY a.created_at DESC
            ''', (user_id, now, now)).fetchall()
        else:
            # For non-logged-in users, show all active announcements
            announcements = db.execute('''
                SELECT id, title, message, type, created_at
                FROM announcements
                WHERE is_active = 1
                  AND (start_date IS NULL OR start_date <= ?)
                  AND (end_date IS NULL OR end_date >= ?)
                ORDER BY created_at DESC
            ''', (now, now)).fetchall()

        return jsonify({
            'success': True,
            'announcements': [dict(a) for a in announcements]
        })

    except Exception as e:
        current_app.logger.error(f"Error fetching active announcements: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@main_bp.route('/api/announcements/<int:announcement_id>/dismiss', methods=['POST'])
@login_required
def dismiss_announcement(announcement_id):
    """Mark an announcement as dismissed for the current user"""
    try:
        user_id = session.get('user_id')
        db = database.get_db()

        # Mark as dismissed
        db.execute('''
            INSERT INTO user_announcement_views (user_id, announcement_id, dismissed_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id, announcement_id) DO UPDATE SET
                dismissed_at = CURRENT_TIMESTAMP
        ''', (user_id, announcement_id))

        # Also create a notification so user can still see it in notifications
        announcement = db.execute('''
            SELECT title, message, type FROM announcements WHERE id = ?
        ''', (announcement_id,)).fetchone()

        if announcement:
            db.execute('''
                INSERT INTO user_notifications (user_id, type, title, message, is_read, created_at)
                VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            ''', (user_id, 'announcement', announcement['title'], announcement['message']))

        db.commit()

        return jsonify({'success': True})

    except Exception as e:
        db.rollback()
        current_app.logger.error(f"Error dismissing announcement: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ========================================
# PROBLEM REPORTS
# ========================================

@main_bp.route('/api/problem-reports', methods=['POST'])
@login_required
def create_problem_report():
    """Submit a problem report"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    try:
        data = request.get_json()

        category = data.get('category', '').strip()
        title = data.get('title', '').strip()
        description = data.get('description', '').strip()
        show_id = data.get('show_id')
        movie_id = data.get('movie_id')
        episode_id = data.get('episode_id')

        if not category or not title or not description:
            return jsonify({
                'success': False,
                'error': 'Category, title, and description are required'
            }), 400

        db = database.get_db()

        cur = db.execute('''
            INSERT INTO problem_reports
            (user_id, category, title, description, show_id, movie_id, episode_id, status, priority)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'open', 'normal')
        ''', (user_id, category, title, description, show_id, movie_id, episode_id))

        db.commit()

        return jsonify({
            'success': True,
            'id': cur.lastrowid
        })

    except Exception as e:
        db.rollback()
        current_app.logger.error(f"Error creating problem report: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
