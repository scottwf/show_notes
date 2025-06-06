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

@bp.route('/')
def index():
    return render_template('index.html')


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
            resp = requests.get(endpoint, params={'apikey': api_key}, timeout=5)
        elif service == 'bazarr':
            endpoint = f"{url.rstrip('/')}/api/v1/system/status"
            resp = requests.get(endpoint, params={'apiKey': api_key}, timeout=5)
        elif service == 'ollama':
            endpoint = f"{url.rstrip('/')}/api/tags"
            resp = requests.get(endpoint, timeout=5)
        else:
            return jsonify(success=False)
        return jsonify(success=resp.status_code == 200)
    except Exception:
        return jsonify(success=False)


@bp.route('/login')
def login():
    return render_template('login.html')


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
