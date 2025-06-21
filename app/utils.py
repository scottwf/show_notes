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

# logger = logging.getLogger(__name__) # Standard logging
# current_app.logger is used for Flask specific logging within app context

import os
from flask import url_for

"""
Utility functions for the ShowNotes application.

This module provides a collection of helper functions that support various operations
within the application. These utilities are designed to be reusable and encapsulate
specific functionalities, particularly for interacting with external services and
handling data transformations.

Key Functionalities:
- **Service Interaction:** Functions to communicate with external APIs such as
  Sonarr, Radarr, Bazarr, Ollama, Tautulli, and Pushover. This includes fetching
  data, synchronizing libraries, and testing service connections.
- **Data Synchronization:** Core logic for pulling library information (shows, movies,
  episodes) and watch history from services and storing it in the local database.
- **Connection Testing:** A suite of functions to validate connectivity and
  authentication with the configured external services, providing feedback to the user.
- **Image Handling:** Helper functions to construct URLs for proxying and caching
  images from external sources, ensuring consistent and efficient image delivery.
- **Data Transformation:** Utility functions for cleaning strings, formatting
  datetime objects, and other data manipulations required across the application.
"""

def cache_image(image_url, image_type_folder, cache_key_prefix, source_service):
    """
    Constructs a proxied URL for an image, to be handled by the image_proxy route.

    This function takes an image URL from an external service (like Sonarr or Radarr)
    and prepares a new URL that points to this application's `image_proxy` endpoint.
    It correctly resolves relative URLs to absolute ones using the service's base
    URL from the settings.

    The actual fetching and caching of the image is performed by the `image_proxy`
    route when this generated URL is accessed by a client (e.g., an `<img>` tag).

    Args:
        image_url (str): The original URL of the image, which can be relative (e.g., "/image/4.jpg")
                         or absolute.
        image_type_folder (str): A string indicating the type of image (e.g., 'poster', 'background').
                                 This is primarily for organizational context for the calling function.
        cache_key_prefix (str): A prefix used to construct a unique cache key, helping to avoid
                                collisions (e.g., 'show_poster_{tmdb_id}').
        source_service (str): The originating service ('sonarr' or 'radarr'). This is crucial for
                              determining the correct base URL and API key to use for resolving
                              relative paths.

    Returns:
        str or None: A string containing the relative URL for the `main.image_proxy` endpoint
                     (e.g., "/image_proxy?url=..."). Returns None if the input `image_url` is empty.
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
    Internally requests a proxied image URL to trigger the caching mechanism.

    This function uses the Flask test client to make a GET request to a URL
    generated by `cache_image`. This is useful for pre-caching images in the
    background during library syncs, so they are readily available when a user
    first loads a page.

    Args:
        proxy_image_url (str): The relative URL for the `image_proxy` endpoint, as
                               generated by the `cache_image` function.
        item_title_for_logging (str, optional): A descriptive name of the item being
                                                cached (e.g., "Poster for 'The Office'")
                                                for clearer log messages. Defaults to "".
    """
    if not proxy_image_url:
        return

    try:
        # Ensure an app context is available, especially if this function
        # might be called from a background thread or script without one.
        with current_app.app_context():
            client = current_app.test_client()
            # proxy_image_url is expected to be a relative path like '/image_proxy?url=...'
            response = client.get(proxy_image_url)
            if response.status_code == 200:
                current_app.logger.info(f"Successfully triggered image_proxy for '{item_title_for_logging}': {proxy_image_url}")
            else:
                current_app.logger.warning(f"Failed to trigger image_proxy for '{item_title_for_logging}' via {proxy_image_url}. Status: {response.status_code}")
    except Exception as e:
        current_app.logger.error(f"Error triggering image_proxy for '{item_title_for_logging}' ({proxy_image_url}): {e}")

def _clean_title(title):
    """
    Cleans a title string to provide a simpler, more consistent format for matching.

    This function performs several operations to normalize a title:
    1.  Removes content within parentheses (e.g., "(2022)").
    2.  Strips out special characters and punctuation, leaving only alphanumeric
        characters and whitespace.
    3.  Normalizes multiple whitespace characters into a single space.
    4.  Removes any leading or trailing whitespace.

    Args:
        title (str): The input title string to be cleaned.

    Returns:
        str: The cleaned and normalized title string.
    """
    # Remove content in parentheses (like year)
    title = re.sub(r'\s*\(.*?\)\s*', '', title)
    # Remove special characters (punctuation) but keep letters, numbers, and whitespace
    title = re.sub(r'[^\w\s]', '', title)
    # Normalize whitespace to single spaces and strip
    title = re.sub(r'\s+', ' ', title).strip()
    return title

# --- Connection Test Functions --- 

def _test_service_connection(service_name, url_setting_name, api_key_setting_name=None, endpoint="", method='GET', expected_status=200, params=None, headers_extra=None, url_override=None, api_key_override=None):
    """
    A generic helper to test the connection to an external service.

    This function abstracts the logic for testing a service endpoint. It fetches
    the service URL and API key from the database (or uses provided overrides),
    constructs the full request URL, and makes an HTTP request. It then checks if the
    response status code matches the expected code for a successful connection.

    This function is intended to be called by specific test functions like
    `test_sonarr_connection`.

    Args:
        service_name (str): The user-friendly name of the service (e.g., "Sonarr") for logging.
        url_setting_name (str): The key for the service's URL in the `settings` table.
        api_key_setting_name (str, optional): The key for the service's API key in the
                                              `settings` table. Defaults to None.
        endpoint (str, optional): The API endpoint path to test (e.g., "/api/v3/system/status").
                                  Defaults to "".
        method (str, optional): The HTTP method to use for the test request. Defaults to 'GET'.
        expected_status (int, optional): The HTTP status code that indicates a successful
                                         connection. Defaults to 200.
        params (dict, optional): A dictionary of query parameters for the request. Defaults to None.
        headers_extra (dict, optional): A dictionary of any extra headers to include. Defaults to None.
        url_override (str, optional): A specific URL to use instead of fetching from settings.
                                      This is useful for testing new, unsaved settings. Defaults to None.
        api_key_override (str, optional): A specific API key to use instead of fetching from settings.
                                          Defaults to None.

    Returns:
        tuple: A tuple containing:
               - bool: True if the connection was successful, False otherwise.
               - str: A user-friendly message describing the result (e.g., "Connection successful."
                      or an error message).
    """
    service_url = None
    api_key = None

    with current_app.app_context():
        if url_override:
            service_url = url_override
        else:
            service_url = database.get_setting(url_setting_name)
        if api_key_setting_name:
            if api_key_override:
                api_key = api_key_override
            else:
                api_key = database.get_setting(api_key_setting_name)

    if not service_url:
        msg = f"{service_name} URL ('{url_setting_name}') not configured."
        current_app.logger.info(f"_test_service_connection: {msg}")
        return False, msg
    
    if api_key_setting_name and not api_key:
        msg = f"{service_name} API key ('{api_key_setting_name}') not configured, but required."
        current_app.logger.info(f"_test_service_connection: {msg}")
        return False, msg

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
            return True, "Connection successful."
        else:
            msg = f"Connection test to {full_endpoint_url} failed with status {response.status_code}. Response: {response.text[:200]}"
            current_app.logger.warning(f"_test_service_connection: {service_name} {msg}")
            return False, msg
    except requests.exceptions.Timeout:
        msg = f"Timeout connecting to {service_name} at {full_endpoint_url}"
        current_app.logger.error(f"_test_service_connection: {msg}")
        return False, msg
    except requests.exceptions.ConnectionError:
        msg = f"Connection error for {service_name} at {full_endpoint_url}"
        current_app.logger.error(f"_test_service_connection: {msg}")
        return False, msg
    except requests.exceptions.RequestException as e:
        msg = f"Generic error for {service_name} at {full_endpoint_url}: {e}"
        current_app.logger.error(f"_test_service_connection: {msg}")
        return False, msg

def test_sonarr_connection():
    """Tests the connection to the configured Sonarr service."""
    return _test_service_connection("Sonarr", 'sonarr_url', 'sonarr_api_key', '/api/v3/system/status')

def test_radarr_connection():
    """Tests the connection to the configured Radarr service."""
    return _test_service_connection("Radarr", 'radarr_url', 'radarr_api_key', '/api/v3/system/status')

def test_bazarr_connection():
    """
    Tests the connection to the configured Bazarr service.

    Note: Assumes a common API endpoint and authentication method (X-Api-Key).
    """
    # Bazarr's API might be at /api/system/status or just /api/status. Let's try /api/system/status first.
    # It also might require authentication differently, but X-Api-Key is a common pattern.
    return _test_service_connection("Bazarr", 'bazarr_url', 'bazarr_api_key', '/api/system/status')

def test_ollama_connection():
    """
    Tests the connection to the configured Ollama service.
    
    Ollama doesn't require an API key for its standard status endpoints.
    """
    # Ollama usually doesn't require an API key for basic checks like listing tags or root ping.
    # A GET to the root or /api/tags should work if the server is up.
    return _test_service_connection("Ollama", 'ollama_url', endpoint='/api/tags') # /api/ps or just / might also work

# --- End Connection Test Functions ---


# --- Connection Test Functions (with Parameters) ---

def _test_service_connection_with_params(service_name, service_url, api_key=None, endpoint="", method='GET', expected_status=200, params=None, headers_extra=None, body_json=None):
    """
    Generic helper to test a service connection using explicitly provided parameters.

    This is similar to `_test_service_connection` but is designed to be used when
    testing settings that have not yet been saved to the database (e.g., from a
    web form). It takes the URL and API key as direct arguments instead of
    fetching them from the database.

    Args:
        service_name (str): User-friendly name of the service for logging.
        service_url (str): The URL of the service to test.
        api_key (str, optional): The API key for the service. Defaults to None.
        endpoint (str, optional): API endpoint path. Defaults to "".
        method (str, optional): HTTP method. Defaults to 'GET'.
        expected_status (int, optional): Expected success status code. Defaults to 200.
        params (dict, optional): Query parameters. Defaults to None.
        headers_extra (dict, optional): Extra request headers. Defaults to None.
        body_json (dict, optional): A dictionary to be sent as the JSON body of the
                                    request (for 'POST' or 'PUT' methods). Defaults to None.

    Returns:
        tuple: A tuple containing:
               - bool: True on success, False on failure.
               - str: A message describing the outcome.
    """
    if not service_url:
        msg = f"{service_name} URL not provided."
        current_app.logger.info(f"_test_service_connection_with_params: {msg}")
        return False, msg
    
    required_key_services = ["Sonarr", "Radarr", "Bazarr"]
    if service_name in required_key_services and not api_key:
        current_app.logger.info(f"_test_service_connection_with_params: {service_name} API key not provided, but required for this service test.")
        return False, f"{service_name} API key not provided."

    full_endpoint_url = f"{service_url.rstrip('/')}{endpoint}"
    headers = headers_extra or {}
    if api_key and service_name in required_key_services:
        headers["X-Api-Key"] = api_key

    try:
        current_app.logger.debug(f"Testing {service_name} connection to {full_endpoint_url} with method {method} using provided params.")
        response = requests.request(method, full_endpoint_url, headers=headers, params=params, json=body_json, timeout=5)
        if response.status_code == expected_status:
            current_app.logger.info(f"_test_service_connection_with_params: {service_name} connection successful to {full_endpoint_url}.")
            return True, None
        else:
            error_message = f"{service_name} connection test to {full_endpoint_url} failed with status {response.status_code}. Response: {response.text[:200]}"
            current_app.logger.warning(f"_test_service_connection_with_params: {error_message}")
            return False, error_message
    except requests.exceptions.Timeout:
        error_message = f"Timeout connecting to {service_name} at {full_endpoint_url}"
        current_app.logger.error(f"_test_service_connection_with_params: {error_message}")
        return False, error_message
    except requests.exceptions.ConnectionError:
        error_message = f"Connection error for {service_name} at {full_endpoint_url}"
        current_app.logger.error(f"_test_service_connection_with_params: {error_message}")
        return False, error_message
    except requests.exceptions.RequestException as e:
        error_message = f"Generic error for {service_name} at {full_endpoint_url}: {e}"
        current_app.logger.error(f"_test_service_connection_with_params: {error_message}")
        return False, error_message

def test_sonarr_connection_with_params(url, api_key):
    """
    Tests the Sonarr connection using a provided URL and API key.

    Args:
        url (str): The Sonarr URL to test.
        api_key (str): The Sonarr API key to test.

    Returns:
        tuple: (bool, str) indicating success and a result message.
    """
    return _test_service_connection_with_params("Sonarr", url, api_key, '/api/v3/system/status')

def test_radarr_connection_with_params(url, api_key):
    """
    Tests the Radarr connection using a provided URL and API key.

    Args:
        url (str): The Radarr URL to test.
        api_key (str): The Radarr API key to test.

    Returns:
        tuple: (bool, str) indicating success and a result message.
    """
    return _test_service_connection_with_params("Radarr", url, api_key, '/api/v3/system/status')

def test_bazarr_connection_with_params(url, api_key):
    """

    Tests the Bazarr connection using a provided URL and API key.

    Args:
        url (str): The Bazarr URL to test.
        api_key (str): The Bazarr API key to test.

    Returns:
        tuple: (bool, str) indicating success and a result message.
    """
    return _test_service_connection_with_params("Bazarr", url, api_key, '/api/system/status')

def test_ollama_connection_with_params(url):
    """
    Tests the Ollama connection using a provided URL.

    Args:
        url (str): The Ollama URL to test.

    Returns:
        tuple: (bool, str) indicating success and a result message.
    """
    return _test_service_connection_with_params("Ollama", url, endpoint='/api/tags')

def test_pushover_notification_with_params(token, user_key):
    """
    Tests the Pushover service by sending a test notification.

    Args:
        token (str): The Pushover application API token.
        user_key (str): The Pushover user/group key.

    Returns:
        tuple: (bool, str) indicating success and a result message.
    """
    if not token or not user_key:
        return False, "Pushover Token and User Key must be provided."

    url = "https://api.pushover.net/1/messages.json"
    payload = {
        'token': token,
        'user': user_key,
        'message': 'This is a test notification from ShowNotes!',
        'title': 'ShowNotes Test'
    }
    try:
        response = requests.post(url, data=payload, timeout=5)
        response_data = response.json()
        if response_data.get('status') == 1:
            current_app.logger.info("Pushover test notification sent successfully.")
            return True, None
        else:
            error_message = response_data.get('errors', ['Unknown error'])
            current_app.logger.warning(f"Pushover test failed: {error_message}")
            return False, ', '.join(error_message)
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Error sending Pushover test notification: {e}")
        return False, str(e)

# --- End Connection Test Functions (with Parameters) --- 


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

def get_all_radarr_movies():
    """
    Fetches a list of all movies from the configured Radarr instance.

    Communicates with the Radarr API to retrieve the complete movie library.

    Returns:
        list or None: A list of dictionaries, where each dictionary represents a movie.
                      Returns None if Radarr is not configured or an error occurs.
    """
    radarr_url = None
    radarr_api_key = None
    with current_app.app_context():
        radarr_url = database.get_setting('radarr_url')
        radarr_api_key = database.get_setting('radarr_api_key')

    if not radarr_url or not radarr_api_key:
        current_app.logger.error("get_all_radarr_movies: Radarr URL or API key not configured.")
        return None

    endpoint = f"{radarr_url.rstrip('/')}/api/v3/movie"
    headers = {"X-Api-Key": radarr_api_key}

    try:
        response = requests.get(endpoint, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        current_app.logger.error(f"get_all_radarr_movies: Timeout connecting to Radarr at {endpoint}")
        return None
    except requests.exceptions.ConnectionError:
        current_app.logger.error(f"get_all_radarr_movies: Connection error connecting to Radarr at {endpoint}")
        return None
    except requests.exceptions.HTTPError as e:
        current_app.logger.error(f"get_all_radarr_movies: HTTP error fetching Radarr movies: {e}. Response: {e.response.text if e.response else 'No response'}")
        return None
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"get_all_radarr_movies: Generic error fetching Radarr movies: {e}")
        return None
    except json.JSONDecodeError as e:
        current_app.logger.error(f"get_all_radarr_movies: Error decoding Radarr movies JSON response: {e}")
        return None

def get_sonarr_poster(show_title):
    """
    Retrieves the poster URL for a specific show from Sonarr's library data.

    This function first fetches all shows from Sonarr and then performs a fuzzy
    string match on the title to find the correct show and return its poster URL.
    This can be inefficient and is a candidate for optimization by using a local
    database cache first.

    Args:
        show_title (str): The title of the show to search for.

    Returns:
        str or None: The URL of the show's poster. Returns None if the show is not
                     found or an error occurs.
    """
    # This function is inefficient as it fetches all shows.
    # A better approach would be to query the local `sonarr_shows` table.
    # Consider this function for deprecation or refactoring.
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
            current_app.logger.warning(f"--- Sonarr Poster Search FAILED for: '{show_title}' --- No show met the 90% ratio threshold.")
    
    return None

def get_radarr_poster(movie_title):
    """
    Retrieves the poster URL for a specific movie from Radarr's library data.

    Similar to `get_sonarr_poster`, this function fetches all movies from Radarr
    and uses fuzzy matching to find the correct one. It is also a candidate for
    optimization.

    Args:
        movie_title (str): The title of the movie to search for.

    Returns:
        str or None: The URL of the movie's poster, or None if not found.
    """
    # This function is inefficient. Refactor to use the local DB.
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
                show_tmdb_id_for_filename = show_data.get("tmdbId")

                if final_poster_url:
                    if show_tmdb_id_for_filename:
                        poster_target_filename = f"{show_tmdb_id_for_filename}.jpg"
                        try:
                            db.execute(
                                "INSERT INTO image_cache_queue (item_type, item_db_id, image_url, image_kind, target_filename) VALUES (?, ?, ?, ?, ?)",
                                ('show', show_db_id, final_poster_url, 'poster', poster_target_filename)
                            )
                            current_app.logger.info(f"Queued poster for show ID {show_db_id} (TMDB ID {show_tmdb_id_for_filename}): {final_poster_url}")
                        except sqlite3.Error as e:
                            current_app.logger.error(f"Failed to queue poster for show ID {show_db_id}: {e}")
                    else:
                        current_app.logger.warning(f"Skipping poster queue for show ID {show_db_id} (Title: {show_data.get('title', 'N/A')}) due to missing TMDB ID.")

                if final_fanart_url:
                    if show_tmdb_id_for_filename:
                        fanart_target_filename = f"{show_tmdb_id_for_filename}.jpg"
                        try:
                            db.execute(
                                "INSERT INTO image_cache_queue (item_type, item_db_id, image_url, image_kind, target_filename) VALUES (?, ?, ?, ?, ?)",
                                ('show', show_db_id, final_fanart_url, 'background', fanart_target_filename)
                            )
                            current_app.logger.info(f"Queued fanart for show ID {show_db_id} (TMDB ID {show_tmdb_id_for_filename}): {final_fanart_url}")
                        except sqlite3.Error as e:
                            current_app.logger.error(f"Failed to queue fanart for show ID {show_db_id}: {e}")
                    else:
                        current_app.logger.warning(f"Skipping fanart queue for show ID {show_db_id} (Title: {show_data.get('title', 'N/A')}) due to missing TMDB ID.")

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
    """
    Synchronizes the entire Radarr library with the local database.

    This function mirrors the functionality of `sync_sonarr_library` but for movies:
    1.  Fetches all movies from the Radarr API.
    2.  Iterates through each movie and "upserts" its data into the `radarr_movies` table.
    3.  Queues poster and fanart images for background caching.
    4.  Removes any movies from the local database that no longer exist in Radarr.

    This is typically triggered manually from the admin panel.

    Returns:
        int: The number of movies that were successfully processed and synced.
    """
    current_app.logger.info("Starting Radarr library synchronization with new details...")
    movies_synced_count = 0
    movies_added_count = 0
    movies_updated_count = 0

    all_radarr_movies = get_all_radarr_movies()
    if not all_radarr_movies:
        current_app.logger.warning("sync_radarr_library: No movies returned from Radarr or Radarr not configured.")
        with current_app.app_context():
            conn = database.get_db_connection()
            try:
                database.update_sync_status(conn, 'radarr', 'failed' if not database.get_setting('radarr_url') else 'success_no_data')
            finally:
                conn.close()
        return {'status': 'warning', 'message': 'No movies returned from Radarr or Radarr not configured.', 'synced': 0, 'added': 0, 'updated': 0}

    radarr_url = None
    with current_app.app_context():
        radarr_url = database.get_setting('radarr_url')
        conn = database.get_db_connection()
    
    try:
        cursor = conn.cursor()
        for movie_data in all_radarr_movies:
            radarr_movie_id = movie_data.get('id')
            if not radarr_movie_id:
                current_app.logger.warning(f"sync_radarr_library: Movie data missing 'id'. Skipping. Data: {movie_data.get('title', 'N/A')}")
                continue

            # Extract poster and fanart URLs
            poster_url = None
            fanart_url = None
            if movie_data.get('images'):
                for image in movie_data['images']:
                    # Prefer remoteUrl (absolute) over url (relative)
                    img_src = image.get('remoteUrl') or image.get('url')
                    if img_src and img_src.startswith('/') and radarr_url:
                        img_src = f"{radarr_url.rstrip('/')}{img_src}"
                    
                    if image.get('coverType') == 'poster':
                        poster_url = img_src
                    elif image.get('coverType') == 'fanart':
                        fanart_url = img_src

            # Safely extract nested rating info
            ratings_data = movie_data.get('ratings', {})
            imdb_rating_info = ratings_data.get('imdb', {})
            tmdb_rating_info = ratings_data.get('tmdb', {})
            rt_rating_info = ratings_data.get('rottenTomatoes', {})

            # Safely extract original language name
            original_language_obj = movie_data.get('originalLanguage', {})
            original_language_name = original_language_obj.get('name')

            # Convert genres list to JSON string
            genres_list = movie_data.get('genres', [])
            genres_json = json.dumps(genres_list) if genres_list else None

            movie_to_insert = {
                'radarr_id': radarr_movie_id,
                'title': movie_data.get('title'),
                'year': movie_data.get('year'),
                'tmdb_id': movie_data.get('tmdbId'),
                'imdb_id': movie_data.get('imdbId'),
                'overview': movie_data.get('overview'),
                'poster_url': poster_url,
                'fanart_url': fanart_url,
                'release_date': movie_data.get('releaseDate'), # Or physicalRelease / digitalRelease if preferred
                'original_language_name': original_language_name,
                'studio': movie_data.get('studio'),
                'runtime': movie_data.get('runtime'),
                'status': movie_data.get('status'),
                'genres': genres_json,
                'certification': movie_data.get('certification'),
                'popularity': movie_data.get('popularity'),
                'original_title': movie_data.get('originalTitle'),
                'ratings_imdb_value': imdb_rating_info.get('value'),
                'ratings_imdb_votes': imdb_rating_info.get('votes'),
                'ratings_tmdb_value': tmdb_rating_info.get('value'),
                'ratings_tmdb_votes': tmdb_rating_info.get('votes'),
                'ratings_rottenTomatoes_value': rt_rating_info.get('value'),
                'ratings_rottenTomatoes_votes': rt_rating_info.get('votes'),
                # Ensure all columns from migration 005 are covered
            }

            # Check if movie exists
            cursor.execute("SELECT id FROM radarr_movies WHERE radarr_id = ?", (radarr_movie_id,))
            existing_movie = cursor.fetchone()

            # Construct columns and placeholders for insert/update dynamically
            # This ensures that if a key is None from Radarr, it's inserted as NULL
            # (assuming the DB column allows NULLs, which they should for optional fields)
            
            db_columns = list(movie_to_insert.keys())
            db_values = [movie_to_insert.get(col) for col in db_columns]

            if existing_movie:
                set_clause = ", ".join([f"{col} = ?" for col in db_columns if col != 'radarr_id'])
                sql_query = f"UPDATE radarr_movies SET {set_clause} WHERE radarr_id = ?"
                
                # Prepare values for update: all values except radarr_movie_id, then radarr_movie_id at the end for WHERE clause
                update_values_list = [movie_to_insert.get(col) for col in db_columns if col != 'radarr_id']
                update_values_list.append(radarr_movie_id)
                
                cursor.execute(sql_query, tuple(update_values_list))
                if cursor.rowcount > 0:
                    movies_updated_count += 1
                movie_db_id = existing_movie[0] # Get ID if exists
            else:
                placeholders = ', '.join(['?'] * len(db_columns))
                sql_query = f"INSERT INTO radarr_movies ({', '.join(db_columns)}) VALUES ({placeholders}) RETURNING id" # Added RETURNING id
                cursor.execute(sql_query, tuple(db_values))
                result = cursor.fetchone()
                if result and result[0]:
                    movie_db_id = result[0]
                    movies_added_count += 1
                else:
                    current_app.logger.error(f"sync_radarr_library: Failed to get ID for new movie Radarr ID {radarr_movie_id}. Skipping image queue for this movie.")
                    conn.rollback() # Rollback this movie's transaction
                    continue # Skip to next movie
            
            movies_synced_count += 1

            # Add to image_cache_queue
            movie_tmdb_id_for_filename = movie_to_insert.get('tmdb_id') # This is movie_data.get('tmdbId')

            if movie_db_id and movie_tmdb_id_for_filename:
                if poster_url:
                    poster_target_filename = f"{movie_tmdb_id_for_filename}.jpg"
                    try:
                        # Use conn.execute directly as we are already in a transaction managed by conn
                        conn.execute(
                            "INSERT INTO image_cache_queue (item_type, item_db_id, image_url, image_kind, target_filename) VALUES (?, ?, ?, ?, ?)",
                            ('movie', movie_db_id, poster_url, 'poster', poster_target_filename)
                        )
                        current_app.logger.info(f"Queued poster for movie ID {movie_db_id} (TMDB ID {movie_tmdb_id_for_filename}): {poster_url}")
                    except sqlite3.Error as e:
                        current_app.logger.error(f"Failed to queue poster for movie ID {movie_db_id}: {e}")

                if fanart_url:
                    fanart_target_filename = f"{movie_tmdb_id_for_filename}.jpg"
                    try:
                        conn.execute(
                            "INSERT INTO image_cache_queue (item_type, item_db_id, image_url, image_kind, target_filename) VALUES (?, ?, ?, ?, ?)",
                            ('movie', movie_db_id, fanart_url, 'background', fanart_target_filename)
                        )
                        current_app.logger.info(f"Queued background (fanart) for movie ID {movie_db_id} (TMDB ID {movie_tmdb_id_for_filename}): {fanart_url}")
                    except sqlite3.Error as e:
                        current_app.logger.error(f"Failed to queue background (fanart) for movie ID {movie_db_id}: {e}")
            elif not movie_tmdb_id_for_filename:
                 current_app.logger.warning(f"Skipping image queue for movie ID {movie_db_id} (Title: {movie_to_insert.get('title', 'N/A')}) due to missing TMDB ID.")
            # movie_db_id should always be set if we didn't 'continue'

        conn.commit()
        database.update_sync_status(conn, 'radarr', 'success')
        current_app.logger.info(f"Radarr library synchronization finished. Synced: {movies_synced_count}, Added: {movies_added_count}, Updated: {movies_updated_count}")
        return {'status': 'success', 'message': 'Radarr library synced successfully.', 'synced': movies_synced_count, 'added': movies_added_count, 'updated': movies_updated_count}

    except sqlite3.Error as e:
        current_app.logger.error(f"sync_radarr_library: Database error during Radarr sync: {e}")
        if conn: conn.rollback()
        temp_conn_for_status = None
        try:
            with current_app.app_context():
                 temp_conn_for_status = database.get_db_connection()
            database.update_sync_status(temp_conn_for_status, 'radarr', 'failed_db_error')
        except Exception as e_status:
            current_app.logger.error(f"sync_radarr_library: Failed to update sync status after DB error: {e_status}")
        finally:
            if temp_conn_for_status: temp_conn_for_status.close()
        return {'status': 'error', 'message': f'Database error: {e}', 'synced': movies_synced_count, 'added': movies_added_count, 'updated': movies_updated_count}
    except Exception as e:
        current_app.logger.error(f"sync_radarr_library: An unexpected error occurred during Radarr sync: {e}")
        if conn: conn.rollback()
        temp_conn_for_status_unexpected = None
        try:
            with current_app.app_context():
                 temp_conn_for_status_unexpected = database.get_db_connection()
            database.update_sync_status(temp_conn_for_status_unexpected, 'radarr', 'failed_unexpected_error')
        except Exception as e_status_unexpected:
            current_app.logger.error(f"sync_radarr_library: Failed to update sync status after unexpected error: {e_status_unexpected}")
        finally:
            if temp_conn_for_status_unexpected: temp_conn_for_status_unexpected.close()
        return {'status': 'error', 'message': f'Unexpected error: {e}', 'synced': movies_synced_count, 'added': movies_added_count, 'updated': movies_updated_count}
    finally:
        if conn:
            conn.close()

# --- Jinja Filters ---
import datetime

def format_datetime_simple(value, format_str='%b %d, %Y %H:%M'):
    """
    Jinja2 filter to format a datetime object into a more readable string.

    Args:
        value (datetime.datetime): The datetime object to format.
        format_str (str, optional): The format string to use, following standard
                                    strftime conventions. Defaults to '%b %d, %Y %H:%M'.

    Returns:
        str: The formatted datetime string.
    """
    if value is None:
        return ""

    dt_obj = None
    if isinstance(value, str):
        try:
            dt_obj = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            # Attempt to parse just the date part if time is not crucial or format is unexpected
            try:
                dt_obj = datetime.datetime.strptime(value, '%Y-%m-%d')
            except ValueError:
                current_app.logger.warning(f"format_datetime_simple: Could not parse date string: {value}")
                return value # Return original if parsing fails completely
    elif isinstance(value, datetime.datetime):
        dt_obj = value
    else:
        current_app.logger.warning(f"format_datetime_simple: Invalid type for value: {type(value)}")
        return value # Return original if not a string or datetime object

    if dt_obj:
        return dt_obj.strftime(format_str)
    return value # Should not be reached if logic is correct, but as a fallback

# --- Tautulli Stubs ---

def sync_tautulli_watch_history():
    """
    Synchronizes recent watch history from Tautulli to the local database.

    This function connects to the Tautulli API to fetch recent watch history
    and logs relevant events (scrobbles, plays, etc.) into the `plex_activity_log`
    table. It's designed to enrich the application's understanding of user
    viewing habits.

    It fetches a configurable number of records and avoids duplicating entries
    by checking for existing records based on session key and timestamp.

    Returns:
        int: The number of new watch history events successfully inserted into the database.
    
    Raises:
        Exception: Propagates exceptions if Tautulli is not configured or if there's
                   an API communication error.
    """
    db_conn = database.get_db()
    cursor = db_conn.cursor()

    with current_app.app_context():
        tautulli_url = database.get_setting('tautulli_url')
        api_key = database.get_setting('tautulli_api_key')

    if not tautulli_url or not api_key:
        current_app.logger.warning("Tautulli URL or API key not configured. Skipping sync.")
        return 0

    params = {
        'apikey': api_key,
        'cmd': 'get_history',
        'length': 100
    }
    try:
        resp = requests.get(f"{tautulli_url.rstrip('/')}/api/v2", params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        history_items = data.get('response', {}).get('data', {}).get('data', [])
    except Exception as e:
        current_app.logger.error(f"Error fetching Tautulli history: {e}")
        return 0

    inserted = 0
    for item in history_items:
        try:
            db_conn.execute(
                """INSERT INTO plex_activity_log (
                       event_type, plex_username, player_title, player_uuid, session_key,
                       rating_key, parent_rating_key, grandparent_rating_key, media_type,
                       title, show_title, season_episode, view_offset_ms, duration_ms, event_timestamp,
                       tmdb_id, raw_payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.get('event'),
                    item.get('friendly_name'),
                    None,
                    None,
                    item.get('session_id'),
                    item.get('rating_key'),
                    item.get('parent_rating_key'),
                    item.get('grandparent_rating_key'),
                    item.get('media_type'),
                    item.get('title'),
                    item.get('grandparent_title'),
                    item.get('parent_media_index') and item.get('media_index') and f"S{int(item.get('parent_media_index')):02d}E{int(item.get('media_index')):02d}",
                    None,
                    None,
                    item.get('date'),
                    None,
                    json.dumps(item)
                )
            )
            inserted += 1
        except Exception as e:
            current_app.logger.warning(f"Failed to insert Tautulli history item: {e}")
            continue

    db_conn.commit()
    current_app.logger.info(f"Tautulli sync complete. {inserted} events added.")
    return inserted

def test_tautulli_connection():
    """Tests the connection to the configured Tautulli service."""
    # Tautulli's get_history endpoint with a limit of 1 is a good way to test.
    # It requires the API key.
    return _test_service_connection(
        "Tautulli",
        'tautulli_url',
        'tautulli_api_key',
        endpoint='/api/v2?cmd=get_history&length=1'
    )

def test_tautulli_connection_with_params(url, api_key):
    """
    Tests the Tautulli connection using a provided URL and API key.

    Args:
        url (str): The Tautulli URL to test.
        api_key (str): The Tautulli API key to test.

    Returns:
        tuple: (bool, str) indicating success and a result message.
    """
    return _test_service_connection_with_params(
        "Tautulli",
        url,
        api_key,
        endpoint='/api/v2?cmd=get_history&length=1'
    )
