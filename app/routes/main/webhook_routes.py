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

@main_bp.route('/plex/webhook', methods=['POST'])
def plex_webhook():
    """
    Handles incoming webhook events from a Plex Media Server.

    This endpoint is designed to receive POST requests from Plex. It parses the
    webhook payload for media events (play, pause, stop, scrobble) and logs the
    relevant details into the `plex_activity_log` table. This log is the primary
    source of data for the user-facing homepage.

    It validates the webhook secret if one is configured in the settings to ensure
    the request is coming from the configured Plex server.

    Returns:
        A JSON response indicating success or an error, along with an appropriate
        HTTP status code.
    """
    try:
        if request.is_json:
            payload = request.get_json()
        else:
            payload = json.loads(request.form.get('payload'))
        
        current_app.logger.info(f"Webhook payload: {json.dumps(payload, indent=2)}")
        
        global last_plex_event
        last_plex_event = payload

        event_type = payload.get('event')
        activity_event_types = ['media.play', 'media.pause', 'media.resume', 'media.stop', 'media.scrobble']

        if event_type in activity_event_types:
            db = database.get_db()
            metadata = payload.get('Metadata', {})
            account = payload.get('Account', {})
            player = payload.get('Player', {})

            # Skip trailers and short content (less than 10 minutes)
            duration_ms = metadata.get('duration', 0)
            if duration_ms and duration_ms < 600000:  # 10 minutes in milliseconds
                current_app.logger.info(f"Skipping short content (likely trailer): '{metadata.get('title')}' ({duration_ms}ms)")
                return jsonify({'status': 'skipped', 'reason': 'trailer or short content'}), 200

            tmdb_id = None
            tvdb_id = None
            guids = metadata.get('Guid')
            if isinstance(guids, list):
                for guid_item in guids:
                    guid_str = guid_item.get('id', '')
                    if guid_str.startswith('tmdb://'):
                        try:
                            tmdb_id = int(guid_str.split('//')[1])
                        except Exception:
                            tmdb_id = None
                    if guid_str.startswith('tvdb://'):
                        try:
                            tvdb_id = int(guid_str.split('//')[1])
                        except Exception:
                            tvdb_id = None
            # Fallback: try to get TVDB ID from grandparentRatingKey if not found
            if not tvdb_id:
                try:
                    tvdb_id = int(metadata.get('grandparentRatingKey'))
                except Exception:
                    tvdb_id = None

            # Get the show's TMDB ID from our database using TVDB ID or title matching
            show_tmdb_id = None
            if tvdb_id:
                show_record = db.execute('SELECT tmdb_id FROM sonarr_shows WHERE tvdb_id = ?', (tvdb_id,)).fetchone()
                if show_record:
                    show_tmdb_id = show_record['tmdb_id']

            # Fallback: Try to match by show title if TVDB lookup failed
            if not show_tmdb_id and metadata.get('grandparentTitle'):
                show_title = metadata.get('grandparentTitle')
                show_record = db.execute(
                    'SELECT tmdb_id FROM sonarr_shows WHERE LOWER(title) = LOWER(?)',
                    (show_title,)
                ).fetchone()
                if show_record:
                    show_tmdb_id = show_record['tmdb_id']
                    current_app.logger.info(f"Matched show '{show_title}' by title (TMDB: {show_tmdb_id})")

            season_num = metadata.get('parentIndex')
            episode_num = metadata.get('index')
            season_episode_str = None
            if metadata.get('type') == 'episode':
                if season_num is not None and episode_num is not None:
                    season_episode_str = f"S{str(season_num).zfill(2)}E{str(episode_num).zfill(2)}"

            # Check for duplicate event (Plex sometimes sends webhooks twice)
            # Use session_key + event_type + rating_key within a time window
            # Don't include view_offset as it can legitimately change during playback
            session_key = metadata.get('sessionKey')
            rating_key = metadata.get('ratingKey')
            view_offset = metadata.get('viewOffset')

            # Look for a recent duplicate (within last 10 seconds)
            import datetime
            ten_seconds_ago = datetime.datetime.now().timestamp() - 10

            duplicate_check = db.execute('''
                SELECT id FROM plex_activity_log
                WHERE session_key = ?
                  AND event_type = ?
                  AND rating_key = ?
                  AND event_timestamp >= datetime(?, 'unixepoch')
                LIMIT 1
            ''', (session_key, event_type, rating_key, ten_seconds_ago)).fetchone()

            if duplicate_check:
                current_app.logger.info(f"Skipping duplicate event '{event_type}' for '{metadata.get('title')}'")
                return jsonify({'status': 'skipped', 'reason': 'duplicate event'}), 200

            sql_insert = """
                INSERT INTO plex_activity_log (
                    event_type, plex_username, player_title, player_uuid, session_key,
                    rating_key, parent_rating_key, grandparent_rating_key, media_type,
                    title, show_title, season_episode, view_offset_ms, duration_ms, tmdb_id, raw_payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            params = (
                event_type, account.get('title'), player.get('title'), player.get('uuid'), session_key,
                metadata.get('ratingKey'), metadata.get('parentRatingKey'), metadata.get('grandparentRatingKey'), metadata.get('type'),
                metadata.get('title'), metadata.get('grandparentTitle'), season_episode_str, view_offset,
                metadata.get('duration'), show_tmdb_id, json.dumps(payload)
            )
            db.execute(sql_insert, params)
            db.commit()
            current_app.logger.info(f"Logged event '{event_type}' for '{metadata.get('title')}' to plex_activity_log.")

            # Update user watch statistics for stop/scrobble events
            if event_type in ['media.stop', 'media.scrobble']:
                plex_username = account.get('title')
                if plex_username:
                    user = db.execute('SELECT id FROM users WHERE plex_username = ?', (plex_username,)).fetchone()
                    if user:
                        try:
                            today = datetime.date.today()
                            _update_daily_statistics(user['id'], today)
                            _update_watch_streak(user['id'])
                            current_app.logger.info(f"Updated watch statistics for user {user['id']}")
                        except Exception as stats_error:
                            current_app.logger.error(f"Error updating watch statistics: {stats_error}", exc_info=True)

                        # Update episode watch progress for episodes
                        if metadata.get('type') == 'episode':
                            try:
                                view_offset_ms = metadata.get('viewOffset', 0)
                                duration_ms = metadata.get('duration', 0)
                                watch_percentage = (view_offset_ms / duration_ms * 100) if duration_ms > 0 else 0

                                # Mark as watched if:
                                # 1. It's a scrobble event (Plex sends this when >= 90% watched), OR
                                # 2. Watch percentage >= 95%
                                should_mark_watched = (event_type == 'media.scrobble' or watch_percentage >= 95)

                                if should_mark_watched:
                                    # Find the episode in our database
                                    if show_tmdb_id and season_num is not None and episode_num is not None:
                                        # Get the show's internal ID
                                        show_row = db.execute('SELECT id FROM sonarr_shows WHERE tmdb_id = ?', (show_tmdb_id,)).fetchone()
                                        if show_row:
                                            show_id = show_row['id']
                                            # Get the episode's internal ID
                                            episode_row = db.execute('''
                                                SELECT e.id
                                                FROM sonarr_episodes e
                                                JOIN sonarr_seasons s ON e.season_id = s.id
                                                WHERE s.show_id = ? AND s.season_number = ? AND e.episode_number = ?
                                            ''', (show_id, season_num, episode_num)).fetchone()

                                            if episode_row:
                                                episode_id = episode_row['id']

                                                # Insert or update episode progress
                                                db.execute('''
                                                    INSERT INTO user_episode_progress (
                                                        user_id, episode_id, show_id, season_number, episode_number,
                                                        is_watched, watch_count, last_watched_at, marked_manually
                                                    )
                                                    VALUES (?, ?, ?, ?, ?, 1, 1, CURRENT_TIMESTAMP, 0)
                                                    ON CONFLICT (user_id, episode_id) DO UPDATE SET
                                                        is_watched = 1,
                                                        watch_count = watch_count + 1,
                                                        last_watched_at = CURRENT_TIMESTAMP,
                                                        updated_at = CURRENT_TIMESTAMP
                                                ''', (user['id'], episode_id, show_id, season_num, episode_num))
                                                db.commit()

                                                # Update show completion
                                                _calculate_show_completion(user['id'], show_id)

                                                current_app.logger.info(f"Marked episode {season_episode_str} as watched for user {user['id']}")
                                            else:
                                                current_app.logger.warning(f"Episode not found in database: show_id={show_id}, S{season_num}E{episode_num}")
                                        else:
                                            current_app.logger.warning(f"Show not found in database with TMDB ID: {show_tmdb_id}")
                            except Exception as progress_error:
                                current_app.logger.error(f"Error updating episode progress: {progress_error}", exc_info=True)

            # --- Store episode character data if available ---
            if metadata.get('type') == 'episode' and 'Role' in metadata:
                episode_rating_key = metadata.get('ratingKey')

                # --- Correctly identify the show's TMDB ID ---
                show_tvdb_id_from_plex = None
                try:
                    show_tvdb_id_from_plex = int(metadata.get('grandparentRatingKey'))
                except (ValueError, TypeError):
                    current_app.logger.warning(f"Could not parse grandparentRatingKey: {metadata.get('grandparentRatingKey')}")

                correct_show_tmdb_id = None
                if show_tvdb_id_from_plex:
                    show_record = db.execute('SELECT tmdb_id FROM sonarr_shows WHERE tvdb_id = ?', (show_tvdb_id_from_plex,)).fetchone()
                    if show_record:
                        correct_show_tmdb_id = show_record['tmdb_id']
                    else:
                        current_app.logger.warning(f"Could not find show in DB with TVDB ID: {show_tvdb_id_from_plex}")

                if not correct_show_tmdb_id:
                    # Fallback to the tmdb_id from the episode's own GUID if show lookup fails
                    correct_show_tmdb_id = tmdb_id
                    current_app.logger.warning(f"Falling back to using episode's TMDB ID ({tmdb_id}) for show, as show lookup failed.")


                # Remove old character rows for this episode
                db.execute('DELETE FROM episode_characters WHERE episode_rating_key = ?', (episode_rating_key,))
                roles = metadata['Role']
                for role in roles:
                    db.execute(
                        'INSERT INTO episode_characters (show_tmdb_id, show_tvdb_id, season_number, episode_number, episode_rating_key, character_name, actor_name, actor_id, actor_thumb) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (
                            correct_show_tmdb_id, # Use the corrected show TMDB ID
                            show_tvdb_id_from_plex, # Use the show's TVDB ID
                            season_num,
                            episode_num,
                            episode_rating_key,
                            role.get('role'),
                            role.get('tag'),
                            role.get('id'),
                            role.get('thumb')
                        )
                    )
                db.commit()
                current_app.logger.info(f"Stored {len(roles)} episode characters for episode {episode_rating_key} (S{season_num}E{episode_num}) with correct show TMDB ID {correct_show_tmdb_id}")
        
        return '', 200
    except Exception as e:
        current_app.logger.error(f"Error processing Plex webhook: {e}", exc_info=True)
        return 'error', 400


@main_bp.route('/sonarr/webhook', methods=['POST'])
def sonarr_webhook():
    """
    Handles incoming webhook events from Sonarr.

    This endpoint receives webhook notifications from Sonarr when shows, seasons,
    or episodes are added, updated, or removed. It automatically triggers a
    library sync to keep the ShowNotes database up to date.

    Supported events:
    - Download: When episodes are downloaded
    - Series: When series are added/updated
    - Episode: When episodes are added/updated
    - Rename: When files are renamed

    Returns:
        A JSON response indicating success or an error.
    """
    from app.system_logger import syslog, SystemLogger

    current_app.logger.info("Sonarr webhook received.")
    try:
        if request.is_json:
            payload = request.get_json()
        else:
            payload = json.loads(request.form.get('payload', '{}'))

        current_app.logger.info(f"Sonarr webhook received: {json.dumps(payload, indent=2)}")

        event_type = payload.get('eventType')
        series_title = payload.get('series', {}).get('title', 'Unknown')

        # Log webhook receipt
        syslog.info(SystemLogger.WEBHOOK, f"Sonarr webhook received: {event_type}", {
            'event_type': event_type,
            'series': series_title
        })
        
        # Record webhook activity in database
        try:
            db = database.get_db()
            payload_summary = f"Event: {event_type}"
            if event_type == 'Download' and payload.get('series'):
                payload_summary += f" - {payload['series'].get('title', 'Unknown')}"
            elif event_type == 'Series' and payload.get('series'):
                payload_summary += f" - {payload['series'].get('title', 'Unknown')}"
            
            db.execute(
                'INSERT INTO webhook_activity (service_name, event_type, payload_summary) VALUES (?, ?, ?)',
                ('sonarr', event_type, payload_summary)
            )
            db.commit()
        except Exception as e:
            current_app.logger.error(f"Failed to record Sonarr webhook activity: {e}")
        
        # Events that should trigger a library sync
        sync_events = [
            'Download',           # Episode downloaded
            'Series',             # Series added/updated (generic)
            'SeriesAdd',          # Series added (Sonarr v3+)
            'SeriesDelete',       # Series deleted
            'Episode',            # Episode added/updated
            'EpisodeFileDelete',  # Episode file deleted
            'Rename',             # Files renamed
            'Delete',             # Files deleted
            'Health',             # Health check (good for periodic syncs)
            'Test'                # Test event
        ]
        
        run_full_sync = False

        if event_type == 'Download':
            current_app.logger.info(f"Sonarr webhook event 'Download' detected, triggering targeted episode update.")
            try:
                # Extract necessary info from the payload
                series_id = payload.get('series', {}).get('id')
                series_title = payload.get('series', {}).get('title', 'Unknown Show')
                episode_ids = [ep.get('id') for ep in payload.get('episodes', []) if ep.get('id') is not None]
                # Some Sonarr payload variants send a single `episode` object instead of `episodes[]`
                single_episode_id = payload.get('episode', {}).get('id')
                if single_episode_id is not None and single_episode_id not in episode_ids:
                    episode_ids.append(single_episode_id)
                episodes_info = payload.get('episodes', [])
                if not episodes_info and payload.get('episode'):
                    episodes_info = [payload.get('episode')]

                if not series_id or not episode_ids:
                    current_app.logger.warning("Webhook 'Download' event missing series_id or episode_ids; triggering full library sync fallback.")
                    # Fall back to full sync so availability still updates even with partial webhook payloads.
                    run_full_sync = True
                else:
                    from ..utils import update_sonarr_episode
                    import threading

                    # Optimistically mark downloaded episodes as available immediately.
                    # Sonarr's episode endpoint can briefly lag right after a Download event.
                    try:
                        db_local = database.get_db()
                        show_local = db_local.execute(
                            'SELECT id FROM sonarr_shows WHERE sonarr_id = ?',
                            (series_id,)
                        ).fetchone()
                        if show_local:
                            show_local_id = show_local['id']
                            marked_count = 0
                            for ep in episodes_info:
                                season_num = ep.get('seasonNumber')
                                episode_num = ep.get('episodeNumber')
                                if season_num is None or episode_num is None:
                                    continue
                                # Look up season_id first, then update by season_id + episode_number
                                # This is more reliable than show_id + season_number which may be NULL
                                # for episodes created by the full sync
                                season_local = db_local.execute(
                                    'SELECT id FROM sonarr_seasons WHERE show_id = ? AND season_number = ?',
                                    (show_local_id, season_num)
                                ).fetchone()
                                if not season_local:
                                    current_app.logger.warning(
                                        f"No season row found for show_id={show_local_id} season={season_num} during optimistic mark"
                                    )
                                    continue
                                result = db_local.execute(
                                    '''
                                    UPDATE sonarr_episodes
                                    SET has_file = 1
                                    WHERE season_id = ? AND episode_number = ?
                                    ''',
                                    (season_local['id'], episode_num)
                                )
                                marked_count += result.rowcount
                            if marked_count:
                                db_local.commit()
                                current_app.logger.info(
                                    f"Marked {marked_count} episode row(s) available immediately for series {series_id} from Download webhook."
                                )
                            else:
                                current_app.logger.warning(
                                    f"Optimistic mark matched 0 episodes for series {series_id}. "
                                    f"Episodes may not exist in DB yet — background sync will create them."
                                )
                    except Exception as mark_err:
                        current_app.logger.warning(f"Immediate has_file mark from Download webhook failed: {mark_err}")

                    # Capture the real application object to pass to the thread
                    app_instance = current_app._get_current_object()

                    def sync_in_background(app):
                        with app.app_context():
                            from app.system_logger import syslog, SystemLogger

                            current_app.logger.info(f"Starting background targeted Sonarr sync for series {series_id}.")
                            syslog.info(SystemLogger.SYNC, f"Starting targeted sync: {series_title}", {
                                'series_id': series_id,
                                'episode_count': len(episode_ids)
                            })

                            try:
                                updated_count = update_sonarr_episode(series_id, episode_ids, force_has_file=True) or 0
                                current_app.logger.info(f"Targeted episode sync for series {series_id} completed.")
                                syslog.success(SystemLogger.SYNC, f"Episode sync complete: {series_title}")

                                # Verify downloaded episodes are marked available in DB; if not, run full sync fallback.
                                try:
                                    expected_eps = [
                                        (ep.get('seasonNumber'), ep.get('episodeNumber'))
                                        for ep in episodes_info
                                        if ep.get('seasonNumber') is not None and ep.get('episodeNumber') is not None
                                    ]
                                    if expected_eps:
                                        db_check = database.get_db()
                                        show_row_check = db_check.execute(
                                            'SELECT id FROM sonarr_shows WHERE sonarr_id = ?',
                                            (series_id,)
                                        ).fetchone()
                                        available_count = 0
                                        if show_row_check:
                                            show_id_check = show_row_check['id']
                                            for season_num, episode_num in expected_eps:
                                                # Use season_id lookup for reliable matching
                                                season_check = db_check.execute(
                                                    'SELECT id FROM sonarr_seasons WHERE show_id = ? AND season_number = ?',
                                                    (show_id_check, season_num)
                                                ).fetchone()
                                                if not season_check:
                                                    continue
                                                row = db_check.execute(
                                                    '''
                                                    SELECT has_file
                                                    FROM sonarr_episodes
                                                    WHERE season_id = ? AND episode_number = ?
                                                    ''',
                                                    (season_check['id'], episode_num)
                                                ).fetchone()
                                                if row and row['has_file']:
                                                    available_count += 1

                                        if available_count < len(expected_eps):
                                            current_app.logger.warning(
                                                f"Targeted Sonarr update left {len(expected_eps) - available_count}/{len(expected_eps)} episodes unavailable for series {series_id}; triggering full sync fallback."
                                            )
                                            syslog.warning(SystemLogger.SYNC, f"Targeted sync incomplete for {series_title}; running full sync fallback", {
                                                'series_id': series_id,
                                                'expected_episodes': len(expected_eps),
                                                'available_after_targeted': available_count,
                                                'updated_count': updated_count
                                            })
                                            from ..utils import sync_sonarr_library
                                            sync_sonarr_library()
                                except Exception as verify_err:
                                    current_app.logger.warning(f"Targeted Sonarr availability verification failed: {verify_err}")

                                # TVMaze enrichment for the show
                                try:
                                    from app.tvmaze_enrichment import tvmaze_enrichment_service
                                    db_temp = database.get_db()

                                    show_row = db_temp.execute(
                                        'SELECT * FROM sonarr_shows WHERE sonarr_id = ?',
                                        (series_id,)
                                    ).fetchone()

                                    if show_row and tvmaze_enrichment_service.should_enrich_show(dict(show_row)):
                                        syslog.info(SystemLogger.ENRICHMENT, f"Starting TVMaze enrichment: {series_title}")
                                        success = tvmaze_enrichment_service.enrich_show(dict(show_row))
                                        if success:
                                            syslog.success(SystemLogger.ENRICHMENT, f"TVMaze enrichment complete: {series_title}")
                                        else:
                                            syslog.warning(SystemLogger.ENRICHMENT, f"TVMaze enrichment failed: {series_title}")
                                except Exception as e_enrich:
                                    syslog.error(SystemLogger.ENRICHMENT, f"TVMaze enrichment error: {series_title}", {
                                        'error': str(e_enrich)
                                    })
                                    current_app.logger.error(f"TVMaze enrichment failed: {e_enrich}")

                                # Create notifications for users who favorited this show
                                try:
                                    db = database.get_db()

                                    # Find the show in our database
                                    show = db.execute(
                                        'SELECT id, tmdb_id, title FROM sonarr_shows WHERE sonarr_id = ?',
                                        (series_id,)
                                    ).fetchone()

                                    if show:
                                        # Find users who favorited this show
                                        favorited_users = db.execute('''
                                            SELECT user_id FROM user_favorites
                                            WHERE show_id = ? AND is_dropped = 0
                                        ''', (show['id'],)).fetchall()

                                        # Create notification for each user
                                        for user in favorited_users:
                                            for episode in episodes_info:
                                                season_num = episode.get('seasonNumber')
                                                episode_num = episode.get('episodeNumber')
                                                episode_title = episode.get('title', f'Episode {episode_num}')

                                                notification_title = f"New Episode: {series_title}"
                                                notification_message = f"S{season_num:02d}E{episode_num:02d}: {episode_title} is now available!"

                                                db.execute('''
                                                    INSERT INTO user_notifications
                                                    (user_id, show_id, notification_type, title, message, season_number, episode_number)
                                                    VALUES (?, ?, ?, ?, ?, ?, ?)
                                                ''', (
                                                    user['user_id'],
                                                    show['id'],
                                                    'new_episode',
                                                    notification_title,
                                                    notification_message,
                                                    season_num,
                                                    episode_num
                                                ))

                                        db.commit()
                                        current_app.logger.info(f"Created notifications for {len(favorited_users)} users about {len(episodes_info)} new episodes")
                                        syslog.success(SystemLogger.NOTIFICATION, f"Created {len(favorited_users)} notifications for {series_title}", {
                                            'user_count': len(favorited_users),
                                            'episode_count': len(episodes_info)
                                        })
                                    else:
                                        current_app.logger.warning(f"Show with sonarr_id {series_id} not found in database")
                                        syslog.warning(SystemLogger.SYNC, f"Show not found in database: sonarr_id {series_id}")

                                except Exception as e:
                                    current_app.logger.error(f"Error creating notifications: {e}", exc_info=True)
                                    syslog.error(SystemLogger.NOTIFICATION, f"Failed to create notifications for {series_title}", {
                                        'error': str(e)
                                    })

                            except Exception as e:
                                current_app.logger.error(f"Error in background targeted Sonarr sync: {e}", exc_info=True)

                    sync_thread = threading.Thread(target=sync_in_background, args=(app_instance,))
                    sync_thread.daemon = True
                    sync_thread.start()
                    current_app.logger.info(f"Initiated targeted background sync for series {series_id}, episodes {episode_ids}")

            except Exception as e:
                current_app.logger.error(f"Failed to trigger targeted Sonarr sync from webhook: {e}", exc_info=True)
                # Ensure we still attempt a full sync fallback
                run_full_sync = True
        
        if run_full_sync or (event_type in sync_events and event_type != 'Download'):
            current_app.logger.info(f"Sonarr webhook event '{event_type}' detected, triggering full library sync as a fallback.")
            
            # Import here to avoid circular imports
            from ..utils import sync_sonarr_library
            
            try:
                # Trigger the sync in a background thread to avoid blocking the webhook response
                import threading
                
                # Capture the real application object to pass to the thread
                app_instance = current_app._get_current_object()

                def sync_in_background(app):
                    with app.app_context():
                        from app.system_logger import syslog, SystemLogger

                        current_app.logger.info("Starting background Sonarr library sync.")
                        syslog.info(SystemLogger.SYNC, f"Starting full library sync (event: {event_type})")

                        try:
                            count = sync_sonarr_library()
                            current_app.logger.info(f"Sonarr webhook-triggered sync completed: {count} shows processed")
                            syslog.success(SystemLogger.SYNC, f"Full library sync complete: {count} shows processed", {
                                'show_count': count,
                                'event_type': event_type
                            })
                        except Exception as e:
                            current_app.logger.error(f"Error in background Sonarr sync: {e}", exc_info=True)
                            syslog.error(SystemLogger.SYNC, "Full library sync failed", {
                                'error': str(e),
                                'event_type': event_type
                            })
                
                # Start background sync
                sync_thread = threading.Thread(target=sync_in_background, args=(app_instance,))
                sync_thread.daemon = True
                sync_thread.start()
                
                current_app.logger.info("Sonarr library sync initiated in background")
                
            except Exception as e:
                current_app.logger.error(f"Failed to trigger Sonarr sync from webhook: {e}", exc_info=True)
        else:
            current_app.logger.debug(f"Sonarr webhook event '{event_type}' received but no sync needed")
        
        return jsonify({'status': 'success', 'message': f'Processed {event_type} event'}), 200
        
    except Exception as e:
        current_app.logger.error(f"Error processing Sonarr webhook: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@main_bp.route('/radarr/webhook', methods=['POST'])
def radarr_webhook():
    """
    Handles incoming webhook events from Radarr.

    This endpoint receives webhook notifications from Radarr when movies are
    added, updated, or removed. It automatically triggers a library sync to
    keep the ShowNotes database up to date.

    Supported events:
    - Download: When movies are downloaded
    - Movie: When movies are added/updated
    - Rename: When files are renamed
    - Delete: When files are deleted

    Returns:
        A JSON response indicating success or an error.
    """
    current_app.logger.info("Radarr webhook received.")
    try:
        if request.is_json:
            payload = request.get_json()
        else:
            payload = json.loads(request.form.get('payload', '{}'))
        
        current_app.logger.info(f"Radarr webhook received: {json.dumps(payload, indent=2)}")
        
        event_type = payload.get('eventType')
        
        # Record webhook activity in database
        try:
            db = database.get_db()
            payload_summary = f"Event: {event_type}"
            if event_type == 'Download' and payload.get('movie'):
                payload_summary += f" - {payload['movie'].get('title', 'Unknown')}"
            elif event_type == 'Movie' and payload.get('movie'):
                payload_summary += f" - {payload['movie'].get('title', 'Unknown')}"
            
            db.execute(
                'INSERT INTO webhook_activity (service_name, event_type, payload_summary) VALUES (?, ?, ?)',
                ('radarr', event_type, payload_summary)
            )
            db.commit()
        except Exception as e:
            current_app.logger.error(f"Failed to record Radarr webhook activity: {e}")
        
        # Events that should trigger a library sync
        sync_events = [
            'Download',           # Movie downloaded
            'Movie',              # Movie added/updated (generic)
            'MovieAdded',         # Movie added (Radarr v3+)
            'MovieDelete',        # Movie deleted
            'MovieFileDelete',    # Movie file deleted
            'Rename',             # Files renamed
            'Delete',             # Files deleted
            'Health',             # Health check (good for periodic syncs)
            'Test'                # Test event
        ]
        
        if event_type in sync_events:
            current_app.logger.info(f"Radarr webhook event '{event_type}' detected, triggering library sync")
            
            # Import here to avoid circular imports
            from ..utils import sync_radarr_library
            
            try:
                # Trigger the sync in a background thread to avoid blocking the webhook response
                import threading

                # Capture the real application object to pass to the thread
                app_instance = current_app._get_current_object()

                def sync_in_background(app):
                    with app.app_context():
                        current_app.logger.info("Starting background Radarr library sync.")
                        try:
                            result = sync_radarr_library()
                            current_app.logger.info(f"Radarr webhook-triggered sync completed: {result}")
                        except Exception as e:
                            current_app.logger.error(f"Error in background Radarr sync: {e}", exc_info=True)
                
                # Start background sync
                sync_thread = threading.Thread(target=sync_in_background, args=(app_instance,))
                sync_thread.daemon = True
                sync_thread.start()
                
                current_app.logger.info("Radarr library sync initiated in background")
                
            except Exception as e:
                current_app.logger.error(f"Failed to trigger Radarr sync from webhook: {e}", exc_info=True)
        else:
            current_app.logger.debug(f"Radarr webhook event '{event_type}' received but no sync needed")
        
        return jsonify({'status': 'success', 'message': f'Processed {event_type} event'}), 200
        
    except Exception as e:
        current_app.logger.error(f"Error processing Radarr webhook: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

