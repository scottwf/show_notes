import os
import json
import requests
import sqlite3
import time

from flask import (
    Blueprint, render_template, request, redirect, url_for, session, jsonify,
    flash, current_app, Response, abort
)
from flask_login import login_user, login_required, logout_user
from werkzeug.security import generate_password_hash

from .. import database
from ..utils import get_sonarr_poster, get_radarr_poster

main_bp = Blueprint('main', __name__)

last_plex_event = None

def is_onboarding_complete():
    try:
        db = database.get_db()
        admin_user = db.execute('SELECT id FROM users WHERE is_admin = 1 LIMIT 1').fetchone()
        settings_record = db.execute('SELECT id FROM settings LIMIT 1').fetchone()
        return admin_user is not None and settings_record is not None
    except sqlite3.OperationalError:
        return False

@main_bp.before_app_request
def check_onboarding():
    if request.endpoint and 'static' not in request.endpoint:
        exempt_endpoints = [
            'main.onboarding',
            'main.login',
            'main.callback',
            'main.logout',
            'main.plex_webhook'
        ]
        if not is_onboarding_complete() and request.endpoint not in exempt_endpoints:
            flash('Initial setup required. Please complete the onboarding process.', 'info')
            return redirect(url_for('main.onboarding'))

@main_bp.route('/')
def home():
    db = database.get_db()
    s_username = session.get('username')
    plex_event_from_db = None
    if s_username:
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
        except Exception as e:
            current_app.logger.error(f"Error fetching from plex_activity_log for user {s_username}: {e}", exc_info=True)

    plex_event_for_template = None
    if plex_event_from_db:
        plex_event_for_template = dict(plex_event_from_db)
        media_type = plex_event_for_template.get('media_type')
        tmdb_id = plex_event_for_template.get('tmdb_id') # This is episode tmdb_id for episodes

        if media_type == 'movie' and tmdb_id:
            item_data = db.execute('SELECT poster_url, year, overview FROM radarr_movies WHERE tmdb_id = ?', (tmdb_id,)).fetchone()
            if item_data:
                plex_event_for_template.update(dict(item_data))
        elif media_type == 'episode':
            # First, try to get the show's TMDB ID using grandparent_rating_key -> tvdb_id
            grandparent_rating_key = plex_event_for_template.get('grandparent_rating_key')
            show_tmdb_id_from_sonarr = None
            if grandparent_rating_key:
                try:
                    # Assuming grandparent_rating_key from Plex maps to tvdb_id in sonarr_shows
                    show_info = db.execute(
                        'SELECT tmdb_id FROM sonarr_shows WHERE tvdb_id = ?',
                        (grandparent_rating_key,)
                    ).fetchone()
                    if show_info and show_info['tmdb_id']:
                        show_tmdb_id_from_sonarr = show_info['tmdb_id']
                        plex_event_for_template['show_tmdb_id'] = show_tmdb_id_from_sonarr
                except Exception as e:
                    current_app.logger.error(f"Error fetching show_tmdb_id from sonarr_shows by tvdb_id: {e}")

            # Fallback or primary fetch for episode-specific display (poster, year of show, overview of show)
            # The current tmdb_id is the episode's tmdb_id.
            # If we have show_tmdb_id_from_sonarr, we should use that to fetch show details.
            # Otherwise, the original logic using episode's tmdb_id (if it was ever meant to be show's tmdb_id) might be flawed.
            # Let's assume the original intent for item_data was to get show details.
            # If show_tmdb_id_from_sonarr is found, use it. Otherwise, the original tmdb_id (episode's) won't find a show.

            show_id_to_query = show_tmdb_id_from_sonarr if show_tmdb_id_from_sonarr else tmdb_id
            # However, tmdb_id here is for the EPISODE, not the show. So the original query for sonarr_shows using episode tmdb_id was incorrect.
            # We should ONLY query sonarr_shows if we have a valid show_tmdb_id from the tvdb_id lookup.

            if show_tmdb_id_from_sonarr: # Use the show's actual TMDB ID
                 item_data = db.execute('SELECT poster_url, year, overview FROM sonarr_shows WHERE tmdb_id = ?', (show_tmdb_id_from_sonarr,)).fetchone()
                 if item_data:
                     plex_event_for_template.update(dict(item_data))
            # If show_tmdb_id_from_sonarr is None, we don't have a reliable show TMDB ID to fetch poster/year/overview for the show.
            # The plex_event_for_template will still contain episode title, show title, etc. from plex_activity_log.

    return render_template('home.html',
                           plex_event=plex_event_for_template,
                           username=s_username,
                           is_admin=session.get('is_admin', False))

@main_bp.route('/plex/webhook', methods=['POST'])
def plex_webhook():
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
        flash(f'Welcome back, {user_obj.username}!', 'success')
    else:
        flash('Could not log you in. Please contact an administrator.', 'danger')

    return redirect(url_for('main.home'))

@main_bp.route('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.home'))

@main_bp.route('/onboarding', methods=['GET', 'POST'])
def onboarding():
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
                '''INSERT INTO settings (radarr_url, radarr_api_key, sonarr_url, sonarr_api_key, bazarr_url, bazarr_api_key, ollama_url, pushover_key, pushover_token, plex_client_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    request.form['radarr_url'], request.form['radarr_api_key'],
                    request.form['sonarr_url'], request.form['sonarr_api_key'],
                    request.form['bazarr_url'], request.form['bazarr_api_key'],
                    request.form['ollama_url'], request.form.get('pushover_key'),
                    request.form.get('pushover_token'), request.form['plex_client_id']
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

    results = [dict(row) for row in sonarr_results + radarr_results]
    
    # Sort results by title
    results.sort(key=lambda x: x['title'])
    
    return jsonify(results)

@main_bp.route('/movie/<int:tmdb_id>')
@login_required
def movie_detail(tmdb_id):
    db = database.get_db()
    movie = db.execute('SELECT * FROM radarr_movies WHERE tmdb_id = ?', (tmdb_id,)).fetchone()
    if not movie:
        abort(404)
    return render_template('movie_detail.html', movie=movie)

@main_bp.route('/show/<int:tmdb_id>')
@login_required
def show_detail(tmdb_id):
    db = database.get_db()
    show = db.execute('SELECT * FROM sonarr_shows WHERE tmdb_id = ?', (tmdb_id,)).fetchone()
    if not show:
        abort(404)
    return render_template('show_detail.html', show=show)

@main_bp.route('/image_proxy')
@login_required
def image_proxy():
    url = request.args.get('url')
    if not url:
        abort(400)
    try:
        resp = requests.get(url, stream=True)
        return Response(resp.iter_content(chunk_size=1024), content_type=resp.headers['content-type'])
    except Exception as e:
        current_app.logger.error(f"Image proxy error for url {url}: {e}")
        abort(404)
