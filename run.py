print("DEBUG: Starting run.py")
from dotenv import load_dotenv

from app import create_app

app = create_app()

if __name__ == "__main__":
    print("DEBUG: Entering main block in run.py")
    load_dotenv()
    print("DEBUG: Loaded .env")
    # app = create_app()  # This line is already executed before the if block
    print("DEBUG: Created app, about to run app.run()")
    app.run(debug=True, host='0.0.0.0', port=5001)
    print("DEBUG: app.run() has exited")
