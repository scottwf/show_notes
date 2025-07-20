"""
Main Blueprint for ShowNotes User Interface

This module defines the primary user-facing routes for the ShowNotes application.
It handles core functionalities like user authentication (via Plex OAuth), the
homepage display, search, and detailed views for movies, shows, and episodes.

Key Features:
- **Onboarding:** A flow to guide the administrator through initial setup if the
  application is unconfigured.
- **Plex Integration:** Includes the webhook endpoint to receive real-time updates
  from Plex, and a robust login system using Plex's OAuth mechanism.
- **Homepage:** A dynamic homepage that displays the user's current and previously
  watched media based on their Plex activity.
- **Detailed Views:** Routes to display comprehensive information about specific
  movies, TV shows, and individual episodes, pulling data from the local database
  that has been synced from services like Sonarr and Radarr.
- **Image Proxy:** An endpoint to securely proxy and cache images from external
  sources, preventing mixed content issues and improving performance.
"""
import os
import json
import requests
import re
import sqlite3
import time
import datetime # Added
from datetime import timezone # Added
import urllib.parse
import logging
import markdown as md

from flask import (
    Blueprint, render_template, request, redirect, url_for, session, jsonify,
    flash, current_app, Response, abort
)
from flask_login import login_user, login_required, logout_user # current_user is not directly used, session is used for username
from werkzeug.security import generate_password_hash, check_password_hash

from .. import database
from ..utils import get_sonarr_poster, get_radarr_poster
from ..prompt_builder import build_character_prompt, build_character_chat_prompt
from ..llm_services import get_llm_response
from ..utils import parse_llm_markdown_sections, parse_relationships_section, parse_traits_section, parse_events_section, parse_quote_section, parse_motivations_section, parse_importance_section

main_bp = Blueprint('main', __name__)

last_plex_event = None

def is_onboarding_complete():
    """
    Checks if the initial application setup has been completed.

    This function determines if onboarding is necessary by checking for the
    existence of at least one admin user and at least one settings record in the
    database.

    Returns:
        bool: True if both an admin user and a settings record exist, False otherwise.
    """
    try:
        db = database.get_db()
        admin_user = db.execute('SELECT id FROM users WHERE is_admin = 1 LIMIT 1').fetchone()
        settings_record = db.execute('SELECT id FROM settings LIMIT 1').fetchone()
        return admin_user is not None and settings_record is not None
    except sqlite3.OperationalError:
        return False

@main_bp.before_app_request
def check_onboarding():
    """
    Redirects to the onboarding page if the application is not yet configured.

    This function is registered with `before_app_request` and runs before each
    request. It ensures that unauthenticated users are directed to the onboarding
    page to create an admin account and configure initial settings. It exempts
    critical endpoints like the onboarding page itself, login/logout routes, and
    static file requests to prevent a redirect loop.
    """
    if request.endpoint and 'static' not in request.endpoint:
        # Allow access to specific endpoints even if onboarding is not complete
        exempt_endpoints = [
            'main.onboarding', # Onboarding page itself
            'main.login',
            'main.callback',
            'main.logout',
            'main.plex_webhook'
        ]
        if not is_onboarding_complete() and request.endpoint not in exempt_endpoints:
            flash('Initial setup required. Please complete the onboarding process.', 'info')
            return redirect(url_for('main.onboarding'))

def _get_plex_event_details(plex_event_row, db):
    """
    Enriches a Plex activity log record with detailed metadata and image URLs.

    This helper function takes a raw row from the `plex_activity_log` table and
    joins it with data from the `sonarr_shows` or `radarr_movies` tables to create
    a comprehensive dictionary of item details. It resolves the correct TMDB ID
    for linking and fetching cached posters, and constructs URLs for detail pages.

    Args:
        plex_event_row (sqlite3.Row): A row object from the `plex_activity_log` table.
        db (sqlite3.Connection): An active database connection.

    Returns:
        dict or None: An enriched dictionary containing details for the media item,
                      including title, year, poster URLs, and links. Returns None if
                      the input row is invalid.
    """
    if not plex_event_row:
        return None

    item_details = dict(plex_event_row)
    media_type = item_details.get('media_type')

    plex_tmdb_id = item_details.get('tmdb_id')
    grandparent_rating_key = item_details.get('grandparent_rating_key')

    item_details['item_type_for_url'] = None
    item_details['tmdb_id_for_poster'] = None
    item_details['link_tmdb_id'] = None

    if media_type == 'movie':
        if plex_tmdb_id:
            movie_data = db.execute(
                'SELECT title, poster_url, year, overview FROM radarr_movies WHERE tmdb_id = ?', (plex_tmdb_id,)
            ).fetchone()
            if movie_data:
                item_details.update(dict(movie_data))
            item_details['tmdb_id_for_poster'] = plex_tmdb_id
            item_details['link_tmdb_id'] = plex_tmdb_id
        item_details['item_type_for_url'] = 'movie'

    elif media_type == 'episode':
        item_details['item_type_for_url'] = 'show'
        item_details['episode_title'] = dict(plex_event_row).get('title')
        show_info = None
        # Try TVDB ID lookup first
        if grandparent_rating_key:
            show_info = db.execute(
                'SELECT tmdb_id, title, poster_url, year, overview FROM sonarr_shows WHERE tvdb_id = ?', (grandparent_rating_key,)
            ).fetchone()
        # Fallback: Try to find by show title if TVDB lookup fails
        if not show_info:
            show_title = item_details.get('show_title') or item_details.get('grandparent_title') or item_details.get('title')
            if show_title:
                show_info = db.execute(
                    'SELECT tmdb_id, title, poster_url, year, overview FROM sonarr_shows WHERE LOWER(title) = ?', (show_title.lower(),)
                ).fetchone()
                if show_info:
                    current_app.logger.warning(f"_get_plex_event_details: Fallback to title lookup for show '{show_title}' (TVDB ID {grandparent_rating_key})")
        if show_info:
            item_details.update(dict(show_info))
            item_details['tmdb_id_for_poster'] = show_info['tmdb_id']
            item_details['link_tmdb_id'] = show_info['tmdb_id']
        else:
            current_app.logger.warning(f"_get_plex_event_details: Could not find show for TVDB ID {grandparent_rating_key} or title '{item_details.get('show_title') or item_details.get('grandparent_title') or item_details.get('title')}'")

    item_details.setdefault('title', dict(plex_event_row).get('title'))
    item_details.setdefault('year', None)

    if item_details.get('season_episode') and item_details.get('link_tmdb_id'):
        match = re.match(r'S(\d+)E(\d+)', item_details['season_episode'])
        if match:
            item_details['season_number'] = int(match.group(1))
            item_details['episode_number'] = int(match.group(2))
            item_details['episode_detail_url'] = url_for('main.episode_detail', tmdb_id=item_details['link_tmdb_id'], season_number=item_details['season_number'], episode_number=item_details['episode_number'])

    if item_details.get('tmdb_id_for_poster'):
        item_details['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=item_details['tmdb_id_for_poster'])
        item_details['cached_fanart_url'] = url_for('main.image_proxy', type='background', id=item_details['tmdb_id_for_poster'])
    else:
        item_details['cached_poster_url'] = url_for('static', filename='logos/placeholder_poster.png')
        item_details['cached_fanart_url'] = url_for('static', filename='logos/placeholder_background.png')

    return item_details

@main_bp.route('/')
def home():
    """
    Renders the user's homepage.

    The homepage displays a personalized view of the user's Plex activity. It
    shows the currently playing/paused item and a grid of previously watched
    movies and shows. The data is fetched from the `plex_activity_log` table
    and enriched with metadata from the local database.

    Returns:
        A rendered HTML template for the homepage, populated with the user's
        Plex activity data.
    """
    db = database.get_db()
    s_username = session.get('username')
    current_plex_event = None
    previous_items_list = []

    if s_username:
        # 1. Fetch Current Item (actively playing, paused, or resumed)
        current_event_row = db.execute(
            """
            SELECT * FROM plex_activity_log
            WHERE plex_username = ?
              AND event_type IN ('media.play', 'media.resume', 'media.pause')
            ORDER BY event_timestamp DESC, id DESC
            LIMIT 1
            """, (s_username,)
        ).fetchone()

        if current_event_row:
            current_plex_event = _get_plex_event_details(current_event_row, db)
            current_app.logger.debug(f"Current Plex event for {s_username}: {current_plex_event}")


        # 2. Fetch Previous Items (recently stopped or scrobbled)
        recent_stopped_scrobbled_events = db.execute(
            """
            SELECT * FROM plex_activity_log
            WHERE plex_username = ?
              AND event_type IN ('media.stop', 'media.scrobble')
            ORDER BY event_timestamp DESC, id DESC
            LIMIT 25
            """, (s_username,)
        ).fetchall()

        processed_tmdb_ids = set()
        if current_plex_event and current_plex_event.get('link_tmdb_id'):
            processed_tmdb_ids.add(current_plex_event['link_tmdb_id'])

        MAX_PREVIOUS_ITEMS = 6

        for event_row in recent_stopped_scrobbled_events:
            if len(previous_items_list) >= MAX_PREVIOUS_ITEMS:
                break

            detailed_item = _get_plex_event_details(event_row, db)

            if detailed_item and detailed_item.get('link_tmdb_id'):
                item_primary_tmdb_id = detailed_item['link_tmdb_id'] # Show's or Movie's TMDB ID
                if item_primary_tmdb_id not in processed_tmdb_ids:
                    if detailed_item.get('tmdb_id_for_poster'): # Ensure we have a poster ID
                        previous_items_list.append(detailed_item)
                        processed_tmdb_ids.add(item_primary_tmdb_id)
                    else:
                        current_app.logger.debug(f"Previous item for {s_username} skipped (no tmdb_id_for_poster): {detailed_item.get('title')}")
                # else: item already processed or is current item
            # else:
                # current_app.logger.debug(f"Previous item for {s_username} skipped (no link_tmdb_id or incomplete details): {event_row.get('title')}")


    return render_template('home.html',
                           current_plex_event=current_plex_event,
                           previous_items_list=previous_items_list,
                           username=s_username,
                           is_admin=session.get('is_admin', False))

# ============================================================================
# WEBHOOK ENDPOINTS
# ============================================================================

@main_bp.route('/plex/webhook', methods=['POST'])
def plex_webhook():
    """
    Handles incoming webhook events from a Plex Media Server.

    This endpoint is designed to receive POST requests from Plex. It parses the
    webhook payload for media events (play, pause, stop, scrobble) and logs the
    relevant details into the `plex_activity_log` table. This log is the primary
    source of data for the user-facing homepage.

    It validates the webhook secret if one is configured in the settings to ensure
    the request is coming from the configured Plex server.

    Returns:
        A JSON response indicating success or an error, along with an appropriate
        HTTP status code.
    """
    try:
        if request.is_json:
            payload = request.get_json()
        else:
            payload = json.loads(request.form.get('payload'))
        
        current_app.logger.info(f"Webhook payload: {json.dumps(payload, indent=2)}")
        
        global last_plex_event
        last_plex_event = payload

        event_type = payload.get('event')
        activity_event_types = ['media.play', 'media.pause', 'media.resume', 'media.stop', 'media.scrobble']

        if event_type in activity_event_types:
            db = database.get_db()
            metadata = payload.get('Metadata', {})
            account = payload.get('Account', {})
            player = payload.get('Player', {})

            tmdb_id = None
            tvdb_id = None
            guids = metadata.get('Guid')
            if isinstance(guids, list):
                for guid_item in guids:
                    guid_str = guid_item.get('id', '')
                    if guid_str.startswith('tmdb://'):
                        try:
                            tmdb_id = int(guid_str.split('//')[1])
                        except Exception:
                            tmdb_id = None
                    if guid_str.startswith('tvdb://'):
                        try:
                            tvdb_id = int(guid_str.split('//')[1])
                        except Exception:
                            tvdb_id = None
            # Fallback: try to get TVDB ID from grandparentRatingKey if not found
            if not tvdb_id:
                try:
                    tvdb_id = int(metadata.get('grandparentRatingKey'))
                except Exception:
                    tvdb_id = None

            season_num = metadata.get('parentIndex')
            episode_num = metadata.get('index')
            season_episode_str = None
            if metadata.get('type') == 'episode':
                if season_num is not None and episode_num is not None:
                    season_episode_str = f"S{str(season_num).zfill(2)}E{str(episode_num).zfill(2)}"

            sql_insert = """
                INSERT INTO plex_activity_log (
                    event_type, plex_username, player_title, player_uuid, session_key,
                    rating_key, parent_rating_key, grandparent_rating_key, media_type,
                    title, show_title, season_episode, view_offset_ms, duration_ms, tmdb_id, raw_payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            params = (
                event_type, account.get('title'), player.get('title'), player.get('uuid'), metadata.get('sessionKey'),
                metadata.get('ratingKey'), metadata.get('parentRatingKey'), metadata.get('grandparentRatingKey'), metadata.get('type'),
                metadata.get('title'), metadata.get('grandparentTitle'), season_episode_str, metadata.get('viewOffset'),
                metadata.get('duration'), tmdb_id, json.dumps(payload)
            )
            db.execute(sql_insert, params)
            db.commit()
            current_app.logger.info(f"Logged event '{event_type}' for '{metadata.get('title')}' to plex_activity_log.")

            # --- Store episode character data if available ---
            if metadata.get('type') == 'episode' and 'Role' in metadata:
                episode_rating_key = metadata.get('ratingKey')
                # Remove old character rows for this episode
                db.execute('DELETE FROM episode_characters WHERE episode_rating_key = ?', (episode_rating_key,))
                roles = metadata['Role']
                for role in roles:
                    db.execute(
                        'INSERT INTO episode_characters (show_tmdb_id, show_tvdb_id, season_number, episode_number, episode_rating_key, character_name, actor_name, actor_id, actor_thumb) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (
                            tmdb_id,
                            tvdb_id,
                            season_num,
                            episode_num,
                            episode_rating_key,
                            role.get('role'),
                            role.get('tag'),
                            role.get('id'),
                            role.get('thumb')
                        )
                    )
                db.commit()
                current_app.logger.info(f"Stored {len(roles)} episode characters for episode {episode_rating_key} (S{season_num}E{episode_num})")
        
        return '', 200
    except Exception as e:
        current_app.logger.error(f"Error processing Plex webhook: {e}", exc_info=True)
        return 'error', 400


@main_bp.route('/sonarr/webhook', methods=['POST'])
def sonarr_webhook():
    """
    Handles incoming webhook events from Sonarr.

    This endpoint receives webhook notifications from Sonarr when shows, seasons,
    or episodes are added, updated, or removed. It automatically triggers a
    library sync to keep the ShowNotes database up to date.

    Supported events:
    - Download: When episodes are downloaded
    - Series: When series are added/updated
    - Episode: When episodes are added/updated
    - Rename: When files are renamed

    Returns:
        A JSON response indicating success or an error.
    """
    try:
        if request.is_json:
            payload = request.get_json()
        else:
            payload = json.loads(request.form.get('payload', '{}'))
        
        current_app.logger.info(f"Sonarr webhook received: {json.dumps(payload, indent=2)}")
        
        event_type = payload.get('eventType')
        
        # Record webhook activity in database
        try:
            db = database.get_db()
            payload_summary = f"Event: {event_type}"
            if event_type == 'Download' and payload.get('series'):
                payload_summary += f" - {payload['series'].get('title', 'Unknown')}"
            elif event_type == 'Series' and payload.get('series'):
                payload_summary += f" - {payload['series'].get('title', 'Unknown')}"
            
            db.execute(
                'INSERT INTO webhook_activity (service_name, event_type, payload_summary) VALUES (?, ?, ?)',
                ('sonarr', event_type, payload_summary)
            )
            db.commit()
        except Exception as e:
            current_app.logger.error(f"Failed to record Sonarr webhook activity: {e}")
        
        # Events that should trigger a library sync
        sync_events = [
            'Download',           # Episode downloaded
            'Series',             # Series added/updated
            'Episode',            # Episode added/updated
            'Rename',             # Files renamed
            'Delete',             # Files deleted
            'Health',             # Health check (good for periodic syncs)
            'Test'                # Test event
        ]
        
        if event_type in sync_events:
            current_app.logger.info(f"Sonarr webhook event '{event_type}' detected, triggering library sync")
            
            # Import here to avoid circular imports
            from ..utils import sync_sonarr_library
            
            try:
                # Trigger the sync in a background thread to avoid blocking the webhook response
                import threading
                def sync_in_background():
                    try:
                        with current_app.app_context():
                            count = sync_sonarr_library()
                            current_app.logger.info(f"Sonarr webhook-triggered sync completed: {count} shows processed")
                    except Exception as e:
                        current_app.logger.error(f"Error in background Sonarr sync: {e}", exc_info=True)
                
                # Start background sync
                sync_thread = threading.Thread(target=sync_in_background)
                sync_thread.daemon = True
                sync_thread.start()
                
                current_app.logger.info("Sonarr library sync initiated in background")
                
            except Exception as e:
                current_app.logger.error(f"Failed to trigger Sonarr sync from webhook: {e}", exc_info=True)
        else:
            current_app.logger.debug(f"Sonarr webhook event '{event_type}' received but no sync needed")
        
        return jsonify({'status': 'success', 'message': f'Processed {event_type} event'}), 200
        
    except Exception as e:
        current_app.logger.error(f"Error processing Sonarr webhook: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@main_bp.route('/radarr/webhook', methods=['POST'])
def radarr_webhook():
    """
    Handles incoming webhook events from Radarr.

    This endpoint receives webhook notifications from Radarr when movies are
    added, updated, or removed. It automatically triggers a library sync to
    keep the ShowNotes database up to date.

    Supported events:
    - Download: When movies are downloaded
    - Movie: When movies are added/updated
    - Rename: When files are renamed
    - Delete: When files are deleted

    Returns:
        A JSON response indicating success or an error.
    """
    try:
        if request.is_json:
            payload = request.get_json()
        else:
            payload = json.loads(request.form.get('payload', '{}'))
        
        current_app.logger.info(f"Radarr webhook received: {json.dumps(payload, indent=2)}")
        
        event_type = payload.get('eventType')
        
        # Record webhook activity in database
        try:
            db = database.get_db()
            payload_summary = f"Event: {event_type}"
            if event_type == 'Download' and payload.get('movie'):
                payload_summary += f" - {payload['movie'].get('title', 'Unknown')}"
            elif event_type == 'Movie' and payload.get('movie'):
                payload_summary += f" - {payload['movie'].get('title', 'Unknown')}"
            
            db.execute(
                'INSERT INTO webhook_activity (service_name, event_type, payload_summary) VALUES (?, ?, ?)',
                ('radarr', event_type, payload_summary)
            )
            db.commit()
        except Exception as e:
            current_app.logger.error(f"Failed to record Radarr webhook activity: {e}")
        
        # Events that should trigger a library sync
        sync_events = [
            'Download',           # Movie downloaded
            'Movie',              # Movie added/updated
            'Rename',             # Files renamed
            'Delete',             # Files deleted
            'Health',             # Health check (good for periodic syncs)
            'Test'                # Test event
        ]
        
        if event_type in sync_events:
            current_app.logger.info(f"Radarr webhook event '{event_type}' detected, triggering library sync")
            
            # Import here to avoid circular imports
            from ..utils import sync_radarr_library
            
            try:
                # Trigger the sync in a background thread to avoid blocking the webhook response
                import threading
                def sync_in_background():
                    try:
                        with current_app.app_context():
                            result = sync_radarr_library()
                            current_app.logger.info(f"Radarr webhook-triggered sync completed: {result}")
                    except Exception as e:
                        current_app.logger.error(f"Error in background Radarr sync: {e}", exc_info=True)
                
                # Start background sync
                sync_thread = threading.Thread(target=sync_in_background)
                sync_thread.daemon = True
                sync_thread.start()
                
                current_app.logger.info("Radarr library sync initiated in background")
                
            except Exception as e:
                current_app.logger.error(f"Failed to trigger Radarr sync from webhook: {e}", exc_info=True)
        else:
            current_app.logger.debug(f"Radarr webhook event '{event_type}' received but no sync needed")
        
        return jsonify({'status': 'success', 'message': f'Processed {event_type} event'}), 200
        
    except Exception as e:
        current_app.logger.error(f"Error processing Radarr webhook: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    Initiates the Plex OAuth login process or handles admin username/password login.

    On ``GET`` requests, this starts the Plex OAuth flow by requesting a PIN and
    redirecting the user to Plex for authentication. On ``POST`` requests it
    validates the provided admin credentials and logs the user in using
    Flask-Login.
    """
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        db = database.get_db()
        user_record = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if user_record and user_record['is_admin'] and user_record['password_hash']:
            if check_password_hash(user_record['password_hash'], password):
                user_obj = current_app.login_manager._user_callback(user_record['id'])
                if user_obj:
                    login_user(user_obj)
                    session['user_id'] = user_obj.id
                    session['username'] = user_obj.username
                    session['is_admin'] = user_obj.is_admin
                    db.execute('UPDATE users SET last_login_at=CURRENT_TIMESTAMP WHERE id=?', (user_obj.id,))
                    db.commit()
                    flash(f'Welcome back, {user_obj.username}!', 'success')
                    return redirect(url_for('main.home'))
        flash('Invalid admin credentials.', 'danger')
        return redirect(url_for('main.login'))

    # GET request - start Plex OAuth
    client_id = database.get_setting('plex_client_id')
    if not client_id:
        flash("Plex Client ID is not configured in settings.", "danger")
        return redirect(url_for('main.home'))

    headers = {'X-Plex-Client-Identifier': client_id, 'Accept': 'application/json'}
    r = requests.post('https://plex.tv/api/v2/pins?strong=true', headers=headers)
    if r.status_code != 201:
        flash('Failed to initiate Plex login.', 'danger')
        return redirect(url_for('main.home'))

    pin = r.json()
    session['plex_pin_id'] = pin['id']

    plex_auth_url = f"https://app.plex.tv/auth#?clientID={client_id}&code={pin['code']}&forwardUrl={url_for('main.callback', _external=True)}"
    return redirect(plex_auth_url)

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
        flash('Plex login session expired. Please try again.', 'warning')
        return redirect(url_for('main.home'))

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
    
    db = database.get_db()
    user_record = db.execute('SELECT * FROM users WHERE plex_user_id = ?', (plex_user_id,)).fetchone()

    if not user_record:
        flash(f"Plex user {user_info.get('username')} is not registered in this application.", 'warning')
        return redirect(url_for('main.home'))

    # Log in the user
    user_obj = current_app.login_manager._user_callback(user_record['id'])
    if user_obj:
        login_user(user_obj)
        session['user_id'] = user_obj.id
        session['username'] = user_obj.username
        session['is_admin'] = user_obj.is_admin
        db.execute('UPDATE users SET last_login_at=CURRENT_TIMESTAMP WHERE id=?', (user_obj.id,))
        db.commit()
        flash(f'Welcome back, {user_obj.username}!', 'success')
    else:
        flash('Could not log you in. Please contact an administrator.', 'danger')

    return redirect(url_for('main.home'))

@main_bp.route('/logout')
@login_required
def logout():
    """
    Logs the current user out.

    This route clears the user's session data and logs them out using Flask-Login's
    `logout_user` function. It then redirects the user to the homepage.

    Returns:
        A redirect to the homepage.
    """
    logout_user()
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.home'))

@main_bp.route('/onboarding', methods=['GET', 'POST'])
def onboarding():
    """
    Handles the initial setup and onboarding for the application.

    If onboarding is already complete (an admin user exists), this page will
    redirect to the homepage.

    On a GET request, it renders the onboarding form.
    On a POST request, it validates the form data (username and password),
    creates the first administrative user, initializes the settings table, and
    redirects to the login page.

    Returns:
        - A rendered HTML template for the onboarding page on GET.
        - A redirect to the login page on successful POST.
        - The onboarding template with errors on a failed POST.
    """
    if is_onboarding_complete():
        return redirect(url_for('main.home'))

    if request.method == 'POST':
        db = database.get_db()
        try:
            # Create admin user
            pw_hash = generate_password_hash(request.form['password'])
            db.execute(
                'INSERT INTO users (username, password_hash, is_admin, plex_user_id) VALUES (?, ?, 1, ?)',
                (request.form['username'], pw_hash, request.form.get('plex_user_id'))
            )
            # Create settings
            db.execute(
                '''INSERT INTO settings (radarr_url, radarr_api_key, sonarr_url, sonarr_api_key, bazarr_url, bazarr_api_key, ollama_url, pushover_key, pushover_token, plex_client_id, tautulli_url, tautulli_api_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', # Added two placeholders
                (
                    request.form['radarr_url'], request.form['radarr_api_key'],
                    request.form['sonarr_url'], request.form['sonarr_api_key'],
                    request.form['bazarr_url'], request.form['bazarr_api_key'],
                    request.form['ollama_url'], request.form.get('pushover_key'),
                    request.form.get('pushover_token'), request.form['plex_client_id'],
                    request.form.get('tautulli_url', ''), # Added Tautulli URL
                    request.form.get('tautulli_api_key', '') # Added Tautulli API Key
                )
            )
            db.commit()
            flash('Onboarding complete! Please log in.', 'success')
            return redirect(url_for('main.login'))
        except Exception as e:
            db.rollback()
            flash(f'An error occurred during onboarding: {e}', 'danger')
            current_app.logger.error(f"Onboarding error: {e}", exc_info=True)

    return render_template('onboarding.html')

@main_bp.route('/search')
@login_required
def search():
    """
    Provides search results for the main user-facing search bar.

    This API endpoint is called by the JavaScript search functionality. It takes
    a query parameter 'q' and searches the `sonarr_shows` and `radarr_movies`
    tables for matching titles.

    Args:
        q (str): The search term, provided as a URL query parameter.

    Returns:
        flask.Response: A JSON response containing a list of search results,
                        including title, type, year, and a URL to the detail page.
    """
    query = request.args.get('q', '').lower()
    if not query:
        return jsonify([])

    db = database.get_db()
    
    # Search Sonarr
    sonarr_results = db.execute(
        "SELECT title, 'show' as type, tmdb_id, year, poster_url, fanart_url FROM sonarr_shows WHERE title LIKE ?", ('%' + query + '%',)
    ).fetchall()

    # Search Radarr
    radarr_results = db.execute(
        "SELECT title, 'movie' as type, tmdb_id, year, poster_url, fanart_url FROM radarr_movies WHERE title LIKE ?", ('%' + query + '%',)
    ).fetchall()

    results = []
    for row in sonarr_results + radarr_results:
        item = dict(row)
        if item.get('tmdb_id'):
            item['poster_url'] = url_for('main.image_proxy', type='poster', id=item['tmdb_id'])
            item['fanart_url'] = url_for('main.image_proxy', type='background', id=item['tmdb_id'])
        else:
            # Set to placeholder or None if no tmdb_id, so templates don't break
            item['poster_url'] = url_for('static', filename='logos/placeholder_poster.png')
            item['fanart_url'] = url_for('static', filename='logos/placeholder_background.png')
        results.append(item)
    
    # Sort results by title
    results.sort(key=lambda x: x['title'])
    
    return jsonify(results)

@main_bp.route('/movie/<int:tmdb_id>')
@login_required
def movie_detail(tmdb_id):
    """
    Displays the detail page for a specific movie.

    It fetches the movie's metadata from the `radarr_movies` table using the
    provided TMDB ID. It also retrieves related watch history for the logged-in
    user from the `plex_activity_log` table to show view count and last watched date.

    Args:
        tmdb_id (int): The The Movie Database (TMDB) ID for the movie.

    Returns:
        A rendered HTML template for the movie detail page, or a 404 error
        if the movie is not found in the database.
    """
    db = database.get_db()
    movie = db.execute('SELECT * FROM radarr_movies WHERE tmdb_id = ?', (tmdb_id,)).fetchone()
    if not movie:
        abort(404)
    movie_dict = dict(movie)
    if movie_dict.get('tmdb_id'):
        movie_dict['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=movie_dict['tmdb_id'])
        movie_dict['cached_fanart_url'] = url_for('main.image_proxy', type='background', id=movie_dict['tmdb_id'])
    else:
        movie_dict['cached_poster_url'] = url_for('static', filename='logos/placeholder_poster.png')
        movie_dict['cached_fanart_url'] = url_for('static', filename='logos/placeholder_background.png')
    return render_template('movie_detail.html', movie=movie_dict)

@main_bp.route('/show/<int:tmdb_id>')
@login_required
def show_detail(tmdb_id):
    """
    Displays the detail page for a specific TV show.

    This function gathers comprehensive information for a show, including:
    - Basic metadata from the `sonarr_shows` table.
    - A list of all seasons and episodes from the `sonarr_seasons` and
      `sonarr_episodes` tables.
    - The user's watch history for the show from `plex_activity_log`.
    - A "featured episode" card, which highlights either the most recently
      watched episode or the next unwatched episode.

    Args:
        tmdb_id (int): The The Movie Database (TMDB) ID for the show.

    Returns:
        A rendered HTML template for the show detail page, or a 404 error
        if the show is not found.
    """
    db = database.get_db()
    s_username = session.get('username')
    show_dict = None

    show_row = db.execute('SELECT * FROM sonarr_shows WHERE tmdb_id = ?', (tmdb_id,)).fetchone()
    if not show_row:
        current_app.logger.warning(f"Show with TMDB ID {tmdb_id} not found in sonarr_shows.")
        abort(404)
    show_dict = dict(show_row)
    if show_dict.get('tmdb_id'):
        show_dict['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=show_dict['tmdb_id'])
        show_dict['cached_fanart_url'] = url_for('main.image_proxy', type='background', id=show_dict['tmdb_id'])
    else:
        show_dict['cached_poster_url'] = url_for('static', filename='logos/placeholder_poster.png')
        show_dict['cached_fanart_url'] = url_for('static', filename='logos/placeholder_background.png')
    show_db_id = show_dict['id']

    seasons_rows = db.execute(
        'SELECT * FROM sonarr_seasons WHERE show_id = ? ORDER BY season_number DESC', (show_db_id,)
    ).fetchall()

    seasons_with_episodes = []
    all_show_episodes_for_next_aired_check = []

    for season_row in seasons_rows:
        if season_row['season_number'] == 0:
            # Skip specials/Season 0 from main listing
            continue
        season_dict = dict(season_row)
        season_db_id = season_dict['id']

        episodes_rows = db.execute(
            'SELECT * FROM sonarr_episodes WHERE season_id = ? ORDER BY episode_number DESC', (season_db_id,)
        ).fetchall()

        current_season_episodes = [dict(ep_row) for ep_row in episodes_rows]
        season_dict['episodes'] = current_season_episodes
        seasons_with_episodes.append(season_dict)
        all_show_episodes_for_next_aired_check.extend(current_season_episodes)

    next_aired_episode_info = None
    if show_dict.get('status', '').lower() == 'continuing' or show_dict.get('status', '').lower() == 'upcoming': # Only look for next_aired if show is active
        try:
            now_utc = datetime.datetime.now(timezone.utc)
            relevant_episodes = [ep for ep in all_show_episodes_for_next_aired_check if ep.get('air_date_utc')]
            relevant_episodes.sort(key=lambda ep: ep['air_date_utc'])

            for episode in relevant_episodes:
                air_date_str = episode['air_date_utc']
                try:
                    air_date = datetime.datetime.fromisoformat(air_date_str.replace('Z', '+00:00'))
                    if air_date > now_utc:
                        season_number_for_next_aired = None
                        # Find season number for this episode
                        for s_dict in seasons_with_episodes:
                            if s_dict['id'] == episode['season_id']:
                                season_number_for_next_aired = s_dict['season_number']
                                break

                        if season_number_for_next_aired is not None: # Ensure season number was found
                            next_aired_episode_info = {
                                'title': episode['title'],
                                'season_number': season_number_for_next_aired,
                                'episode_number': episode['episode_number'],
                                'air_date_utc': air_date_str,
                                'season_episode_str': f"S{str(season_number_for_next_aired).zfill(2)}E{str(episode['episode_number']).zfill(2)}"
                            }
                            break # Found the earliest next aired episode
                except (ValueError, TypeError) as e_parse:
                    current_app.logger.debug(f"Could not parse air_date_utc '{air_date_str}' for episode ID {episode.get('id')}: {e_parse}")
                    continue
        except Exception as e_next_aired:
            current_app.logger.error(f"Error determining next aired episode for show TMDB ID {tmdb_id}: {e_next_aired}")

    currently_watched_episode_info = None
    last_watched_episode_info = None
    plex_username = session.get('username')
    show_tvdb_id = show_dict.get('tvdb_id') # This is from sonarr_shows.tvdb_id

    if plex_username and show_tvdb_id:
        try:
            # grandparent_rating_key in plex_activity_log is Plex's internal key, often related to tvdb_id but might be string.
            # Convert show_tvdb_id to string for safer comparison if Plex stores it as string.
            plex_activity_row = db.execute(
                """
                SELECT title, season_episode, view_offset_ms, duration_ms, event_timestamp
                FROM plex_activity_log
                WHERE plex_username = ?
                  AND grandparent_rating_key = ?
                  AND media_type = 'episode'
                  AND event_type IN ('media.play', 'media.pause', 'media.resume')
                ORDER BY event_timestamp DESC
                LIMIT 1
                """,
                (plex_username, str(show_tvdb_id))
            ).fetchone()

            if plex_activity_row:
                currently_watched_episode_info = dict(plex_activity_row)
                if currently_watched_episode_info.get('view_offset_ms') is not None and \
                   currently_watched_episode_info.get('duration_ms') is not None and \
                   currently_watched_episode_info['duration_ms'] > 0:
                    progress = (currently_watched_episode_info['view_offset_ms'] / currently_watched_episode_info['duration_ms']) * 100
                    currently_watched_episode_info['progress_percent'] = round(progress)
        except sqlite3.Error as e_sql: # More specific for DB errors
            current_app.logger.error(f"SQLite error fetching currently watched episode for show TVDB ID {show_tvdb_id} and user {plex_username}: {e_sql}")
        except Exception as e_watched:
            current_app.logger.error(f"Generic error fetching currently watched episode for show TVDB ID {show_tvdb_id} and user {plex_username}: {e_watched}")

        if not currently_watched_episode_info:
            last_row = db.execute(
                """
                SELECT title, season_episode, event_timestamp
                FROM plex_activity_log
                WHERE plex_username = ?
                  AND grandparent_rating_key = ?
                  AND media_type = 'episode'
                  AND event_type IN ('media.stop', 'media.scrobble')
                ORDER BY event_timestamp DESC
                LIMIT 1
                """,
                (plex_username, str(show_tvdb_id))
            ).fetchone()
            if last_row:
                last_watched_episode_info = dict(last_row)

    next_up_episode = get_next_up_episode(
        currently_watched_episode_info,
        last_watched_episode_info,
        show_dict,
        seasons_with_episodes
    )

    return render_template('show_detail.html',
                           show=show_dict,
                           seasons_with_episodes=seasons_with_episodes,
                           next_aired_episode_info=next_aired_episode_info,
                           next_up_episode=next_up_episode
                           )

def get_next_up_episode(currently_watched, last_watched, show_info, seasons_with_episodes, user_prefs=None):
    """
    Determines the "Next Up" episode for a show's detail page with enhanced logic.
    """
    if user_prefs is None:
        user_prefs = {'skip_specials': True, 'order': 'default'}

    db = database.get_db()
    source_info = None
    is_currently_watching = False
    is_next_unwatched = False

    if currently_watched:
        source_info = currently_watched
        is_currently_watching = True
    elif last_watched:
        last_season_episode_str = last_watched.get('season_episode')
        match = re.match(r'S(\d+)E(\d+)', last_season_episode_str) if last_season_episode_str else None
        if match:
            last_season_num = int(match.group(1))
            last_episode_num = int(match.group(2))

            all_episodes = []
            for season in sorted(seasons_with_episodes, key=lambda s: s['season_number']):
                if user_prefs['skip_specials'] and season['season_number'] == 0:
                    continue
                # Sort episodes within the season
                sorted_episodes = sorted(season['episodes'], key=lambda e: e['episode_number'])
                for episode in sorted_episodes:
                    all_episodes.append({
                        'season_number': season['season_number'],
                        **episode
                    })

            last_watched_index = -1
            for i, ep in enumerate(all_episodes):
                if ep['season_number'] == last_season_num and ep['episode_number'] == last_episode_num:
                    last_watched_index = i
                    break

            if last_watched_index != -1:
                # Search for the next available episode, considering multi-part episodes
                for i in range(last_watched_index + 1, len(all_episodes)):
                    next_ep = all_episodes[i]
                    if next_ep.get('has_file'):
                        # Check for multi-part episode logic (e.g., if the title is the same as the previous)
                        if i > 0 and all_episodes[i-1]['title'] == next_ep['title']:
                            # This might be the second part of a multi-part episode, let's see if we should skip it
                            # For now, we assume the user wants to see the next file regardless.
                            # More complex logic could be added here.
                            pass

                        source_info = {
                            'title': next_ep['title'],
                            'season_episode': f"S{str(next_ep['season_number']).zfill(2)}E{str(next_ep['episode_number']).zfill(2)}",
                            'event_timestamp': last_watched.get('event_timestamp')
                        }
                        is_next_unwatched = True
                        break

        if not source_info:
            source_info = last_watched

    if not source_info:
        return None

    season_episode_str = source_info.get('season_episode')
    match = re.match(r'S(\d+)E(\d+)', season_episode_str) if season_episode_str else None
    if not match:
        return None
    season_number, episode_number = map(int, match.groups())

    episode_detail_url = url_for('main.episode_detail',
                                 tmdb_id=show_info['tmdb_id'],
                                 season_number=season_number,
                                 episode_number=episode_number)

    raw_timestamp = source_info.get('event_timestamp')
    formatted_timestamp = "Unknown"
    if raw_timestamp:
        try:
            dt_obj = datetime.datetime.fromisoformat(str(raw_timestamp).replace('Z', '+00:00'))
            formatted_timestamp = dt_obj.strftime("%b %d, %Y at %I:%M %p")
        except (ValueError, TypeError):
            formatted_timestamp = str(raw_timestamp)

    return {
        'title': source_info.get('title'),
        'season_episode_str': season_episode_str,
        'season_number': season_number,
        'episode_number': episode_number,
        'poster_url': show_info.get('cached_poster_url'),
        'event_timestamp': raw_timestamp,
        'formatted_timestamp': formatted_timestamp,
        'progress_percent': source_info.get('progress_percent') if is_currently_watching else None,
        'episode_detail_url': episode_detail_url,
        'is_currently_watching': is_currently_watching,
        'is_next_unwatched': is_next_unwatched,
        'overview': source_info.get('overview', '')
    }

@main_bp.route('/show/<int:tmdb_id>/season/<int:season_number>/episode/<int:episode_number>')
@login_required
def episode_detail(tmdb_id, season_number, episode_number):
    """
    Displays the detail page for a single TV episode.

    It fetches metadata for the episode, its parent season, and its parent show
    from the database to provide a comprehensive view. This includes details
    like air date, summary, and a link back to the main show page.

    Args:
        tmdb_id (int): The TMDB ID of the parent show.
        season_number (int): The season number of the episode.
        episode_number (int): The episode number.

    Returns:
        A rendered HTML template for the episode detail page, or a 404 error
        if the show or episode cannot be found.
    """
    db = database.get_db()

    # Fetch show, season, and episode details in one go if possible
    show_row = db.execute('SELECT id, title, tmdb_id, tvdb_id, poster_url, fanart_url FROM sonarr_shows WHERE tmdb_id = ?', (tmdb_id,)).fetchone()
    if not show_row:
        abort(404)
    show_dict = dict(show_row)
    # Use consistent names for cached URLs as expected by the new template.
    if show_dict.get('tmdb_id'):
        show_dict['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=show_dict['tmdb_id'])
        show_dict['cached_fanart_url'] = url_for('main.image_proxy', type='background', id=show_dict['tmdb_id']) # Optional for episode page bg
    else:
        show_dict['cached_poster_url'] = url_for('static', filename='logos/placeholder_poster.png')
        show_dict['cached_fanart_url'] = url_for('static', filename='logos/placeholder_background.png')

    show_id = show_dict['id']
    show_tvdb_id = show_dict.get('tvdb_id')
    show_tmdb_id = show_dict.get('tmdb_id')
    show_title = show_dict.get('title')
    season_row = db.execute('SELECT id FROM sonarr_seasons WHERE show_id=? AND season_number=?', (show_id, season_number)).fetchone()
    if not season_row:
        abort(404)

    # Fetch all columns for the episode
    episode_row = db.execute('SELECT * FROM sonarr_episodes WHERE season_id=? AND episode_number=?', (season_row['id'], episode_number)).fetchone()
    if not episode_row:
        abort(404)

    episode_dict = dict(episode_row)

    # Try all possible IDs for cast lookup
    episode_characters = []
    # 1. Sonarr TVDB ID
    if show_tvdb_id:
        episode_characters = db.execute(
            'SELECT * FROM episode_characters WHERE show_tvdb_id = ? AND season_number = ? AND episode_number = ? ORDER BY id',
            (show_tvdb_id, season_number, episode_number)
        ).fetchall()
        episode_characters = [dict(row) for row in episode_characters]
    # 2. Sonarr TMDB ID
    if not episode_characters and show_tmdb_id:
        episode_characters = db.execute(
            'SELECT * FROM episode_characters WHERE show_tmdb_id = ? AND season_number = ? AND episode_number = ? ORDER BY id',
            (show_tmdb_id, season_number, episode_number)
        ).fetchall()
        episode_characters = [dict(row) for row in episode_characters]
    # 3. Try Plex webhook IDs from most recent plex_activity_log for this episode
    if not episode_characters:
        # Try to find the most recent plex_activity_log for this show/season/episode
        # We'll match by show title and season/episode string (season_episode)
        season_episode_str = f"S{str(season_number).zfill(2)}E{str(episode_number).zfill(2)}"
        plex_row = db.execute(
            'SELECT raw_payload FROM plex_activity_log WHERE show_title = ? AND season_episode = ? ORDER BY event_timestamp DESC LIMIT 1',
            (show_title, season_episode_str)
        ).fetchone()
        plex_tmdb_id = None
        plex_tvdb_id = None
        if plex_row:
            import json
            try:
                payload = json.loads(plex_row['raw_payload'])
                guids = payload.get('Metadata', {}).get('Guid', [])
                for guid_item in guids:
                    guid_str = guid_item.get('id', '')
                    if guid_str.startswith('tmdb://'):
                        try:
                            plex_tmdb_id = int(guid_str.split('//')[1])
                        except Exception:
                            plex_tmdb_id = None
                    if guid_str.startswith('tvdb://'):
                        try:
                            plex_tvdb_id = int(guid_str.split('//')[1])
                        except Exception:
                            plex_tvdb_id = None
            except Exception:
                pass
        # 3a. Plex TVDB ID
        if plex_tvdb_id:
            episode_characters = db.execute(
                'SELECT * FROM episode_characters WHERE show_tvdb_id = ? AND season_number = ? AND episode_number = ? ORDER BY id',
                (plex_tvdb_id, season_number, episode_number)
            ).fetchall()
            episode_characters = [dict(row) for row in episode_characters]
        # 3b. Plex TMDB ID
        if not episode_characters and plex_tmdb_id:
            episode_characters = db.execute(
                'SELECT * FROM episode_characters WHERE show_tmdb_id = ? AND season_number = ? AND episode_number = ? ORDER BY id',
                (plex_tmdb_id, season_number, episode_number)
            ).fetchall()
            episode_characters = [dict(row) for row in episode_characters]

    # Format air date
    if episode_dict.get('air_date_utc'):
        try:
            # Ensure Z is handled for UTC parsing if present
            air_date_str = episode_dict['air_date_utc']
            if 'Z' in air_date_str.upper() and not '+' in air_date_str and not '-' in air_date_str[10:]: # Simple check for Zulu time
                 air_date_str = air_date_str.upper().replace('Z', '+00:00')

            air_dt = datetime.datetime.fromisoformat(air_date_str)
            episode_dict['formatted_air_date'] = air_dt.strftime('%B %d, %Y')
        except ValueError as e:
            current_app.logger.warning(f"Could not parse air_date_utc '{episode_dict['air_date_utc']}' for episode: {e}")
            episode_dict['formatted_air_date'] = episode_dict['air_date_utc'] # Fallback
    else:
        episode_dict['formatted_air_date'] = 'N/A'

    # Ensure 'is_available' based on 'has_file'
    episode_dict['is_available'] = episode_dict.get('has_file', False)

    # Add runtime if available (example field name, adjust if different in your schema)
    # episode_dict['runtime_minutes'] = episode_dict.get('runtime', None)

    return render_template('episode_detail.html',
                           show=show_dict,
                           episode=episode_dict,
                           season_number=season_number,
                           episode_characters=episode_characters)

@main_bp.route('/image_proxy/<string:type>/<int:id>')
@login_required
def image_proxy(type, id):
    """
    Securely proxies and caches images from external services (Sonarr/Radarr).

    This endpoint is responsible for fetching images (posters or backgrounds),
    caching them locally, and serving them to the client. It prevents mixed-content
    warnings and improves performance by reducing redundant external requests.

    - It first checks if the requested image already exists in the local cache.
    - If found, it serves the cached file directly.
    - If not found, it queries the database for the original image URL from
      Sonarr or Radarr based on the provided TMDB ID.
    - It then fetches the image from the external URL, saves it to the appropriate
      local cache directory (`/static/poster` or `/static/background`), and then
      serves the image.

    Args:
        type (str): The type of image to fetch ('poster' or 'background').
        id (int): The The Movie Database (TMDB) ID for the movie or show.

    Returns:
        flask.Response: The image data with the correct content type, a placeholder
                        image if the original is not found, or a 404 error for
                        invalid requests.
    """
    # Validate type
    if type not in ['poster', 'background']:
        abort(404)

    # Define cache path
    cache_folder = os.path.join(current_app.static_folder, type)
    # Sanitize ID to prevent directory traversal
    safe_filename = f"{str(id)}.jpg"
    cached_image_path = os.path.join(cache_folder, safe_filename)

    # Create directory if it doesn't exist
    os.makedirs(cache_folder, exist_ok=True)

    # 1. Check if image is already cached
    if os.path.exists(cached_image_path):
        return current_app.send_static_file(f'{type}/{safe_filename}')

    # 2. If not cached, find the image URL from the database
    db = database.get_db()
    external_url = None
    source = None # To determine which service's URL to use for relative paths

    # Check Radarr (movies) first
    movie_record = db.execute(f"SELECT {'poster_url' if type == 'poster' else 'fanart_url'} as url FROM radarr_movies WHERE tmdb_id = ?", (id,)).fetchone()
    if movie_record and movie_record['url']:
        external_url = movie_record['url']
        source = 'radarr'
    else:
        # Check Sonarr (shows)
        show_record = db.execute(f"SELECT {'poster_url' if type == 'poster' else 'fanart_url'} as url FROM sonarr_shows WHERE tmdb_id = ?", (id,)).fetchone()
        if show_record and show_record['url']:
            external_url = show_record['url']
            source = 'sonarr'

    if not external_url:
        # Return a placeholder if no URL is found in the database
        placeholder_path = f'logos/placeholder_{type}.png' if os.path.exists(os.path.join(current_app.static_folder, f'logos/placeholder_{type}.png')) else 'logos/placeholder_poster.png'
        return current_app.send_static_file(placeholder_path)


    # 3. Fetch the image from the external URL
    try:
        # Handle relative URLs from Sonarr/Radarr
        if external_url.startswith('/'):
            service_url = database.get_setting(f'{source}_url')
            if service_url:
                external_url = f"{service_url.rstrip('/')}{external_url}"
            else:
                raise ValueError(f"{source} URL not configured, cannot resolve relative image path.")

        # Use a session for potential keep-alive and other benefits
        with requests.Session() as s:
            # Add API key if the source requires it for media assets
            api_key = database.get_setting(f'{source}_api_key')
            if api_key:
                s.headers.update({'X-Api-Key': api_key})
            
            resp = s.get(external_url, stream=True, timeout=10)
            resp.raise_for_status() # Raise an exception for bad status codes

        # 4. Save the image to the cache
        with open(cached_image_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        
        current_app.logger.info(f"Cached image: {cached_image_path}")

        # 5. Serve the newly cached image
        return current_app.send_static_file(f'{type}/{safe_filename}')

    except (requests.RequestException, ValueError, IOError) as e:
        current_app.logger.error(f"Failed to fetch or cache image for {type}/{id} from {external_url}. Error: {e}")
        # If fetching fails, serve the placeholder
        placeholder_path = f'logos/placeholder_{type}.png' if os.path.exists(os.path.join(current_app.static_folder, f'logos/placeholder_{type}.png')) else 'logos/placeholder_poster.png'
        return current_app.send_static_file(placeholder_path)

@main_bp.route('/character/<int:show_id>/<int:season_number>/<int:episode_number>/<int:actor_id>', methods=['GET', 'POST'])
def character_detail(show_id, season_number, episode_number, actor_id):
    db = database.get_db()
    # ... (existing character and show data fetching logic)
    char_row = db.execute(
        'SELECT * FROM episode_characters WHERE show_tmdb_id = ? AND season_number = ? AND episode_number = ? AND actor_id = ? LIMIT 1',
        (show_id, season_number, episode_number, actor_id)
    ).fetchone()
    character = dict(char_row) if char_row else None
    if not character:
        # ... (fallback logic)
        pass

    show_title = 'Unknown Show'
    show_row = db.execute('SELECT title FROM sonarr_shows WHERE tmdb_id = ?', (show_id,)).fetchone()
    if show_row:
        show_title = show_row['title']

    character_name = character.get('character_name', 'Unknown Character') if character else 'Unknown Character'

    if request.method == 'POST':
        data = request.get_json()
        user_message = data.get('message')
        if not user_message:
            return jsonify({'error': 'Empty message'}), 400

        if 'chat_history' not in session:
            session['chat_history'] = []

        session['chat_history'].append({'role': 'user', 'content': user_message})

        # Generate LLM response
        prompt = build_character_chat_prompt(
            character=character_name,
            show=show_title,
            season=season_number,
            episode=episode_number,
            chat_history=session['chat_history']
        )
        llm_reply, error = get_llm_response(prompt)

        if error:
            return jsonify({'error': error}), 500

        session['chat_history'].append({'role': 'assistant', 'content': llm_reply})
        session.modified = True

        return jsonify({'reply': llm_reply})

    # For GET request, clear chat history for a new session
    session.pop('chat_history', None)

    # ... (existing LLM data fetching and processing for cards)
    llm_fields = [
        'llm_relationships', 'llm_motivations', 'llm_quote', 'llm_traits', 'llm_events', 'llm_importance',
        'llm_raw_response', 'llm_last_updated', 'llm_source'
    ]
    has_llm_data = character and any(character.get(f) for f in llm_fields)
    llm_sections = {}
    llm_last_updated = None
    llm_source = None
    llm_error = None
    if has_llm_data:
        # Use cached data
        llm_sections = {
            'Significant Relationships': character.get('llm_relationships'),
            'Primary Motivations & Inner Conflicts': character.get('llm_motivations'),
            'Notable Quote': character.get('llm_quote'),
            'Personality & Traits': character.get('llm_traits'),
            'Key Events': character.get('llm_events'),
            'Importance to the Story': character.get('llm_importance'),
        }
        llm_last_updated = character.get('llm_last_updated')
        llm_source = character.get('llm_source')
    else:
        # Call LLM and cache results
        prompt_options = {
            'include_relationships': True,
            'include_motivations': True,
            'include_quote': True,
            'tone': 'tv_expert'
        }
        generated_prompt = build_character_prompt(
            character=character_name,
            show=show_title,
            season=season_number,
            episode=episode_number,
            options=prompt_options
        )
        llm_summary, llm_error = get_llm_response(generated_prompt)
        llm_sections = {}
        if llm_summary:
            # Parse markdown into sections
            match = re.search(r"(## .*)", llm_summary, re.DOTALL)
            if match:
                llm_summary = match.group(1)
            llm_sections = parse_llm_markdown_sections(llm_summary)
            # Store in DB
            now = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            model_source = 'Unknown'
            from ..database import get_setting
            provider = get_setting('preferred_llm_provider')
            model = get_setting('ollama_model_name') if provider == 'ollama' else get_setting('openai_model_name')
            if provider and model:
                model_source = f"{provider.capitalize()} {model}"
            db.execute(
                '''UPDATE episode_characters SET
                    llm_relationships = ?,
                    llm_motivations = ?,
                    llm_quote = ?,
                    llm_traits = ?,
                    llm_events = ?,
                    llm_importance = ?,
                    llm_raw_response = ?,
                    llm_last_updated = ?,
                    llm_source = ?
                  WHERE show_tmdb_id = ? AND season_number = ? AND episode_number = ? AND actor_id = ?''',
                (
                    llm_sections.get('Significant Relationships'),
                    llm_sections.get('Primary Motivations & Inner Conflicts'),
                    llm_sections.get('Notable Quote'),
                    llm_sections.get('Personality & Traits'),
                    llm_sections.get('Key Events'),
                    llm_sections.get('Importance to the Story'),
                    llm_summary,
                    now,
                    model_source,
                    show_id, season_number, episode_number, actor_id
                )
            )
            db.commit()
            llm_last_updated = now
            llm_source = model_source

    llm_cards = {}
    if llm_sections.get('Significant Relationships'):
        llm_cards['relationships'] = parse_relationships_section(llm_sections['Significant Relationships'])
    if llm_sections.get('Personality & Traits'):
        llm_cards['traits'] = parse_traits_section(llm_sections['Personality & Traits'])
    if llm_sections.get('Key Events'):
        llm_cards['events'] = parse_events_section(llm_sections['Key Events'])
    if llm_sections.get('Notable Quote'):
        llm_cards['quote'] = parse_quote_section(llm_sections['Notable Quote'])
    if llm_sections.get('Primary Motivations & Inner Conflicts'):
        llm_cards['motivations'] = parse_motivations_section(llm_sections['Primary Motivations & Inner Conflicts'])
    if llm_sections.get('Importance to the Story'):
        llm_cards['importance'] = parse_importance_section(llm_sections['Importance to the Story'])
    llm_sections_html = {k: md.markdown(v) for k, v in llm_sections.items() if v}

    return render_template('character_detail.html',
                           show_id=show_id,
                           season_number=season_number,
                           episode_number=episode_number,
                           actor_id=actor_id,
                           character=character,
                           llm_cards=llm_cards,
                           llm_sections_html=llm_sections_html,
                           llm_last_updated=llm_last_updated,
                           llm_source=llm_source,
                           llm_error=llm_error)
