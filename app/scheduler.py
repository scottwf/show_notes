import asyncio
import json
import logging # Using standard logging for scheduler-specific logs initially
from flask import current_app # Will be used within app_context

# Assuming _get_service_config_dict might be moved or duplicated here for scheduler's use
# For now, we'll define it here. If it exists centrally, we'd import it.
# Helper function to get service configuration
def _get_service_config_dict_scheduler(service_name_lower):
    # This function needs to run within an app context to use get_setting
    from app.database import get_setting # Import here to avoid circular dependency if scheduler is imported by __init__

    config = {}
    config['url'] = get_setting(f"{service_name_lower}_url")
    config['api_key'] = get_setting(f"{service_name_lower}_api_key")

    if service_name_lower == 'plex':
        config['token'] = get_setting("plex_token")
        # current_app.logger.info(f"Plex config for scheduler: {config}") # Debug logging

    if not config.get('url'):
        # Use current_app.logger if available (i.e., if called within app context)
        # Otherwise, use a standard logger for scheduler setup phase.
        logger = current_app.logger if current_app else logging.getLogger(__name__)
        logger.warning(f"URL for {service_name_lower} not found in settings. Skipping in scheduler.")
        return None
    return config

async def check_all_services_status(app_instance):
    """
    Checks the status of all configured services and updates the database.
    This function is designed to be called by APScheduler and needs the Flask app instance
    to correctly establish an application context for database operations.
    """
    logger = app_instance.logger # Use Flask app's logger

    logger.info("Scheduler job 'check_all_services_status' started.")

    # Import services and DB functions here, inside the app_context if necessary,
    # or ensure they are safe to import at module level.
    from app.services.status_checker import PlexChecker, SonarrChecker, RadarrChecker, BazarrChecker
    from app.database import get_db

    services_to_check = {
        'plex': PlexChecker,
        'sonarr': SonarrChecker,
        'radarr': RadarrChecker,
        'bazarr': BazarrChecker
    }

    with app_instance.app_context():
        for service_name_lower, CheckerClass in services_to_check.items():
            logger.debug(f"Scheduler checking service: {service_name_lower}")
            config = _get_service_config_dict_scheduler(service_name_lower)

            if not config:
                logger.info(f"Service {service_name_lower} is not configured. Skipping check.")
                continue

            checker = CheckerClass(config)

            try:
                result = await checker.check_status()
                details_json = json.dumps(result.get('details', {}))

                db = get_db() # get_db() must be called within app_context
                db.execute(
                    """
                    INSERT OR REPLACE INTO service_status
                    (service_name, status, last_checked, response_time, version, details)
                    VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?, ?)
                    """,
                    (
                        result.get('name'),
                        result.get('status'),
                        result.get('response_time'),
                        result.get('version'),
                        details_json
                    )
                )
                db.commit()
                logger.info(f"Successfully checked and updated status for {result.get('name')}: {result.get('status')}, version {result.get('version')}, response_time {result.get('response_time')}ms.")

            except Exception as e:
                logger.error(f"Error checking status for {service_name_lower}: {e}", exc_info=True)
                # Optionally, update the database with an error status
                try:
                    db = get_db()
                    error_details = json.dumps({'error': str(e)})
                    db.execute(
                        """
                        INSERT OR REPLACE INTO service_status
                        (service_name, status, last_checked, response_time, version, details)
                        VALUES (?, 'offline', CURRENT_TIMESTAMP, 0, 'N/A', ?)
                        """,
                        (service_name_lower.capitalize(), error_details) # Use service_name_lower.capitalize() as fallback name
                    )
                    db.commit()
                    logger.info(f"Stored error status for {service_name_lower} in database.")
                except Exception as db_e:
                    logger.error(f"Failed to store error status for {service_name_lower} in DB: {db_e}", exc_info=True)

    logger.info("Scheduler job 'check_all_services_status' finished.")

# Example of how to initialize scheduler (this part will be in __init__.py or run.py)
# from apscheduler.schedulers.asyncio import AsyncIOScheduler
# scheduler = AsyncIOScheduler()

# def init_scheduler(app):
#     scheduler.add_job(
#         check_all_services_status,
#         'interval',
#         minutes=5,
#         id='check_services_job',
#         args=[app] # Pass the Flask app instance here
#     )
#     scheduler.start()
#     # Setup shutdown
#     import atexit
#     atexit.register(lambda: scheduler.shutdown())

# Note: The _get_service_config_dict_scheduler is defined here for clarity.
# In a larger application, this helper might be better placed in app.database or app.utils
# to be easily accessible by both admin_api.py and scheduler.py without duplication,
# ensuring it's always used within an app context.
# For now, this duplication is accepted for this subtask.
# The direct import of get_setting inside the function is a way to manage its dependency on app_context.
# If app.scheduler is imported by app.__init__ before app is fully created, top-level calls
# to get_setting would fail.
