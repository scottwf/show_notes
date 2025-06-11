import os
from flask import Flask
from flask_login import LoginManager
from . import database
import sqlite3
import logging
from logging.handlers import RotatingFileHandler

def create_app(test_config=None):
    app = Flask(
        __name__,
        instance_relative_config=True,
        static_folder='static',  # best practice: relative to the app package
        static_url_path='/static'
    )
    app.config.from_mapping(
        SECRET_KEY='dev', # Replace with a real secret key in production
        DATABASE=os.path.join(app.instance_path, 'shownotes.sqlite3'),
    )

    if test_config is None:
        # load the instance config, if it exists, when not testing
        app.config.from_pyfile('config.py', silent=True)
    else:
        # load the test config if passed in
        app.config.from_mapping(test_config)

    # ensure the instance folder exists
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        # TODO: Add proper logging for this error
        pass

    # Configure logging
    log_file = '/tmp/shownotes_app.log'
    # Rotate logs at 10MB, keep 5 backups
    file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.DEBUG) # Set file handler to DEBUG
    
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.DEBUG) # Set app logger to DEBUG
    
    # Also set root logger to DEBUG to catch other potential logs if needed
    # Or configure specific loggers like 'werkzeug' if their default level is too high
    logging.getLogger().setLevel(logging.DEBUG) 

    app.logger.info("ShowNotes application logging configured to /tmp/shownotes_app.log")

    database.init_app(app)

    # Initialize the database if tables are missing
    with app.app_context():
        db = database.get_db()
        needs_init = False
        try:
            # Check schema version
            db_version = db.execute('SELECT version FROM schema_version WHERE id = 1').fetchone()
            if not db_version or db_version['version'] < database.CURRENT_SCHEMA_VERSION:
                app.logger.warning(f"Database schema is out of date (DB version: {db_version['version'] if db_version else 'None'}, Code version: {database.CURRENT_SCHEMA_VERSION}). Re-initializing.")
                needs_init = True
            else:
                app.logger.info(f"Database schema is up to date (version {db_version['version']}).")
        except sqlite3.OperationalError as e:
            # This likely means the schema_version table itself doesn't exist.
            if 'no such table' in str(e).lower():
                app.logger.warning(f"Database version table not found (error: {e}). Assuming new or old database. Re-initializing.")
                needs_init = True
            else:
                app.logger.error(f"An unexpected database error occurred during startup check: {e}", exc_info=True)
                raise # For other DB errors, it's better to fail fast

        if needs_init:
            database.init_db()
            app.logger.info(f"Database successfully initialized/updated at {app.config['DATABASE']}.")

    from . import routes
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'main.login'  # Or your actual login route like 'main.login_plex_start'
    login_manager.session_protection = "strong"

    class User:
        def __init__(self, id, username, is_admin=False):
            self.id = id
            self.username = username
            self.is_admin = bool(is_admin) # Ensure boolean
            self.is_active = True
            self.is_authenticated = True
            self.is_anonymous = False

        def get_id(self):
            return str(self.id)

    @login_manager.user_loader
    def load_user(user_id):
        db = database.get_db()
        user_data = db.execute(
            'SELECT id, username, is_admin FROM users WHERE id = ?',
            (user_id,)
        ).fetchone()
        if user_data:
            return User(
                id=user_data['id'], 
                username=user_data['username'], 
                is_admin=user_data['is_admin'] # Directly access, bool() in User.__init__ handles conversion
            )
        return None

    app.register_blueprint(routes.bp)

    # Add other blueprints here (if any)
    # from .auth import auth as auth_blueprint
    # app.register_blueprint(auth_blueprint)

    return app
