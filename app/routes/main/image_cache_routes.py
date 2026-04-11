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
    variant = request.args.get('variant', 'full')

    # Validate type
    if type not in ['poster', 'background']:
        abort(404)
    if variant not in ['full', 'thumb']:
        abort(404)

    # Define cache path
    cache_folder = os.path.join(current_app.static_folder, type)
    if variant == 'thumb':
        cache_folder = os.path.join(cache_folder, 'thumbs')
    # Sanitize ID to prevent directory traversal
    safe_filename = f"{str(id)}.jpg"
    cached_image_path = os.path.join(cache_folder, safe_filename)

    # Create directory if it doesn't exist
    os.makedirs(cache_folder, exist_ok=True)

    # 1. Check if the requested image variant is already cached
    if os.path.exists(cached_image_path):
        static_path = f'{type}/{safe_filename}' if variant == 'full' else f'{type}/thumbs/{safe_filename}'
        return current_app.send_static_file(static_path)

    full_image_path = _get_cached_image_path(type, id, variant='full')
    if variant == 'thumb' and os.path.exists(full_image_path):
        try:
            from PIL import Image

            with Image.open(full_image_path) as img:
                img = img.convert('RGB')
                img.thumbnail(_POSTER_THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
                img.save(cached_image_path, format='JPEG', quality=_POSTER_THUMBNAIL_QUALITY, optimize=True)
            return current_app.send_static_file(f'{type}/thumbs/{safe_filename}')
        except Exception as e:
            current_app.logger.warning(f"Failed to generate cached thumbnail for {type}/{id}: {e}")

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

        # 4. Save the full image to the cache
        target_full_path = full_image_path if type == 'poster' else cached_image_path
        with open(target_full_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        if type == 'poster':
            try:
                from PIL import Image

                thumb_dir = os.path.dirname(_get_cached_image_path(type, id, variant='thumb'))
                os.makedirs(thumb_dir, exist_ok=True)
                thumb_path = _get_cached_image_path(type, id, variant='thumb')
                with Image.open(target_full_path) as img:
                    img = img.convert('RGB')
                    img.thumbnail(_POSTER_THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
                    img.save(thumb_path, format='JPEG', quality=_POSTER_THUMBNAIL_QUALITY, optimize=True)
            except Exception as e:
                current_app.logger.warning(f"Failed to generate thumbnail for poster/{id}: {e}")

        current_app.logger.info(f"Cached image: {target_full_path}")

        # 5. Serve the newly cached image variant
        if variant == 'thumb' and type == 'poster':
            thumb_path = _get_cached_image_path(type, id, variant='thumb')
            if os.path.exists(thumb_path):
                return current_app.send_static_file(f'{type}/thumbs/{safe_filename}')
        return current_app.send_static_file(f'{type}/{safe_filename}')

    except (requests.RequestException, ValueError, IOError) as e:
        current_app.logger.error(f"Failed to fetch or cache image for {type}/{id} from {external_url}. Error: {e}")
        # If fetching fails, serve the placeholder
        placeholder_path = f'logos/placeholder_{type}.png' if os.path.exists(os.path.join(current_app.static_folder, f'logos/placeholder_{type}.png')) else 'logos/placeholder_poster.png'
        return current_app.send_static_file(placeholder_path)

@main_bp.route('/image_proxy/cast/<int:person_id>')
@login_required
def cast_image_proxy(person_id):
    """Proxy and cache cast member photos from TVMaze"""
    cache_folder = os.path.join(current_app.static_folder, 'cast')
    safe_filename = f"{str(person_id)}.jpg"
    cached_image_path = os.path.join(cache_folder, safe_filename)
    os.makedirs(cache_folder, exist_ok=True)

    if os.path.exists(cached_image_path):
        return current_app.send_static_file(f'cast/{safe_filename}')

    db = database.get_db()
    cast_record = db.execute("""
        SELECT person_image_url FROM show_cast
        WHERE person_id = ? LIMIT 1
    """, (person_id,)).fetchone()

    if not cast_record or not cast_record['person_image_url']:
        return current_app.send_static_file('logos/placeholder_poster.png')

    try:
        with requests.Session() as s:
            resp = s.get(cast_record['person_image_url'], stream=True, timeout=10)
            resp.raise_for_status()
        with open(cached_image_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return current_app.send_static_file(f'cast/{safe_filename}')
    except Exception as e:
        current_app.logger.error(f"Failed to fetch cast photo {person_id}: {e}")
        return current_app.send_static_file('logos/placeholder_poster.png')

