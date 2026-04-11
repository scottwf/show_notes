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
import threading
import datetime # Added
from datetime import timezone # Added
import urllib.parse
import logging
import markdown as md

from flask import (
    Blueprint, render_template, request, redirect, url_for, session, jsonify,
    flash, current_app, Response, abort, g
)
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from ... import database

main_bp = Blueprint('main', __name__)

from ._shared import get_current_member, get_user_members, is_onboarding_complete

@main_bp.context_processor
def inject_household():
    """Make current_member, all_members, and unread_count available in every template."""
    if not session.get('user_id'):
        return {}
    try:
        member = get_current_member()
        members = get_user_members(session['user_id'])
        # Lightweight unread count for the nav badge
        db = database.get_db()
        user_id = session['user_id']
        member_id = session.get('member_id')
        if member_id:
            row = db.execute(
                'SELECT COUNT(*) as c FROM user_notifications WHERE user_id=? AND member_id=? AND is_read=0 AND is_dismissed=0',
                (user_id, member_id)
            ).fetchone()
        else:
            row = db.execute(
                'SELECT COUNT(*) as c FROM user_notifications WHERE user_id=? AND is_read=0 AND is_dismissed=0',
                (user_id,)
            ).fetchone()
        unread_count = row['c'] if row else 0
        return {'current_member': member, 'all_members': members, 'nav_unread_count': unread_count}
    except Exception:
        return {}
_homepage_cache = {}
_homepage_cache_lock = threading.Lock()
_IMAGE_ROUTE_ENDPOINTS = {'main.image_proxy', 'main.cast_image_proxy'}
_POSTER_THUMBNAIL_SIZE = (240, 360)
_POSTER_THUMBNAIL_QUALITY = 78


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
    if request.endpoint in _IMAGE_ROUTE_ENDPOINTS:
        return

    if request.endpoint and 'static' not in request.endpoint:
        # Allow access to specific endpoints even if onboarding is not complete
        exempt_endpoints = [
            'main.onboarding', # Onboarding Step 1 (admin account)
            'main.onboarding_services', # Onboarding Step 2 (service config)
            'main.onboarding_test_service', # Onboarding service testing
            'main.login',
            'main.callback',
            'main.logout',
            'main.plex_webhook'
        ]
        if not is_onboarding_complete() and request.endpoint not in exempt_endpoints:
            flash('Initial setup required. Please complete the onboarding process.', 'info')
            return redirect(url_for('main.onboarding'))

@main_bp.before_app_request
def update_session_profile_photo():
    """
    Update session with profile photo URL if it has changed.
    This ensures the session always reflects the current profile photo from the database,
    even when users upload a new photo.

    Performance optimization: Skip for static file requests and use request-level caching.
    """
    # Skip for static file requests to improve performance
    if request.endpoint in _IMAGE_ROUTE_ENDPOINTS:
        return

    if request.endpoint and ('static' in request.endpoint or request.endpoint.startswith('_')):
        return

    # Skip if no user logged in
    if not session.get('user_id'):
        return

    # Use request-level cache (g object) to avoid multiple lookups per request
    if hasattr(g, '_profile_photo_checked'):
        return
    g._profile_photo_checked = True

    try:
        db = database.get_db()
        user_record = db.execute('SELECT profile_photo_url FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        if user_record:
            db_photo_url = user_record['profile_photo_url']
            session_photo_url = session.get('profile_photo_url')
            # Update session if database value is different
            if db_photo_url != session_photo_url:
                session['profile_photo_url'] = db_photo_url
    except Exception:
        pass  # Silently fail to avoid breaking the request



# ---------------------------------------------------------------------------
# Register route sub-modules (all share main_bp)
# ---------------------------------------------------------------------------
from . import auth_routes             # noqa: F401, E402
from . import media_routes            # noqa: F401, E402
from . import webhook_routes          # noqa: F401, E402
from . import profile_routes          # noqa: F401, E402
from . import statistics_routes       # noqa: F401, E402
from . import lists_progress_routes   # noqa: F401, E402
from . import calendar_recommendations_routes  # noqa: F401, E402
from . import image_cache_routes      # noqa: F401, E402
