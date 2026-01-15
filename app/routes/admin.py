"""
Admin Blueprint for ShowNotes

This module defines the blueprint for the administrative interface of the ShowNotes
application. It includes routes for all admin-facing pages and functionalities,
such as the dashboard, settings management, task execution, and log viewing.

All routes in this blueprint are prefixed with `/admin` and require the user to be
logged in and have administrative privileges, enforced by the `@admin_required`
decorator.

ORGANIZATION:
This file is organized into logical sections for better maintainability:
- DECORATORS & UTILITIES: Shared decorators and constants
- DASHBOARD & SEARCH: Main dashboard and search functionality  
- SETTINGS MANAGEMENT: Service configuration and connection testing
- TASK EXECUTION: Background task triggers (sync, parsing, etc.)
- LOG MANAGEMENT: Log viewing, streaming, and logbook functionality
- LLM TOOLS: LLM testing and prompt management
- API USAGE: API usage tracking and monitoring

Key Features:
- **Dashboard:** A summary page with key statistics about the application's data.
- **Settings:** A page for configuring connections to external services like
  Sonarr, Radarr, and LLM providers.
- **Tasks:** A UI for manually triggering long-running tasks like library syncs.
- **Log Management:** Tools for viewing and streaming application logs.
- **LLM Tools:** Pages for testing LLM summaries and viewing prompt templates.
- **API Endpoints:** Various API endpoints to support the dynamic functionality
  of the admin interface, such as search and connection testing.
"""
import os
import glob
import time
import secrets
import socket
from flask import (
    Blueprint, render_template, request, redirect, url_for, session, jsonify, flash,
    current_app, Response, stream_with_context, abort
)
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from functools import wraps

from .. import database
from ..database import get_db, close_db, get_setting, set_setting, update_sync_status
from ..utils import (
    sync_sonarr_library, sync_radarr_library,
    test_sonarr_connection, test_radarr_connection, test_bazarr_connection, test_ollama_connection,
    test_sonarr_connection_with_params, test_radarr_connection_with_params,
    test_bazarr_connection_with_params, test_ollama_connection_with_params,
    test_pushover_notification_with_params,
    sync_tautulli_watch_history,
    test_tautulli_connection, test_tautulli_connection_with_params,
    test_jellyseer_connection, test_jellyseer_connection_with_params,
    get_ollama_models,
    convert_utc_to_user_timezone, get_user_timezone
)
from ..parse_subtitles import process_all_subtitles

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# ============================================================================
# DECORATORS & UTILITIES
# ============================================================================

def admin_required(f):
    """
    Decorator to ensure that a route is accessed by an authenticated admin user.

    If the user is not authenticated or is not an admin, it logs a warning,
    flashes an error message, and aborts the request with a 403 Forbidden status.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, 'is_admin', False):
            current_app.logger.warning(f"Admin access denied for user {current_user.username if current_user.is_authenticated else 'Anonymous'} to {request.endpoint}")
            flash('You must be an administrator to access this page.', 'danger')
            abort(403) # Forbidden
        return f(*args, **kwargs)
    return decorated_function

# List of admin panel routes that are searchable via the admin search bar.
# Each entry contains a user-friendly title, a category for grouping,
# and a lambda function to generate the URL dynamically using url_for.
ADMIN_SEARCHABLE_ROUTES = [
    {'title': 'Admin Dashboard', 'category': 'Admin Page', 'url_func': lambda: url_for('admin.dashboard')},
    {'title': 'Service Settings', 'category': 'Admin Page', 'url_func': lambda: url_for('admin.settings')},
    {'title': 'Admin Tasks (Sync)', 'category': 'Admin Page', 'url_func': lambda: url_for('admin.tasks')},
    {'title': 'Logbook', 'category': 'Admin Page', 'url_func': lambda: url_for('admin.logbook_view')},
    {'title': 'View Logs', 'category': 'Admin Page', 'url_func': lambda: url_for('admin.logs_view')},


    {'title': 'Issue Reports', 'category': 'Admin Page', 'url_func': lambda: url_for('admin.issue_reports')},
]

@admin_bp.route('/search', methods=['GET'])
@login_required
@admin_required
def admin_search():
    """
    Provides search functionality for the admin panel.

    Searches across Sonarr shows, Radarr movies, and predefined admin routes
    based on the query parameter 'q'.

    Returns:
        flask.Response: A JSON list of search results, where each result
                        contains 'title', 'category', 'url', and optionally 'year'.
    """
    query = request.args.get('q', '').strip().lower()
    results = []
    if not query: # Return empty list if query is blank
        return jsonify([])

    db = get_db()

    # Search Shows from sonarr_shows table
    show_rows = db.execute(
        "SELECT title, tmdb_id, year FROM sonarr_shows WHERE lower(title) LIKE ?", ('%' + query + '%',)
    ).fetchall()
    for row in show_rows:
        results.append({
            'title': row['title'],
            'category': 'Show', # Consistent category naming
            'year': row['year'],
            'url': url_for('main.show_detail', tmdb_id=row['tmdb_id'])
        })

    # Search Movies
    movie_rows = db.execute(
        "SELECT title, tmdb_id, year FROM radarr_movies WHERE lower(title) LIKE ?", ('%' + query + '%',)
    ).fetchall()
    for row in movie_rows:
        results.append({
            'title': row['title'],
            'category': 'Movie', # Consistent category naming
            'year': row['year'],
            'url': url_for('main.movie_detail', tmdb_id=row['tmdb_id'])
        })

    # Search Admin Routes
    for route_info in ADMIN_SEARCHABLE_ROUTES:
        if query in route_info['title'].lower():
            try:
                url = route_info['url_func']() # Call the lambda to get URL
                results.append({
                    'title': route_info['title'],
                    'category': route_info['category'],
                    'url': url
                })
            except Exception as e:
                current_app.logger.error(f"Error generating URL for admin route {route_info['title']}: {e}")

    # Sort results for consistent ordering: by category first, then by title.
    results.sort(key=lambda x: (x['category'], x['title']))

    return jsonify(results)

# ============================================================================
# DASHBOARD & SEARCH
# ============================================================================

@admin_bp.route('/dashboard', methods=['GET'])
@login_required
@admin_required
def dashboard():
    """
    Renders the admin dashboard page with comprehensive application statistics.

    This page provides a high-level overview of the application's state by
    displaying key statistics organized into three main sections:
    - Plex Activity: Content consumption and user engagement metrics
    - Media Library: Sonarr/Radarr library statistics and sync status
    - API Usage: LLM service usage and cost tracking

    Returns:
        A rendered HTML template for the admin dashboard with all metrics.
    """
    db = database.get_db()
    
    def safe_value(query):
        """Execute a scalar SQL query and return a numeric result or 0."""
        try:
            result = db.execute(query).fetchone()
            return result[0] if result and result[0] is not None else 0
        except Exception:
            return 0

    # ============================================================================
    # MEDIA LIBRARY STATISTICS
    # ============================================================================
    
    # Basic library counts
    movie_count = safe_value('SELECT COUNT(*) FROM radarr_movies')
    show_count = safe_value('SELECT COUNT(*) FROM sonarr_shows')
    user_count = safe_value('SELECT COUNT(*) FROM users')

    # File availability metrics
    episodes_with_files = safe_value('SELECT COUNT(*) FROM sonarr_episodes WHERE has_file = 1')
    movies_with_files = safe_value('SELECT COUNT(*) FROM radarr_movies WHERE has_file = 1')
    
    # Recent sync activity (last 7 days)
    radarr_week_count = safe_value(
        "SELECT COUNT(*) FROM radarr_movies WHERE last_synced_at >= DATETIME('now', '-7 days')"
    )
    sonarr_week_count = safe_value(
        "SELECT COUNT(*) FROM sonarr_shows WHERE last_synced_at >= DATETIME('now', '-7 days')"
    )

    # ============================================================================
    # PLEX ACTIVITY METRICS
    # ============================================================================
    
    # Content consumption (unique items played)
    # Include both Plex webhook events ('media.play', 'media.scrobble') and Tautulli events ('watched')
    unique_movies_played = safe_value(
        "SELECT COUNT(DISTINCT title) FROM plex_activity_log WHERE media_type = 'movie' AND event_type IN ('media.play', 'media.scrobble', 'watched')"
    )
    unique_episodes_played = safe_value(
        "SELECT COUNT(DISTINCT title) FROM plex_activity_log WHERE media_type = 'episode' AND event_type IN ('media.play', 'media.scrobble', 'watched')"
    )
    unique_shows_watched = safe_value(
        "SELECT COUNT(DISTINCT show_title) FROM plex_activity_log WHERE show_title IS NOT NULL"
    )

    # Recent activity volume (last 7 days)
    plex_events_week = safe_value(
        "SELECT COUNT(*) FROM plex_activity_log WHERE event_timestamp >= DATETIME('now', '-7 days')"
    )
    recent_plays = safe_value(
        "SELECT COUNT(*) FROM plex_activity_log WHERE event_type IN ('media.play', 'watched') AND event_timestamp >= DATETIME('now', '-7 days')"
    )
    recent_scrobbles = safe_value(
        "SELECT COUNT(*) FROM plex_activity_log WHERE event_type = 'media.scrobble' AND event_timestamp >= DATETIME('now', '-7 days')"
    )
    
    # ============================================================================
    # USER ACTIVITY METRICS
    # ============================================================================
    
    # Plex user activity (based on media consumption)
    unique_plex_users = safe_value(
        "SELECT COUNT(DISTINCT plex_username) FROM plex_activity_log WHERE plex_username IS NOT NULL"
    )
    plex_users_today = safe_value(
        "SELECT COUNT(DISTINCT plex_username) FROM plex_activity_log WHERE plex_username IS NOT NULL AND event_timestamp >= DATETIME('now', '-1 day')"
    )
    plex_users_week = safe_value(
        "SELECT COUNT(DISTINCT plex_username) FROM plex_activity_log WHERE plex_username IS NOT NULL AND event_timestamp >= DATETIME('now', '-7 days')"
    )
    plex_users_month = safe_value(
        "SELECT COUNT(DISTINCT plex_username) FROM plex_activity_log WHERE plex_username IS NOT NULL AND event_timestamp >= DATETIME('now', '-30 days')"
    )
    
    # ShowNotes user activity (based on login activity)
    shownotes_users_today = safe_value(
        "SELECT COUNT(DISTINCT username) FROM users WHERE last_login_at >= DATETIME('now', '-1 day')"
    )
    shownotes_users_week = safe_value(
        "SELECT COUNT(DISTINCT username) FROM users WHERE last_login_at >= DATETIME('now', '-7 days')"
    )
    shownotes_users_month = safe_value(
        "SELECT COUNT(DISTINCT username) FROM users WHERE last_login_at >= DATETIME('now', '-30 days')"
    )
    
    # ============================================================================
    # WEBHOOK ACTIVITY METRICS
    # ============================================================================
    
    # Get last webhook activity timestamps
    sonarr_last_webhook = db.execute(
        "SELECT received_at, event_type, payload_summary FROM webhook_activity WHERE service_name = 'sonarr' ORDER BY received_at DESC LIMIT 1"
    ).fetchone()
    
    radarr_last_webhook = db.execute(
        "SELECT received_at, event_type, payload_summary FROM webhook_activity WHERE service_name = 'radarr' ORDER BY received_at DESC LIMIT 1"
    ).fetchone()
    
    # Convert string timestamps to datetime objects for template formatting
    import datetime
    if sonarr_last_webhook and sonarr_last_webhook['received_at']:
        try:
            sonarr_last_webhook = dict(sonarr_last_webhook)
            sonarr_last_webhook['received_at'] = datetime.datetime.strptime(
                sonarr_last_webhook['received_at'], '%Y-%m-%d %H:%M:%S'
            )
        except (ValueError, TypeError):
            sonarr_last_webhook['received_at'] = None
    
    if radarr_last_webhook and radarr_last_webhook['received_at']:
        try:
            radarr_last_webhook = dict(radarr_last_webhook)
            radarr_last_webhook['received_at'] = datetime.datetime.strptime(
                radarr_last_webhook['received_at'], '%Y-%m-%d %H:%M:%S'
            )
        except (ValueError, TypeError):
            radarr_last_webhook['received_at'] = None
    
    # ============================================================================
    # API USAGE METRICS
    # ============================================================================
    
    # Total API usage
    total_api_calls = safe_value('SELECT COUNT(*) FROM api_usage')
    total_api_cost = safe_value('SELECT SUM(cost_usd) FROM api_usage')
    
    # OpenAI usage (last 7 days)
    openai_cost_week = safe_value(
        "SELECT SUM(cost_usd) FROM api_usage WHERE provider='openai' AND timestamp >= DATETIME('now', '-7 days')"
    )
    openai_call_count_week = safe_value(
        "SELECT COUNT(*) FROM api_usage WHERE provider='openai' AND timestamp >= DATETIME('now', '-7 days')"
    )
    
    # Ollama usage (last 7 days)
    ollama_avg_ms = safe_value(
        "SELECT AVG(processing_time_ms) FROM api_usage WHERE provider='ollama' AND timestamp >= DATETIME('now', '-7 days')"
    )
    ollama_call_count_week = safe_value(
        "SELECT COUNT(*) FROM api_usage WHERE provider='ollama' AND timestamp >= DATETIME('now', '-7 days')"
    )

    return render_template(
        'admin_dashboard.html',
        # Media Library metrics
        movie_count=movie_count,
        show_count=show_count,
        user_count=user_count,
        episodes_with_files=episodes_with_files,
        movies_with_files=movies_with_files,
        radarr_week_count=radarr_week_count,
        sonarr_week_count=sonarr_week_count,
        
        # Plex Activity metrics
        unique_movies_played=unique_movies_played,
        unique_episodes_played=unique_episodes_played,
        unique_shows_watched=unique_shows_watched,
        plex_events_week=plex_events_week,
        recent_plays=recent_plays,
        recent_scrobbles=recent_scrobbles,
        
        # User Activity metrics
        unique_plex_users=unique_plex_users,
        plex_users_today=plex_users_today,
        plex_users_week=plex_users_week,
        plex_users_month=plex_users_month,
        shownotes_users_today=shownotes_users_today,
        shownotes_users_week=shownotes_users_week,
        shownotes_users_month=shownotes_users_month,
        
        # API Usage metrics
        total_api_calls=total_api_calls,
        total_api_cost=total_api_cost,
        openai_cost_week=openai_cost_week,
        openai_call_count_week=openai_call_count_week,
        ollama_avg_ms=ollama_avg_ms,
        ollama_call_count_week=ollama_call_count_week,
        
        # Webhook Activity metrics
        sonarr_last_webhook=sonarr_last_webhook,
        radarr_last_webhook=radarr_last_webhook,
    )

# ============================================================================
# TASK EXECUTION
# ============================================================================

@admin_bp.route('/tasks')
@login_required
@admin_required
def tasks():
    """
    Renders the admin tasks page.

    This page provides a UI for administrators to manually trigger various
    background tasks, such as synchronizing the Sonarr and Radarr libraries or
    parsing subtitles.

    Returns:
        A rendered HTML template for the admin tasks page.
    """
    return render_template('admin_tasks.html', title='Admin Tasks')

# ============================================================================
# LOG MANAGEMENT
# ============================================================================

@admin_bp.route('/logs', methods=['GET'])
@login_required
@admin_required
def logs_view():
    """
    Displays the log viewer page.

    Allows admins to view application logs, select log files, and stream live logs.
    """
    return render_template('admin_logs.html', title='View Logs')

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
        # Enrich with episode detail URL and formatted time
        for row in rows:
            row_dict = dict(row)

            # Get TMDB ID - either from row or lookup by title
            tmdb_id = row_dict.get('tmdb_id')
            show_title = row_dict.get('show_title')
            title = row_dict.get('title')
            media_type = row_dict.get('media_type')

            # If no tmdb_id, look it up based on media type
            if not tmdb_id:
                if media_type == 'episode' and show_title:
                    # Look up TV show by show title
                    lookup = db.execute(
                        'SELECT tmdb_id FROM sonarr_shows WHERE title = ? LIMIT 1',
                        (show_title,)
                    ).fetchone()
                    if lookup:
                        tmdb_id = lookup['tmdb_id']
                        row_dict['tmdb_id'] = tmdb_id
                elif media_type == 'movie' and title:
                    # Look up movie by title
                    lookup = db.execute(
                        'SELECT tmdb_id FROM radarr_movies WHERE title = ? LIMIT 1',
                        (title,)
                    ).fetchone()
                    if lookup:
                        tmdb_id = lookup['tmdb_id']
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
                    import re
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
                event_type_map = {
                    'media.play': 'Play',
                    'media.pause': 'Pause',
                    'media.stop': 'Stop',
                    'media.scrobble': 'Scrobble'
                }
                row_dict['event_type_fmt'] = event_type_map.get(event_type, event_type)
            # Get show title and episode title
            show_title = row_dict.get('show_title')
            episode_title = row_dict.get('title')
            row_dict['display_title'] = f'{show_title} – {episode_title}' if show_title else episode_title
            # Get correct TMDB ID from sonarr_shows
            if tmdb_id:
                sonarr_show = db.execute('SELECT tmdb_id FROM sonarr_shows WHERE tmdb_id=?', (tmdb_id,)).fetchone()
                if sonarr_show:
                    row_dict['tmdb_id'] = sonarr_show['tmdb_id']
            plex_logs.append(row_dict)
    return jsonify({'sync_logs': sync_logs, 'plex_logs': plex_logs})
    db = database.get_db()
    users = db.execute('SELECT id, username, plex_username, plex_user_id, last_login_at FROM users').fetchall()
    user_latest = {}
    for u in users:
        latest = db.execute('''SELECT title, season_episode FROM plex_activity_log
                              WHERE plex_username = ? AND event_type IN ('media.stop','media.scrobble')
                              ORDER BY event_timestamp DESC LIMIT 1''', (u['plex_username'],)).fetchone()
        user_latest[u['id']] = latest
    plex_token = database.get_setting('plex_token')
    return render_template('admin_users.html', users=users, user_latest=user_latest, plex_token=plex_token)

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

@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def settings():
    """
    Displays and handles updates for the application settings page.

    On a GET request, it renders the settings page, populating it with current
    values from the database for services like Sonarr, Radarr, Ollama, etc.
    It also fetches available Ollama models if Ollama is configured.

    On a POST request, it processes the submitted form data, updating the `users`
    and `settings` tables in the database with the new values. It then redirects
    back to the settings page with a success message.

    Returns:
        - A rendered HTML template of the settings page on GET.
        - A redirect to the settings page on POST.
    """
    db = database.get_db()
    user = db.execute('SELECT * FROM users WHERE is_admin=1 LIMIT 1').fetchone()
    settings = db.execute('SELECT * FROM settings LIMIT 1').fetchone()
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username and user:
            db.execute('UPDATE users SET username=? WHERE id=?', (username, user['id']))
        if password:
            pw_hash = generate_password_hash(password)
            db.execute('UPDATE users SET password_hash=? WHERE id=?', (pw_hash, user['id']))
        db.execute('''UPDATE settings SET
            radarr_url=?, radarr_api_key=?, radarr_remote_url=?,
            sonarr_url=?, sonarr_api_key=?, sonarr_remote_url=?,
            bazarr_url=?, bazarr_api_key=?, bazarr_remote_url=?,
            pushover_key=?, pushover_token=?,
            plex_client_id=?, tautulli_url=?, tautulli_api_key=?,
            thetvdb_api_key=?, timezone=?, jellyseer_url=?, jellyseer_api_key=?, jellyseer_remote_url=? WHERE id=?''', (
            request.form.get('radarr_url'),
            request.form.get('radarr_api_key'),
            request.form.get('radarr_remote_url'),
            request.form.get('sonarr_url'),
            request.form.get('sonarr_api_key'),
            request.form.get('sonarr_remote_url'),
            request.form.get('bazarr_url'),
            request.form.get('bazarr_api_key'),
            request.form.get('bazarr_remote_url'),
            request.form.get('pushover_key'),
            request.form.get('pushover_token'),
            request.form.get('plex_client_id'),
            request.form.get('tautulli_url'),
            request.form.get('tautulli_api_key'),
            request.form.get('thetvdb_api_key'),
            request.form.get('timezone', 'UTC'),
            request.form.get('jellyseer_url'),
            request.form.get('jellyseer_api_key'),
            request.form.get('jellyseer_remote_url'),
            settings['id'] if settings else 1 # Ensure settings table has an ID=1 row
        ))
        db.commit()
        flash('Settings updated successfully.', 'success')
        return redirect(url_for('admin.settings'))
    
    if settings and ('plex_redirect_uri' in settings and settings['plex_redirect_uri']):
        redirect_uri = settings['plex_redirect_uri']
    else:
        if request.host.startswith('shownotes.chitekmedia.club'):
            redirect_uri = f'https://shownotes.chitekmedia.club/callback'
        else:
            redirect_uri = request.url_root.rstrip('/') + '/callback'
    defaults = {
        'plex_client_id': settings['plex_client_id'] if settings and 'plex_client_id' in settings and settings['plex_client_id'] else f'shownotes-app-{socket.gethostname()}',
        'plex_client_secret': settings['plex_client_secret'] if settings and 'plex_client_secret' in settings and settings['plex_client_secret'] else '',
        'plex_redirect_uri': redirect_uri,
    }
    merged_settings = dict(settings) if settings else {}
    # Ensure new fields are present in merged_settings, even if None initially from DB
    merged_settings.setdefault('thetvdb_api_key', None)
    merged_settings.setdefault('sonarr_remote_url', None)
    merged_settings.setdefault('radarr_remote_url', None)
    merged_settings.setdefault('bazarr_remote_url', None)
    merged_settings.setdefault('timezone', 'UTC')

    for k, v in defaults.items():
        if not merged_settings.get(k): # This will only apply to plex_client_id, secret, redirect_uri if not set
            merged_settings[k] = v
    site_url = request.url_root.rstrip('/')
    plex_webhook_url = url_for('main.plex_webhook', _external=True)
    sonarr_webhook_url = url_for('main.sonarr_webhook', _external=True)
    radarr_webhook_url = url_for('main.radarr_webhook', _external=True)

    sonarr_status = test_sonarr_connection()
    radarr_status = test_radarr_connection()
    bazarr_status = test_bazarr_connection()
    tautulli_status = test_tautulli_connection()
    jellyseerr_status = test_jellyseer_connection()

    # Get list of timezones
    import pytz
    timezones = pytz.common_timezones

    return render_template(
        'admin_settings.html',
        user=user,
        settings=merged_settings,
        site_url=site_url,
        plex_webhook_url=plex_webhook_url,
        sonarr_webhook_url=sonarr_webhook_url,
        radarr_webhook_url=radarr_webhook_url,
        sonarr_status=sonarr_status,
        radarr_status=radarr_status,
        bazarr_status=bazarr_status,
        tautulli_status=tautulli_status,
        jellyseerr_status=jellyseerr_status,
        ollama_models=[],  # Empty list since LLM features removed
        saved_ollama_model=None,
        openai_models=[],  # Empty list since LLM features removed
        timezones=timezones
    )

@admin_bp.route('/api/ollama-models')
@login_required
@admin_required
def ollama_models_api():
    """API endpoint to fetch available Ollama models"""
    import requests
    url = request.args.get('url')
    if not url:
        return jsonify({"error": "URL parameter required"}), 400

    try:
        response = requests.get(f"{url.rstrip('/')}/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            models = data.get('models', [])
            model_names = [model.get('name') for model in models if model.get('name')]
            return jsonify({"models": model_names})
        else:
            return jsonify({"error": f"Ollama server returned status {response.status_code}"}), 500
    except requests.exceptions.Timeout:
        return jsonify({"error": "Connection timeout"}), 500
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Could not connect to Ollama server"}), 500
    except Exception as e:
        current_app.logger.error(f"Error fetching Ollama models: {e}")
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/test-ollama-models')
@login_required
@admin_required
def test_ollama_models_route():
    """Debug route to test Ollama model fetching"""
    models = get_ollama_models()
    return jsonify({"models": models, "count": len(models)})

@admin_bp.route('/sync-sonarr', methods=['POST'])
@login_required
@admin_required
def sync_sonarr():
    """
    Triggers a Sonarr library synchronization task in the background.

    This is a POST-only endpoint that initiates the `sync_sonarr_library`
    utility function in a background thread. It immediately returns to avoid
    timeout issues, and the sync continues in the background.

    Returns:
        A redirect to the 'admin.tasks' page.
    """
    from ..utils import sync_sonarr_library
    import threading

    flash("Sonarr library sync started in background. Check Event Logs for progress.", "info")

    # Capture the application object to pass to the thread
    app_instance = current_app._get_current_object()

    def sync_in_background(app):
        with app.app_context():
            try:
                from app.system_logger import syslog, SystemLogger
                current_app.logger.info("Manual Sonarr sync started from admin panel")
                syslog.info(SystemLogger.SYNC, "Manual Sonarr sync initiated from admin panel")

                count = sync_sonarr_library()

                current_app.logger.info(f"Manual Sonarr sync completed: {count} shows processed")
                syslog.success(SystemLogger.SYNC, f"Manual Sonarr sync completed: {count} shows", {
                    'show_count': count,
                    'source': 'admin_panel'
                })
            except Exception as e:
                current_app.logger.error(f"Manual Sonarr sync error: {e}", exc_info=True)
                syslog.error(SystemLogger.SYNC, "Manual Sonarr sync failed", {
                    'error': str(e),
                    'source': 'admin_panel'
                })

    # Start background sync
    sync_thread = threading.Thread(target=sync_in_background, args=(app_instance,))
    sync_thread.daemon = True
    sync_thread.start()

    current_app.logger.info("Sonarr library sync initiated in background thread")

    return redirect(url_for('admin.tasks'))

# ============================================================================
# LLM TOOLS
# ============================================================================


@admin_bp.route('/clear-character-cache', methods=['POST'])
@login_required
@admin_required
def clear_character_cache():
    """Clear all cached LLM data for characters to force regeneration."""
    try:
        db = database.get_db()
        result = db.execute('''
            UPDATE episode_characters 
            SET llm_relationships=NULL, llm_motivations=NULL, llm_quote=NULL, 
                llm_traits=NULL, llm_events=NULL, llm_importance=NULL, 
                llm_raw_response=NULL, llm_last_updated=NULL, llm_source=NULL
        ''')
        db.commit()
        
        rows_affected = result.rowcount
        return jsonify({'success': True, 'message': f'Cleared LLM cache for {rows_affected} characters'})
    except Exception as e:
        current_app.logger.error(f"Error clearing character cache: {e}")
        return jsonify({'error': 'Failed to clear cache'}), 500














@admin_bp.route('/api/latest-episode')
@login_required
@admin_required
def get_latest_episode():
    """
    API endpoint to get the latest aired episode for a show.
    """
    tmdb_id = request.args.get('tmdb_id')
    if not tmdb_id:
        return jsonify({'error': 'TMDB ID is required'}), 400

    try:
        db = get_db()
        
        # Get the latest aired episode for this show (only episodes that have actually aired)
        # We need to join through the seasons table to get season numbers
        latest_episode = db.execute('''
            SELECT s.season_number, e.episode_number, e.air_date_utc
            FROM sonarr_episodes e
            JOIN sonarr_seasons s ON e.season_id = s.id
            JOIN sonarr_shows sh ON s.show_id = sh.id
            WHERE sh.tmdb_id = ? 
            AND e.air_date_utc IS NOT NULL 
            AND e.air_date_utc != ''
            AND e.air_date_utc <= datetime('now')
            ORDER BY s.season_number DESC, e.episode_number DESC
            LIMIT 1
        ''', (tmdb_id,)).fetchone()
        
        if latest_episode:
            return jsonify({
                'season': latest_episode['season_number'],
                'episode': latest_episode['episode_number'],
                'air_date': latest_episode['air_date_utc']
            })
        else:
            # If no aired episodes found, get the latest episode regardless of air date
            latest_episode = db.execute('''
                SELECT s.season_number, e.episode_number
                FROM sonarr_episodes e
                JOIN sonarr_seasons s ON e.season_id = s.id
                JOIN sonarr_shows sh ON s.show_id = sh.id
                WHERE sh.tmdb_id = ? 
                ORDER BY s.season_number DESC, e.episode_number DESC
                LIMIT 1
            ''', (tmdb_id,)).fetchone()
            
            if latest_episode:
                return jsonify({
                    'season': latest_episode['season_number'],
                    'episode': latest_episode['episode_number'],
                    'air_date': None
                })
            else:
                return jsonify({'error': 'No episodes found for this show'}), 404
                
    except Exception as e:
        current_app.logger.error(f"Error fetching latest episode: {e}", exc_info=True)
        return jsonify({'error': 'Database error'}), 500

@admin_bp.route('/api/get-character-info', methods=['POST'])
@login_required
@admin_required
def get_character_info():
    """
    API endpoint to get character information from the database for testing.
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON payload'}), 400

    character_name = data.get('character', '')
    show_title = data.get('show', '')
    season = data.get('season', 1)
    episode = data.get('episode', 1)

    if not character_name or not show_title:
        return jsonify({'error': 'Character and show are required'}), 400

    db = get_db()
    
    try:
        # First, find the show by title
        show_row = db.execute('SELECT tmdb_id, title, year, overview FROM sonarr_shows WHERE title LIKE ?', (f'%{show_title}%',)).fetchone()
        
        if not show_row:
            current_app.logger.warning(f"Show not found for title: {show_title}")
            return jsonify({'error': 'Show not found', 'searched_title': show_title}), 404
        
        show_tmdb_id = show_row['tmdb_id']
        current_app.logger.info(f"Found show: {show_row['title']} (TMDB ID: {show_tmdb_id})")
        
        # Find the character by name and show
        character_row = db.execute('''
            SELECT ec.actor_name, ec.character_name
            FROM episode_characters ec
            WHERE ec.show_tmdb_id = ? 
            AND ec.season_number = ? 
            AND ec.episode_number = ?
            AND ec.character_name LIKE ?
            LIMIT 1
        ''', (show_tmdb_id, season, episode, f'%{character_name}%')).fetchone()
        
        # Also check what characters exist for this show/episode for debugging
        all_characters = db.execute('''
            SELECT ec.character_name, ec.actor_name
            FROM episode_characters ec
            WHERE ec.show_tmdb_id = ? 
            AND ec.season_number = ? 
            AND ec.episode_number = ?
            LIMIT 10
        ''', (show_tmdb_id, season, episode)).fetchall()
        
        result = {
            'character_name': character_name,
            'show_title': show_title,
            'season': season,
            'episode': episode,
            'actor_name': None,
            'show_year': show_row['year'],
            'show_overview': show_row['overview'],
            'debug_info': {
                'searched_character': character_name,
                'found_show': show_row['title'],
                'show_tmdb_id': show_tmdb_id,
                'available_characters': [{'name': c['character_name'], 'actor': c['actor_name']} for c in all_characters]
            }
        }
        
        if character_row:
            result['actor_name'] = character_row['actor_name']
            current_app.logger.info(f"Found character: {character_row['character_name']} played by {character_row['actor_name']}")
        else:
            current_app.logger.warning(f"Character not found: {character_name} in {show_title} S{season}E{episode}")
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.error(f"Error fetching character info: {e}", exc_info=True)
        return jsonify({'error': 'Database error'}), 500

@admin_bp.route('/api/replace-variables', methods=['POST'])
@login_required
@admin_required
def replace_variables():
    """
    API endpoint to replace variables in a prompt with sample data for testing.
    """
    data = request.get_json()
    if not data or 'prompt_text' not in data:
        return jsonify({'error': 'Missing prompt_text'}), 400

    prompt_text = data['prompt_text']
    
    # Sample data for variable replacement (using single brackets)
    sample_data = {
        '{character}': data.get('character', 'John Doe'),
        '{show}': data.get('show', 'Breaking Bad'),
        '{season}': str(data.get('season', 2)),
        '{episode}': str(data.get('episode', 5)),
        '{actor}': data.get('actor', 'Bryan Cranston'),
        '{year}': str(data.get('year', 2008)),
        '{genre}': data.get('genre', 'Drama'),
        '{overview}': data.get('overview', 'A high school chemistry teacher diagnosed with inoperable lung cancer turns to manufacturing and selling methamphetamine.'),
        '{episode_title}': data.get('episode_title', 'The One Where Walter Gets Angry'),
        '{episode_overview}': data.get('episode_overview', 'Walter confronts his family about his secret life while dealing with the consequences of his actions.'),
        '{air_date}': data.get('air_date', 'March 15, 2009'),
        '{other_characters}': data.get('other_characters', 'Jesse Pinkman, Skyler White, Hank Schrader')
    }

    # Replace variables in the prompt
    replaced_prompt = prompt_text
    for variable, replacement in sample_data.items():
        replaced_prompt = replaced_prompt.replace(variable, replacement)

    return jsonify({
        'original_prompt': prompt_text,
        'replaced_prompt': replaced_prompt,
        'variables_found': [var for var in sample_data.keys() if var in prompt_text]
    })

@admin_bp.route('/api/prompt-history/<int:prompt_id>')
@login_required
@admin_required
def get_prompt_history(prompt_id):
    """
    API endpoint to retrieve the version history for a specific prompt.
    """
    db = get_db()
    try:
        history_rows = db.execute(
            'SELECT * FROM prompt_history WHERE prompt_id = ? ORDER BY timestamp DESC',
            (prompt_id,)
        ).fetchall()

        history = [dict(row) for row in history_rows]

        return jsonify(history)
    except Exception as e:
        current_app.logger.error(f"Error fetching history for prompt_id {prompt_id}: {e}", exc_info=True)
        return jsonify({'error': 'Database query failed'}), 500

@admin_bp.route('/api/characters-for-show')
@login_required
@admin_required
def api_characters_for_show():
    """
    API endpoint to get all unique character names for a given show.
    Accepts a 'tmdb_id' query parameter.
    First tries episode_characters table, then falls back to Plex activity log.
    """
    show_tmdb_id = request.args.get('tmdb_id')
    if not show_tmdb_id:
        return jsonify({'error': 'tmdb_id parameter is required'}), 400

    db = get_db()
    try:
        # First, try to get characters from episode_characters table
        characters = db.execute(
            "SELECT DISTINCT character_name FROM episode_characters WHERE show_tmdb_id = ?",
            (show_tmdb_id,)
        ).fetchall()

        character_names = [row['character_name'] for row in characters if row['character_name']]
        
        # If no characters found in episode_characters, try Plex activity log fallback
        if not character_names:
            # Get show title from sonarr_shows
            show_row = db.execute('SELECT title FROM sonarr_shows WHERE tmdb_id = ?', (show_tmdb_id,)).fetchone()
            if show_row:
                show_title = show_row['title']
                
                # Get the most recent Plex activity log entry for this show
                plex_row = db.execute(
                    'SELECT raw_payload FROM plex_activity_log WHERE show_title = ? ORDER BY event_timestamp DESC LIMIT 1',
                    (show_title,)
                ).fetchone()
                
                if plex_row:
                    import json
                    try:
                        payload = json.loads(plex_row['raw_payload'])
                        metadata = payload.get('Metadata', {})
                        roles = metadata.get('Role', [])
                        
                        # Extract character names from Plex data
                        plex_characters = []
                        for role in roles:
                            character_name = role.get('role')
                            if character_name:
                                plex_characters.append(character_name)
                        
                        character_names = plex_characters
                        current_app.logger.info(f"Found {len(character_names)} characters from Plex data for show {show_title}")
                        
                    except (json.JSONDecodeError, KeyError) as e:
                        current_app.logger.error(f"Error parsing Plex data for show {show_title}: {e}")

        return jsonify(character_names)

    except Exception as e:
        current_app.logger.error(f"Error fetching characters for show {show_tmdb_id}: {e}", exc_info=True)
        return jsonify({'error': 'Database query failed'}), 500

# ============================================================================
# API USAGE
# ============================================================================




@admin_bp.route('/sync-radarr', methods=['POST'])
@login_required
@admin_required
def sync_radarr():
    """
    Triggers a Radarr library synchronization task in the background.

    A POST-only endpoint that calls the `sync_radarr_library` utility function
    in a background thread. It immediately returns to avoid timeout issues.

    Returns:
        A redirect to the 'admin.tasks' page.
    """
    from ..utils import sync_radarr_library
    import threading

    flash("Radarr library sync started in background. Check Event Logs for progress.", "info")

    # Capture the application object to pass to the thread
    app_instance = current_app._get_current_object()

    def sync_in_background(app):
        with app.app_context():
            try:
                from app.system_logger import syslog, SystemLogger
                current_app.logger.info("Manual Radarr sync started from admin panel")
                syslog.info(SystemLogger.SYNC, "Manual Radarr sync initiated from admin panel")

                count = sync_radarr_library()

                current_app.logger.info(f"Manual Radarr sync completed: {count} movies processed")
                syslog.success(SystemLogger.SYNC, f"Manual Radarr sync completed: {count} movies", {
                    'movie_count': count,
                    'source': 'admin_panel'
                })
            except Exception as e:
                current_app.logger.error(f"Manual Radarr sync error: {e}", exc_info=True)
                syslog.error(SystemLogger.SYNC, "Manual Radarr sync failed", {
                    'error': str(e),
                    'source': 'admin_panel'
                })

    # Start background sync
    sync_thread = threading.Thread(target=sync_in_background, args=(app_instance,))
    sync_thread.daemon = True
    sync_thread.start()

    current_app.logger.info("Radarr library sync initiated in background thread")

    return redirect(url_for('admin.tasks'))

@admin_bp.route('/gen_plex_secret', methods=['POST'])
@login_required
@admin_required
def gen_plex_secret():
    """
    Generates a new secure secret for the Plex webhook.

    This endpoint creates a new cryptographically secure token, saves it to the
    database as 'webhook_secret', and returns it as JSON. This is used on the
    settings page to allow the admin to easily generate a new secret.

    Returns:
        flask.Response: A JSON response containing the new webhook secret.
    """
    new_secret = secrets.token_hex(16)
    set_setting('webhook_secret', new_secret)
    return jsonify({'secret': new_secret})


@admin_bp.route('/test-api', methods=['POST'])
@login_required
@admin_required
def test_api_connection():
    """
    Tests the connection to an external API service (Sonarr, Radarr, etc.).

    Expects JSON payload with 'service', 'url', and 'api_key' (if applicable).
    Returns JSON indicating success or failure with an error message.
    """
    data = request.json
    service = data.get('service')
    url = data.get('url')
    api_key = data.get('api_key')
    current_app.logger.info(f'Test API request for {service} at {url}')

    success = False
    error_message = 'Invalid service specified.'

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
    elif service == 'jellyseer' or service == 'jellyseerr':  # Support both spellings
        success, error_message = test_jellyseer_connection_with_params(url, api_key)
    
    if success:
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': error_message or 'Connection test failed'}), 400


@admin_bp.route('/api/ollama-models', methods=['GET'])
@login_required
@admin_required
def get_ollama_models():
    """
    Fetches the available models from an Ollama server.

    Expects a 'url' query parameter with the Ollama server's URL.
    Returns a JSON list of model names or an error.
    """
    ollama_url = request.args.get('url')
    if not ollama_url:
        return jsonify({'error': 'Ollama URL parameter is required.'}), 400

    try:
        import requests
        # Ensure the URL is well-formed
        api_url = ollama_url.rstrip('/') + '/api/tags'
        
        current_app.logger.info(f"Fetching Ollama models from: {api_url}")
        
        resp = requests.get(api_url, timeout=5)
        resp.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)

        data = resp.json()
        
        # The expected structure is a JSON object with a "models" key,
        # which is a list of objects, each with a "model" name.
        # Example: {"models": [{"model": "llama2:latest", ...}, ...]}
        ollama_models = [m.get('name') for m in data.get('models', []) if m.get('name')]
        
        current_app.logger.info(f"Successfully fetched {len(ollama_models)} models from Ollama.")
        
        return jsonify({'models': ollama_models})

    except requests.exceptions.Timeout:
        error_msg = "Connection to Ollama timed out. Ensure the URL is correct and the server is responsive."
        current_app.logger.error(f"{error_msg} URL: {ollama_url}")
        return jsonify({'error': error_msg}), 504 # Gateway Timeout
    except requests.exceptions.RequestException as e:
        error_msg = f"Could not connect to Ollama. Please check the URL and ensure the service is running. Error: {e}"
        current_app.logger.error(f"{error_msg} URL: {ollama_url}")
        return jsonify({'error': error_msg}), 500
    except Exception as e:
        error_msg = f"An unexpected error occurred: {e}"
        current_app.logger.error(f"Failed to fetch Ollama models from {ollama_url}. {error_msg}", exc_info=True)
        return jsonify({'error': error_msg}), 500


@admin_bp.route('/test-pushover', methods=['POST'])
@login_required
@admin_required
def test_pushover_connection_route():
    """
    Tests the Pushover notification service with provided credentials.

    Expects JSON payload with 'token' and 'user_key'.
    Returns JSON indicating success or failure.
    """
    data = request.json
    token = data.get('token')
    user_key = data.get('user_key')
    current_app.logger.info(f'Test Pushover request')

    success, error_message = test_pushover_notification_with_params(token, user_key)
    
    if success:
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': error_message or 'Pushover test failed'}), 400

@admin_bp.route('/sync-tautulli', methods=['POST'])
@login_required
@admin_required
def sync_tautulli():
    """
    Triggers a Tautulli watch history synchronization task.

    Supports both incremental (default) and full import modes.
    Query parameter ?full=true triggers a full import.

    Returns:
        A redirect to the 'admin.tasks' page.
    """
    full_import = request.args.get('full', 'false').lower() == 'true'

    if full_import:
        flash("Tautulli FULL import started in background. This may take several minutes. Check Event Logs for progress.", "info")
    else:
        flash("Tautulli incremental sync started...", "info")

    import threading
    app_instance = current_app._get_current_object()

    def sync_in_background(app, full):
        with app.app_context():
            try:
                from app.system_logger import syslog, SystemLogger
                mode = "full import" if full else "incremental sync"
                syslog.info(SystemLogger.SYNC, f"Manual Tautulli {mode} initiated from admin panel")

                count = sync_tautulli_watch_history(full_import=full)

                syslog.success(SystemLogger.SYNC, f"Tautulli {mode} completed: {count} new events", {
                    'event_count': count,
                    'mode': mode
                })
            except Exception as e:
                syslog.error(SystemLogger.SYNC, f"Tautulli {mode} failed", {
                    'error': str(e),
                    'mode': mode
                })

    sync_thread = threading.Thread(target=sync_in_background, args=(app_instance, full_import))
    sync_thread.daemon = True
    sync_thread.start()

    return redirect(url_for('admin.tasks'))

@admin_bp.route('/tautulli-wipe-and-import', methods=['POST'])
@login_required
@admin_required
def tautulli_wipe_and_import():
    """
    Wipes all existing Plex activity log data and performs a fresh full import
    from Tautulli. Use this for onboarding or to reset watch history.

    Returns:
        A redirect to the 'admin.tasks' page.
    """
    flash("Wiping watch history and starting fresh Tautulli import in background. Check Event Logs for progress.", "warning")

    import threading
    app_instance = current_app._get_current_object()

    def wipe_and_import(app):
        with app.app_context():
            try:
                from app.system_logger import syslog, SystemLogger
                db = database.get_db()

                # Get count before wiping
                old_count = db.execute('SELECT COUNT(*) as count FROM plex_activity_log').fetchone()['count']

                syslog.info(SystemLogger.SYNC, f"Wiping {old_count} existing watch history records")

                # Wipe all existing data
                db.execute('DELETE FROM plex_activity_log')
                db.commit()

                syslog.success(SystemLogger.SYNC, "Watch history wiped, starting fresh import")

                # Do full import
                count = sync_tautulli_watch_history(full_import=True)

                syslog.success(SystemLogger.SYNC, f"Fresh Tautulli import completed: {count} events imported", {
                    'old_count': old_count,
                    'new_count': count
                })
            except Exception as e:
                syslog.error(SystemLogger.SYNC, "Tautulli wipe and import failed", {
                    'error': str(e)
                })

    import_thread = threading.Thread(target=wipe_and_import, args=(app_instance,))
    import_thread.daemon = True
    import_thread.start()

    return redirect(url_for('admin.tasks'))

@admin_bp.route('/process-watch-status', methods=['POST'])
@login_required
@admin_required
def process_watch_status():
    """
    Process plex_activity_log to update user_episode_progress with watch indicators.

    This scans all historical watch events and marks episodes as watched in the
    user_episode_progress table. Useful for backfilling watch status from Tautulli imports.

    Returns:
        A redirect to the 'admin.tasks' page.
    """
    flash("Processing activity log for watch indicators in background. This may take a few minutes. Check Event Logs for progress.", "info")

    import threading
    app_instance = current_app._get_current_object()

    def process_in_background(app):
        with app.app_context():
            try:
                from app.system_logger import syslog, SystemLogger
                syslog.info(SystemLogger.SYNC, "Processing activity log for watch status initiated from admin panel")

                from app.utils import process_activity_log_for_watch_status
                count = process_activity_log_for_watch_status()

                syslog.success(SystemLogger.SYNC, f"Watch status processing completed: {count} episodes marked as watched", {
                    'episode_count': count
                })
            except Exception as e:
                syslog.error(SystemLogger.SYNC, "Watch status processing failed", {
                    'error': str(e)
                })

    process_thread = threading.Thread(target=process_in_background, args=(app_instance,))
    process_thread.daemon = True
    process_thread.start()

    return redirect(url_for('admin.tasks'))

@admin_bp.route('/parse-subtitles', methods=['POST'])
@login_required
@admin_required
def parse_all_subtitles_route():
    """
    Triggers the task to parse all subtitles for all shows.

    This POST-only endpoint initiates the `process_all_subtitles` function,
    which can be a long-running task. It flashes status messages and redirects
    to the tasks page.

    Returns:
        A redirect to the 'admin.tasks' page.
    """
    current_app.logger.info("Subtitle parsing task triggered by admin.")
    flash("Subtitle parsing started...", "info")
    try:
        # Assuming process_all_subtitles handles its own logging for details
        process_all_subtitles()
        flash("Subtitle parsing completed successfully.", "success")
        current_app.logger.info("Subtitle parsing task completed successfully.")
    except Exception as e:
        current_app.logger.error(f"Error during subtitle parsing: {e}", exc_info=True)
        flash(f"Error during subtitle parsing: {str(e)}", "danger")
    return redirect(url_for('admin.tasks'))

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


@admin_bp.route('/event-logs')
@login_required
@admin_required
def event_logs():
    """Display system event logs page"""
    return render_template('admin_event_logs.html', title='System Event Logs')


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
