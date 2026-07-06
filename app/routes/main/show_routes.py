"""
Show, episode, and character detail routes plus LLM summary API endpoints.

Split out of media_routes.py as part of the main blueprint refactor.
"""
import json
import re
import sqlite3
import datetime
from datetime import timezone

from flask import (
    render_template, request, redirect, url_for, session, jsonify,
    flash, current_app, abort
)
from flask_login import login_required

from ... import database
from . import main_bp
from ._shared import (
    _get_tautulli_rating_key_for_media,
    _build_admin_service_links,
    _calculate_year_display,
)

@main_bp.route('/show/<int:tmdb_id>')
@login_required
def show_detail(tmdb_id):
    """
    Displays the detail page for a specific TV show.

    This function gathers comprehensive information for a show, including:
    - Basic metadata from the `sonarr_shows` table.
    - A list of all seasons and episodes from the `sonarr_seasons` and
      `sonarr_episodes` tables.
    - The user's watch history for the show from `plex_activity_log`.
    - A "featured episode" card, which highlights either the most recently
      watched episode or the next unwatched episode.

    Args:
        tmdb_id (int): The The Movie Database (TMDB) ID for the show.

    Returns:
        A rendered HTML template for the show detail page, or a 404 error
        if the show is not found.
    """
    db = database.get_db()
    s_username = session.get('username')
    show_dict = None

    show_row = db.execute('SELECT * FROM sonarr_shows WHERE tmdb_id = ?', (tmdb_id,)).fetchone()
    if not show_row:
        current_app.logger.warning(f"Show with TMDB ID {tmdb_id} not found in sonarr_shows.")
        abort(404)
    show_dict = dict(show_row)
    show_dict['year_display'] = _calculate_year_display(show_dict)

    # Parse genres from JSON
    genres_list = []
    if show_dict.get('genres'):
        try:
            genres_list = json.loads(show_dict['genres'])
        except json.JSONDecodeError:
            pass
    show_dict['genres_list'] = genres_list

    # Fetch cast information (try show_id, then tvdb_id, then tvmaze_id)
    cast_members = []
    cast_rows = db.execute("""
        SELECT * FROM show_cast
        WHERE show_id = ?
        ORDER BY cast_order ASC
        LIMIT 20
    """, (show_dict['id'],)).fetchall()

    if not cast_rows and show_dict.get('tvdb_id'):
        cast_rows = db.execute("""
            SELECT * FROM show_cast
            WHERE show_tvdb_id = ?
            ORDER BY cast_order ASC
            LIMIT 20
        """, (show_dict['tvdb_id'],)).fetchall()

    if not cast_rows and show_dict.get('tvmaze_id'):
        cast_rows = db.execute("""
            SELECT * FROM show_cast
            WHERE show_tvmaze_id = ?
            ORDER BY cast_order ASC
            LIMIT 20
        """, (show_dict['tvmaze_id'],)).fetchall()

    if cast_rows:
        cast_members = [dict(row) for row in cast_rows]

    # Fetch crew (creators, executive producers)
    crew_rows = db.execute("""
        SELECT person_name, job, person_image_url, tvmaze_person_id, sort_order
        FROM show_crew
        WHERE show_id = ?
        ORDER BY CASE job WHEN 'Creator' THEN 0 WHEN 'Co-Creator' THEN 1 WHEN 'Showrunner' THEN 2 ELSE 3 END, sort_order ASC
    """, (show_dict['id'],)).fetchall()
    crew_members = [dict(row) for row in crew_rows] if crew_rows else []

    if show_dict.get('tmdb_id'):
        show_dict['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=show_dict['tmdb_id'])
        show_dict['cached_fanart_url'] = url_for('main.image_proxy', type='background', id=show_dict['tmdb_id'])
    else:
        show_dict['cached_poster_url'] = url_for('static', filename='logos/placeholder_poster.png')
        show_dict['cached_fanart_url'] = url_for('static', filename='logos/placeholder_background.png')
    show_db_id = show_dict['id']

    # Fetch seasons and episodes in batch to avoid N+1 queries
    seasons_rows = db.execute(
        'SELECT * FROM sonarr_seasons WHERE show_id = ? ORDER BY season_number DESC', (show_db_id,)
    ).fetchall()

    # Get all season IDs (excluding Season 0)
    season_ids = [s['id'] for s in seasons_rows if s['season_number'] != 0]

    # Batch fetch all episodes for all seasons at once
    episodes_by_season = {}
    if season_ids:
        placeholders = ','.join('?' * len(season_ids))
        all_episodes = db.execute(
            f'SELECT * FROM sonarr_episodes WHERE season_id IN ({placeholders}) ORDER BY season_id, episode_number DESC',
            season_ids
        ).fetchall()
        # Group episodes by season_id
        for ep in all_episodes:
            season_id = ep['season_id']
            if season_id not in episodes_by_season:
                episodes_by_season[season_id] = []
            episodes_by_season[season_id].append(dict(ep))

    seasons_with_episodes = []
    all_show_episodes_for_next_aired_check = []

    for season_row in seasons_rows:
        if season_row['season_number'] == 0:
            # Skip specials/Season 0 from main listing
            continue
        season_dict = dict(season_row)
        season_db_id = season_dict['id']

        # Get episodes from pre-fetched map
        current_season_episodes = episodes_by_season.get(season_db_id, [])
        season_dict['episodes'] = current_season_episodes
        seasons_with_episodes.append(season_dict)
        all_show_episodes_for_next_aired_check.extend(current_season_episodes)

    next_aired_episode_info = None
    if show_dict.get('status', '').lower() == 'continuing' or show_dict.get('status', '').lower() == 'upcoming': # Only look for next_aired if show is active
        try:
            now_utc = datetime.datetime.now(timezone.utc)
            relevant_episodes = [ep for ep in all_show_episodes_for_next_aired_check if ep.get('air_date_utc')]
            relevant_episodes.sort(key=lambda ep: ep['air_date_utc'])

            for episode in relevant_episodes:
                air_date_str = episode['air_date_utc']
                try:
                    air_date = datetime.datetime.fromisoformat(air_date_str.replace('Z', '+00:00'))
                    if air_date > now_utc:
                        season_number_for_next_aired = None
                        # Find season number for this episode
                        for s_dict in seasons_with_episodes:
                            if s_dict['id'] == episode['season_id']:
                                season_number_for_next_aired = s_dict['season_number']
                                break

                        if season_number_for_next_aired is not None: # Ensure season number was found
                            next_aired_episode_info = {
                                'title': episode['title'],
                                'season_number': season_number_for_next_aired,
                                'episode_number': episode['episode_number'],
                                'air_date_utc': air_date_str,
                                'season_episode_str': f"S{str(season_number_for_next_aired).zfill(2)}E{str(episode['episode_number']).zfill(2)}"
                            }
                            break # Found the earliest next aired episode
                except (ValueError, TypeError) as e_parse:
                    current_app.logger.debug(f"Could not parse air_date_utc '{air_date_str}' for episode ID {episode.get('id')}: {e_parse}")
                    continue
        except Exception as e_next_aired:
            current_app.logger.error(f"Error determining next aired episode for show TMDB ID {tmdb_id}: {e_next_aired}")

    currently_watched_episode_info = None
    last_watched_episode_info = None
    plex_username = session.get('username')
    show_tmdb_id_for_plex = show_dict.get('tmdb_id')

    if plex_username and show_tmdb_id_for_plex:
        try:
            # Match by tmdb_id which is reliably set by both Plex webhooks and Tautulli sync
            plex_activity_row = db.execute(
                """
                SELECT title, season_episode, view_offset_ms, duration_ms, event_timestamp
                FROM plex_activity_log
                WHERE plex_username = ?
                  AND tmdb_id = ?
                  AND media_type = 'episode'
                  AND event_type IN ('media.play', 'media.pause', 'media.resume')
                ORDER BY event_timestamp DESC
                LIMIT 1
                """,
                (plex_username, show_tmdb_id_for_plex)
            ).fetchone()

            if plex_activity_row:
                currently_watched_episode_info = dict(plex_activity_row)
                if currently_watched_episode_info.get('view_offset_ms') is not None and \
                   currently_watched_episode_info.get('duration_ms') is not None and \
                   currently_watched_episode_info['duration_ms'] > 0:
                    progress = (currently_watched_episode_info['view_offset_ms'] / currently_watched_episode_info['duration_ms']) * 100
                    currently_watched_episode_info['progress_percent'] = round(progress)
        except sqlite3.Error as e_sql:
            current_app.logger.error(f"SQLite error fetching currently watched episode for show TMDB ID {show_tmdb_id_for_plex} and user {plex_username}: {e_sql}")
        except Exception as e_watched:
            current_app.logger.error(f"Generic error fetching currently watched episode for show TMDB ID {show_tmdb_id_for_plex} and user {plex_username}: {e_watched}")

        if not currently_watched_episode_info:
            last_row = db.execute(
                """
                SELECT title, season_episode, event_timestamp
                FROM plex_activity_log
                WHERE plex_username = ?
                  AND tmdb_id = ?
                  AND media_type = 'episode'
                  AND event_type IN ('media.stop', 'media.scrobble', 'watched')
                ORDER BY event_timestamp DESC
                LIMIT 1
                """,
                (plex_username, show_tmdb_id_for_plex)
            ).fetchone()
            if last_row:
                last_watched_episode_info = dict(last_row)

    next_up_episode = get_next_up_episode(
        currently_watched_episode_info,
        last_watched_episode_info,
        show_dict,
        seasons_with_episodes
    )

    # Get Jellyseer URL for request button — prefer public/remote URL for browser links
    settings = db.execute('SELECT jellyseer_url, jellyseer_remote_url FROM settings LIMIT 1').fetchone()
    jellyseer_url = None
    if settings:
        jellyseer_url = settings['jellyseer_remote_url'] or settings['jellyseer_url'] or None
    admin_service_links = _build_admin_service_links(db, 'show', show_dict)

    # Fetch season summaries
    show_summary = None
    season_recaps = {}
    try:
        from app.summary_services import get_season_summary, get_show_summary
        for season_dict in seasons_with_episodes:
            season_dict['summary'] = get_season_summary(tmdb_id, season_dict['season_number'])
            if season_dict['summary']:
                season_recaps[season_dict['season_number']] = season_dict['summary']
        show_summary = get_show_summary(tmdb_id)
    except Exception as e:
        current_app.logger.debug(f"Could not fetch summaries: {e}")

    # Cutoff disclaimer: read from settings, pass to template if disclaimer is enabled
    cutoff_disclaimer = None
    try:
        settings_row = db.execute('SELECT summary_show_disclaimer, llm_knowledge_cutoff_date FROM settings LIMIT 1').fetchone()
        if settings_row and settings_row['summary_show_disclaimer'] not in ('0', 0, None) and settings_row['llm_knowledge_cutoff_date']:
            import datetime as _dt
            cutoff_date = _dt.datetime.strptime(settings_row['llm_knowledge_cutoff_date'], '%Y-%m-%d').date()
            cutoff_disclaimer = cutoff_date.strftime('%B %Y')
    except Exception:
        pass

    return render_template('show_detail.html',
                           show=show_dict,
                           seasons_with_episodes=seasons_with_episodes,
                           next_aired_episode_info=next_aired_episode_info,
                           next_up_episode=next_up_episode,
                           cast_members=cast_members,
                           crew_members=crew_members,
                           jellyseer_url=jellyseer_url,
                           admin_service_links=admin_service_links,
                           season_recaps=season_recaps,
                           show_summary=show_summary,
                           cutoff_disclaimer=cutoff_disclaimer
                           )

def get_next_up_episode(currently_watched, last_watched, show_info, seasons_with_episodes, user_prefs=None):
    """
    Determines the "Next Up" episode for a show's detail page with enhanced logic.
    """
    if user_prefs is None:
        user_prefs = {'skip_specials': True, 'order': 'default'}

    db = database.get_db()
    source_info = None
    is_currently_watching = False
    is_next_unwatched = False

    if currently_watched:
        source_info = currently_watched
        is_currently_watching = True
    elif last_watched:
        last_season_episode_str = last_watched.get('season_episode')
        match = re.match(r'S(\d+)E(\d+)', last_season_episode_str) if last_season_episode_str else None
        if match:
            last_season_num = int(match.group(1))
            last_episode_num = int(match.group(2))

            all_episodes = []
            for season in sorted(seasons_with_episodes, key=lambda s: s['season_number']):
                if user_prefs['skip_specials'] and season['season_number'] == 0:
                    continue
                # Sort episodes within the season
                sorted_episodes = sorted(season['episodes'], key=lambda e: e['episode_number'])
                for episode in sorted_episodes:
                    all_episodes.append({
                        'season_number': season['season_number'],
                        **episode
                    })

            last_watched_index = -1
            for i, ep in enumerate(all_episodes):
                if ep['season_number'] == last_season_num and ep['episode_number'] == last_episode_num:
                    last_watched_index = i
                    break

            if last_watched_index != -1:
                # Search for the next available episode, considering multi-part episodes
                for i in range(last_watched_index + 1, len(all_episodes)):
                    next_ep = all_episodes[i]
                    if next_ep.get('has_file'):
                        # Check for multi-part episode logic (e.g., if the title is the same as the previous)
                        if i > 0 and all_episodes[i-1]['title'] == next_ep['title']:
                            # This might be the second part of a multi-part episode, let's see if we should skip it
                            # For now, we assume the user wants to see the next file regardless.
                            # More complex logic could be added here.
                            pass

                        source_info = {
                            'title': next_ep['title'],
                            'season_episode': f"S{str(next_ep['season_number']).zfill(2)}E{str(next_ep['episode_number']).zfill(2)}",
                            'event_timestamp': last_watched.get('event_timestamp')
                        }
                        is_next_unwatched = True
                        break

        if not source_info:
            source_info = last_watched

    if not source_info:
        return None

    season_episode_str = source_info.get('season_episode')
    match = re.match(r'S(\d+)E(\d+)', season_episode_str) if season_episode_str else None
    if not match:
        return None
    season_number, episode_number = map(int, match.groups())

    episode_detail_url = url_for('main.episode_detail',
                                 tmdb_id=show_info['tmdb_id'],
                                 season_number=season_number,
                                 episode_number=episode_number)

    raw_timestamp = source_info.get('event_timestamp')
    formatted_timestamp = "Unknown"
    if raw_timestamp:
        try:
            dt_obj = datetime.datetime.fromisoformat(str(raw_timestamp).replace('Z', '+00:00'))
            formatted_timestamp = dt_obj.strftime("%b %d, %Y at %I:%M %p")
        except (ValueError, TypeError):
            formatted_timestamp = str(raw_timestamp)

    return {
        'title': source_info.get('title'),
        'season_episode_str': season_episode_str,
        'season_number': season_number,
        'episode_number': episode_number,
        'poster_url': show_info.get('cached_poster_url'),
        'event_timestamp': raw_timestamp,
        'formatted_timestamp': formatted_timestamp,
        'progress_percent': source_info.get('progress_percent') if is_currently_watching else None,
        'episode_detail_url': episode_detail_url,
        'is_currently_watching': is_currently_watching,
        'is_next_unwatched': is_next_unwatched,
        'overview': source_info.get('overview', '')
    }
@main_bp.route('/show/<int:tmdb_id>/season/<int:season_number>/episode/<int:episode_number>')
@login_required
def episode_detail(tmdb_id, season_number, episode_number):
    """
    Displays the detail page for a single TV episode.

    It fetches metadata for the episode, its parent season, and its parent show
    from the database to provide a comprehensive view. This includes details
    like air date, summary, and a link back to the main show page.

    Args:
        tmdb_id (int): The TMDB ID of the parent show.
        season_number (int): The season number of the episode.
        episode_number (int): The episode number.

    Returns:
        A rendered HTML template for the episode detail page, or a 404 error
        if the show or episode cannot be found.
    """
    db = database.get_db()

    # Fetch show, season, and episode details in one go if possible
    show_row = db.execute('SELECT id, title, tmdb_id, tvdb_id, poster_url, fanart_url FROM sonarr_shows WHERE tmdb_id = ?', (tmdb_id,)).fetchone()
    if not show_row:
        abort(404)
    show_dict = dict(show_row)
    # Use consistent names for cached URLs as expected by the new template.
    if show_dict.get('tmdb_id'):
        show_dict['cached_poster_url'] = url_for('main.image_proxy', type='poster', id=show_dict['tmdb_id'])
        show_dict['cached_fanart_url'] = url_for('main.image_proxy', type='background', id=show_dict['tmdb_id']) # Optional for episode page bg
    else:
        show_dict['cached_poster_url'] = url_for('static', filename='logos/placeholder_poster.png')
        show_dict['cached_fanart_url'] = url_for('static', filename='logos/placeholder_background.png')

    show_id = show_dict['id']
    show_tvdb_id = show_dict.get('tvdb_id')
    show_tmdb_id = show_dict.get('tmdb_id')
    show_title = show_dict.get('title')
    season_row = db.execute('SELECT id FROM sonarr_seasons WHERE show_id=? AND season_number=?', (show_id, season_number)).fetchone()
    if not season_row:
        abort(404)

    # Fetch all columns for the episode
    episode_row = db.execute('SELECT * FROM sonarr_episodes WHERE season_id=? AND episode_number=?', (season_row['id'], episode_number)).fetchone()
    if not episode_row:
        abort(404)

    episode_dict = dict(episode_row)

    # Fetch previous and next episodes for navigation
    prev_episode = None
    next_episode = None
    
    # Get previous episode (highest episode number less than current)
    prev_row = db.execute(
        'SELECT episode_number, title FROM sonarr_episodes WHERE season_id=? AND episode_number < ? ORDER BY episode_number DESC LIMIT 1',
        (season_row['id'], episode_number)
    ).fetchone()
    if prev_row:
        prev_episode = dict(prev_row)
    
    # Get next episode (lowest episode number greater than current)
    next_row = db.execute(
        'SELECT episode_number, title FROM sonarr_episodes WHERE season_id=? AND episode_number > ? ORDER BY episode_number ASC LIMIT 1',
        (season_row['id'], episode_number)
    ).fetchone()
    if next_row:
        next_episode = dict(next_row)

    # Try all possible IDs for cast lookup
    episode_characters = []
    # 1. Sonarr TVDB ID
    if show_tvdb_id:
        episode_characters = db.execute(
            'SELECT * FROM episode_characters WHERE show_tvdb_id = ? AND season_number = ? AND episode_number = ? ORDER BY id',
            (show_tvdb_id, season_number, episode_number)
        ).fetchall()
        episode_characters = [dict(row) for row in episode_characters]
    # 2. Sonarr TMDB ID
    if not episode_characters and show_tmdb_id:
        episode_characters = db.execute(
            'SELECT * FROM episode_characters WHERE show_tmdb_id = ? AND season_number = ? AND episode_number = ? ORDER BY id',
            (show_tmdb_id, season_number, episode_number)
        ).fetchall()
        episode_characters = [dict(row) for row in episode_characters]
    # 3. Try Plex webhook IDs from most recent plex_activity_log for this episode
    if not episode_characters:
        # Try to find the most recent plex_activity_log for this show/season/episode
        # We'll match by show title and season/episode string (season_episode)
        season_episode_str = f"S{str(season_number).zfill(2)}E{str(episode_number).zfill(2)}"
        plex_row = db.execute(
            'SELECT raw_payload FROM plex_activity_log WHERE show_title = ? AND season_episode = ? ORDER BY event_timestamp DESC LIMIT 1',
            (show_title, season_episode_str)
        ).fetchone()
        plex_tmdb_id = None
        plex_tvdb_id = None
        if plex_row:
            import json
            try:
                payload = json.loads(plex_row['raw_payload'])
                guids = payload.get('Metadata', {}).get('Guid', [])
                for guid_item in guids:
                    guid_str = guid_item.get('id', '')
                    if guid_str.startswith('tmdb://'):
                        try:
                            plex_tmdb_id = int(guid_str.split('//')[1])
                        except Exception:
                            plex_tmdb_id = None
                    if guid_str.startswith('tvdb://'):
                        try:
                            plex_tvdb_id = int(guid_str.split('//')[1])
                        except Exception:
                            plex_tvdb_id = None
            except Exception:
                pass
        # 3a. Plex TVDB ID
        if plex_tvdb_id:
            episode_characters = db.execute(
                'SELECT * FROM episode_characters WHERE show_tvdb_id = ? AND season_number = ? AND episode_number = ? ORDER BY id',
                (plex_tvdb_id, season_number, episode_number)
            ).fetchall()
            episode_characters = [dict(row) for row in episode_characters]
        # 3b. Plex TMDB ID
        if not episode_characters and plex_tmdb_id:
            episode_characters = db.execute(
                'SELECT * FROM episode_characters WHERE show_tmdb_id = ? AND season_number = ? AND episode_number = ? ORDER BY id',
                (plex_tmdb_id, season_number, episode_number)
            ).fetchall()
            episode_characters = [dict(row) for row in episode_characters]

    # Format air date — convert UTC to configured local timezone before formatting
    if episode_dict.get('air_date_utc'):
        from ...data_transforms import convert_utc_to_user_timezone
        episode_dict['formatted_air_date'] = convert_utc_to_user_timezone(
            episode_dict['air_date_utc'], '%B %d, %Y'
        )
    else:
        episode_dict['formatted_air_date'] = 'N/A'

    # Ensure 'is_available' based on 'has_file'
    episode_dict['is_available'] = episode_dict.get('has_file', False)

    # Add runtime if available (example field name, adjust if different in your schema)
    # episode_dict['runtime_minutes'] = episode_dict.get('runtime', None)


    # Debug episode_characters before rendering
    current_app.logger.info(f"[DEBUG] Episode {tmdb_id} S{season_number}E{episode_number} found {len(episode_characters)} characters:")
    for char in episode_characters:
        current_app.logger.info(f"[DEBUG] Character: ID={char.get('id')}, Name={char.get('character_name')}, Actor={char.get('actor_name')}")
    
    return render_template('episode_detail.html',
                           show=show_dict,
                           episode=episode_dict,
                           season_number=season_number,
                           episode_characters=episode_characters,
                           prev_episode=prev_episode,
                           next_episode=next_episode)


@main_bp.route('/character/<int:show_id>/<int:season_number>/<int:episode_number>/<int:character_id>')
def character_detail(show_id, season_number, episode_number, character_id):
    """
    Display character detail page showing actor information and other appearances.
    """
    db = database.get_db()

    # Get character information
    character = db.execute('''
        SELECT ec.*
        FROM episode_characters ec
        WHERE ec.id = ?
        LIMIT 1
    ''', (character_id,)).fetchone()

    if not character:
        flash('Character not found.', 'danger')
        return redirect(url_for('main.episode_detail', tmdb_id=show_id, season_number=season_number, episode_number=episode_number))

    # Get show information
    show = db.execute('SELECT title, overview, year FROM sonarr_shows WHERE tmdb_id = ?', (show_id,)).fetchone()
    show_title = show['title'] if show else "Unknown Show"

    # Get all episodes this character appears in for this show
    character_episodes = db.execute('''
        SELECT DISTINCT ec.season_number, ec.episode_number, se.title, se.air_date_utc
        FROM episode_characters ec
        LEFT JOIN sonarr_episodes se ON ec.episode_number = se.episode_number
        LEFT JOIN sonarr_seasons ss ON se.season_id = ss.id AND ec.season_number = ss.season_number
        LEFT JOIN sonarr_shows sshow ON ss.show_id = sshow.id
        WHERE ec.show_tmdb_id = ?
        AND ec.character_name = ?
        AND sshow.tmdb_id = ?
        ORDER BY ec.season_number, ec.episode_number
    ''', (show_id, character['character_name'], show_id)).fetchall()

    # Get other shows this actor appears in (same actor name)
    other_shows = []
    if character['actor_name']:
        other_shows = db.execute('''
            SELECT DISTINCT ss.tmdb_id, ss.title, ec.character_name, COUNT(DISTINCT ec.episode_number) as episode_count
            FROM episode_characters ec
            JOIN sonarr_shows ss ON ec.show_tmdb_id = ss.tmdb_id
            WHERE ec.actor_name = ?
            AND ss.tmdb_id != ?
            GROUP BY ss.tmdb_id, ss.title, ec.character_name
            ORDER BY episode_count DESC
            LIMIT 10
        ''', (character['actor_name'], show_id)).fetchall()

    # Try to get TMDB person ID from show_cast table for external links
    tmdb_person_id = None
    tvmaze_person_id = character.get('actor_id')
    if character.get('actor_name'):
        cast_row = db.execute(
            'SELECT tmdb_person_id, person_id FROM show_cast WHERE actor_name = ? AND tmdb_person_id IS NOT NULL LIMIT 1',
            (character['actor_name'],)
        ).fetchone()
        if cast_row:
            tmdb_person_id = cast_row['tmdb_person_id']
            if not tvmaze_person_id:
                tvmaze_person_id = cast_row['person_id']

    return render_template('character_detail.html',
                           show_id=show_id,
                           season_number=season_number,
                           episode_number=episode_number,
                           character_id=character_id,
                           character=character,
                           show_title=show_title,
                           character_episodes=character_episodes,
                           other_shows=other_shows,
                           tmdb_person_id=tmdb_person_id,
                           tvmaze_person_id=tvmaze_person_id)


@main_bp.route('/api/summary/feedback', methods=['POST'])
@login_required
def summary_feedback():
    """Submit a thumbs up/down rating or problem report on an AI summary."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    data = request.get_json() or {}
    summary_type = data.get('summary_type')   # episode, season, show
    show_id      = data.get('show_id')
    season_number = data.get('season_number')
    episode_id   = data.get('episode_id')
    rating       = data.get('rating')          # 1, -1, or None
    report_type  = data.get('report_type')     # inaccurate, outdated, spoilers, other
    notes        = data.get('notes', '').strip()

    if not summary_type:
        return jsonify({'success': False, 'error': 'summary_type required'}), 400
    if rating not in (1, -1, None):
        return jsonify({'success': False, 'error': 'rating must be 1, -1, or null'}), 400

    db = database.get_db()
    db.execute('''
        INSERT INTO summary_feedback
            (user_id, summary_type, show_id, season_number, episode_id, rating, report_type, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, summary_type, show_id, season_number, episode_id, rating, report_type, notes or None))
    db.commit()

    return jsonify({'success': True})


@main_bp.route('/api/generate-show-summary', methods=['POST'])
@login_required
def generate_show_summary_route():
    """Generate or regenerate a show summary for the current user."""
    from app.summary_services import generate_show_summary
    
    data = request.get_json()
    tmdb_id = data.get('tmdb_id')
    
    if not tmdb_id:
        return jsonify({"error": "tmdb_id required"}), 400
    
    try:
        success, error = generate_show_summary(int(tmdb_id))
    except Exception as e:
        current_app.logger.error(f"Error generating show summary for tmdb_id={tmdb_id}: {e}", exc_info=True)
        return jsonify({
            "status": "failed",
            "error": str(e)
        }), 500
    
    if success:
        return jsonify({
            "status": "completed",
            "message": f"Show summary generated successfully"
        })
    else:
        return jsonify({
            "status": "failed",
            "error": error or "Unknown error"
        }), 500


@main_bp.route('/api/generate-season-summary', methods=['POST'])
@login_required
def generate_season_summary_route():
    """Generate or regenerate a season summary for the current user."""
    from app.summary_services import generate_season_summary
    
    data = request.get_json()
    tmdb_id = data.get('tmdb_id')
    season_number = data.get('season_number')
    
    if not tmdb_id or season_number is None:
        return jsonify({"error": "tmdb_id and season_number required"}), 400
    
    success, error = generate_season_summary(int(tmdb_id), int(season_number))
    
    if success:
        return jsonify({
            "status": "completed",
            "message": f"Season {season_number} summary generated successfully"
        })
    else:
        return jsonify({
            "status": "failed",
            "error": error or "Unknown error"
        }), 500
