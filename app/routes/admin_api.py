import asyncio
import json
from flask import Blueprint, jsonify, request, current_app
from app.database import get_db, get_setting
from app.services.status_checker import PlexChecker, SonarrChecker, RadarrChecker, BazarrChecker

admin_api_bp = Blueprint('admin_api', __name__, url_prefix='/admin/api')

# Helper function to get service configuration (as discussed in subtask item 7)
# This centralizes the logic for fetching settings for each service.
def _get_service_config_dict(service_name_lower):
    config = {}
    # Common settings
    config['url'] = get_setting(f"{service_name_lower}_url")
    config['api_key'] = get_setting(f"{service_name_lower}_api_key")

    # Service-specific settings or overrides
    if service_name_lower == 'plex':
        # Plex might use a specific token and its URL might be handled differently
        # For now, we assume plex_url and plex_token are in settings
        config['token'] = get_setting("plex_token")
        if not config['url']: # Fallback if plex_url is not explicitly in settings
            # This is a placeholder; actual Plex URL might come from a general app setting
            # or be dynamically determined. For now, we expect it in settings.
            current_app.logger.warning("Plex URL not found in settings, Plex checker might fail.")
            pass


    # Basic validation: URL is usually required for a service to be considered configured.
    if not config.get('url'):
        current_app.logger.warning(f"URL for {service_name_lower} not found in settings.")
        return None # Indicate that the service is not configured

    return config


@admin_api_bp.route('/services/status', methods=['GET'])
async def get_services_status():
    db = get_db()
    try:
        cursor = db.execute(
            "SELECT id, service_name, status, last_checked, response_time, version, details FROM service_status ORDER BY service_name"
        )
        statuses = cursor.fetchall()
        results = []
        for row in statuses:
            row_dict = dict(row)
            try:
                if row_dict['details']:
                    row_dict['details'] = json.loads(row_dict['details'])
            except json.JSONDecodeError:
                current_app.logger.error(f"Failed to parse JSON details for {row_dict['service_name']}: {row_dict['details']}")
                # Keep details as string if it's not valid JSON
            results.append(row_dict)
        return jsonify(results)
    except Exception as e:
        current_app.logger.error(f"Error fetching service statuses: {e}")
        return jsonify({'error': 'Failed to fetch service statuses', 'details': str(e)}), 500


@admin_api_bp.route('/services/test/<service_name>', methods=['POST'])
async def test_service(service_name):
    db = get_db()
    service_name_lower = service_name.lower()

    config = _get_service_config_dict(service_name_lower)

    if not config:
        return jsonify({'error': f"Service '{service_name}' is not configured or URL is missing."}), 404

    checker = None
    if service_name_lower == 'plex':
        checker = PlexChecker(config)
    elif service_name_lower == 'sonarr':
        checker = SonarrChecker(config)
    elif service_name_lower == 'radarr':
        checker = RadarrChecker(config)
    elif service_name_lower == 'bazarr':
        checker = BazarrChecker(config)
    else:
        return jsonify({'error': 'Unknown service name'}), 404

    try:
        result = await checker.check_status()

        # Ensure details is a JSON string for DB storage
        details_json = json.dumps(result.get('details', {}))

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

        # Return the original result, but ensure details are properly formatted if they were stringified
        # For the JSON response, it's better if 'details' is a dict, not a string.
        return jsonify(result)

    except Exception as e:
        current_app.logger.error(f"Error testing service {service_name}: {e}")
        # Attempt to store an error status
        try:
            error_details = json.dumps({'error': str(e), 'trace': traceback.format_exc() if current_app.debug else 'Enable debug for traceback'})
            db.execute(
                """
                INSERT OR REPLACE INTO service_status
                (service_name, status, last_checked, response_time, version, details)
                VALUES (?, 'offline', CURRENT_TIMESTAMP, 0, 'N/A', ?)
                """,
                (service_name, error_details)
            )
            db.commit()
        except Exception as db_e:
            current_app.logger.error(f"Error storing error status for {service_name} in DB: {db_e}")

        return jsonify({'error': f"Failed to test service {service_name}", 'details': str(e)}), 500


@admin_api_bp.route('/services/history', methods=['GET'])
async def get_services_history():
    # This is a placeholder as per requirements.
    # A full implementation would involve querying historical data, possibly from a separate table
    # or by analyzing logs if service_status is only for the latest status.
    return jsonify({'message': 'History endpoint not fully implemented yet. This endpoint will provide historical status data.'})

# Note on _get_service_config_dict:
# This helper centralizes fetching configurations.
# Plex URL handling: The current implementation expects 'plex_url' in settings.
# If Plex's URL is derived differently (e.g., from a general app URL or localhost assumption),
# this helper would be the place to adjust that logic.
# For instance, if plex_url is not in settings, it could default to 'http://localhost:32400'
# or try to discover it if that's a feature.
# The current code logs a warning if plex_url is missing.
# API keys/tokens: Handled for Sonarr, Radarr, Bazarr (api_key) and Plex (token).
# If a service does not need an API key for its status check, the checker itself should handle that gracefully
# (e.g., not add the X-Api-Key header if self.api_key is None).
# The _make_request in ServiceChecker should already be robust to None api_key/token.
import traceback # Add for more detailed error logging if needed
