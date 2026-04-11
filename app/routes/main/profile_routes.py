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

@main_bp.route('/profile/history')
@login_required
def watch_history():
    """
    Full watch history page with filtering and search (like Tautulli).

    Shows complete watch history with ability to filter and search.
    """
    user_id = session.get('user_id')
    if not user_id:
        flash('Please log in to view your profile.', 'warning')
        return redirect(url_for('main.login'))

    db = database.get_db()

    # Get user info
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    user_dict = dict(user)
    s_username = user['plex_username'] if user['plex_username'] else user['username']

    # Get watch history (recent 100 unique items for full history)
    # Use ROW_NUMBER to get only the most recent entry per unique episode/movie
    # Filter out trailers (duration < 10 minutes = 600000ms)
    watch_history = db.execute("""
        WITH ranked_events AS (
            SELECT
                id, event_type, plex_username, media_type, title, show_title,
                season_episode, view_offset_ms, duration_ms, event_timestamp,
                tmdb_id, grandparent_rating_key,
                ROW_NUMBER() OVER (
                    PARTITION BY
                        CASE
                            WHEN media_type = 'episode' THEN show_title || '-' || season_episode
                            WHEN media_type = 'movie' THEN 'movie-' || COALESCE(tmdb_id, title)
                            ELSE title
                        END
                    ORDER BY event_timestamp DESC
                ) as rn
            FROM plex_activity_log
            WHERE plex_username = ?
            AND event_type IN ('media.stop', 'media.scrobble')
            AND (duration_ms IS NULL OR duration_ms >= 600000)
        )
        SELECT
            id, event_type, plex_username, media_type, title, show_title,
            season_episode, view_offset_ms, duration_ms, event_timestamp,
            tmdb_id, grandparent_rating_key
        FROM ranked_events
        WHERE rn = 1
        ORDER BY event_timestamp DESC
        LIMIT 100
    """, (s_username,)).fetchall()

    # Enrich watch history with show/movie data
    # Batch query approach to avoid N+1 queries
    enriched_history = []

    # Collect all tmdb_ids for movies and show titles for episodes
    movie_tmdb_ids = [item['tmdb_id'] for item in watch_history
                      if item['media_type'] == 'movie' and item['tmdb_id']]
    show_titles = [item['show_title'].lower() for item in watch_history
                   if item['media_type'] == 'episode' and item['show_title']]

    # Batch fetch movies
    movies_map = {}
    if movie_tmdb_ids:
        placeholders = ','.join('?' * len(movie_tmdb_ids))
        movies = db.execute(
            f'SELECT tmdb_id, title, year, poster_url FROM radarr_movies WHERE tmdb_id IN ({placeholders})',
            movie_tmdb_ids
        ).fetchall()
        movies_map = {m['tmdb_id']: dict(m) for m in movies}

    # Batch fetch shows
    shows_map = {}
    if show_titles:
        placeholders = ','.join('?' * len(show_titles))
        shows = db.execute(
            f'SELECT tmdb_id, title, poster_url, LOWER(title) as title_lower FROM sonarr_shows WHERE LOWER(title) IN ({placeholders})',
            show_titles
        ).fetchall()
        shows_map = {s['title_lower']: dict(s) for s in shows}

    # Now enrich items using the pre-fetched data
    for item in watch_history:
        item_dict = dict(item)

        # Try to get additional metadata
        if item_dict['media_type'] == 'movie' and item_dict.get('tmdb_id'):
            movie = movies_map.get(item_dict['tmdb_id'])
            if movie:
                item_dict['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=item_dict['tmdb_id'])
                item_dict['detail_url'] = url_for('main.movie_detail', tmdb_id=item_dict['tmdb_id'])

        elif item_dict['media_type'] == 'episode' and item_dict.get('show_title'):
            show = shows_map.get(item_dict['show_title'].lower())
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

        enriched_history.append(item_dict)

    return render_template('watch_history.html',
                         user=user_dict,
                         watch_history=enriched_history)

# ============================================================================
# WEBHOOK ENDPOINTS
# ============================================================================

@main_bp.route('/pick-profile')
@login_required
def pick_profile():
    """Profile picker — shown after login when multiple household members exist."""
    user_id = session.get('user_id')
    members = get_user_members(user_id)
    if len(members) == 1:
        set_member_session(members[0]['id'])
        return redirect(url_for('main.home'))
    return render_template('pick_profile.html', members=members)


@main_bp.route('/pick-profile/set', methods=['POST'])
@login_required
def set_profile():
    """Set the active household member from the picker or switch-profile UI."""
    user_id = session.get('user_id')
    member_id = request.form.get('member_id', type=int)
    if not member_id:
        return redirect(url_for('main.pick_profile'))
    db = database.get_db()
    member = db.execute(
        'SELECT id FROM household_members WHERE id = ? AND user_id = ?',
        (member_id, user_id)
    ).fetchone()
    if member:
        set_member_session(member_id)
    return redirect(request.form.get('next') or url_for('main.home'))


@main_bp.route('/api/profile/members', methods=['GET'])
@login_required
def list_members():
    user_id = session.get('user_id')
    members = [dict(m) for m in get_user_members(user_id)]
    return jsonify(members)


@main_bp.route('/api/profile/members', methods=['POST'])
@login_required
def add_member():
    """Create a new household member profile."""
    user_id = session.get('user_id')
    display_name = (request.json or request.form).get('display_name', '').strip()
    avatar_color = (request.json or request.form).get('avatar_color', '#0ea5e9')
    if not display_name:
        return jsonify({'error': 'display_name required'}), 400
    if avatar_color not in MEMBER_AVATAR_COLORS:
        avatar_color = MEMBER_AVATAR_COLORS[0]

    db = database.get_db()
    count = db.execute('SELECT COUNT(*) FROM household_members WHERE user_id = ?', (user_id,)).fetchone()[0]
    if count >= 6:
        return jsonify({'error': 'Maximum 6 profiles per account'}), 400

    db.execute(
        'INSERT INTO household_members (user_id, display_name, avatar_color) VALUES (?, ?, ?)',
        (user_id, display_name, avatar_color)
    )
    db.commit()
    member = db.execute(
        'SELECT * FROM household_members WHERE user_id = ? ORDER BY id DESC LIMIT 1',
        (user_id,)
    ).fetchone()
    return jsonify(dict(member)), 201


@main_bp.route('/api/profile/members/<int:member_id>', methods=['DELETE'])
@login_required
def delete_member(member_id):
    """Delete a household member (cannot delete the default member)."""
    user_id = session.get('user_id')
    db = database.get_db()
    member = db.execute(
        'SELECT * FROM household_members WHERE id = ? AND user_id = ?',
        (member_id, user_id)
    ).fetchone()
    if not member:
        return jsonify({'error': 'Not found'}), 404
    if member['is_default']:
        return jsonify({'error': 'Cannot delete the primary profile'}), 400
    db.execute('DELETE FROM household_members WHERE id = ?', (member_id,))
    db.commit()
    if session.get('member_id') == member_id:
        default = db.execute(
            'SELECT id FROM household_members WHERE user_id = ? AND is_default = 1',
            (user_id,)
        ).fetchone()
        if default:
            set_member_session(default['id'])
    return jsonify({'deleted': True})


@main_bp.route('/api/profile/members/<int:member_id>', methods=['PATCH'])
@login_required
def update_member(member_id):
    """Rename a member or update their avatar color."""
    user_id = session.get('user_id')
    db = database.get_db()
    member = db.execute(
        'SELECT id FROM household_members WHERE id = ? AND user_id = ?',
        (member_id, user_id)
    ).fetchone()
    if not member:
        return jsonify({'error': 'Not found'}), 404
    data = request.json or {}
    display_name = data.get('display_name', '').strip()
    avatar_color = data.get('avatar_color', '')
    if display_name:
        db.execute('UPDATE household_members SET display_name = ? WHERE id = ?', (display_name, member_id))
    if avatar_color in MEMBER_AVATAR_COLORS:
        db.execute('UPDATE household_members SET avatar_color = ? WHERE id = ?', (avatar_color, member_id))
    db.commit()
    return jsonify(dict(db.execute('SELECT * FROM household_members WHERE id = ?', (member_id,)).fetchone()))


@main_bp.route('/profile')
@login_required
def profile():
    """
    User's full profile page with header, bio, and watch history.

    Shows profile information, stats, and recent watch history.
    """
    user_id = session.get('user_id')
    if not user_id:
        flash('Please log in to view your profile.', 'warning')
        return redirect(url_for('main.login'))

    db = database.get_db()

    # Get user info
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    user_dict = dict(user)
    user_dict['plex_member_since'] = user_dict.get('plex_joined_at') or user_dict.get('created_at')

    # Get currently playing/paused item from Tautulli (real-time data)
    from ..utils import get_tautulli_current_activity

    current_plex_event = None
    s_username = user['plex_username'] if user['plex_username'] else user['username']

    tautulli_session = get_tautulli_current_activity(username=s_username)

    if tautulli_session:
        # Convert Tautulli session data to our expected format
        parent_index = int(tautulli_session.get('parent_media_index', 0) or 0)
        media_index = int(tautulli_session.get('media_index', 0) or 0)
        view_offset = int(tautulli_session.get('view_offset', 0) or 0)
        duration = int(tautulli_session.get('duration', 0) or 0)

        current_plex_event = {
            'title': tautulli_session.get('full_title') or tautulli_session.get('title'),
            'media_type': tautulli_session.get('media_type'),
            'show_title': tautulli_session.get('grandparent_title'),
            'episode_title': tautulli_session.get('title'),
            'season_episode': f"S{parent_index:02d}E{media_index:02d}" if tautulli_session.get('media_type') == 'episode' else None,
            'view_offset_ms': view_offset * 1000,
            'duration_ms': duration * 1000,
            'state': tautulli_session.get('state'),
            'year': tautulli_session.get('year'),
            'overview': tautulli_session.get('summary'),
        }

        # Get details with proper linking
        event_details = _get_plex_event_details(current_plex_event, db)
        current_plex_event.update(event_details)

    # Get profile statistics
    stats = _get_profile_stats(db, user_id, member_id=session.get('member_id'))

    # Get watch history — one entry per show/movie, most recent play per title
    watch_history = db.execute("""
        WITH ranked AS (
            SELECT
                id, media_type, show_title, title, season_episode, tmdb_id,
                grandparent_rating_key, event_timestamp, view_offset_ms, duration_ms,
                CASE
                    WHEN media_type = 'episode' THEN 'show-' || LOWER(COALESCE(show_title, title))
                    WHEN media_type = 'movie'   THEN 'movie-' || COALESCE(CAST(tmdb_id AS TEXT), LOWER(title))
                    ELSE LOWER(title)
                END AS group_key,
                ROW_NUMBER() OVER (
                    PARTITION BY CASE
                        WHEN media_type = 'episode' THEN 'show-' || LOWER(COALESCE(show_title, title))
                        WHEN media_type = 'movie'   THEN 'movie-' || COALESCE(CAST(tmdb_id AS TEXT), LOWER(title))
                        ELSE LOWER(title)
                    END
                    ORDER BY event_timestamp DESC
                ) AS rn,
                COUNT(*) OVER (
                    PARTITION BY CASE
                        WHEN media_type = 'episode' THEN 'show-' || LOWER(COALESCE(show_title, title))
                        WHEN media_type = 'movie'   THEN 'movie-' || COALESCE(CAST(tmdb_id AS TEXT), LOWER(title))
                        ELSE LOWER(title)
                    END
                ) AS play_count
            FROM plex_activity_log
            WHERE plex_username = ?
              AND event_type IN ('media.stop', 'media.scrobble')
              AND (duration_ms IS NULL OR duration_ms >= 600000)
        )
        SELECT * FROM ranked WHERE rn = 1
        ORDER BY event_timestamp DESC
        LIMIT 200
    """, (s_username,)).fetchall()

    # Enrich watch history with show/movie data using batch queries to avoid N+1
    enriched_history = []

    movie_tmdb_ids = [item['tmdb_id'] for item in watch_history
                      if item['media_type'] == 'movie' and item['tmdb_id']]
    show_titles = [item['show_title'].lower() for item in watch_history
                   if item['media_type'] == 'episode' and item['show_title']]

    movies_map = {}
    if movie_tmdb_ids:
        placeholders = ','.join('?' * len(movie_tmdb_ids))
        movies = db.execute(
            f'SELECT tmdb_id, title, year, poster_url FROM radarr_movies WHERE tmdb_id IN ({placeholders})',
            movie_tmdb_ids
        ).fetchall()
        movies_map = {m['tmdb_id']: dict(m) for m in movies}

    shows_map = {}
    if show_titles:
        placeholders = ','.join('?' * len(show_titles))
        shows = db.execute(
            f'SELECT tmdb_id, title, poster_url, LOWER(title) as title_lower FROM sonarr_shows WHERE LOWER(title) IN ({placeholders})',
            show_titles
        ).fetchall()
        shows_map = {s['title_lower']: dict(s) for s in shows}

    for item in watch_history:
        item_dict = dict(item)

        if item_dict['media_type'] == 'movie' and item_dict.get('tmdb_id'):
            movie = movies_map.get(item_dict['tmdb_id'])
            if movie:
                item_dict['year'] = movie.get('year')
                item_dict['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=item_dict['tmdb_id'])
                item_dict['detail_url'] = url_for('main.movie_detail', tmdb_id=item_dict['tmdb_id'])

        elif item_dict['media_type'] == 'episode' and item_dict.get('show_title'):
            show = shows_map.get(item_dict['show_title'].lower())
            if show:
                item_dict['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=show['tmdb_id'])
                item_dict['detail_url'] = url_for('main.show_detail', tmdb_id=show['tmdb_id'])
                if item_dict.get('season_episode'):
                    match = re.match(r'S(\d+)E(\d+)', item_dict['season_episode'])
                    if match:
                        season_num = int(match.group(1))
                        episode_num = int(match.group(2))
                        item_dict['episode_detail_url'] = url_for('main.episode_detail',
                                                                    tmdb_id=show['tmdb_id'],
                                                                    season_number=season_num,
                                                                    episode_number=episode_num)

        enriched_history.append(item_dict)

    return render_template('profile_history.html',
                         user=user_dict,
                         current_plex_event=current_plex_event,
                         watch_history=enriched_history,
                         **stats,
                         active_tab='history')


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
    member_id = session.get('member_id')
    if member_id:
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
            WHERE uf.user_id = ? AND uf.member_id = ? AND uf.is_dropped = 0
            ORDER BY uf.added_at DESC
        """, (user_id, member_id)).fetchall()
    else:
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
    stats = _get_profile_stats(db, user_id, member_id=member_id)

    return render_template('profile_favorites.html',
                         user=user_dict,
                         favorites=enriched_favorites,
                         **stats,
                         active_tab='favorites')


@main_bp.route('/profile/notifications')
@login_required
def profile_notifications():
    """Redirect to standalone notifications page"""
    return redirect(url_for('main.notifications'))


@main_bp.route('/notifications')
@login_required
def notifications():
    """Standalone notifications page with sub-tabs and type filters"""
    user_id = session.get('user_id')
    if not user_id:
        flash('Please log in to view notifications.', 'warning')
        return redirect(url_for('main.login'))

    db = database.get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    user_dict = dict(user)
    user_dict['plex_member_since'] = user_dict.get('plex_joined_at') or user_dict.get('created_at')

    member_id = session.get('member_id')
    tab = request.args.get('tab', 'all')       # all, unread, read
    active_type = request.args.get('type', '')  # filter by notification type

    _notif_select = """
        SELECT
            n.id, n.user_id, n.show_id, COALESCE(n.notification_type, n.type) as notif_type,
            n.title, n.message, n.episode_id, n.season_number, n.episode_number,
            n.is_read, n.is_dismissed, n.created_at, n.read_at, n.issue_report_id, n.service_url,
            s.tmdb_id as show_tmdb_id, s.title as show_title
        FROM user_notifications n
        LEFT JOIN sonarr_shows s ON n.show_id = s.id
    """

    def _build_where(include_dismissed=False, extra=''):
        clause = "n.user_id = ?"
        params = [user_id]
        if member_id:
            clause += " AND (n.member_id = ? OR n.member_id IS NULL)"
            params.append(member_id)
        clause += f" AND n.is_dismissed = {1 if include_dismissed else 0}"
        if not include_dismissed:
            if tab == 'unread':
                clause += " AND n.is_read = 0"
            elif tab == 'read':
                clause += " AND n.is_read = 1"
        if active_type:
            clause += " AND COALESCE(n.notification_type, n.type) = ?"
            params.append(active_type)
        if extra:
            clause += f" {extra}"
        return clause, params

    where, params = _build_where()
    notifications_list = db.execute(
        _notif_select + f"WHERE {where} ORDER BY n.created_at DESC LIMIT 100",
        params
    ).fetchall()

    dismissed_where, dismissed_params = _build_where(include_dismissed=True)
    dismissed_notifications = db.execute(
        _notif_select + f"WHERE {dismissed_where} ORDER BY n.created_at DESC LIMIT 20",
        dismissed_params
    ).fetchall()

    # Distinct types for filter chips
    base_clause = "n.user_id = ? AND n.is_dismissed = 0"
    base_params = [user_id]
    if member_id:
        base_clause += " AND (n.member_id = ? OR n.member_id IS NULL)"
        base_params.append(member_id)
    type_counts = db.execute(
        f"""SELECT COALESCE(notification_type, type) as t, COUNT(*) as cnt
            FROM user_notifications n WHERE {base_clause}
            AND COALESCE(notification_type, type) IS NOT NULL
            GROUP BY t ORDER BY cnt DESC""",
        base_params
    ).fetchall()

    # Counts for sub-tabs
    unread_count = db.execute(
        f"SELECT COUNT(*) FROM user_notifications n WHERE {base_clause} AND n.is_read = 0",
        base_params
    ).fetchone()[0]
    read_count = db.execute(
        f"SELECT COUNT(*) FROM user_notifications n WHERE {base_clause} AND n.is_read = 1",
        base_params
    ).fetchone()[0]
    all_count = db.execute(
        f"SELECT COUNT(*) FROM user_notifications n WHERE {base_clause}",
        base_params
    ).fetchone()[0]

    stats = _get_profile_stats(db, user_id, member_id=member_id)

    return render_template('notifications.html',
                         user=user_dict,
                         notifications=notifications_list,
                         dismissed_notifications=dismissed_notifications,
                         type_counts=type_counts,
                         active_tab_filter=tab,
                         active_type_filter=active_type,
                         all_count=all_count,
                         unread_count_tab=unread_count,
                         read_count_tab=read_count,
                         **stats)


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
    
    member_id = session.get('member_id')

    if request.method == 'POST':
        # Add to favorites
        try:
            db.execute(
                'INSERT OR IGNORE INTO user_favorites (user_id, show_id, member_id) VALUES (?, ?, ?)',
                (user_id, show_id, member_id)
            )
            db.commit()
            return jsonify({'success': True, 'action': 'added'})
        except Exception as e:
            current_app.logger.error(f"Error adding favorite: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    elif request.method == 'DELETE':
        # Remove from favorites
        try:
            if member_id:
                db.execute(
                    'DELETE FROM user_favorites WHERE user_id = ? AND show_id = ? AND member_id = ?',
                    (user_id, show_id, member_id)
                )
            else:
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
    
    member_id = session.get('member_id')
    if member_id:
        favorite = db.execute(
            'SELECT id FROM user_favorites WHERE user_id = ? AND show_id = ? AND member_id = ? AND is_dropped = 0',
            (user_id, show_id, member_id)
        ).fetchone()
    else:
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
    member_id = session.get('member_id')
    if member_id:
        db.execute(
            'UPDATE user_notifications SET is_read = 1, read_at = CURRENT_TIMESTAMP WHERE user_id = ? AND member_id = ? AND is_read = 0',
            (user_id, member_id)
        )
    else:
        db.execute(
            'UPDATE user_notifications SET is_read = 1, read_at = CURRENT_TIMESTAMP WHERE user_id = ? AND is_read = 0',
            (user_id,)
        )
    db.commit()

    return jsonify({'success': True})


@main_bp.route('/api/profile/notification/<int:notification_id>/dismiss', methods=['POST'])
@login_required
def dismiss_notification(notification_id):
    """Dismiss a notification — hides from main list and badge, keeps in dismissed archive."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = database.get_db()

    notification = db.execute(
        'SELECT user_id FROM user_notifications WHERE id = ?', (notification_id,)
    ).fetchone()
    if not notification:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    if notification['user_id'] != user_id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    db.execute(
        'UPDATE user_notifications SET is_dismissed = 1, is_read = 1, read_at = COALESCE(read_at, CURRENT_TIMESTAMP) WHERE id = ?',
        (notification_id,)
    )
    db.commit()
    return jsonify({'success': True})


@main_bp.route('/api/profile/notification/<int:notification_id>/restore', methods=['POST'])
@login_required
def restore_notification(notification_id):
    """Restore a dismissed notification back to the active list."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    db = database.get_db()

    notification = db.execute(
        'SELECT user_id FROM user_notifications WHERE id = ?', (notification_id,)
    ).fetchone()
    if not notification:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    if notification['user_id'] != user_id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    db.execute(
        'UPDATE user_notifications SET is_dismissed = 0 WHERE id = ?',
        (notification_id,)
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
    user_dict['plex_member_since'] = user_dict.get('plex_joined_at') or user_dict.get('created_at')

    # Get profile statistics using helper function
    stats = _get_profile_stats(db, user_id, member_id=session.get('member_id'))

    # iCal feed URL paths — scheme/host added client-side via window.location.origin
    # so the URLs always match however the user is actually accessing the site (https).
    ical_token = user_dict.get('ical_token')
    ical_feed_bases = None
    if ical_token:
        ical_feed_bases = {
            'all':      url_for('main.calendar_ical_feed', token=ical_token, filter='all'),
            'premieres':url_for('main.calendar_ical_feed', token=ical_token, filter='premieres'),
            'series':   url_for('main.calendar_ical_feed', token=ical_token, filter='series'),
            'finales':  url_for('main.calendar_ical_feed', token=ical_token, filter='finales'),
            'movies':   url_for('main.calendar_ical_feed', token=ical_token, filter='movies'),
        }

    return render_template('profile_settings.html',
                         user=user_dict,
                         ical_token=ical_token,
                         ical_feed_bases=ical_feed_bases,
                         **stats,
                         active_tab='settings')

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
        allow_recommendations = request.form.get('allow_recommendations') == 'true'

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

        # Determine if the active member is a sub-profile (non-default)
        active_member_id = session.get('member_id')
        active_is_subprofile = False
        if active_member_id and photo_url:
            m = db.execute(
                'SELECT is_default FROM household_members WHERE id = ? AND user_id = ?',
                (active_member_id, user_id)
            ).fetchone()
            if m and not m['is_default']:
                active_is_subprofile = True

        # Always update bio/privacy on the user account
        db.execute('''
            UPDATE users
            SET bio = ?, profile_show_profile = ?, profile_show_lists = ?,
                profile_show_favorites = ?, profile_show_history = ?,
                profile_show_progress = ?, allow_recommendations = ?
            WHERE id = ?
        ''', (bio, profile_show_profile, profile_show_lists,
              profile_show_favorites, profile_show_history, profile_show_progress,
              allow_recommendations, user_id))

        # Handle photo: sub-profiles save to household_members.avatar_url only;
        # primary account saves to users.profile_photo_url and syncs default member row.
        if photo_url:
            if active_is_subprofile:
                db.execute(
                    'UPDATE household_members SET avatar_url = ? WHERE id = ?',
                    (photo_url, active_member_id)
                )
            else:
                db.execute(
                    'UPDATE users SET profile_photo_url = ? WHERE id = ?',
                    (photo_url, user_id)
                )
                db.execute(
                    'UPDATE household_members SET avatar_url = ? WHERE user_id = ? AND is_default = 1',
                    (photo_url, user_id)
                )

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

@main_bp.route('/api/profile/change-password', methods=['POST'])
@login_required
def change_password():
    """Change user's password (admin only)"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    db = database.get_db()

    try:
        data = request.get_json()
        current_password = data.get('current_password')
        new_password = data.get('new_password')

        # Validation
        if not current_password or not new_password:
            return jsonify({'success': False, 'error': 'Current and new password are required'}), 400

        if len(new_password) < 6:
            return jsonify({'success': False, 'error': 'New password must be at least 6 characters'}), 400

        # Get current user
        user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404

        # Verify user is admin
        if not user['is_admin']:
            return jsonify({'success': False, 'error': 'Only admin users can change passwords'}), 403

        # Verify current password
        if not user['password_hash'] or not check_password_hash(user['password_hash'], current_password):
            return jsonify({'success': False, 'error': 'Current password is incorrect'}), 400

        # Hash new password
        new_password_hash = generate_password_hash(new_password)

        # Update password
        db.execute('UPDATE users SET password_hash = ? WHERE id = ?', (new_password_hash, user_id))
        db.commit()

        current_app.logger.info(f"Password changed successfully for user {user['username']}")
        return jsonify({'success': True})

    except Exception as e:
        db.rollback()
        current_app.logger.error(f"Error changing password: {str(e)}")
        return jsonify({'success': False, 'error': 'An error occurred while changing password'}), 500

# ========================================
# RECOMMENDATIONS
# ========================================

