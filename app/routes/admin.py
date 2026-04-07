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

from .. import database
from ..database import get_db, close_db, get_setting, set_setting, update_sync_status
from ..utils import (
    sync_sonarr_library, sync_radarr_library,
    test_sonarr_connection, test_radarr_connection, test_bazarr_connection, test_ollama_connection,
    test_sonarr_connection_with_params, test_radarr_connection_with_params,
    test_bazarr_connection_with_params, test_ollama_connection_with_params,
    test_pushover_notification_with_params,
    sync_tautulli_watch_history,
    test_tautulli_connection, test_tautulli_connection_with_params,
    test_jellyseer_connection, test_jellyseer_connection_with_params,
    test_thetvdb_connection, test_thetvdb_connection_with_params,
    get_ollama_models,
    convert_utc_to_user_timezone, get_user_timezone
)
from ..parse_subtitles import process_all_subtitles

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
    {'title': 'View Logs', 'category': 'Admin Page', 'url_func': lambda: url_for('admin.logs_view')},


    {'title': 'Issue Reports', 'category': 'Admin Page', 'url_func': lambda: url_for('admin.issue_reports')},
    {'title': 'AI / LLM Settings', 'category': 'Admin Page', 'url_func': lambda: url_for('admin.ai_settings')},
    {'title': 'AI Summaries & LLM Usage', 'category': 'Admin Page', 'url_func': lambda: url_for('admin.ai_summaries')},
    {'title': 'Recap Pipeline (Subtitle-First)', 'category': 'Admin Page', 'url_func': lambda: url_for('admin.recap_pipeline')},
]

@admin_bp.route('/search', methods=['GET'])
@login_required
@admin_required
def admin_search():
    """
    Provides search functionality for the admin panel.

    Searches across Sonarr shows, Radarr movies, and predefined admin routes
    based on the query parameter 'q'.

    Returns:
        flask.Response: A JSON list of search results, where each result
                        contains 'title', 'category', 'url', and optionally 'year'.
    """
    query = request.args.get('q', '').strip().lower()
    results = []
    if not query: # Return empty list if query is blank
        return jsonify([])

    db = get_db()

    # Search Shows from sonarr_shows table
    show_rows = db.execute(
        "SELECT title, tmdb_id, year FROM sonarr_shows WHERE lower(title) LIKE ?", ('%' + query + '%',)
    ).fetchall()
    for row in show_rows:
        results.append({
            'title': row['title'],
            'category': 'Show', # Consistent category naming
            'year': row['year'],
            'url': url_for('main.show_detail', tmdb_id=row['tmdb_id'])
        })

    # Search Movies
    movie_rows = db.execute(
        "SELECT title, tmdb_id, year FROM radarr_movies WHERE lower(title) LIKE ?", ('%' + query + '%',)
    ).fetchall()
    for row in movie_rows:
        results.append({
            'title': row['title'],
            'category': 'Movie', # Consistent category naming
            'year': row['year'],
            'url': url_for('main.movie_detail', tmdb_id=row['tmdb_id'])
        })

    # Search Admin Routes
    for route_info in ADMIN_SEARCHABLE_ROUTES:
        if query in route_info['title'].lower():
            try:
                url = route_info['url_func']() # Call the lambda to get URL
                results.append({
                    'title': route_info['title'],
                    'category': route_info['category'],
                    'url': url
                })
            except Exception as e:
                current_app.logger.error(f"Error generating URL for admin route {route_info['title']}: {e}")

    # Sort results for consistent ordering: by category first, then by title.
    results.sort(key=lambda x: (x['category'], x['title']))

    return jsonify(results)

# ============================================================================
# DASHBOARD & SEARCH
# ============================================================================

@admin_bp.route('/dashboard', methods=['GET'])
@login_required
@admin_required
def dashboard():
    """
    Renders the admin dashboard page with comprehensive application statistics.

    This page provides a high-level overview of the application's state by
    displaying key statistics organized into three main sections:
    - Plex Activity: Content consumption and user engagement metrics
    - Media Library: Sonarr/Radarr library statistics and sync status
    - API Usage: LLM service usage and cost tracking

    Returns:
        A rendered HTML template for the admin dashboard with all metrics.
    """
    db = database.get_db()
    import datetime

    # ============================================================================
    # CONSOLIDATED QUERIES - Reduce 30+ queries to ~5 queries
    # ============================================================================

    # Query 1: Media library counts (combines 7 individual queries into 1)
    library_stats = db.execute("""
        SELECT
            (SELECT COUNT(*) FROM radarr_movies) as movie_count,
            (SELECT COUNT(*) FROM sonarr_shows) as show_count,
            (SELECT COUNT(*) FROM users) as user_count,
            (SELECT COUNT(*) FROM sonarr_episodes WHERE has_file = 1) as episodes_with_files,
            (SELECT COUNT(*) FROM radarr_movies WHERE has_file = 1) as movies_with_files,
            (SELECT COUNT(*) FROM radarr_movies WHERE last_synced_at >= DATETIME('now', '-7 days')) as radarr_week_count,
            (SELECT COUNT(*) FROM sonarr_shows WHERE last_synced_at >= DATETIME('now', '-7 days')) as sonarr_week_count
    """).fetchone()

    movie_count = library_stats['movie_count'] or 0
    show_count = library_stats['show_count'] or 0
    user_count = library_stats['user_count'] or 0
    episodes_with_files = library_stats['episodes_with_files'] or 0
    movies_with_files = library_stats['movies_with_files'] or 0
    radarr_week_count = library_stats['radarr_week_count'] or 0
    sonarr_week_count = library_stats['sonarr_week_count'] or 0

    # Query 2: Plex activity metrics (combines 10 individual queries into 1)
    plex_stats = db.execute("""
        SELECT
            (SELECT COUNT(DISTINCT title) FROM plex_activity_log WHERE media_type = 'movie' AND event_type IN ('media.play', 'media.scrobble', 'watched')) as unique_movies_played,
            (SELECT COUNT(DISTINCT title) FROM plex_activity_log WHERE media_type = 'episode' AND event_type IN ('media.play', 'media.scrobble', 'watched')) as unique_episodes_played,
            (SELECT COUNT(DISTINCT show_title) FROM plex_activity_log WHERE show_title IS NOT NULL) as unique_shows_watched,
            (SELECT COUNT(*) FROM plex_activity_log WHERE event_timestamp >= DATETIME('now', '-7 days')) as plex_events_week,
            (SELECT COUNT(*) FROM plex_activity_log WHERE event_type IN ('media.play', 'watched') AND event_timestamp >= DATETIME('now', '-7 days')) as recent_plays,
            (SELECT COUNT(*) FROM plex_activity_log WHERE event_type = 'media.scrobble' AND event_timestamp >= DATETIME('now', '-7 days')) as recent_scrobbles,
            (SELECT COUNT(DISTINCT plex_username) FROM plex_activity_log WHERE plex_username IS NOT NULL) as unique_plex_users,
            (SELECT COUNT(DISTINCT plex_username) FROM plex_activity_log WHERE plex_username IS NOT NULL AND event_timestamp >= DATETIME('now', '-1 day')) as plex_users_today,
            (SELECT COUNT(DISTINCT plex_username) FROM plex_activity_log WHERE plex_username IS NOT NULL AND event_timestamp >= DATETIME('now', '-7 days')) as plex_users_week,
            (SELECT COUNT(DISTINCT plex_username) FROM plex_activity_log WHERE plex_username IS NOT NULL AND event_timestamp >= DATETIME('now', '-30 days')) as plex_users_month
    """).fetchone()

    unique_movies_played = plex_stats['unique_movies_played'] or 0
    unique_episodes_played = plex_stats['unique_episodes_played'] or 0
    unique_shows_watched = plex_stats['unique_shows_watched'] or 0
    plex_events_week = plex_stats['plex_events_week'] or 0
    recent_plays = plex_stats['recent_plays'] or 0
    recent_scrobbles = plex_stats['recent_scrobbles'] or 0
    unique_plex_users = plex_stats['unique_plex_users'] or 0
    plex_users_today = plex_stats['plex_users_today'] or 0
    plex_users_week = plex_stats['plex_users_week'] or 0
    plex_users_month = plex_stats['plex_users_month'] or 0

    # Query 3: User login activity (combines 3 queries into 1)
    user_stats = db.execute("""
        SELECT
            (SELECT COUNT(DISTINCT username) FROM users WHERE last_login_at >= DATETIME('now', '-1 day')) as shownotes_users_today,
            (SELECT COUNT(DISTINCT username) FROM users WHERE last_login_at >= DATETIME('now', '-7 days')) as shownotes_users_week,
            (SELECT COUNT(DISTINCT username) FROM users WHERE last_login_at >= DATETIME('now', '-30 days')) as shownotes_users_month
    """).fetchone()

    shownotes_users_today = user_stats['shownotes_users_today'] or 0
    shownotes_users_week = user_stats['shownotes_users_week'] or 0
    shownotes_users_month = user_stats['shownotes_users_month'] or 0

    # Query 4: API usage metrics (combines 6 queries into 1)
    api_stats = db.execute("""
        SELECT
            (SELECT COUNT(*) FROM api_usage) as total_api_calls,
            (SELECT SUM(cost_usd) FROM api_usage) as total_api_cost,
            (SELECT SUM(cost_usd) FROM api_usage WHERE provider='openai' AND timestamp >= DATETIME('now', '-7 days')) as openai_cost_week,
            (SELECT COUNT(*) FROM api_usage WHERE provider='openai' AND timestamp >= DATETIME('now', '-7 days')) as openai_call_count_week,
            (SELECT AVG(processing_time_ms) FROM api_usage WHERE provider='ollama' AND timestamp >= DATETIME('now', '-7 days')) as ollama_avg_ms,
            (SELECT COUNT(*) FROM api_usage WHERE provider='ollama' AND timestamp >= DATETIME('now', '-7 days')) as ollama_call_count_week
    """).fetchone()

    total_api_calls = api_stats['total_api_calls'] or 0
    total_api_cost = api_stats['total_api_cost'] or 0
    openai_cost_week = api_stats['openai_cost_week'] or 0
    openai_call_count_week = api_stats['openai_call_count_week'] or 0
    ollama_avg_ms = api_stats['ollama_avg_ms'] or 0
    ollama_call_count_week = api_stats['ollama_call_count_week'] or 0

    # ============================================================================
    # WEBHOOK ACTIVITY METRICS (kept as separate queries - different tables)
    # ============================================================================

    # Get last webhook activity timestamps
    sonarr_last_webhook = db.execute(
        "SELECT received_at, event_type, payload_summary FROM webhook_activity WHERE service_name = 'sonarr' ORDER BY received_at DESC LIMIT 1"
    ).fetchone()

    radarr_last_webhook = db.execute(
        "SELECT received_at, event_type, payload_summary FROM webhook_activity WHERE service_name = 'radarr' ORDER BY received_at DESC LIMIT 1"
    ).fetchone()

    # Convert string timestamps to datetime objects for template formatting
    if sonarr_last_webhook and sonarr_last_webhook['received_at']:
        try:
            sonarr_last_webhook = dict(sonarr_last_webhook)
            sonarr_last_webhook['received_at'] = datetime.datetime.strptime(
                sonarr_last_webhook['received_at'], '%Y-%m-%d %H:%M:%S'
            )
        except (ValueError, TypeError):
            sonarr_last_webhook['received_at'] = None

    if radarr_last_webhook and radarr_last_webhook['received_at']:
        try:
            radarr_last_webhook = dict(radarr_last_webhook)
            radarr_last_webhook['received_at'] = datetime.datetime.strptime(
                radarr_last_webhook['received_at'], '%Y-%m-%d %H:%M:%S'
            )
        except (ValueError, TypeError):
            radarr_last_webhook['received_at'] = None

    return render_template(
        'admin_dashboard.html',
        # Media Library metrics
        movie_count=movie_count,
        show_count=show_count,
        user_count=user_count,
        episodes_with_files=episodes_with_files,
        movies_with_files=movies_with_files,
        radarr_week_count=radarr_week_count,
        sonarr_week_count=sonarr_week_count,
        
        # Plex Activity metrics
        unique_movies_played=unique_movies_played,
        unique_episodes_played=unique_episodes_played,
        unique_shows_watched=unique_shows_watched,
        plex_events_week=plex_events_week,
        recent_plays=recent_plays,
        recent_scrobbles=recent_scrobbles,
        
        # User Activity metrics
        unique_plex_users=unique_plex_users,
        plex_users_today=plex_users_today,
        plex_users_week=plex_users_week,
        plex_users_month=plex_users_month,
        shownotes_users_today=shownotes_users_today,
        shownotes_users_week=shownotes_users_week,
        shownotes_users_month=shownotes_users_month,
        
        # API Usage metrics
        total_api_calls=total_api_calls,
        total_api_cost=total_api_cost,
        openai_cost_week=openai_cost_week,
        openai_call_count_week=openai_call_count_week,
        ollama_avg_ms=ollama_avg_ms,
        ollama_call_count_week=ollama_call_count_week,
        
        # Webhook Activity metrics
        sonarr_last_webhook=sonarr_last_webhook,
        radarr_last_webhook=radarr_last_webhook,
    )

# ============================================================================
# TASK EXECUTION
# ============================================================================

@admin_bp.route('/tasks')
@login_required
@admin_required
def tasks():
    """
    Renders the admin tasks page.

    This page provides a UI for administrators to manually trigger various
    background tasks, such as synchronizing the Sonarr and Radarr libraries or
    parsing subtitles.

    Returns:
        A rendered HTML template for the admin tasks page.
    """
    return render_template('admin_tasks.html', title='Admin Tasks')

# ============================================================================
# AI SUMMARIES & LLM USAGE
# ============================================================================

@admin_bp.route('/ai-summaries')
@login_required
@admin_required
def ai_summaries():
    """Renders the AI Summaries & LLM Usage admin page."""
    db = get_db()

    def safe_value(query, params=None):
        try:
            result = db.execute(query, params or ()).fetchone()
            return result[0] if result and result[0] is not None else 0
        except Exception:
            return 0

    # --- Usage stats ---
    total_calls = safe_value('SELECT COUNT(*) FROM api_usage')
    total_tokens = safe_value('SELECT SUM(total_tokens) FROM api_usage')
    total_cost = safe_value('SELECT SUM(cost_usd) FROM api_usage')
    avg_processing_time = safe_value('SELECT AVG(processing_time_ms) FROM api_usage WHERE processing_time_ms IS NOT NULL')

    # Last 7 days
    calls_7d = safe_value("SELECT COUNT(*) FROM api_usage WHERE timestamp >= DATETIME('now', '-7 days')")
    tokens_7d = safe_value("SELECT SUM(total_tokens) FROM api_usage WHERE timestamp >= DATETIME('now', '-7 days')")
    cost_7d = safe_value("SELECT SUM(cost_usd) FROM api_usage WHERE timestamp >= DATETIME('now', '-7 days')")

    # Last 30 days
    calls_30d = safe_value("SELECT COUNT(*) FROM api_usage WHERE timestamp >= DATETIME('now', '-30 days')")
    tokens_30d = safe_value("SELECT SUM(total_tokens) FROM api_usage WHERE timestamp >= DATETIME('now', '-30 days')")
    cost_30d = safe_value("SELECT SUM(cost_usd) FROM api_usage WHERE timestamp >= DATETIME('now', '-30 days')")

    # Per-provider breakdown
    provider_stats = db.execute("""
        SELECT provider,
               COUNT(*) as calls,
               SUM(total_tokens) as tokens,
               SUM(cost_usd) as cost,
               AVG(processing_time_ms) as avg_time
        FROM api_usage
        GROUP BY provider
        ORDER BY calls DESC
    """).fetchall()

    # --- Summary queue status ---
    try:
        from ..summary_services import get_summary_queue_status
        queue_status = get_summary_queue_status()
    except Exception:
        queue_status = {
            'pending_count': 0, 'completed_count': 0, 'failed_count': 0,
            'generating_count': 0, 'last_generated_at': None,
            'current_provider': '', 'current_model': '',
        }

    # --- All summaries list ---
    season_summaries = db.execute("""
        SELECT ss.id, ss.tmdb_id, ss.show_title, ss.season_number, ss.status,
               ss.llm_provider, ss.llm_model, ss.summary_text, ss.error_message,
               ss.created_at, ss.updated_at
        FROM season_summaries ss
        ORDER BY ss.updated_at DESC
    """).fetchall()

    show_summaries = db.execute("""
        SELECT sh.id, sh.tmdb_id, sh.show_title, sh.status,
               sh.llm_provider, sh.llm_model, sh.summary_text, sh.error_message,
               sh.created_at, sh.updated_at
        FROM show_summaries sh
        ORDER BY sh.updated_at DESC
    """).fetchall()

    return render_template('admin_ai_summaries.html',
        title='AI Summaries & LLM Usage',
        total_calls=total_calls,
        total_tokens=total_tokens,
        total_cost=total_cost,
        avg_processing_time=avg_processing_time,
        calls_7d=calls_7d, tokens_7d=tokens_7d, cost_7d=cost_7d,
        calls_30d=calls_30d, tokens_30d=tokens_30d, cost_30d=cost_30d,
        provider_stats=provider_stats,
        queue_status=queue_status,
        season_summaries=season_summaries,
        show_summaries=show_summaries,
    )

# ============================================================================
# LOG MANAGEMENT
# ============================================================================

@admin_bp.route('/logs', methods=['GET'])
@login_required
@admin_required
def logs_view():
    """
    Displays the log viewer page.

    Allows admins to view application logs, select log files, and stream live logs.
    """
    return render_template('admin_logs.html', title='View Logs')

@admin_bp.route('/watch-history')
@login_required
@admin_required
def watch_history_view():
    """
    Renders the watch history page.

    The watch history provides a view of Plex watch activity with filtering
    by user, show, media type, and date range. The data for this page is
    fetched dynamically via the `/watch-history/data` endpoint.

    Returns:
        A rendered HTML template for the watch history.
    """
    return render_template('admin_watch_history.html')

@admin_bp.route('/watch-history/users')
@login_required
@admin_required
def watch_history_users():
    """Get list of unique Plex usernames for filter dropdown."""
    db = database.get_db()
    users = db.execute('''
        SELECT DISTINCT plex_username
        FROM plex_activity_log
        WHERE plex_username IS NOT NULL
        ORDER BY LOWER(plex_username) COLLATE NOCASE
    ''').fetchall()
    return jsonify({'users': [u['plex_username'] for u in users]})

@admin_bp.route('/watch-history/data')
@login_required
@admin_required
def watch_history_data():
    """
    Provides data for the watch history page.

    Fetches Plex activity logs based on query parameters for user, show,
    media type, and date range. Enriches logs with formatted timestamps
    and detail URLs.

    Query Params:
        user (str, optional): Filters Plex logs by username.
        show (str, optional): Filters Plex logs by show title.
        media_type (str, optional): Filters by media type ('episode', 'movie').
        days (int, optional): Filters by number of days back.

    Returns:
        flask.Response: JSON response containing list of plex_logs.
    """
    category = request.args.get('category')
    user = request.args.get('user')
    show = request.args.get('show')
    media_type = request.args.get('media_type')
    days = request.args.get('days')
    db = database.get_db()
    sync_logs = []
    plex_logs = []

    # Plex Activity logs - deduplicated to show only most recent entry per unique item
    if not category or category in ['plex', 'all']:
        # Build WHERE conditions
        where_conditions = []
        params = []

        # Filter by user
        if user:
            where_conditions.append('plex_username = ?')
            params.append(user)

        # Filter by show title
        if show:
            where_conditions.append('(title LIKE ? OR show_title LIKE ?)')
            params.extend([f'%{show}%']*2)

        # Filter by media type
        if media_type:
            where_conditions.append('media_type = ?')
            params.append(media_type)

        # Filter by date range
        if days:
            where_conditions.append('event_timestamp >= datetime("now", "-" || ? || " days")')
            params.append(int(days))

        where_clause = ' AND '.join(where_conditions) if where_conditions else '1=1'

        # Use CTE with ROW_NUMBER to deduplicate entries
        # Partition by user + show + episode to get one entry per unique watched item per user
        query = f'''
            WITH ranked_events AS (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY
                            plex_username,
                            CASE
                                WHEN media_type = 'episode' THEN show_title || '-' || season_episode
                                WHEN media_type = 'movie' THEN 'movie-' || COALESCE(tmdb_id, title)
                                ELSE title
                            END
                        ORDER BY event_timestamp DESC
                    ) as rn
                FROM plex_activity_log
                WHERE {where_clause}
            )
            SELECT * FROM ranked_events
            WHERE rn = 1
            ORDER BY event_timestamp DESC
            LIMIT 100
        '''
        rows = db.execute(query, params).fetchall()

        # PERFORMANCE OPTIMIZATION: Batch lookup TMDB IDs instead of querying in loop
        # Collect all unique show titles and movie titles that need lookup
        import re
        show_titles_to_lookup = set()
        movie_titles_to_lookup = set()

        for row in rows:
            if not row['tmdb_id']:
                if row['media_type'] == 'episode' and row['show_title']:
                    show_titles_to_lookup.add(row['show_title'])
                elif row['media_type'] == 'movie' and row['title']:
                    movie_titles_to_lookup.add(row['title'])

        # Batch fetch show TMDB IDs (single query instead of N queries)
        show_tmdb_map = {}
        if show_titles_to_lookup:
            placeholders = ','.join('?' * len(show_titles_to_lookup))
            show_results = db.execute(
                f'SELECT title, tmdb_id FROM sonarr_shows WHERE title IN ({placeholders})',
                list(show_titles_to_lookup)
            ).fetchall()
            show_tmdb_map = {r['title']: r['tmdb_id'] for r in show_results}

        # Batch fetch movie TMDB IDs (single query instead of N queries)
        movie_tmdb_map = {}
        if movie_titles_to_lookup:
            placeholders = ','.join('?' * len(movie_titles_to_lookup))
            movie_results = db.execute(
                f'SELECT title, tmdb_id FROM radarr_movies WHERE title IN ({placeholders})',
                list(movie_titles_to_lookup)
            ).fetchall()
            movie_tmdb_map = {r['title']: r['tmdb_id'] for r in movie_results}

        # Event type display mapping
        event_type_map = {
            'media.play': 'Play',
            'media.pause': 'Pause',
            'media.stop': 'Stop',
            'media.scrobble': 'Scrobble'
        }

        # Enrich with episode detail URL and formatted time
        for row in rows:
            row_dict = dict(row)

            # Get TMDB ID - either from row or from batch lookup
            tmdb_id = row_dict.get('tmdb_id')
            show_title = row_dict.get('show_title')
            title = row_dict.get('title')
            media_type = row_dict.get('media_type')

            # Use batch lookup results if no tmdb_id
            if not tmdb_id:
                if media_type == 'episode' and show_title:
                    tmdb_id = show_tmdb_map.get(show_title)
                    if tmdb_id:
                        row_dict['tmdb_id'] = tmdb_id
                elif media_type == 'movie' and title:
                    tmdb_id = movie_tmdb_map.get(title)
                    if tmdb_id:
                        row_dict['tmdb_id'] = tmdb_id

            # Build URLs based on media type
            season_episode = row_dict.get('season_episode')
            episode_detail_url = None
            show_detail_url = None
            movie_detail_url = None

            if media_type == 'episode' and tmdb_id:
                # Link to show detail page
                show_detail_url = url_for('main.show_detail', tmdb_id=tmdb_id)

                # If we have season/episode info, link to episode detail
                if season_episode:
                    match = re.match(r'S(\d+)E(\d+)', season_episode)
                    if match:
                        season_number = int(match.group(1))
                        episode_number = int(match.group(2))
                        episode_detail_url = url_for('main.episode_detail', tmdb_id=tmdb_id, season_number=season_number, episode_number=episode_number)
            elif media_type == 'movie' and tmdb_id:
                # Link to movie detail page
                movie_detail_url = url_for('main.movie_detail', tmdb_id=tmdb_id)

            row_dict['episode_detail_url'] = episode_detail_url
            row_dict['show_detail_url'] = show_detail_url
            row_dict['movie_detail_url'] = movie_detail_url

            # Format timestamp with user's timezone
            ts = row_dict.get('event_timestamp')
            if ts:
                try:
                    row_dict['event_timestamp_fmt'] = convert_utc_to_user_timezone(ts, '%Y-%m-%d %H:%M')
                except Exception:
                    row_dict['event_timestamp_fmt'] = str(ts)

            # Format event type
            event_type = row_dict.get('event_type')
            if event_type:
                row_dict['event_type_fmt'] = event_type_map.get(event_type, event_type)

            # Build display title
            episode_title = row_dict.get('title')
            row_dict['display_title'] = f'{show_title} – {episode_title}' if show_title else episode_title

            plex_logs.append(row_dict)

    return jsonify({'sync_logs': sync_logs, 'plex_logs': plex_logs})


@admin_bp.route('/users')
@login_required
@admin_required
def admin_users():
    """Admin users overview page showing activity, issues, favorites, and Jellyseerr requests per user."""
    import time
    t0 = time.monotonic()
    db = database.get_db()

    users = db.execute('''
        SELECT id, username, plex_username, plex_user_id, is_admin,
               last_login_at, profile_photo_url,
               profile_show_profile, profile_show_lists, profile_show_favorites,
               profile_show_history, profile_show_progress, allow_recommendations
        FROM users ORDER BY last_login_at DESC
    ''').fetchall()
    current_app.logger.debug(f"admin_users: users query {(time.monotonic()-t0)*1000:.0f}ms")

    # Single query for last watched per user using window function (replaces N+1)
    t1 = time.monotonic()
    last_watched = {r['plex_username']: r for r in db.execute('''
        SELECT plex_username, title, show_title, season_episode, media_type, event_timestamp
        FROM (
            SELECT plex_username, title, show_title, season_episode, media_type, event_timestamp,
                   ROW_NUMBER() OVER (PARTITION BY plex_username ORDER BY event_timestamp DESC) as rn
            FROM plex_activity_log
            WHERE event_type IN ('media.stop', 'media.scrobble', 'watched')
              AND plex_username IS NOT NULL
        ) WHERE rn = 1
    ''').fetchall()}
    current_app.logger.debug(f"admin_users: last_watched query {(time.monotonic()-t1)*1000:.0f}ms")

    t2 = time.monotonic()
    watch_counts = {r['plex_username']: r['cnt'] for r in db.execute('''
        SELECT plex_username, COUNT(*) as cnt FROM plex_activity_log
        WHERE event_type IN ('media.scrobble', 'watched') AND plex_username IS NOT NULL
        GROUP BY plex_username
    ''').fetchall()}

    issue_counts = {r['user_id']: r['cnt'] for r in db.execute('''
        SELECT user_id, COUNT(*) as cnt FROM issue_reports
        WHERE status != 'resolved' GROUP BY user_id
    ''').fetchall()}

    problem_counts = {r['user_id']: r['cnt'] for r in db.execute('''
        SELECT user_id, COUNT(*) as cnt FROM problem_reports
        WHERE status != 'resolved' GROUP BY user_id
    ''').fetchall()}

    fav_counts = {r['user_id']: r['cnt'] for r in db.execute('''
        SELECT user_id, COUNT(*) as cnt FROM user_favorites
        WHERE is_dropped = 0 GROUP BY user_id
    ''').fetchall()}

    # Household sub-profiles (non-default members) grouped by user_id
    hm_rows = db.execute('''
        SELECT id, user_id, display_name, avatar_color, avatar_url
        FROM household_members WHERE is_default = 0
        ORDER BY user_id, created_at
    ''').fetchall()
    members_by_user = {}
    for m in hm_rows:
        members_by_user.setdefault(m['user_id'], []).append(dict(m))

    member_fav_counts = {r['member_id']: r['cnt'] for r in db.execute('''
        SELECT member_id, COUNT(*) as cnt FROM user_favorites
        WHERE is_dropped = 0 AND member_id IS NOT NULL
        GROUP BY member_id
    ''').fetchall()}
    current_app.logger.debug(f"admin_users: aggregate queries {(time.monotonic()-t2)*1000:.0f}ms")

    t3 = time.monotonic()
    from ..utils import get_jellyseer_user_requests
    jellyseer_counts = get_jellyseer_user_requests()
    current_app.logger.debug(f"admin_users: jellyseerr {(time.monotonic()-t3)*1000:.0f}ms")

    current_app.logger.debug(f"admin_users: total {(time.monotonic()-t0)*1000:.0f}ms")

    return render_template('admin_users.html',
        users=users,
        last_watched=last_watched,
        watch_counts=watch_counts,
        issue_counts=issue_counts,
        problem_counts=problem_counts,
        fav_counts=fav_counts,
        jellyseer_counts=jellyseer_counts,
        members_by_user=members_by_user,
        member_fav_counts=member_fav_counts,
    )


@admin_bp.route('/api/users/<int:user_id>/permissions', methods=['POST'])
@login_required
@admin_required
def update_user_permissions(user_id):
    """Update a user's admin status and privacy/permission settings."""
    db = database.get_db()
    user = db.execute('SELECT id FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    data = request.json or {}
    db.execute('''
        UPDATE users SET
            is_admin = ?,
            profile_show_profile = ?,
            profile_show_lists = ?,
            profile_show_favorites = ?,
            profile_show_history = ?,
            profile_show_progress = ?,
            allow_recommendations = ?
        WHERE id = ?
    ''', (
        1 if data.get('is_admin') else 0,
        1 if data.get('profile_show_profile') else 0,
        1 if data.get('profile_show_lists') else 0,
        1 if data.get('profile_show_favorites') else 0,
        1 if data.get('profile_show_history') else 0,
        1 if data.get('profile_show_progress') else 0,
        1 if data.get('allow_recommendations') else 0,
        user_id,
    ))
    db.commit()
    return jsonify({'success': True})


@admin_bp.route('/logs/list', methods=['GET'])
@login_required
@admin_required
def logs_list():
    """
    Provides a list of available log files.

    This API endpoint scans the log directory for files matching the pattern
    'shownotes.log*' and returns their filenames as a JSON list. This is used
    by the log viewer to populate the log file selection dropdown.

    Returns:
        flask.Response: A JSON response containing a sorted list of log filenames.
    """
    log_dir = os.path.join(os.path.dirname(current_app.root_path), 'logs')
    log_files_paths = glob.glob(os.path.join(log_dir, 'shownotes.log*'))
    log_filenames = sorted([os.path.basename(f) for f in log_files_paths])
    return jsonify(log_filenames)

@admin_bp.route('/logs/get/<path:filename>', methods=['GET'])
@login_required
@admin_required
def get_log_content(filename):
    """
    Retrieves the content of a specified log file.

    This API endpoint reads the last 100 lines of a given log file and returns
    them as a JSON list. It includes a security check to prevent path traversal
    attacks.

    Args:
        filename (str): The name of the log file to be read, captured from the URL path.

    Returns:
        flask.Response: A JSON response containing a list of log lines, or an
                        error response if the file is not found or access is denied.
    """
    log_dir = os.path.join(os.path.dirname(current_app.root_path), 'logs')
    file_path = os.path.join(log_dir, filename)

    # Security check to prevent path traversal
    if not os.path.abspath(file_path).startswith(os.path.abspath(log_dir)):
        current_app.logger.warning(f"Log access rejected for {filename} due to path traversal attempt.")
        return jsonify({"error": "Access denied"}), 403

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines() # Read all lines
        return jsonify(lines[-100:]) # Return last 100 lines
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404
    except Exception as e:
        current_app.logger.error(f"Error reading log file {filename}: {e}")
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/logs/stream/<path:filename>', methods=['GET'])
@login_required
@admin_required
def stream_log_content(filename):
    """
    Streams the content of a log file in real-time using Server-Sent Events (SSE).

    This endpoint opens a specified log file and continuously sends any new lines
    to the client. This allows for a "live tail" feature in the log viewer UI.
    It includes a security check to prevent path traversal.

    Args:
        filename (str): The name of the log file to stream, from the URL path.

    Returns:
        flask.Response: An SSE stream that pushes log lines to the client.
    """
    log_dir = os.path.join(os.path.dirname(current_app.root_path), 'logs')
    file_path = os.path.join(log_dir, filename)

    # Security check
    if not os.path.abspath(file_path).startswith(os.path.abspath(log_dir)):
        return Response("data: ERROR: Access Denied\n\n", mimetype='text/event-stream', status=403)

    if not os.path.exists(file_path):
        return Response("data: ERROR: File Not Found\n\n", mimetype='text/event-stream', status=404)

    def generate_log_updates(file_path_stream):
        """Generator function to yield new log lines."""
        try:
            with open(file_path_stream, 'r', encoding='utf-8') as f:
                f.seek(0, os.SEEK_END)
                while True:
                    line = f.readline()
                    if not line:
                        time.sleep(0.5)
                        continue
                    yield f"data: {line.rstrip()}\n\n"
        except Exception as e:
            current_app.logger.error(f"Error streaming log file {file_path_stream}: {e}")
            yield f"data: ERROR: Could not stream log: {str(e)}\n\n"

    return Response(stream_with_context(generate_log_updates(file_path)), mimetype='text/event-stream')

# ============================================================================
# SETTINGS MANAGEMENT
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

@admin_bp.route('/api/ollama-models')
@login_required
@admin_required
def ollama_models_api():
    """API endpoint to fetch available Ollama models"""
    import requests
    url = request.args.get('url')
    if not url:
        return jsonify({"error": "URL parameter required"}), 400

    try:
        response = requests.get(f"{url.rstrip('/')}/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            models = data.get('models', [])
            model_names = [model.get('name') for model in models if model.get('name')]
            return jsonify({"models": model_names})
        else:
            return jsonify({"error": f"Ollama server returned status {response.status_code}"}), 500
    except requests.exceptions.Timeout:
        return jsonify({"error": "Connection timeout"}), 500
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Could not connect to Ollama server"}), 500
    except Exception as e:
        current_app.logger.error(f"Error fetching Ollama models: {e}")
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/test-ollama-models')
@login_required
@admin_required
def test_ollama_models_route():
    """Debug route to test Ollama model fetching"""
    models = get_ollama_models()
    return jsonify({"models": models, "count": len(models)})

@admin_bp.route('/api/summary-queue-status')
@login_required
@admin_required
def summary_queue_status():
    """API endpoint to get summary generation queue status."""
    from app.summary_services import get_summary_queue_status
    return jsonify(get_summary_queue_status())

@admin_bp.route('/api/trigger-summary-generation', methods=['POST'])
@login_required
@admin_required
def trigger_summary_generation():
    """Manually trigger summary generation in a background thread."""
    import threading
    from app.summary_services import process_summary_queue

    app = current_app._get_current_object()

    def run_summaries():
        process_summary_queue(app)

    thread = threading.Thread(target=run_summaries)
    thread.daemon = True
    thread.start()
    return jsonify({"status": "started", "message": "Summary generation started in background"})

@admin_bp.route('/api/generate-season-summary', methods=['POST'])
@login_required
@admin_required
def generate_single_season_summary():
    """Generate summary for a specific show/season immediately."""
    from app.summary_services import generate_season_summary
    tmdb_id = request.json.get('tmdb_id')
    season_number = request.json.get('season_number')
    if not tmdb_id or season_number is None:
        return jsonify({"error": "tmdb_id and season_number required"}), 400

    success, error = generate_season_summary(int(tmdb_id), int(season_number))
    if success:
        return jsonify({"status": "completed", "message": f"Summary generated for tmdb_id={tmdb_id} S{season_number}"})
    else:
        return jsonify({"status": "failed", "error": error}), 500

@admin_bp.route('/sync-sonarr', methods=['POST'])
@login_required
@admin_required
def sync_sonarr():
    """
    Triggers a Sonarr library synchronization task in the background.

    This is a POST-only endpoint that initiates the `sync_sonarr_library`
    utility function in a background thread. It immediately returns to avoid
    timeout issues, and the sync continues in the background.

    Returns:
        A redirect to the 'admin.tasks' page.
    """
    from ..utils import sync_sonarr_library
    import threading

    flash("Sonarr library sync started in background. Check Event Logs for progress.", "info")

    # Capture the application object to pass to the thread
    app_instance = current_app._get_current_object()

    def sync_in_background(app):
        with app.app_context():
            try:
                from app.system_logger import syslog, SystemLogger
                current_app.logger.info("Manual Sonarr sync started from admin panel")
                syslog.info(SystemLogger.SYNC, "Manual Sonarr sync initiated from admin panel")

                count = sync_sonarr_library()

                current_app.logger.info(f"Manual Sonarr sync completed: {count} shows processed")
                syslog.success(SystemLogger.SYNC, f"Manual Sonarr sync completed: {count} shows", {
                    'show_count': count,
                    'source': 'admin_panel'
                })
            except Exception as e:
                current_app.logger.error(f"Manual Sonarr sync error: {e}", exc_info=True)
                syslog.error(SystemLogger.SYNC, "Manual Sonarr sync failed", {
                    'error': str(e),
                    'source': 'admin_panel'
                })

    # Start background sync
    sync_thread = threading.Thread(target=sync_in_background, args=(app_instance,))
    sync_thread.daemon = True
    sync_thread.start()

    current_app.logger.info("Sonarr library sync initiated in background thread")

    return redirect(url_for('admin.tasks'))

# ============================================================================
# LLM TOOLS
# ============================================================================


@admin_bp.route('/clear-character-cache', methods=['POST'])
@login_required
@admin_required
def clear_character_cache():
    """Clear all cached LLM data for characters to force regeneration."""
    try:
        db = database.get_db()
        result = db.execute('''
            UPDATE episode_characters 
            SET llm_relationships=NULL, llm_motivations=NULL, llm_quote=NULL, 
                llm_traits=NULL, llm_events=NULL, llm_importance=NULL, 
                llm_raw_response=NULL, llm_last_updated=NULL, llm_source=NULL
        ''')
        db.commit()
        
        rows_affected = result.rowcount
        return jsonify({'success': True, 'message': f'Cleared LLM cache for {rows_affected} characters'})
    except Exception as e:
        current_app.logger.error(f"Error clearing character cache: {e}")
        return jsonify({'error': 'Failed to clear cache'}), 500














@admin_bp.route('/api/latest-episode')
@login_required
@admin_required
def get_latest_episode():
    """
    API endpoint to get the latest aired episode for a show.
    """
    tmdb_id = request.args.get('tmdb_id')
    if not tmdb_id:
        return jsonify({'error': 'TMDB ID is required'}), 400

    try:
        db = get_db()
        
        # Get the latest aired episode for this show (only episodes that have actually aired)
        # We need to join through the seasons table to get season numbers
        latest_episode = db.execute('''
            SELECT s.season_number, e.episode_number, e.air_date_utc
            FROM sonarr_episodes e
            JOIN sonarr_seasons s ON e.season_id = s.id
            JOIN sonarr_shows sh ON s.show_id = sh.id
            WHERE sh.tmdb_id = ? 
            AND e.air_date_utc IS NOT NULL 
            AND e.air_date_utc != ''
            AND e.air_date_utc <= datetime('now')
            ORDER BY s.season_number DESC, e.episode_number DESC
            LIMIT 1
        ''', (tmdb_id,)).fetchone()
        
        if latest_episode:
            return jsonify({
                'season': latest_episode['season_number'],
                'episode': latest_episode['episode_number'],
                'air_date': latest_episode['air_date_utc']
            })
        else:
            # If no aired episodes found, get the latest episode regardless of air date
            latest_episode = db.execute('''
                SELECT s.season_number, e.episode_number
                FROM sonarr_episodes e
                JOIN sonarr_seasons s ON e.season_id = s.id
                JOIN sonarr_shows sh ON s.show_id = sh.id
                WHERE sh.tmdb_id = ? 
                ORDER BY s.season_number DESC, e.episode_number DESC
                LIMIT 1
            ''', (tmdb_id,)).fetchone()
            
            if latest_episode:
                return jsonify({
                    'season': latest_episode['season_number'],
                    'episode': latest_episode['episode_number'],
                    'air_date': None
                })
            else:
                return jsonify({'error': 'No episodes found for this show'}), 404
                
    except Exception as e:
        current_app.logger.error(f"Error fetching latest episode: {e}", exc_info=True)
        return jsonify({'error': 'Database error'}), 500

@admin_bp.route('/api/get-character-info', methods=['POST'])
@login_required
@admin_required
def get_character_info():
    """
    API endpoint to get character information from the database for testing.
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON payload'}), 400

    character_name = data.get('character', '')
    show_title = data.get('show', '')
    season = data.get('season', 1)
    episode = data.get('episode', 1)

    if not character_name or not show_title:
        return jsonify({'error': 'Character and show are required'}), 400

    db = get_db()
    
    try:
        # First, find the show by title
        show_row = db.execute('SELECT tmdb_id, title, year, overview FROM sonarr_shows WHERE title LIKE ?', (f'%{show_title}%',)).fetchone()
        
        if not show_row:
            current_app.logger.warning(f"Show not found for title: {show_title}")
            return jsonify({'error': 'Show not found', 'searched_title': show_title}), 404
        
        show_tmdb_id = show_row['tmdb_id']
        current_app.logger.info(f"Found show: {show_row['title']} (TMDB ID: {show_tmdb_id})")
        
        # Find the character by name and show
        character_row = db.execute('''
            SELECT ec.actor_name, ec.character_name
            FROM episode_characters ec
            WHERE ec.show_tmdb_id = ? 
            AND ec.season_number = ? 
            AND ec.episode_number = ?
            AND ec.character_name LIKE ?
            LIMIT 1
        ''', (show_tmdb_id, season, episode, f'%{character_name}%')).fetchone()
        
        # Also check what characters exist for this show/episode for debugging
        all_characters = db.execute('''
            SELECT ec.character_name, ec.actor_name
            FROM episode_characters ec
            WHERE ec.show_tmdb_id = ? 
            AND ec.season_number = ? 
            AND ec.episode_number = ?
            LIMIT 10
        ''', (show_tmdb_id, season, episode)).fetchall()
        
        result = {
            'character_name': character_name,
            'show_title': show_title,
            'season': season,
            'episode': episode,
            'actor_name': None,
            'show_year': show_row['year'],
            'show_overview': show_row['overview'],
            'debug_info': {
                'searched_character': character_name,
                'found_show': show_row['title'],
                'show_tmdb_id': show_tmdb_id,
                'available_characters': [{'name': c['character_name'], 'actor': c['actor_name']} for c in all_characters]
            }
        }
        
        if character_row:
            result['actor_name'] = character_row['actor_name']
            current_app.logger.info(f"Found character: {character_row['character_name']} played by {character_row['actor_name']}")
        else:
            current_app.logger.warning(f"Character not found: {character_name} in {show_title} S{season}E{episode}")
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.error(f"Error fetching character info: {e}", exc_info=True)
        return jsonify({'error': 'Database error'}), 500

@admin_bp.route('/api/replace-variables', methods=['POST'])
@login_required
@admin_required
def replace_variables():
    """
    API endpoint to replace variables in a prompt with sample data for testing.
    """
    data = request.get_json()
    if not data or 'prompt_text' not in data:
        return jsonify({'error': 'Missing prompt_text'}), 400

    prompt_text = data['prompt_text']
    
    # Sample data for variable replacement (using single brackets)
    sample_data = {
        '{character}': data.get('character', 'John Doe'),
        '{show}': data.get('show', 'Breaking Bad'),
        '{season}': str(data.get('season', 2)),
        '{episode}': str(data.get('episode', 5)),
        '{actor}': data.get('actor', 'Bryan Cranston'),
        '{year}': str(data.get('year', 2008)),
        '{genre}': data.get('genre', 'Drama'),
        '{overview}': data.get('overview', 'A high school chemistry teacher diagnosed with inoperable lung cancer turns to manufacturing and selling methamphetamine.'),
        '{episode_title}': data.get('episode_title', 'The One Where Walter Gets Angry'),
        '{episode_overview}': data.get('episode_overview', 'Walter confronts his family about his secret life while dealing with the consequences of his actions.'),
        '{air_date}': data.get('air_date', 'March 15, 2009'),
        '{other_characters}': data.get('other_characters', 'Jesse Pinkman, Skyler White, Hank Schrader')
    }

    # Replace variables in the prompt
    replaced_prompt = prompt_text
    for variable, replacement in sample_data.items():
        replaced_prompt = replaced_prompt.replace(variable, replacement)

    return jsonify({
        'original_prompt': prompt_text,
        'replaced_prompt': replaced_prompt,
        'variables_found': [var for var in sample_data.keys() if var in prompt_text]
    })

@admin_bp.route('/api/prompt-history/<int:prompt_id>')
@login_required
@admin_required
def get_prompt_history(prompt_id):
    """
    API endpoint to retrieve the version history for a specific prompt.
    """
    db = get_db()
    try:
        history_rows = db.execute(
            'SELECT * FROM prompt_history WHERE prompt_id = ? ORDER BY timestamp DESC',
            (prompt_id,)
        ).fetchall()

        history = [dict(row) for row in history_rows]

        return jsonify(history)
    except Exception as e:
        current_app.logger.error(f"Error fetching history for prompt_id {prompt_id}: {e}", exc_info=True)
        return jsonify({'error': 'Database query failed'}), 500

@admin_bp.route('/api/characters-for-show')
@login_required
@admin_required
def api_characters_for_show():
    """
    API endpoint to get all unique character names for a given show.
    Accepts a 'tmdb_id' query parameter.
    First tries episode_characters table, then falls back to Plex activity log.
    """
    show_tmdb_id = request.args.get('tmdb_id')
    if not show_tmdb_id:
        return jsonify({'error': 'tmdb_id parameter is required'}), 400

    db = get_db()
    try:
        # First, try to get characters from episode_characters table
        characters = db.execute(
            "SELECT DISTINCT character_name FROM episode_characters WHERE show_tmdb_id = ?",
            (show_tmdb_id,)
        ).fetchall()

        character_names = [row['character_name'] for row in characters if row['character_name']]
        
        # If no characters found in episode_characters, try Plex activity log fallback
        if not character_names:
            # Get show title from sonarr_shows
            show_row = db.execute('SELECT title FROM sonarr_shows WHERE tmdb_id = ?', (show_tmdb_id,)).fetchone()
            if show_row:
                show_title = show_row['title']
                
                # Get the most recent Plex activity log entry for this show
                plex_row = db.execute(
                    'SELECT raw_payload FROM plex_activity_log WHERE show_title = ? ORDER BY event_timestamp DESC LIMIT 1',
                    (show_title,)
                ).fetchone()
                
                if plex_row:
                    import json
                    try:
                        payload = json.loads(plex_row['raw_payload'])
                        metadata = payload.get('Metadata', {})
                        roles = metadata.get('Role', [])
                        
                        # Extract character names from Plex data
                        plex_characters = []
                        for role in roles:
                            character_name = role.get('role')
                            if character_name:
                                plex_characters.append(character_name)
                        
                        character_names = plex_characters
                        current_app.logger.info(f"Found {len(character_names)} characters from Plex data for show {show_title}")
                        
                    except (json.JSONDecodeError, KeyError) as e:
                        current_app.logger.error(f"Error parsing Plex data for show {show_title}: {e}")

        return jsonify(character_names)

    except Exception as e:
        current_app.logger.error(f"Error fetching characters for show {show_tmdb_id}: {e}", exc_info=True)
        return jsonify({'error': 'Database query failed'}), 500

# ============================================================================
# API USAGE
# ============================================================================




@admin_bp.route('/sync-radarr', methods=['POST'])
@login_required
@admin_required
def sync_radarr():
    """
    Triggers a Radarr library synchronization task in the background.

    A POST-only endpoint that calls the `sync_radarr_library` utility function
    in a background thread. It immediately returns to avoid timeout issues.

    Returns:
        A redirect to the 'admin.tasks' page.
    """
    from ..utils import sync_radarr_library
    import threading

    flash("Radarr library sync started in background. Check Event Logs for progress.", "info")

    # Capture the application object to pass to the thread
    app_instance = current_app._get_current_object()

    def sync_in_background(app):
        with app.app_context():
            try:
                from app.system_logger import syslog, SystemLogger
                current_app.logger.info("Manual Radarr sync started from admin panel")
                syslog.info(SystemLogger.SYNC, "Manual Radarr sync initiated from admin panel")

                count = sync_radarr_library()

                current_app.logger.info(f"Manual Radarr sync completed: {count} movies processed")
                syslog.success(SystemLogger.SYNC, f"Manual Radarr sync completed: {count} movies", {
                    'movie_count': count,
                    'source': 'admin_panel'
                })
            except Exception as e:
                current_app.logger.error(f"Manual Radarr sync error: {e}", exc_info=True)
                syslog.error(SystemLogger.SYNC, "Manual Radarr sync failed", {
                    'error': str(e),
                    'source': 'admin_panel'
                })

    # Start background sync
    sync_thread = threading.Thread(target=sync_in_background, args=(app_instance,))
    sync_thread.daemon = True
    sync_thread.start()

    current_app.logger.info("Radarr library sync initiated in background thread")

    return redirect(url_for('admin.tasks'))

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

@admin_bp.route('/sync-tautulli', methods=['POST'])
@login_required
@admin_required
def sync_tautulli():
    """
    Triggers a Tautulli watch history synchronization task.

    Supports both incremental (default) and full import modes.
    Query parameter ?full=true triggers a full import.

    Returns:
        A redirect to the 'admin.tasks' page.
    """
    full_import = request.args.get('full', 'false').lower() == 'true'

    if full_import:
        flash("Tautulli FULL import started in background. This may take several minutes. Check Event Logs for progress.", "info")
    else:
        flash("Tautulli incremental sync started...", "info")

    import threading
    app_instance = current_app._get_current_object()

    def sync_in_background(app, full):
        with app.app_context():
            try:
                from app.system_logger import syslog, SystemLogger
                mode = "full import" if full else "incremental sync"
                syslog.info(SystemLogger.SYNC, f"Manual Tautulli {mode} initiated from admin panel")

                count = sync_tautulli_watch_history(full_import=full)

                syslog.success(SystemLogger.SYNC, f"Tautulli {mode} completed: {count} new events", {
                    'event_count': count,
                    'mode': mode
                })
            except Exception as e:
                syslog.error(SystemLogger.SYNC, f"Tautulli {mode} failed", {
                    'error': str(e),
                    'mode': mode
                })

    sync_thread = threading.Thread(target=sync_in_background, args=(app_instance, full_import))
    sync_thread.daemon = True
    sync_thread.start()

    return redirect(url_for('admin.tasks'))

@admin_bp.route('/tautulli-wipe-and-import', methods=['POST'])
@login_required
@admin_required
def tautulli_wipe_and_import():
    """
    Wipes all existing Plex activity log data and performs a fresh full import
    from Tautulli. Use this for onboarding or to reset watch history.

    Returns:
        A redirect to the 'admin.tasks' page.
    """
    flash("Wiping watch history and starting fresh Tautulli import in background. Check Event Logs for progress.", "warning")

    import threading
    app_instance = current_app._get_current_object()

    def wipe_and_import(app):
        with app.app_context():
            try:
                from app.system_logger import syslog, SystemLogger
                db = database.get_db()

                # Get count before wiping
                old_count = db.execute('SELECT COUNT(*) as count FROM plex_activity_log').fetchone()['count']

                syslog.info(SystemLogger.SYNC, f"Wiping {old_count} existing watch history records")

                # Wipe all existing data
                db.execute('DELETE FROM plex_activity_log')
                db.commit()

                syslog.success(SystemLogger.SYNC, "Watch history wiped, starting fresh import")

                # Do full import
                count = sync_tautulli_watch_history(full_import=True)

                syslog.success(SystemLogger.SYNC, f"Fresh Tautulli import completed: {count} events imported", {
                    'old_count': old_count,
                    'new_count': count
                })
            except Exception as e:
                syslog.error(SystemLogger.SYNC, "Tautulli wipe and import failed", {
                    'error': str(e)
                })

    import_thread = threading.Thread(target=wipe_and_import, args=(app_instance,))
    import_thread.daemon = True
    import_thread.start()

    return redirect(url_for('admin.tasks'))

@admin_bp.route('/process-watch-status', methods=['POST'])
@login_required
@admin_required
def process_watch_status():
    """
    Process plex_activity_log to update user_episode_progress with watch indicators.

    This scans all historical watch events and marks episodes as watched in the
    user_episode_progress table. Useful for backfilling watch status from Tautulli imports.

    Returns:
        A redirect to the 'admin.tasks' page.
    """
    flash("Processing activity log for watch indicators in background. This may take a few minutes. Check Event Logs for progress.", "info")

    import threading
    app_instance = current_app._get_current_object()

    def process_in_background(app):
        with app.app_context():
            try:
                from app.system_logger import syslog, SystemLogger
                syslog.info(SystemLogger.SYNC, "Processing activity log for watch status initiated from admin panel")

                from app.utils import process_activity_log_for_watch_status
                count = process_activity_log_for_watch_status()

                syslog.success(SystemLogger.SYNC, f"Watch status processing completed: {count} episodes marked as watched", {
                    'episode_count': count
                })
            except Exception as e:
                syslog.error(SystemLogger.SYNC, "Watch status processing failed", {
                    'error': str(e)
                })

    process_thread = threading.Thread(target=process_in_background, args=(app_instance,))
    process_thread.daemon = True
    process_thread.start()

    return redirect(url_for('admin.tasks'))

@admin_bp.route('/parse-subtitles', methods=['POST'])
@login_required
@admin_required
def parse_all_subtitles_route():
    """
    Triggers the task to parse all subtitles for all shows.

    This POST-only endpoint initiates the `process_all_subtitles` function,
    which can be a long-running task. It flashes status messages and redirects
    to the tasks page.

    Returns:
        A redirect to the 'admin.tasks' page.
    """
    current_app.logger.info("Subtitle parsing task triggered by admin.")
    flash("Subtitle parsing started...", "info")
    try:
        # Assuming process_all_subtitles handles its own logging for details
        process_all_subtitles()
        flash("Subtitle parsing completed successfully.", "success")
        current_app.logger.info("Subtitle parsing task completed successfully.")
    except Exception as e:
        current_app.logger.error(f"Error during subtitle parsing: {e}", exc_info=True)
        flash(f"Error during subtitle parsing: {str(e)}", "danger")
    return redirect(url_for('admin.tasks'))

@admin_bp.route('/plex_webhook_payloads', methods=['GET'])
@login_required
@admin_required
def plex_webhook_payloads():
    db = get_db()
    rows = db.execute('SELECT id, event_type, event_timestamp, raw_payload FROM plex_activity_log ORDER BY event_timestamp DESC LIMIT 20').fetchall()
    payloads = []
    import json
    for row in rows:
        try:
            payload = json.loads(row['raw_payload']) if row['raw_payload'] else {}
        except Exception:
            payload = row['raw_payload']
        payloads.append({
            'id': row['id'],
            'event_type': row['event_type'],
            'event_timestamp': row['event_timestamp'],
            'payload': payload
        })
    return render_template('admin_plex_webhook_payloads.html', payloads=payloads)


@admin_bp.route('/issue-reports')
@login_required
@admin_required
def issue_reports():
    db = get_db()
    rows = db.execute('SELECT * FROM issue_reports ORDER BY created_at DESC').fetchall()
    return render_template('admin_issue_reports.html', reports=[dict(r) for r in rows])


@admin_bp.route('/issue-reports/<int:report_id>/resolve', methods=['POST'])
@login_required
@admin_required
def resolve_issue_report(report_id):
    db = get_db()

    # Get issue report details before resolving
    report = db.execute(
        'SELECT user_id, title, show_id, issue_type FROM issue_reports WHERE id = ?',
        (report_id,)
    ).fetchone()

    if not report:
        flash('Report not found.', 'error')
        return redirect(url_for('admin.issue_reports'))

    # Resolve the report
    notes = request.form.get('resolution_notes', '')
    db.execute(
        "UPDATE issue_reports SET status='resolved', resolved_by_admin_id=?, resolved_at=CURRENT_TIMESTAMP, resolution_notes=? WHERE id=?",
        (current_user.id, notes, report_id)
    )
    db.commit()

    # Create notification for the user who reported
    try:
        import re

        # Parse episode info from title
        season_num = None
        episode_num = None
        if ' - S' in report['title']:
            match = re.search(r'S(\d+)E(\d+)', report['title'])
            if match:
                season_num = int(match.group(1))
                episode_num = int(match.group(2))

        notification_title = f"Issue Resolved: {report['title']}"
        notification_message = f"Your reported issue ({report['issue_type']}) has been resolved."
        if notes:
            notification_message += f" Resolution: {notes}"

        db.execute('''
            INSERT INTO user_notifications
            (user_id, show_id, notification_type, title, message, season_number, episode_number)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            report['user_id'],
            report['show_id'],
            'issue_resolved',
            notification_title,
            notification_message,
            season_num,
            episode_num
        ))

        db.commit()
        current_app.logger.info(f"Created resolution notification for user {report['user_id']}")
    except Exception as e:
        current_app.logger.error(f"Error creating resolution notification: {e}", exc_info=True)

    flash('Report resolved.', 'success')
    return redirect(url_for('admin.issue_reports'))


@admin_bp.route('/event-logs')
@login_required
@admin_required
def event_logs():
    """Display system event logs page"""
    return render_template('admin_event_logs.html', title='System Event Logs')


@admin_bp.route('/api/event-logs', methods=['GET'])
@login_required
@admin_required
def api_event_logs():
    """API endpoint to fetch event logs with filtering and pagination"""
    from app.system_logger import SystemLogger

    try:
        # Get query parameters
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 50))
        level = request.args.get('level', None)
        component = request.args.get('component', None)
        search = request.args.get('search', None)

        # Calculate offset
        offset = (page - 1) * per_page

        # Get logs
        logs = SystemLogger.get_logs(
            limit=per_page,
            offset=offset,
            level=level,
            component=component,
            search=search
        )

        # Get total count
        total_count = SystemLogger.get_log_count(
            level=level,
            component=component,
            search=search
        )

        # Get user's timezone for client-side formatting
        user_timezone = get_user_timezone()

        return jsonify({
            'success': True,
            'logs': logs,
            'total': total_count,
            'page': page,
            'per_page': per_page,
            'total_pages': (total_count + per_page - 1) // per_page,
            'timezone': user_timezone
        })

    except Exception as e:
        current_app.logger.error(f"Error fetching event logs: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin_bp.route('/api/event-logs/<int:log_id>', methods=['GET'])
@login_required
@admin_required
def api_event_log_detail(log_id):
    """API endpoint to get full details of a specific log entry"""
    try:
        db = get_db()
        log = db.execute('SELECT * FROM system_logs WHERE id = ?', (log_id,)).fetchone()

        if not log:
            return jsonify({
                'success': False,
                'error': 'Log entry not found'
            }), 404

        return jsonify({
            'success': True,
            'log': dict(log)
        })

    except Exception as e:
        current_app.logger.error(f"Error fetching log detail: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ========================================
# ANNOUNCEMENTS
# ========================================

@admin_bp.route('/announcements')
@login_required
@admin_required
def announcements():
    """Admin page for managing announcements"""
    return render_template('admin_announcements.html')

@admin_bp.route('/api/announcements', methods=['GET'])
@login_required
@admin_required
def api_get_announcements():
    """Get all announcements"""
    try:
        db = get_db()
        announcements = db.execute('''
            SELECT id, title, message, type, is_active, start_date, end_date, created_at, updated_at
            FROM announcements
            ORDER BY created_at DESC
        ''').fetchall()

        return jsonify({
            'success': True,
            'announcements': [dict(a) for a in announcements]
        })

    except Exception as e:
        current_app.logger.error(f"Error fetching announcements: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@admin_bp.route('/api/announcements', methods=['POST'])
@login_required
@admin_required
def api_create_announcement():
    """Create a new announcement"""
    db = None
    try:
        data = request.get_json()
        current_app.logger.info(f"Announcement creation request data: {data}")

        if not data:
            current_app.logger.error("No data provided in announcement creation request")
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400

        title = data.get('title', '').strip()
        message = data.get('message', '').strip()
        type_ = data.get('type', 'info')
        is_active = 1 if data.get('is_active', True) else 0  # Convert to int for SQLite
        start_date = data.get('start_date') or None  # Convert empty string to None
        end_date = data.get('end_date') or None  # Convert empty string to None

        current_app.logger.info(f"Processed values - title: '{title}', message: '{message}', type: '{type_}', is_active: {is_active}, start_date: {start_date}, end_date: {end_date}")

        if not title or not message:
            current_app.logger.error(f"Missing required fields - title: '{title}', message: '{message}'")
            return jsonify({
                'success': False,
                'error': 'Title and message are required'
            }), 400

        db = get_db()
        user_id = session.get('user_id')
        current_app.logger.info(f"Creating announcement for user_id: {user_id}")

        cur = db.execute('''
            INSERT INTO announcements (title, message, type, is_active, start_date, end_date, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (title, message, type_, is_active, start_date, end_date, user_id))

        db.commit()
        current_app.logger.info(f"Announcement created successfully with id: {cur.lastrowid}")

        return jsonify({
            'success': True,
            'id': cur.lastrowid
        })

    except Exception as e:
        if db:
            db.rollback()
        current_app.logger.error(f"Error creating announcement: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@admin_bp.route('/api/announcements/<int:announcement_id>', methods=['PATCH'])
@login_required
@admin_required
def api_update_announcement(announcement_id):
    """Update an announcement"""
    db = None
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400

        title = data.get('title', '').strip()
        message = data.get('message', '').strip()
        type_ = data.get('type', 'info')
        is_active = 1 if data.get('is_active', True) else 0  # Convert to int for SQLite
        start_date = data.get('start_date') or None  # Convert empty string to None
        end_date = data.get('end_date') or None  # Convert empty string to None

        if not title or not message:
            return jsonify({
                'success': False,
                'error': 'Title and message are required'
            }), 400

        db = get_db()

        db.execute('''
            UPDATE announcements
            SET title = ?, message = ?, type = ?, is_active = ?,
                start_date = ?, end_date = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (title, message, type_, is_active, start_date, end_date, announcement_id))

        db.commit()

        return jsonify({'success': True})

    except Exception as e:
        if db:
            db.rollback()
        current_app.logger.error(f"Error updating announcement: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@admin_bp.route('/api/announcements/<int:announcement_id>', methods=['DELETE'])
@login_required
@admin_required
def api_delete_announcement(announcement_id):
    """Delete an announcement"""
    try:
        db = get_db()
        db.execute('DELETE FROM announcements WHERE id = ?', (announcement_id,))
        db.commit()

        return jsonify({'success': True})

    except Exception as e:
        db.rollback()
        current_app.logger.error(f"Error deleting announcement: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ========================================
# PROBLEM REPORTS
# ========================================

@admin_bp.route('/problem-reports')
@login_required
@admin_required
def problem_reports():
    """Admin page for managing problem reports"""
    return render_template('admin_problem_reports.html')

@admin_bp.route('/api/admin/problem-reports', methods=['GET'])
@login_required
@admin_required
def api_get_problem_reports():
    """Get all problem reports with optional status filter"""
    try:
        db = get_db()
        status = request.args.get('status')

        if status and status != 'all':
            reports = db.execute('''
                SELECT pr.*, u.username,
                       s.title as show_title,
                       m.title as movie_title,
                       e.title as episode_title
                FROM problem_reports pr
                JOIN users u ON pr.user_id = u.id
                LEFT JOIN sonarr_shows s ON pr.show_id = s.id
                LEFT JOIN radarr_movies m ON pr.movie_id = m.id
                LEFT JOIN sonarr_episodes e ON pr.episode_id = e.id
                WHERE pr.status = ?
                ORDER BY pr.created_at DESC
            ''', (status,)).fetchall()
        else:
            reports = db.execute('''
                SELECT pr.*, u.username,
                       s.title as show_title,
                       m.title as movie_title,
                       e.title as episode_title
                FROM problem_reports pr
                JOIN users u ON pr.user_id = u.id
                LEFT JOIN sonarr_shows s ON pr.show_id = s.id
                LEFT JOIN radarr_movies m ON pr.movie_id = m.id
                LEFT JOIN sonarr_episodes e ON pr.episode_id = e.id
                ORDER BY pr.created_at DESC
            ''').fetchall()

        # Get user's timezone for client-side formatting
        user_timezone = get_user_timezone()

        return jsonify({
            'success': True,
            'reports': [dict(r) for r in reports],
            'timezone': user_timezone
        })

    except Exception as e:
        current_app.logger.error(f"Error fetching problem reports: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@admin_bp.route('/api/admin/problem-reports/<int:report_id>', methods=['PATCH'])
@login_required
@admin_required
def api_update_problem_report(report_id):
    """Update a problem report"""
    try:
        data = request.get_json()

        status = data.get('status')
        priority = data.get('priority')
        admin_notes = data.get('admin_notes', '').strip()

        db = get_db()
        user_id = session.get('user_id')

        # If marking as resolved, set resolved_by and resolved_at
        if status == 'resolved':
            db.execute('''
                UPDATE problem_reports
                SET status = ?, priority = ?, admin_notes = ?,
                    resolved_by = ?, resolved_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (status, priority, admin_notes, user_id, report_id))
        else:
            db.execute('''
                UPDATE problem_reports
                SET status = ?, priority = ?, admin_notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (status, priority, admin_notes, report_id))

        db.commit()

        return jsonify({'success': True})

    except Exception as e:
        db.rollback()
        current_app.logger.error(f"Error updating problem report: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# AI / LLM MANAGEMENT
# ============================================================================

@admin_bp.route('/ai')
@login_required
@admin_required
def ai_settings():
    """AI admin page with settings, prompts, generate, and logs tabs."""
    db = get_db()

    # Load current settings
    settings_row = db.execute('SELECT * FROM settings LIMIT 1').fetchone()
    settings = dict(settings_row) if settings_row else {}

    # Load prompts
    prompts = db.execute('SELECT * FROM llm_prompts ORDER BY id').fetchall()

    # Load shows for generate tab
    shows = db.execute(
        'SELECT id, title, season_count, status FROM sonarr_shows ORDER BY title'
    ).fetchall()

    # Summary counts per show
    summary_counts = db.execute('''
        SELECT
            s.id as show_id, s.title,
            SUM(CASE WHEN sm.episode_number IS NOT NULL THEN 1 ELSE 0 END) as episode_count,
            SUM(CASE WHEN sm.episode_number IS NULL AND sm.season_number IS NOT NULL THEN 1 ELSE 0 END) as season_count
        FROM show_summaries sm
        JOIN sonarr_shows s ON sm.show_id = s.id
        GROUP BY sm.show_id
        ORDER BY s.title
    ''').fetchall()

    # API usage logs (most recent 100)
    logs = db.execute(
        'SELECT * FROM api_usage ORDER BY timestamp DESC LIMIT 100'
    ).fetchall()

    # Log stats
    log_stats = db.execute('''
        SELECT
            (SELECT COUNT(*) FROM api_usage) as total_calls,
            (SELECT COALESCE(SUM(cost_usd), 0) FROM api_usage) as total_cost,
            (SELECT COUNT(*) FROM api_usage WHERE timestamp >= DATETIME('now', '-7 days')) as week_calls,
            (SELECT COALESCE(SUM(cost_usd), 0) FROM api_usage WHERE timestamp >= DATETIME('now', '-7 days')) as week_cost
    ''').fetchone()

    return render_template('admin_ai.html',
                           settings=settings,
                           prompts=prompts,
                           shows=shows,
                           summary_counts=summary_counts,
                           logs=logs,
                           log_stats=log_stats)


@admin_bp.route('/ai/save-settings', methods=['POST'])
@login_required
@admin_required
def ai_save_settings():
    """Save AI/LLM provider settings."""
    fields = ['preferred_llm_provider', 'ollama_url', 'ollama_model_name',
              'openai_api_key', 'openai_model_name',
              'openrouter_api_key', 'openrouter_model_name']

    for field in fields:
        value = request.form.get(field, '').strip()
        set_setting(field, value if value else None)

    flash('AI settings saved successfully.', 'success')
    return redirect(url_for('admin.ai_settings'))


@admin_bp.route('/ai/save-prompt', methods=['POST'])
@login_required
@admin_required
def ai_save_prompt():
    """Save an edited prompt template."""
    prompt_key = request.form.get('prompt_key')
    prompt_template = request.form.get('prompt_template', '').strip()

    if not prompt_key or not prompt_template:
        flash('Prompt key and template are required.', 'error')
        return redirect(url_for('admin.ai_settings'))

    db = get_db()
    db.execute(
        'UPDATE llm_prompts SET prompt_template = ?, updated_at = CURRENT_TIMESTAMP WHERE prompt_key = ?',
        (prompt_template, prompt_key)
    )
    db.commit()
    flash(f'Prompt "{prompt_key}" saved.', 'success')
    return redirect(url_for('admin.ai_settings'))


@admin_bp.route('/ai/reset-prompt', methods=['POST'])
@login_required
@admin_required
def ai_reset_prompt():
    """Reset a prompt to its default template."""
    data = request.json
    prompt_key = data.get('prompt_key')

    defaults = {
        "episode_summary": """Write a concise summary (2-3 paragraphs) of {show_title} Season {season_number}, Episode {episode_number}: "{episode_title}".

Here is the episode description for context: {episode_overview}

Focus on the key plot developments, character moments, and how this episode connects to the larger season arc. Write in past tense as a recap for someone who has already watched the episode. Do not include spoiler warnings.""",
        "season_recap": """Write a comprehensive season recap (3-5 paragraphs) for {show_title} Season {season_number}.

Here are summaries of the individual episodes for reference:
{episode_summaries}

Provide an engaging recap that covers the major storylines, character development, and key turning points of the season. Write in past tense as a recap for someone who has already watched the season. End with how the season concludes and any cliffhangers or setups for the next season. Do not include spoiler warnings."""
    }

    if prompt_key not in defaults:
        return jsonify({'success': False, 'error': 'Unknown prompt key'})

    db = get_db()
    db.execute(
        'UPDATE llm_prompts SET prompt_template = ?, updated_at = CURRENT_TIMESTAMP WHERE prompt_key = ?',
        (defaults[prompt_key], prompt_key)
    )
    db.commit()
    return jsonify({'success': True})


@admin_bp.route('/ai/test-connection', methods=['POST'])
@login_required
@admin_required
def ai_test_connection():
    """Test connection to an LLM provider."""
    data = request.json
    service = data.get('service')

    if service == 'ollama':
        url = data.get('url', '').strip()
        if not url:
            return jsonify({'success': False, 'error': 'URL is required'})
        try:
            resp = requests.get(url.rstrip('/') + '/api/tags', timeout=10)
            if resp.status_code == 200:
                models = [m.get('name') for m in resp.json().get('models', []) if m.get('name')]
                return jsonify({'success': True, 'models': models})
            return jsonify({'success': False, 'error': f'HTTP {resp.status_code}'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})

    elif service == 'openai':
        api_key = data.get('api_key', '').strip()
        if not api_key:
            return jsonify({'success': False, 'error': 'API key is required'})
        try:
            client = OpenAI(api_key=api_key)
            client.models.list()
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})

    elif service == 'openrouter':
        api_key = data.get('api_key', '').strip()
        if not api_key:
            return jsonify({'success': False, 'error': 'API key is required'})
        try:
            resp = requests.get('https://openrouter.ai/api/v1/models',
                                headers={'Authorization': f'Bearer {api_key}'}, timeout=10)
            if resp.status_code == 200:
                return jsonify({'success': True})
            return jsonify({'success': False, 'error': f'HTTP {resp.status_code}'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})

    return jsonify({'success': False, 'error': 'Unknown service'})


@admin_bp.route('/ai/generate', methods=['POST'])
@login_required
@admin_required
def ai_generate():
    """Generate AI summaries for a show's episodes and seasons."""
    import time as time_mod
    from ..llm_services import generate_episode_summary, generate_season_recap

    data = request.json
    show_id = data.get('show_id')
    target_season = data.get('season_number')

    if not show_id:
        return jsonify({'success': False, 'error': 'show_id is required'})

    db = get_db()
    show = db.execute('SELECT * FROM sonarr_shows WHERE id = ?', (show_id,)).fetchone()
    if not show:
        return jsonify({'success': False, 'error': 'Show not found'})

    # Get the active provider info for logging
    provider = get_setting('preferred_llm_provider')
    if not provider:
        return jsonify({'success': False, 'error': 'No LLM provider configured. Set one in Settings tab.'})

    model_setting = f'{provider}_model_name'
    model = get_setting(model_setting) or 'default'

    log_lines = []
    episode_count = 0
    season_count = 0

    # Get seasons (skip season 0 = specials)
    if target_season:
        seasons = db.execute(
            'SELECT * FROM sonarr_seasons WHERE show_id = ? AND season_number = ?',
            (show_id, target_season)
        ).fetchall()
    else:
        seasons = db.execute(
            'SELECT * FROM sonarr_seasons WHERE show_id = ? AND season_number > 0 ORDER BY season_number',
            (show_id,)
        ).fetchall()

    for season in seasons:
        sn = season['season_number']

        # Get episodes for this season
        episodes = db.execute('''
            SELECT * FROM sonarr_episodes
            WHERE show_id = ? AND season_number = ? AND episode_number > 0
            ORDER BY episode_number
        ''', (show_id, sn)).fetchall()

        if not episodes:
            log_lines.append(f"Season {sn}: No episodes found, skipping.")
            continue

        # Generate episode summaries
        episode_summary_texts = []
        for ep in episodes:
            # Check if summary already exists
            existing = db.execute(
                'SELECT id FROM show_summaries WHERE show_id = ? AND season_number = ? AND episode_number = ?',
                (show_id, sn, ep['episode_number'])
            ).fetchone()

            if existing:
                # Load existing for season recap context
                existing_text = db.execute(
                    'SELECT summary_text FROM show_summaries WHERE id = ?', (existing['id'],)
                ).fetchone()
                if existing_text:
                    episode_summary_texts.append(f"E{ep['episode_number']}: {existing_text['summary_text']}")
                log_lines.append(f"S{sn}E{ep['episode_number']}: Already exists, skipping.")
                continue

            log_lines.append(f"S{sn}E{ep['episode_number']}: Generating summary for \"{ep['title']}\"...")
            summary, error = generate_episode_summary(
                show['title'], sn, ep['episode_number'],
                ep['title'], ep['overview']
            )

            if error:
                log_lines.append(f"  Error: {error}")
                continue

            # Save to database
            db.execute(
                '''INSERT INTO show_summaries (show_id, season_number, episode_number, summary_text, provider, model, prompt_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (show_id, sn, ep['episode_number'], summary, provider, model, 'episode_summary')
            )
            db.commit()
            episode_count += 1
            episode_summary_texts.append(f"E{ep['episode_number']}: {summary}")
            log_lines.append(f"  Done ({len(summary)} chars)")

            # Small delay to avoid rate limits
            time_mod.sleep(1)

        # Generate season recap if we have episode summaries
        existing_recap = db.execute(
            'SELECT id FROM show_summaries WHERE show_id = ? AND season_number = ? AND episode_number IS NULL',
            (show_id, sn)
        ).fetchone()

        if existing_recap:
            log_lines.append(f"Season {sn} recap: Already exists, skipping.")
            continue

        if episode_summary_texts:
            log_lines.append(f"Season {sn}: Generating season recap...")
            recap_text = "\n\n".join(episode_summary_texts)
            recap, error = generate_season_recap(show['title'], sn, recap_text)

            if error:
                log_lines.append(f"  Error: {error}")
            else:
                db.execute(
                    '''INSERT INTO show_summaries (show_id, season_number, episode_number, summary_text, provider, model, prompt_key)
                       VALUES (?, ?, NULL, ?, ?, ?, ?)''',
                    (show_id, sn, recap, provider, model, 'season_recap')
                )
                db.commit()
                season_count += 1
                log_lines.append(f"  Done ({len(recap)} chars)")
                time_mod.sleep(1)

    return jsonify({
        'success': True,
        'log': "\n".join(log_lines),
        'episode_count': episode_count,
        'season_count': season_count
    })


@admin_bp.route('/ai/delete-summaries', methods=['POST'])
@login_required
@admin_required
def ai_delete_summaries():
    """Delete all AI summaries for a show."""
    data = request.json
    show_id = data.get('show_id')
    if not show_id:
        return jsonify({'success': False, 'error': 'show_id required'})

    db = get_db()
    db.execute('DELETE FROM show_summaries WHERE show_id = ?', (show_id,))
    db.commit()
    return jsonify({'success': True})


@admin_bp.route('/ai/logs-data')
@login_required
@admin_required
def ai_logs_data():
    """Return API usage logs as JSON for AJAX refresh."""
    provider_filter = request.args.get('provider', '')
    db = get_db()

    if provider_filter:
        logs = db.execute(
            'SELECT * FROM api_usage WHERE provider = ? ORDER BY timestamp DESC LIMIT 100',
            (provider_filter,)
        ).fetchall()
    else:
        logs = db.execute('SELECT * FROM api_usage ORDER BY timestamp DESC LIMIT 100').fetchall()

    return jsonify({
        'logs': [dict(row) for row in logs]
    })


# ============================================================================
# RECAP PIPELINE (subtitle-first, local model)
# ============================================================================

@admin_bp.route('/recap-pipeline')
@login_required
@admin_required
def recap_pipeline():
    """Renders the subtitle-first recap pipeline admin page."""
    from ..recap_pipeline import get_recap_pipeline_status

    db = get_db()
    status = get_recap_pipeline_status()

    # List all shows that have subtitles available
    shows_with_subs = db.execute("""
        SELECT s.tmdb_id, s.title,
               COUNT(DISTINCT sub.season_number || '-' || sub.episode_number) AS subtitle_episode_count
        FROM sonarr_shows s
        JOIN subtitles sub ON sub.show_tmdb_id = s.tmdb_id
        GROUP BY s.tmdb_id, s.title
        ORDER BY s.title
    """).fetchall()

    # Recent recaps
    recent_season_recaps = db.execute("""
        SELECT sr.id, s.title AS show_title, sr.season_number,
               sr.local_model, sr.openai_model_version, sr.status,
               sr.spoiler_cutoff_episode, sr.runtime_seconds,
               sr.openai_cost_usd, sr.updated_at,
               sr.error_message
        FROM season_recaps sr
        JOIN sonarr_shows s ON s.tmdb_id = sr.show_tmdb_id
        ORDER BY sr.updated_at DESC
        LIMIT 50
    """).fetchall()

    recent_episode_recaps = db.execute("""
        SELECT er.id, s.title AS show_title, er.season_number, er.episode_number,
               er.local_model, er.status, er.runtime_seconds, er.updated_at,
               er.error_message
        FROM episode_recaps er
        JOIN sonarr_shows s ON s.tmdb_id = er.show_tmdb_id
        ORDER BY er.updated_at DESC
        LIMIT 100
    """).fetchall()

    return render_template(
        'admin_recap_pipeline.html',
        title='Recap Pipeline',
        status=status,
        shows_with_subs=shows_with_subs,
        recent_season_recaps=recent_season_recaps,
        recent_episode_recaps=recent_episode_recaps,
    )


@admin_bp.route('/recap-pipeline/generate-season', methods=['POST'])
@login_required
@admin_required
def recap_pipeline_generate_season():
    """Trigger subtitle-first season recap generation."""
    from ..recap_pipeline import generate_season_recap

    tmdb_id = request.form.get('tmdb_id', type=int)
    season_number = request.form.get('season_number', type=int)
    spoiler_cutoff = request.form.get('spoiler_cutoff', type=int) or None
    local_model = request.form.get('local_model', 'gpt-oss:20b').strip() or 'gpt-oss:20b'
    openai_polish = bool(request.form.get('openai_polish'))
    force = bool(request.form.get('force'))

    if not tmdb_id or not season_number:
        flash('tmdb_id and season_number are required.', 'danger')
        return redirect(url_for('admin.recap_pipeline'))

    current_app.logger.info(
        f"Admin triggered season recap: tmdb={tmdb_id} S{season_number} "
        f"model={local_model} polish={openai_polish} force={force}"
    )

    recap, error = generate_season_recap(
        tmdb_id, season_number,
        spoiler_cutoff=spoiler_cutoff,
        local_model=local_model,
        openai_polish=openai_polish,
        force=force,
    )

    if error:
        flash(f'Season recap generation failed: {error}', 'danger')
    else:
        flash(f'Season recap generated successfully for season {season_number}.', 'success')

    return redirect(url_for('admin.recap_pipeline'))


@admin_bp.route('/recap-pipeline/generate-episode', methods=['POST'])
@login_required
@admin_required
def recap_pipeline_generate_episode():
    """Trigger subtitle-first episode recap generation."""
    from ..recap_pipeline import generate_episode_recap

    tmdb_id = request.form.get('tmdb_id', type=int)
    season_number = request.form.get('season_number', type=int)
    episode_number = request.form.get('episode_number', type=int)
    spoiler_cutoff = request.form.get('spoiler_cutoff', type=int) or None
    local_model = request.form.get('local_model', 'gpt-oss:20b').strip() or 'gpt-oss:20b'
    force = bool(request.form.get('force'))

    if not tmdb_id or not season_number or not episode_number:
        flash('tmdb_id, season_number, and episode_number are required.', 'danger')
        return redirect(url_for('admin.recap_pipeline'))

    current_app.logger.info(
        f"Admin triggered episode recap: tmdb={tmdb_id} S{season_number}E{episode_number} "
        f"model={local_model} force={force}"
    )

    summary, error = generate_episode_recap(
        tmdb_id, season_number, episode_number,
        spoiler_cutoff=spoiler_cutoff,
        local_model=local_model,
        force=force,
    )

    if error:
        flash(f'Episode recap generation failed: {error}', 'danger')
    else:
        flash(
            f'Episode recap generated for S{season_number:02d}E{episode_number:02d}.',
            'success',
        )

    return redirect(url_for('admin.recap_pipeline'))


@admin_bp.route('/recap-pipeline/season/<int:recap_id>', methods=['GET'])
@login_required
@admin_required
def recap_pipeline_view_season(recap_id):
    """View a single season recap."""
    db = get_db()
    row = db.execute("""
        SELECT sr.*, s.title AS show_title
        FROM season_recaps sr
        JOIN sonarr_shows s ON s.tmdb_id = sr.show_tmdb_id
        WHERE sr.id = ?
    """, (recap_id,)).fetchone()
    if not row:
        abort(404)
    return render_template(
        'admin_recap_pipeline.html',
        title='View Season Recap',
        view_recap=dict(row),
        status={}, shows_with_subs=[],
        recent_season_recaps=[], recent_episode_recaps=[],
    )
