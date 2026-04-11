import datetime
import re
import pytz
from flask import current_app, g
from . import database

def format_datetime_simple(value, format_str='%b %d, %Y %H:%M'):
    """
    Jinja2 filter to format a datetime object into a more readable string.
    Converts UTC timestamps to the configured timezone from settings.

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
        # Get timezone from settings (cached in Flask g object per request)
        try:
            from flask import g
            if not hasattr(g, '_timezone_setting'):
                db = database.get_db()
                settings = db.execute('SELECT timezone FROM settings LIMIT 1').fetchone()
                g._timezone_setting = settings['timezone'] if settings and settings['timezone'] else 'UTC'
            tz_name = g._timezone_setting
        except Exception:
            tz_name = 'UTC'
        
        # Convert to configured timezone
        try:
            # Ensure the datetime is timezone-aware (assume UTC if naive)
            if dt_obj.tzinfo is None:
                dt_obj = pytz.UTC.localize(dt_obj)
            else:
                # Normalize to pytz.UTC for consistent handling.
                # datetime.timezone.utc and pytz.UTC are not the same object,
                # so always call astimezone to ensure a canonical pytz UTC tzinfo.
                dt_obj = dt_obj.astimezone(pytz.UTC)
            
            # Convert to configured timezone
            target_tz = pytz.timezone(tz_name)
            dt_obj = dt_obj.astimezone(target_tz)
        except Exception as e:
            current_app.logger.warning(f"format_datetime_simple: Error converting timezone: {e}")
            # Fall back to original datetime if conversion fails
        
        return dt_obj.strftime(format_str)
    return value # Should not be reached if logic is correct, but as a fallback

def format_milliseconds(value):
    """Format a millisecond duration as ``MM:SS.mmm``."""
    if value is None:
        return ""
    try:
        ms = int(value)
        seconds, milliseconds = divmod(ms, 1000)
        minutes, seconds = divmod(seconds, 60)
        return f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
    except Exception:
        return str(value)

# --- Tautulli Stubs ---

def parse_llm_markdown_sections(md):
    """
    Parse markdown output from LLM into a dict of sections.
    Each '## Section Name' becomes a key, and its content is the value.
    """
    import re
    sections = {}
    current = None
    for line in md.splitlines():
        header_match = re.match(r"^##\s+(.+)", line)
        if header_match:
            current = header_match.group(1).strip()
            sections[current] = ''
        elif current is not None:
            sections[current] += line + '\n'
    # Strip trailing newlines
    for k in sections:
        sections[k] = sections[k].strip()
    return sections

def parse_relationships_section(md):
    # Expects lines like: relationship_1: name: "X" role: "Y" description: "Z"
    import re
    relationships = []
    pattern = re.compile(r'relationship_\d+: name: "([^"]*)" role: "([^"]*)" description: "([^"]*)"')
    for match in pattern.finditer(md):
        relationships.append({
            'name': match.group(1),
            'role': match.group(2),
            'description': match.group(3)
        })
    return relationships

def parse_traits_section(md):
    # Expects lines like: traits: - "Trait1" - "Trait2"
    import re
    traits = []
    lines = md.splitlines()
    for line in lines:
        if line.strip().startswith('- '):
            trait = line.strip()[2:].strip('"')
            traits.append(trait)
    return traits

def parse_events_section(md):
    # Expects lines like: events: - "Event1" - "Event2"
    import re
    events = []
    lines = md.splitlines()
    for line in lines:
        if line.strip().startswith('- '):
            event = line.strip()[2:].strip('"')
            events.append(event)
    return events

def parse_quote_section(md):
    # Expects: quote: "..."
    import re
    match = re.search(r'quote: "([^"]+)"', md)
    return match.group(1) if match else md.strip()

def parse_motivations_section(md):
    # Expects: description: ...
    import re
    match = re.search(r'description: (.+)', md)
    return match.group(1).strip() if match else md.strip()

def parse_importance_section(md):
    # Expects: description: ...
    import re
    match = re.search(r'description: (.+)', md)
    return match.group(1).strip() if match else md.strip()

def get_user_timezone():
    """
    Get the configured timezone from settings.

    Returns:
        str: The timezone string (e.g., 'America/New_York') or 'UTC' if not configured
    """
    try:
        from .database import get_setting
        timezone = get_setting('timezone')
        return timezone if timezone else 'UTC'
    except Exception:
        return 'UTC'

def convert_utc_to_user_timezone(utc_datetime_str, output_format='%Y-%m-%d %H:%M:%S'):
    """
    Convert a UTC datetime string to the user's configured timezone.

    Args:
        utc_datetime_str: String or datetime object representing UTC time
        output_format: strftime format string for output

    Returns:
        str: Formatted datetime string in user's timezone
    """
    try:
        import datetime as dt

        # Handle different input types
        if isinstance(utc_datetime_str, str):
            # Try to parse the string
            try:
                # Try ISO format first
                utc_dt = dt.datetime.fromisoformat(utc_datetime_str.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                # Try parsing without timezone info (assume UTC)
                try:
                    utc_dt = dt.datetime.strptime(utc_datetime_str, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    # Return original string if parsing fails
                    return utc_datetime_str
        elif isinstance(utc_datetime_str, (int, float)):
            # Unix timestamp
            utc_dt = dt.datetime.fromtimestamp(float(utc_datetime_str), tz=pytz.UTC)
        elif isinstance(utc_datetime_str, dt.datetime):
            utc_dt = utc_datetime_str
        else:
            return str(utc_datetime_str)

        # Ensure datetime is timezone-aware (UTC)
        if utc_dt.tzinfo is None:
            utc_dt = pytz.UTC.localize(utc_dt)
        else:
            # Normalize to pytz UTC regardless of which UTC implementation is present
            # (datetime.timezone.utc and pytz.UTC are not the same object).
            utc_dt = utc_dt.astimezone(pytz.UTC)

        # Get user's timezone
        user_tz_str = get_user_timezone()
        user_tz = pytz.timezone(user_tz_str)

        # Convert to user's timezone
        local_dt = utc_dt.astimezone(user_tz)

        return local_dt.strftime(output_format)

    except Exception as e:
        current_app.logger.error(f"Error converting timezone: {e}")
        # Return original value if conversion fails
        return str(utc_datetime_str)


# ========================================
# CALENDAR DATA CACHING
# ========================================

