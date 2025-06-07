import os
import requests
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
from werkzeug.security import generate_password_hash

from . import database

PLEX_HEADERS = {
    'X-Plex-Client-Identifier': os.environ.get('PLEX_CLIENT_ID', 'shownotes'),
    'X-Plex-Product': 'ShowNotes',
    'X-Plex-Version': '0.1',
}

bp = Blueprint('main', __name__)


def admin_exists():
    db = database.get_db()
    row = db.execute('SELECT id FROM users WHERE is_admin = 1').fetchone()
    return row is not None


@bp.before_app_request
def check_onboarding():
    if not admin_exists() and request.endpoint not in ('main.onboarding', 'static'):
        return redirect(url_for('main.onboarding'))


@bp.route('/admin/settings', methods=['GET', 'POST'], strict_slashes=False)
def admin_settings():
    db = database.get_db()
    # Get admin user (first admin found)
    user = db.execute('SELECT * FROM users WHERE is_admin=1 LIMIT 1').fetchone()
    # Get settings (first row)
    settings = db.execute('SELECT * FROM settings LIMIT 1').fetchone()
    if request.method == 'POST':
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
            plex_client_id=?, plex_client_secret=?, plex_redirect_uri=?
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
            request.form.get('plex_client_secret'),
            request.form.get('plex_redirect_uri'),
            settings['id'] if settings else 1
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
    site_url = request.url_root.rstrip('/')
    return render_template('admin_settings.html', user=user, settings=merged_settings, site_url=site_url)


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
        # Store the last event in memory for backward compatibility
        global last_plex_event
        last_plex_event = payload
        # Extract fields for DB
        event_type = payload.get('event')
        account = payload.get('Account', {})
        user_id = account.get('id')
        user_name = account.get('title')
        metadata = payload.get('Metadata', {})
        media_type = metadata.get('type')
        show_title = metadata.get('grandparentTitle') if media_type == 'episode' else metadata.get('title')
        episode_title = metadata.get('title') if media_type == 'episode' else None
        season = metadata.get('parentIndex') if media_type == 'episode' else None
        episode = metadata.get('index') if media_type == 'episode' else None
        summary = metadata.get('summary')
        raw_json = pyjson.dumps(payload)
        # Insert into DB
        db = database.get_db()
        db.execute('''INSERT INTO plex_events \
            (event_type, user_id, user_name, media_type, show_title, episode_title, season, episode, summary, raw_json) \
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (event_type, user_id, user_name, media_type, show_title, episode_title, season, episode, summary, raw_json)
        )
        db.commit()

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
            poster_path = os.path.join(os.path.dirname(__file__), 'static', 'posters', f'poster_{clean_name}{ext}')
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
    client_secret = get_setting('plex_client_secret') or os.environ.get('PLEX_CLIENT_SECRET', 'YOUR_PLEX_CLIENT_SECRET')
    redirect_uri = get_setting('plex_redirect_uri') or os.environ.get('PLEX_REDIRECT_URI', 'https://shownotes.chitekmedia.club/callback')
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
        r = requests.get('https://plex.tv/users/account', headers=headers)
        if r.status_code == 200:
            user_info = r.json().get('user', {})
    except Exception:
        pass
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
    print('DEBUG: Plex user_info used for login:', user_info)
    session['plex_user'] = {
        'username': username,
        'id': user_id,
        'auth_token': auth_token,
    }
    flash(f'Logged in as Plex user: {session["plex_user"]["username"]}')
    return redirect(url_for('main.home'))

@bp.route('/logout', endpoint='plex_logout')
def logout():
    session.clear()
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
    user = session.get('plex_user')
    print('DEBUG: user in session:', user)
    db = database.get_db()
    plex_event = None
    poster_url = None

    # Determine user id or username from session
    session_user_id = user.get('id') if user else None
    session_username = user.get('username') if user else None

    # Try to get the most recent event for the logged-in user
    row = None
    if session_user_id:
        row = db.execute('SELECT * FROM plex_events WHERE user_id=? ORDER BY timestamp DESC, id DESC LIMIT 1', (session_user_id,)).fetchone()
    if not row and session_username:
        row = db.execute('SELECT * FROM plex_events WHERE user_name=? ORDER BY timestamp DESC, id DESC LIMIT 1', (session_username,)).fetchone()
    if row:
        import json as pyjson
        try:
            plex_event = pyjson.loads(row['raw_json']) if row['raw_json'] else dict(row)
        except Exception:
            plex_event = dict(row)
    else:
        plex_event = None

    # Try to use local cached poster if available
    if plex_event and plex_event.get('Metadata'):
        import os, re
        meta = plex_event['Metadata']
        poster_url = None
        clean_name = None
        ext = '.jpg'
        if meta.get('type') == 'episode' and meta.get('grandparentTitle'):
            clean_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', meta['grandparentTitle'].lower())
        elif meta.get('type') == 'movie' and meta.get('title'):
            clean_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', meta['title'].lower())
        if clean_name:
            # Check for any allowed extension
            static_dir = os.path.join(os.path.dirname(__file__), 'static', 'posters')
            for candidate_ext in ['.jpg', '.jpeg', '.png', '.webp']:
                candidate_path = os.path.join(static_dir, f'poster_{clean_name}{candidate_ext}')
                if os.path.exists(candidate_path):
                    poster_url = url_for('static', filename=f'posters/poster_{clean_name}{candidate_ext}')
                    break
        # If not cached, fallback to Sonarr/Radarr/remote
        if not poster_url:
            if meta.get('type') == 'episode' and meta.get('grandparentTitle'):
                poster_url = get_sonarr_poster(meta['grandparentTitle'])
            elif meta.get('type') == 'movie' and meta.get('title'):
                poster_url = get_radarr_poster(meta['title'])
            # fallback to Plex poster
            if not poster_url:
                thumb = meta.get('grandparentThumb') or meta.get('thumb')
                if thumb and thumb.startswith('http'):
                    poster_url = thumb
                elif thumb:
                    poster_url = f"https://shownotes.chitekmedia.club{thumb}"
    print('DEBUG: Passing to template:', {'plex_event': plex_event, 'user': user, 'poster_url': poster_url})
    return render_template('home.html', plex_event=plex_event, user=user, poster_url=poster_url)

@bp.route('/plex/debug')
def plex_debug():
    from flask import jsonify
    return jsonify(last_plex_event)

@bp.route('/onboarding', methods=['GET', 'POST'])
def onboarding():
    if request.method == 'POST':
        db = database.get_db()
        username = request.form['username']
        password = request.form['password']
        pw_hash = generate_password_hash(password)
        db.execute(
            'INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)',
            (username, pw_hash),
        )
        db.execute(
            'INSERT INTO settings (radarr_url, radarr_api_key, sonarr_url, sonarr_api_key, bazarr_url, bazarr_api_key, ollama_url, pushover_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (
                request.form.get('radarr_url'),
                request.form.get('radarr_api_key'),
                request.form.get('sonarr_url'),
                request.form.get('sonarr_api_key'),
                request.form.get('bazarr_url'),
                request.form.get('bazarr_api_key'),
                request.form.get('ollama_url'),
                request.form.get('pushover_key'),
            ),
        )
        db.commit()
        return redirect(url_for('main.index'))
    return render_template('onboarding.html')


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
        else:
            return jsonify({'success': False, 'error': 'Unknown service'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@bp.route('/test-pushover', methods=['POST'])
def test_pushover():
    data = request.get_json()
    token = data.get('token')
    user_key = data.get('user_key')
    if not token or not user_key:
        return jsonify({'success': False, 'error': 'Missing token or user key'}), 400

    payload = {
        'token': token,
        'user': user_key,
        'message': 'Test notification from Show Notes Admin Settings'
    }
    try:
        r = requests.post('https://api.pushover.net/1/messages.json', data=payload, timeout=5)
        if r.status_code == 200:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': r.text}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500




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
