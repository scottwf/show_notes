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

