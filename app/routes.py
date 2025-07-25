import os
import json
import requests
import glob
import time
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, flash, current_app, send_from_directory, Response, stream_with_context
from werkzeug.security import generate_password_hash
import urllib.parse

from flask_login import login_required, current_user, login_user
from functools import wraps
from flask import abort

from . import database, utils
from .utils import sync_sonarr_library, sync_radarr_library, test_sonarr_connection, test_radarr_connection, test_bazarr_connection, test_ollama_connection, get_sonarr_poster, get_radarr_poster

PLEX_HEADERS = {
    'X-Plex-Client-Identifier': os.environ.get('PLEX_CLIENT_ID', 'shownotes'),
    'X-Plex-Product': 'ShowNotes',
    'X-Plex-Version': '0.1',
}

import sqlite3 # Add this import at the top of the file if not already present, or near other db imports

bp = Blueprint('main', __name__)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, 'is_admin', False):
            current_app.logger.warning(f"Admin access denied for user {current_user.username if current_user.is_authenticated else 'Anonymous'} to {request.endpoint}")
            flash('You must be an administrator to access this page.', 'danger')
            abort(403) # Forbidden
        return f(*args, **kwargs)
    return decorated_function



def is_onboarding_complete():
    try:
        db = database.get_db()
        admin_user = db.execute('SELECT id FROM users WHERE is_admin = 1 LIMIT 1').fetchone()
        settings_record = db.execute('SELECT id FROM settings LIMIT 1').fetchone()
        return admin_user is not None and settings_record is not None
    except sqlite3.OperationalError as e:
        # This typically means the table doesn't exist, so onboarding is not complete.
        return False


@bp.before_request  # Correct decorator for Blueprints
def check_onboarding():
    # Determine the list of endpoints exempt from the onboarding check
    # These typically include onboarding itself, static files, and the entire auth flow.
    exempt_endpoints = [
        'main.onboarding',
        'main.onboarding_services',  # Allow both onboarding steps
        'main.onboarding_test_service',  # Allow AJAX service test during onboarding
        'static',
        'main.test_api', # Assuming this is for Pushover/API tests during onboarding
        'main.login',             # Plex login initiation
        'main.plex_callback',     # Plex callback URL
        'main.login_plex_start',  # Your custom route that starts Plex OAuth
        'main.login_plex_poll',   # Your custom route that polls Plex PIN
        'main.plex_logout',       # Allow logout even if onboarding isn't done
        'main.plex_webhook'       # Allow Plex webhook to be processed regardless of onboarding state
    ]
    
    # If onboarding is not complete and the current request is not for an exempt endpoint,
    # redirect to the onboarding page.
    if not is_onboarding_complete() and request.endpoint not in exempt_endpoints:
        # Also, ensure we are not already on the onboarding page to prevent redirect loops
        # though request.endpoint check should cover this for 'main.onboarding'.
        if request.path != url_for('main.onboarding'): # Extra safety for path
            flash('Initial setup required. Please complete the onboarding process.', 'info')
            return redirect(url_for('main.onboarding'))


@bp.route('/admin/dashboard', methods=['GET'], endpoint='admin_dashboard')
def admin_dashboard():
    if not session.get('is_admin', False):
        flash('You must be an administrator to view this page.', 'error')
        return redirect(url_for('main.home'))
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


# --- Admin Link Plex Account ---
@bp.route('/admin/link-plex/start', methods=['GET'])
def admin_link_plex_start():
    """Start Plex OAuth for admin account linking."""
    import requests
    client_id = os.environ.get('PLEX_CLIENT_ID', 'shownotes')
    headers = {
        'X-Plex-Client-Identifier': client_id,
        'X-Plex-Product': 'ShowNotes',
        'X-Plex-Version': '0.1',
    }
    r = requests.post('https://plex.tv/api/v2/pins.json', headers=headers)
    data = r.json()
    session['plex_pin_id'] = data['id']
    session['plex_client_id'] = client_id
    session['plex_link_admin'] = True  # Mark this as an admin link flow
    auth_url = (
        f"https://app.plex.tv/auth/#!?clientID={client_id}"
        f"&code={data['code']}&context%5Bdevice%5D%5Bproduct%5D=ShowNotes"
    )
    return jsonify({'authUrl': auth_url})

@bp.route('/admin/link-plex/callback', methods=['GET'])
def admin_link_plex_callback():
    """Callback for Plex OAuth admin linking (polls for PIN, updates admin user)."""
    import requests
    from flask_login import current_user
    pin_id = session.get('plex_pin_id')
    client_id = session.get('plex_client_id')
    if not pin_id or not client_id or not session.get('is_admin'):
        flash('Missing session info. Please try linking again.', 'danger')
        return redirect(url_for('main.admin_dashboard'))
    # Poll for Plex PIN auth
    poll_url = f'https://plex.tv/api/v2/pins/{pin_id}'
    headers = {
        'X-Plex-Client-Identifier': client_id,
        'Accept': 'application/json',
    }
    for _ in range(60):
        r = requests.get(poll_url, headers=headers)
        if r.status_code != 200:
            break
        data = r.json()
        if data.get('authToken'):
            token = data['authToken']
            # Get user info from Plex
            user_r = requests.get(
                'https://plex.tv/api/v2/user',
                headers={**headers, 'X-Plex-Token': token},
            )
            user = user_r.json()
            # Update the admin user record in DB
            db = database.get_db()
            admin_user = db.execute('SELECT id FROM users WHERE is_admin = 1 LIMIT 1').fetchone()
            if admin_user:
                db.execute('UPDATE users SET plex_id=?, plex_token=? WHERE id=?', (user['id'], token, admin_user['id']))
                db.commit()
                session['plex_token'] = token
                session['plex_id'] = user['id']
                flash('Plex account linked to admin successfully!', 'success')
            else:
                flash('Could not find admin user to update.', 'danger')
            return redirect(url_for('main.admin_dashboard'))
        import time
        time.sleep(1)
    flash('Plex linking timed out. Please try again.', 'danger')
    return redirect(url_for('main.admin_dashboard'))


@bp.route('/admin/tasks')
@login_required
@admin_required
def admin_tasks():
    return render_template('admin_tasks.html', title='Admin Tasks')


@bp.route('/admin/logs', methods=['GET'], endpoint='admin_logs_view')
@login_required
@admin_required
def admin_logs_view():
    return render_template('admin_logs.html', title='View Logs')

@bp.route('/admin/logs/list', methods=['GET'], endpoint='admin_logs_list')
@login_required
@admin_required
def admin_logs_list():
    log_dir = os.path.join(os.path.dirname(current_app.root_path), 'logs')
    log_files_paths = glob.glob(os.path.join(log_dir, 'shownotes.log*'))
    log_filenames = sorted([os.path.basename(f) for f in log_files_paths])
    return jsonify(log_filenames)

@bp.route('/admin/logs/get/<path:filename>', methods=['GET'], endpoint='admin_get_log_content')
@login_required
@admin_required
def admin_get_log_content(filename):
    log_dir = os.path.join(os.path.dirname(current_app.root_path), 'logs')
    file_path = os.path.join(log_dir, filename)

    # Security Check
    if not os.path.abspath(file_path).startswith(os.path.abspath(log_dir)):
        current_app.logger.warning(f"Log access rejected for {filename} due to path traversal attempt.")
        return jsonify({"error": "Access denied"}), 403

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        return jsonify(lines[-100:]) # Return last 100 lines
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404
    except Exception as e:
        current_app.logger.error(f"Error reading log file {filename}: {e}")
        return jsonify({"error": str(e)}), 500

@bp.route('/admin/logs/stream/<path:filename>', methods=['GET'], endpoint='admin_stream_log_content')
@login_required
@admin_required
def admin_stream_log_content(filename):
    log_dir = os.path.join(os.path.dirname(current_app.root_path), 'logs')
    file_path = os.path.join(log_dir, filename)

    # Security Check
    if not os.path.abspath(file_path).startswith(os.path.abspath(log_dir)):
        current_app.logger.warning(f"Log stream access rejected for {filename} due to path traversal attempt.")
        # For SSE, returning a non-200 response might be handled by client-side error events
        return Response("data: ERROR: Access Denied\n\n", mimetype='text/event-stream', status=403)

    if not os.path.exists(file_path):
        return Response("data: ERROR: File Not Found\n\n", mimetype='text/event-stream', status=404)

    def generate_log_updates(file_path_stream):
        try:
            with open(file_path_stream, 'r', encoding='utf-8') as f:
                # Send last N lines first (e.g. last 10 lines)
                f.seek(0, os.SEEK_END)
                file_size = f.tell()

                # Attempt to send the last few lines immediately
                # This is a simplified approach; a more robust one would handle small files
                # or read in chunks backwards.
                num_initial_lines = 10
                if file_size > 0:
                    # Try to find the start of the 10th to last line
                    # This is approximate and might not be perfect
                    approx_avg_line_length = 100 # Assume average line length
                    seek_pos = max(0, file_size - (num_initial_lines * approx_avg_line_length))
                    f.seek(seek_pos)
                    if seek_pos > 0: # if not at the beginning, discard the first partial line
                        f.readline()

                    initial_lines = f.readlines() # Read remaining lines up to the end
                    for line in initial_lines:
                         yield f"data: {line.rstrip()}\n\n"

                # Now, start streaming new lines
                while True:
                    line = f.readline()
                    if not line:
                        time.sleep(0.5)  # Wait for new lines
                        continue
                    yield f"data: {line.rstrip()}\n\n"
        except Exception as e:
            current_app.logger.error(f"Error streaming log file {file_path_stream}: {e}")
            yield f"data: ERROR: Could not stream log: {str(e)}\n\n"

    return Response(stream_with_context(generate_log_updates(file_path)), mimetype='text/event-stream')

@bp.route('/admin/settings', methods=['GET', 'POST'], endpoint='admin_settings')
def admin_settings():
    db = database.get_db()
    # Get admin user (first admin found)
    user = db.execute('SELECT * FROM users WHERE is_admin=1 LIMIT 1').fetchone()
    # Get settings (first row)
    settings = db.execute('SELECT * FROM settings LIMIT 1').fetchone()
    if request.method == 'POST':
        print(f"DEBUG: Session at start of onboarding POST: {list(session.items())}")
        # Update admin user
        username = request.form.get('username')
        password = request.form.get('password')
        if username and user:
            db.execute('UPDATE users SET username=? WHERE id=?', (username, user['id']))
        if password:
            from werkzeug.security import generate_password_hash
            pw_hash = generate_password_hash(password)
            db.execute('UPDATE users SET password_hash=? WHERE id=?', (pw_hash, user['id']))
        # Update settings
        db.execute('''UPDATE settings SET 
            radarr_url=?, radarr_api_key=?,
            sonarr_url=?, sonarr_api_key=?,
            bazarr_url=?, bazarr_api_key=?,
            ollama_url=?, pushover_key=?, pushover_token=?,
            plex_client_id=?
            WHERE id=?''', (
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
            settings['id'] if settings else 1 # Values for plex_client_secret and plex_redirect_uri removed
        ))
        db.commit()
        # Reload updated info
        user = db.execute('SELECT * FROM users WHERE is_admin=1 LIMIT 1').fetchone()
        settings = db.execute('SELECT * FROM settings LIMIT 1').fetchone()
    import socket
    # Provide smart defaults for Plex OAuth fields if missing
    # Smart default for redirect_uri: use https for shownotes.chitekmedia.club
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
    # Merge defaults into settings for template
    merged_settings = dict(settings) if settings else {}
    for k, v in defaults.items():
        if not merged_settings.get(k):
            merged_settings[k] = v
    site_url = request.url_root.rstrip('/') # Restore site_url
    plex_webhook_url = url_for('main.plex_webhook', _external=True) # Define plex_webhook_url

    # Perform connection tests
    sonarr_status = test_sonarr_connection()
    radarr_status = test_radarr_connection()
    bazarr_status = test_bazarr_connection()
    ollama_status = test_ollama_connection()

    return render_template(
        'admin_settings.html',
        user=user,                # Pass user object
        settings=merged_settings, # Pass the merged settings (defaults + DB)
        site_url=site_url,        # Pass site_url
        plex_webhook_url=plex_webhook_url,
        sonarr_status=sonarr_status,
        radarr_status=radarr_status,
        bazarr_status=bazarr_status,
        ollama_status=ollama_status
    )


@bp.route('/admin/sync-radarr', methods=['POST'], endpoint='admin_sync_radarr')
def admin_sync_radarr():
    if not session.get('is_admin', False):
        flash("You must be an administrator to perform this action.", "error")
        return redirect(url_for('main.home'))

    flash("Radarr library sync started...", "info")
    try:
        result = sync_radarr_library()
        if result.get('status') == 'success':
            flash(f"Radarr library sync completed successfully.\n{result['synced']} synced, {result['added']} added and {result['updated']} updated", "success")
        else:
            flash(f"Radarr sync error: {result.get('message', 'Unknown error')}", "error")
    except Exception as e:
        flash(f"Error during Radarr sync: {str(e)}", "error")
        current_app.logger.error(f"Radarr sync error: {e}", exc_info=True)
    return redirect(url_for('main.admin_tasks'))

@bp.route('/admin/sync-sonarr', methods=['POST'], endpoint='admin_sync_sonarr')
def admin_sync_sonarr():
    if not session.get('is_admin', False):
        flash("You must be an administrator to perform this action.", "error")
        return redirect(url_for('main.home'))

    flash("Sonarr library sync started...", "info")
    try:
        result = sync_sonarr_library()
        if result.get('status') == 'success':
            flash(f"Sonarr library sync completed successfully.\n{result['synced']} synced, {result['added']} added and {result['updated']} updated", "success")
        else:
            flash(f"Sonarr sync error: {result.get('message', 'Unknown error')}", "error")
    except Exception as e:
        flash(f"Error during Sonarr sync: {str(e)}", "error")
        current_app.logger.error(f"Sonarr sync error: {e}", exc_info=True)
    return redirect(url_for('main.admin_tasks'))


# In-memory cache for last Plex event (for demo; replace with persistent storage later)
last_plex_event = None

@bp.route('/admin/gen_plex_secret', methods=['POST'])
def gen_plex_secret():
    import secrets
    secret = secrets.token_urlsafe(32)
    return jsonify({'secret': secret})

@bp.route('/plex/webhook', methods=['POST'])
def plex_webhook():
    from flask import request
    import json as pyjson
    try:
        # Plex sends JSON or form-encoded data; handle both
        if request.is_json:
            payload = request.get_json()
        else:
            payload = request.form.get('payload')
            if payload:
                payload = pyjson.loads(payload)
            else:
                payload = {}
        current_app.logger.info("--- Received Plex Webhook POST ---")
        current_app.logger.info(f"Webhook payload: {pyjson.dumps(payload, indent=2)}")
        # Store the last event in memory for backward compatibility
        global last_plex_event
        last_plex_event = payload
        # Extract fields for DB
        event_type = payload.get('event')
        event_type = payload.get('event')
        raw_json_payload = pyjson.dumps(payload) # Store the entire payload
        client_ip = request.remote_addr

        # --- Log to plex_activity_log --- 
        activity_event_types = ['media.play', 'media.pause', 'media.resume', 'media.stop', 'media.scrobble']
        if event_type in activity_event_types:
            try:
                db_activity = database.get_db()
                metadata = payload.get('Metadata', {})
                account = payload.get('Account', {})
                player = payload.get('Player', {})

                plex_username = account.get('title')
                player_title = player.get('title')
                player_uuid = player.get('uuid')
                session_key = metadata.get('sessionKey')
                rating_key = metadata.get('ratingKey')
                parent_rating_key = metadata.get('parentRatingKey')
                grandparent_rating_key = metadata.get('grandparentRatingKey')
                media_type_activity = metadata.get('type')
                title_activity = metadata.get('title')
                show_title_activity = metadata.get('grandparentTitle') if media_type_activity == 'episode' else None
                
                season_episode_str = None
                if media_type_activity == 'episode':
                    season_num = metadata.get('parentIndex')
                    episode_num = metadata.get('index')
                    if season_num is not None and episode_num is not None:
                        season_episode_str = f"S{str(season_num).zfill(2)}E{str(episode_num).zfill(2)}"

                # --- Extract TMDB ID from GUIDs ---
                tmdb_id = None
                guids = metadata.get('Guid')
                if isinstance(guids, list):
                    for guid_item in guids:
                        guid_str = guid_item.get('id', '')
                        if guid_str.startswith('tmdb://'):
                            try:
                                tmdb_id = int(guid_str.split('//')[1])
                                current_app.logger.info(f"Extracted tmdb_id '{tmdb_id}' from Guid list.")
                                break # Found it
                            except (ValueError, IndexError):
                                current_app.logger.warning(f"Could not parse tmdb_id from guid: {guid_str}")
                
                if not tmdb_id:
                    guid_str = metadata.get('guid')
                    if isinstance(guid_str, str) and 'tmdb://' in guid_str:
                        import re
                        match = re.search(r'tmdb://(\d+)', guid_str)
                        if match:
                            try:
                                tmdb_id = int(match.group(1))
                                current_app.logger.info(f"Extracted tmdb_id '{tmdb_id}' from guid string.")
                            except ValueError:
                                current_app.logger.warning(f"Could not parse tmdb_id from guid string: {guid_str}")

                view_offset_ms = metadata.get('viewOffset')
                duration_ms = metadata.get('duration')

                sql_insert_activity = """
                    INSERT INTO plex_activity_log (
                        event_type, plex_username, player_title, player_uuid, session_key,
                        rating_key, parent_rating_key, grandparent_rating_key, media_type,
                        title, show_title, season_episode, view_offset_ms, duration_ms, tmdb_id, raw_payload
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                params_activity = (
                    event_type, plex_username, player_title, player_uuid, session_key,
                    rating_key, parent_rating_key, grandparent_rating_key, media_type_activity,
                    title_activity, show_title_activity, season_episode_str, view_offset_ms, duration_ms, tmdb_id, raw_json_payload
                )
                db_activity.execute(sql_insert_activity, params_activity)
                db_activity.commit()
                current_app.logger.info(f"Logged event '{event_type}' for '{title_activity}' to plex_activity_log.")
            except Exception as e_activity:
                current_app.logger.error(f"Error logging to plex_activity_log: {e_activity}", exc_info=True)

        # Original logging to plex_events (only for media.play)
        if event_type == 'media.play':
            # Insert into DB only if it's a 'media.play' (start) event
            db = database.get_db()
            db.execute('''INSERT INTO plex_events (event_type, metadata, client_ip)
                          VALUES (?, ?, ?)''',
                       (event_type, raw_json_payload, client_ip))
            db.commit()
            print(f'Logged Plex media.play event: {payload}') # Added print for confirmation
        else:
            print(f'Skipped Plex event (not media.play): {event_type}') # Added print for skipped events

        # For poster caching and other logic, we still need to parse details from the payload
        account = payload.get('Account', {})
        # user_id = account.get('id') # Not directly inserted, but useful if other logic needs it
        # user_name = account.get('title') # Not directly inserted
        metadata_dict = payload.get('Metadata', {}) # Renamed to avoid conflict with column name
        media_type = metadata_dict.get('type')
        show_title = metadata_dict.get('grandparentTitle') if media_type == 'episode' else metadata_dict.get('title')
        # episode_title = metadata_dict.get('title') if media_type == 'episode' else None # Not used by poster logic below
        # season = metadata_dict.get('parentIndex') if media_type == 'episode' else None # Not used
        # episode = metadata_dict.get('index') if media_type == 'episode' else None # Not used
        # summary = metadata_dict.get('summary') # Not used

        # Poster caching for Sonarr/Radarr
        import re, os
        poster_url = None
        poster_path = None
        clean_name = None
        if media_type == 'episode' and show_title:
            clean_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', show_title.lower())
            poster_url = get_sonarr_poster(show_title)
        elif media_type == 'movie' and show_title:
            clean_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', show_title.lower())
            poster_url = get_radarr_poster(show_title)
        if poster_url and clean_name:
            ext = os.path.splitext(poster_url)[-1].split('?')[0]
            if ext.lower() not in ['.jpg', '.jpeg', '.png', '.webp']:
                ext = '.jpg'
            poster_path = os.path.join(os.path.dirname(__file__), 'static', 'poster', f'poster_{clean_name}{ext}')
            if not os.path.exists(poster_path):
                try:
                    resp = requests.get(poster_url, timeout=10)
                    if resp.status_code == 200:
                        with open(poster_path, 'wb') as f:
                            f.write(resp.content)
                        print(f'Cached poster to {poster_path}')
                except Exception as e:
                    print(f'Failed to cache poster: {e}')
        print('Received and logged Plex webhook:', payload)
        return '', 200
    except Exception as e:
        print('Error processing Plex webhook:', e)
        return 'error', 400

import os
from flask import session, redirect, url_for, request, render_template, flash
import requests

# Plex OAuth config: Use a helper to fetch settings from DB or env at runtime
import os

def get_plex_oauth_settings():
    from .database import get_setting
    client_id = get_setting('plex_client_id') or os.environ.get('PLEX_CLIENT_ID', 'YOUR_PLEX_CLIENT_ID')
    client_secret = None # Plex PIN auth typically doesn't use a client secret for this flow
    redirect_uri = os.environ.get('PLEX_REDIRECT_URI', 'https://shownotes.chitekmedia.club/callback') # Get from env or default
    return client_id, client_secret, redirect_uri

@bp.route('/login')
def login():
    import requests
    client_id, _, redirect_uri = get_plex_oauth_settings()
    # Step 1: Request a PIN from Plex
    headers = {
        'X-Plex-Client-Identifier': client_id,
        'Accept': 'application/json',
    }
    r = requests.post('https://plex.tv/api/v2/pins?strong=true', headers=headers)
    if r.status_code != 201:
        flash('Failed to initiate Plex login. Try again later.')
        return redirect(url_for('main.home'))
    pin = r.json()
    pin_id = pin['id']
    pin_code = pin['code']
    session['plex_pin_id'] = pin_id
    session['plex_pin_code'] = pin_code
    session['plex_client_id'] = client_id
    session['plex_redirect_uri'] = redirect_uri
    # Step 2: Redirect user to Plex auth page
    plex_auth_url = f'https://app.plex.tv/auth#?clientID={client_id}&code={pin_code}&forwardUrl={redirect_uri}'
    return redirect(plex_auth_url)

import time

def poll_plex_pin(pin_id, client_id, timeout=60):
    """Poll the Plex API for PIN status and return auth token if authorized."""
    import requests
    poll_url = f'https://plex.tv/api/v2/pins/{pin_id}'
    headers = {
        'X-Plex-Client-Identifier': client_id,
        'Accept': 'application/json',
    }
    for _ in range(timeout):
        r = requests.get(poll_url, headers=headers)
        if r.status_code != 200:
            break
        data = r.json()
        if data.get('authToken'):
            return data['authToken'], data
        time.sleep(1)
    return None, None

@bp.route('/callback', endpoint='plex_callback')
def callback():
    # Step 3: Poll for PIN status
    pin_id = session.get('plex_pin_id')
    client_id = session.get('plex_client_id')
    redirect_uri = session.get('plex_redirect_uri')
    if not pin_id or not client_id:
        flash('Missing Plex PIN/session. Please try logging in again.')
        return redirect(url_for('main.home'))
    auth_token, pin_data = poll_plex_pin(pin_id, client_id)
    if not auth_token:
        flash('Plex login failed or timed out. Please try again.')
        return redirect(url_for('main.home'))
    # Step 4: Fetch user info with auth token
    user_info = None
    try:
        headers = {
            'X-Plex-Token': auth_token,
            'Accept': 'application/json',
        }
        r = requests.get('https://plex.tv/api/v2/user', headers=headers) # Changed endpoint
        if r.status_code == 200:
            user_info = r.json() # The response IS the user object
            if not user_info:
                print(f"DEBUG: Plex /api/v2/user response was empty or not valid. Full JSON: {user_info}")
                user_info = {} # Ensure user_info is a dict
        else:
            print(f"DEBUG: Failed to fetch from plex.tv/api/v2/user. Status: {r.status_code}, Response: {r.text}")
            user_info = {} # Ensure user_info is a dict to prevent downstream errors
    except Exception as e:
        print(f"DEBUG: Exception during plex.tv/users/account request: {e}")
        user_info = {} # Ensure user_info is a dict
    # Try to get the best username and user id: username, then title, then email, then Account.title/id from last_plex_event
    username = None
    user_id = None
    if user_info:
        username = user_info.get('username') or user_info.get('title') or user_info.get('email')
        user_id = user_info.get('id')
    # If username or id is missing or generic, try to get Account.title/id from last_plex_event
    if not username or username == 'plex_user' or not user_id:
        global last_plex_event
        if last_plex_event and 'Account' in last_plex_event:
            if not username or username == 'plex_user':
                username = last_plex_event['Account'].get('title', username)
            if not user_id:
                user_id = last_plex_event['Account'].get('id', user_id)
    if not username:
        username = 'plex_user'
    print('DEBUG: Plex user_info from API:', user_info)
    session['plex_token'] = auth_token
    session['user_id'] = user_id # This is Plex User ID
    session['username'] = username # This is Plex Username
    session['is_admin'] = False # Default to not admin
    session['db_user_id'] = None # Local DB user ID
    print(f"DEBUG: Session set in /callback: user_id={session.get('user_id')}, username={session.get('username')}")

    if user_id:
        db = database.get_db()
        # Check if this Plex user is linked to a local admin user
        user_record = db.execute(
            'SELECT id, username, is_admin FROM users WHERE plex_user_id = ?',
            (user_id,)
        ).fetchone()

        if user_record:
            session['db_user_id'] = user_record['id']
            # session['username'] = user_record['username'] # Optionally override Plex username with local one if desired
            if user_record['is_admin']:
                session['is_admin'] = True
            flash(f'Welcome back, {user_record["username"]}! Admin status: {session["is_admin"]}.')
            
            # Create User object from app/__init__.py and log them in with Flask-Login
            # Assuming User class is accessible or we re-fetch from load_user logic
            # For simplicity, let's re-fetch using the load_user mechanism if possible
            # or directly instantiate if User class is imported/available.
            # We need the User class definition from __init__.py to be accessible here.
            # A common way is to have User model in a separate models.py
            # For now, we'll assume load_user can be called or we construct it.
            
            # Simplest approach: Re-use the User class defined in __init__.py
            # This requires a bit of a workaround or refactoring User class to be importable.
            # Let's try to get the user object via the loader, which is cleaner.
            user_for_login = current_app.login_manager._user_callback(user_record['id'])
            if user_for_login:
                login_user(user_for_login)
                current_app.logger.info(f"Flask-Login: User {user_for_login.username} (ID: {user_for_login.id}) logged in.")
            else:
                current_app.logger.error(f"Flask-Login: Could not load user {user_record['id']} after Plex auth.")
                flash('Login session error. Please try again.', 'danger')
                return redirect(url_for('main.login'))

        elif user_info: # User authenticated with Plex but not in local DB
            # Potentially create a new user here if auto-registration is desired
            # For now, just log them in with Plex details, no local admin rights
            flash(f'User {username} (Plex) logged in. Not yet linked to a local account. Please complete onboarding or contact admin.', 'info')
            # If you want to allow login without a local DB record, you'd create a temporary User object here
            # and call login_user. However, this is generally not recommended without linking to a local user.
            # For now, redirect to home, they won't be Flask-Login authenticated.

        # Redirect to home or a specific page after login
        return redirect(url_for('main.home'))

    # Fallback if something went wrong before user_info was processed
    flash('Plex login process encountered an issue.', 'warning')
    return redirect(url_for('main.home'))

@bp.route('/logout', endpoint='plex_logout')
def logout():
    print("DEBUG: Entered /logout function") # New print
    session.clear()
    print(f"DEBUG: Session after clear in /logout: {list(session.items())}")
    flash('Logged out.')
    return redirect(url_for('main.home'))

import re

def get_sonarr_poster(show_title):
    db = database.get_db()
    settings = db.execute('SELECT * FROM settings LIMIT 1').fetchone()
    sonarr_url = settings['sonarr_url'] if settings and 'sonarr_url' in settings else None
    sonarr_api_key = settings['sonarr_api_key'] if settings and 'sonarr_api_key' in settings else None
    if not sonarr_url or not sonarr_api_key:
        return None
    try:
        r = requests.get(f"{sonarr_url.rstrip('/')}/api/v3/series", headers={"X-Api-Key": sonarr_api_key}, timeout=5)
        if r.status_code == 200:
            for show in r.json():
                # Fuzzy match on title
                if show_title.lower() in [show['title'].lower(), show.get('cleanTitle','').lower()]:
                    posters = [img['remoteUrl'] for img in show['images'] if img['coverType'] == 'poster' and 'remoteUrl' in img]
                    if posters:
                        return posters[0]
    except Exception as e:
        print(f"Sonarr error: {e}")
    return None

def get_radarr_poster(movie_title):
    db = database.get_db()
    settings = db.execute('SELECT * FROM settings LIMIT 1').fetchone()
    radarr_url = settings['radarr_url'] if settings and 'radarr_url' in settings else None
    radarr_api_key = settings['radarr_api_key'] if settings and 'radarr_api_key' in settings else None
    if not radarr_url or not radarr_api_key:
        return None
    try:
        r = requests.get(f"{radarr_url.rstrip('/')}/api/v3/movie", headers={"X-Api-Key": radarr_api_key}, timeout=5)
        if r.status_code == 200:
            for movie in r.json():
                if movie_title.lower() in [movie['title'].lower(), movie.get('originalTitle','').lower()]:
                    posters = [img['remoteUrl'] for img in movie['images'] if img['coverType'] == 'poster' and 'remoteUrl' in img]
                    if posters:
                        return posters[0]
    except Exception as e:
        print(f"Radarr error: {e}")
    return None

@bp.route('/')
def home():
    print(f"DEBUG: Session at start of /home: {list(session.items())}")
    db = database.get_db()
    
    # Get user details from session
    s_user_id = session.get('user_id')
    s_username = session.get('username')
    s_is_admin = session.get('is_admin', False)

    print(f"DEBUG: Home - session user_id: {s_user_id}, username: {s_username}, is_admin: {s_is_admin}")

    plex_event_from_db = None # Original event from plex_activity_log
    if s_username:
        current_app.logger.info(f"Attempting to fetch latest activity for user: {s_username} from plex_activity_log.")
        try:
            plex_event_from_db = db.execute(
                """
                SELECT * FROM plex_activity_log
                WHERE plex_username = ? 
                  AND event_type IN ('media.play', 'media.resume', 'media.stop', 'media.scrobble', 'media.pause')
                ORDER BY event_timestamp DESC, id DESC
                LIMIT 1
                """,
                (s_username,)
            ).fetchone()

            if plex_event_from_db:
                current_app.logger.info(f"Found latest activity for {s_username}: Event ID {plex_event_from_db['id']}, Type {plex_event_from_db['event_type']}, Title '{plex_event_from_db['title']}'")
            else:
                current_app.logger.info(f"No recent relevant activity found for user {s_username} in plex_activity_log.")
        except Exception as e:
            current_app.logger.error(f"Error fetching from plex_activity_log for user {s_username}: {e}", exc_info=True)
    else:
        current_app.logger.info("No user in session (s_username is None), not fetching from plex_activity_log.")

    # Prepare details for the template
    plex_event_for_template = None
    poster_url_for_template = None

    if plex_event_from_db:
        plex_event_for_template = dict(plex_event_from_db)
        media_type = plex_event_for_template.get('media_type')
        tmdb_id = plex_event_for_template.get('tmdb_id')
        activity_title = plex_event_for_template.get('title') # General title
        activity_show_title = plex_event_for_template.get('show_title') # Specific to shows/episodes

        current_app.logger.info(f"Processing event for media_type: '{media_type}', tmdb_id: {tmdb_id}")

        # --- Logic for Movies ---
        if media_type == 'movie' and tmdb_id:
            movie_data = db.execute(
                'SELECT poster_url, tmdb_id AS tmdbId, year, overview FROM radarr_movies WHERE tmdb_id = ?',
                (tmdb_id,)
            ).fetchone()

            if movie_data:
                current_app.logger.info(f"Found movie data for tmdbId: {tmdb_id}")
                plex_event_for_template['poster_path'] = movie_data['poster_url']
                plex_event_for_template['tmdb_id'] = movie_data['tmdbId'] # This should be tmdb_id from the aliased select # Redundant but good for consistency
                plex_event_for_template['year'] = movie_data['year']
                plex_event_for_template['overview'] = movie_data['overview']
            else:
                current_app.logger.warning(f"Could not find movie in radarr_movies with tmdbId: {tmdb_id}")

        # --- Logic for TV Shows ---
        elif media_type == 'episode' and tmdb_id:
            show_data = db.execute(
                'SELECT poster_url, tmdb_id AS tmdbId, year, overview FROM sonarr_shows WHERE tmdb_id = ?',
                (tmdb_id,)
            ).fetchone()

            if show_data:
                current_app.logger.info(f"Found show data for tmdbId: {tmdb_id}")
                plex_event_for_template['poster_path'] = show_data['poster_url']
                plex_event_for_template['show_tmdb_id'] = show_data['tmdbId'] # This should be tmdb_id from the aliased select # Use specific key for shows
                plex_event_for_template['year'] = show_data['year']
                plex_event_for_template['overview'] = show_data['overview']
            else:
                current_app.logger.warning(f"Could not find show in sonarr_shows with tmdbId: {tmdb_id}")
        else:
            current_app.logger.warning("Event had no tmdb_id or was not a movie/episode, cannot fetch details.")

        if plex_event_for_template and plex_event_for_template.get('poster_path'):
            poster_url_for_template = url_for('main.image_proxy', url=plex_event_for_template['poster_path'])
            current_app.logger.info(f"Generated proxied poster URL for: {plex_event_for_template.get('poster_path')}")
        else:
            current_app.logger.warning(f"Failed to get remote_poster_url for media_type='{media_type}', title='{activity_title}', show_title='{activity_show_title}'.")

        current_app.logger.info(f"Final plex_event_for_template: {plex_event_for_template}")
        current_app.logger.info(f"Final poster_url_for_template: {poster_url_for_template}")

    print(f"DEBUG: Passing to template: plex_event defined: {plex_event_for_template is not None}, username: {s_username}, is_admin: {s_is_admin}, poster_url defined: {poster_url_for_template is not None}")
    return render_template('home.html', 
                           plex_event=plex_event_for_template, 
                           username=s_username, 
                           is_admin=s_is_admin, 
                           poster_url=poster_url_for_template)

@bp.route('/plex/debug')
def plex_debug():
    from flask import jsonify
    return jsonify(last_plex_event)

import os # Ensure os is imported if not already at the top of the file

@bp.route('/onboarding', methods=['GET', 'POST'])
def onboarding():
    # Step 1: Admin account creation
    env_settings = {}
    if request.method == 'GET':
        db = database.get_db()
        admin_user = db.execute('SELECT id FROM users WHERE is_admin = 1 LIMIT 1').fetchone()
        settings_record = db.execute('SELECT id FROM settings LIMIT 1').fetchone()
        if admin_user and not settings_record:
            # Partial onboarding: admin exists but no settings, go to services step
            return redirect(url_for('main.onboarding_services'))
        env_settings = {
            'username': os.environ.get('ADMIN_USERNAME', ''),
        }
        return render_template('onboarding.html', env_settings=env_settings)

    if request.method == 'POST':
        form_or_env_data = {
            'username': request.form.get('username', os.environ.get('ADMIN_USERNAME', '')),
        }
        db = database.get_db()
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if not username or not password or not confirm_password:
            flash('Username and password fields are required.', 'error')
            return render_template('onboarding.html', env_settings=form_or_env_data)

        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('onboarding.html', env_settings=form_or_env_data)

        pw_hash = generate_password_hash(password)
        try:
            cursor = db.execute(
                'INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)',
                (username, pw_hash),
            )
            db.commit()
            local_admin_user_id = cursor.lastrowid

            # Optionally link Plex user if present in session
            plex_user_id_in_session = session.get('user_id')
            plex_username_in_session = session.get('username')
            if local_admin_user_id and plex_user_id_in_session and plex_username_in_session:
                db.execute(
                    'UPDATE users SET plex_user_id = ?, plex_username = ? WHERE id = ?',
                    (plex_user_id_in_session, plex_username_in_session, local_admin_user_id)
                )
                db.commit()
                flash(f'Admin account created and linked to Plex user {plex_username_in_session}.', 'info')
            session['is_admin'] = True
            # Redirect to Step 2: Service configuration
            return redirect(url_for('main.onboarding_services'))
        except Exception as e:
            db.rollback()
            flash(f'An error occurred during onboarding: {e}', 'error')
            return render_template('onboarding.html', env_settings=form_or_env_data)

@bp.route('/onboarding/services', methods=['GET', 'POST'])
def onboarding_services():
    db = database.get_db()
    if request.method == 'GET':
        env_settings = {
            'radarr_url': os.environ.get('RADARR_URL', ''),
            'radarr_api_key': os.environ.get('RADARR_API_KEY', ''),
            'sonarr_url': os.environ.get('SONARR_URL', ''),
            'sonarr_api_key': os.environ.get('SONARR_API_KEY', ''),
            'bazarr_url': os.environ.get('BAZARR_URL', ''),
            'bazarr_api_key': os.environ.get('BAZARR_API_KEY', ''),
            'ollama_url': os.environ.get('OLLAMA_API_URL', os.environ.get('OLLAMA_URL', '')),
            'pushover_user_key': os.environ.get('PUSHOVER_USER_KEY', ''),
            'pushover_api_token': os.environ.get('PUSHOVER_API_TOKEN', ''),
        }
        return render_template('onboarding_services.html', env_settings=env_settings)
    if request.method == 'POST':
        # Save submitted service config to DB
        try:
            db.execute('DELETE FROM settings')
            db.execute(
                'INSERT INTO settings (radarr_url, radarr_api_key, sonarr_url, sonarr_api_key, bazarr_url, bazarr_api_key, ollama_url, pushover_key, pushover_token) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    request.form.get('radarr_url',''),
                    request.form.get('radarr_api_key',''),
                    request.form.get('sonarr_url',''),
                    request.form.get('sonarr_api_key',''),
                    request.form.get('bazarr_url',''),
                    request.form.get('bazarr_api_key',''),
                    request.form.get('ollama_url',''),
                    request.form.get('pushover_user_key',''),
                    request.form.get('pushover_api_token','')
                )
            )
            db.commit()
            flash('Service configuration saved! Onboarding complete.', 'success')
            return redirect(url_for('main.home'))
        except Exception as e:
            db.rollback()
            flash(f'An error occurred saving service configuration: {e}', 'error')
            env_settings = {k: request.form.get(k, '') for k in ['radarr_url','radarr_api_key','sonarr_url','sonarr_api_key','bazarr_url','bazarr_api_key','ollama_url','pushover_user_key','pushover_api_token']}
            return render_template('onboarding_services.html', env_settings=env_settings)

@bp.route('/onboarding/test-service', methods=['POST'])
def onboarding_test_service():
    data = request.get_json()
    service = data.get('service')
    url = data.get('url', '')
    key = data.get('key', '')
    try:
        if service == 'radarr':
            from .utils import _test_service_connection
            ok, msg = _test_service_connection('radarr', None, None, endpoint='/api/v3/movie', method='GET', params={'apikey': key}, headers_extra={'X-Api-Key': key}, url_override=url)
            return jsonify({'success': ok, 'message': msg})
        elif service == 'sonarr':
            from .utils import _test_service_connection
            ok, msg = _test_service_connection('sonarr', None, None, endpoint='/api/v3/series', method='GET', params={'apikey': key}, headers_extra={'X-Api-Key': key}, url_override=url)
            return jsonify({'success': ok, 'message': msg})
        elif service == 'bazarr':
            from .utils import _test_service_connection
            ok, msg = _test_service_connection('bazarr', None, None, endpoint='/api/status', method='GET', params={'apikey': key}, headers_extra={'X-Api-Key': key}, url_override=url)
            return jsonify({'success': ok, 'message': msg})
        elif service == 'ollama':
            # Ollama: Just try GET /api/tags
            import requests
            test_url = url.rstrip('/') + '/api/tags'
            resp = requests.get(test_url, timeout=5)
            if resp.status_code == 200:
                return jsonify({'success': True, 'message': 'Ollama reachable'})
            else:
                return jsonify({'success': False, 'message': f'Ollama error: {resp.status_code}'})
        elif service == 'pushover':
            # Pushover: Try sending a test notification
            from . import utils
            ok, msg = utils._send_test_pushover(url, key)
            return jsonify({'success': ok, 'message': msg})
        else:
            return jsonify({'success': False, 'message': 'Unknown service'}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# Helper function for sending Pushover test notification
def _send_test_pushover(user_key, api_token):
    if not user_key or not api_token:
        return False, "User key and API token are required."
    try:
        url = "https://api.pushover.net/1/messages.json"
        payload = {
            "token": api_token,
            "user": user_key,
            "message": "This is a test notification from ShowNotes!",
            "title": "ShowNotes Test"
        }
        r = requests.post(url, data=payload, timeout=5)
        r.raise_for_status() # Raise an exception for HTTP errors
        response_data = r.json()
        if response_data.get("status") == 1:
            return True, "Test notification sent successfully."
        else:
            return False, f"Pushover API error: {response_data.get('errors', ['Unknown error'])[0]}"
    except requests.exceptions.Timeout:
        return False, "Connection to Pushover timed out."
    except requests.exceptions.RequestException as e:
        return False, f"Failed to send test notification: {str(e)}"

@bp.route('/test-api', methods=['POST'])
def test_api():
    data = request.get_json()
    service = data.get('service')
    url = data.get('url')
    api_key = data.get('api_key')
    try:
        if service in ('radarr', 'sonarr'):
            endpoint = f"{url.rstrip('/')}/api/v3/system/status"
            headers = {'X-Api-Key': api_key}
            r = requests.get(endpoint, headers=headers, timeout=5)
            return jsonify({'success': r.status_code == 200})
        elif service == 'bazarr':
            endpoint = f"{url.rstrip('/')}/api/status"
            headers = {'X-Api-Key': api_key}
            r = requests.get(endpoint, headers=headers, timeout=5)
            return jsonify({'success': r.status_code == 200})
        elif service == 'ollama':
            r = requests.get(url.rstrip('/') + '/api/tags', timeout=5)
            return jsonify({'success': r.status_code == 200})
        elif service == 'pushover':
            user_key = data.get('pushover_user_key')
            api_token = data.get('pushover_api_token')
            success, message = _send_test_pushover(user_key, api_token)
            if success:
                return jsonify({'success': True, 'message': message})
            else:
                return jsonify({'success': False, 'error': message})
        else:
            return jsonify({'success': False, 'error': 'Unknown service'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@bp.route('/test-pushover', methods=['POST'])
def test_pushover():
    data = request.get_json()
    user_key = data.get('user_key')  # This route expects 'user_key' from its caller
    api_token = data.get('token')   # This route expects 'token' (for api_token) from its caller
    
    success, message = _send_test_pushover(user_key, api_token)
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        # Determine appropriate status code based on message content if needed, or use a generic one
        status_code = 400 if "required" in message.lower() or "Pushover API error" in message.lower() else 500
        return jsonify({'success': False, 'error': message}), status_code




@bp.route('/login/plex/start')
def login_plex_start():
    r = requests.post('https://plex.tv/api/v2/pins.json', headers=PLEX_HEADERS)
    data = r.json()
    session['plex_pin_id'] = data['id']
    session['plex_client_id'] = PLEX_HEADERS['X-Plex-Client-Identifier']
    auth_url = (
        f"https://app.plex.tv/auth/#!?clientID={PLEX_HEADERS['X-Plex-Client-Identifier']}"
        f"&code={data['code']}&context%5Bdevice%5D%5Bproduct%5D=ShowNotes"
    )
    return jsonify({'authUrl': auth_url})

@bp.route('/login/plex/poll')
def login_plex_poll():
    pin_id = session.get('plex_pin_id')
    if not pin_id:
        return jsonify({'authorized': False}), 400
    r = requests.get(f'https://plex.tv/api/v2/pins/{pin_id}.json', headers=PLEX_HEADERS)
    data = r.json()
    if data.get('authToken'):
        token = data['authToken']
        user_r = requests.get(
            'https://plex.tv/api/v2/user',
            headers={**PLEX_HEADERS, 'X-Plex-Token': token},
        )
        user = user_r.json()
        db = database.get_db()
        row = db.execute('SELECT id FROM users WHERE plex_id=?', (str(user['id']),)).fetchone()
        if row is None:
            db.execute(
                'INSERT INTO users (username, plex_id, plex_token) VALUES (?, ?, ?)',
                (user['username'], user['id'], token),
            )
            user_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        else:
            user_id = row['id']
            db.execute('UPDATE users SET plex_token=? WHERE id=?', (token, user_id))
        db.commit()
        session['user_id'] = user_id
        session['plex_token'] = token
        return jsonify({'authorized': True})
    return jsonify({'authorized': False})

# --- Image Proxy -----------------------------------------------------------

@bp.route('/image-proxy')
def image_proxy():
    remote_url = request.args.get('url')
    if not remote_url:
        return 'Missing URL parameter', 400

    # Basic validation to ensure it's a Sonarr/Radarr URL if possible
    # This is not a security feature, just a sanity check.
    settings = database.get_db().execute('SELECT radarr_url, sonarr_url, radarr_api_key, sonarr_api_key FROM settings LIMIT 1').fetchone()
    radarr_url = settings['radarr_url'] if settings else ''
    sonarr_url = settings['sonarr_url'] if settings else ''

    if not (remote_url.startswith(radarr_url) or remote_url.startswith(sonarr_url)):
        # For security, you might want to strictly enforce this or have a better check
        pass # Allowing any URL for now, but be cautious

    try:
        # Generate a safe filename from the URL
        parsed_url = urllib.parse.urlparse(remote_url)
        # Use a hash of the path to avoid issues with long filenames or special characters
        filename = f"{hash(parsed_url.path)}.jpg"
        
        cache_dir = os.path.join(current_app.static_folder, 'poster_cache')
        os.makedirs(cache_dir, exist_ok=True)
        
        image_path = os.path.join(cache_dir, filename)

        if not os.path.exists(image_path):
            # Fetch from remote and save to cache
            # Add API keys if required by Sonarr/Radarr for media covers
            headers = {}
            if remote_url.startswith(sonarr_url):
                headers['X-Api-Key'] = settings['sonarr_api_key']
            elif remote_url.startswith(radarr_url):
                headers['X-Api-Key'] = settings['radarr_api_key']

            response = requests.get(remote_url, stream=True, headers=headers)
            response.raise_for_status()
            with open(image_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

        return send_from_directory(cache_dir, filename)

    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Failed to proxy image from {remote_url}: {e}")
        # Optionally, return a placeholder image
        return send_from_directory(current_app.static_folder, 'placeholder.png')
    except Exception as e:
        current_app.logger.error(f"An unexpected error occurred in image_proxy: {e}")
        return 'Internal Server Error', 500

@bp.route('/search')
def search():
    """Search shows and movies from the local database efficiently."""
    query_term = request.args.get('q', '').strip()
    if not query_term:
        return jsonify([])

    db = database.get_db()
    # Retrieve service URLs for constructing absolute image paths
    sonarr_url_base = (database.get_setting('sonarr_url') or '').rstrip('/')
    radarr_url_base = (database.get_setting('radarr_url') or '').rstrip('/')
    results = []

    def get_proxied_url(base_url, relative_path):
        """Constructs an absolute URL and returns a proxied URL for it."""
        if not base_url or not relative_path:
            return None
        # Sonarr/Radarr may provide full URLs or relative paths
        if relative_path.startswith(('http://', 'https://')):
            absolute_url = relative_path
        else:
            absolute_url = f"{base_url}{relative_path}"
        return url_for('main.image_proxy', url=absolute_url)

    # Search Sonarr shows
    try:
        like_query = f"%{query_term.lower()}%"
        cursor_shows = db.execute(
            "SELECT tmdb_id, title, poster_url, fanart_url FROM sonarr_shows WHERE LOWER(title) LIKE ?",
            (like_query,)
        )
        for row in cursor_shows.fetchall():
            results.append({
                'id': row['tmdb_id'],
                'type': 'show',
                'title': row['title'],
                'poster': get_proxied_url(sonarr_url_base, row['poster_url']),
                'background': get_proxied_url(sonarr_url_base, row['fanart_url'])
            })
    except Exception as e:
        current_app.logger.error(f"Error searching Sonarr shows in DB: {e}", exc_info=True)

    # Search Radarr movies
    try:
        like_query = f"%{query_term.lower()}%"
        cursor_movies = db.execute(
            "SELECT tmdb_id, title, year, poster_url, fanart_url FROM radarr_movies WHERE LOWER(title) LIKE ?",
            (like_query,)
        )
        for row in cursor_movies.fetchall():
            results.append({
                'id': row['tmdb_id'],
                'type': 'movie',
                'title': row['title'],
                'year': row['year'],
                'poster': get_proxied_url(radarr_url_base, row['poster_url']),
                'background': get_proxied_url(radarr_url_base, row['fanart_url'])
            })
    except Exception as e:
        current_app.logger.error(f"Error searching Radarr movies in DB: {e}", exc_info=True)

    return jsonify(results)


# --- Show Detail Page ---
@bp.route('/show/<int:tmdb_id>')
@login_required
def show_detail(tmdb_id):
    db = database.get_db()
    show = db.execute('SELECT * FROM sonarr_shows WHERE tmdb_id = ?', (tmdb_id,)).fetchone()
    if show:
        show_dict = dict(show) # Make it mutable

        # Generate proxied URLs for display
        if show_dict.get('poster_url'):
            # Use tmdbId from sonarr_shows for the cache key prefix part, as it's the ID used in the route
            show_dict['poster_display_url'] = utils.cache_image(
                show_dict['poster_url'],
                'posters',
                f"show_poster_{show_dict['tmdb_id']}", # tmdbId from sonarr_shows
                'sonarr'
            )
        else:
            show_dict['poster_display_url'] = None

        if show_dict.get('fanart_url'):
            show_dict['fanart_display_url'] = utils.cache_image(
                show_dict['fanart_url'],
                'background',
                f"show_fanart_{show_dict['tmdb_id']}", # tmdbId from sonarr_shows
                'sonarr'
            )
        else:
            show_dict['fanart_display_url'] = None

        return render_template('show_detail.html', show=show_dict, title=show_dict['title'])
    else:
        current_app.logger.warning(f"Show with tmdb_id {tmdb_id} not found in sonarr_shows.")
        abort(404)

# --- Movie Detail Page ---
@bp.route('/movie/<int:tmdb_id>')
def movie_detail(tmdb_id):
    db = database.get_db()
    # Fetch all relevant movie details
    movie_data = db.execute(
        """SELECT tmdb_id, title, year, overview, poster_url, fanart_url, status, 
                  path_on_disk, has_file, imdb_id 
           FROM radarr_movies 
           WHERE tmdb_id = ?""",
        (tmdb_id,)
    ).fetchone()

    if movie_data is None:
        flash('Movie not found.', 'error')
        return redirect(url_for('main.home'))

    # Convert sqlite3.Row to a mutable dictionary for easier manipulation
    movie = dict(movie_data)

    # Generate cache keys safely, handling potential None title
    movie_title_for_cache = movie.get('title', 'unknown_movie').replace(' ', '_').replace('/', '_') # Basic sanitization for cache key
    tmdb_id_str = str(movie.get('tmdb_id', 'unknown_id'))
    
    poster_cache_key = f"movie_poster_{tmdb_id_str}_{movie_title_for_cache}"
    fanart_cache_key = f"movie_fanart_{tmdb_id_str}_{movie_title_for_cache}"

    # Use utils.cache_image for poster and fanart, handling cases where URLs might be None
    movie['poster_display_url'] = utils.cache_image(
        movie.get('poster_url'), 
        'posters', 
        poster_cache_key, 
        'radarr'
    ) if movie.get('poster_url') else None

    movie['fanart_display_url'] = utils.cache_image(
        movie.get('fanart_url'), 
        'background', 
        fanart_cache_key, 
        'radarr'
    ) if movie.get('fanart_url') else None
    
    # Future: Fetch cast, crew, trailers, etc.

    return render_template('movie_detail.html', movie=movie)
