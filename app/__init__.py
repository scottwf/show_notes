import os
from flask import Flask
from . import database

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

    database.init_app(app)

    from . import routes
    app.register_blueprint(routes.bp)

    # Add other blueprints here (if any)
    # from .auth import auth as auth_blueprint
    # app.register_blueprint(auth_blueprint)

    return app
