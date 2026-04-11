"""
Utility shim for ShowNotes.

All logic has been split into focused service modules. This file re-exports
everything from those modules so existing imports continue to work unchanged.

Internal modules:
  notifications      — Pushover, ntfy, admin notifications
  service_testing    — Connection test functions for all services
  sonarr_service     — Sonarr API + library sync
  radarr_service     — Radarr API + library sync
  tautulli_service   — Tautulli API + watch history sync
  calendar_service   — Calendar data, iCal feed, cache
  data_transforms    — Datetime formatting, LLM markdown parsers, timezone utils
"""

import os
import time
from flask import current_app, url_for


# ---------------------------------------------------------------------------
# Shared internal helper — kept here to avoid circular imports.
# sonarr_service and radarr_service import this from utils.
# ---------------------------------------------------------------------------

def _trigger_image_cache(proxy_image_url, item_title_for_logging=""):
    """
    Internally requests a proxied image URL to trigger the caching mechanism.

    Uses the Flask test client to GET a proxied image URL so the image is
    cached before users load pages. Called during library syncs.
    """
    if not proxy_image_url:
        return

    try:
        with current_app.app_context():
            client = current_app.test_client()
            response = client.get(proxy_image_url)
            if response.status_code == 200:
                current_app.logger.info(f"Successfully triggered image cache for '{item_title_for_logging}'.")
            else:
                current_app.logger.warning(
                    f"Failed to trigger image cache for '{item_title_for_logging}' via {proxy_image_url}. "
                    f"Status: {response.status_code}"
                )
    except Exception as e:
        current_app.logger.error(
            f"Error triggering image cache for '{item_title_for_logging}' ({proxy_image_url}): {e}"
        )


# ---------------------------------------------------------------------------
# Re-export everything from service modules.
# Import order matters: calendar_service must be imported before sonarr_service
# because sonarr_service imports invalidate_calendar_cache from calendar_service.
# service_testing must be imported before calendar_service because
# calendar_service imports get_jellyseerr_requests_for_user from service_testing.
# ---------------------------------------------------------------------------

from .notifications import (  # noqa: E402
    send_pushover_notification,
    send_ntfy_notification,
    send_admin_notification,
)

from .service_testing import (  # noqa: E402
    _test_service_connection,
    test_sonarr_connection,
    test_radarr_connection,
    test_bazarr_connection,
    test_ollama_connection,
    get_ollama_models,
    _test_service_connection_with_params,
    test_sonarr_connection_with_params,
    test_radarr_connection_with_params,
    test_bazarr_connection_with_params,
    test_ollama_connection_with_params,
    test_pushover_notification_with_params,
    test_tautulli_connection,
    test_tautulli_connection_with_params,
    test_jellyseer_connection,
    test_jellyseer_connection_with_params,
    get_jellyseer_user_requests,
    get_jellyseerr_requests_for_user,
    test_thetvdb_connection,
    test_thetvdb_connection_with_params,
)

from .data_transforms import (  # noqa: E402
    format_datetime_simple,
    format_milliseconds,
    parse_llm_markdown_sections,
    parse_relationships_section,
    parse_traits_section,
    parse_events_section,
    parse_quote_section,
    parse_motivations_section,
    parse_importance_section,
    get_user_timezone,
    convert_utc_to_user_timezone,
)

from .calendar_service import (  # noqa: E402
    generate_ical_for_user,
    get_calendar_cache_path,
    get_calendar_cache,
    set_calendar_cache,
    invalidate_calendar_cache,
    build_calendar_data,
    get_calendar_data_for_user,
)

from .tautulli_service import (  # noqa: E402
    sync_tautulli_watch_history,
    process_activity_log_for_watch_status,
    get_tautulli_activity,
    get_tautulli_data,
    get_tautulli_current_activity,
)

from .sonarr_service import (  # noqa: E402
    get_all_sonarr_shows,
    get_sonarr_episodes_for_show,
    get_sonarr_show_details,
    get_episodes_by_series_id,
    sync_sonarr_tags,
    sync_sonarr_library,
    update_sonarr_episode,
)

from .radarr_service import (  # noqa: E402
    get_all_radarr_movies,
    sync_radarr_library,
)
