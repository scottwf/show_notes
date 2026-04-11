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

@admin_bp.route('/logs', methods=['GET'])
@login_required
@admin_required
def logs_view():
    """
    Displays the log viewer page.

    Allows admins to view application logs, select log files, and stream live logs.
    """
    default_tab = request.args.get('tab', 'files')
    if default_tab not in {'files', 'events'}:
        default_tab = 'files'
    return render_template('admin_logs.html', title='View Logs', default_tab=default_tab)

@admin_bp.route('/watch-history')
@login_required
@admin_required
def watch_history_view():
    """
    Renders the watch history page.

    The watch history provides a view of Plex watch activity with filtering
    by user, show, media type, and date range. The data for this page is
    fetched dynamically via the `/watch-history/data` endpoint.

    Returns:
        A rendered HTML template for the watch history.
    """
    return render_template('admin_watch_history.html')

@admin_bp.route('/watch-history/users')
@login_required
@admin_required
def watch_history_users():
    """Get list of unique Plex usernames for filter dropdown."""
    db = database.get_db()
    users = db.execute('''
        SELECT DISTINCT plex_username
        FROM plex_activity_log
        WHERE plex_username IS NOT NULL
        ORDER BY LOWER(plex_username) COLLATE NOCASE
    ''').fetchall()
    return jsonify({'users': [u['plex_username'] for u in users]})

@admin_bp.route('/watch-history/data')
@login_required
@admin_required
def watch_history_data():
    """
    Provides data for the watch history page.

    Fetches Plex activity logs based on query parameters for user, show,
    media type, and date range. Enriches logs with formatted timestamps
    and detail URLs.

    Query Params:
        user (str, optional): Filters Plex logs by username.
        show (str, optional): Filters Plex logs by show title.
        media_type (str, optional): Filters by media type ('episode', 'movie').
        days (int, optional): Filters by number of days back.

    Returns:
        flask.Response: JSON response containing list of plex_logs.
    """
    category = request.args.get('category')
    user = request.args.get('user')
    show = request.args.get('show')
    media_type = request.args.get('media_type')
    days = request.args.get('days')
    db = database.get_db()
    sync_logs = []
    plex_logs = []

    # Plex Activity logs - deduplicated to show only most recent entry per unique item
    if not category or category in ['plex', 'all']:
        # Build WHERE conditions
        where_conditions = []
        params = []

        # Filter by user
        if user:
            where_conditions.append('plex_username = ?')
            params.append(user)

        # Filter by show title
        if show:
            where_conditions.append('(title LIKE ? OR show_title LIKE ?)')
            params.extend([f'%{show}%']*2)

        # Filter by media type
        if media_type:
            where_conditions.append('media_type = ?')
            params.append(media_type)

        # Filter by date range
        if days:
            where_conditions.append('event_timestamp >= datetime("now", "-" || ? || " days")')
            params.append(int(days))

        where_clause = ' AND '.join(where_conditions) if where_conditions else '1=1'

        # Use CTE with ROW_NUMBER to deduplicate entries
        # Partition by user + show + episode to get one entry per unique watched item per user
        query = f'''
            WITH ranked_events AS (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY
                            plex_username,
                            CASE
                                WHEN media_type = 'episode' THEN show_title || '-' || season_episode
                                WHEN media_type = 'movie' THEN 'movie-' || COALESCE(tmdb_id, title)
                                ELSE title
                            END
                        ORDER BY event_timestamp DESC
                    ) as rn
                FROM plex_activity_log
                WHERE {where_clause}
            )
            SELECT * FROM ranked_events
            WHERE rn = 1
            ORDER BY event_timestamp DESC
            LIMIT 100
        '''
        rows = db.execute(query, params).fetchall()

        # PERFORMANCE OPTIMIZATION: Batch lookup TMDB IDs instead of querying in loop
        # Collect all unique show titles and movie titles that need lookup
        import re
        show_titles_to_lookup = set()
        movie_titles_to_lookup = set()

        for row in rows:
            if not row['tmdb_id']:
                if row['media_type'] == 'episode' and row['show_title']:
                    show_titles_to_lookup.add(row['show_title'])
                elif row['media_type'] == 'movie' and row['title']:
                    movie_titles_to_lookup.add(row['title'])

        # Batch fetch show TMDB IDs (single query instead of N queries)
        show_tmdb_map = {}
        if show_titles_to_lookup:
            placeholders = ','.join('?' * len(show_titles_to_lookup))
            show_results = db.execute(
                f'SELECT title, tmdb_id FROM sonarr_shows WHERE title IN ({placeholders})',
                list(show_titles_to_lookup)
            ).fetchall()
            show_tmdb_map = {r['title']: r['tmdb_id'] for r in show_results}

        # Batch fetch movie TMDB IDs (single query instead of N queries)
        movie_tmdb_map = {}
        if movie_titles_to_lookup:
            placeholders = ','.join('?' * len(movie_titles_to_lookup))
            movie_results = db.execute(
                f'SELECT title, tmdb_id FROM radarr_movies WHERE title IN ({placeholders})',
                list(movie_titles_to_lookup)
            ).fetchall()
            movie_tmdb_map = {r['title']: r['tmdb_id'] for r in movie_results}

        # Event type display mapping
        event_type_map = {
            'media.play': 'Play',
            'media.pause': 'Pause',
            'media.stop': 'Stop',
            'media.scrobble': 'Scrobble'
        }

        # Enrich with episode detail URL and formatted time
        for row in rows:
            row_dict = dict(row)

            # Get TMDB ID - either from row or from batch lookup
            tmdb_id = row_dict.get('tmdb_id')
            show_title = row_dict.get('show_title')
            title = row_dict.get('title')
            media_type = row_dict.get('media_type')

            # Use batch lookup results if no tmdb_id
            if not tmdb_id:
                if media_type == 'episode' and show_title:
                    tmdb_id = show_tmdb_map.get(show_title)
                    if tmdb_id:
                        row_dict['tmdb_id'] = tmdb_id
                elif media_type == 'movie' and title:
                    tmdb_id = movie_tmdb_map.get(title)
                    if tmdb_id:
                        row_dict['tmdb_id'] = tmdb_id

            # Build URLs based on media type
            season_episode = row_dict.get('season_episode')
            episode_detail_url = None
            show_detail_url = None
            movie_detail_url = None

            if media_type == 'episode' and tmdb_id:
                # Link to show detail page
                show_detail_url = url_for('main.show_detail', tmdb_id=tmdb_id)

                # If we have season/episode info, link to episode detail
                if season_episode:
                    match = re.match(r'S(\d+)E(\d+)', season_episode)
                    if match:
                        season_number = int(match.group(1))
                        episode_number = int(match.group(2))
                        episode_detail_url = url_for('main.episode_detail', tmdb_id=tmdb_id, season_number=season_number, episode_number=episode_number)
            elif media_type == 'movie' and tmdb_id:
                # Link to movie detail page
                movie_detail_url = url_for('main.movie_detail', tmdb_id=tmdb_id)

            row_dict['episode_detail_url'] = episode_detail_url
            row_dict['show_detail_url'] = show_detail_url
            row_dict['movie_detail_url'] = movie_detail_url

            # Format timestamp with user's timezone
            ts = row_dict.get('event_timestamp')
            if ts:
                try:
                    row_dict['event_timestamp_fmt'] = convert_utc_to_user_timezone(ts, '%Y-%m-%d %H:%M')
                except Exception:
                    row_dict['event_timestamp_fmt'] = str(ts)

            # Format event type
            event_type = row_dict.get('event_type')
            if event_type:
                row_dict['event_type_fmt'] = event_type_map.get(event_type, event_type)

            # Build display title
            episode_title = row_dict.get('title')
            row_dict['display_title'] = f'{show_title} – {episode_title}' if show_title else episode_title

            plex_logs.append(row_dict)

    return jsonify({'sync_logs': sync_logs, 'plex_logs': plex_logs})


@admin_bp.route('/logs/list', methods=['GET'])
@login_required
@admin_required
def logs_list():
    """
    Provides a list of available log files.

    This API endpoint scans the log directory for files matching the pattern
    'shownotes.log*' and returns their filenames as a JSON list. This is used
    by the log viewer to populate the log file selection dropdown.

    Returns:
        flask.Response: A JSON response containing a sorted list of log filenames.
    """
    log_dir = os.path.join(os.path.dirname(current_app.root_path), 'logs')
    log_files_paths = glob.glob(os.path.join(log_dir, 'shownotes.log*'))
    log_filenames = sorted([os.path.basename(f) for f in log_files_paths])
    return jsonify(log_filenames)

@admin_bp.route('/logs/get/<path:filename>', methods=['GET'])
@login_required
@admin_required
def get_log_content(filename):
    """
    Retrieves the content of a specified log file.

    This API endpoint reads the last 100 lines of a given log file and returns
    them as a JSON list. It includes a security check to prevent path traversal
    attacks.

    Args:
        filename (str): The name of the log file to be read, captured from the URL path.

    Returns:
        flask.Response: A JSON response containing a list of log lines, or an
                        error response if the file is not found or access is denied.
    """
    log_dir = os.path.join(os.path.dirname(current_app.root_path), 'logs')
    file_path = os.path.join(log_dir, filename)

    # Security check to prevent path traversal
    if not os.path.abspath(file_path).startswith(os.path.abspath(log_dir)):
        current_app.logger.warning(f"Log access rejected for {filename} due to path traversal attempt.")
        return jsonify({"error": "Access denied"}), 403

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines() # Read all lines
        return jsonify(lines[-100:]) # Return last 100 lines
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404
    except Exception as e:
        current_app.logger.error(f"Error reading log file {filename}: {e}")
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/logs/stream/<path:filename>', methods=['GET'])
@login_required
@admin_required
def stream_log_content(filename):
    """
    Streams the content of a log file in real-time using Server-Sent Events (SSE).

    This endpoint opens a specified log file and continuously sends any new lines
    to the client. This allows for a "live tail" feature in the log viewer UI.
    It includes a security check to prevent path traversal.

    Args:
        filename (str): The name of the log file to stream, from the URL path.

    Returns:
        flask.Response: An SSE stream that pushes log lines to the client.
    """
    log_dir = os.path.join(os.path.dirname(current_app.root_path), 'logs')
    file_path = os.path.join(log_dir, filename)

    # Security check
    if not os.path.abspath(file_path).startswith(os.path.abspath(log_dir)):
        return Response("data: ERROR: Access Denied\n\n", mimetype='text/event-stream', status=403)

    if not os.path.exists(file_path):
        return Response("data: ERROR: File Not Found\n\n", mimetype='text/event-stream', status=404)

    def generate_log_updates(file_path_stream):
        """Generator function to yield new log lines."""
        try:
            with open(file_path_stream, 'r', encoding='utf-8') as f:
                f.seek(0, os.SEEK_END)
                while True:
                    line = f.readline()
                    if not line:
                        time.sleep(0.5)
                        continue
                    yield f"data: {line.rstrip()}\n\n"
        except Exception as e:
            current_app.logger.error(f"Error streaming log file {file_path_stream}: {e}")
            yield f"data: ERROR: Could not stream log: {str(e)}\n\n"

    return Response(stream_with_context(generate_log_updates(file_path)), mimetype='text/event-stream')

# ============================================================================
# SETTINGS MANAGEMENT
# ============================================================================

@admin_bp.route('/plex_webhook_payloads', methods=['GET'])
@login_required
@admin_required
def plex_webhook_payloads():
    db = get_db()
    rows = db.execute('SELECT id, event_type, event_timestamp, raw_payload FROM plex_activity_log ORDER BY event_timestamp DESC LIMIT 20').fetchall()
    payloads = []
    import json
    for row in rows:
        try:
            payload = json.loads(row['raw_payload']) if row['raw_payload'] else {}
        except Exception:
            payload = row['raw_payload']
        payloads.append({
            'id': row['id'],
            'event_type': row['event_type'],
            'event_timestamp': row['event_timestamp'],
            'payload': payload
        })
    return render_template('admin_plex_webhook_payloads.html', payloads=payloads)


@admin_bp.route('/event-logs')
@login_required
@admin_required
def event_logs():
    """Legacy event logs page now redirects to merged logs view."""
    return redirect(url_for('admin.logs_view', tab='events'))


@admin_bp.route('/api/event-logs', methods=['GET'])
@login_required
@admin_required
def api_event_logs():
    """API endpoint to fetch event logs with filtering and pagination"""
    from app.system_logger import SystemLogger

    try:
        # Get query parameters
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 50))
        level = request.args.get('level', None)
        component = request.args.get('component', None)
        search = request.args.get('search', None)

        # Calculate offset
        offset = (page - 1) * per_page

        # Get logs
        logs = SystemLogger.get_logs(
            limit=per_page,
            offset=offset,
            level=level,
            component=component,
            search=search
        )

        # Get total count
        total_count = SystemLogger.get_log_count(
            level=level,
            component=component,
            search=search
        )

        # Get user's timezone for client-side formatting
        user_timezone = get_user_timezone()

        return jsonify({
            'success': True,
            'logs': logs,
            'total': total_count,
            'page': page,
            'per_page': per_page,
            'total_pages': (total_count + per_page - 1) // per_page,
            'timezone': user_timezone
        })

    except Exception as e:
        current_app.logger.error(f"Error fetching event logs: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin_bp.route('/api/event-logs/<int:log_id>', methods=['GET'])
@login_required
@admin_required
def api_event_log_detail(log_id):
    """API endpoint to get full details of a specific log entry"""
    try:
        db = get_db()
        log = db.execute('SELECT * FROM system_logs WHERE id = ?', (log_id,)).fetchone()

        if not log:
            return jsonify({
                'success': False,
                'error': 'Log entry not found'
            }), 404

        return jsonify({
            'success': True,
            'log': dict(log)
        })

    except Exception as e:
        current_app.logger.error(f"Error fetching log detail: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ========================================
# ANNOUNCEMENTS
# ========================================

