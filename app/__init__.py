import os
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask
from flask_login import LoginManager
from . import database # Reverted to use the original database.py

login_manager = LoginManager()

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)

    # --- Configuration ---
    app.config.from_mapping(
        SECRET_KEY='dev',  # IMPORTANT: Change this for production!
        DATABASE=os.path.join(app.instance_path, 'shownotes.sqlite3'),
    )

    if test_config is None:
        # Load the instance config, if it exists, when not testing
        app.config.from_pyfile('config.py', silent=True)
    else:
        # Load the test config if passed in
        app.config.from_mapping(test_config)

    # Ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass # Already exists

    # --- Logging Configuration ---
    # Place logs in a 'logs' directory at the project root
    log_dir = os.path.join(os.path.dirname(app.root_path), 'logs') 
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'shownotes.log')

    # Rotating file handler: 10MB per file, 5 backup files
    file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
    formatter = logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO) # Set level for the handler
    
    # Add handler to Flask's logger and the root logger
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO) # Set level for Flask's logger
    
    # Configure root logger to also use this handler (optional, but good practice)
    # This ensures libraries also log through our setup if they use standard logging
    logging.getLogger().addHandler(file_handler)
    logging.getLogger().setLevel(logging.INFO)

    app.logger.info('ShowNotes application startup: Logging configured.')

    # --- Database Setup ---
    # The init_app function in database_clean.py will register CLI commands like 'init-db'
    # It does NOT automatically create the database on app start anymore.
    database.init_app(app)

    # --- Login Manager Setup ---
    login_manager.init_app(app)
    login_manager.login_view = 'main.login' # The route for the login page

    # Define a simple User class for Flask-Login
    # In a real app, this would likely be a more complex model (e.g., from SQLAlchemy)
    class User:
        def __init__(self, id, username):
            self.id = id
            self.username = username
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
                return User(id=user_data['id'], username=user_data['username'])
        except Exception as e:
            # Log the error if the database query fails (e.g., table not yet created)
            app.logger.error(f"Error loading user {user_id} from database: {e}")
        return None # Return None if the user is not found or an error occurs

    # --- Register Blueprints ---
    from . import routes  # Import your routes blueprint
    app.register_blueprint(routes.bp)
    # If you have other blueprints, register them here
    # Example: from . import admin_routes
    #          app.register_blueprint(admin_routes.admin_bp, url_prefix='/admin')

    app.logger.info('ShowNotes application successfully created.')
    return app
