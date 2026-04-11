import os
import glob
import time
import secrets
import socket
import requests
from openai import OpenAI
from flask import (
    render_template, request, redirect, url_for, session, jsonify, flash,
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
    convert_utc_to_user_timezone, get_user_timezone,
    get_jellyseer_user_requests,
)
from ...parse_subtitles import process_all_subtitles
from . import admin_bp, admin_required, ADMIN_SEARCHABLE_ROUTES

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

