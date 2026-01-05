import os
import logging
from datetime import timedelta, datetime
from logging.handlers import RotatingFileHandler
from flask import Flask
from flask_login import LoginManager
from . import database
from . import cli
from .utils import format_datetime_simple, format_milliseconds

login_manager = LoginManager()

print("DEBUG: Starting create_app() in app/__init__.py")
def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)

    # --- Configuration ---
    app.config.from_mapping(
        SECRET_KEY='dev',  # IMPORTANT: Change this for production!
        DATABASE=os.path.join(app.instance_path, 'shownotes.sqlite3'),
        ENVIRONMENT=os.environ.get('ENVIRONMENT', 'development'),  # 'development' or 'production'
        # Session configuration for persistent login
        SESSION_PERMANENT=True,
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),  # Sessions last 30 days
        SESSION_COOKIE_SECURE=False,  # Set to True in production with HTTPS
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
    )

    print("DEBUG: Finished configuration setup")

    if test_config is None:
        # Load the instance config, if it exists, when not testing
        app.config.from_pyfile('config.py', silent=True)
    else:
        # Load the test config if passed in
        app.config.from_mapping(test_config)

    print("DEBUG: Finished loading config")

    # Ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass # Already exists

    print("DEBUG: Instance folder exists")

    # --- Logging Configuration ---
    # Place logs in a 'logs' directory at the project root
    log_dir = os.path.join(os.path.dirname(app.root_path), 'logs') 
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'shownotes.log')

    # Rotating file handler: 5MB per file, 5 backup files
    file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=5)
    formatter = logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO) # Set level for the handler
    
    # Add handler to Flask's logger and the root logger
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)
    print(f"DEBUG: Logging enabled to file: {log_file}")

    print("DEBUG: Finished logging setup")

    # --- Database Setup ---
    # The init_app function in database_clean.py will register CLI commands like 'init-db'
    # It does NOT automatically create the database on app start anymore.
    database.init_app(app)
    print("DEBUG: Finished database setup")

    cli.init_app(app) # Register CLI commands from app/cli.py

    # --- Login Manager Setup ---
    login_manager.init_app(app)
    login_manager.login_view = 'main.login' # The route for the login page

    # Define a simple User class for Flask-Login
    # In a real app, this would likely be a more complex model (e.g., from SQLAlchemy)
    class User:
        # Basic User model for Flask-Login
        def __init__(self, id, username, is_admin=False):
            self.id = id
            self.username = username
            self.is_admin = bool(is_admin) # Ensure it's a boolean
            self.is_authenticated = True
            self.is_active = True
            self.is_anonymous = False

        def get_id(self):
            return str(self.id)

    @login_manager.user_loader
    def load_user(user_id):
        # This function is called by Flask-Login to get a User object for a given user_id
        try:
            db = database.get_db()
            user_data = db.execute(
                'SELECT * FROM users WHERE id = ?', (user_id,)
            ).fetchone()
            if user_data:
                return User(id=user_data['id'], username=user_data['username'], is_admin=user_data['is_admin'])
        except Exception as e:
            # Log the error if the database query fails (e.g., table not yet created)
            app.logger.error(f"Error loading user {user_id} from database: {e}")
        return None # Return None if the user is not found or an error occurs

    # --- Register Blueprints ---
    from .routes.main import main_bp
    from .routes.admin import admin_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)

    # Register Jinja filters
    app.jinja_env.filters['format_datetime'] = format_datetime_simple
    app.jinja_env.filters['format_ms'] = format_milliseconds

    # Register context processor to make current year available in all templates
    @app.context_processor
    def inject_current_year():
        return {'current_year': datetime.now().year}

    app.logger.info('ShowNotes application successfully created.')
    return app
