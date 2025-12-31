# ShowNotes Makefile
# Common development tasks

.PHONY: help setup install dev clean reset-db build-css watch-css docker-build docker-run docker-stop test

# Default target
help:
	@echo "ShowNotes - Development Commands"
	@echo "================================="
	@echo ""
	@echo "Setup Commands:"
	@echo "  make setup          - Initial setup (venv, deps, db, .env)"
	@echo "  make install        - Install/update Python dependencies"
	@echo ""
	@echo "Development Commands:"
	@echo "  make dev            - Run development server"
	@echo "  make watch          - Run dev server + Tailwind watch"
	@echo "  make build-css      - Build Tailwind CSS once"
	@echo "  make watch-css      - Watch and rebuild Tailwind CSS"
	@echo ""
	@echo "Database Commands:"
	@echo "  make reset-db       - Reset database (WARNING: deletes data)"
	@echo "  make backup-db      - Backup current database"
	@echo ""
	@echo "Docker Commands:"
	@echo "  make docker-build   - Build Docker image"
	@echo "  make docker-run     - Run Docker container"
	@echo "  make docker-stop    - Stop Docker container"
	@echo "  make docker-logs    - View Docker logs"
	@echo ""
	@echo "Cleanup Commands:"
	@echo "  make clean          - Remove generated files"
	@echo "  make clean-all      - Remove everything (venv, db, cache)"
	@echo ""

# Initial setup
setup: venv/bin/activate .env
	@echo "✅ Setup complete!"
	@echo ""
	@echo "Edit .env with your settings, then run:"
	@echo "  make dev"

venv/bin/activate: requirements.txt
	@echo "Creating virtual environment..."
	python3 -m venv venv
	./venv/bin/pip install --upgrade pip
	./venv/bin/pip install -r requirements.txt
	@echo "✅ Virtual environment created"

.env:
	@echo "Creating .env file..."
	cp .env.example .env
	@echo "⚠️  Edit .env with your Plex settings"

# Install dependencies
install: venv/bin/activate
	@echo "Installing dependencies..."
	./venv/bin/pip install -r requirements.txt
	@echo "✅ Dependencies installed"

# Initialize database
init-db:
	@echo "Initializing database..."
	./venv/bin/python init_fresh_database.py
	@echo "✅ Database initialized"

# Run development server
dev: venv/bin/activate .env
	@echo "Starting ShowNotes development server..."
	@echo "Access at: http://localhost:5001"
	./venv/bin/python run.py

# Run dev server + Tailwind watch in parallel
watch: venv/bin/activate .env
	@echo "Starting ShowNotes with Tailwind watch mode..."
	@command -v tmux >/dev/null 2>&1 || { echo "tmux not found. Install with: sudo apt install tmux"; exit 1; }
	tmux new-session -d -s shownotes-dev
	tmux split-window -h
	tmux send-keys -t shownotes-dev:0.0 'cd $(PWD) && source venv/bin/activate && python3 run.py' C-m
	tmux send-keys -t shownotes-dev:0.1 'cd $(PWD) && npx tailwindcss -i ./app/static/input.css -o ./app/static/css/style.css --watch' C-m
	tmux attach -t shownotes-dev

# Build Tailwind CSS
build-css:
	@echo "Building Tailwind CSS..."
	npx tailwindcss -i ./app/static/input.css -o ./app/static/css/style.css --minify
	@echo "✅ CSS built"

# Watch Tailwind CSS
watch-css:
	@echo "Watching Tailwind CSS changes..."
	npx tailwindcss -i ./app/static/input.css -o ./app/static/css/style.css --watch

# Reset database
reset-db:
	@echo "⚠️  WARNING: This will delete all data!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		rm -f instance/shownotes.sqlite3; \
		./venv/bin/python init_fresh_database.py; \
		echo "✅ Database reset complete"; \
	else \
		echo "Cancelled"; \
	fi

# Backup database
backup-db:
	@echo "Backing up database..."
	@mkdir -p backups
	@cp instance/shownotes.sqlite3 backups/shownotes-$(shell date +%Y%m%d-%H%M%S).sqlite3
	@echo "✅ Database backed up to backups/"

# Docker commands
docker-build:
	@echo "Building Docker image..."
	docker build -t shownotes:latest .
	@echo "✅ Docker image built"

docker-run:
	@echo "Running Docker container..."
	docker-compose up -d
	@echo "✅ Container started"
	@echo "Access at: http://localhost:5001"

docker-stop:
	@echo "Stopping Docker container..."
	docker-compose down
	@echo "✅ Container stopped"

docker-logs:
	docker-compose logs -f shownotes

# Clean generated files
clean:
	@echo "Cleaning generated files..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.log" -delete 2>/dev/null || true
	rm -rf .pytest_cache
	@echo "✅ Cleaned"

# Clean everything
clean-all: clean
	@echo "⚠️  WARNING: This will remove venv, database, and all caches!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		rm -rf venv; \
		rm -rf instance; \
		rm -rf logs; \
		rm -rf node_modules; \
		echo "✅ Everything cleaned"; \
	else \
		echo "Cancelled"; \
	fi

# Run tests (when available)
test: venv/bin/activate
	@echo "Running tests..."
	./venv/bin/python -m pytest tests/ -v

# Check code quality (optional)
lint: venv/bin/activate
	@echo "Checking code quality..."
	./venv/bin/flake8 app/ || echo "flake8 not installed"
	./venv/bin/black --check app/ || echo "black not installed"
