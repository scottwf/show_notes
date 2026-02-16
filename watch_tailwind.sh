#!/bin/bash
echo "Starting Tailwind CSS watcher..."
echo "Monitoring ./app/static/input.css and your template/JS files."
echo "Outputting to ./app/static/css/style.css"
echo "Press Ctrl+C to stop."
npm run watch:css
