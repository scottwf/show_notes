import requests
import logging
import json
import sqlite3
import datetime # For last_synced_at
from flask import current_app
from . import database

logger = logging.getLogger(__name__)

def get_all_sonarr_shows():
    """
    Fetches all series from Sonarr's API.

    Retrieves Sonarr URL and API key from database settings.
    Handles connection errors and non-200 HTTP responses.

    Returns:
        list: A list of Sonarr series objects (dictionaries) if successful.
        list: An empty list if Sonarr is not configured or an error occurs.
    """
    sonarr_url = None
    sonarr_api_key = None
    # get_setting requires an app context
    with current_app.app_context():
        sonarr_url = database.get_setting('sonarr_url')
        sonarr_api_key = database.get_setting('sonarr_api_key')

    if not sonarr_url or not sonarr_api_key:
        logger.error("get_all_sonarr_shows: Sonarr URL or API key not configured.")
        return []

    endpoint = f"{sonarr_url.rstrip('/')}/api/v3/series"
    headers = {"X-Api-Key": sonarr_api_key}

    try:
        response = requests.get(endpoint, headers=headers, timeout=10)
        response.raise_for_status()  # Raises HTTPError for bad responses (4XX or 5XX)
        return response.json()
    except requests.exceptions.Timeout:
        logger.error(f"get_all_sonarr_shows: Timeout connecting to Sonarr at {endpoint}")
        return []
    except requests.exceptions.ConnectionError:
        logger.error(f"get_all_sonarr_shows: Connection error connecting to Sonarr at {endpoint}")
        return []
    except requests.exceptions.HTTPError as e:
        logger.error(f"get_all_sonarr_shows: HTTP error fetching Sonarr shows: {e}. Response: {e.response.text if e.response else 'No response'}")
        return []
    except requests.exceptions.RequestException as e:
        logger.error(f"get_all_sonarr_shows: Generic error fetching Sonarr shows: {e}")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"get_all_sonarr_shows: Error decoding Sonarr shows JSON response: {e}")
        return []

def get_sonarr_episodes_for_show(sonarr_series_id):
    """
    Fetches all episodes for a given Sonarr series ID.

    Retrieves Sonarr URL and API key from database settings.
    Handles connection errors and non-200 HTTP responses.

    Args:
        sonarr_series_id (int): The Sonarr series ID.

    Returns:
        list: A list of Sonarr episode objects (dictionaries) if successful.
        list: An empty list if Sonarr is not configured or an error occurs.
    """
    sonarr_url = None
    sonarr_api_key = None
    with current_app.app_context():
        sonarr_url = database.get_setting('sonarr_url')
        sonarr_api_key = database.get_setting('sonarr_api_key')

    if not sonarr_url or not sonarr_api_key:
        logger.error(f"get_sonarr_episodes_for_show: Sonarr URL or API key not configured for series ID {sonarr_series_id}.")
        return []

    if not sonarr_series_id:
        logger.error("get_sonarr_episodes_for_show: sonarr_series_id cannot be None or empty.")
        return []

    endpoint = f"{sonarr_url.rstrip('/')}/api/v3/episode?seriesId={sonarr_series_id}"
    headers = {"X-Api-Key": sonarr_api_key}

    try:
        response = requests.get(endpoint, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        logger.error(f"get_sonarr_episodes_for_show: Timeout connecting to Sonarr at {endpoint} for series ID {sonarr_series_id}")
        return []
    except requests.exceptions.ConnectionError:
        logger.error(f"get_sonarr_episodes_for_show: Connection error connecting to Sonarr at {endpoint} for series ID {sonarr_series_id}")
        return []
    except requests.exceptions.HTTPError as e:
        logger.error(f"get_sonarr_episodes_for_show: HTTP error fetching episodes for series {sonarr_series_id}: {e}. Response: {e.response.text if e.response else 'No response'}")
        return []
    except requests.exceptions.RequestException as e:
        logger.error(f"get_sonarr_episodes_for_show: Generic error fetching episodes for series {sonarr_series_id}: {e}")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"get_sonarr_episodes_for_show: Error decoding Sonarr episodes JSON response for series {sonarr_series_id}: {e}")
        return []

def get_all_radarr_movies():
    """
    Fetches all movies from Radarr's API.

    Retrieves Radarr URL and API key from database settings.
    Handles connection errors and non-200 HTTP responses.

    Returns:
        list: A list of Radarr movie objects (dictionaries) if successful.
        list: An empty list if Radarr is not configured or an error occurs.
    """
    radarr_url = None
    radarr_api_key = None
    with current_app.app_context():
        radarr_url = database.get_setting('radarr_url')
        radarr_api_key = database.get_setting('radarr_api_key')

    if not radarr_url or not radarr_api_key:
        logger.error("get_all_radarr_movies: Radarr URL or API key not configured.")
        return []

    endpoint = f"{radarr_url.rstrip('/')}/api/v3/movie"
    headers = {"X-Api-Key": radarr_api_key}

    try:
        response = requests.get(endpoint, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        logger.error(f"get_all_radarr_movies: Timeout connecting to Radarr at {endpoint}")
        return []
    except requests.exceptions.ConnectionError:
        logger.error(f"get_all_radarr_movies: Connection error connecting to Radarr at {endpoint}")
        return []
    except requests.exceptions.HTTPError as e:
        logger.error(f"get_all_radarr_movies: HTTP error fetching Radarr movies: {e}. Response: {e.response.text if e.response else 'No response'}")
        return []
    except requests.exceptions.RequestException as e:
        logger.error(f"get_all_radarr_movies: Generic error fetching Radarr movies: {e}")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"get_all_radarr_movies: Error decoding Radarr movies JSON response: {e}")
        return []

def sync_sonarr_library():
    """
    Fetches all shows, their seasons, and episodes from Sonarr
    and syncs them with the local database.
    """
    logger.info("Starting Sonarr library sync.")
    shows_synced_count = 0
    episodes_synced_count = 0

    # App context for API calls and initial DB setup
    with current_app.app_context():
        db = database.get_db()
        all_shows_data = get_all_sonarr_shows()

        if not all_shows_data:
            logger.warning("sync_sonarr_library: No shows returned from Sonarr API or Sonarr not configured.")
            return

        for show_data in all_shows_data:
            try:
                logger.info(f"Syncing show: {show_data.get('title', 'N/A')} (Sonarr ID: {show_data.get('id', 'N/A')})")

                # Prepare show data
                show_values = {
                    "sonarr_id": show_data.get("id"),
                    "tvdb_id": show_data.get("tvdbId"),
                    "imdb_id": show_data.get("imdbId"),
                    "title": show_data.get("title"),
                    "year": show_data.get("year"),
                    "overview": show_data.get("overview"),
                    "status": show_data.get("status"),
                    "season_count": len(show_data.get("seasons", [])), # More reliable than show_data.get("seasonCount") sometimes
                    "episode_count": show_data.get("episodeCount"),
                    "episode_file_count": show_data.get("episodeFileCount"),
                    "poster_url": next((img['url'] for img in show_data.get('images', []) if img['coverType'] == 'poster'), None),
                    "fanart_url": next((img['url'] for img in show_data.get('images', []) if img['coverType'] == 'fanart'), None),
                    "path_on_disk": show_data.get("path"),
                }

                # Filter out None values to avoid inserting NULL for non-nullable or for cleaner updates
                show_values_filtered = {k: v for k, v in show_values.items() if v is not None}

                # Insert/Update Sonarr Show
                # last_synced_at is updated automatically by the SET clause or DEFAULT
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

                cursor = db.execute(sql, tuple(show_values_filtered.values()))
                show_db_id = cursor.fetchone()[0]

                if not show_db_id:
                    logger.error(f"sync_sonarr_library: Failed to insert/update show and get ID for Sonarr ID {show_data.get('id')}")
                    db.rollback() # Rollback this show's transaction
                    continue # Skip to next show

                # Sync Seasons and Episodes for this show
                # Sonarr's /api/v3/series endpoint includes season details
                sonarr_show_id = show_data.get("id")
                api_seasons = show_data.get("seasons", [])

                if not api_seasons:
                    logger.warning(f"sync_sonarr_library: No seasons found in API response for show ID {sonarr_show_id}. Attempting to fetch episodes directly to deduce seasons.")

                # Fetch all episodes for the show once
                all_episodes_data = get_sonarr_episodes_for_show(sonarr_show_id)
                if not all_episodes_data and not api_seasons: # No season info from series, and no episodes fetched
                     logger.warning(f"sync_sonarr_library: No episodes found for show ID {sonarr_show_id} and no explicit season data. Skipping season/episode sync for this show.")
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
                        logger.warning(f"sync_sonarr_library: Season data found without season number for show ID {sonarr_show_id}. Skipping this season entry.")
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
                        "monitored": bool(season_data_api.get("monitored", False)),
                        "statistics": json.dumps(stats_api if stats_api else {"episodeFileCount": season_episode_file_count, "totalEpisodeCount": season_episode_count})
                    }
                    season_values_filtered = {k: v for k, v in season_values.items() if v is not None}

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
                    cursor_season = db.execute(sql_season, tuple(season_values_filtered.values()))
                    season_db_id = cursor_season.fetchone()[0]

                    if not season_db_id:
                        logger.error(f"sync_sonarr_library: Failed to insert/update season {season_number} for show ID {show_db_id} (Sonarr Show ID: {sonarr_show_id})")
                        # Potentially rollback or just log and continue with other seasons/episodes
                        continue

                    # Sync Episodes for this season (using the already fetched all_episodes_data)
                    current_season_episodes = [ep for ep in all_episodes_data if ep.get("seasonNumber") == season_number and ep.get("seriesId") == sonarr_show_id]
                    for episode_data in current_season_episodes:
                        episode_values = {
                            "season_id": season_db_id,
                            "sonarr_show_id": sonarr_show_id, # Sonarr's seriesId
                            "sonarr_episode_id": episode_data.get("id"), # Sonarr's episodeId
                            "episode_number": episode_data.get("episodeNumber"),
                            "title": episode_data.get("title"),
                            "overview": episode_data.get("overview"),
                            "air_date_utc": episode_data.get("airDateUtc"),
                            "has_file": bool(episode_data.get("hasFile", False)),
                            "monitored": bool(episode_data.get("monitored", False)),
                        }
                        episode_values_filtered = {k: v for k, v in episode_values.items() if v is not None}

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
                        try:
                            db.execute(sql_episode, tuple(episode_values_filtered.values()))
                            episodes_synced_count +=1
                        except sqlite3.IntegrityError as e:
                             logger.error(f"sync_sonarr_library: Integrity error syncing episode Sonarr ID {episode_data.get('id')} for season {season_number}, show {sonarr_show_id}: {e}")
                             # This could happen if sonarr_episode_id is not unique, which it should be.
                             # Or if season_id is invalid (less likely given above logic)


                # Fallback for seasons not present in show_data.seasons (e.g. season 0 / specials if not listed)
                # but present in episode list
                for season_number, episodes_in_season in episodes_by_season_num.items():
                    if season_number in processed_season_numbers or season_number == 0: # Often season 0 is specials, handle if not in api_seasons
                        # Skip if already processed via api_seasons or if it's season 0 and not explicitly handled (can be noisy)
                        # Re-evaluate if season 0 needs specific handling beyond what API provides for `show_data.seasons`
                        if season_number == 0 and not any(s.get("seasonNumber") == 0 for s in api_seasons):
                             logger.info(f"sync_sonarr_library: Found episodes for season 0 for show ID {sonarr_show_id}, but season 0 was not in series.seasons. Processing based on episodes.")
                        elif season_number in processed_season_numbers:
                            continue


                    logger.info(f"Syncing season {season_number} for show ID {sonarr_show_id} (Sonarr Show ID: {sonarr_show_id}) from episode data (fallback).")
                    s_episode_count = len(episodes_in_season)
                    s_episode_file_count = sum(1 for ep in episodes_in_season if ep.get("hasFile"))
                    s_monitored = all(ep.get("monitored", False) for ep in episodes_in_season) # Approximate if all episodes are monitored

                    season_values_fb = {
                        "show_id": show_db_id,
                        "season_number": season_number,
                        "episode_count": s_episode_count,
                        "episode_file_count": s_episode_file_count,
                        "monitored": s_monitored,
                        "statistics": json.dumps({"episodeFileCount": s_episode_file_count, "totalEpisodeCount": s_episode_count})
                    }
                    season_values_fb_filtered = {k: v for k, v in season_values_fb.items() if v is not None}

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
                    cursor_season_fb = db.execute(sql_season_fb, tuple(season_values_fb_filtered.values()))
                    season_db_id_fb = cursor_season_fb.fetchone()[0]

                    if not season_db_id_fb:
                        logger.error(f"sync_sonarr_library: Failed to insert/update season {season_number} (fallback) for show ID {show_db_id}")
                        continue

                    for episode_data in episodes_in_season: # episodes_in_season are from all_episodes_data, grouped
                        episode_values_fb = {
                            "season_id": season_db_id_fb,
                            "sonarr_show_id": sonarr_show_id,
                            "sonarr_episode_id": episode_data.get("id"),
                            "episode_number": episode_data.get("episodeNumber"),
                            "title": episode_data.get("title"),
                            "overview": episode_data.get("overview"),
                            "air_date_utc": episode_data.get("airDateUtc"),
                            "has_file": bool(episode_data.get("hasFile", False)),
                            "monitored": bool(episode_data.get("monitored", False)),
                        }
                        episode_values_fb_filtered = {k: v for k, v in episode_values_fb.items() if v is not None}
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
                        try:
                            db.execute(sql_episode_fb, tuple(episode_values_fb_filtered.values()))
                            episodes_synced_count += 1
                        except sqlite3.IntegrityError as e:
                            logger.error(f"sync_sonarr_library: Integrity error syncing episode (fallback) Sonarr ID {episode_data.get('id')} for season {season_number}, show {sonarr_show_id}: {e}")


                db.commit() # Commit after each show and its seasons/episodes are processed
                shows_synced_count += 1
                logger.info(f"Successfully synced show: {show_data.get('title')} and its seasons/episodes.")

            except sqlite3.Error as e:
                db.rollback() # Rollback on error for this show
                logger.error(f"sync_sonarr_library: Database error while syncing show Sonarr ID {show_data.get('id', 'N/A')}: {e}")
            except Exception as e:
                db.rollback() # General exception rollback
                logger.error(f"sync_sonarr_library: Unexpected error while syncing show Sonarr ID {show_data.get('id', 'N/A')}: {e}", exc_info=True)

        logger.info(f"Sonarr library sync finished. Synced {shows_synced_count} shows and {episodes_synced_count} episodes.")


def sync_radarr_library():
    """
    Fetches all movies from Radarr and syncs them with the local database.
    """
    logger.info("Starting Radarr library sync.")
    movies_synced_count = 0

    with current_app.app_context():
        db = database.get_db()
        all_movies_data = get_all_radarr_movies()

        if not all_movies_data:
            logger.warning("sync_radarr_library: No movies returned from Radarr API or Radarr not configured.")
            return

        for movie_data in all_movies_data:
            try:
                logger.info(f"Syncing movie: {movie_data.get('title', 'N/A')} (Radarr ID: {movie_data.get('id', 'N/A')})")

                movie_values = {
                    "radarr_id": movie_data.get("id"),
                    "tmdb_id": movie_data.get("tmdbId"),
                    "imdb_id": movie_data.get("imdbId"),
                    "title": movie_data.get("title"),
                    "year": movie_data.get("year"),
                    "overview": movie_data.get("overview"),
                    "status": movie_data.get("status"),
                    "poster_url": next((img['url'] for img in movie_data.get('images', []) if img['coverType'] == 'poster'), None),
                    "fanart_url": next((img['url'] for img in movie_data.get('images', []) if img['coverType'] == 'fanart'), None),
                    "path_on_disk": movie_data.get("path"),
                    "has_file": bool(movie_data.get("hasFile", False)),
                    "monitored": bool(movie_data.get("monitored", False)),
                }
                movie_values_filtered = {k: v for k, v in movie_values.items() if v is not None}

                sql = """
                    INSERT INTO radarr_movies ({columns}, last_synced_at)
                    VALUES ({placeholders}, CURRENT_TIMESTAMP)
                    ON CONFLICT (radarr_id) DO UPDATE SET
                    {update_setters}, last_synced_at = CURRENT_TIMESTAMP;
                """.format(
                    columns=", ".join(movie_values_filtered.keys()),
                    placeholders=", ".join("?" for _ in movie_values_filtered),
                    update_setters=", ".join(f"{key} = excluded.{key}" for key in movie_values_filtered)
                )

                db.execute(sql, tuple(movie_values_filtered.values()))
                db.commit() # Commit after each movie
                movies_synced_count += 1
                logger.info(f"Successfully synced movie: {movie_data.get('title')}")

            except sqlite3.Error as e:
                db.rollback()
                logger.error(f"sync_radarr_library: Database error while syncing movie Radarr ID {movie_data.get('id', 'N/A')}: {e}")
            except Exception as e:
                db.rollback()
                logger.error(f"sync_radarr_library: Unexpected error while syncing movie Radarr ID {movie_data.get('id', 'N/A')}: {e}", exc_info=True)

        logger.info(f"Radarr library sync finished. Synced {movies_synced_count} movies.")
