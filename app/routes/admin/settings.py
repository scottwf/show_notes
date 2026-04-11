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

@admin_bp.route('/ai-summaries')
@login_required
@admin_required
def ai_summaries():
    """Legacy AI summaries page now redirects to consolidated AI admin."""
    return redirect(url_for('admin.ai_settings'))

# ============================================================================
# LOG MANAGEMENT
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
            ntfy_url=?, ntfy_topic=?, ntfy_token=?,
            notify_on_problem_report=?, notify_on_new_user=?, notify_on_issue_resolved=?,
            plex_client_id=?, tautulli_url=?, tautulli_api_key=?,
            thetvdb_api_key=?, timezone=?,
            jellyseer_url=?, jellyseer_api_key=?, jellyseer_remote_url=?,
            ollama_url=?, ollama_model_name=?, openai_api_key=?, openai_model_name=?,
            preferred_llm_provider=?,
            schedule_tautulli_hour=?, schedule_tautulli_minute=?,
            schedule_sonarr_day=?, schedule_sonarr_hour=?, schedule_sonarr_minute=?,
            schedule_radarr_day=?, schedule_radarr_hour=?, schedule_radarr_minute=?,
            llm_knowledge_cutoff_date=?,
            summary_schedule_start_hour=?, summary_schedule_end_hour=?,
            summary_delay_seconds=?, summary_enabled=?
            WHERE id=?''', (
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
            request.form.get('ntfy_url'),
            request.form.get('ntfy_topic'),
            request.form.get('ntfy_token'),
            1 if request.form.get('notify_on_problem_report') else 0,
            1 if request.form.get('notify_on_new_user') else 0,
            1 if request.form.get('notify_on_issue_resolved') else 0,
            request.form.get('plex_client_id'),
            request.form.get('tautulli_url'),
            request.form.get('tautulli_api_key'),
            request.form.get('thetvdb_api_key'),
            request.form.get('timezone', 'UTC'),
            request.form.get('jellyseer_url'),
            request.form.get('jellyseer_api_key'),
            request.form.get('jellyseer_remote_url'),
            request.form.get('ollama_url'),
            request.form.get('ollama_model_name'),
            request.form.get('openai_api_key'),
            request.form.get('openai_model_name'),
            request.form.get('preferred_llm_provider') or None,
            request.form.get('schedule_tautulli_hour', 3, type=int),
            request.form.get('schedule_tautulli_minute', 0, type=int),
            request.form.get('schedule_sonarr_day', 'sun'),
            request.form.get('schedule_sonarr_hour', 4, type=int),
            request.form.get('schedule_sonarr_minute', 0, type=int),
            request.form.get('schedule_radarr_day', 'sun'),
            request.form.get('schedule_radarr_hour', 5, type=int),
            request.form.get('schedule_radarr_minute', 0, type=int),
            request.form.get('llm_knowledge_cutoff_date') or None,
            request.form.get('summary_schedule_start_hour', 2, type=int),
            request.form.get('summary_schedule_end_hour', 6, type=int),
            request.form.get('summary_delay_seconds', 30, type=int),
            1 if request.form.get('summary_enabled') else 0,
            settings['id'] if settings else 1
        ))
        db.commit()

        # Reschedule background jobs with new times
        try:
            from app.scheduler import reschedule_jobs
            reschedule_jobs(current_app._get_current_object())
        except Exception as e:
            current_app.logger.warning(f"Could not reschedule jobs: {e}")

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
    thetvdb_status = test_thetvdb_connection()

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
        thetvdb_status=thetvdb_status,
        ollama_models=[],
        saved_ollama_model=merged_settings.get('ollama_model_name'),
        timezones=timezones
    )

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
    elif service == 'thetvdb':
        success, error_message = test_thetvdb_connection_with_params(api_key)
    
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

@admin_bp.route('/test-ntfy', methods=['POST'])
@login_required
@admin_required
def test_ntfy_route():
    """Test ntfy notification with provided credentials."""
    data = request.json
    ntfy_url = (data.get('ntfy_url') or 'https://ntfy.sh').rstrip('/')
    ntfy_topic = data.get('ntfy_topic', '').strip()
    ntfy_token = data.get('ntfy_token', '').strip() or None

    if not ntfy_topic:
        return jsonify({'success': False, 'error': 'Topic is required'}), 400

    import requests as _req
    headers = {'Title': 'ShowNotes Test', 'Content-Type': 'text/plain'}
    if ntfy_token:
        headers['Authorization'] = f'Bearer {ntfy_token}'
    try:
        resp = _req.post(f"{ntfy_url}/{ntfy_topic}", data=b'This is a test notification from ShowNotes!', headers=headers, timeout=5)
        if resp.status_code in (200, 201, 202):
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': f'HTTP {resp.status_code}: {resp.text}'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


