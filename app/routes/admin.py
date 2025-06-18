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
    """Admin dashboard summarizing counts of key objects."""
    db = database.get_db()
    movie_count = db.execute('SELECT COUNT(*) FROM radarr_movies').fetchone()[0]
    show_count = db.execute('SELECT COUNT(*) FROM sonarr_shows').fetchone()[0]
    user_count = db.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    plex_event_count = db.execute('SELECT COUNT(*) FROM plex_events').fetchone()[0]
    return render_template('admin_dashboard.html',
                           movie_count=movie_count,
                           show_count=show_count,
                           user_count=user_count,
                           plex_event_count=plex_event_count)

@admin_bp.route('/tasks')
@login_required
@admin_required
def tasks():
    """
    Renders the admin tasks page.

    This page provides a UI for administrators to trigger manual tasks
    such as library synchronization with Sonarr and Radarr.
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

    The logbook displays service sync statuses and Plex activity logs,
    with options for filtering. Data is fetched by a separate '/logbook/data' endpoint.
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
    Lists available log files.

    Scans the log directory for 'shownotes.log*' files and returns
    a sorted list of their filenames.

    Returns:
        flask.Response: JSON list of log filenames.
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
    Retrieves the last 100 lines of a specified log file.

    Args:
        filename (str): The name of the log file.

    Returns:
        flask.Response: JSON list of log lines, or an error response
                        if access is denied, file not found, or read error.
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
    Streams log file content in real-time using Server-Sent Events (SSE).

    Args:
        filename (str): The name of the log file to stream.

    Returns:
        flask.Response: An SSE stream of log lines.
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
    """Display and save service configuration settings."""
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
            ollama_url=?, pushover_key=?, pushover_token=?,
            plex_client_id=?, tautulli_url=?, tautulli_api_key=? WHERE id=?''', (
            request.form.get('radarr_url'),
            request.form.get('radarr_api_key'),
            request.form.get('sonarr_url'),
            request.form.get('sonarr_api_key'),
            request.form.get('bazarr_url'),
            request.form.get('bazarr_api_key'),
            request.form.get('ollama_url'),
            request.form.get('pushover_key'),
            request.form.get('pushover_token'),
            request.form.get('plex_client_id'),
            request.form.get('tautulli_url'),
            request.form.get('tautulli_api_key'),
            settings['id'] if settings else 1
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
    for k, v in defaults.items():
        if not merged_settings.get(k):
            merged_settings[k] = v
    site_url = request.url_root.rstrip('/')
    plex_webhook_url = url_for('main.plex_webhook', _external=True)

    sonarr_status = test_sonarr_connection()
    radarr_status = test_radarr_connection()
    bazarr_status = test_bazarr_connection()
    ollama_status = test_ollama_connection()
    tautulli_status = test_tautulli_connection() # Added Tautulli status

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
        tautulli_status=tautulli_status # Added Tautulli status
    )

@admin_bp.route('/sync-sonarr', methods=['POST'])
@login_required
@admin_required
def sync_sonarr():
    """Triggers a Sonarr library synchronization task."""
    flash("Sonarr library sync started...", "info")
    try:
        count = sync_sonarr_library()
        flash(f"Sonarr library sync completed successfully. {count} shows processed.", "success")
    except Exception as e:
        flash(f"Error during Sonarr sync: {str(e)}", "danger") # Changed to danger for errors
        current_app.logger.error(f"Sonarr sync error: {e}", exc_info=True)
    return redirect(url_for('admin.tasks'))

@admin_bp.route('/sync-radarr', methods=['POST'])
@login_required
@admin_required
def sync_radarr():
    """Triggers a Radarr library synchronization task."""
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
    """Generates a secure URL-safe secret, typically for Plex webhook or similar."""
    secret = secrets.token_urlsafe(32)
    return jsonify({'secret': secret})


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
    """Triggers a Tautulli watch history synchronization task."""
    flash("Tautulli watch history sync started...", "info")
    try:
        count = sync_tautulli_watch_history()
        flash(f"Tautulli sync completed. {count} events processed.", "success")
    except Exception as e:
        flash(f"Error during Tautulli sync: {str(e)}", "danger") # Changed to danger for errors
        current_app.logger.error(f"Tautulli sync error: {e}", exc_info=True)
    return redirect(url_for('admin.tasks'))
