"""
Admin Blueprint for ShowNotes

This module defines the blueprint for the administrative interface of the ShowNotes
application. It includes routes for all admin-facing pages and functionalities,
such as the dashboard, settings management, task execution, and log viewing.

All routes in this blueprint are prefixed with `/admin` and require the user to be
logged in and have administrative privileges, enforced by the `@admin_required`
decorator.

ORGANIZATION:
This file is organized into logical sections for better maintainability:
- DECORATORS & UTILITIES: Shared decorators and constants
- DASHBOARD & SEARCH: Main dashboard and search functionality  
- SETTINGS MANAGEMENT: Service configuration and connection testing
- TASK EXECUTION: Background task triggers (sync, parsing, etc.)
- LOG MANAGEMENT: Log viewing, streaming, and logbook functionality
- LLM TOOLS: LLM testing and prompt management
- API USAGE: API usage tracking and monitoring

Key Features:
- **Dashboard:** A summary page with key statistics about the application's data.
- **Settings:** A page for configuring connections to external services like
  Sonarr, Radarr, and LLM providers.
- **Tasks:** A UI for manually triggering long-running tasks like library syncs.
- **Log Management:** Tools for viewing and streaming application logs.
- **LLM Tools:** Pages for testing LLM summaries and viewing prompt templates.
- **API Endpoints:** Various API endpoints to support the dynamic functionality
  of the admin interface, such as search and connection testing.
"""
import os
import glob
import time
import secrets
import socket
import requests
from openai import OpenAI
from flask import (
    Blueprint, render_template, request, redirect, url_for, session, jsonify, flash,
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
    convert_utc_to_user_timezone, get_user_timezone
)
from ...parse_subtitles import process_all_subtitles

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# ============================================================================
# DECORATORS & UTILITIES
# ============================================================================

def admin_required(f):
    """
    Decorator to ensure that a route is accessed by an authenticated admin user.

    If the user is not authenticated or is not an admin, it logs a warning,
    flashes an error message, and aborts the request with a 403 Forbidden status.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, 'is_admin', False):
            current_app.logger.warning(f"Admin access denied for user {current_user.username if current_user.is_authenticated else 'Anonymous'} to {request.endpoint}")
            flash('You must be an administrator to access this page.', 'danger')
            abort(403) # Forbidden
        return f(*args, **kwargs)
    return decorated_function

# List of admin panel routes that are searchable via the admin search bar.
# Each entry contains a user-friendly title, a category for grouping,
# and a lambda function to generate the URL dynamically using url_for.
ADMIN_SEARCHABLE_ROUTES = [
    {'title': 'Admin Dashboard', 'category': 'Admin Page', 'url_func': lambda: url_for('admin.dashboard')},
    {'title': 'Service Settings', 'category': 'Admin Page', 'url_func': lambda: url_for('admin.settings')},
    {'title': 'Admin Tasks (Sync)', 'category': 'Admin Page', 'url_func': lambda: url_for('admin.tasks')},
    {'title': 'Logbook', 'category': 'Admin Page', 'url_func': lambda: url_for('admin.logbook_view')},
    {'title': 'Logs', 'category': 'Admin Page', 'url_func': lambda: url_for('admin.logs_view')},


    {'title': 'Issue Reports', 'category': 'Admin Page', 'url_func': lambda: url_for('admin.issue_reports')},
    {'title': 'AI / LLM Settings', 'category': 'Admin Page', 'url_func': lambda: url_for('admin.ai_settings')},
    {'title': 'Recap Pipeline (Subtitle-First)', 'category': 'Admin Page', 'url_func': lambda: url_for('admin.recap_pipeline')},
]


# ---------------------------------------------------------------------------
# Register route sub-modules (order doesn't matter, all share admin_bp)
# ---------------------------------------------------------------------------
from . import dashboard      # noqa: F401, E402
from . import sync_tasks     # noqa: F401, E402
from . import settings       # noqa: F401, E402
from . import logs           # noqa: F401, E402
from . import management     # noqa: F401, E402
from . import llm            # noqa: F401, E402
