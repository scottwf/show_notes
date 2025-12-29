"""System Event Logger - Database-backed event logging for ShowNotes"""
import json
from datetime import datetime
from flask import current_app, request, session
from app.database import get_db

class SystemLogger:
    """Logger for system events stored in database"""

    # Log levels
    INFO = 'info'
    WARNING = 'warning'
    ERROR = 'error'
    SUCCESS = 'success'
    DEBUG = 'debug'

    # Components
    WEBHOOK = 'webhook'
    SYNC = 'sync'
    NOTIFICATION = 'notification'
    ENRICHMENT = 'enrichment'
    AUTH = 'auth'
    ADMIN = 'admin'
    API = 'api'
    SYSTEM = 'system'

    @staticmethod
    def log(level, component, message, details=None):
        """
        Log an event to the system_logs table

        Args:
            level: Log level (INFO, WARNING, ERROR, SUCCESS, DEBUG)
            component: Component name (WEBHOOK, SYNC, etc.)
            message: Short message (255 chars max)
            details: Optional dict with additional details (stored as JSON)
        """
        try:
            db = get_db()

            # Get user info if available
            user_id = session.get('user_id') if session else None

            # Get IP address if in request context
            ip_address = None
            try:
                if request:
                    ip_address = request.remote_addr
            except RuntimeError:
                pass  # Not in request context

            # Serialize details to JSON if provided
            details_json = None
            if details:
                if isinstance(details, dict):
                    details_json = json.dumps(details)
                else:
                    details_json = str(details)

            # Insert log entry
            db.execute("""
                INSERT INTO system_logs (level, component, message, details, user_id, ip_address)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (level, component, message, details_json, user_id, ip_address))

            db.commit()

        except Exception as e:
            # Fallback to standard logging if DB logging fails
            current_app.logger.error(f"Failed to log to system_logs: {e}")

    @staticmethod
    def info(component, message, details=None):
        """Log an informational event"""
        SystemLogger.log(SystemLogger.INFO, component, message, details)

    @staticmethod
    def warning(component, message, details=None):
        """Log a warning event"""
        SystemLogger.log(SystemLogger.WARNING, component, message, details)

    @staticmethod
    def error(component, message, details=None):
        """Log an error event"""
        SystemLogger.log(SystemLogger.ERROR, component, message, details)

    @staticmethod
    def success(component, message, details=None):
        """Log a success event"""
        SystemLogger.log(SystemLogger.SUCCESS, component, message, details)

    @staticmethod
    def debug(component, message, details=None):
        """Log a debug event"""
        SystemLogger.log(SystemLogger.DEBUG, component, message, details)

    @staticmethod
    def get_logs(limit=100, offset=0, level=None, component=None, search=None):
        """
        Retrieve logs from database with filtering

        Args:
            limit: Number of logs to retrieve
            offset: Offset for pagination
            level: Filter by log level
            component: Filter by component
            search: Search in message

        Returns:
            List of log entries as dicts
        """
        db = get_db()

        query = "SELECT * FROM system_logs WHERE 1=1"
        params = []

        if level:
            query += " AND level = ?"
            params.append(level)

        if component:
            query += " AND component = ?"
            params.append(component)

        if search:
            query += " AND (message LIKE ? OR details LIKE ?)"
            search_term = f"%{search}%"
            params.extend([search_term, search_term])

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = db.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def get_log_count(level=None, component=None, search=None):
        """Get total count of logs with filters"""
        db = get_db()

        query = "SELECT COUNT(*) as count FROM system_logs WHERE 1=1"
        params = []

        if level:
            query += " AND level = ?"
            params.append(level)

        if component:
            query += " AND component = ?"
            params.append(component)

        if search:
            query += " AND (message LIKE ? OR details LIKE ?)"
            search_term = f"%{search}%"
            params.extend([search_term, search_term])

        result = db.execute(query, params).fetchone()
        return result['count'] if result else 0

    @staticmethod
    def cleanup_old_logs(days=30):
        """Delete logs older than specified days"""
        db = get_db()

        db.execute("""
            DELETE FROM system_logs
            WHERE timestamp < datetime('now', '-' || ? || ' days')
        """, (days,))

        deleted = db.total_changes
        db.commit()

        return deleted

# Convenience instance
syslog = SystemLogger()
