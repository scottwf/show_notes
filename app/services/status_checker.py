import aiohttp
import asyncio
import json
import time

class ServiceChecker:
    def __init__(self, config):
        self.config = config
        self.base_url = config.get('url')
        self.api_key = config.get('api_key') # For services like Sonarr, Radarr, Bazarr
        self.token = config.get('token') # For services like Plex

    async def _make_request(self, endpoint, headers=None, method='GET', data=None):
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        if headers is None:
            headers = {}
        headers.setdefault('Accept', 'application/json')

        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                start_time = time.monotonic()
                async with session.request(method, url, json=data, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    response_time_ms = (time.monotonic() - start_time) * 1000
                    response_data = None
                    try:
                        if response.content_type == 'application/json':
                            response_data = await response.json()
                        else:
                            response_data = await response.text()
                    except json.JSONDecodeError:
                        response_data = await response.text() # Store as text if not valid JSON

                    if response.status >= 200 and response.status < 300:
                        return response_data, response.status, response_time_ms
                    else:
                        return {'error': f"HTTP Status {response.status}", 'details': response_data}, response.status, response_time_ms
        except aiohttp.ClientConnectorError as e:
            return {'error': f"Connection error: {e}"}, None, 0
        except asyncio.TimeoutError:
            return {'error': "Request timed out"}, None, 0
        except Exception as e: # Catch any other unexpected errors
            return {'error': f"An unexpected error occurred: {e}"}, None, 0

    async def check_status(self):
        raise NotImplementedError("Each checker must implement this method.")

class PlexChecker(ServiceChecker):
    def __init__(self, config):
        super().__init__(config)
        self.name = "Plex"

    async def check_status(self):
        start_time = time.monotonic()
        # Plex's /identity endpoint is a good lightweight check.
        # It might require X-Plex-Token for version, but basic connectivity can be checked.
        headers = {}
        if self.token:
            headers['X-Plex-Token'] = self.token

        data, status_code, response_time_ms = await self._make_request("/identity", headers=headers)

        # If the initial request failed, try base URL as a fallback for basic connectivity
        if status_code is None or status_code >= 400:
             data_fallback, status_code_fallback, response_time_ms_fallback = await self._make_request("", headers=headers)
             if status_code_fallback is not None and status_code_fallback < 400:
                 data, status_code, response_time_ms = data_fallback, status_code_fallback, response_time_ms_fallback
             else: # If fallback also fails, use original error
                 response_time_ms = (time.monotonic() - start_time) * 1000 # Recalculate if initial request failed early

        service_status = 'offline'
        version = 'N/A'
        details = data if isinstance(data, dict) and 'error' in data else {}

        if status_code is not None and status_code >= 200 and status_code < 300:
            service_status = 'online'
            if isinstance(data, dict) and data.get('MediaContainer'):
                version = data['MediaContainer'].get('version', 'N/A')
                details = {'serverName': data['MediaContainer'].get('friendlyName', 'Unknown')}
            elif isinstance(data, dict): # If response is JSON but not the expected structure
                details = data

        return {
            'name': self.name,
            'status': service_status,
            'version': version,
            'response_time': round(response_time_ms),
            'details': details
        }

class SonarrChecker(ServiceChecker):
    def __init__(self, config):
        super().__init__(config)
        self.name = "Sonarr"

    async def check_status(self):
        headers = {}
        if self.api_key:
            headers['X-Api-Key'] = self.api_key
        else: # API key is required for Sonarr
             return {
                'name': self.name,
                'status': 'offline',
                'version': 'N/A',
                'response_time': 0,
                'details': {'error': 'API key not configured'}
            }

        data, status_code, response_time_ms = await self._make_request("/api/v3/system/status", headers=headers)

        service_status = 'offline'
        version = 'N/A'
        details_dict = {}

        if status_code is not None and status_code >= 200 and status_code < 300 and isinstance(data, dict):
            service_status = 'online'
            version = data.get('version', 'N/A')
            details_dict = {
                'appName': data.get('appName'),
                'branch': data.get('branch'),
                'osName': data.get('osName'),
                'osVersion': data.get('osVersion'),
                'isDocker': data.get('isDocker')
            }
        elif isinstance(data, dict) and 'error' in data:
            details_dict = data

        return {
            'name': self.name,
            'status': service_status,
            'version': version,
            'response_time': round(response_time_ms),
            'details': details_dict
        }

class RadarrChecker(ServiceChecker):
    def __init__(self, config):
        super().__init__(config)
        self.name = "Radarr"

    async def check_status(self):
        headers = {}
        if self.api_key:
            headers['X-Api-Key'] = self.api_key
        else: # API key is required
             return {
                'name': self.name,
                'status': 'offline',
                'version': 'N/A',
                'response_time': 0,
                'details': {'error': 'API key not configured'}
            }

        data, status_code, response_time_ms = await self._make_request("/api/v3/system/status", headers=headers)

        service_status = 'offline'
        version = 'N/A'
        details_dict = {}

        if status_code is not None and status_code >= 200 and status_code < 300 and isinstance(data, dict):
            service_status = 'online'
            version = data.get('version', 'N/A')
            details_dict = {
                'appName': data.get('appName'),
                'branch': data.get('branch'),
                'osName': data.get('osName'),
                'osVersion': data.get('osVersion'),
                'isDocker': data.get('isDocker')
            }
        elif isinstance(data, dict) and 'error' in data:
            details_dict = data

        return {
            'name': self.name,
            'status': service_status,
            'version': version,
            'response_time': round(response_time_ms),
            'details': details_dict
        }

class BazarrChecker(ServiceChecker):
    def __init__(self, config):
        super().__init__(config)
        self.name = "Bazarr"

    async def check_status(self):
        headers = {}
        if self.api_key:
            headers['X-Api-Key'] = self.api_key
        # Bazarr might not require API key for its /api/status or equivalent
        # If it does, and it's not provided, the request will likely fail with unauthorized.

        # According to public API docs (e.g. https://bazarr.featureupvote.com/suggestions/328653/api-docs)
        # /api/system/status seems to be the endpoint, similar to sonarr/radarr.
        # If this has changed or is incorrect, a simple base URL check might be a fallback.
        data, status_code, response_time_ms = await self._make_request("/api/system/status", headers=headers)

        service_status = 'offline'
        version = 'N/A'
        details_dict = {}

        if status_code is not None and status_code >= 200 and status_code < 300 and isinstance(data, dict):
            service_status = 'online'
            version = data.get('version', data.get('bazarr_version', 'N/A')) # Bazarr might use 'bazarr_version'
            details_dict = {
                'osName': data.get('os_name'),
                'osVersion': data.get('os_version'),
                'pythonVersion': data.get('python_version'),
                'packageVersion': data.get('package_version') # This might be the same as 'version'
            }
        elif isinstance(data, dict) and 'error' in data: # If there was an error from _make_request
            details_dict = data
        elif status_code is not None and status_code >= 400 : # If API key is missing or other error
             # Fallback to base URL check if /api/system/status fails (e.g. due to auth or endpoint not existing)
            fallback_data, fallback_status_code, fallback_response_time_ms = await self._make_request("", headers=headers)
            if fallback_status_code is not None and fallback_status_code >=200 and fallback_status_code < 300:
                service_status = 'online'
                response_time_ms = fallback_response_time_ms # Use fallback response time
                details_dict = {'message': 'Basic connectivity OK, system status endpoint failed or requires auth.'}
                if isinstance(fallback_data, dict): # some basic info might be available
                    details_dict.update(fallback_data)
            else:
                details_dict = data # Original error from /api/system/status

        return {
            'name': self.name,
            'status': service_status,
            'version': version,
            'response_time': round(response_time_ms),
            'details': details_dict
        }

# Example of how it might be used (for testing purposes)
async def main():
    # Dummy configs - these would come from database/user settings
    plex_config = {'url': 'http://localhost:32400', 'token': 'YOUR_PLEX_TOKEN_IF_NEEDED'}
    sonarr_config = {'url': 'http://localhost:8989', 'api_key': 'YOUR_SONARR_API_KEY'}
    radarr_config = {'url': 'http://localhost:7878', 'api_key': 'YOUR_RADARR_API_KEY'}
    bazarr_config = {'url': 'http://localhost:6767', 'api_key': 'YOUR_BAZARR_API_KEY'} # Or no API key if not needed for status

    checkers = [
        PlexChecker(plex_config),
        SonarrChecker(sonarr_config),
        RadarrChecker(radarr_config),
        BazarrChecker(bazarr_config)
    ]

    results = await asyncio.gather(*(checker.check_status() for checker in checkers))

    for result in results:
        print(json.dumps(result, indent=2))

if __name__ == '__main__':
    # This part is for local testing of the script.
    # In a real Flask app, you wouldn't run it like this.
    # You'd import the classes and use them in your background tasks or API handlers.
    # Note: Running this directly might fail if the services are not running or accessible.

    # To run this test:
    # 1. Ensure aiohttp is installed: pip install aiohttp
    # 2. Replace dummy configs with your actual service details if you want to test against live services.
    # 3. Run: python app/services/status_checker.py

    # Check if we are in a context where asyncio event loop is already running (e.g. Jupyter notebook)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        print("Asyncio loop is already running. Creating a new task for main().")
        task = loop.create_task(main())
        # In a Jupyter environment, you might need to await this task if it's the last cell.
    else:
        asyncio.run(main())

# Placeholder for how service configurations will be passed.
# This will be refined when integrating with the background task and API endpoints.
# For now, the checkers expect config in their __init__.
# Example:
# configs_from_db = get_all_service_configurations() # Function to fetch from DB
# active_checkers = []
# if configs_from_db.get('plex'): active_checkers.append(PlexChecker(configs_from_db['plex']))
# ... and so on for other services.
# results = await asyncio.gather(*(checker.check_status() for checker in active_checkers))
# store_results_in_db(results)
