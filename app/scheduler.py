"""
Background scheduler for periodic sync and summary generation tasks.

This module uses APScheduler to run periodic tasks:
- Tautulli watch history sync (configurable, default daily 3 AM)
- Sonarr library sync (configurable, default Sundays 4 AM)
- Radarr library sync (configurable, default Sundays 5 AM)
- LLM summary generation (configurable quiet hours window)

Schedule times are read from the settings table and can be updated
at runtime via reschedule_jobs().
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

        count = sync_tautulli_watch_history(full_import=False, max_records=500)
        current_app.logger.info(f"Scheduled Tautulli sync completed: {count} new events")

        watch_count = process_activity_log_for_watch_status()
        current_app.logger.info(f"Scheduled watch indicator processing completed: {watch_count} episodes marked as watched")

        try:
            from app.system_logger import syslog, SystemLogger
            syslog.success(SystemLogger.SYNC, f"Scheduled Tautulli sync completed: {count} events, {watch_count} episodes marked", {
                'event_count': count,
                'watch_count': watch_count,
                'type': 'scheduled'
            })
        except Exception:
            pass

    except Exception as e:
        current_app.logger.error(f"Error in scheduled Tautulli sync: {e}", exc_info=True)
        try:
            from app.system_logger import syslog, SystemLogger
            syslog.error(SystemLogger.SYNC, f"Scheduled Tautulli sync failed: {str(e)}", {
                'error': str(e),
                'type': 'scheduled'
            })
        except Exception:
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
        except Exception:
            pass

    except Exception as e:
        current_app.logger.error(f"Error in scheduled Sonarr sync: {e}", exc_info=True)
        try:
            from app.system_logger import syslog, SystemLogger
            syslog.error(SystemLogger.SYNC, f"Scheduled Sonarr sync failed: {str(e)}", {
                'error': str(e),
                'type': 'scheduled'
            })
        except Exception:
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
        except Exception:
            pass

    except Exception as e:
        current_app.logger.error(f"Error in scheduled Radarr sync: {e}", exc_info=True)
        try:
            from app.system_logger import syslog, SystemLogger
            syslog.error(SystemLogger.SYNC, f"Scheduled Radarr sync failed: {str(e)}", {
                'error': str(e),
                'type': 'scheduled'
            })
        except Exception:
            pass

def scheduled_ai_summaries():
    """
    Scheduled AI summary generation.
    Finds shows with upcoming new seasons and generates episode summaries
    and season recaps for completed seasons that don't have them yet.
    Runs weekly on Mondays at 6 AM.
    """
    import time as time_mod
    from app.database import get_db, get_setting
    from app.llm_services import generate_episode_summary, generate_season_recap

    try:
        provider = get_setting('preferred_llm_provider')
        if not provider:
            current_app.logger.info("Scheduled AI summaries: No LLM provider configured, skipping.")
            return

        model = get_setting(f'{provider}_model_name') or 'default'
        db = get_db()

        # Find continuing shows that have episodes with future air dates (upcoming season)
        shows = db.execute('''
            SELECT DISTINCT s.id, s.title, s.season_count
            FROM sonarr_shows s
            JOIN sonarr_episodes e ON s.id = e.show_id
            WHERE s.status = 'continuing'
              AND e.season_number > 0
              AND e.episode_number = 1
              AND e.air_date_utc > DATETIME('now')
              AND e.air_date_utc <= DATETIME('now', '+60 days')
        ''').fetchall()

        if not shows:
            current_app.logger.info("Scheduled AI summaries: No shows with upcoming new seasons found.")
            return

        current_app.logger.info(f"Scheduled AI summaries: Found {len(shows)} shows with upcoming seasons")
        total_episodes = 0
        total_seasons = 0

        for show in shows:
            # Get completed seasons (all episodes have files, not season 0)
            seasons = db.execute('''
                SELECT ss.season_number
                FROM sonarr_seasons ss
                WHERE ss.show_id = ? AND ss.season_number > 0
                  AND ss.episode_file_count > 0
                  AND ss.episode_file_count = ss.episode_count
                ORDER BY ss.season_number
            ''', (show['id'],)).fetchall()

            for season in seasons:
                sn = season['season_number']

                # Check if season recap already exists
                existing_recap = db.execute(
                    'SELECT id FROM show_summaries WHERE show_id = ? AND season_number = ? AND episode_number IS NULL',
                    (show['id'], sn)
                ).fetchone()
                if existing_recap:
                    continue

                # Generate episode summaries for this season
                episodes = db.execute('''
                    SELECT * FROM sonarr_episodes
                    WHERE show_id = ? AND season_number = ? AND episode_number > 0
                    ORDER BY episode_number
                ''', (show['id'], sn)).fetchall()

                episode_texts = []
                for ep in episodes:
                    existing = db.execute(
                        'SELECT summary_text FROM show_summaries WHERE show_id = ? AND season_number = ? AND episode_number = ?',
                        (show['id'], sn, ep['episode_number'])
                    ).fetchone()

                    if existing:
                        episode_texts.append(f"E{ep['episode_number']}: {existing['summary_text']}")
                        continue

                    summary, error = generate_episode_summary(
                        show['title'], sn, ep['episode_number'], ep['title'], ep['overview']
                    )
                    if summary:
                        db.execute(
                            '''INSERT INTO show_summaries (show_id, season_number, episode_number, summary_text, provider, model, prompt_key)
                               VALUES (?, ?, ?, ?, ?, ?, ?)''',
                            (show['id'], sn, ep['episode_number'], summary, provider, model, 'episode_summary')
                        )
                        db.commit()
                        total_episodes += 1
                        episode_texts.append(f"E{ep['episode_number']}: {summary}")
                    time_mod.sleep(2)  # Rate limit

                # Generate season recap
                if episode_texts:
                    recap, error = generate_season_recap(show['title'], sn, "\n\n".join(episode_texts))
                    if recap:
                        db.execute(
                            '''INSERT INTO show_summaries (show_id, season_number, episode_number, summary_text, provider, model, prompt_key)
                               VALUES (?, ?, NULL, ?, ?, ?, ?)''',
                            (show['id'], sn, recap, provider, model, 'season_recap')
                        )
                        db.commit()
                        total_seasons += 1
                    time_mod.sleep(2)

        current_app.logger.info(f"Scheduled AI summaries completed: {total_episodes} episodes, {total_seasons} season recaps")

        try:
            from app.system_logger import syslog, SystemLogger
            syslog.success(SystemLogger.SYNC, f"AI summary generation: {total_episodes} episodes, {total_seasons} seasons", {
                'episode_count': total_episodes,
                'season_count': total_seasons,
                'type': 'scheduled'
            })
        except:
            pass

    except Exception as e:
        current_app.logger.error(f"Error in scheduled AI summaries: {e}", exc_info=True)
        try:
            from app.system_logger import syslog, SystemLogger
            syslog.error(SystemLogger.SYNC, f"Scheduled AI summary generation failed: {str(e)}", {
                'error': str(e),
                'type': 'scheduled'
            })
        except:
            pass


def scheduled_summary_generation():
    """
    Scheduled LLM summary generation task.
    Processes the summary queue within the configured quiet hours window.
    """
    try:
        from app.summary_services import process_summary_queue
        # process_summary_queue needs the app object to create its own context
        # for long-running operations; current_app proxy gives us access
        app = current_app._get_current_object()
        process_summary_queue(app)
    except Exception as e:
        current_app.logger.error(f"Error in scheduled summary generation: {e}", exc_info=True)
        try:
            from app.system_logger import syslog, SystemLogger
            syslog.error(SystemLogger.SYNC, f"Scheduled summary generation failed: {str(e)}", {
                'error': str(e),
                'type': 'scheduled'
            })
        except Exception:
            pass


def _get_schedule_settings(app):
    """Read schedule configuration from database, falling back to defaults."""
    with app.app_context():
        from app.database import get_setting
        return {
            'tautulli_hour': get_setting('schedule_tautulli_hour') or 3,
            'tautulli_minute': get_setting('schedule_tautulli_minute') or 0,
            'sonarr_day': get_setting('schedule_sonarr_day') or 'sun',
            'sonarr_hour': get_setting('schedule_sonarr_hour') or 4,
            'sonarr_minute': get_setting('schedule_sonarr_minute') or 0,
            'radarr_day': get_setting('schedule_radarr_day') or 'sun',
            'radarr_hour': get_setting('schedule_radarr_hour') or 5,
            'radarr_minute': get_setting('schedule_radarr_minute') or 0,
            'summary_start_hour': get_setting('summary_schedule_start_hour') or 2,
            'summary_enabled': get_setting('summary_enabled') or 0,
        }


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

    scheduler = BackgroundScheduler(daemon=True)
    logging.getLogger('apscheduler').setLevel(logging.INFO)

    def wrap_with_context(func):
        """Wrap function to run within Flask app context"""
        def wrapper():
            with app.app_context():
                func()
        return wrapper

    # Read schedule settings from database
    try:
        cfg = _get_schedule_settings(app)
    except Exception as e:
        app.logger.warning(f"Could not read schedule settings, using defaults: {e}")
        cfg = {
            'tautulli_hour': 3, 'tautulli_minute': 0,
            'sonarr_day': 'sun', 'sonarr_hour': 4, 'sonarr_minute': 0,
            'radarr_day': 'sun', 'radarr_hour': 5, 'radarr_minute': 0,
            'summary_start_hour': 2, 'summary_enabled': 0,
        }

    # Daily Tautulli sync
    scheduler.add_job(
        wrap_with_context(scheduled_tautulli_sync),
        'cron',
        hour=int(cfg['tautulli_hour']),
        minute=int(cfg['tautulli_minute']),
        id='tautulli_sync',
        replace_existing=True
    )
    app.logger.info(f"Scheduled Tautulli sync at {cfg['tautulli_hour']}:{cfg['tautulli_minute']:02d}")

    # Weekly Sonarr sync
    scheduler.add_job(
        wrap_with_context(scheduled_sonarr_sync),
        'cron',
        day_of_week=cfg['sonarr_day'],
        hour=int(cfg['sonarr_hour']),
        minute=int(cfg['sonarr_minute']),
        id='sonarr_sync',
        replace_existing=True
    )
    app.logger.info(f"Scheduled Sonarr sync on {cfg['sonarr_day']} at {cfg['sonarr_hour']}:{cfg['sonarr_minute']:02d}")

    # Weekly Radarr sync
    scheduler.add_job(
        wrap_with_context(scheduled_radarr_sync),
        'cron',
        day_of_week=cfg['radarr_day'],
        hour=int(cfg['radarr_hour']),
        minute=int(cfg['radarr_minute']),
        id='radarr_sync',
        replace_existing=True
    )
    app.logger.info(f"Scheduled Radarr sync on {cfg['radarr_day']} at {cfg['radarr_hour']}:{cfg['radarr_minute']:02d}")

    # Summary generation (runs at start of quiet window, self-limits to window)
    scheduler.add_job(
        wrap_with_context(scheduled_summary_generation),
        'cron',
        hour=int(cfg['summary_start_hour']),
        minute=0,
        id='summary_generation',
        replace_existing=True
    )
    status = "enabled" if cfg['summary_enabled'] else "disabled (will check on trigger)"
    app.logger.info(f"Scheduled summary generation at {cfg['summary_start_hour']}:00 ({status})")

    # Weekly AI summary generation on Mondays at 6 AM
    scheduler.add_job(
        wrap_with_context(scheduled_ai_summaries),
        'cron',
        day_of_week='mon',
        hour=6,
        minute=0,
        id='ai_summaries',
        replace_existing=True
    )
    app.logger.info("Scheduled weekly AI summary generation on Mondays at 6:00 AM")

    scheduler.start()
    app.logger.info("Background scheduler started successfully")

    import atexit
    atexit.register(lambda: scheduler.shutdown() if scheduler else None)


def reschedule_jobs(app):
    """
    Update scheduler job times from current database settings.
    Call this after admin saves schedule configuration.
    """
    global scheduler
    if not scheduler:
        app.logger.warning("Scheduler not initialized, cannot reschedule")
        return

    try:
        cfg = _get_schedule_settings(app)
    except Exception as e:
        app.logger.error(f"Failed to read schedule settings for reschedule: {e}")
        return

    try:
        scheduler.reschedule_job(
            'tautulli_sync', trigger='cron',
            hour=int(cfg['tautulli_hour']), minute=int(cfg['tautulli_minute'])
        )
        scheduler.reschedule_job(
            'sonarr_sync', trigger='cron',
            day_of_week=cfg['sonarr_day'],
            hour=int(cfg['sonarr_hour']), minute=int(cfg['sonarr_minute'])
        )
        scheduler.reschedule_job(
            'radarr_sync', trigger='cron',
            day_of_week=cfg['radarr_day'],
            hour=int(cfg['radarr_hour']), minute=int(cfg['radarr_minute'])
        )
        scheduler.reschedule_job(
            'summary_generation', trigger='cron',
            hour=int(cfg['summary_start_hour']), minute=0
        )
        app.logger.info("Scheduler jobs rescheduled successfully")
    except Exception as e:
        app.logger.error(f"Error rescheduling jobs: {e}", exc_info=True)


def shutdown_scheduler():
    """Shutdown the scheduler gracefully"""
    global scheduler
    if scheduler:
        scheduler.shutdown()
        scheduler = None
