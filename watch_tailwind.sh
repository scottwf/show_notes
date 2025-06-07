#!/bin/bash
echo "Starting Tailwind CSS watcher..."
echo "Monitoring ./app/static/input.css and your template files."
echo "Outputting to ./app/static/admin_settings.css"
echo "Press Ctrl+C to stop."
npx tailwindcss -i ./app/static/input.css -o ./app/static/admin_settings.css --watch
