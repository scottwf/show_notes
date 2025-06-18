import os
import json
import requests
import re
import sqlite3
import time
import datetime # Added
from datetime import timezone # Added

from flask import (
    Blueprint, render_template, request, redirect, url_for, session, jsonify,
    flash, current_app, Response, abort
)
from flask_login import login_user, login_required, logout_user # current_user is not directly used, session is used for username
from werkzeug.security import generate_password_hash

from .. import database
from ..utils import get_sonarr_poster, get_radarr_poster

main_bp = Blueprint('main', __name__)

last_plex_event = None

def is_onboarding_complete():
    """
    Checks if the initial admin user and settings have been created.

    Returns:
        bool: True if onboarding is complete, False otherwise.
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
    Redirects to onboarding page if setup is not complete.

    This function runs before each request. If onboarding is not complete
    (admin user and settings not created), it redirects to the onboarding
    page, unless the current request is for an exempt endpoint (like
    onboarding itself, login, static files).
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
    Enriches a Plex event row with details from local Sonarr/Radarr databases.

    Args:
        plex_event_row (sqlite3.Row): A row from the plex_activity_log table.
        db (sqlite3.Connection): The database connection.

    Returns:
        dict: A dictionary containing enriched item details, including cached image URLs
              and links to detail pages, or None if input is None.
    """
    if not plex_event_row:
        return None

    item_details = dict(plex_event_row)
    media_type = item_details.get('media_type')

    plex_tmdb_id = item_details.get('tmdb_id') # This is episode's TMDB ID or movie's TMDB ID from Plex payload
    grandparent_rating_key = item_details.get('grandparent_rating_key') # This is TVDB ID for shows from Plex payload

    item_details['item_type_for_url'] = None
    item_details['tmdb_id_for_poster'] = None
    item_details['link_tmdb_id'] = None # TMDB ID for the link to movie/show detail page

    if media_type == 'movie':
        if plex_tmdb_id: # This should be the movie's TMDB ID
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
        # Store original episode title before potentially overriding with show title
        item_details['episode_title'] = dict(plex_event_row).get('title') # Corrected: use plex_event_row

        if grandparent_rating_key: # This is TVDB ID
            show_info = db.execute(
                'SELECT tmdb_id, title, poster_url, year, overview FROM sonarr_shows WHERE tvdb_id = ?', (grandparent_rating_key,)
            ).fetchone()
            if show_info:
                # Update item_details with show's info, but preserve episode-specific fields like original title
                # Fields like 'year', 'overview', 'poster_url' will be from the show.
                # 'title' from show_info is the show's title.
                item_details.update(dict(show_info))
                item_details['tmdb_id_for_poster'] = show_info['tmdb_id']
                item_details['link_tmdb_id'] = show_info['tmdb_id']
                # item_details['title'] is now show title, original episode title is in item_details['episode_title']
        # If grandparent_rating_key is missing, we might not be able to reliably get show's TMDB ID for poster/link

    # Fallback for poster_url if not found via Radarr/Sonarr lookup but was in Plex event (less likely to be what we want)
    # if item_details.get('poster_url') is None and dict(plex_event_row).get('poster_url'):
    #     item_details['poster_url'] = dict(plex_event_row).get('poster_url') # This is often a low-res Plex thumb

    # Ensure some title exists, default to original from plex_event_row if no enrichment happened
    item_details.setdefault('title', dict(plex_event_row).get('title'))
    item_details.setdefault('year', None)

    if item_details.get('season_episode') and item_details.get('link_tmdb_id'):
        match = re.match(r'S(\d+)E(\d+)', item_details['season_episode'])
        if match:
            item_details['season_number'] = int(match.group(1))
            item_details['episode_number'] = int(match.group(2))
            item_details['episode_detail_url'] = url_for('main.episode_detail', tmdb_id=item_details['link_tmdb_id'], season_number=item_details['season_number'], episode_number=item_details['episode_number'])

    # Generate cached image URLs
    if item_details.get('tmdb_id_for_poster'):
        item_details['cached_poster_url'] = url_for('static', filename=f"poster/{item_details['tmdb_id_for_poster']}.jpg")
        # For Plex events, fanart might be less common or derived from the same ID.
        # Assuming tmdb_id_for_poster can also be used for a potential background.
        item_details['cached_fanart_url'] = url_for('static', filename=f"background/{item_details['tmdb_id_for_poster']}.jpg")
    else:
        item_details['cached_poster_url'] = None
        item_details['cached_fanart_url'] = None
        # Fallback to any poster_url that might have been set directly from Sonarr/Radarr if tmdb_id_for_poster was missing
        # but this is less ideal as we want to use cached images.
        # if item_details.get('poster_url'):
        #     item_details['cached_poster_url'] = item_details['poster_url']


    return item_details

@main_bp.route('/')
def home():
    """Render the homepage with recent Plex activity for the user."""
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

@main_bp.route('/plex/webhook', methods=['POST'])
def plex_webhook():
    """
    Handles incoming webhook events from Plex.

    Parses Plex webhook payloads, logs relevant media activity (play, pause,
    resume, stop, scrobble) to the `plex_activity_log` table.
    This data is used to display user activity on the homepage and show details.
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
            guids = metadata.get('Guid')
            if isinstance(guids, list):
                for guid_item in guids:
                    guid_str = guid_item.get('id', '')
                    if guid_str.startswith('tmdb://'):
                        tmdb_id = int(guid_str.split('//')[1])
                        break
            
            season_episode_str = None
            if metadata.get('type') == 'episode':
                season_num = metadata.get('parentIndex')
                episode_num = metadata.get('index')
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
        
        return '', 200
    except Exception as e:
        current_app.logger.error(f"Error processing Plex webhook: {e}", exc_info=True)
        return 'error', 400

@main_bp.route('/login')
def login():
    """
    Initiates the Plex OAuth login process.

    Redirects the user to Plex.tv to authenticate and authorize the application.
    It first obtains a PIN from Plex, stores its ID in the session, and then
    constructs the authentication URL.
    """
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
    Handles the callback from Plex after user authentication.

    Polls Plex using the PIN ID to get an authentication token. If successful,
    retrieves user information from Plex, finds the corresponding user in the
    local database, and logs them in.
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
    """Logs out the current user and clears the session."""
    logout_user()
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.home'))

@main_bp.route('/onboarding', methods=['GET', 'POST'])
def onboarding():
    """
    Handles the initial application setup (admin user and basic settings).

    If onboarding is already complete, redirects to the homepage.
    On GET, displays the onboarding form.
    On POST, creates the admin user and saves initial settings to the database.
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
    """Search for shows and movies by title.

    Returns a JSON list of matching items for autocomplete.
    """
    query = request.args.get('q', '').strip()
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
            item['poster_url'] = url_for('static', filename=f"poster/{item['tmdb_id']}.jpg")
            item['fanart_url'] = url_for('static', filename=f"background/{item['tmdb_id']}.jpg")
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

    Args:
        tmdb_id (int): The TMDB ID of the movie.

    Returns:
        flask.Response: Rendered movie detail template with movie information,
                        including cached image URLs, or 404 if not found.
    """
    db = database.get_db()
    movie = db.execute('SELECT * FROM radarr_movies WHERE tmdb_id = ?', (tmdb_id,)).fetchone()
    if not movie:
        abort(404)
    movie_dict = dict(movie)
    if movie_dict.get('tmdb_id'):
        movie_dict['cached_poster_url'] = url_for('static', filename=f"poster/{movie_dict['tmdb_id']}.jpg")
        movie_dict['cached_fanart_url'] = url_for('static', filename=f"background/{movie_dict['tmdb_id']}.jpg")
    else:
        movie_dict['cached_poster_url'] = None
        movie_dict['cached_fanart_url'] = None
    return render_template('movie_detail.html', movie=movie_dict)

@main_bp.route('/show/<int:tmdb_id>')
@login_required
def show_detail(tmdb_id):
    """Display a show's seasons and episodes.

    Args:
        tmdb_id (int): TMDB identifier for the show.

    Returns:
        flask.Response: Rendered show detail template with show information,
                        season/episode lists, cached image URLs, next aired episode,
                        and featured (recently/currently watched) episode details.
    """
    db = database.get_db()
    show_dict = None

    show_row = db.execute('SELECT * FROM sonarr_shows WHERE tmdb_id = ?', (tmdb_id,)).fetchone()
    if not show_row:
        current_app.logger.warning(f"Show with TMDB ID {tmdb_id} not found in sonarr_shows.")
        abort(404)
    show_dict = dict(show_row)
    if show_dict.get('tmdb_id'):
        show_dict['cached_poster_url'] = url_for('static', filename=f"poster/{show_dict['tmdb_id']}.jpg")
        show_dict['cached_fanart_url'] = url_for('static', filename=f"background/{show_dict['tmdb_id']}.jpg")
    else:
        show_dict['cached_poster_url'] = None
        show_dict['cached_fanart_url'] = None
    show_db_id = show_dict['id']

    seasons_rows = db.execute(
        'SELECT * FROM sonarr_seasons WHERE show_id = ? ORDER BY season_number', (show_db_id,)
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
            'SELECT * FROM sonarr_episodes WHERE season_id = ? ORDER BY episode_number', (season_db_id,)
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

    return render_template('show_detail.html',
                           show=show_dict,
                           seasons_with_episodes=seasons_with_episodes,
                           next_aired_episode_info=next_aired_episode_info,
                           # currently_watched_episode_info=currently_watched_episode_info, # Replaced by featured_episode
                           # last_watched_episode_info=last_watched_episode_info, # Replaced by featured_episode
                           featured_episode=prepare_featured_episode(currently_watched_episode_info, last_watched_episode_info, show_dict)
                           )

def prepare_featured_episode(currently_watched, last_watched, show_info):
    """
    Prepares a dictionary for the "featured episode" (currently or recently watched).

    This function consolidates information from either the currently watched or
    last watched episode data, formats it, and includes necessary details for
    display on the show detail page.

    Args:
        currently_watched (dict, None): Data for an episode being actively watched.
        last_watched (dict, None): Data for the last scrobbled/stopped episode.
        show_info (dict): Dictionary containing details of the parent show,
                          including 'tmdb_id' and 'cached_poster_url'.

    Returns:
        dict, None: A dictionary with formatted episode details for the template,
                    or None if no relevant watch activity is found.
    """
    featured_episode_data = None
    source_info = None
    is_currently_watching = False

    if currently_watched:
        source_info = currently_watched
        is_currently_watching = True
    elif last_watched:
        source_info = last_watched

    if source_info:
        season_episode_str = source_info.get('season_episode')
        season_number = None
        episode_number = None
        match = re.match(r'S(\d+)E(\d+)', season_episode_str) if season_episode_str else None
        if match:
            season_number = int(match.group(1))
            episode_number = int(match.group(2))

        if season_number is not None and episode_number is not None:
            episode_detail_url = url_for('main.episode_detail',
                                         tmdb_id=show_info['tmdb_id'],
                                         season_number=season_number,
                                         episode_number=episode_number)

            # Format timestamp
            raw_timestamp = source_info.get('event_timestamp')
            formatted_timestamp = "Unknown"
            if raw_timestamp:
                try:
                    if isinstance(raw_timestamp, str):
                        # Attempt to parse from ISO format, common from DB
                        dt_obj = datetime.datetime.fromisoformat(raw_timestamp.replace('Z', '+00:00'))
                    elif isinstance(raw_timestamp, (int, float)): # Handle Unix timestamps
                        dt_obj = datetime.datetime.fromtimestamp(raw_timestamp, tz=timezone.utc)
                    else: # Assuming it's already a datetime object
                        dt_obj = raw_timestamp
                    formatted_timestamp = dt_obj.strftime("%b %d, %Y %I:%M %p")
                except (ValueError, TypeError) as e:
                    current_app.logger.warning(f"Could not parse timestamp '{raw_timestamp}': {e}")
                    formatted_timestamp = str(raw_timestamp) # Fallback

            featured_episode_data = {
                'title': source_info.get('title'),
                'season_episode_str': season_episode_str,
                'season_number': season_number,
                'episode_number': episode_number,
                'poster_url': show_info.get('cached_poster_url'), # Use show's poster
                'event_timestamp': raw_timestamp,
                'formatted_timestamp': formatted_timestamp,
                'progress_percent': source_info.get('progress_percent') if is_currently_watching else None,
                'episode_detail_url': episode_detail_url,
                'is_currently_watching': is_currently_watching
            }
    return featured_episode_data

@main_bp.route('/show/<int:tmdb_id>/season/<int:season_number>/episode/<int:episode_number>')
@login_required
def episode_detail(tmdb_id, season_number, episode_number):
    """Render the detail page for a single episode.

    Args:
        tmdb_id (int): TMDB ID of the parent show.
        season_number (int): Season number of the episode.
        episode_number (int): Episode number within the season.

    Returns:
        flask.Response: Rendered episode detail template with show and episode
                        information, including cached image URLs, formatted dates,
                        and availability status.
    """
    db = database.get_db()
    show_row = db.execute('SELECT id, title, tmdb_id, poster_url, fanart_url FROM sonarr_shows WHERE tmdb_id = ?', (tmdb_id,)).fetchone()
    if not show_row:
        abort(404)
    show_dict = dict(show_row)
    # Use consistent names for cached URLs as expected by the new template.
    if show_dict.get('tmdb_id'):
        show_dict['cached_poster_url'] = url_for('static', filename=f"poster/{show_dict['tmdb_id']}.jpg")
        show_dict['cached_fanart_url'] = url_for('static', filename=f"background/{show_dict['tmdb_id']}.jpg") # Optional for episode page bg
    else:
        show_dict['cached_poster_url'] = None
        show_dict['cached_fanart_url'] = None

    show_id = show_dict['id']
    season_row = db.execute('SELECT id FROM sonarr_seasons WHERE show_id=? AND season_number=?', (show_id, season_number)).fetchone()
    if not season_row:
        abort(404)

    # Fetch all columns for the episode
    episode_row = db.execute('SELECT * FROM sonarr_episodes WHERE season_id=? AND episode_number=?', (season_row['id'], episode_number)).fetchone()
    if not episode_row:
        abort(404)

    episode_dict = dict(episode_row)

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
                           season_number=season_number)

@main_bp.route('/image_proxy')
@login_required
def image_proxy():
    """Proxy an external image URL through the application."""
    url = request.args.get('url')
    if not url:
        abort(400)
    try:
        resp = requests.get(url, stream=True)
        return Response(resp.iter_content(chunk_size=1024), content_type=resp.headers['content-type'])
    except Exception as e:
        current_app.logger.error(f"Image proxy error for url {url}: {e}")
        abort(404)
