import os
from flask import Flask
from . import database
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

    from . import routes
    app.register_blueprint(routes.bp)

    # Add other blueprints here (if any)
    # from .auth import auth as auth_blueprint
    # app.register_blueprint(auth_blueprint)

    return app
