import requests
import json
from flask import current_app
from . import database

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

def get_ollama_models():
    """
    Fetches the list of available Ollama models.

    Returns:
        list: A list of model names (strings), or an empty list if unable to fetch.
    """
    ollama_url = database.get_setting('ollama_url')
    if not ollama_url:
        current_app.logger.info("get_ollama_models: No Ollama URL configured")
        return []

    try:
        response = requests.get(f"{ollama_url.rstrip('/')}/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            # The /api/tags endpoint returns {"models": [{"name": "..."}, ...]}
            models = data.get('models', [])
            model_names = [model.get('name') for model in models if model.get('name')]
            current_app.logger.info(f"get_ollama_models: Found {len(model_names)} models: {model_names}")
            return model_names
        else:
            current_app.logger.warning(f"Failed to fetch Ollama models: status {response.status_code}")
            return []
    except Exception as e:
        current_app.logger.error(f"Error fetching Ollama models: {e}")
        return []

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
    
    required_key_services = ["Sonarr", "Radarr", "Bazarr", "Jellyseer"]
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

def test_tautulli_connection():
    """Tests the connection to the configured Tautulli service."""
    # Get settings from database
    tautulli_url = database.get_setting('tautulli_url')
    tautulli_api_key = database.get_setting('tautulli_api_key')

    if not tautulli_url:
        return False, "Tautulli URL not configured."

    # Use the _with_params version which correctly handles Tautulli API key as a query parameter
    return test_tautulli_connection_with_params(tautulli_url, tautulli_api_key)

def test_tautulli_connection_with_params(url, api_key):
    """
    Tests the Tautulli connection using a provided URL and API key.

    Args:
        url (str): The Tautulli URL to test.
        api_key (str): The Tautulli API key to test.

    Returns:
        tuple: (bool, str) indicating success and a result message.
    """
    # Tautulli expects API key as a query parameter, not a header
    params = {'apikey': api_key} if api_key else {}
    params['cmd'] = 'get_history'
    params['length'] = '1'

    return _test_service_connection_with_params(
        "Tautulli",
        url,
        api_key=None,  # Don't pass api_key since Tautulli doesn't use headers
        endpoint='/api/v2',
        params=params
    )

def test_jellyseer_connection():
    """Tests the connection to the configured Jellyseer/Overseerr service."""
    jellyseer_url = database.get_setting('jellyseer_url')
    jellyseer_api_key = database.get_setting('jellyseer_api_key')

    if not jellyseer_url:
        return False, "Jellyseer URL not configured."

    return test_jellyseer_connection_with_params(jellyseer_url, jellyseer_api_key)

def test_jellyseer_connection_with_params(url, api_key):
    """
    Tests the Jellyseer/Overseerr connection using a provided URL and API key.

    Args:
        url (str): The Jellyseer URL to test.
        api_key (str): The Jellyseer API key to test.

    Returns:
        tuple: (bool, str) indicating success and a result message.
    """
    return _test_service_connection_with_params(
        "Jellyseer",
        url,
        api_key=api_key,
        endpoint='/api/v1/settings/main'
    )

def get_jellyseer_user_requests():
    """
    Fetch all Jellyseerr requests and return a dict mapping
    plex_username (lowercase) -> request count.
    Returns empty dict if Jellyseerr is not configured or the request fails.
    """
    jellyseer_url = database.get_setting('jellyseer_url')
    jellyseer_api_key = database.get_setting('jellyseer_api_key')
    if not jellyseer_url or not jellyseer_api_key:
        return {}
    try:
        headers = {'X-Api-Key': jellyseer_api_key}
        response = requests.get(
            f"{jellyseer_url}/api/v1/request",
            params={'take': 1000, 'filter': 'all', 'sort': 'added'},
            headers=headers,
            timeout=2
        )
        if response.status_code != 200:
            return {}
        counts = {}
        for req in response.json().get('results', []):
            requested_by = req.get('requestedBy', {})
            plex_username = (requested_by.get('plexUsername') or requested_by.get('username') or '').lower()
            if plex_username:
                counts[plex_username] = counts.get(plex_username, 0) + 1
        return counts
    except Exception:
        return {}

def get_jellyseerr_requests_for_user(plex_username):
    """
    Fetch TMDB IDs of TV shows requested by this Plex user on Jellyseerr/Overseerr.
    Returns a set of TMDB IDs (integers), or empty set if unavailable.
    """
    if not plex_username:
        return set()
    jellyseer_url = database.get_setting('jellyseer_url')
    jellyseer_api_key = database.get_setting('jellyseer_api_key')
    if not jellyseer_url or not jellyseer_api_key:
        return set()
    try:
        headers = {'X-Api-Key': jellyseer_api_key}
        response = requests.get(
            f"{jellyseer_url}/api/v1/request",
            params={'take': 500, 'filter': 'all', 'sort': 'added'},
            headers=headers,
            timeout=3
        )
        if response.status_code != 200:
            return set()
        tmdb_ids = set()
        plex_lower = plex_username.lower()
        for req in response.json().get('results', []):
            # Only TV show requests
            if req.get('type') != 'tv':
                continue
            requested_by = req.get('requestedBy', {})
            req_username = (requested_by.get('plexUsername') or requested_by.get('username') or '').lower()
            if req_username != plex_lower:
                continue
            media = req.get('media', {})
            tmdb_id = media.get('tmdbId')
            if tmdb_id:
                tmdb_ids.add(int(tmdb_id))
        return tmdb_ids
    except Exception:
        return set()


def test_thetvdb_connection():
    """Tests the connection to TheTVDB API using the configured API key."""
    api_key = database.get_setting('thetvdb_api_key')
    if not api_key:
        return False, "TheTVDB API key not configured."
    return test_thetvdb_connection_with_params(api_key)

def test_thetvdb_connection_with_params(api_key):
    """Tests TheTVDB API connection by attempting login."""
    if not api_key:
        return False, "TheTVDB API key is required."
    try:
        resp = requests.post(
            "https://api4.thetvdb.com/v4/login",
            json={"apikey": api_key},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get('data', {}).get('token'):
                return True, "Connected successfully."
            return False, "Login succeeded but no token returned."
        elif resp.status_code == 401:
            return False, "Invalid API key."
        else:
            return False, f"Unexpected response (HTTP {resp.status_code})"
    except requests.exceptions.RequestException as e:
        return False, f"Connection error: {str(e)}"

