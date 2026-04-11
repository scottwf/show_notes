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
        # Get only current user's lists (public and private), scoped to member if set
        _list_member_id = session.get('member_id')
        if _list_member_id:
            lists = db.execute('''
                SELECT l.id, l.name, l.description, l.item_count, l.is_public,
                       l.created_at, l.updated_at, l.user_id,
                       u.username as owner_username
                FROM user_lists l
                JOIN users u ON l.user_id = u.id
                WHERE l.user_id = ? AND l.member_id = ?
                ORDER BY l.updated_at DESC
            ''', (user_id, _list_member_id)).fetchall()
        else:
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

    member_id = session.get('member_id')

    try:
        cur = db.execute('''
            INSERT INTO user_lists (user_id, member_id, name, description, is_public)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, member_id, name, description, is_public))
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
    stats = _get_profile_stats(db, user_id, member_id=session.get('member_id'))

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
    stats = _get_profile_stats(db, user_id, member_id=session.get('member_id'))

    return render_template('profile_list_detail.html',
                         user=user_dict,
                         list=lst,
                         **stats,
                         active_tab='lists')


# ============================================================================
# Watch Progress Helper Functions
# ============================================================================

@main_bp.route('/api/profile/progress/shows', methods=['GET'])
@login_required
def api_get_progress_shows():
    """Get shows with progress filtered by status"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    status = request.args.get('status', 'watching')  # watching|completed|dropped|plan_to_watch|favourites|all
    member_id = session.get('member_id')

    db = database.get_db()

    # Derive status from data since status column is often NULL
    # dropped = last watched > 90 days ago and not completed
    # watching = last watched within 90 days and not completed
    # completed = completion >= 95%
    cte = '''
        WITH progress AS (
            SELECT
                usp.id, usp.show_id, usp.watched_episodes, usp.total_episodes,
                usp.completion_percentage, usp.last_watched_at,
                s.title, s.poster_url AS poster_path, s.tmdb_id, s.year,
                CASE
                    WHEN usp.completion_percentage >= 95
                         OR (usp.total_episodes > 0 AND usp.watched_episodes >= usp.total_episodes)
                        THEN 'completed'
                    WHEN usp.last_watched_at IS NOT NULL
                         AND (julianday('now') - julianday(usp.last_watched_at)) <= 90
                        THEN 'watching'
                    WHEN usp.last_watched_at IS NOT NULL
                        THEN 'dropped'
                    ELSE 'plan_to_watch'
                END AS derived_status,
                CASE WHEN uf.id IS NOT NULL THEN 1 ELSE 0 END AS is_favourite
            FROM user_show_progress usp
            JOIN sonarr_shows s ON usp.show_id = s.id
            LEFT JOIN user_favorites uf
                ON uf.show_id = usp.show_id
               AND uf.user_id = usp.user_id
               AND uf.media_type = 'show'
            WHERE usp.user_id = ? AND usp.watched_episodes > 0
        )
    '''
    params = [user_id]

    if status == 'favourites':
        query = cte + "SELECT * FROM progress WHERE is_favourite = 1 ORDER BY last_watched_at DESC"
    elif status == 'all':
        query = cte + "SELECT * FROM progress ORDER BY last_watched_at DESC"
    else:
        query = cte + "SELECT * FROM progress WHERE derived_status = ? ORDER BY last_watched_at DESC"
        params.append(status)

    shows = db.execute(query, params).fetchall()

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
            'status': show['derived_status'],
            'last_watched_at': show['last_watched_at'],
            'is_favourite': bool(show['is_favourite'])
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
    stats = _get_profile_stats(db, user_id, member_id=session.get('member_id'))

    return render_template('profile_progress.html',
                         user=user_dict,
                         **stats,
                         active_tab='progress')

