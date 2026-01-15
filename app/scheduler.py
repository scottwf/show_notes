"""
Background scheduler for periodic sync tasks.

This module uses APScheduler to run periodic syncs for:
- Tautulli watch history (daily)
- Watch indicator processing (daily after Tautulli sync)
- Sonarr library sync (weekly)
- Radarr library sync (weekly)
"""

from apscheduler.schedulers.background import BackgroundScheduler
from flask import current_app
import logging

# Module-level scheduler instance
scheduler = None

def scheduled_tautulli_sync():
    """
    Scheduled Tautulli sync task.
    Runs daily to fetch recent watch history and process watch indicators.
    """
    from app.utils import sync_tautulli_watch_history, process_activity_log_for_watch_status

    try:
        current_app.logger.info("Starting scheduled Tautulli sync")

        # Sync recent Tautulli history (incremental)
        count = sync_tautulli_watch_history(full_import=False, max_records=500)
        current_app.logger.info(f"Scheduled Tautulli sync completed: {count} new events")

        # Process watch indicators from activity log
        watch_count = process_activity_log_for_watch_status()
        current_app.logger.info(f"Scheduled watch indicator processing completed: {watch_count} episodes marked as watched")

        # Log to system logger if available
        try:
            from app.system_logger import syslog, SystemLogger
            syslog.success(SystemLogger.SYNC, f"Scheduled Tautulli sync completed: {count} events, {watch_count} episodes marked", {
                'event_count': count,
                'watch_count': watch_count,
                'type': 'scheduled'
            })
        except:
            pass

    except Exception as e:
        current_app.logger.error(f"Error in scheduled Tautulli sync: {e}", exc_info=True)
        try:
            from app.system_logger import syslog, SystemLogger
            syslog.error(SystemLogger.SYNC, f"Scheduled Tautulli sync failed: {str(e)}", {
                'error': str(e),
                'type': 'scheduled'
            })
        except:
            pass

def scheduled_sonarr_sync():
    """
    Scheduled Sonarr library sync task.
    Runs weekly to catch any changes missed by webhooks.
    """
    from app.utils import sync_sonarr_library

    try:
        current_app.logger.info("Starting scheduled Sonarr library sync")
        sync_sonarr_library()
        current_app.logger.info("Scheduled Sonarr sync completed")

        try:
            from app.system_logger import syslog, SystemLogger
            syslog.success(SystemLogger.SYNC, "Scheduled Sonarr library sync completed", {
                'type': 'scheduled'
            })
        except:
            pass

    except Exception as e:
        current_app.logger.error(f"Error in scheduled Sonarr sync: {e}", exc_info=True)
        try:
            from app.system_logger import syslog, SystemLogger
            syslog.error(SystemLogger.SYNC, f"Scheduled Sonarr sync failed: {str(e)}", {
                'error': str(e),
                'type': 'scheduled'
            })
        except:
            pass

def scheduled_radarr_sync():
    """
    Scheduled Radarr library sync task.
    Runs weekly to catch any changes missed by webhooks.
    """
    from app.utils import sync_radarr_library

    try:
        current_app.logger.info("Starting scheduled Radarr library sync")
        sync_radarr_library()
        current_app.logger.info("Scheduled Radarr sync completed")

        try:
            from app.system_logger import syslog, SystemLogger
            syslog.success(SystemLogger.SYNC, "Scheduled Radarr library sync completed", {
                'type': 'scheduled'
            })
        except:
            pass

    except Exception as e:
        current_app.logger.error(f"Error in scheduled Radarr sync: {e}", exc_info=True)
        try:
            from app.system_logger import syslog, SystemLogger
            syslog.error(SystemLogger.SYNC, f"Scheduled Radarr sync failed: {str(e)}", {
                'error': str(e),
                'type': 'scheduled'
            })
        except:
            pass

def init_scheduler(app):
    """
    Initialize the background scheduler with the Flask app context.

    Args:
        app: Flask application instance
    """
    global scheduler

    if scheduler is not None:
        app.logger.warning("Scheduler already initialized, skipping")
        return

    # Create background scheduler
    scheduler = BackgroundScheduler(daemon=True)

    # Configure logging for APScheduler
    logging.getLogger('apscheduler').setLevel(logging.INFO)

    # Add jobs with Flask app context
    def wrap_with_context(func):
        """Wrap function to run within Flask app context"""
        def wrapper():
            with app.app_context():
                func()
        return wrapper

    # Daily Tautulli sync at 3 AM
    scheduler.add_job(
        wrap_with_context(scheduled_tautulli_sync),
        'cron',
        hour=3,
        minute=0,
        id='tautulli_sync',
        replace_existing=True
    )
    app.logger.info("Scheduled daily Tautulli sync at 3:00 AM")

    # Weekly Sonarr sync on Sundays at 4 AM
    scheduler.add_job(
        wrap_with_context(scheduled_sonarr_sync),
        'cron',
        day_of_week='sun',
        hour=4,
        minute=0,
        id='sonarr_sync',
        replace_existing=True
    )
    app.logger.info("Scheduled weekly Sonarr sync on Sundays at 4:00 AM")

    # Weekly Radarr sync on Sundays at 5 AM
    scheduler.add_job(
        wrap_with_context(scheduled_radarr_sync),
        'cron',
        day_of_week='sun',
        hour=5,
        minute=0,
        id='radarr_sync',
        replace_existing=True
    )
    app.logger.info("Scheduled weekly Radarr sync on Sundays at 5:00 AM")

    # Start the scheduler
    scheduler.start()
    app.logger.info("Background scheduler started successfully")

    # Register shutdown handler
    import atexit
    atexit.register(lambda: scheduler.shutdown() if scheduler else None)

def shutdown_scheduler():
    """Shutdown the scheduler gracefully"""
    global scheduler
    if scheduler:
        scheduler.shutdown()
        scheduler = None
