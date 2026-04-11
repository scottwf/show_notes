import os
import json
import requests
import re
import sqlite3
import time
import threading
import datetime
from datetime import timezone
import urllib.parse
import logging
import markdown as md

from flask import (
    render_template, request, redirect, url_for, session, jsonify,
    flash, current_app, Response, abort, g
)
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from ... import database
from . import main_bp
from ._shared import (
    get_current_member, get_user_members, set_member_session,
    _get_cached_value, _get_cached_image_path, _get_media_image_url,
    is_onboarding_complete, _get_profile_stats, _get_plex_event_details,
    _calculate_show_completion, MEMBER_AVATAR_COLORS,
)

@main_bp.route('/calendar')
@login_required
def calendar():
    """
    Display TV Countdown calendar showing:
    - Upcoming episodes from favorited shows
    - Upcoming episodes from watched shows
    - Upcoming series premieres (shows in library but not yet available)

    Uses daily cached calendar data for improved performance.
    """
    user_id = session.get('user_id')
    if not user_id:
        flash('Please log in to view the calendar.', 'warning')
        return redirect(url_for('main.login'))

    db = database.get_db()

    # Get plex username for user context
    plex_username = current_user.plex_username if current_user else None

    # Get calendar data (uses cache when available)
    from app import utils
    calendar_data = utils.get_calendar_data_for_user(db, user_id, plex_username)

    # Get favorited and watched IDs as sets for easy lookup
    favorited_ids = set(calendar_data.get('favorited_show_ids', []))
    tracked_ids = set(calendar_data.get('tracked_show_ids', []))

    # Format upcoming episodes for template (only tracked shows)
    formatted_upcoming = []
    for ep in calendar_data.get('tracked_upcoming', []):
        ep_dict = ep.copy()
        tmdb_id = ep.get('tmdb_id')
        if tmdb_id:
            ep_dict['episode_url'] = url_for('main.episode_detail',
                                             tmdb_id=tmdb_id,
                                             season_number=ep.get('season_number'),
                                             episode_number=ep.get('episode_number'))
            # Rename fields for template compatibility
            ep_dict['show_db_id'] = ep.get('show_id')
        formatted_upcoming.append(ep_dict)

    # Format premieres for template
    formatted_premieres = []
    for ep in calendar_data.get('premieres', []):
        ep_dict = ep.copy()
        tmdb_id = ep.get('tmdb_id')
        if tmdb_id:
            ep_dict['episode_url'] = url_for('main.episode_detail',
                                             tmdb_id=tmdb_id,
                                             season_number=ep.get('season_number'),
                                             episode_number=ep.get('episode_number'))
            ep_dict['show_db_id'] = ep.get('show_id')
            if ep.get('is_series_premiere'):
                ep_dict['premiere_type'] = 'Series Premiere'
            else:
                ep_dict['premiere_type'] = f"Season {ep.get('season_number')} Premiere"
            ep_dict['premiere_date'] = ep.get('air_date_utc')
        formatted_premieres.append(ep_dict)

    # Format finales for template (tracked shows only)
    formatted_finales = []
    for ep in calendar_data.get('tracked_finales', []):
        ep_dict = ep.copy()
        tmdb_id = ep.get('tmdb_id')
        if tmdb_id:
            ep_dict['episode_url'] = url_for('main.episode_detail',
                                             tmdb_id=tmdb_id,
                                             season_number=ep.get('season_number'),
                                             episode_number=ep.get('episode_number'))
            ep_dict['show_db_id'] = ep.get('show_id')
            ep_dict['finale_date'] = ep.get('air_date_utc')
        formatted_finales.append(ep_dict)

    return render_template('calendar.html',
                         upcoming_episodes=formatted_upcoming,
                         series_premieres=formatted_premieres,
                         season_finales=formatted_finales)

@main_bp.route('/calendar/feed/<token>.ics')
def calendar_ical_feed(token):
    """
    Serve a personal iCal (.ics) feed for a user based on their unique token.
    No login required — token acts as the auth credential.

    Query params:
        filter: all | premieres | series | finales  (default: all)
        alarm:  1d | 2h | none                      (default: 1d)
    """
    from flask import request as flask_request, Response
    db = database.get_db()
    user_row = db.execute('SELECT id FROM users WHERE ical_token = ?', (token,)).fetchone()
    if not user_row:
        return 'Not found', 404

    feed_filter = flask_request.args.get('filter', 'all')
    if feed_filter not in ('all', 'premieres', 'series', 'finales', 'movies'):
        feed_filter = 'all'
    alarm = flask_request.args.get('alarm', '1d')
    if alarm not in ('1d', '2h', 'none'):
        alarm = '1d'

    from app import utils
    ical_content = utils.generate_ical_for_user(db, user_row['id'],
                                                feed_filter=feed_filter,
                                                alarm=alarm)

    resp = Response(ical_content, mimetype='text/calendar')
    resp.headers['Content-Disposition'] = f'attachment; filename="shownotes-{feed_filter}.ics"'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    # Explicitly clear Vary so iOS Calendar doesn't reject the feed
    resp.headers['Vary'] = 'Accept-Encoding'
    return resp


@main_bp.route('/api/calendar/regenerate-token', methods=['POST'])
@login_required
def regenerate_ical_token():
    """Regenerate the user's iCal feed token."""
    import secrets
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    db = database.get_db()
    new_token = secrets.token_urlsafe(32)
    db.execute('UPDATE users SET ical_token = ? WHERE id = ?', (new_token, user_id))
    db.commit()

    new_url = url_for('main.calendar_ical_feed', token=new_token, _external=True)
    return jsonify({'success': True, 'token': new_token, 'feed_url': new_url})


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

    member_id = session.get('member_id')

    try:
        # Insert recommendation
        db.execute('''
            INSERT INTO user_recommendations (user_id, member_id, media_type, media_id, title, note)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, member_id, media_type, media_id, title, note))
        db.commit()

        return jsonify({'success': True})

    except Exception as e:
        db.rollback()
        current_app.logger.error(f"Error creating recommendation: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@main_bp.route('/profile/recommendations')
@login_required
def profile_recommendations():
    """Display user's recommendations page (sent and received)"""
    user_id = session.get('user_id')
    if not user_id:
        flash('Please log in to view your profile.', 'warning')
        return redirect(url_for('main.login'))

    db = database.get_db()

    # Get user info
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

    # Convert user row to dict
    user_dict = dict(user)
    user_dict['plex_member_since'] = user_dict.get('plex_joined_at') or user_dict.get('created_at')

    # Get user's personal recommendations, scoped to member if active
    member_id = session.get('member_id')
    if member_id:
        my_recommendations = db.execute("""
            SELECT
                ur.id, ur.media_type, ur.media_id, ur.title, ur.note, ur.created_at,
                s.tmdb_id as show_tmdb_id, s.poster_url as show_poster_url, s.year as show_year,
                m.tmdb_id as movie_tmdb_id, m.poster_url as movie_poster_url, m.year as movie_year
            FROM user_recommendations ur
            LEFT JOIN sonarr_shows s ON ur.media_type = 'show' AND ur.media_id = s.id
            LEFT JOIN radarr_movies m ON ur.media_type = 'movie' AND ur.media_id = m.id
            WHERE ur.user_id = ? AND ur.member_id = ?
            ORDER BY ur.created_at DESC
        """, (user_id, member_id)).fetchall()
    else:
        my_recommendations = db.execute("""
            SELECT
                ur.id, ur.media_type, ur.media_id, ur.title, ur.note, ur.created_at,
                s.tmdb_id as show_tmdb_id, s.poster_url as show_poster_url, s.year as show_year,
                m.tmdb_id as movie_tmdb_id, m.poster_url as movie_poster_url, m.year as movie_year
            FROM user_recommendations ur
            LEFT JOIN sonarr_shows s ON ur.media_type = 'show' AND ur.media_id = s.id
            LEFT JOIN radarr_movies m ON ur.media_type = 'movie' AND ur.media_id = m.id
            WHERE ur.user_id = ?
            ORDER BY ur.created_at DESC
        """, (user_id,)).fetchall()

    # Enrich personal recommendations
    enriched_my_recs = []
    for rec in my_recommendations:
        rec_dict = dict(rec)
        if rec_dict['media_type'] == 'show' and rec_dict.get('show_tmdb_id'):
            rec_dict['tmdb_id'] = rec_dict['show_tmdb_id']
            rec_dict['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=rec_dict['show_tmdb_id'])
            rec_dict['detail_url'] = url_for('main.show_detail', tmdb_id=rec_dict['show_tmdb_id'])
            rec_dict['year'] = rec_dict['show_year']
        elif rec_dict['media_type'] == 'movie' and rec_dict.get('movie_tmdb_id'):
            rec_dict['tmdb_id'] = rec_dict['movie_tmdb_id']
            rec_dict['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=rec_dict['movie_tmdb_id'])
            rec_dict['detail_url'] = url_for('main.movie_detail', tmdb_id=rec_dict['movie_tmdb_id'])
            rec_dict['year'] = rec_dict['movie_year']
        else:
            rec_dict['cached_poster_url'] = url_for('static', filename='logos/placeholder_poster.png')
            rec_dict['detail_url'] = '#'
            rec_dict['year'] = None

        # Format date
        if rec_dict.get('created_at'):
            try:
                dt = datetime.datetime.fromisoformat(str(rec_dict['created_at']).replace('Z', '+00:00'))
                rec_dict['formatted_date'] = dt.strftime('%B %d, %Y')
            except:
                rec_dict['formatted_date'] = 'Unknown'

        enriched_my_recs.append(rec_dict)

    # Get received recommendations
    received_recommendations = db.execute("""
        SELECT
            rs.id, rs.from_user_id, rs.media_type, rs.media_id, rs.title, rs.note,
            rs.is_read, rs.created_at,
            u.username as from_username, u.profile_photo_url as from_photo,
            s.tmdb_id as show_tmdb_id, s.poster_url as show_poster_url, s.year as show_year,
            m.tmdb_id as movie_tmdb_id, m.poster_url as movie_poster_url, m.year as movie_year
        FROM recommendation_shares rs
        JOIN users u ON rs.from_user_id = u.id
        LEFT JOIN sonarr_shows s ON rs.media_type = 'show' AND rs.media_id = s.id
        LEFT JOIN radarr_movies m ON rs.media_type = 'movie' AND rs.media_id = m.id
        WHERE rs.to_user_id = ?
        ORDER BY rs.created_at DESC
    """, (user_id,)).fetchall()

    # Enrich received recommendations
    enriched_received = []
    for rec in received_recommendations:
        rec_dict = dict(rec)
        if rec_dict['media_type'] == 'show' and rec_dict.get('show_tmdb_id'):
            rec_dict['tmdb_id'] = rec_dict['show_tmdb_id']
            rec_dict['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=rec_dict['show_tmdb_id'])
            rec_dict['detail_url'] = url_for('main.show_detail', tmdb_id=rec_dict['show_tmdb_id'])
            rec_dict['year'] = rec_dict['show_year']
        elif rec_dict['media_type'] == 'movie' and rec_dict.get('movie_tmdb_id'):
            rec_dict['tmdb_id'] = rec_dict['movie_tmdb_id']
            rec_dict['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=rec_dict['movie_tmdb_id'])
            rec_dict['detail_url'] = url_for('main.movie_detail', tmdb_id=rec_dict['movie_tmdb_id'])
            rec_dict['year'] = rec_dict['movie_year']
        else:
            rec_dict['cached_poster_url'] = url_for('static', filename='logos/placeholder_poster.png')
            rec_dict['detail_url'] = '#'
            rec_dict['year'] = None

        # Format date
        if rec_dict.get('created_at'):
            try:
                dt = datetime.datetime.fromisoformat(str(rec_dict['created_at']).replace('Z', '+00:00'))
                rec_dict['formatted_date'] = dt.strftime('%B %d, %Y')
            except:
                rec_dict['formatted_date'] = 'Unknown'

        enriched_received.append(rec_dict)

    # Count unread received recommendations
    unread_count = sum(1 for r in enriched_received if not r.get('is_read'))

    # Get profile statistics
    stats = _get_profile_stats(db, user_id, member_id=member_id)

    return render_template('profile_recommendations.html',
                         user=user_dict,
                         my_recommendations=enriched_my_recs,
                         received_recommendations=enriched_received,
                         unread_received_count=unread_count,
                         **stats,
                         active_tab='recommendations')


@main_bp.route('/api/profile/recommendations/<int:rec_id>', methods=['DELETE'])
@login_required
def delete_recommendation(rec_id):
    """Delete a personal recommendation"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    db = database.get_db()

    try:
        # Make sure the recommendation belongs to the user
        rec = db.execute(
            'SELECT id FROM user_recommendations WHERE id = ? AND user_id = ?',
            (rec_id, user_id)
        ).fetchone()

        if not rec:
            return jsonify({'success': False, 'error': 'Recommendation not found'}), 404

        db.execute('DELETE FROM user_recommendations WHERE id = ?', (rec_id,))
        db.commit()

        return jsonify({'success': True})

    except Exception as e:
        db.rollback()
        current_app.logger.error(f"Error deleting recommendation: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@main_bp.route('/api/users', methods=['GET'])
@login_required
def get_users_for_recommendations():
    """Get list of users who allow recommendations (for user picker)"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    db = database.get_db()

    try:
        # Get all users except current user who have allow_recommendations = 1
        users = db.execute("""
            SELECT id, username, profile_photo_url
            FROM users
            WHERE id != ? AND (allow_recommendations IS NULL OR allow_recommendations = 1)
            ORDER BY username
        """, (user_id,)).fetchall()

        users_list = [
            {
                'id': u['id'],
                'username': u['username'],
                'profile_photo_url': u['profile_photo_url']
            }
            for u in users
        ]

        return jsonify({'success': True, 'users': users_list})

    except Exception as e:
        current_app.logger.error(f"Error fetching users: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@main_bp.route('/api/recommendations/send', methods=['POST'])
@login_required
def send_recommendation():
    """Send a recommendation to another user"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    data = request.get_json()
    to_user_id = data.get('to_user_id')
    media_type = data.get('media_type')
    media_id = data.get('media_id')
    title = data.get('title', '')
    note = data.get('note', '').strip()

    if not to_user_id or not media_type or not media_id:
        return jsonify({'success': False, 'error': 'Missing required fields'}), 400

    if media_type not in ['show', 'movie']:
        return jsonify({'success': False, 'error': 'Invalid media type'}), 400

    db = database.get_db()

    try:
        # Verify target user exists and allows recommendations
        target_user = db.execute("""
            SELECT id, username, allow_recommendations
            FROM users WHERE id = ?
        """, (to_user_id,)).fetchone()

        if not target_user:
            return jsonify({'success': False, 'error': 'User not found'}), 404

        # Check if user allows recommendations (default to True if column is NULL)
        if target_user['allow_recommendations'] == 0:
            return jsonify({'success': False, 'error': 'This user has disabled recommendations'}), 403

        # Get sender's username
        sender = db.execute('SELECT username FROM users WHERE id = ?', (user_id,)).fetchone()
        sender_username = sender['username'] if sender else 'Someone'

        # Insert recommendation share
        cursor = db.execute('''
            INSERT INTO recommendation_shares (from_user_id, to_user_id, media_type, media_id, title, note)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, to_user_id, media_type, media_id, title, note))
        rec_share_id = cursor.lastrowid

        # Also insert a notification for the target user
        notification_title = f'New Recommendation from {sender_username}'
        notification_message = f'{sender_username} recommended "{title}" to you'
        if note:
            notification_message += f': "{note[:100]}..."' if len(note) > 100 else f': "{note}"'

        # Get show_id or movie_id for the notification
        show_id = None
        movie_id = None
        if media_type == 'show':
            show_id = media_id
        elif media_type == 'movie':
            movie_id = media_id

        db.execute('''
            INSERT INTO user_notifications
            (user_id, show_id, movie_id, notification_type, title, message, created_at)
            VALUES (?, ?, ?, 'recommendation', ?, ?, CURRENT_TIMESTAMP)
        ''', (to_user_id, show_id, movie_id, notification_title, notification_message))

        db.commit()

        return jsonify({'success': True})

    except Exception as e:
        db.rollback()
        current_app.logger.error(f"Error sending recommendation: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@main_bp.route('/api/recommendations/received/<int:rec_id>/read', methods=['POST'])
@login_required
def mark_recommendation_read(rec_id):
    """Mark a received recommendation as read"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    db = database.get_db()

    try:
        # Make sure the recommendation is for the current user
        rec = db.execute(
            'SELECT id FROM recommendation_shares WHERE id = ? AND to_user_id = ?',
            (rec_id, user_id)
        ).fetchone()

        if not rec:
            return jsonify({'success': False, 'error': 'Recommendation not found'}), 404

        db.execute('UPDATE recommendation_shares SET is_read = 1 WHERE id = ?', (rec_id,))
        db.commit()

        return jsonify({'success': True})

    except Exception as e:
        db.rollback()
        current_app.logger.error(f"Error marking recommendation as read: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@main_bp.route('/api/recommendations/received/<int:rec_id>', methods=['DELETE'])
@login_required
def delete_received_recommendation(rec_id):
    """Delete a received recommendation"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    db = database.get_db()

    try:
        # Make sure the recommendation is for the current user
        rec = db.execute(
            'SELECT id FROM recommendation_shares WHERE id = ? AND to_user_id = ?',
            (rec_id, user_id)
        ).fetchone()

        if not rec:
            return jsonify({'success': False, 'error': 'Recommendation not found'}), 404

        db.execute('DELETE FROM recommendation_shares WHERE id = ?', (rec_id,))
        db.commit()

        return jsonify({'success': True})

    except Exception as e:
        db.rollback()
        current_app.logger.error(f"Error deleting received recommendation: {str(e)}")
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
            # Non-logged-in users see no announcements
            announcements = []

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

        report_id = cur.lastrowid
        db.commit()

        # Notify admin
        try:
            from ..utils import send_admin_notification
            username = session.get('username', 'Unknown user')
            notif_url = url_for('admin.problem_reports', _external=True)
            send_admin_notification(
                title=f'New Issue Report: {title}',
                message=f'{username} reported: {description[:200]}',
                url=notif_url,
                url_title='View Reports',
                trigger_key='notify_on_problem_report',
            )
        except Exception as notif_err:
            current_app.logger.warning(f"Admin notification failed: {notif_err}")

        return jsonify({
            'success': True,
            'id': report_id
        })

    except Exception as e:
        db.rollback()
        current_app.logger.error(f"Error creating problem report: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


