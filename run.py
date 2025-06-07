from app import create_app

app = create_app()

if __name__ == '__main__':
    # Allow access from outside the host (useful for domain testing)
    app.run(debug=True, host='0.0.0.0', port=5001)
