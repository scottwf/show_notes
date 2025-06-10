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

    from .routes.admin_api import admin_api_bp
    app.register_blueprint(admin_api_bp)

    from .routes.admin import admin_bp
    app.register_blueprint(admin_bp)

    # Add other blueprints here (if any)
    # from .auth import auth as auth_blueprint
    # app.register_blueprint(auth_blueprint)

    # Initialize and start APScheduler
    # Make sure this is done only once, typically when the app is created, not for every request.
    # The standard Flask development server (werkzeug) might run create_app twice when reloading.
    # Consider if app.scheduler attribute check or similar is needed if issues arise with duplicate schedulers.
    if not hasattr(app, 'scheduler'): # Ensure scheduler is initialized only once
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from app.scheduler import check_all_services_status
        import atexit

        app.scheduler = AsyncIOScheduler(timezone="UTC") # Use UTC for timezone consistency
        app.scheduler.add_job(
            check_all_services_status,
            'interval',
            minutes=5, # Interval for checking services
            id='check_services_job',
            args=[app], # Pass the Flask app instance
            misfire_grace_time=60 # Allow job to run 60s late if scheduler was busy
        )
        try:
            app.scheduler.start()
            app.logger.info("APScheduler started for service status checks.")

            # Register shutdown hook
            atexit.register(lambda: app.scheduler.shutdown())
            app.logger.info("APScheduler shutdown hook registered.")
        except Exception as e:
            app.logger.error(f"Failed to start APScheduler: {e}", exc_info=True)


    return app
