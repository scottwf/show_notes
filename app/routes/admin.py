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
    test_tautulli_connection, test_tautulli_connection_with_params
)
from ..parse_subtitles import process_all_subtitles
from .. import prompt_builder
from .. import prompts # if prompts.py contains directly usable prompt strings
import inspect
from ..llm_services import get_llm_response


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
    {'title': 'API Usage Logs', 'category': 'Admin Page', 'url_func': lambda: url_for('admin.api_usage_logs')},
    {'title': 'View Prompts', 'category': 'Admin Page', 'url_func': lambda: url_for('admin.view_prompts')},
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
    unique_movies_played = safe_value(
        "SELECT COUNT(DISTINCT title) FROM plex_activity_log WHERE media_type = 'movie' AND event_type IN ('media.play', 'media.scrobble')"
    )
    unique_episodes_played = safe_value(
        "SELECT COUNT(DISTINCT title) FROM plex_activity_log WHERE media_type = 'episode' AND event_type IN ('media.play', 'media.scrobble')"
    )
    unique_shows_watched = safe_value(
        "SELECT COUNT(DISTINCT show_title) FROM plex_activity_log WHERE show_title IS NOT NULL"
    )
    
    # Recent activity volume (last 7 days)
    plex_events_week = safe_value(
        "SELECT COUNT(*) FROM plex_activity_log WHERE event_timestamp >= DATETIME('now', '-7 days')"
    )
    recent_plays = safe_value(
        "SELECT COUNT(*) FROM plex_activity_log WHERE event_type = 'media.play' AND event_timestamp >= DATETIME('now', '-7 days')"
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

@admin_bp.route('/logbook')
@login_required
@admin_required
def logbook_view():
    """
    Renders the interactive logbook page.

    The logbook provides a consolidated view of recent system activities,
    including service synchronization statuses and Plex watch history. The data
    for this page is fetched dynamically via the `/logbook/data` endpoint.

    Returns:
        A rendered HTML template for the logbook.
    """
    return render_template('admin_logbook.html')

@admin_bp.route('/logbook/data')
@login_required
@admin_required
def logbook_data():
    """
    Provides data for the admin logbook.

    Fetches service sync logs and Plex activity logs based on query parameters
    for category, user, and show. Enriches Plex logs with formatted timestamps
    and episode detail URLs.

    Query Params:
        category (str, optional): Filters logs by category ('sync', 'plex', 'all').
        user (str, optional): Filters Plex logs by username.
        show (str, optional): Filters Plex logs by show title.

    Returns:
        flask.Response: JSON response containing lists of sync_logs and plex_logs.
    """
    category = request.args.get('category')
    user = request.args.get('user')
    show = request.args.get('show')
    db = database.get_db()
    sync_logs = []
    plex_logs = []
    # Service Sync logs
    if not category or category in ['sync', 'all']:
        sync_logs = [dict(row) for row in db.execute('SELECT * FROM service_sync_status ORDER BY last_attempted_sync_at DESC LIMIT 20').fetchall()]
    # Plex Activity logs
    if not category or category in ['plex', 'all']:
        query = 'SELECT * FROM plex_activity_log WHERE 1=1'
        params = []
        if user:
            query += ' AND plex_username = ?'
            params.append(user)
        if show:
            query += ' AND (title LIKE ? OR grandparentTitle LIKE ? OR grandparent_title LIKE ?)'  # support different column names
            params.extend([f'%{show}%']*3)
        query += ' ORDER BY event_timestamp DESC, id DESC LIMIT 50'
        rows = db.execute(query, params).fetchall()
        # Enrich with episode detail URL and formatted time
        for row in rows:
            row_dict = dict(row)
            # Try to build episode_detail_url if possible
            season_episode = row_dict.get('season_episode')
            tmdb_id = row_dict.get('tmdb_id')
            episode_detail_url = None
            if season_episode and tmdb_id:
                import re
                match = re.match(r'S(\d+)E(\d+)', season_episode)
                if match:
                    season_number = int(match.group(1))
                    episode_number = int(match.group(2))
                    episode_detail_url = url_for('main.episode_detail', tmdb_id=tmdb_id, season_number=season_number, episode_number=episode_number)
            row_dict['episode_detail_url'] = episode_detail_url
            # Format timestamp
            import datetime
            ts = row_dict.get('event_timestamp')
            if ts:
                try:
                    dt = datetime.datetime.fromtimestamp(float(ts))
                    row_dict['event_timestamp_fmt'] = dt.strftime('%Y-%m-%d %H:%M')
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
            show_title = row_dict.get('grandparentTitle') or row_dict.get('grandparent_title')
            episode_title = row_dict.get('title')
            row_dict['display_title'] = f'{show_title} – {episode_title}'
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
            radarr_url=?, radarr_api_key=?,
            sonarr_url=?, sonarr_api_key=?,
            bazarr_url=?, bazarr_api_key=?,
            ollama_url=?, ollama_model_name=?, openai_api_key=?, openai_model_name=?, preferred_llm_provider=?,
            pushover_key=?, pushover_token=?,
            plex_client_id=?, tautulli_url=?, tautulli_api_key=?,
            thetvdb_api_key=? WHERE id=?''', (
            request.form.get('radarr_url'),
            request.form.get('radarr_api_key'),
            request.form.get('sonarr_url'),
            request.form.get('sonarr_api_key'),
            request.form.get('bazarr_url'),
            request.form.get('bazarr_api_key'),
            request.form.get('ollama_url'),
            request.form.get('ollama_model_name'),
            request.form.get('openai_api_key'),
            request.form.get('openai_model_name'),
            request.form.get('preferred_llm_provider'),
            request.form.get('pushover_key'),
            request.form.get('pushover_token'),
            request.form.get('plex_client_id'),
            request.form.get('tautulli_url'),
            request.form.get('tautulli_api_key'),
            request.form.get('thetvdb_api_key'),
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
    merged_settings.setdefault('openai_api_key', None)
    merged_settings.setdefault('openai_model_name', None)
    merged_settings.setdefault('preferred_llm_provider', None)
    merged_settings.setdefault('ollama_model_name', None)
    merged_settings.setdefault('thetvdb_api_key', None)

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
    ollama_status = test_ollama_connection()
    tautulli_status = test_tautulli_connection() # Added Tautulli status

    # Fetch available Ollama models for dropdown
    ollama_models = []
    saved_model = merged_settings.get('ollama_model_name')

    openai_models = [
        {"name": "gpt-3.5-turbo", "price": "$0.0015 / 1K"},
        {"name": "gpt-4o", "price": "$0.005 / 1K"},
        {"name": "gpt-4-turbo", "price": "$0.01 / 1K"},
    ]

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
        ollama_status=ollama_status,
        tautulli_status=tautulli_status, # Added Tautulli status
        ollama_models=ollama_models,
        saved_ollama_model=saved_model,
        openai_models=openai_models
    )

@admin_bp.route('/sync-sonarr', methods=['POST'])
@login_required
@admin_required
def sync_sonarr():
    """
    Triggers a Sonarr library synchronization task.

    This is a POST-only endpoint that initiates the `sync_sonarr_library`
    utility function. It flashes messages to the user indicating the start,
    success, or failure of the sync task and then redirects back to the tasks page.

    Returns:
        A redirect to the 'admin.tasks' page.
    """
    flash("Sonarr library sync started...", "info")
    try:
        count = sync_sonarr_library()
        flash(f"Sonarr library sync completed successfully. {count} shows processed.", "success")
    except Exception as e:
        flash(f"Error during Sonarr sync: {str(e)}", "danger") # Changed to danger for errors
        current_app.logger.error(f"Sonarr sync error: {e}", exc_info=True)
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


@admin_bp.route('/view-prompts', methods=['GET', 'POST'])
@login_required
@admin_required
def view_prompts():
    """
    Displays all available LLM prompt templates from the database.
    """
    db = get_db()
    if request.method == 'POST':
        prompt_id = request.form.get('prompt_id')
        prompt_text = request.form.get('prompt_text')

        if prompt_id and prompt_text:
            # First, get the current prompt to store in history
            current_prompt = db.execute('SELECT prompt FROM prompts WHERE id = ?', (prompt_id,)).fetchone()
            if current_prompt:
                # Add current version to history
                db.execute('INSERT INTO prompt_history (prompt_id, prompt) VALUES (?, ?)',
                           (prompt_id, current_prompt['prompt']))

                # Update the prompt
                db.execute('UPDATE prompts SET prompt = ? WHERE id = ?', (prompt_text, prompt_id))
                db.commit()
                flash('Prompt updated successfully.', 'success')
            else:
                flash('Prompt not found.', 'danger')
        else:
            flash('Invalid request.', 'danger')
        return redirect(url_for('admin.view_prompts'))

    prompts_from_db = db.execute('SELECT * FROM prompts ORDER BY name').fetchall()

    # For now, we will also keep the old way of loading prompts from files
    # to avoid breaking anything. We will phase this out later.
    builder_prompts = []
    try:
        builder_functions = inspect.getmembers(prompt_builder, inspect.isfunction)
        for name, func in builder_functions:
            if name.startswith('build_'):
                # Here you can decide if you want to show example output
                # For simplicity, we'll just show the name and docstring
                docstring = inspect.getdoc(func)
                builder_prompts.append({'name': name, 'text': docstring, 'source': 'prompt_builder.py'})
    except Exception as e:
        current_app.logger.error(f"Error inspecting prompt_builder.py: {e}", exc_info=True)

    static_prompts = []
    try:
        for var_name, var_value in inspect.getmembers(prompts):
            if isinstance(var_value, str) and "PROMPT" in var_name.upper():
                static_prompts.append({'name': var_name, 'text': var_value, 'source': 'prompts.py'})
    except Exception as e:
        current_app.logger.error(f"Error inspecting prompts.py: {e}", exc_info=True)

    return render_template('admin_view_prompts_simple.html',
                           prompts_from_db=prompts_from_db,
                           builder_prompts=builder_prompts,
                           static_prompts=static_prompts,
                           title="Prompt Management")

@admin_bp.route('/api/test-llm', methods=['POST'])
@login_required
@admin_required
def test_llm():
    """
    API endpoint to test LLM prompts with real data.
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON payload'}), 400

    prompt = data.get('prompt', '')
    prompt_type = data.get('prompt_type', 'character')
    test_data = data.get('test_data', {})

    if not prompt:
        return jsonify({'error': 'Prompt is required'}), 400

    try:
        # Import LLM functions
        from app.llm_services import get_llm_response
        
        # Log the test attempt
        current_app.logger.info(f"LLM test - Type: {prompt_type}, Prompt length: {len(prompt)}")
        
        # Get LLM response (returns tuple: response_text, error_message)
        response_text, error_message = get_llm_response(prompt)
        
        if error_message:
            current_app.logger.error(f"LLM test failed: {error_message}")
            return jsonify({'error': error_message}), 500
        
        if not response_text:
            current_app.logger.error("LLM test returned empty response")
            return jsonify({'error': 'LLM returned empty response'}), 500
        
        current_app.logger.info(f"LLM test successful - Response length: {len(response_text)}")
        
        # Get LLM info from the last API usage log entry
        db = get_db()
        llm_info = {}
        try:
            last_usage = db.execute(
                'SELECT provider, endpoint, cost_usd, processing_time_ms FROM api_usage ORDER BY timestamp DESC LIMIT 1'
            ).fetchone()
            if last_usage:
                llm_info = {
                    'provider': last_usage['provider'],
                    'model': last_usage['endpoint'],
                    'cost': f"${last_usage['cost_usd']:.4f}" if last_usage['cost_usd'] else 'N/A',
                    'time': f"{last_usage['processing_time_ms']}ms" if last_usage['processing_time_ms'] else 'N/A'
                }
        except Exception as e:
            current_app.logger.error(f"Error fetching LLM info: {e}")

        return jsonify({
            'content': response_text,
            'prompt_type': prompt_type,
            'test_data': test_data,
            'llm_info': llm_info
        })
        
    except Exception as e:
        current_app.logger.error(f"LLM test error: {e}", exc_info=True)
        return jsonify({'error': f'LLM request failed: {str(e)}'}), 500

@admin_bp.route('/api/save-prompt', methods=['POST'])
@login_required
@admin_required
def save_prompt():
    """
    API endpoint to save a prompt template.
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON payload'}), 400

    prompt_type = data.get('prompt_type', '')
    prompt_text = data.get('prompt_text', '')

    if not prompt_type or not prompt_text:
        return jsonify({'error': 'Prompt type and text are required'}), 400

    try:
        db = get_db()
        
        # Map prompt types to database names
        prompt_name_map = {
            'character': 'character_summary',
            'show': 'show_summary', 
            'season': 'season_summary',
            'episode': 'episode_summary'
        }
        
        prompt_name = prompt_name_map.get(prompt_type)
        if not prompt_name:
            return jsonify({'error': 'Invalid prompt type'}), 400

        # Check if prompt exists
        existing = db.execute('SELECT id FROM prompts WHERE name = ?', (prompt_name,)).fetchone()
        
        if existing:
            # Update existing prompt
            db.execute('UPDATE prompts SET prompt = ? WHERE name = ?', (prompt_text, prompt_name))
            current_app.logger.info(f"Updated prompt template: {prompt_name}")
        else:
            # Insert new prompt
            db.execute('INSERT INTO prompts (name, prompt) VALUES (?, ?)', (prompt_name, prompt_text))
            current_app.logger.info(f"Created new prompt template: {prompt_name}")
        
        db.commit()
        return jsonify({'success': True, 'message': 'Prompt template saved successfully'})
        
    except Exception as e:
        current_app.logger.error(f"Error saving prompt: {e}", exc_info=True)
        return jsonify({'error': 'Failed to save prompt template'}), 500

@admin_bp.route('/api/get-prompt')
@login_required
@admin_required
def get_prompt():
    """
    API endpoint to get a saved prompt template.
    """
    prompt_type = request.args.get('type', '')
    
    if not prompt_type:
        return jsonify({'error': 'Prompt type is required'}), 400

    try:
        db = get_db()
        
        # Map prompt types to database names
        prompt_name_map = {
            'character': 'character_summary',
            'show': 'show_summary', 
            'season': 'season_summary',
            'episode': 'episode_summary'
        }
        
        prompt_name = prompt_name_map.get(prompt_type)
        if not prompt_name:
            return jsonify({'error': 'Invalid prompt type'}), 400

        # Get prompt from database
        prompt_row = db.execute('SELECT prompt FROM prompts WHERE name = ?', (prompt_name,)).fetchone()
        
        if prompt_row:
            return jsonify({'prompt': prompt_row['prompt']})
        else:
            return jsonify({'prompt': None})
        
    except Exception as e:
        current_app.logger.error(f"Error getting prompt: {e}", exc_info=True)
        return jsonify({'error': 'Failed to get prompt template'}), 500

@admin_bp.route('/api/test-grounded-llm', methods=['POST'])
@login_required
@admin_required
def test_grounded_llm():
    """
    API endpoint to test LLM with grounded episode data.
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON payload'}), 400

    prompt_type = data.get('prompt_type', '')
    tmdb_id = data.get('tmdb_id')
    season = data.get('season')
    episode = data.get('episode')
    character_name = data.get('character_name', '')
    show_title = data.get('show_title', '')

    if not prompt_type or not tmdb_id or not season or not episode:
        return jsonify({'error': 'Prompt type, TMDB ID, season, and episode are required'}), 400

    try:
        # Import LLM functions
        from app.llm_services import get_llm_response
        from app.prompt_builder import build_grounded_character_prompt, build_grounded_show_prompt
        
        # Build grounded prompt based on type
        if prompt_type == 'character' and character_name:
            prompt = build_grounded_character_prompt(character_name, show_title, tmdb_id, season, episode)
        elif prompt_type == 'show':
            prompt = build_grounded_show_prompt(show_title, tmdb_id, season, episode)
        else:
            return jsonify({'error': 'Invalid prompt type or missing character name'}), 400
        
        # Log the test attempt
        current_app.logger.info(f"Grounded LLM test - Type: {prompt_type}, TMDB: {tmdb_id}, S{season}E{episode}")
        
        # Get LLM response
        response_text, error_message = get_llm_response(prompt)
        
        if error_message:
            current_app.logger.error(f"LLM test failed: {error_message}")
            return jsonify({'error': f'LLM request failed: {error_message}'}), 500
        
        if not response_text:
            current_app.logger.error("LLM returned empty response")
            return jsonify({'error': 'LLM returned empty response'}), 500
        
        # Get LLM info from the most recent API usage record
        db = get_db()
        llm_info_row = db.execute("""
            SELECT provider, model, cost, response_time 
            FROM api_usage 
            ORDER BY timestamp DESC 
            LIMIT 1
        """).fetchone()
        
        llm_info = {
            'provider': llm_info_row['provider'] if llm_info_row else 'Unknown',
            'model': llm_info_row['model'] if llm_info_row else 'Unknown',
            'cost': llm_info_row['cost'] if llm_info_row else 0.0,
            'time': llm_info_row['response_time'] if llm_info_row else 0
        }
        
        current_app.logger.info(f"Grounded LLM test successful - Provider: {llm_info['provider']}, Model: {llm_info['model']}")
        
        return jsonify({
            'success': True,
            'response': response_text,
            'llm_info': llm_info,
            'prompt_used': prompt[:500] + '...' if len(prompt) > 500 else prompt
        })
        
    except Exception as e:
        current_app.logger.error(f"Error in grounded LLM test: {e}", exc_info=True)
        return jsonify({'error': 'Failed to run grounded LLM test'}), 500

@admin_bp.route('/api/test-recap-scraping', methods=['POST'])
@login_required
@admin_required
def test_recap_scraping():
    """
    API endpoint to test recap scraping functionality.
    """
    try:
        from app.recap_scrapers import recap_scraping_manager
        
        # Test scraping recent recaps
        current_app.logger.info("Testing recap scraping...")
        recaps = recap_scraping_manager.scrape_recent_recaps(days_back=7)
        
        # Match recaps to shows in database
        matched_recaps = recap_scraping_manager.match_recaps_to_shows(recaps)
        
        # Store matched recaps
        if matched_recaps:
            recap_scraping_manager.store_recap_summaries(matched_recaps)
        
        return jsonify({
            'success': True,
            'total_recaps_found': len(recaps),
            'matched_recaps': len(matched_recaps),
            'recaps': recaps[:10],  # Return first 10 for preview
            'matched': matched_recaps[:5]  # Return first 5 matched for preview
        })
        
    except Exception as e:
        current_app.logger.error(f"Error in recap scraping test: {e}", exc_info=True)
        return jsonify({'error': f'Failed to test recap scraping: {str(e)}'}), 500

@admin_bp.route('/api/scrape-show-recaps', methods=['POST'])
@login_required
@admin_required
def scrape_show_recaps():
    """
    API endpoint to scrape recaps for a specific show.
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON payload'}), 400

    tmdb_id = data.get('tmdb_id')
    show_title = data.get('show_title')
    max_episodes = data.get('max_episodes', 20)

    if not tmdb_id or not show_title:
        return jsonify({'error': 'TMDB ID and show title are required'}), 400

    try:
        from app.recap_scrapers import recap_scraping_manager
        
        # Scrape recaps for the specific show
        current_app.logger.info(f"Scraping recaps for show: {show_title}")
        recaps = recap_scraping_manager.scrape_show_recaps(show_title, max_episodes)
        
        if not recaps:
            return jsonify({
                'success': False,
                'error': f'No recaps found for "{show_title}". This may be due to rate limiting from recap sites or the show not having recent recaps available.',
                'suggestion': 'Try again later or check if the show has recent episodes with recaps on Vulture or Showbiz Junkies.'
            })
        
        # Match recaps to the show (should all match since we filtered by show title)
        matched_recaps = []
        for recap in recaps:
            recap['tmdb_id'] = tmdb_id
            recap['matched_show'] = show_title
            matched_recaps.append(recap)
        
        # Store the recaps
        if matched_recaps:
            recap_scraping_manager.store_recap_summaries(matched_recaps)
        
        # Get updated episode count for this show
        db = get_db()
        episode_count = db.execute("""
            SELECT COUNT(*) as count FROM episode_summaries 
            WHERE tmdb_id = ? AND source_provider IN ('Vulture', 'Showbiz Junkies')
        """, (tmdb_id,)).fetchone()['count']
        
        return jsonify({
            'success': True,
            'show_title': show_title,
            'recaps_found': len(recaps),
            'recaps_stored': len(matched_recaps),
            'total_episode_summaries': episode_count,
            'recaps': recaps[:10]  # Return first 10 for preview
        })
        
    except Exception as e:
        error_msg = str(e)
        current_app.logger.error(f"Error scraping recaps for {show_title}: {e}", exc_info=True)
        
        # Provide more specific error messages
        if "pattern" in error_msg.lower() and "match" in error_msg.lower():
            return jsonify({
                'success': False,
                'error': f'Scraping failed for {show_title}. This could be due to site structure changes or unexpected content format.',
                'suggestion': 'The scraping system has been updated with proper browser headers. If this persists, the site structure may have changed and the scraping rules may need updates.'
            })
        else:
            return jsonify({'error': f'Failed to scrape recaps for {show_title}: {str(e)}'}), 500

# Recap Sites Management
@admin_bp.route('/recap-sites')
@login_required
@admin_required
def recap_sites():
    """Recap sites management page"""
    return render_template('admin_recap_sites.html')

@admin_bp.route('/api/recap-sites', methods=['GET'])
@login_required
@admin_required
def get_recap_sites():
    """Get all recap sites"""
    try:
        db = get_db()
        sites = db.execute("""
            SELECT id, site_name, base_url, is_active, rate_limit_seconds, 
                   user_agent, link_patterns, title_patterns, content_patterns,
                   sample_urls, created_at, updated_at
            FROM recap_sites 
            ORDER BY site_name
        """).fetchall()
        
        sites_list = []
        for site in sites:
            sites_list.append({
                'id': site['id'],
                'site_name': site['site_name'],
                'base_url': site['base_url'],
                'is_active': bool(site['is_active']),
                'rate_limit_seconds': site['rate_limit_seconds'],
                'user_agent': site['user_agent'],
                'link_patterns': site['link_patterns'],
                'title_patterns': site['title_patterns'],
                'content_patterns': site['content_patterns'],
                'sample_urls': site['sample_urls'],
                'created_at': site['created_at'],
                'updated_at': site['updated_at']
            })
        
        return jsonify({'success': True, 'sites': sites_list})
        
    except Exception as e:
        current_app.logger.error(f"Error getting recap sites: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@admin_bp.route('/api/recap-sites', methods=['POST'])
@login_required
@admin_required
def create_recap_site():
    """Create a new recap site"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['site_name', 'base_url']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400
        
        db = get_db()
        
        # Check if site already exists
        existing = db.execute(
            "SELECT id FROM recap_sites WHERE site_name = ?", 
            (data['site_name'],)
        ).fetchone()
        
        if existing:
            return jsonify({'success': False, 'error': 'Site with this name already exists'}), 400
        
        # Insert new site
        db.execute("""
            INSERT INTO recap_sites 
            (site_name, base_url, is_active, rate_limit_seconds, user_agent,
             link_patterns, title_patterns, content_patterns, sample_urls, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """, (
            data['site_name'],
            data['base_url'],
            data.get('is_active', True),
            data.get('rate_limit_seconds', 30),
            data.get('user_agent', ''),
            data.get('link_patterns', '[]'),
            data.get('title_patterns', '[]'),
            data.get('content_patterns', '[]'),
            data.get('sample_urls', '[]')
        ))
        
        db.commit()
        return jsonify({'success': True, 'message': 'Recap site created successfully'})
        
    except Exception as e:
        current_app.logger.error(f"Error creating recap site: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@admin_bp.route('/api/recap-sites/<int:site_id>', methods=['GET'])
@login_required
@admin_required
def get_recap_site(site_id):
    """Get a specific recap site"""
    try:
        db = get_db()
        site = db.execute("""
            SELECT id, site_name, base_url, is_active, rate_limit_seconds, 
                   user_agent, link_patterns, title_patterns, content_patterns,
                   sample_urls, created_at, updated_at
            FROM recap_sites 
            WHERE id = ?
        """, (site_id,)).fetchone()
        
        if not site:
            return jsonify({'success': False, 'error': 'Site not found'}), 404
        
        site_data = {
            'id': site['id'],
            'site_name': site['site_name'],
            'base_url': site['base_url'],
            'is_active': bool(site['is_active']),
            'rate_limit_seconds': site['rate_limit_seconds'],
            'user_agent': site['user_agent'],
            'link_patterns': site['link_patterns'],
            'title_patterns': site['title_patterns'],
            'content_patterns': site['content_patterns'],
            'sample_urls': site['sample_urls'],
            'created_at': site['created_at'],
            'updated_at': site['updated_at']
        }
        
        return jsonify({'success': True, 'site': site_data})
        
    except Exception as e:
        current_app.logger.error(f"Error getting recap site: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@admin_bp.route('/api/recap-sites/<int:site_id>', methods=['PUT'])
@login_required
@admin_required
def update_recap_site(site_id):
    """Update a recap site"""
    try:
        data = request.get_json()
        
        db = get_db()
        
        # Check if site exists
        existing = db.execute("SELECT id FROM recap_sites WHERE id = ?", (site_id,)).fetchone()
        if not existing:
            return jsonify({'success': False, 'error': 'Site not found'}), 404
        
        # Update site
        db.execute("""
            UPDATE recap_sites 
            SET site_name = ?, base_url = ?, is_active = ?, rate_limit_seconds = ?,
                user_agent = ?, link_patterns = ?, title_patterns = ?, content_patterns = ?,
                sample_urls = ?, updated_at = datetime('now')
            WHERE id = ?
        """, (
            data['site_name'],
            data['base_url'],
            data.get('is_active', True),
            data.get('rate_limit_seconds', 30),
            data.get('user_agent', ''),
            data.get('link_patterns', '[]'),
            data.get('title_patterns', '[]'),
            data.get('content_patterns', '[]'),
            data.get('sample_urls', '[]'),
            site_id
        ))
        
        db.commit()
        return jsonify({'success': True, 'message': 'Recap site updated successfully'})
        
    except Exception as e:
        current_app.logger.error(f"Error updating recap site: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@admin_bp.route('/api/recap-sites/<int:site_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_recap_site(site_id):
    """Delete a recap site"""
    try:
        db = get_db()
        
        # Check if site exists
        existing = db.execute("SELECT id FROM recap_sites WHERE id = ?", (site_id,)).fetchone()
        if not existing:
            return jsonify({'success': False, 'error': 'Site not found'}), 404
        
        # Delete site
        db.execute("DELETE FROM recap_sites WHERE id = ?", (site_id,))
        db.commit()
        
        return jsonify({'success': True, 'message': 'Recap site deleted successfully'})
        
    except Exception as e:
        current_app.logger.error(f"Error deleting recap site: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@admin_bp.route('/api/generate-scraping-rules', methods=['POST'])
@login_required
@admin_required
def generate_scraping_rules():
    """Generate scraping rules using LLM"""
    try:
        data = request.get_json()
        site_name = data.get('site_name')
        base_url = data.get('base_url')
        sample_urls = data.get('sample_urls', [])
        
        if not site_name or not base_url or not sample_urls:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        current_app.logger.info(f"Generating rules for {site_name} with {len(sample_urls)} sample URLs")
        
        # Use LLM to analyze sample URLs and generate intelligent patterns
        from app.llm_services import get_llm_response
        
        # Create a prompt for the LLM to analyze the URLs and generate patterns
        prompt = f"""
You are a web scraping expert. I need you to analyze these sample URLs from {site_name} and generate regex patterns for scraping episode recaps.

Sample URLs:
{chr(10).join(sample_urls)}

Base URL: {base_url}

Please analyze the URL structure and generate three types of regex patterns:

1. LINK_PATTERNS: Patterns to find recap links in HTML (should capture href and link text)
2. TITLE_PATTERNS: Patterns to extract season/episode numbers from titles
3. CONTENT_PATTERNS: Patterns to extract the main recap content from HTML

For each type, provide 2-4 patterns that would work for this site. Consider:
- URL structure (paths, segments, naming conventions)
- Common HTML patterns for recap sites
- Episode numbering formats (S1E1, Season 1 Episode 1, etc.)
- Content container patterns (article, div with classes, etc.)

Respond in this exact JSON format:
{{
    "link_patterns": [
        "pattern1",
        "pattern2"
    ],
    "title_patterns": [
        "pattern1", 
        "pattern2"
    ],
    "content_patterns": [
        "pattern1",
        "pattern2"
    ]
}}

Only return the JSON, no other text.
"""
        
        # Get LLM response
        response_text, error = get_llm_response(prompt)
        
        if error:
            current_app.logger.error(f"LLM error generating rules: {error}")
            # Fallback to basic pattern generation
            return generate_basic_patterns(site_name, base_url, sample_urls)
        
        # Parse LLM response
        try:
            import json
            llm_rules = json.loads(response_text.strip())
            
            # Validate the response has the expected structure
            if not all(key in llm_rules for key in ['link_patterns', 'title_patterns', 'content_patterns']):
                raise ValueError("Invalid LLM response structure")
            
            # Ensure all patterns are lists
            for key in ['link_patterns', 'title_patterns', 'content_patterns']:
                if not isinstance(llm_rules[key], list):
                    llm_rules[key] = [llm_rules[key]]
            
            current_app.logger.info(f"Successfully generated LLM rules for {site_name}")
            
            return jsonify({
                'success': True,
                'rules': {
                    'link_patterns': json.dumps(llm_rules['link_patterns']),
                    'title_patterns': json.dumps(llm_rules['title_patterns']),
                    'content_patterns': json.dumps(llm_rules['content_patterns'])
                },
                'source': 'llm'
            })
            
        except (json.JSONDecodeError, ValueError) as e:
            current_app.logger.error(f"Failed to parse LLM response: {e}")
            current_app.logger.error(f"LLM response: {response_text}")
            # Fallback to basic pattern generation
            return generate_basic_patterns(site_name, base_url, sample_urls)
        
    except Exception as e:
        current_app.logger.error(f"Error generating scraping rules: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

def generate_basic_patterns(site_name, base_url, sample_urls):
    """Fallback basic pattern generation when LLM fails"""
    try:
        # Analyze URL structure to generate patterns
        url_segments = []
        for url in sample_urls:
            if url.strip():
                import urllib.parse
                parsed = urllib.parse.urlparse(url.strip())
                path_segments = [seg for seg in parsed.path.split('/') if seg]
                url_segments.extend(path_segments)
        
        # Generate site-specific link patterns based on URL structure
        link_patterns = []
        
        # Check if URLs contain common recap patterns
        if any('recap' in seg.lower() for seg in url_segments):
            link_patterns.append(r'<a[^>]+href="([^"]*recap[^"]*)"[^>]*>([^<]+)</a>')
        
        if any('episode' in seg.lower() for seg in url_segments):
            link_patterns.append(r'<a[^>]+href="([^"]*episode[^"]*)"[^>]*>([^<]+)</a>')
        
        # Check for season recap patterns
        if any('season' in seg.lower() for seg in url_segments):
            link_patterns.append(r'<a[^>]+href="([^"]*season[^"]*recap[^"]*)"[^>]*>([^<]+)</a>')
        
        # Check for show/series recap patterns
        if any('series' in seg.lower() or 'show' in seg.lower() for seg in url_segments):
            link_patterns.append(r'<a[^>]+href="([^"]*(?:series|show)[^"]*recap[^"]*)"[^>]*>([^<]+)</a>')
        
        # Check for common URL structures
        if any('/tv/' in url for url in sample_urls):
            link_patterns.append(r'<a[^>]+href="([^"]*\/tv\/[^"]*)"[^>]*>([^<]+)</a>')
        
        if any('/article/' in url for url in sample_urls):
            link_patterns.append(r'<a[^>]+href="([^"]*\/article\/[^"]*)"[^>]*>([^<]+)</a>')
        
        if not link_patterns:
            link_patterns = [
                r'<a[^>]+href="([^"]*)"[^>]*>([^<]*recap[^<]*)</a>',
                r'<a[^>]+href="([^"]*)"[^>]*>([^<]*episode[^<]*)</a>'
            ]
        
        # Standard title and content patterns (these are usually consistent across sites)
        title_patterns = [
            r'Season\s+(\d+).*Episode\s+(\d+)',
            r'S(\d+)E(\d+)',
            r'Episode\s+(\d+)',
            r'Season\s+(\d+)\s+Recap',  # Season recaps
            r'Series\s+Recap',  # Show/series recaps
            r'Show\s+Recap'  # Show recaps
        ]
        
        content_patterns = [
            r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
            r'<article[^>]*>(.*?)</article>',
            r'<div[^>]*class="[^"]*entry-content[^"]*"[^>]*>(.*?)</div>'
        ]
        
        import json
        
        return jsonify({
            'success': True,
            'rules': {
                'link_patterns': json.dumps(link_patterns),
                'title_patterns': json.dumps(title_patterns),
                'content_patterns': json.dumps(content_patterns)
            },
            'source': 'basic'
        })
        
    except Exception as e:
        current_app.logger.error(f"Error in basic pattern generation: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@admin_bp.route('/api/test-site-scraping/<int:site_id>', methods=['POST'])
@login_required
@admin_required
def test_site_scraping(site_id):
    """Test scraping for a specific site using its stored sample URLs"""
    try:
        db = get_db()
        
        # Get the site configuration
        site = db.execute("""
            SELECT site_name, base_url, sample_urls, link_patterns, title_patterns, content_patterns
            FROM recap_sites 
            WHERE id = ? AND is_active = 1
        """, (site_id,)).fetchone()
        
        if not site:
            return jsonify({'success': False, 'error': 'Site not found or inactive'}), 404
        
        # Parse sample URLs
        import json
        try:
            sample_urls = json.loads(site['sample_urls'] or '[]')
        except:
            sample_urls = []
        
        if not sample_urls:
            return jsonify({'success': False, 'error': 'No sample URLs found for this site'}), 400
        
        # Test scraping using the site's patterns
        current_app.logger.info(f"Testing scraping for {site['site_name']} with {len(sample_urls)} sample URLs")
        
        # Parse the scraping patterns
        try:
            link_patterns = json.loads(site['link_patterns'] or '[]')
            title_patterns = json.loads(site['title_patterns'] or '[]')
            content_patterns = json.loads(site['content_patterns'] or '[]')
        except:
            link_patterns = title_patterns = content_patterns = []
        
        # Test each sample URL
        test_results = []
        import requests
        import re
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        for url in sample_urls[:3]:  # Test first 3 URLs
            try:
                # Fetch the page
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code != 200:
                    test_results.append({
                        'url': url,
                        'title': f"HTTP {response.status_code}",
                        'status': 'error',
                        'error': f'Failed to fetch: HTTP {response.status_code}'
                    })
                    continue
                
                html = response.text
                
                # Extract title - try multiple methods
                title = "No title found"
                
                # Method 1: Try h1 tags first
                h1_matches = re.findall(r'<h1[^>]*>([^<]+)</h1>', html, re.IGNORECASE)
                if h1_matches:
                    # Filter out social media buttons
                    for h1_text in h1_matches:
                        h1_clean = h1_text.strip()
                        if not any(social in h1_clean.lower() for social in ['share on', 'tweet', 'facebook', 'linkedin']):
                            title = h1_clean
                            break
                
                # Method 2: Try title tag if h1 didn't work
                if title == "No title found":
                    title_match = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
                    if title_match:
                        title_text = title_match.group(1).strip()
                        # Filter out social media buttons
                        if not any(social in title_text.lower() for social in ['share on', 'tweet', 'facebook', 'linkedin']):
                            title = title_text
                
                # Method 3: Extract from URL if title tag is overridden
                if title == "No title found" or any(social in title.lower() for social in ['share on', 'tweet', 'facebook', 'linkedin']):
                    import urllib.parse
                    parsed_url = urllib.parse.urlparse(url)
                    path_parts = [part for part in parsed_url.path.split('/') if part]
                    if path_parts:
                        url_title = path_parts[-1].replace('-', ' ').title()
                        title = url_title
                
                # Decode HTML entities
                import html
                title = html.unescape(title)
                
                # Test episode info extraction
                episode_info = None
                for pattern in title_patterns:
                    match = re.search(pattern, title, re.IGNORECASE)
                    if match:
                        if len(match.groups()) == 2:
                            episode_info = {'season': int(match.group(1)), 'episode': int(match.group(2))}
                        elif len(match.groups()) == 1:
                            episode_info = {'season': 1, 'episode': int(match.group(1))}
                        break
                
                # Test content extraction
                content_found = False
                for pattern in content_patterns:
                    match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
                    if match:
                        content_found = True
                        break
                
                test_results.append({
                    'url': url,
                    'title': title,
                    'episode_info': episode_info,
                    'content_extracted': content_found,
                    'status': 'success'
                })
                
            except Exception as e:
                test_results.append({
                    'url': url,
                    'title': f"Error: {str(e)}",
                    'status': 'error',
                    'error': str(e)
                })
        
        return jsonify({
            'success': True,
            'site_name': site['site_name'],
            'results': test_results,
            'message': f'Tested {len(test_results)} sample URLs from {site["site_name"]}'
        })
        
    except Exception as e:
        current_app.logger.error(f"Error testing site scraping: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@admin_bp.route('/api/test-patterns', methods=['POST'])
@login_required
@admin_required
def test_patterns():
    """Test scraping patterns against sample URLs without saving to database"""
    try:
        data = request.get_json()
        site_name = data.get('site_name')
        base_url = data.get('base_url')
        sample_urls = data.get('sample_urls', [])
        link_patterns = data.get('link_patterns', [])
        title_patterns = data.get('title_patterns', [])
        content_patterns = data.get('content_patterns', [])
        
        if not site_name or not base_url or not sample_urls:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        current_app.logger.info(f"Testing patterns for {site_name} with {len(sample_urls)} sample URLs")
        
        # Test each sample URL
        test_results = []
        import requests
        import re
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        for url in sample_urls[:3]:  # Test first 3 URLs
            try:
                # Fetch the page
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code != 200:
                    test_results.append({
                        'url': url,
                        'title': f"HTTP {response.status_code}",
                        'status': 'error',
                        'error': f'Failed to fetch: HTTP {response.status_code}'
                    })
                    continue
                
                html = response.text
                
                # Extract title - try multiple methods
                title = "No title found"
                
                # Method 1: Try h1 tags first
                h1_matches = re.findall(r'<h1[^>]*>([^<]+)</h1>', html, re.IGNORECASE)
                if h1_matches:
                    # Filter out social media buttons
                    for h1_text in h1_matches:
                        h1_clean = h1_text.strip()
                        if not any(social in h1_clean.lower() for social in ['share on', 'tweet', 'facebook', 'linkedin']):
                            title = h1_clean
                            break
                
                # Method 2: Try title tag if h1 didn't work
                if title == "No title found":
                    title_match = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
                    if title_match:
                        title_text = title_match.group(1).strip()
                        # Filter out social media buttons
                        if not any(social in title_text.lower() for social in ['share on', 'tweet', 'facebook', 'linkedin']):
                            title = title_text
                
                # Method 3: Extract from URL if title tag is overridden
                if title == "No title found" or any(social in title.lower() for social in ['share on', 'tweet', 'facebook', 'linkedin']):
                    import urllib.parse
                    parsed_url = urllib.parse.urlparse(url)
                    path_parts = [part for part in parsed_url.path.split('/') if part]
                    if path_parts:
                        url_title = path_parts[-1].replace('-', ' ').title()
                        title = url_title
                
                # Decode HTML entities
                import html
                title = html.unescape(title)
                
                # Test episode info extraction
                episode_info = None
                for pattern in title_patterns:
                    match = re.search(pattern, title, re.IGNORECASE)
                    if match:
                        if len(match.groups()) == 2:
                            episode_info = {'season': int(match.group(1)), 'episode': int(match.group(2))}
                        elif len(match.groups()) == 1:
                            episode_info = {'season': 1, 'episode': int(match.group(1))}
                        break
                
                # Test content extraction
                content_found = False
                for pattern in content_patterns:
                    match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
                    if match:
                        content_found = True
                        break
                
                test_results.append({
                    'url': url,
                    'title': title,
                    'episode_info': episode_info,
                    'content_extracted': content_found,
                    'status': 'success'
                })
                
            except Exception as e:
                test_results.append({
                    'url': url,
                    'title': f"Error: {str(e)}",
                    'status': 'error',
                    'error': str(e)
                })
        
        return jsonify({
            'success': True,
            'site_name': site_name,
            'results': test_results,
            'message': f'Tested {len(test_results)} sample URLs for {site_name}'
        })
        
    except Exception as e:
        current_app.logger.error(f"Error testing patterns: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

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

@admin_bp.route('/api-usage-logs')
@login_required
@admin_required
def api_usage_logs():
    """
    Displays a log of all API calls made to external LLM services.

    This page retrieves records from the `api_usage` table and displays them
    in a tabular format, showing details like the provider, endpoint, token
    counts, and cost for each call.

    Returns:
        A rendered HTML template for the API usage logs page.
    """
    current_app.logger.info(f"Admin user {current_user.username if current_user.is_authenticated else 'Unknown'} accessed API usage logs.")
    db = database.get_db()
    # DEBUG: Log the database path being used
    try:
        db_path = db.execute("PRAGMA database_list;").fetchone()[2]
        current_app.logger.warning(f"[API Usage Logs] Using database file: {db_path}")
        # DEBUG: Check if api_usage table exists and row count
        table_exists = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='api_usage';").fetchone()
        if not table_exists:
            current_app.logger.warning("[API Usage Logs] Table 'api_usage' does NOT exist in this database.")
        else:
            row_count = db.execute("SELECT COUNT(*) FROM api_usage;").fetchone()[0]
            current_app.logger.warning(f"[API Usage Logs] Table 'api_usage' exists. Row count: {row_count}")
    except Exception as e:
        current_app.logger.error(f"[API Usage Logs] Debug DB check failed: {e}", exc_info=True)
    import datetime
    provider_filter = request.args.get('provider')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    query = (
        "SELECT id, timestamp, provider, endpoint, prompt_tokens, completion_tokens, total_tokens, cost_usd, processing_time_ms "
        "FROM api_usage WHERE 1=1"
    )
    params = []
    if provider_filter:
        query += " AND provider=?"
        params.append(provider_filter)
    if start_date:
        query += " AND timestamp>=?"
        params.append(f"{start_date} 00:00:00")
    if end_date:
        query += " AND timestamp<=?"
        params.append(f"{end_date} 23:59:59")
    query += " ORDER BY timestamp DESC LIMIT 200"
    logs = db.execute(query, params).fetchall()

    def safe_value(q, p=None):
        try:
            r = db.execute(q, p or []).fetchone()
            return r[0] if r and r[0] is not None else 0
        except Exception:
            return 0

    total_cost = safe_value("SELECT SUM(cost_usd) FROM api_usage")
    week_cost = safe_value("SELECT SUM(cost_usd) FROM api_usage WHERE timestamp >= DATETIME('now','-7 days')")
    openai_count = safe_value("SELECT COUNT(*) FROM api_usage WHERE provider='openai'")
    ollama_count = safe_value("SELECT COUNT(*) FROM api_usage WHERE provider='ollama'")
    # Convert timestamps to datetime objects for Jinja2 compatibility
    processed_logs = []
    for log in logs:
        log_dict = dict(log)
        ts = log_dict.get('timestamp')
        if ts and isinstance(ts, str):
            try:
                log_dict['timestamp'] = datetime.datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
            except Exception:
                log_dict['timestamp'] = None
        processed_logs.append(log_dict)
    return render_template(
        'admin_api_usage_logs.html',
        logs=processed_logs,
        title="API Usage Logs",
        total_cost=total_cost,
        week_cost=week_cost,
        openai_count=openai_count,
        ollama_count=ollama_count,
        provider_filter=provider_filter,
        start_date=start_date,
        end_date=end_date,
    )

@admin_bp.route('/sync-radarr', methods=['POST'])
@login_required
@admin_required
def sync_radarr():
    """
    Triggers a Radarr library synchronization task.

    A POST-only endpoint that calls the `sync_radarr_library` utility function.
    It flashes status messages to the user and redirects to the tasks page upon
    completion or failure.

    Returns:
        A redirect to the 'admin.tasks' page.
    """
    flash("Radarr library sync started...", "info")
    try:
        count = sync_radarr_library()
        flash(f"Radarr library sync completed successfully. {count} movies processed.", "success")
    except Exception as e:
        flash(f"Error during Radarr sync: {str(e)}", "danger") # Changed to danger for errors
        current_app.logger.error(f"Radarr sync error: {e}", exc_info=True)
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
    elif service == 'tautulli': # Added Tautulli service
        success, error_message = test_tautulli_connection_with_params(url, api_key)
    
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

    A POST-only endpoint that calls the `sync_tautulli_watch_history` utility.
    Flashes status messages and redirects to the tasks page.

    Returns:
        A redirect to the 'admin.tasks' page.
    """
    flash("Tautulli watch history sync started...", "info")
    try:
        count = sync_tautulli_watch_history()
        flash(f"Tautulli sync completed. {count} events processed.", "success")
    except Exception as e:
        flash(f"Error during Tautulli sync: {str(e)}", "danger") # Changed to danger for errors
        current_app.logger.error(f"Tautulli sync error: {e}", exc_info=True)
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
    notes = request.form.get('resolution_notes', '')
    db.execute(
        "UPDATE issue_reports SET status='resolved', resolved_by_admin_id=?, resolved_at=CURRENT_TIMESTAMP, resolution_notes=? WHERE id=?",
        (current_user.id, notes, report_id)
    )
    db.commit()
    flash('Report resolved.', 'success')
    return redirect(url_for('admin.issue_reports'))
