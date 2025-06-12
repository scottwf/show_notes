import requests
import logging
import json
import sqlite3
import re
from thefuzz import fuzz
import urllib.parse
import datetime # For last_synced_at
from flask import current_app
from . import database

# logger = logging.getLogger(__name__)
# Use current_app.logger for consistency with routes.py logging
# Ensure current_app is imported if not already: from flask import current_app
import os # Make sure os is imported
from flask import url_for # Make sure url_for is imported

def cache_image(image_url, image_type_folder, cache_key_prefix, source_service):
    """
    Generates a proxied URL for an image, preparing it for caching via image_proxy.
    Handles constructing full URLs for Sonarr/Radarr if relative and adds API keys.

    Args:
        image_url (str): The original URL of the image.
        image_type_folder (str): 'posters' or 'background'. (Not directly used in this version for proxy URL generation but good for context)
        cache_key_prefix (str): A unique prefix for the image (e.g., "movie_tt12345_title"). (Not directly used here but good for context)
        source_service (str): 'sonarr' or 'radarr'.

    Returns:
        str: A URL to the image_proxy endpoint, or None if image_url is invalid.
    """
    if not image_url:
        return None

    # Ensure current_app context for database.get_setting
    with current_app.app_context():
        api_key = None
        base_url = None

        if source_service == 'sonarr':
            api_key = database.get_setting('sonarr_api_key')
            base_url = database.get_setting('sonarr_url')
        elif source_service == 'radarr':
            api_key = database.get_setting('radarr_api_key')
            base_url = database.get_setting('radarr_url')
        
        final_image_url = image_url

        # If URL is relative, prepend the service's base URL
        if base_url and final_image_url.startswith('/'):
            final_image_url = f"{base_url.rstrip('/')}{final_image_url}"
        
        # Add API key if it's a URL from the service that requires it (typically not for direct image URLs from TMDb etc.)
        # This logic assumes that if an API key is present, it should be added.
        # Sonarr/Radarr often serve images through their API that might not need an API key in the URL itself,
        # but if they are proxied through an endpoint that does, this might be relevant.
        # For direct image URLs (e.g. from TMDB via Sonarr/Radarr's 'remoteUrl'), API key is not needed.
        # However, the image_proxy itself will handle fetching with API key if the original URL is to the *arr service.
        # The main purpose here is to ensure the URL passed to image_proxy is complete.
        
        # The image_proxy route is responsible for the actual fetching and API key usage if needed.
        # This function just ensures the URL passed to image_proxy is the correct one to fetch.
        # If image_url is already absolute (e.g. from tmdb), it will be used as is.
        # If it's relative (e.g. /api/... from sonarr/radarr), it's made absolute here.

    # Return the URL that points to our image_proxy endpoint
    # The image_proxy will then fetch this 'final_image_url'
    return url_for('main.image_proxy', url=final_image_url, _external=False)

def _trigger_image_cache(proxy_image_url, item_title_for_logging=""):
    """
    Makes an internal GET request to the given proxy_image_url to trigger caching.
    Uses current_app.test_client().
    """
    if not proxy_image_url:
        return

    try:
        # An app context is needed for test_client and url_for if used inside
        # but cache_image already ran in an app_context to generate proxy_image_url
        with current_app.app_context():
            client = current_app.test_client()
            # The proxy_image_url is already a relative URL like '/image_proxy?url=...'
            # No need to use url_for again here.
            response = client.get(proxy_image_url) # proxy_image_url is already relative
            if response.status_code == 200:
                current_app.logger.info(f"Successfully pre-cached image for '{item_title_for_logging}': {proxy_image_url}")
            else:
                current_app.logger.warning(f"Failed to pre-cache image for '{item_title_for_logging}' via {proxy_image_url}. Status: {response.status_code}")
    except Exception as e:
        current_app.logger.error(f"Error pre-caching image for '{item_title_for_logging}' ({proxy_image_url}): {e}")

def _clean_title(title):
    """Removes year, special characters, and extra whitespace for better matching."""
    # Remove content in parentheses (like year)
    title = re.sub(r'\s*\(.*?\)\s*', '', title)
    # Remove special characters (punctuation) but keep letters, numbers, and whitespace
    title = re.sub(r'[^\w\s]', '', title)
    # Normalize whitespace to single spaces and strip
    title = re.sub(r'\s+', ' ', title).strip()
    return title

# --- Connection Test Functions --- 

def _test_service_connection(service_name, url_setting_name, api_key_setting_name=None, endpoint="", method='GET', expected_status=200, params=None, headers_extra=None):
    """Generic helper to test service connection."""
    service_url = None
    api_key = None

    with current_app.app_context():
        service_url = database.get_setting(url_setting_name)
        if api_key_setting_name:
            api_key = database.get_setting(api_key_setting_name)

    if not service_url:
        current_app.logger.info(f"_test_service_connection: {service_name} URL ('{url_setting_name}') not configured.")
        return False
    
    if api_key_setting_name and not api_key:
        current_app.logger.info(f"_test_service_connection: {service_name} API key ('{api_key_setting_name}') not configured, but required.")
        return False

    full_endpoint_url = f"{service_url.rstrip('/')}{endpoint}"
    headers = headers_extra or {}
    if api_key:
        # Common header for *arr services, Bazarr might differ slightly if it uses Bearer token etc.
        # For now, assuming X-Api-Key is common for those needing a key here.
        if service_name in ["Sonarr", "Radarr", "Bazarr"]:
             headers["X-Api-Key"] = api_key
        # Ollama does not use an API key for basic status checks.

    try:
        current_app.logger.debug(f"Testing {service_name} connection to {full_endpoint_url} with method {method}")
        response = requests.request(method, full_endpoint_url, headers=headers, params=params, timeout=5)
        if response.status_code == expected_status:
            current_app.logger.info(f"_test_service_connection: {service_name} connection successful to {full_endpoint_url}.")
            return True
        else:
            current_app.logger.warning(f"_test_service_connection: {service_name} connection test to {full_endpoint_url} failed with status {response.status_code}. Response: {response.text[:200]}")
            return False
    except requests.exceptions.Timeout:
        current_app.logger.error(f"_test_service_connection: Timeout connecting to {service_name} at {full_endpoint_url}")
        return False
    except requests.exceptions.ConnectionError:
        current_app.logger.error(f"_test_service_connection: Connection error for {service_name} at {full_endpoint_url}")
        return False
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"_test_service_connection: Generic error for {service_name} at {full_endpoint_url}: {e}")
        return False

def test_sonarr_connection():
    return _test_service_connection("Sonarr", 'sonarr_url', 'sonarr_api_key', '/api/v3/system/status')

def test_radarr_connection():
    return _test_service_connection("Radarr", 'radarr_url', 'radarr_api_key', '/api/v3/system/status')

def test_bazarr_connection():
    # Bazarr's API might be at /api/system/status or just /api/status. Let's try /api/system/status first.
    # It also might require authentication differently, but X-Api-Key is a common pattern.
    return _test_service_connection("Bazarr", 'bazarr_url', 'bazarr_api_key', '/api/system/status')

def test_ollama_connection():
    # Ollama usually doesn't require an API key for basic checks like listing tags or root ping.
    # A GET to the root or /api/tags should work if the server is up.
    return _test_service_connection("Ollama", 'ollama_url', endpoint='/api/tags') # /api/ps or just / might also work

# --- End Connection Test Functions --- 


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
        current_app.logger.error("get_all_sonarr_shows: Sonarr URL or API key not configured.")
        return []

    endpoint = f"{sonarr_url.rstrip('/')}/api/v3/series"
    headers = {"X-Api-Key": sonarr_api_key}

    try:
        response = requests.get(endpoint, headers=headers, timeout=10)
        response.raise_for_status()  # Raises HTTPError for bad responses (4XX or 5XX)
        return response.json()
    except requests.exceptions.Timeout:
        current_app.logger.error(f"get_all_sonarr_shows: Timeout connecting to Sonarr at {endpoint}")
        return []
    except requests.exceptions.ConnectionError:
        current_app.logger.error(f"get_all_sonarr_shows: Connection error connecting to Sonarr at {endpoint}")
        return []
    except requests.exceptions.HTTPError as e:
        current_app.logger.error(f"get_all_sonarr_shows: HTTP error fetching Sonarr shows: {e}. Response: {e.response.text if e.response else 'No response'}")
        return []
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"get_all_sonarr_shows: Generic error fetching Sonarr shows: {e}")
        return []
    except json.JSONDecodeError as e:
        current_app.logger.error(f"get_all_sonarr_shows: Error decoding Sonarr shows JSON response: {e}")
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
        current_app.logger.error(f"get_sonarr_episodes_for_show: Sonarr URL or API key not configured for series ID {sonarr_series_id}.")
        return []

    if not sonarr_series_id:
        current_app.logger.error("get_sonarr_episodes_for_show: sonarr_series_id cannot be None or empty.")
        return []

    endpoint = f"{sonarr_url.rstrip('/')}/api/v3/episode?seriesId={sonarr_series_id}"
    headers = {"X-Api-Key": sonarr_api_key}

    try:
        response = requests.get(endpoint, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        current_app.logger.error(f"get_sonarr_episodes_for_show: Timeout connecting to Sonarr at {endpoint} for series ID {sonarr_series_id}")
        return []
    except requests.exceptions.ConnectionError:
        current_app.logger.error(f"get_sonarr_episodes_for_show: Connection error connecting to Sonarr at {endpoint} for series ID {sonarr_series_id}")
        return []
    except requests.exceptions.HTTPError as e:
        current_app.logger.error(f"get_sonarr_episodes_for_show: HTTP error fetching episodes for series {sonarr_series_id}: {e}. Response: {e.response.text if e.response else 'No response'}")
        return []
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"get_sonarr_episodes_for_show: Generic error fetching episodes for series {sonarr_series_id}: {e}")
        return []
    except json.JSONDecodeError as e:
        current_app.logger.error(f"get_sonarr_episodes_for_show: Error decoding Sonarr episodes JSON response for series {sonarr_series_id}: {e}")
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
        current_app.logger.error("get_all_radarr_movies: Radarr URL or API key not configured.")
        return []

    endpoint = f"{radarr_url.rstrip('/')}/api/v3/movie"
    headers = {"X-Api-Key": radarr_api_key}

    try:
        response = requests.get(endpoint, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        current_app.logger.error(f"get_all_radarr_movies: Timeout connecting to Radarr at {endpoint}")
        return []
    except requests.exceptions.ConnectionError:
        current_app.logger.error(f"get_all_radarr_movies: Connection error connecting to Radarr at {endpoint}")
        return []
    except requests.exceptions.HTTPError as e:
        current_app.logger.error(f"get_all_radarr_movies: HTTP error fetching Radarr movies: {e}. Response: {e.response.text if e.response else 'No response'}")
        return []
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"get_all_radarr_movies: Generic error fetching Radarr movies: {e}")
        return []
    except json.JSONDecodeError as e:
        current_app.logger.error(f"get_all_radarr_movies: Error decoding Radarr movies JSON response: {e}")
        return []

def get_sonarr_poster(show_title):
    """
    Finds a Sonarr show by title and returns its poster URL.
    """
    current_app.logger.info(f"--- Starting Sonarr Poster Search for: '{show_title}' ---")
    with current_app.app_context():
        sonarr_url = database.get_setting('sonarr_url')
    if not sonarr_url:
        current_app.logger.error("get_sonarr_poster: Sonarr URL not configured.")
        return None

    all_shows = get_all_sonarr_shows()
    if not all_shows:
        current_app.logger.warning("get_sonarr_poster: Got no shows back from Sonarr.")
        return None

    plex_title = show_title
    for show in all_shows:
        sonarr_title = show.get('title', '')
        ratio = fuzz.token_set_ratio(plex_title, sonarr_title)
        current_app.logger.debug(f"Comparing '{plex_title}' with Sonarr's '{sonarr_title}'. Ratio: {ratio}")
        if ratio > 90:
            current_app.logger.info(f"MATCH FOUND! Title: '{sonarr_title}', Ratio: {ratio}")
            candidate_posters_data = []
            for image in show.get('images', []):
                if image.get('coverType') == 'poster':
                    url = image.get('remoteUrl') or image.get('url') # Prefer remoteUrl if available
                    if url:
                        candidate_posters_data.append({'url': url, 'is_remote': bool(image.get('remoteUrl'))})

            if not candidate_posters_data:
                current_app.logger.warning(f"Match found for '{sonarr_title}', but no poster images in object.")
                return None # Explicitly return None if no candidates

            preferred_poster_url = None
            # Try to find a poster URL whose path does not contain '/season/'
            for poster_data in candidate_posters_data:
                temp_full_url_for_path_check = poster_data['url']
                if not temp_full_url_for_path_check.startswith('http'): # Handle relative URLs for path checking
                    temp_full_url_for_path_check = f"{sonarr_url.rstrip('/')}/{poster_data['url'].lstrip('/')}"
                
                parsed_image_url = urllib.parse.urlparse(temp_full_url_for_path_check)
                if '/season/' not in parsed_image_url.path.lower():
                    preferred_poster_url = poster_data['url']
                    break # Found a preferred non-season specific poster
            
            # If no non-season poster was found, just take the first candidate overall
            if not preferred_poster_url and candidate_posters_data:
                preferred_poster_url = candidate_posters_data[0]['url']
            
            final_poster_url = None
            if preferred_poster_url:
                if not preferred_poster_url.startswith('http'): # Construct full URL if relative
                    base_url = sonarr_url.rstrip('/')
                    img_path = preferred_poster_url.lstrip('/')
                    final_poster_url = f"{base_url}/{img_path}"
                else:
                    final_poster_url = preferred_poster_url
            
            if final_poster_url:
                current_app.logger.info(f"Selected Sonarr poster for '{sonarr_title}'. URL: {final_poster_url}")
                return final_poster_url
            
            # This path should ideally not be reached if candidate_posters_data was not empty
            current_app.logger.warning(f"Match found for '{sonarr_title}', but could not determine a final poster URL.")
    
    current_app.logger.warning(f"--- Sonarr Poster Search FAILED for: '{show_title}' --- No show met the 90% ratio threshold.")
    return None

def get_radarr_poster(movie_title):
    """
    Finds a Radarr movie by title and returns its poster URL.
    """
    current_app.logger.info(f"--- Starting Radarr Poster Search for: '{movie_title}' ---")
    with current_app.app_context():
        radarr_url = database.get_setting('radarr_url')
    if not radarr_url:
        current_app.logger.error("get_radarr_poster: Radarr URL not configured.")
        return None

    all_movies = get_all_radarr_movies()
    if not all_movies:
        current_app.logger.warning("get_radarr_poster: Got no movies back from Radarr.")
        return None

    plex_title = movie_title
    for movie in all_movies:
        radarr_title = movie.get('title', '')
        ratio = fuzz.token_set_ratio(plex_title, radarr_title)
        current_app.logger.debug(f"Comparing '{plex_title}' with Radarr's '{radarr_title}'. Ratio: {ratio}")
        if ratio > 90:
            current_app.logger.info(f"MATCH FOUND! Title: '{radarr_title}', Ratio: {ratio}")
            for image in movie.get('images', []):
                if image.get('coverType') == 'poster' and image.get('url'):
                    relative_url = image.get('url')
                    full_url = f"{radarr_url.rstrip('/')}{relative_url}"
                    current_app.logger.info(f"Found Radarr poster for '{movie_title}'. URL: {full_url}")
                    return full_url
            current_app.logger.warning(f"Match found for '{radarr_title}', but no poster image in object.")

    current_app.logger.warning(f"--- Radarr Poster Search FAILED for: '{movie_title}' --- No movie met the 90% ratio threshold.")
    return None


def sync_sonarr_library():
    processed_count = 0
    """
    Fetches all shows, their seasons, and episodes from Sonarr
    and syncs them with the local database.
    """
    current_app.logger.info("Starting Sonarr library sync.")
    shows_synced_count = 0
    episodes_synced_count = 0

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

                # Prepare show data
                raw_poster_url = next((img.get('url') for img in show_data.get('images', []) if img.get('coverType') == 'poster'), None)
                raw_fanart_url = next((img.get('url') for img in show_data.get('images', []) if img.get('coverType') == 'fanart'), None)

                final_poster_url = raw_poster_url # Default to original
                if sonarr_base_url and raw_poster_url and raw_poster_url.startswith('/'):
                    final_poster_url = f"{sonarr_base_url}{raw_poster_url}"
                
                final_fanart_url = raw_fanart_url # Default to original
                if sonarr_base_url and raw_fanart_url and raw_fanart_url.startswith('/'):
                    final_fanart_url = f"{sonarr_base_url}{raw_fanart_url}"

                show_values = {
                    "sonarr_id": current_sonarr_id,
                    "tvdb_id": show_data.get("tvdbId"),
                    "imdb_id": show_data.get("imdbId"),
                    "status": show_data.get("status"),
                    "ended": show_data.get("ended", False),

                    "overview": show_data.get("overview"),
                    "status": show_data.get("status"),
                    "season_count": len(show_data.get("seasons", [])), # More reliable than show_data.get("seasonCount") sometimes
                    "episode_count": show_data.get("episodeCount"),
                    "episode_file_count": show_data.get("episodeFileCount"),
                    "poster_url": final_poster_url,
                    "fanart_url": final_fanart_url,
                    "path_on_disk": show_data.get("path"),
                }

                # Filter out None values to avoid inserting NULL for non-nullable or for cleaner updates
                show_values_filtered = {k: v for k, v in show_values.items() if v is not None}

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

                # Add to image_cache_queue
                if final_poster_url:
                    parsed_poster_url = urllib.parse.urlparse(final_poster_url)
                    poster_target_filename = f"{hash(parsed_poster_url.path)}.jpg"
                    try:
                        db.execute(
                            "INSERT INTO image_cache_queue (item_type, item_db_id, image_url, image_kind, target_filename) VALUES (?, ?, ?, ?, ?)",
                            ('show', show_db_id, final_poster_url, 'poster', poster_target_filename)
                        )
                        current_app.logger.info(f"Queued poster for show ID {show_db_id}: {final_poster_url}")
                    except sqlite3.Error as e:
                        current_app.logger.error(f"Failed to queue poster for show ID {show_db_id}: {e}")

                if final_fanart_url:
                    parsed_fanart_url = urllib.parse.urlparse(final_fanart_url)
                    fanart_target_filename = f"{hash(parsed_fanart_url.path)}.jpg"
                    try:
                        db.execute(
                            "INSERT INTO image_cache_queue (item_type, item_db_id, image_url, image_kind, target_filename) VALUES (?, ?, ?, ?, ?)",
                            ('show', show_db_id, final_fanart_url, 'fanart', fanart_target_filename)
                        )
                        current_app.logger.info(f"Queued fanart for show ID {show_db_id}: {final_fanart_url}")
                    except sqlite3.Error as e:
                        current_app.logger.error(f"Failed to queue fanart for show ID {show_db_id}: {e}")

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
                        episode_values = {
                            "season_id": season_db_id,
                            "sonarr_show_id": sonarr_show_id,  # Sonarr's seriesId
                            "sonarr_episode_id": episode_data.get("id"),  # Sonarr's episodeId
                            "episode_number": episode_data.get("episodeNumber"),
                            "title": episode_data.get("title"),
                            "overview": episode_data.get("overview"),
                            "air_date_utc": episode_data.get("airDateUtc"),
                            "has_file": bool(episode_data.get("hasFile", False)),
                        }
                        episode_values_filtered = {k: v for k, v in episode_values.items() if v is not None}

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
                            "season_id": season_db_id_fb,
                            "sonarr_show_id": sonarr_show_id,
                            "sonarr_episode_id": episode_data.get("id"),
                            "episode_number": episode_data.get("episodeNumber"),
                            "title": episode_data.get("title"),
                            "overview": episode_data.get("overview"),
                            "air_date_utc": episode_data.get("airDateUtc"),
                            "has_file": bool(episode_data.get("hasFile", False)),
                            # "monitored": bool(episode_data.get("monitored", False)), # Removed
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
        return shows_synced_count

def sync_radarr_library():
    processed_count = 0
    """
    Fetches all movies from Radarr and syncs them with the local database.
    """
    current_app.logger.info("Starting Radarr library sync.")
    movies_synced_count = 0

    with current_app.app_context():
        db = database.get_db()

        settings_row = db.execute('SELECT radarr_url FROM settings LIMIT 1').fetchone()
        radarr_base_url = settings_row['radarr_url'].rstrip('/') if settings_row and 'radarr_url' in settings_row and settings_row['radarr_url'] else None
        if not radarr_base_url:
            current_app.logger.warning("sync_radarr_library: Radarr URL not found in settings. Cannot form absolute image URLs if they are relative.")

        all_movies_data = get_all_radarr_movies()

        if not all_movies_data:
            current_app.logger.warning("sync_radarr_library: No movies returned from Radarr API or Radarr not configured.")
            return processed_count

        for movie_data in all_movies_data:
            try:
                current_app.logger.info(f"Syncing movie: {movie_data.get('title', 'N/A')} (Radarr ID: {movie_data.get('id', 'N/A')})")

                raw_poster_url = next((img.get('url') for img in movie_data.get('images', []) if img.get('coverType') == 'poster'), None)
                raw_fanart_url = next((img.get('url') for img in movie_data.get('images', []) if img.get('coverType') == 'fanart'), None)

                final_poster_url = raw_poster_url # Default to original
                if radarr_base_url and raw_poster_url and raw_poster_url.startswith('/'):
                    final_poster_url = f"{radarr_base_url}{raw_poster_url}"
                
                final_fanart_url = raw_fanart_url # Default to original
                if radarr_base_url and raw_fanart_url and raw_fanart_url.startswith('/'):
                    final_fanart_url = f"{radarr_base_url}{raw_fanart_url}"
                
                movie_values = {
                    "radarr_id": movie_data.get("id"),
                    "tmdb_id": movie_data.get("tmdbId"),
                    "imdb_id": movie_data.get("imdbId"),
                    "title": movie_data.get("title"),
                    "year": movie_data.get("year"),
                    "overview": movie_data.get("overview"),
                    "status": movie_data.get("status"),
                    "poster_url": final_poster_url,
                    "fanart_url": final_fanart_url,
                    "path_on_disk": movie_data.get("path"),
                    "has_file": bool(movie_data.get("hasFile", False)),
                    "last_synced_at": datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                }
                movie_values_filtered = {k: v for k, v in movie_values.items() if v is not None}

                sql = """
                    INSERT INTO radarr_movies ({columns}, last_synced_at)
                    VALUES ({placeholders}, CURRENT_TIMESTAMP)
                    ON CONFLICT (radarr_id) DO UPDATE SET
                    {update_setters}, last_synced_at = CURRENT_TIMESTAMP
                    RETURNING id;
                """.format(
                    columns=", ".join(movie_values_filtered.keys()),
                    placeholders=", ".join("?" for _ in movie_values_filtered),
                    update_setters=", ".join(f"{key} = excluded.{key}" for key in movie_values_filtered)
                )

                cursor = db.execute(sql, tuple(movie_values_filtered.values()))
                movie_db_id_row = cursor.fetchone()
                if not movie_db_id_row:
                    current_app.logger.error(f"sync_radarr_library: Failed to get DB ID for Radarr movie ID {movie_data.get('id')}")
                    continue # Skip this movie if ID retrieval failed
                movie_db_id = movie_db_id_row[0]

                # Add to image_cache_queue
                if final_poster_url:
                    parsed_poster_url = urllib.parse.urlparse(final_poster_url)
                    poster_target_filename = f"{hash(parsed_poster_url.path)}.jpg"
                    try:
                        db.execute(
                            "INSERT INTO image_cache_queue (item_type, item_db_id, image_url, image_kind, target_filename) VALUES (?, ?, ?, ?, ?)",
                            ('movie', movie_db_id, final_poster_url, 'poster', poster_target_filename)
                        )
                        current_app.logger.info(f"Queued poster for movie ID {movie_db_id}: {final_poster_url}")
                    except sqlite3.Error as e:
                        current_app.logger.error(f"Failed to queue poster for movie ID {movie_db_id}: {e}")

                if final_fanart_url:
                    parsed_fanart_url = urllib.parse.urlparse(final_fanart_url)
                    fanart_target_filename = f"{hash(parsed_fanart_url.path)}.jpg"
                    try:
                        db.execute(
                            "INSERT INTO image_cache_queue (item_type, item_db_id, image_url, image_kind, target_filename) VALUES (?, ?, ?, ?, ?)",
                            ('movie', movie_db_id, final_fanart_url, 'fanart', fanart_target_filename)
                        )
                        current_app.logger.info(f"Queued fanart for movie ID {movie_db_id}: {final_fanart_url}")
                    except sqlite3.Error as e:
                        current_app.logger.error(f"Failed to queue fanart for movie ID {movie_db_id}: {e}")

                db.commit() # Commit after each movie and its queued images
                movies_synced_count += 1
                current_app.logger.info(f"Successfully synced movie: {movie_data.get('title')}")

            except sqlite3.Error as e:
                db.rollback()
                current_app.logger.error(f"sync_radarr_library: Database error while syncing movie Radarr ID {movie_data.get('id', 'N/A')}: {e}")
            except Exception as e:
                db.rollback()
                current_app.logger.error(f"sync_radarr_library: Unexpected error while syncing movie Radarr ID {movie_data.get('id', 'N/A')}: {e}", exc_info=True)

        current_app.logger.info(f"Radarr library sync finished. Synced {movies_synced_count} movies.")
        return movies_synced_count
