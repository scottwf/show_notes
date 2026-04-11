import requests
from flask import current_app
from . import database

def send_pushover_notification(title, message, url=None, url_title=None, priority=0):
    """
    Send a Pushover notification using configured credentials.

    Args:
        title (str): Notification title
        message (str): Notification message
        url (str, optional): URL to include in notification (e.g., Sonarr link)
        url_title (str, optional): Title for the URL button (e.g., "View in Sonarr")
        priority (int, optional): -2 to 2, where 1 requires confirmation (default: 0)

    Returns:
        tuple: (bool, str) indicating success and error message if any
    """
    from . import database

    pushover_token = database.get_setting('pushover_token')
    pushover_key = database.get_setting('pushover_key')

    if not pushover_token or not pushover_key:
        current_app.logger.warning("Pushover not configured, skipping notification")
        return False, "Pushover not configured"

    api_url = "https://api.pushover.net/1/messages.json"
    payload = {
        'token': pushover_token,
        'user': pushover_key,
        'title': title,
        'message': message,
        'priority': priority
    }

    if url:
        payload['url'] = url
    if url_title:
        payload['url_title'] = url_title

    try:
        response = requests.post(api_url, data=payload, timeout=5)
        response_data = response.json()
        if response_data.get('status') == 1:
            current_app.logger.info(f"Pushover notification sent: {title}")
            return True, None
        else:
            error_message = response_data.get('errors', ['Unknown error'])
            current_app.logger.warning(f"Pushover send failed: {error_message}")
            return False, ', '.join(error_message)
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Error sending Pushover notification: {e}")
        return False, str(e)

def send_ntfy_notification(title, message, url=None, priority='default'):
    """
    Send a notification via ntfy using configured settings.

    Returns:
        tuple: (bool, str) success and error message if any
    """
    from . import database

    ntfy_url = database.get_setting('ntfy_url') or 'https://ntfy.sh'
    ntfy_topic = database.get_setting('ntfy_topic')
    ntfy_token = database.get_setting('ntfy_token')

    if not ntfy_topic:
        current_app.logger.warning("ntfy not configured (missing topic), skipping notification")
        return False, "ntfy not configured"

    endpoint = f"{ntfy_url.rstrip('/')}/{ntfy_topic}"
    headers = {
        'Title': title,
        'Priority': priority,
        'Content-Type': 'text/plain',
    }
    if ntfy_token:
        headers['Authorization'] = f'Bearer {ntfy_token}'
    if url:
        headers['Click'] = url

    try:
        response = requests.post(endpoint, data=message.encode('utf-8'), headers=headers, timeout=5)
        if response.status_code in (200, 201, 202):
            current_app.logger.info(f"ntfy notification sent: {title}")
            return True, None
        else:
            current_app.logger.warning(f"ntfy send failed: {response.status_code} {response.text}")
            return False, f"HTTP {response.status_code}"
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Error sending ntfy notification: {e}")
        return False, str(e)


def send_admin_notification(title, message, url=None, url_title=None, trigger_key=None):
    """
    Send an admin push notification via all configured services.

    Args:
        title (str): Notification title
        message (str): Notification body
        url (str, optional): Deep-link URL to include
        url_title (str, optional): Label for the URL (Pushover only)
        trigger_key (str, optional): Setting key to check before sending
            (e.g. 'notify_on_problem_report'). If None, always sends.

    Sends via Pushover and/or ntfy if credentials are configured.
    Silently skips any service that isn't set up.
    """
    from . import database

    # Check trigger flag if one was provided
    if trigger_key:
        flag = database.get_setting(trigger_key)
        if flag in (0, '0', False, 'false', 'False', None):
            return

    pushover_token = database.get_setting('pushover_token')
    pushover_key = database.get_setting('pushover_key')
    ntfy_topic = database.get_setting('ntfy_topic')

    if pushover_token and pushover_key:
        send_pushover_notification(title, message, url=url, url_title=url_title)

    if ntfy_topic:
        send_ntfy_notification(title, message, url=url)


# --- End Connection Test Functions (with Parameters) ---


