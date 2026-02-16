#!/bin/bash
echo "Starting Tailwind CSS watcher..."
echo "Monitoring ./app/static/input.css and your template files."
echo "Outputting to ./app/static/css/style.css"
echo "Press Ctrl+C to stop."
npx tailwindcss -i ./app/static/src/input.css -o ./app/static/css/style.css --watch
