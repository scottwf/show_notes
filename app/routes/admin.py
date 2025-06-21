"""
Admin Blueprint for ShowNotes

This module defines the blueprint for the administrative interface of the ShowNotes
application. It includes routes for all admin-facing pages and functionalities,
such as the dashboard, settings management, task execution, and log viewing.

All routes in this blueprint are prefixed with `/admin` and require the user to be
logged in and have administrative privileges, enforced by the `@admin_required`
decorator.

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
    {'title': 'Test LLM Summary', 'category': 'Admin Page', 'url_func': lambda: url_for('admin.test_llm_summary')},
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

@admin_bp.route('/dashboard', methods=['GET'])
@login_required
@admin_required
def dashboard():
    """
    Renders the admin dashboard page.

    This page provides a high-level overview of the application's state by
    displaying key statistics, such as the number of movies, shows, users,
    and Plex events currently in the database.

    Returns:
        A rendered HTML template for the admin dashboard.
    """
    db = database.get_db()
    def safe_value(query):
        """Execute a scalar SQL query and return a numeric result or 0."""
        try:
            result = db.execute(query).fetchone()
            return result[0] if result and result[0] is not None else 0
        except Exception:
            return 0

    movie_count = safe_value('SELECT COUNT(*) FROM radarr_movies')
    show_count = safe_value('SELECT COUNT(*) FROM sonarr_shows')
    user_count = safe_value('SELECT COUNT(*) FROM users')
    plex_event_count = safe_value('SELECT COUNT(*) FROM plex_events')

    radarr_week_count = safe_value(
        "SELECT COUNT(*) FROM radarr_movies WHERE last_synced_at >= DATETIME('now', '-7 days')"
    )
    sonarr_week_count = safe_value(
        "SELECT COUNT(*) FROM sonarr_shows WHERE last_synced_at >= DATETIME('now', '-7 days')"
    )

    openai_cost_week = safe_value(
        "SELECT SUM(cost_usd) FROM api_usage WHERE provider='openai' AND timestamp >= DATETIME('now', '-7 days')"
    )
    openai_call_count_week = safe_value(
        "SELECT COUNT(*) FROM api_usage WHERE provider='openai' AND timestamp >= DATETIME('now', '-7 days')"
    )
    ollama_avg_ms = safe_value(
        "SELECT AVG(processing_time_ms) FROM api_usage WHERE provider='ollama' AND timestamp >= DATETIME('now', '-7 days')"
    )
    ollama_call_count_week = safe_value(
        "SELECT COUNT(*) FROM api_usage WHERE provider='ollama' AND timestamp >= DATETIME('now', '-7 days')"
    )

    return render_template(
        'admin_dashboard.html',
        movie_count=movie_count,
        show_count=show_count,
        user_count=user_count,
        plex_event_count=plex_event_count,
        radarr_week_count=radarr_week_count,
        sonarr_week_count=sonarr_week_count,
        openai_cost_week=openai_cost_week,
        openai_call_count_week=openai_call_count_week,
        ollama_avg_ms=ollama_avg_ms,
        ollama_call_count_week=ollama_call_count_week,
    )


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
            plex_client_id=?, tautulli_url=?, tautulli_api_key=? WHERE id=?''', (
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

    for k, v in defaults.items():
        if not merged_settings.get(k): # This will only apply to plex_client_id, secret, redirect_uri if not set
            merged_settings[k] = v
    site_url = request.url_root.rstrip('/')
    plex_webhook_url = url_for('main.plex_webhook', _external=True)

    sonarr_status = test_sonarr_connection()
    radarr_status = test_radarr_connection()
    bazarr_status = test_bazarr_connection()
    ollama_status = test_ollama_connection()
    tautulli_status = test_tautulli_connection() # Added Tautulli status

    # Fetch available Ollama models for dropdown
    ollama_models = []
    ollama_url = merged_settings.get('ollama_url')
    if ollama_url:
        try:
            import requests
            resp = requests.get(ollama_url.rstrip('/') + '/api/tags', timeout=5)
            if resp.ok:
                data = resp.json()
                ollama_models = [m['model'] for m in data.get('models', [])]
        except Exception as e:
            current_app.logger.warning(f"Could not fetch Ollama models: {e}")

    # Ensure the saved model is always in the list
    saved_model = merged_settings.get('ollama_model_name')
    if saved_model and saved_model not in ollama_models:
        ollama_models.insert(0, saved_model)

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
        sonarr_status=sonarr_status,
        radarr_status=radarr_status,
        bazarr_status=bazarr_status,
        ollama_status=ollama_status,
        tautulli_status=tautulli_status, # Added Tautulli status
        ollama_models=ollama_models,
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

@admin_bp.route('/test-llm-summary', methods=['GET', 'POST'])
@login_required
@admin_required
def test_llm_summary():
    """
    Renders a page for testing LLM character summary generation.

    This page provides a form where an administrator can input a character, show,
    and episode details to manually test the summary generation process.

    On a POST request, it builds a prompt using the form data, calls the
    configured LLM service, and displays the generated prompt and the LLM's
    response on the page.

    Returns:
        A rendered HTML template for the LLM test page, including any
        generated results from a POST request.
    """
    current_app.logger.info(f"Admin user {current_user.username if current_user.is_authenticated else 'Unknown'} accessed Test LLM Summary page.")

    # Initialize variables
    test_character = ''
    test_show = ''
    test_season = 1
    test_episode = 1
    preferred_provider = get_setting('preferred_llm_provider') or 'ollama'
    prompt_options = {
        'include_relationships': True,
        'include_motivations': True,
        'include_quote': True,
        'tone': 'tv_expert'
    }
    generated_prompt = ''
    llm_response = None
    error_message = None
    card_data = None

    if request.method == 'POST':
        # Get values from the submitted form
        test_character = request.form.get('test_character', '')
        test_show = request.form.get('test_show', '')
        test_season = int(request.form.get('test_season', 1))
        test_episode = int(request.form.get('test_episode', 1))
        preferred_provider = request.form.get('preferred_provider', preferred_provider)
        prompt_options = {
            'include_relationships': 'include_relationships' in request.form,
            'include_motivations': 'include_motivations' in request.form,
            'include_quote': 'include_quote' in request.form,
            'tone': request.form.get('tone', 'tv_expert')
        }

        # Build prompt and call LLM
        generated_prompt = prompt_builder.build_character_prompt(
            character=test_character,
            show=test_show,
            season=test_season,
            episode=test_episode,
            options=prompt_options
        )
        llm_response, error_message = get_llm_response(generated_prompt, llm_model_name=None, provider=preferred_provider)
        if llm_response:
            card_data = llm_response

    return render_template('admin_test_llm_summary.html',
                           test_character=test_character,
                           test_show=test_show,
                           test_season=test_season,
                           test_episode=test_episode,
                           prompt_options=prompt_options,
                           generated_prompt=generated_prompt,
                           llm_response=llm_response,
                           error_message=error_message,
                           preferred_provider=preferred_provider,
                           card_data=card_data,
                           title="Test LLM Summary Generation")

@admin_bp.route('/api/test-llm-summary', methods=['POST'])
@login_required
@admin_required
def api_test_llm_summary():
    """
    API endpoint to run an LLM summary test and return results as JSON.

    This provides the backend functionality for the LLM test page. It accepts
    test parameters as a JSON payload, builds the prompt, calls the appropriate
    LLM service, and returns all the inputs and outputs in a JSON response.

    JSON Payload:
        - test_character (str)
        - test_show (str)
        - test_season (int)
        - test_episode (int)
        - preferred_provider (str)
        - prompt_options (dict)

    Returns:
        flask.Response: A JSON response containing the test results or an error message.
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON payload'}), 400

    test_character = data.get('test_character', '')
    test_show = data.get('test_show', '')
    test_season = int(data.get('test_season', 1))
    test_episode = int(data.get('test_episode', 1))
    preferred_provider = data.get('preferred_provider') or get_setting('preferred_llm_provider') or 'ollama'
    prompt_options = data.get('prompt_options', {
        'include_relationships': True,
        'include_motivations': True,
        'include_quote': True,
        'tone': 'tv_expert'
    })

    # Build prompt
    generated_prompt = prompt_builder.build_character_prompt(
        character=test_character,
        show=test_show,
        season=test_season,
        episode=test_episode,
        options=prompt_options
    )

    # Determine model name if provider is Ollama
    ollama_model_name = None
    if preferred_provider == 'ollama':
        ollama_model_name = get_setting('ollama_model_name')
        if not ollama_model_name:
            current_app.logger.error('Ollama is selected, but no Ollama model name is configured in settings.')
            return jsonify({'error': 'Ollama is selected, but no Ollama model name is configured in settings.'}), 400

    # Call LLM
    try:
        llm_response, error_message = get_llm_response(generated_prompt, llm_model_name=ollama_model_name, provider=preferred_provider)
    except Exception as e:
        current_app.logger.error(f"Error calling LLM provider {preferred_provider}: {e}", exc_info=True)
        return jsonify({'error': f'Error calling LLM provider {preferred_provider}: {e}'}), 500

    # Prepare response
    response_data = {
        'test_character': test_character,
        'test_show': test_show,
        'test_season': test_season,
        'test_episode': test_episode,
        'preferred_provider': preferred_provider,
        'prompt_options': prompt_options,
        'generated_prompt': generated_prompt,
        'llm_response': llm_response,
        'error_message': error_message
    }
    if not llm_response and not error_message:
        response_data['error_message'] = 'No response received from LLM. This may mean the provider is not configured, returned an empty response, or the model is missing.'
    return jsonify(response_data)

@admin_bp.route('/view-prompts')
@login_required
@admin_required
def view_prompts():
    """
    Displays all available LLM prompt templates.

    This page introspects the `prompt_builder.py` and `prompts.py` modules to
    find and display the structure and example output of all defined prompts.
    It helps administrators understand and verify the prompts being sent to the
    LLM services.

    Returns:
        A rendered HTML template showing lists of static and builder prompts.
    """
    current_app.logger.info(f"Admin user {current_user.username if current_user.is_authenticated else 'Unknown'} accessed View Prompts page.")

    builder_prompts = []
    try:
        builder_functions = inspect.getmembers(prompt_builder, inspect.isfunction)
        for name, func in builder_functions:
            if name.startswith('build_'):
                prompt_text = f"Could not generate example for {name}. Review function signature and test manually."
                source_info = f'prompt_builder.py - {name}()'
                docstring = inspect.getdoc(func)
                if docstring:
                    prompt_text = f"Docstring:\n{docstring}\n\n{prompt_text}"

                try:
                    if name == 'build_quote_prompt':
                        prompt_text = func(character='PlaceholderCharacter', show='PlaceholderShow')
                    elif name == 'build_relationships_prompt':
                        prompt_text = func(character='PlaceholderCharacter', show='PlaceholderShow')
                    elif name == 'build_character_prompt':
                        prompt_text = func(character='PlaceholderCharacter', show='PlaceholderShow',
                                           options={'include_quote': True, 'include_relationships': True, 'include_motivations': True})
                    # Add more specific handlers if other build_ functions have simple, common call patterns

                    builder_prompts.append({'name': name, 'text': prompt_text, 'source': source_info, 'docstring': docstring})
                except Exception as e:
                    current_app.logger.warning(f"Could not generate example for prompt function {name}: {e}")
                    # Keep the docstring and error message if example generation failed
                    builder_prompts.append({'name': name, 'text': prompt_text, 'source': source_info, 'docstring': docstring, 'error': str(e)})

    except Exception as e:
        current_app.logger.error(f"Error inspecting prompt_builder.py: {e}", exc_info=True)
        flash("Error loading prompts from prompt_builder.py.", "danger")

    static_prompts = []
    try:
        for var_name, var_value in inspect.getmembers(prompts):
            if isinstance(var_value, str) and "PROMPT" in var_name.upper(): # Convention
                static_prompts.append({'name': var_name, 'text': var_value, 'source': 'prompts.py'})
    except Exception as e:
        current_app.logger.error(f"Error inspecting prompts.py: {e}", exc_info=True)
        flash("Error loading prompts from prompts.py.", "danger")

    return render_template('admin_view_prompts.html',
                           builder_prompts=builder_prompts,
                           static_prompts=static_prompts,
                           title="View Prompts")

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
