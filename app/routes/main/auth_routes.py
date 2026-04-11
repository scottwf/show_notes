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

@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    Handles user login via username/password.

    On ``GET`` requests, renders the login page.
    On ``POST`` requests, validates admin credentials and logs the user in.
    """
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember_me = request.form.get('remember_me') == 'on'
        db = database.get_db()
        current_app.logger.info(f"Login attempt for username: {username}, remember_me: {remember_me}")
        user_record = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        current_app.logger.info(f"User record found: {bool(user_record)}")
        if user_record:
            current_app.logger.info(f"User is_admin: {user_record['is_admin']}, has_password_hash: {bool(user_record['password_hash'])}")
        if user_record and user_record['is_admin'] and user_record['password_hash']:
            password_valid = check_password_hash(user_record['password_hash'], password)
            current_app.logger.info(f"Password check result: {password_valid}")
            if password_valid:
                user_obj = current_app.login_manager._user_callback(user_record['id'])
                current_app.logger.info(f"User object created: {bool(user_obj)}")
                if user_obj:
                    login_user(user_obj, remember=remember_me)
                    session.permanent = remember_me  # Make session permanent if remember me is checked
                    session['user_id'] = user_obj.id
                    session['username'] = user_obj.username
                    session['is_admin'] = user_obj.is_admin
                    session['profile_photo_url'] = user_record['profile_photo_url'] if user_record['profile_photo_url'] else None
                    db.execute('UPDATE users SET last_login_at=CURRENT_TIMESTAMP WHERE id=?', (user_obj.id,))
                    db.commit()
                    flash(f'Welcome back, {user_obj.username}!', 'success')
                    return redirect(url_for('main.home'))
        current_app.logger.warning(f"Login failed for username: {username}")
        flash('Invalid admin credentials.', 'danger')
        return redirect(url_for('main.login'))

    # GET request - render login page
    return render_template('login.html')

@main_bp.route('/login/plex/start')
def plex_login_start():
    """
    Initiates the Plex OAuth flow by creating a PIN and returning the auth URL.

    Returns:
        JSON response with the Plex auth URL for the user to authenticate.
    """
    client_id = database.get_setting('plex_client_id')
    if not client_id:
        return jsonify({'error': 'Plex OAuth is not configured'}), 500

    # Create a PIN for Plex OAuth
    headers = {
        'X-Plex-Client-Identifier': client_id,
        'X-Plex-Product': 'ShowNotes',
        'X-Plex-Version': '1.0',
        'X-Plex-Platform': 'Web',
        'X-Plex-Platform-Version': '1.0',
        'X-Plex-Device': 'Browser',
        'X-Plex-Device-Name': 'ShowNotes Web',
        'Accept': 'application/json'
    }

    try:
        response = requests.post('https://plex.tv/api/v2/pins?strong=true', headers=headers)
        response.raise_for_status()
        pin_data = response.json()

        pin_id = pin_data.get('id')
        pin_code = pin_data.get('code')

        if not pin_id or not pin_code:
            return jsonify({'error': 'Failed to generate Plex PIN'}), 500

        # Store PIN ID in session for later polling
        session['plex_pin_id'] = pin_id

        # Build auth URL - don't use forwardUrl since localhost URLs may not be accepted
        # The user will manually close the window after auth, and we'll poll for completion
        auth_url = f'https://app.plex.tv/auth#?clientID={client_id}&code={pin_code}'

        return jsonify({'authUrl': auth_url})

    except Exception as e:
        current_app.logger.error(f"Error starting Plex OAuth: {e}")
        return jsonify({'error': 'Failed to start Plex authentication'}), 500

@main_bp.route('/login/plex/poll')
def plex_login_poll():
    """
    Polls the Plex API to check if the user has authorized the PIN.

    Returns:
        JSON response indicating whether authorization is complete.
    """
    pin_id = session.get('plex_pin_id')
    client_id = database.get_setting('plex_client_id')

    if not pin_id or not client_id:
        return jsonify({'authorized': False, 'error': 'No active PIN session'}), 400

    headers = {
        'X-Plex-Client-Identifier': client_id,
        'Accept': 'application/json'
    }

    try:
        response = requests.get(f'https://plex.tv/api/v2/pins/{pin_id}', headers=headers)
        response.raise_for_status()
        data = response.json()

        auth_token = data.get('authToken')

        if auth_token:
            # Get user info from Plex
            headers['X-Plex-Token'] = auth_token
            user_response = requests.get('https://plex.tv/api/v2/user', headers=headers)
            user_response.raise_for_status()
            user_info = user_response.json()

            plex_user_id = user_info.get('id')
            plex_username = user_info.get('username') or user_info.get('title')
            plex_joined_at_timestamp = user_info.get('joinedAt')  # Get Plex account creation date (Unix timestamp)

            # Convert Unix timestamp to ISO datetime string
            plex_joined_at = None
            if plex_joined_at_timestamp:
                plex_joined_at = datetime.datetime.fromtimestamp(plex_joined_at_timestamp, tz=timezone.utc).isoformat()

            # Check if user exists in database
            db = database.get_db()
            user_record = db.execute('SELECT * FROM users WHERE plex_user_id = ?', (plex_user_id,)).fetchone()

            if user_record:
                # Block inactive (imported-but-not-yet-activated) accounts
                if not user_record['is_active']:
                    return jsonify({'authorized': False, 'error': 'Your account has not been activated yet. Please contact the administrator.'})

                # Log in the user
                user_obj = current_app.login_manager._user_callback(user_record['id'])
                if user_obj:
                    login_user(user_obj, remember=True)
                    session.permanent = True
                    session['user_id'] = user_obj.id
                    session['username'] = user_obj.username
                    session['is_admin'] = user_obj.is_admin
                    user_record = db.execute('SELECT profile_photo_url FROM users WHERE id = ?', (user_obj.id,)).fetchone()
                    session['profile_photo_url'] = user_record['profile_photo_url'] if user_record and user_record['profile_photo_url'] else None

                    # Update plex token, last login, and Plex join date
                    if plex_joined_at:
                        db.execute('UPDATE users SET plex_token=?, last_login_at=CURRENT_TIMESTAMP, plex_joined_at=? WHERE id=?',
                                  (auth_token, plex_joined_at, user_obj.id))
                    else:
                        db.execute('UPDATE users SET plex_token=?, last_login_at=CURRENT_TIMESTAMP WHERE id=?',
                                  (auth_token, user_obj.id))
                    db.commit()

                    # Household member: auto-select if only one, else prompt picker
                    members = get_user_members(user_obj.id)
                    if len(members) == 1:
                        set_member_session(members[0]['id'])
                        return jsonify({'authorized': True, 'username': user_obj.username})
                    else:
                        return jsonify({'authorized': True, 'username': user_obj.username, 'pick_profile': True})
            else:
                # If admin is already logged in, link their account to Plex
                if current_user.is_authenticated and current_user.is_admin:
                    if plex_joined_at:
                        db.execute('UPDATE users SET plex_user_id=?, plex_username=?, plex_token=?, plex_joined_at=? WHERE id=?',
                                  (plex_user_id, plex_username, auth_token, plex_joined_at, current_user.id))
                    else:
                        db.execute('UPDATE users SET plex_user_id=?, plex_username=?, plex_token=? WHERE id=?',
                                  (plex_user_id, plex_username, auth_token, current_user.id))
                    db.commit()
                    return jsonify({'authorized': True, 'username': current_user.username, 'linked': True})
                else:
                    return jsonify({'authorized': False, 'error': f'Plex user {plex_username} is not registered in this application'})

        return jsonify({'authorized': False})

    except Exception as e:
        current_app.logger.error(f"Error polling Plex auth status: {e}")
        return jsonify({'authorized': False, 'error': str(e)}), 500

@main_bp.route('/callback')
def callback():
    """
    Handles the callback from the Plex OAuth authentication process.

    After the user authenticates with Plex, Plex redirects them back to this
    endpoint. This function checks the status of the PIN associated with the
    client ID. If the PIN has been authorized, it retrieves the user's Plex
    auth token, username, and other details.

    It then either finds an existing user in the database or creates a new one,
    logs the user in, and redirects them to the homepage.

    Returns:
        A redirect to the homepage on successful login, or an error page/message
        on failure.
    """
    pin_id = session.get('plex_pin_id')
    client_id = database.get_setting('plex_client_id')
    if not pin_id or not client_id:
        flash('Plex OAuth is not configured. Please use username/password login.', 'info')
        return redirect(url_for('main.login'))

    # Poll for auth token
    poll_url = f'https://plex.tv/api/v2/pins/{pin_id}'
    headers = {'X-Plex-Client-Identifier': client_id, 'Accept': 'application/json'}
    start_time = time.time()
    auth_token = None
    while time.time() - start_time < 120: # 2 minute timeout
        r = requests.get(poll_url, headers=headers)
        if r.status_code == 200:
            data = r.json()
            if data.get('authToken'):
                auth_token = data['authToken']
                break
        time.sleep(2)
    
    if not auth_token:
        flash('Plex login failed or timed out.', 'danger')
        return redirect(url_for('main.home'))

    # Get user info from Plex
    headers['X-Plex-Token'] = auth_token
    r = requests.get('https://plex.tv/api/v2/user', headers=headers)
    if r.status_code != 200:
        flash('Failed to retrieve user information from Plex.', 'danger')
        return redirect(url_for('main.home'))
    
    user_info = r.json()
    plex_user_id = user_info.get('id')
    plex_joined_at_timestamp = user_info.get('joinedAt')  # Get Plex account creation date (Unix timestamp)

    # Convert Unix timestamp to ISO datetime string
    plex_joined_at = None
    if plex_joined_at_timestamp:
        plex_joined_at = datetime.datetime.fromtimestamp(plex_joined_at_timestamp, tz=timezone.utc).isoformat()

    db = database.get_db()
    user_record = db.execute('SELECT * FROM users WHERE plex_user_id = ?', (plex_user_id,)).fetchone()

    if not user_record:
        flash(f"Plex user {user_info.get('username')} is not registered in this application.", 'warning')
        return redirect(url_for('main.home'))

    # Log in the user
    user_obj = current_app.login_manager._user_callback(user_record['id'])
    if user_obj:
        login_user(user_obj, remember=True)
        session.permanent = True
        session['user_id'] = user_obj.id
        session['username'] = user_obj.username
        session['is_admin'] = user_obj.is_admin
        user_record = db.execute('SELECT profile_photo_url FROM users WHERE id = ?', (user_obj.id,)).fetchone()
        session['profile_photo_url'] = user_record['profile_photo_url'] if user_record and user_record['profile_photo_url'] else None

        # Update last login and Plex join date
        if plex_joined_at:
            db.execute('UPDATE users SET last_login_at=CURRENT_TIMESTAMP, plex_joined_at=? WHERE id=?',
                      (plex_joined_at, user_obj.id))
        else:
            db.execute('UPDATE users SET last_login_at=CURRENT_TIMESTAMP WHERE id=?', (user_obj.id,))
        db.commit()
        flash(f'Welcome back, {user_obj.username}!', 'success')
    else:
        flash('Could not log you in. Please contact an administrator.', 'danger')

    return redirect(url_for('main.home'))

@main_bp.route('/logout')
def logout():
    """
    Logs the current user out.

    This route clears the user's session data and logs them out using Flask-Login's
    `logout_user` function. It then redirects the user to the homepage.
    Does not require @login_required to allow clearing broken sessions.

    Returns:
        A redirect to the homepage.
    """
    logout_user()
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.login'))

@main_bp.route('/onboarding', methods=['GET', 'POST'])
def onboarding():
    """
    Step 1 of onboarding: Create admin account.

    If onboarding is already complete, redirects to homepage.
    On POST, creates admin user and redirects to Step 2 (service configuration).
    """
    if is_onboarding_complete():
        return redirect(url_for('main.home'))

    if request.method == 'POST':
        db = database.get_db()
        try:
            # Create admin user
            pw_hash = generate_password_hash(request.form['password'])
            db.execute(
                'INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)',
                (request.form['username'], pw_hash)
            )
            db.commit()

            # Store username in session for Step 2
            session['onboarding_username'] = request.form['username']

            flash('Admin account created! Now configure your services.', 'success')
            return redirect(url_for('main.onboarding_services'))
        except Exception as e:
            db.rollback()
            flash(f'An error occurred: {e}', 'danger')
            current_app.logger.error(f"Onboarding Step 1 error: {e}", exc_info=True)

    return render_template('onboarding.html')

@main_bp.route('/onboarding/services', methods=['GET', 'POST'])
def onboarding_services():
    """
    Step 2 of onboarding: Configure services (Radarr, Sonarr, Tautulli, etc.)

    Requires that Step 1 (admin account creation) has been completed.
    On POST, creates settings record and completes onboarding.
    On GET, pre-populates form fields from .env file if available.
    """
    # Check if Step 1 is complete (admin user exists)
    db = database.get_db()
    admin_user = db.execute('SELECT id FROM users WHERE is_admin = 1 LIMIT 1').fetchone()

    if not admin_user:
        flash('Please create an admin account first.', 'warning')
        return redirect(url_for('main.onboarding'))

    # Check if onboarding is already complete (settings exist)
    settings_record = db.execute('SELECT id FROM settings LIMIT 1').fetchone()
    if settings_record:
        flash('Onboarding already complete. Please log in.', 'info')
        return redirect(url_for('main.login'))

    # Load environment variables for pre-populating form
    env_settings = {
        'base_url': os.getenv('BASE_URL', ''),
        'radarr_url': os.getenv('RADARR_URL', ''),
        'radarr_api_key': os.getenv('RADARR_API_KEY', ''),
        'radarr_remote_url': os.getenv('RADARR_REMOTE_URL', ''),
        'sonarr_url': os.getenv('SONARR_URL', ''),
        'sonarr_api_key': os.getenv('SONARR_API_KEY', ''),
        'sonarr_remote_url': os.getenv('SONARR_REMOTE_URL', ''),
        'bazarr_url': os.getenv('BAZARR_URL', ''),
        'bazarr_api_key': os.getenv('BAZARR_API_KEY', ''),
        'tautulli_url': os.getenv('TAUTULLI_URL', ''),
        'tautulli_api_key': os.getenv('TAUTULLI_API_KEY', ''),
        'jellyseer_url': os.getenv('JELLYSEER_URL', ''),
        'jellyseer_api_key': os.getenv('JELLYSEER_API_KEY', ''),
        'ollama_url': os.getenv('OLLAMA_URL', 'http://localhost:11434'),
        'ollama_model': os.getenv('OLLAMA_MODEL', ''),
        'openai_api_key': os.getenv('OPENAI_API_KEY', ''),
        'openai_model': os.getenv('OPENAI_MODEL', ''),
        'pushover_key': os.getenv('PUSHOVER_USER_KEY', ''),
        'pushover_token': os.getenv('PUSHOVER_API_TOKEN', ''),
        'plex_client_id': os.getenv('PLEX_CLIENT_ID', ''),
        'thetvdb_api_key': os.getenv('THETVDB_API_KEY', '')
    }

    if request.method == 'POST':
        try:
            # Get timezone from form, or use browser-detected timezone if available
            timezone = request.form.get('timezone', '')
            
            # Create settings record with service configurations
            db.execute(
                '''INSERT INTO settings (radarr_url, radarr_api_key, radarr_remote_url,
                   sonarr_url, sonarr_api_key, sonarr_remote_url,
                   bazarr_url, bazarr_api_key,
                   tautulli_url, tautulli_api_key,
                   jellyseer_url, jellyseer_api_key,
                   ollama_url, ollama_model_name,
                   openai_api_key, openai_model_name,
                   pushover_key, pushover_token, plex_client_id,
                   thetvdb_api_key, timezone)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    request.form.get('radarr_url', ''),
                    request.form.get('radarr_api_key', ''),
                    request.form.get('radarr_remote_url', ''),
                    request.form.get('sonarr_url', ''),
                    request.form.get('sonarr_api_key', ''),
                    request.form.get('sonarr_remote_url', ''),
                    request.form.get('bazarr_url', ''),
                    request.form.get('bazarr_api_key', ''),
                    request.form.get('tautulli_url', ''),
                    request.form.get('tautulli_api_key', ''),
                    request.form.get('jellyseer_url', ''),
                    request.form.get('jellyseer_api_key', ''),
                    request.form.get('ollama_url', ''),
                    request.form.get('ollama_model', ''),
                    request.form.get('openai_api_key', ''),
                    request.form.get('openai_model', ''),
                    request.form.get('pushover_key', ''),
                    request.form.get('pushover_token', ''),
                    request.form.get('plex_client_id', ''),
                    request.form.get('thetvdb_api_key', ''),
                    timezone
                )
            )
            db.commit()

            # Clear onboarding session data
            session.pop('onboarding_username', None)

            # Capture form values before starting background thread
            has_radarr = bool(request.form.get('radarr_url') and request.form.get('radarr_api_key'))
            has_sonarr = bool(request.form.get('sonarr_url') and request.form.get('sonarr_api_key'))
            has_tautulli = bool(request.form.get('tautulli_url') and request.form.get('tautulli_api_key'))

            # Automatically queue library imports in background
            import threading
            from ..utils import sync_radarr_library, sync_sonarr_library, sync_tautulli_watch_history, process_activity_log_for_watch_status

            def run_background_imports(radarr, sonarr, tautulli):
                """Run all initial library imports in sequence"""
                with current_app.app_context():
                    try:
                        # Import Radarr library
                        if radarr:
                            current_app.logger.info("Starting automatic Radarr import after onboarding")
                            sync_radarr_library()

                        # Import Sonarr library
                        if sonarr:
                            current_app.logger.info("Starting automatic Sonarr import after onboarding")
                            sync_sonarr_library()

                        # Import Tautulli history
                        if tautulli:
                            current_app.logger.info("Starting automatic Tautulli import after onboarding")
                            sync_tautulli_watch_history(full_import=False, max_records=1000)

                            # Process watch indicators from imported history
                            current_app.logger.info("Processing watch indicators from Tautulli import")
                            watch_count = process_activity_log_for_watch_status()
                            current_app.logger.info(f"Marked {watch_count} episodes as watched from initial import")

                        current_app.logger.info("All automatic imports completed")
                    except Exception as e:
                        current_app.logger.error(f"Error during automatic imports: {e}", exc_info=True)

            # Start background thread for imports
            import_thread = threading.Thread(
                target=run_background_imports,
                args=(has_radarr, has_sonarr, has_tautulli),
                daemon=True
            )
            import_thread.start()

            flash('Onboarding complete! Your media libraries are being imported in the background. Check the Event Logs to monitor progress.', 'success')
            return redirect(url_for('main.login'))
        except Exception as e:
            db.rollback()
            flash(f'An error occurred during service configuration: {e}', 'danger')
            current_app.logger.error(f"Onboarding Step 2 error: {e}", exc_info=True)

    return render_template('onboarding_services.html', env_settings=env_settings)

@main_bp.route('/onboarding/test-service', methods=['POST'])
def onboarding_test_service():
    """
    Test service connections during onboarding (no login required).

    Expects JSON payload with 'service', 'url', and 'key' (API key).
    Returns JSON indicating success or failure.
    """
    from ..utils import (
        test_sonarr_connection_with_params,
        test_radarr_connection_with_params,
        test_bazarr_connection_with_params,
        test_ollama_connection_with_params,
        test_tautulli_connection_with_params,
        test_jellyseer_connection_with_params,
        test_pushover_notification_with_params,
        test_thetvdb_connection_with_params
    )

    data = request.json
    service = data.get('service')
    url = data.get('url')
    api_key = data.get('key')  # JavaScript sends 'key', not 'api_key'

    current_app.logger.info(f'Onboarding test for {service} at {url}')

    success = False
    error_message = 'Invalid service specified.'

    try:
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
        elif service == 'jellyseer':
            success, error_message = test_jellyseer_connection_with_params(url, api_key)
        elif service == 'pushover':
            # For pushover, 'url' is user_key and 'key' is token
            success, error_message = test_pushover_notification_with_params(api_key, url)
        elif service == 'thetvdb':
            success, error_message = test_thetvdb_connection_with_params(api_key)

        if success:
            return jsonify({'success': True, 'message': 'Connection successful!'})
        else:
            return jsonify({'success': False, 'message': error_message or 'Connection test failed'})
    except Exception as e:
        current_app.logger.error(f"Service test error for {service}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})

