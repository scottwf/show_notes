import requests
import json
from flask import current_app, url_for
from . import database
from .utils import _trigger_image_cache
from .calendar_service import invalidate_calendar_cache

def get_all_sonarr_shows():
    """
    Fetches a list of all shows from the configured Sonarr instance.

    This function communicates with the Sonarr API to retrieve the complete list
    of TV shows in the user's library.

    Returns:
        list or None: A list of dictionaries, where each dictionary represents a show
                      from Sonarr. Returns None if Sonarr is not configured or if
                      an error occurs during the API call.
    """
    sonarr_url = None
    sonarr_api_key = None
    # get_setting requires an app context
    with current_app.app_context():
        sonarr_url = database.get_setting('sonarr_url')
        sonarr_api_key = database.get_setting('sonarr_api_key')

    if not sonarr_url or not sonarr_api_key:
        current_app.logger.error("get_all_sonarr_shows: Sonarr URL or API key not configured.")
        return None

    endpoint = f"{sonarr_url.rstrip('/')}/api/v3/series"
    headers = {"X-Api-Key": sonarr_api_key}

    try:
        response = requests.get(endpoint, headers=headers, timeout=10)
        response.raise_for_status()  # Raises HTTPError for bad responses (4XX or 5XX)
        return response.json()
    except requests.exceptions.Timeout:
        current_app.logger.error(f"get_all_sonarr_shows: Timeout connecting to Sonarr at {endpoint}")
        return None
    except requests.exceptions.ConnectionError:
        current_app.logger.error(f"get_all_sonarr_shows: Connection error connecting to Sonarr at {endpoint}")
        return None
    except requests.exceptions.HTTPError as e:
        current_app.logger.error(f"get_all_sonarr_shows: HTTP error fetching Sonarr shows: {e}. Response: {e.response.text if e.response else 'No response'}")
        return None
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"get_all_sonarr_shows: Generic error fetching Sonarr shows: {e}")
        return None
    except json.JSONDecodeError as e:
        current_app.logger.error(f"get_all_sonarr_shows: Error decoding Sonarr shows JSON response: {e}")
        return None

def get_sonarr_episodes_for_show(sonarr_series_id):
    """
    Fetches all episodes for a specific Sonarr series ID.

    This function queries the Sonarr API for the episode list of a given show.
    It's used during the library sync process to gather episode details.

    Args:
        sonarr_series_id (int or str): The unique ID of the series in Sonarr.

    Returns:
        list or None: A list of dictionaries, where each dictionary represents an
                      episode. Returns None if Sonarr is not configured or if an
                      error occurs.
    """
    sonarr_url = None
    sonarr_api_key = None
    with current_app.app_context():
        sonarr_url = database.get_setting('sonarr_url')
        sonarr_api_key = database.get_setting('sonarr_api_key')

    if not sonarr_url or not sonarr_api_key:
        current_app.logger.error(f"get_sonarr_episodes_for_show: Sonarr URL or API key not configured for series ID {sonarr_series_id}.")
        return None

    if not sonarr_series_id:
        current_app.logger.error("get_sonarr_episodes_for_show: sonarr_series_id cannot be None or empty.")
        return None

    endpoint = f"{sonarr_url.rstrip('/')}/api/v3/episode?seriesId={sonarr_series_id}"
    headers = {"X-Api-Key": sonarr_api_key}

    try:
        response = requests.get(endpoint, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        current_app.logger.error(f"get_sonarr_episodes_for_show: Timeout connecting to Sonarr at {endpoint} for series ID {sonarr_series_id}")
        return None
    except requests.exceptions.ConnectionError:
        current_app.logger.error(f"get_sonarr_episodes_for_show: Connection error connecting to Sonarr at {endpoint} for series ID {sonarr_series_id}")
        return None
    except requests.exceptions.HTTPError as e:
        current_app.logger.error(f"get_sonarr_episodes_for_show: HTTP error fetching episodes for series {sonarr_series_id}: {e}. Response: {e.response.text if e.response else 'No response'}")
        return None
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"get_sonarr_episodes_for_show: Generic error fetching episodes for series {sonarr_series_id}: {e}")
        return None
    except json.JSONDecodeError as e:
        current_app.logger.error(f"get_sonarr_episodes_for_show: Error decoding Sonarr episodes JSON response for series {sonarr_series_id}: {e}")
        return None

def get_sonarr_show_details(series_id):
    """
    Fetches the details for a single show from the Sonarr API.
    """
    sonarr_url = None
    sonarr_api_key = None
    with current_app.app_context():
        sonarr_url = database.get_setting('sonarr_url')
        sonarr_api_key = database.get_setting('sonarr_api_key')

    if not sonarr_url or not sonarr_api_key:
        current_app.logger.error(f"get_sonarr_show_details: Sonarr URL or API key not configured for series ID {series_id}.")
        return None

    endpoint = f"{sonarr_url.rstrip('/')}/api/v3/series/{series_id}"
    headers = {"X-Api-Key": sonarr_api_key}

    try:
        response = requests.get(endpoint, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Error fetching Sonarr show details for series ID {series_id}: {e}")
        return None

def get_episodes_by_series_id(series_id):
    """
    Fetches all episodes for a given series ID from the Sonarr API.
    """
    sonarr_url = None
    sonarr_api_key = None
    with current_app.app_context():
        sonarr_url = database.get_setting('sonarr_url')
        sonarr_api_key = database.get_setting('sonarr_api_key')

    if not sonarr_url or not sonarr_api_key:
        current_app.logger.error(f"get_episodes_by_series_id: Sonarr URL or API key not configured for series ID {series_id}.")
        return None

    endpoint = f"{sonarr_url.rstrip('/')}/api/v3/episode?seriesId={series_id}"
    headers = {"X-Api-Key": sonarr_api_key}

    try:
        response = requests.get(endpoint, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Error fetching Sonarr episodes for series ID {series_id}: {e}")
        return None

def sync_sonarr_tags():
    """
    Synchronizes Sonarr tags (labels) with the local database.

    Fetches all tags from the Sonarr API and upserts them into the sonarr_tags table.
    This allows us to map tag IDs to human-readable labels.

    Returns:
        int: The number of tags synced.
    """
    current_app.logger.info("Starting Sonarr tags sync.")
    tags_synced_count = 0

    with current_app.app_context():
        db = database.get_db()
        sonarr_url = database.get_setting('sonarr_url')
        sonarr_api_key = database.get_setting('sonarr_api_key')

        if not sonarr_url or not sonarr_api_key:
            current_app.logger.warning("sync_sonarr_tags: Sonarr URL or API key not configured.")
            return tags_synced_count

        try:
            # Fetch tags from Sonarr API
            endpoint = f"{sonarr_url.rstrip('/')}/api/v3/tag"
            headers = {"X-Api-Key": sonarr_api_key}
            response = requests.get(endpoint, headers=headers, timeout=10)
            response.raise_for_status()
            tags_data = response.json()

            if not tags_data:
                current_app.logger.info("sync_sonarr_tags: No tags returned from Sonarr API.")
                return tags_synced_count

            # Sync each tag to the database
            for tag in tags_data:
                tag_id = tag.get('id')
                label = tag.get('label')

                if tag_id is None or not label:
                    current_app.logger.warning(f"sync_sonarr_tags: Skipping tag with missing id or label: {tag}")
                    continue

                try:
                    db.execute("""
                        INSERT INTO sonarr_tags (id, label, last_synced_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT (id) DO UPDATE SET
                        label = excluded.label,
                        last_synced_at = CURRENT_TIMESTAMP
                    """, (tag_id, label))
                    tags_synced_count += 1
                except Exception as e:
                    current_app.logger.error(f"sync_sonarr_tags: Error syncing tag {tag_id}: {e}")
                    continue

            db.commit()
            current_app.logger.info(f"sync_sonarr_tags: Successfully synced {tags_synced_count} tags.")

        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"sync_sonarr_tags: Error fetching tags from Sonarr API: {e}")
        except Exception as e:
            current_app.logger.error(f"sync_sonarr_tags: Unexpected error: {e}")

    return tags_synced_count

def sync_sonarr_library():
    """
    Synchronizes the entire Sonarr library with the local database.

    This comprehensive function performs the following steps:
    1.  Fetches all shows from the Sonarr API.
    2.  For each show, it fetches all its episodes.
    3.  Iterates through each show and episode, and "upserts" their data into the
        `sonarr_shows` and `sonarr_episodes` tables in the local database.
    4.  It uses an in-memory cache to avoid redundant database lookups for shows.
    5.  It queues poster and fanart images for background caching.
    6.  It maintains a list of Sonarr IDs present in the API response and removes
        any shows from the local database that are no longer in Sonarr.

    This function is typically triggered manually from the admin panel.

    Returns:
        int: The number of shows that were successfully processed and synced.
    """
    processed_count = 0 # This variable seems unused here, part of a copy-paste?
    # It's used as a return value if all_shows_data is empty.
    current_app.logger.info("Starting Sonarr library sync.")
    shows_synced_count = 0
    episodes_synced_count = 0

    try:
        from app.system_logger import syslog, SystemLogger
        syslog.info(SystemLogger.SYNC, "Starting Sonarr library sync")
    except:
        pass

    # Sync tags first so they're available when syncing shows
    sync_sonarr_tags()

    # App context for API calls and initial DB setup
    with current_app.app_context():
        db = database.get_db()
        
        settings_row = db.execute('SELECT sonarr_url FROM settings LIMIT 1').fetchone()
        sonarr_base_url = settings_row['sonarr_url'].rstrip('/') if settings_row and 'sonarr_url' in settings_row and settings_row['sonarr_url'] else None
        if not sonarr_base_url:
            current_app.logger.warning("sync_sonarr_library: Sonarr URL not found in settings. Cannot form absolute image URLs if they are relative.")
            # sonarr_base_url will be None, and logic below will handle it by not prepending.

        all_shows_data = get_all_sonarr_shows()

        if not all_shows_data:
            current_app.logger.warning("sync_sonarr_library: No shows returned from Sonarr API or Sonarr not configured.")
            return processed_count

        for show_data in all_shows_data:
            current_sonarr_id_api = None # Initialize to ensure it's defined for logging in except blocks
            try:
                current_sonarr_id_api = show_data.get('id')
                if current_sonarr_id_api is None:
                    current_app.logger.error(f"sync_sonarr_library: Skipping show due to missing Sonarr ID. Data: {show_data.get('title', 'N/A')}")
                    continue
                
                try:
                    current_sonarr_id = int(current_sonarr_id_api)
                except ValueError:
                    current_app.logger.error(f"sync_sonarr_library: Sonarr ID '{current_sonarr_id_api}' is not a valid integer. Skipping show: {show_data.get('title', 'N/A')}")
                    continue

                current_app.logger.info(f"Syncing show: {show_data.get('title', 'N/A')} (Sonarr ID: {current_sonarr_id})")

                # Prepare show data, preferring 'remoteUrl' over 'url'
                poster_img_info = next((img for img in show_data.get('images', []) if img.get('coverType') == 'poster'), None)
                fanart_img_info = next((img for img in show_data.get('images', []) if img.get('coverType') == 'fanart'), None)

                raw_poster_url = poster_img_info.get('remoteUrl') or poster_img_info.get('url') if poster_img_info else None
                raw_fanart_url = fanart_img_info.get('remoteUrl') or fanart_img_info.get('url') if fanart_img_info else None

                final_poster_url = raw_poster_url # Default to original
                if sonarr_base_url and raw_poster_url and raw_poster_url.startswith('/'):
                    final_poster_url = f"{sonarr_base_url}{raw_poster_url}"
                
                final_fanart_url = raw_fanart_url # Default to original
                if sonarr_base_url and raw_fanart_url and raw_fanart_url.startswith('/'):
                    final_fanart_url = f"{sonarr_base_url}{raw_fanart_url}"

                # Extract ratings from Sonarr API response
                ratings_data = show_data.get("ratings", {})
                imdb_rating = ratings_data.get("imdb", {}) if ratings_data else {}
                tmdb_rating = ratings_data.get("tmdb", {}) if ratings_data else {}
                metacritic_rating = ratings_data.get("metacritic", {}) if ratings_data else {}

                # Convert tags array to comma-separated string
                tags_array = show_data.get("tags", [])
                tags_str = ",".join(str(tag_id) for tag_id in tags_array) if tags_array else None

                # Extract original language name from the nested object Sonarr returns
                orig_lang_obj = show_data.get("originalLanguage", {}) or {}
                orig_lang_name = orig_lang_obj.get("name")

                show_values = {
                    "sonarr_id": current_sonarr_id,
                    "tvdb_id": show_data.get("tvdbId"),
                    "tmdb_id": show_data.get("tmdbId"),
                    "imdb_id": show_data.get("imdbId"),
                    "title": show_data.get("title"),
                    "status": show_data.get("status"),
                    "ended": show_data.get("ended", False),
                    "overview": show_data.get("overview"),
                    "season_count": len(show_data.get("seasons", [])), # More reliable than show_data.get("seasonCount") sometimes
                    "episode_count": show_data.get("episodeCount"),
                    "episode_file_count": show_data.get("episodeFileCount"),
                    "poster_url": final_poster_url,
                    "fanart_url": final_fanart_url,
                    "path_on_disk": show_data.get("path"),
                    "ratings_imdb_value": imdb_rating.get("value"),
                    "ratings_imdb_votes": imdb_rating.get("votes"),
                    "ratings_tmdb_value": tmdb_rating.get("value"),
                    "ratings_tmdb_votes": tmdb_rating.get("votes"),
                    "ratings_metacritic_value": metacritic_rating.get("value"),
                    "metacritic_id": show_data.get("metacriticId"),
                    "tags": tags_str,
                    "original_language": orig_lang_name,
                    "content_rating": show_data.get("certification"),
                }

                # Filter out None values to avoid inserting NULL for non-nullable or for cleaner updates
                # BUT keep sonarr_id since it's required for ON CONFLICT clause
                show_values_filtered = {k: v for k, v in show_values.items() if v is not None or k == 'sonarr_id'}

                # Insert/Update Sonarr Show
                sql = """
                    INSERT INTO sonarr_shows ({columns}, last_synced_at)
                    VALUES ({placeholders}, CURRENT_TIMESTAMP)
                    ON CONFLICT (sonarr_id) DO UPDATE SET
                    {update_setters}, last_synced_at = CURRENT_TIMESTAMP
                    RETURNING id;
                """.format(
                    columns=", ".join(show_values_filtered.keys()),
                    placeholders=", ".join("?" for _ in show_values_filtered),
                    update_setters=", ".join(f"{key} = excluded.{key}" for key in show_values_filtered)
                )

                params_tuple = tuple(show_values_filtered.values())
                current_app.logger.debug(f"Attempting to sync sonarr_shows for Sonarr ID: {current_sonarr_id}")
                current_app.logger.debug(f"SQL: {sql}")
                current_app.logger.debug(f"PARAMS: {params_tuple}")

                cursor = db.execute(sql, params_tuple)
                show_db_id = cursor.fetchone()[0]

                if not show_db_id:
                    current_app.logger.error(f"sync_sonarr_library: Failed to insert/update show and get ID for Sonarr ID {current_sonarr_id}")
                    db.rollback() # Rollback this show's transaction
                    continue # Skip to next show

                # Trigger image caching directly (only if we have a request context)
                show_tmdb_id = show_data.get("tmdbId")
                if show_tmdb_id:
                    try:
                        if final_poster_url:
                            proxy_poster_url = url_for('main.image_proxy', type='poster', id=show_tmdb_id)
                            _trigger_image_cache(proxy_poster_url, item_title_for_logging=f"Poster for {show_data.get('title')}")
                        if final_fanart_url:
                            proxy_fanart_url = url_for('main.image_proxy', type='background', id=show_tmdb_id)
                            _trigger_image_cache(proxy_fanart_url, item_title_for_logging=f"Fanart for {show_data.get('title')}")
                    except RuntimeError as e:
                        # Skip image caching if we're outside a request context (e.g., webhook background thread)
                        current_app.logger.debug(f"Skipping image caching for show '{show_data.get('title')}' - no request context: {e}")
                else:
                    current_app.logger.warning(f"Skipping image trigger for show '{show_data.get('title')}' due to missing TMDB ID.")

                # Show enrichment (TVDB primary, TVMaze fallback)
                try:
                    from app.thetvdb_enrichment import thetvdb_enrichment_service

                    # Fetch the show row for enrichment check
                    show_row = db.execute('SELECT * FROM sonarr_shows WHERE id = ?', (show_db_id,)).fetchone()

                    if show_row:
                        show_dict_for_check = dict(show_row)
                    else:
                        show_dict_for_check = {
                            'id': show_db_id,
                            'tvdb_id': show_values.get('tvdb_id'),
                            'title': show_values.get('title'),
                            'tvdb_enriched_at': None,
                            'tvmaze_enriched_at': None
                        }

                    if thetvdb_enrichment_service.should_enrich_show(show_dict_for_check):
                        current_app.logger.info(f"Enrichment needed for '{show_data.get('title')}'")
                        try:
                            from app.system_logger import syslog, SystemLogger
                            syslog.info(SystemLogger.ENRICHMENT, f"Starting enrichment: {show_data.get('title')}")

                            success = thetvdb_enrichment_service.enrich_show(show_dict_for_check)

                            if success:
                                syslog.success(SystemLogger.ENRICHMENT, f"Enrichment complete: {show_data.get('title')}")
                            else:
                                syslog.warning(SystemLogger.ENRICHMENT, f"Enrichment failed: {show_data.get('title')}")
                        except Exception as e_enrich:
                            current_app.logger.error(f"Enrichment failed: {e_enrich}")
                            try:
                                from app.system_logger import syslog, SystemLogger
                                syslog.error(SystemLogger.ENRICHMENT, f"Enrichment error: {show_data.get('title')}", {
                                    'error': str(e_enrich)
                                })
                            except:
                                pass
                except ImportError:
                    current_app.logger.warning("Enrichment service not available")
                except Exception as e:
                    current_app.logger.error(f"Enrichment error: {e}")
                    try:
                        from app.system_logger import syslog, SystemLogger
                        syslog.error(SystemLogger.ENRICHMENT, f"Enrichment setup error: {show_data.get('title')}", {
                            'error': str(e)
                        })
                    except:
                        pass

                # Sync Seasons and Episodes for this show
                # Sonarr's /api/v3/series endpoint includes season details
                sonarr_show_id = show_data.get("id")
                api_seasons = show_data.get("seasons", [])

                if not api_seasons:
                    current_app.logger.warning(f"sync_sonarr_library: No seasons found in API response for show ID {sonarr_show_id}. Attempting to fetch episodes directly to deduce seasons.")

                # Fetch all episodes for the show once
                all_episodes_data = get_sonarr_episodes_for_show(sonarr_show_id)
                if not all_episodes_data and not api_seasons: # No season info from series, and no episodes fetched
                     current_app.logger.warning(f"sync_sonarr_library: No episodes found for show ID {sonarr_show_id} and no explicit season data. Skipping season/episode sync for this show.")
                     db.commit() # Commit show data
                     shows_synced_count += 1
                     continue


                # Group episodes by season number if needed for fallback
                episodes_by_season_num = {}
                if all_episodes_data:
                    for ep_data in all_episodes_data:
                        episodes_by_season_num.setdefault(ep_data.get("seasonNumber"), []).append(ep_data)

                # Process seasons (preferring API season data)
                processed_season_numbers = set()
                for season_data_api in api_seasons:
                    season_number = season_data_api.get("seasonNumber")
                    if season_number is None: # Should not happen with valid Sonarr data
                        current_app.logger.warning(f"sync_sonarr_library: Season data found without season number for show ID {sonarr_show_id}. Skipping this season entry.")
                        continue

                    processed_season_numbers.add(season_number)

                    # Use statistics from API if available
                    stats_api = season_data_api.get("statistics", {})
                    # Sonarr API gives previousEpisodeCount, episodeCount (aired), episodeFileCount, totalEpisodeCount, etc.
                    # We need total episodes in season and files in season
                    # episode_count for sonarr_seasons is total episodes in that season.
                    # episode_file_count is files in that season.
                    season_episode_count = stats_api.get("totalEpisodeCount", 0) if stats_api else 0 # total episodes in this season
                    season_episode_file_count = stats_api.get("episodeFileCount", 0) if stats_api else 0 # files in this season

                    # Fallback if API stats are missing or seem incomplete (e.g. totalEpisodeCount is 0 but episodes exist)
                    if season_episode_count == 0 and season_number in episodes_by_season_num:
                        season_episode_count = len(episodes_by_season_num[season_number])
                        season_episode_file_count = sum(1 for ep in episodes_by_season_num[season_number] if ep.get("hasFile"))

                    season_values = {
                        "show_id": show_db_id,
                        "sonarr_season_id": None, # Not a direct Sonarr ID, for internal linking if needed
                        "season_number": season_number,
                        "episode_count": season_episode_count,
                        "episode_file_count": season_episode_file_count,
                        "statistics": json.dumps(stats_api if stats_api else {"episodeFileCount": season_episode_file_count, "totalEpisodeCount": season_episode_count})
                    }
                    season_values_filtered = {k: v for k, v in season_values.items() if v is not None or k in ['show_id', 'season_number']}

                    sql_season = """
                        INSERT INTO sonarr_seasons ({columns})
                        VALUES ({placeholders})
                        ON CONFLICT (show_id, season_number) DO UPDATE SET
                        {update_setters}
                        RETURNING id;
                    """.format(
                        columns=", ".join(season_values_filtered.keys()),
                        placeholders=", ".join("?" for _ in season_values_filtered),
                        update_setters=", ".join(f"{key} = excluded.{key}" for key in season_values_filtered)
                    )
                    params_season_tuple = tuple(season_values_filtered.values())
                    current_app.logger.debug(f"Attempting to sync sonarr_seasons for show_id {show_db_id}, season {season_number}")
                    current_app.logger.debug(f"SEASON SQL: {sql_season}")
                    current_app.logger.debug(f"SEASON PARAMS: {params_season_tuple}")
                    cursor_season = db.execute(sql_season, params_season_tuple)
                    season_db_id = cursor_season.fetchone()[0]

                    if not season_db_id:
                        current_app.logger.error(f"sync_sonarr_library: Failed to insert/update season {season_number} for show ID {show_db_id} (Sonarr Show ID: {sonarr_show_id})")
                        # Potentially rollback or just log and continue with other seasons/episodes
                        continue

                    # Sync Episodes for this season (using the already fetched all_episodes_data)
                    current_season_episodes = [ep for ep in all_episodes_data if ep.get("seasonNumber") == season_number and ep.get("seriesId") == sonarr_show_id]
                    for episode_data in current_season_episodes:
                        # Extract ratings from episode data
                        ep_ratings_data = episode_data.get("ratings", {})
                        ep_imdb_rating = ep_ratings_data.get("imdb", {}) if ep_ratings_data else {}
                        ep_tmdb_rating = ep_ratings_data.get("tmdb", {}) if ep_ratings_data else {}

                        episode_values = {
                            "show_id": show_db_id,
                            "season_id": season_db_id,
                            "season_number": season_number,
                            "sonarr_show_id": sonarr_show_id,  # Sonarr's seriesId
                            "sonarr_episode_id": episode_data.get("id"),  # Sonarr's episodeId
                            "episode_number": episode_data.get("episodeNumber"),
                            "title": episode_data.get("title"),
                            "overview": episode_data.get("overview"),
                            "air_date_utc": episode_data.get("airDateUtc"),
                            "has_file": bool(episode_data.get("hasFile", False)),
                            "imdb_id": episode_data.get("imdbId"),
                            "ratings_imdb_value": ep_imdb_rating.get("value"),
                            "ratings_imdb_votes": ep_imdb_rating.get("votes"),
                            "ratings_tmdb_value": ep_tmdb_rating.get("value"),
                            "ratings_tmdb_votes": ep_tmdb_rating.get("votes"),
                        }
                        episode_values_filtered = {k: v for k, v in episode_values.items() if v is not None or k == 'sonarr_episode_id'}

                        if not episode_values_filtered.get("sonarr_episode_id"):
                            current_app.logger.warning(f"sync_sonarr_library: Skipping episode due to missing sonarr_episode_id. Data: {episode_data}")
                            continue

                        sql_episode = """
                            INSERT INTO sonarr_episodes ({columns})
                            VALUES ({placeholders})
                            ON CONFLICT (sonarr_episode_id) DO UPDATE SET
                            {update_setters};
                        """.format(
                            columns=", ".join(episode_values_filtered.keys()),
                            placeholders=", ".join("?" for _ in episode_values_filtered),
                            update_setters=", ".join(f"{key} = excluded.{key}" for key in episode_values_filtered)
                        )
                        params_episode_tuple = tuple(episode_values_filtered.values())
                        # current_app.logger.debug(f"Attempting to sync sonarr_episodes for Sonarr Episode ID: {episode_data.get('id')}")
                        # current_app.logger.debug(f"EPISODE SQL: {sql_episode}")
                        # current_app.logger.debug(f"EPISODE PARAMS: {params_episode_tuple}")
                        try:
                            db.execute(sql_episode, params_episode_tuple)
                            episodes_synced_count += 1
                        except sqlite3.IntegrityError as e:
                            current_app.logger.error(f"sync_sonarr_library: Integrity error syncing episode Sonarr ID {episode_data.get('id')} for season {season_number}, show {sonarr_show_id}: {e}")
                        except Exception as e:
                            current_app.logger.error(f"sync_sonarr_library: General error syncing episode Sonarr ID {episode_data.get('id')}: {e}")

                # Fallback for seasons not present in show_data.seasons (e.g. season 0 / specials if not listed)
                # but present in episode list
                for season_number, episodes_in_season in episodes_by_season_num.items():
                    if season_number in processed_season_numbers or season_number == 0: # Often season 0 is specials, handle if not in api_seasons
                        # Skip if already processed via api_seasons or if it's season 0 and not explicitly handled (can be noisy)
                        # Re-evaluate if season 0 needs specific handling beyond what API provides for `show_data.seasons`
                        if season_number == 0 and not any(s.get("seasonNumber") == 0 for s in api_seasons):
                             current_app.logger.info(f"sync_sonarr_library: Found episodes for season 0 for show ID {sonarr_show_id}, but season 0 was not in series.seasons. Processing based on episodes.")
                        elif season_number in processed_season_numbers:
                            continue


                    current_app.logger.info(f"Syncing season {season_number} for show ID {sonarr_show_id} (Sonarr Show ID: {sonarr_show_id}) from episode data (fallback).")
                    s_episode_count = len(episodes_in_season)
                    s_episode_file_count = sum(1 for ep in episodes_in_season if ep.get("hasFile"))
                    # s_monitored = all(ep.get("monitored", False) for ep in episodes_in_season) # Approximate if all episodes are monitored

                    season_values_fb = {
                        "show_id": show_db_id,
                        "season_number": season_number,
                        "episode_count": s_episode_count,
                        "episode_file_count": s_episode_file_count,
                        "statistics": json.dumps({"episodeFileCount": s_episode_file_count, "totalEpisodeCount": s_episode_count})
                    }
                    season_values_fb_filtered = {k: v for k, v in season_values_fb.items() if v is not None or k in ['show_id', 'season_number']}

                    sql_season_fb = """
                        INSERT INTO sonarr_seasons ({columns})
                        VALUES ({placeholders})
                        ON CONFLICT (show_id, season_number) DO UPDATE SET
                        {update_setters}
                        RETURNING id;
                    """.format(
                        columns=", ".join(season_values_fb_filtered.keys()),
                        placeholders=", ".join("?" for _ in season_values_fb_filtered),
                        update_setters=", ".join(f"{key} = excluded.{key}" for key in season_values_fb_filtered)
                    )
                    params_season_fb_tuple = tuple(season_values_fb_filtered.values())
                    current_app.logger.debug(f"Attempting to sync sonarr_seasons (fallback) for show_id {show_db_id}, season {season_number}")
                    current_app.logger.debug(f"SEASON FALLBACK SQL: {sql_season_fb}")
                    current_app.logger.debug(f"SEASON FALLBACK PARAMS: {params_season_fb_tuple}")
                    cursor_season_fb = db.execute(sql_season_fb, params_season_fb_tuple)
                    season_db_id_fb = cursor_season_fb.fetchone()[0]

                    if not season_db_id_fb:
                        current_app.logger.error(f"sync_sonarr_library: Failed to insert/update season {season_number} (fallback) for show ID {show_db_id}")
                        continue

                    for episode_data in episodes_in_season: # episodes_in_season are from all_episodes_data, grouped
                        episode_values_fb = {
                            "show_id": show_db_id,
                            "season_id": season_db_id_fb,
                            "season_number": season_number,
                            "sonarr_show_id": sonarr_show_id,
                            "sonarr_episode_id": episode_data.get("id"),
                            "episode_number": episode_data.get("episodeNumber"),
                            "title": episode_data.get("title"),
                            "overview": episode_data.get("overview"),
                            "air_date_utc": episode_data.get("airDateUtc"),
                            "has_file": bool(episode_data.get("hasFile", False)),
                        }
                        episode_values_fb_filtered = {k: v for k, v in episode_values_fb.items() if v is not None or k == 'sonarr_episode_id'}
                        sql_episode_fb = """
                            INSERT INTO sonarr_episodes ({columns})
                            VALUES ({placeholders})
                            ON CONFLICT (sonarr_episode_id) DO UPDATE SET
                            {update_setters};
                        """.format(
                            columns=", ".join(episode_values_fb_filtered.keys()),
                            placeholders=", ".join("?" for _ in episode_values_fb_filtered),
                            update_setters=", ".join(f"{key} = excluded.{key}" for key in episode_values_fb_filtered)
                        )
                        params_episode_fb_tuple = tuple(episode_values_fb_filtered.values())
                        current_app.logger.debug(f"Attempting to sync sonarr_episodes (fallback) for Sonarr Episode ID: {episode_data.get('id')}")
                        current_app.logger.debug(f"EPISODE FALLBACK SQL: {sql_episode_fb}")
                        current_app.logger.debug(f"EPISODE FALLBACK PARAMS: {params_episode_fb_tuple}")
                        try:
                            db.execute(sql_episode_fb, params_episode_fb_tuple)
                            episodes_synced_count += 1
                        except sqlite3.IntegrityError as e:
                            current_app.logger.error(f"sync_sonarr_library: Integrity error syncing episode (fallback) Sonarr ID {episode_data.get('id')} for season {season_number}, show {sonarr_show_id}: {e}")


                db.commit() # Commit after each show and its seasons/episodes are processed
                shows_synced_count += 1
                current_app.logger.info(f"Successfully synced show: {show_data.get('title')} and its seasons/episodes.")

            except sqlite3.Error as e:
                db.rollback() # Rollback on error for this show
                current_app.logger.error(f"sync_sonarr_library: Database error while syncing show Sonarr ID {current_sonarr_id}: {e}")
            except Exception as e:
                db.rollback() # General exception rollback
                current_app.logger.error(f"sync_sonarr_library: Unexpected error while syncing show Sonarr ID {current_sonarr_id}: {e}", exc_info=True)

        current_app.logger.info(f"Sonarr library sync finished. Synced {shows_synced_count} shows and {episodes_synced_count} episodes.")

        # Invalidate calendar cache since episode data has changed
        invalidate_calendar_cache()

        try:
            from app.system_logger import syslog, SystemLogger
            syslog.success(SystemLogger.SYNC, f"Sonarr library sync complete", {
                'shows_synced': shows_synced_count,
                'episodes_synced': episodes_synced_count
            })
        except:
            pass

        return shows_synced_count

def update_sonarr_episode(series_id, episode_ids, force_has_file=False):
    """
    Updates a specific set of episodes for a given series from Sonarr.

    This function is designed to be called from a webhook, allowing for a much
    more efficient update than a full library sync.

    Args:
        series_id (int): The Sonarr `id` of the series to update.
        episode_ids (list[int]): A list of Sonarr `id`s of the episodes to update.
    """
    current_app.logger.info(f"Starting targeted Sonarr update for series ID {series_id} and episode IDs {episode_ids}")
    
    with current_app.app_context():
        db = database.get_db()

        # Fetch show data first
        show_data = get_sonarr_show_details(series_id)
        if not show_data:
            current_app.logger.error(f"Could not fetch show details for series ID {series_id}. Aborting update.")
            return

        # Keep show metadata fresh
        db.execute('''
            INSERT INTO sonarr_shows (sonarr_id, title, year, status, overview, season_count, tvdb_id, tmdb_id, imdb_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sonarr_id) DO UPDATE SET
                title = excluded.title,
                year = excluded.year,
                status = excluded.status,
                overview = excluded.overview,
                season_count = excluded.season_count,
                tvdb_id = excluded.tvdb_id,
                tmdb_id = excluded.tmdb_id,
                imdb_id = excluded.imdb_id;
            ''', (
                show_data.get('id'),
                show_data.get('title'),
                show_data.get('year'),
                show_data.get('status'),
                show_data.get('overview'),
                show_data.get('seasonCount'),
                show_data.get('tvdbId'),
                show_data.get('tmdbId'),
                show_data.get('imdbId')
            )
        )

        show_row = db.execute(
            'SELECT id FROM sonarr_shows WHERE sonarr_id = ?',
            (series_id,)
        ).fetchone()
        if not show_row:
            db.commit()
            current_app.logger.error(f"Could not resolve local show row for Sonarr series ID {series_id}.")
            return
        show_id = show_row['id']

        # Fetch all Sonarr episodes for this show, then target only requested IDs
        all_episodes_data = get_episodes_by_series_id(series_id)
        if not all_episodes_data:
            current_app.logger.warning(f"No episodes found for series ID {series_id}, but show was updated.")
            db.commit()
            return

        episode_id_set = set(episode_ids or [])
        episodes_to_update = [ep for ep in all_episodes_data if ep.get('id') in episode_id_set]
        if not episodes_to_update:
            current_app.logger.warning(f"No matching episodes found for series ID {series_id} and IDs {episode_ids}.")
            db.commit()
            return

        updated_count = 0

        for episode_data in episodes_to_update:
            season_number = episode_data.get('seasonNumber')
            season_id = None

            if season_number is not None:
                season_row = db.execute(
                    'SELECT id FROM sonarr_seasons WHERE show_id = ? AND season_number = ?',
                    (show_id, season_number)
                ).fetchone()
                if season_row:
                    season_id = season_row['id']
                else:
                    db.execute(
                        'INSERT INTO sonarr_seasons (show_id, season_number) VALUES (?, ?)',
                        (show_id, season_number)
                    )
                    season_id = db.execute(
                        'SELECT id FROM sonarr_seasons WHERE show_id = ? AND season_number = ?',
                        (show_id, season_number)
                    ).fetchone()['id']

            if season_id is None:
                current_app.logger.warning(
                    f"Skipping Sonarr episode {episode_data.get('id')} for series {series_id} due to missing season number."
                )
                continue

            has_file = True if force_has_file else bool(episode_data.get('hasFile', False))
            db.execute('''
                INSERT INTO sonarr_episodes (
                    sonarr_episode_id, show_id, season_id, season_number, episode_number,
                    sonarr_show_id, title, overview, air_date_utc, has_file
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sonarr_episode_id) DO UPDATE SET
                    show_id = excluded.show_id,
                    season_id = excluded.season_id,
                    season_number = excluded.season_number,
                    episode_number = excluded.episode_number,
                    sonarr_show_id = excluded.sonarr_show_id,
                    title = excluded.title,
                    overview = excluded.overview,
                    air_date_utc = excluded.air_date_utc,
                    has_file = excluded.has_file;
                ''', (
                    episode_data.get('id'),
                    show_id,
                    season_id,
                    season_number,
                    episode_data.get('episodeNumber'),
                    series_id,
                    episode_data.get('title'),
                    episode_data.get('overview'),
                    episode_data.get('airDateUtc'),
                    has_file
                )
            )
            updated_count += 1
            current_app.logger.info(
                f"Updated episode: {show_data.get('title')} S{season_number}E{episode_data.get('episodeNumber')} (has_file={has_file})"
            )

        db.commit()
        current_app.logger.info(f"Finished targeted Sonarr update for series ID {series_id}. Updated {updated_count} episodes.")
        return updated_count


