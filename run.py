print("DEBUG: Starting run.py")
from dotenv import load_dotenv

from app import create_app

app = create_app()

if __name__ == "__main__":
    load_dotenv()
    # Run with debug mode but exclude database files from watching
    import os
    import sys
    
    # Set environment variables to reduce file watching
    os.environ['FLASK_ENV'] = 'development'
    
    # Only watch specific directories, not the entire project
    extra_files = [
        'app/',
        'app/templates/',
        'app/static/',
        'app/routes/',
        'app/migrations/',
        'requirements.txt',
        'run.py'
    ]
    
    app.run(debug=True, host='0.0.0.0', port=5001, extra_files=extra_files)
