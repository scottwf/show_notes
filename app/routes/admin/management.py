import os
import glob
import time
import secrets
import socket
import requests
from openai import OpenAI
from flask import (
    render_template, request, redirect, url_for, session, jsonify, flash,
    current_app, Response, stream_with_context, abort
)
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from functools import wraps

from ... import database
from ...database import get_db, close_db, get_setting, set_setting, update_sync_status
from ...utils import (
    sync_sonarr_library, sync_radarr_library,
    test_sonarr_connection, test_radarr_connection, test_bazarr_connection, test_ollama_connection,
    test_sonarr_connection_with_params, test_radarr_connection_with_params,
    test_bazarr_connection_with_params, test_ollama_connection_with_params,
    test_pushover_notification_with_params,
    send_ntfy_notification,
    sync_tautulli_watch_history,
    test_tautulli_connection, test_tautulli_connection_with_params,
    test_jellyseer_connection, test_jellyseer_connection_with_params,
    test_thetvdb_connection, test_thetvdb_connection_with_params,
    get_ollama_models,
    convert_utc_to_user_timezone, get_user_timezone,
    get_jellyseer_user_requests,
)
from ...parse_subtitles import process_all_subtitles
from . import admin_bp, admin_required, ADMIN_SEARCHABLE_ROUTES

@admin_bp.route('/users')
@login_required
@admin_required
def admin_users():
    """Admin users overview page showing activity, issues, favorites, and Jellyseerr requests per user."""
    import time
    t0 = time.monotonic()
    db = database.get_db()

    users = db.execute('''
        SELECT id, username, plex_username, plex_user_id, is_admin, is_active,
               last_login_at, profile_photo_url,
               profile_show_profile, profile_show_lists, profile_show_favorites,
               profile_show_history, profile_show_progress, allow_recommendations
        FROM users ORDER BY last_login_at DESC
    ''').fetchall()
    current_app.logger.debug(f"admin_users: users query {(time.monotonic()-t0)*1000:.0f}ms")

    # Single query for last watched per user using window function (replaces N+1)
    t1 = time.monotonic()
    last_watched = {r['plex_username']: r for r in db.execute('''
        SELECT plex_username, title, show_title, season_episode, media_type, event_timestamp
        FROM (
            SELECT plex_username, title, show_title, season_episode, media_type, event_timestamp,
                   ROW_NUMBER() OVER (PARTITION BY plex_username ORDER BY event_timestamp DESC) as rn
            FROM plex_activity_log
            WHERE event_type IN ('media.stop', 'media.scrobble', 'watched')
              AND plex_username IS NOT NULL
        ) WHERE rn = 1
    ''').fetchall()}
    current_app.logger.debug(f"admin_users: last_watched query {(time.monotonic()-t1)*1000:.0f}ms")

    t2 = time.monotonic()
    watch_counts = {r['plex_username']: r['cnt'] for r in db.execute('''
        SELECT plex_username, COUNT(*) as cnt FROM plex_activity_log
        WHERE event_type IN ('media.scrobble', 'watched') AND plex_username IS NOT NULL
        GROUP BY plex_username
    ''').fetchall()}

    issue_counts = {r['user_id']: r['cnt'] for r in db.execute('''
        SELECT user_id, COUNT(*) as cnt FROM issue_reports
        WHERE status != 'resolved' GROUP BY user_id
    ''').fetchall()}

    problem_counts = {r['user_id']: r['cnt'] for r in db.execute('''
        SELECT user_id, COUNT(*) as cnt FROM problem_reports
        WHERE status != 'resolved' GROUP BY user_id
    ''').fetchall()}

    fav_counts = {r['user_id']: r['cnt'] for r in db.execute('''
        SELECT user_id, COUNT(*) as cnt FROM user_favorites
        WHERE is_dropped = 0 GROUP BY user_id
    ''').fetchall()}

    # Household sub-profiles (non-default members) grouped by user_id
    hm_rows = db.execute('''
        SELECT id, user_id, display_name, avatar_color, avatar_url, last_active_at
        FROM household_members WHERE is_default = 0
        ORDER BY user_id, created_at
    ''').fetchall()
    members_by_user = {}
    for m in hm_rows:
        members_by_user.setdefault(m['user_id'], []).append(dict(m))

    member_fav_counts = {r['member_id']: r['cnt'] for r in db.execute('''
        SELECT member_id, COUNT(*) as cnt FROM user_favorites
        WHERE is_dropped = 0 AND member_id IS NOT NULL
        GROUP BY member_id
    ''').fetchall()}
    current_app.logger.debug(f"admin_users: aggregate queries {(time.monotonic()-t2)*1000:.0f}ms")

    t3 = time.monotonic()
    from ..utils import get_jellyseer_user_requests
    jellyseer_counts = get_jellyseer_user_requests()
    current_app.logger.debug(f"admin_users: jellyseerr {(time.monotonic()-t3)*1000:.0f}ms")

    current_app.logger.debug(f"admin_users: total {(time.monotonic()-t0)*1000:.0f}ms")

    return render_template('admin_users.html',
        users=users,
        last_watched=last_watched,
        watch_counts=watch_counts,
        issue_counts=issue_counts,
        problem_counts=problem_counts,
        fav_counts=fav_counts,
        jellyseer_counts=jellyseer_counts,
        members_by_user=members_by_user,
        member_fav_counts=member_fav_counts,
    )


@admin_bp.route('/api/users/<int:user_id>/permissions', methods=['POST'])
@login_required
@admin_required
def update_user_permissions(user_id):
    """Update a user's admin status and privacy/permission settings."""
    db = database.get_db()
    user = db.execute('SELECT id FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    data = request.json or {}
    db.execute('''
        UPDATE users SET
            is_admin = ?,
            is_active = ?,
            profile_show_profile = ?,
            profile_show_lists = ?,
            profile_show_favorites = ?,
            profile_show_history = ?,
            profile_show_progress = ?,
            allow_recommendations = ?
        WHERE id = ?
    ''', (
        1 if data.get('is_admin') else 0,
        1 if data.get('is_active') else 0,
        1 if data.get('profile_show_profile') else 0,
        1 if data.get('profile_show_lists') else 0,
        1 if data.get('profile_show_favorites') else 0,
        1 if data.get('profile_show_history') else 0,
        1 if data.get('profile_show_progress') else 0,
        1 if data.get('allow_recommendations') else 0,
        user_id,
    ))
    db.commit()
    return jsonify({'success': True})


@admin_bp.route('/api/import-plex-users', methods=['POST'])
@login_required
@admin_required
def import_plex_users():
    """Fetch all Plex users (home/managed + friends) and create inactive accounts for any not registered."""
    import requests as _requests
    db = database.get_db()

    admin_row = db.execute(
        'SELECT plex_token FROM users WHERE is_admin = 1 AND plex_token IS NOT NULL ORDER BY id LIMIT 1'
    ).fetchone()
    if not admin_row:
        return jsonify({'success': False, 'error': 'No admin Plex token found. Log in via Plex first.'}), 400

    from ..database import get_setting
    client_id = get_setting('plex_client_id') or 'shownotes'
    headers = {
        'X-Plex-Token': admin_row['plex_token'],
        'X-Plex-Client-Identifier': client_id,
        'Accept': 'application/json',
    }

    # Collect from all sources, deduplicated by plex_id
    candidates = {}  # plex_id -> user dict

    def _collect(url, extract):
        """Fetch a Plex endpoint and merge results into candidates."""
        try:
            resp = _requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            for pu in extract(resp):
                pid = str(pu.get('id', ''))
                if pid and pid not in candidates:
                    candidates[pid] = pu
        except Exception as e:
            current_app.logger.warning(f'Plex import: {url} failed — {e}')

    # 1. Plex Home managed users
    _collect('https://plex.tv/api/v2/home/users',
             lambda r: r.json().get('users', []))

    # 2. Plex friends (shared-server users)
    _collect('https://plex.tv/api/v2/friends',
             lambda r: r.json() if isinstance(r.json(), list) else r.json().get('friends', []))

    if not candidates:
        return jsonify({'success': False, 'error': 'No users returned from Plex. Check your token.'}), 502

    imported, skipped = [], []
    for plex_id, pu in candidates.items():
        if db.execute('SELECT id FROM users WHERE plex_user_id = ?', (plex_id,)).fetchone():
            skipped.append(pu.get('title') or pu.get('username') or plex_id)
            continue

        base = (pu.get('title') or pu.get('username') or f'user_{plex_id}').strip()
        username = base
        n = 1
        while db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone():
            username = f'{base}_{n}'
            n += 1

        db.execute('''
            INSERT INTO users (username, plex_user_id, plex_username, email, is_active, joined_at)
            VALUES (?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
        ''', (username, plex_id, pu.get('username') or base, pu.get('email') or ''))
        imported.append(username)

    db.commit()
    return jsonify({'success': True, 'imported': imported, 'skipped': skipped,
                    'sources': {'home_users': True, 'friends': True}})


@admin_bp.route('/issue-reports')
@login_required
@admin_required
def issue_reports():
    db = get_db()
    rows = db.execute('SELECT * FROM issue_reports ORDER BY created_at DESC').fetchall()
    return render_template('admin_issue_reports.html', reports=[dict(r) for r in rows])


@admin_bp.route('/issue-reports/<int:report_id>/resolve', methods=['POST'])
@login_required
@admin_required
def resolve_issue_report(report_id):
    db = get_db()

    # Get issue report details before resolving
    report = db.execute(
        'SELECT user_id, title, show_id, issue_type FROM issue_reports WHERE id = ?',
        (report_id,)
    ).fetchone()

    if not report:
        flash('Report not found.', 'error')
        return redirect(url_for('admin.issue_reports'))

    # Resolve the report
    notes = request.form.get('resolution_notes', '')
    db.execute(
        "UPDATE issue_reports SET status='resolved', resolved_by_admin_id=?, resolved_at=CURRENT_TIMESTAMP, resolution_notes=? WHERE id=?",
        (current_user.id, notes, report_id)
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

    flash('Report resolved.', 'success')
    return redirect(url_for('admin.issue_reports'))


@admin_bp.route('/announcements')
@login_required
@admin_required
def announcements():
    """Admin page for managing announcements"""
    return render_template('admin_announcements.html')

@admin_bp.route('/api/announcements', methods=['GET'])
@login_required
@admin_required
def api_get_announcements():
    """Get all announcements"""
    try:
        db = get_db()
        announcements = db.execute('''
            SELECT id, title, message, type, is_active, start_date, end_date, created_at, updated_at
            FROM announcements
            ORDER BY created_at DESC
        ''').fetchall()

        return jsonify({
            'success': True,
            'announcements': [dict(a) for a in announcements]
        })

    except Exception as e:
        current_app.logger.error(f"Error fetching announcements: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@admin_bp.route('/api/announcements', methods=['POST'])
@login_required
@admin_required
def api_create_announcement():
    """Create a new announcement"""
    db = None
    try:
        data = request.get_json()
        current_app.logger.info(f"Announcement creation request data: {data}")

        if not data:
            current_app.logger.error("No data provided in announcement creation request")
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400

        title = data.get('title', '').strip()
        message = data.get('message', '').strip()
        type_ = data.get('type', 'info')
        is_active = 1 if data.get('is_active', True) else 0  # Convert to int for SQLite
        start_date = data.get('start_date') or None  # Convert empty string to None
        end_date = data.get('end_date') or None  # Convert empty string to None

        current_app.logger.info(f"Processed values - title: '{title}', message: '{message}', type: '{type_}', is_active: {is_active}, start_date: {start_date}, end_date: {end_date}")

        if not title or not message:
            current_app.logger.error(f"Missing required fields - title: '{title}', message: '{message}'")
            return jsonify({
                'success': False,
                'error': 'Title and message are required'
            }), 400

        db = get_db()
        user_id = session.get('user_id')
        current_app.logger.info(f"Creating announcement for user_id: {user_id}")

        cur = db.execute('''
            INSERT INTO announcements (title, message, type, is_active, start_date, end_date, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (title, message, type_, is_active, start_date, end_date, user_id))

        db.commit()
        current_app.logger.info(f"Announcement created successfully with id: {cur.lastrowid}")

        return jsonify({
            'success': True,
            'id': cur.lastrowid
        })

    except Exception as e:
        if db:
            db.rollback()
        current_app.logger.error(f"Error creating announcement: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@admin_bp.route('/api/announcements/<int:announcement_id>', methods=['PATCH'])
@login_required
@admin_required
def api_update_announcement(announcement_id):
    """Update an announcement"""
    db = None
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400

        title = data.get('title', '').strip()
        message = data.get('message', '').strip()
        type_ = data.get('type', 'info')
        is_active = 1 if data.get('is_active', True) else 0  # Convert to int for SQLite
        start_date = data.get('start_date') or None  # Convert empty string to None
        end_date = data.get('end_date') or None  # Convert empty string to None

        if not title or not message:
            return jsonify({
                'success': False,
                'error': 'Title and message are required'
            }), 400

        db = get_db()

        db.execute('''
            UPDATE announcements
            SET title = ?, message = ?, type = ?, is_active = ?,
                start_date = ?, end_date = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (title, message, type_, is_active, start_date, end_date, announcement_id))

        db.commit()

        return jsonify({'success': True})

    except Exception as e:
        if db:
            db.rollback()
        current_app.logger.error(f"Error updating announcement: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@admin_bp.route('/api/announcements/<int:announcement_id>', methods=['DELETE'])
@login_required
@admin_required
def api_delete_announcement(announcement_id):
    """Delete an announcement"""
    try:
        db = get_db()
        db.execute('DELETE FROM announcements WHERE id = ?', (announcement_id,))
        db.commit()

        return jsonify({'success': True})

    except Exception as e:
        db.rollback()
        current_app.logger.error(f"Error deleting announcement: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ========================================
# PROBLEM REPORTS
# ========================================

@admin_bp.route('/problem-reports')
@login_required
@admin_required
def problem_reports():
    """Admin page for managing problem reports"""
    return render_template('admin_problem_reports.html')

@admin_bp.route('/api/admin/problem-reports', methods=['GET'])
@login_required
@admin_required
def api_get_problem_reports():
    """Get all problem reports with optional status filter"""
    try:
        db = get_db()
        status = request.args.get('status')

        if status and status != 'all':
            reports = db.execute('''
                SELECT pr.*, u.username,
                       s.title as show_title,
                       m.title as movie_title,
                       e.title as episode_title
                FROM problem_reports pr
                JOIN users u ON pr.user_id = u.id
                LEFT JOIN sonarr_shows s ON pr.show_id = s.id
                LEFT JOIN radarr_movies m ON pr.movie_id = m.id
                LEFT JOIN sonarr_episodes e ON pr.episode_id = e.id
                WHERE pr.status = ?
                ORDER BY pr.created_at DESC
            ''', (status,)).fetchall()
        else:
            reports = db.execute('''
                SELECT pr.*, u.username,
                       s.title as show_title,
                       m.title as movie_title,
                       e.title as episode_title
                FROM problem_reports pr
                JOIN users u ON pr.user_id = u.id
                LEFT JOIN sonarr_shows s ON pr.show_id = s.id
                LEFT JOIN radarr_movies m ON pr.movie_id = m.id
                LEFT JOIN sonarr_episodes e ON pr.episode_id = e.id
                ORDER BY pr.created_at DESC
            ''').fetchall()

        # Get user's timezone for client-side formatting
        user_timezone = get_user_timezone()

        return jsonify({
            'success': True,
            'reports': [dict(r) for r in reports],
            'timezone': user_timezone
        })

    except Exception as e:
        current_app.logger.error(f"Error fetching problem reports: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@admin_bp.route('/api/admin/problem-reports/<int:report_id>', methods=['PATCH'])
@login_required
@admin_required
def api_update_problem_report(report_id):
    """Update a problem report"""
    try:
        data = request.get_json()

        status = data.get('status')
        priority = data.get('priority')
        admin_notes = data.get('admin_notes', '').strip()

        db = get_db()
        user_id = session.get('user_id')

        # If marking as resolved, set resolved_by and resolved_at
        if status == 'resolved':
            db.execute('''
                UPDATE problem_reports
                SET status = ?, priority = ?, admin_notes = ?,
                    resolved_by = ?, resolved_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (status, priority, admin_notes, user_id, report_id))
        else:
            db.execute('''
                UPDATE problem_reports
                SET status = ?, priority = ?, admin_notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (status, priority, admin_notes, report_id))

        db.commit()

        return jsonify({'success': True})

    except Exception as e:
        db.rollback()
        current_app.logger.error(f"Error updating problem report: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# AI / LLM MANAGEMENT
# ============================================================================

