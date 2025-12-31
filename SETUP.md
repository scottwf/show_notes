# ShowNotes Setup Guide

Complete setup instructions for getting ShowNotes up and running on your system.

---

## Table of Contents
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Detailed Setup Steps](#detailed-setup-steps)
- [Configuration](#configuration)
- [Running the Application](#running-the-application)
- [Docker Setup (Coming Soon)](#docker-setup-coming-soon)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

Before you begin, ensure you have the following installed on your system:

### Required
- **Python 3.8+** (tested with Python 3.12)
- **Node.js v18+** and **npm v9+** (for Tailwind CSS)
- **Git** (for cloning the repository)

### Optional (for full functionality)
- **Plex Media Server** (for watch history tracking)
- **Sonarr** (for TV show metadata)
- **Radarr** (for movie metadata)
- **Bazarr** (for subtitle import)
- **Ollama** or **OpenAI API** (for AI-powered summaries)
- **Tautulli** (for enhanced Plex analytics)

### Verify Prerequisites

```bash
# Check Python version (should be 3.8 or higher)
python3 --version

# Check Node.js version (should be 18 or higher)
node --version

# Check npm version (should be 9 or higher)
npm --version

# Check Git
git --version
```

---

## Quick Start

For users who just want to get the app running quickly:

```bash
# 1. Clone the repository
git clone https://github.com/scottwf/show_notes.git
cd show_notes

# 2. Create Python virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Create environment configuration
cp .env.example .env
# Edit .env with your preferred text editor to configure Plex settings

# 5. Initialize the database
python3 init_fresh_database.py

# 6. Build Tailwind CSS (optional if style.css already exists)
npx tailwindcss -i ./app/static/input.css -o ./app/static/css/style.css --minify

# 7. Run the application
python3 run.py
```

The application will be available at `http://localhost:5001`

---

## Detailed Setup Steps

### Step 1: Clone the Repository

```bash
git clone https://github.com/scottwf/show_notes.git
cd show_notes
```

### Step 2: Set Up Python Virtual Environment

**Why?** Virtual environments isolate Python dependencies to avoid conflicts with system packages.

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
# On Linux/Mac:
source venv/bin/activate

# On Windows:
venv\Scripts\activate

# Your prompt should now show (venv) prefix
```

### Step 3: Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**Installed packages include:**
- Flask (web framework)
- Flask-Login (user authentication)
- Werkzeug (WSGI utilities)
- requests (HTTP library)
- python-dotenv (environment variables)
- openai (OpenAI API client)
- ollama (Ollama API client)
- markdown (Markdown parsing)
- thefuzz (fuzzy string matching)
- pytz (timezone handling)

### Step 4: Environment Configuration

```bash
# Copy the example environment file
cp .env.example .env
```

**Edit `.env` with your settings:**

```bash
# Minimum required for basic operation:
PLEX_CLIENT_ID="shownotes-your-instance-name"
PLEX_APP_URL="http://localhost:5001"

# Optional services (configure later via admin panel):
# SONARR_API_KEY="your_sonarr_api_key"
# SONARR_URL="http://localhost:8989"
# RADARR_API_KEY="your_radarr_api_key"
# RADARR_URL="http://localhost:7878"
# BAZARR_API_KEY="your_bazarr_api_key"
# BAZARR_URL="http://localhost:6767"
# OLLAMA_API_URL="http://localhost:11434"
```

**Note:** Most service configurations can be set via the admin panel after first run. The .env file is primarily for Plex OAuth configuration.

### Step 5: Initialize the Database

```bash
python3 init_fresh_database.py
```

This script will:
- Create the `instance/` directory if it doesn't exist
- Create the SQLite database at `instance/shownotes.sqlite3`
- Run all database migrations
- Set up initial tables and schema

**Expected output:**
```
======================================================================
               DATABASE INITIALIZATION
======================================================================

🔄 Running all migrations to create database schema...
📁 Found 56 migration files
...
```

Some warnings about `__file__` or missing tables are normal during initial setup.

### Step 6: Build Tailwind CSS (if needed)

The repository may already include a compiled `app/static/css/style.css`. If not, or if you modify styles:

```bash
# One-time build:
npx tailwindcss -i ./app/static/input.css -o ./app/static/css/style.css --minify

# Watch mode for development (auto-rebuilds on changes):
npx tailwindcss -i ./app/static/input.css -o ./app/static/css/style.css --watch
```

**Alternative:** Use the included watch script:
```bash
bash watch_tailwind.sh
```

### Step 7: Run the Application

**Development mode:**
```bash
python3 run.py
```

The application will start on `http://localhost:5001` by default.

**Custom port:**
```bash
# If port 5001 is in use, modify run.py or run directly:
python3 -c "from app import create_app; app = create_app(); app.run(debug=True, host='0.0.0.0', port=5002)"
```

**Access the application:**
- Main site: `http://localhost:5001`
- Admin panel: `http://localhost:5001/admin/dashboard`

---

## Configuration

### First-Time Setup

1. **Navigate to the admin panel:** `http://localhost:5001/admin/settings`

2. **Configure Plex Authentication:**
   - Click on the Plex section
   - Enter your Plex server URL
   - Click "Authenticate with Plex" to link your account

3. **Configure Optional Services:**
   - **Sonarr:** Enter API URL and API key (found in Sonarr → Settings → General)
   - **Radarr:** Enter API URL and API key (found in Radarr → Settings → General)
   - **Bazarr:** Enter API URL and API key (found in Bazarr → Settings → General)
   - **Ollama/OpenAI:** Configure your LLM provider for AI summaries
   - **Tautulli:** Configure for enhanced Plex analytics

4. **Test Connections:**
   - Use the "Test" button next to each service to verify connectivity
   - Green indicator = successful connection
   - Red indicator = connection failed (check URL and API key)

5. **Sync Your Library:**
   - Navigate to `http://localhost:5001/admin/tasks`
   - Click "Sync Sonarr Library" to import TV shows
   - Click "Sync Radarr Library" to import movies

### Plex Webhook Setup

To automatically track viewing progress:

1. **In Plex Web:**
   - Settings → Webhooks
   - Add webhook URL: `http://YOUR_SERVER_IP:5001/webhook/plex`

2. **Plex will now send events when you:**
   - Play media
   - Pause media
   - Resume media
   - Stop media
   - Complete watching (scrobble)

---

## Running the Application

### Development Mode

**Standard:**
```bash
source venv/bin/activate
python3 run.py
```

**With Tailwind watch (recommended for development):**

Terminal 1:
```bash
source venv/bin/activate
python3 run.py
```

Terminal 2:
```bash
npx tailwindcss -i ./app/static/input.css -o ./app/static/css/style.css --watch
```

**Or use the advanced watchdog setup** (see `docs/dev-server-watchdog.md` for systemd + tmux setup)

### Production Deployment

For production, use a WSGI server like Gunicorn:

```bash
# Install Gunicorn
pip install gunicorn

# Run with Gunicorn (4 workers)
gunicorn -w 4 -b 0.0.0.0:5001 "app:create_app()"
```

**Or use the included systemd service:**
```bash
sudo cp shownotes.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable shownotes
sudo systemctl start shownotes
```

Edit the service file to match your installation path and user.

---

## Docker Setup (Coming Soon)

Docker support is planned for easier deployment. The Docker setup will include:

- Single command installation
- Automatic database initialization
- Pre-built Tailwind CSS
- Environment variable configuration
- Volume mounting for persistent data
- Docker Compose for multi-container setup (with optional Ollama container)

**Proposed Docker usage:**
```bash
# Quick start with Docker
docker run -d \
  -p 5001:5001 \
  -v shownotes-data:/app/instance \
  -e PLEX_CLIENT_ID=your-client-id \
  -e PLEX_APP_URL=http://localhost:5001 \
  scottwf/shownotes:latest

# Or with Docker Compose
docker-compose up -d
```

**Current workaround:** For now, you can create your own Dockerfile based on this setup:

```dockerfile
FROM python:3.12-slim

# Install Node.js
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash -
RUN apt-get install -y nodejs

WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Build Tailwind CSS
RUN npx tailwindcss -i ./app/static/input.css -o ./app/static/css/style.css --minify

# Initialize database
RUN python3 init_fresh_database.py

# Expose port
EXPOSE 5001

# Run application
CMD ["python3", "run.py"]
```

---

## Troubleshooting

### Port Already in Use

**Problem:** `Address already in use` error when starting the app.

**Solution:**
```bash
# Find what's using port 5001
sudo lsof -i :5001

# Kill the process or use a different port
python3 -c "from app import create_app; app = create_app(); app.run(debug=True, port=5002)"
```

### Database Errors

**Problem:** `no such table` errors or migration failures.

**Solution:**
```bash
# Reset database (WARNING: deletes all data)
rm instance/shownotes.sqlite3
python3 init_fresh_database.py
```

### Python Module Not Found

**Problem:** `ModuleNotFoundError` when running the app.

**Solution:**
```bash
# Ensure virtual environment is activated
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Reinstall dependencies
pip install -r requirements.txt
```

### Tailwind CSS Not Building

**Problem:** `tailwind: not found` error.

**Solution:**
```bash
# Use npx to run tailwindcss directly
npx tailwindcss -i ./app/static/input.css -o ./app/static/css/style.css

# Or if that fails, the CSS file is already included in the repo
# You can use it as-is
```

### Plex Authentication Fails

**Problem:** Can't connect to Plex or OAuth fails.

**Solution:**
1. Verify `PLEX_APP_URL` in `.env` matches your actual server URL
2. Ensure the URL is accessible from your Plex server
3. Check Plex server is running and accessible
4. Verify firewall rules allow access to port 5001

### Service Connection Tests Fail

**Problem:** Admin panel shows red indicators for services.

**Solution:**
1. Verify service is running (Sonarr/Radarr/etc.)
2. Check API URL format: `http://localhost:8989` (no trailing slash)
3. Verify API key is correct (copy/paste from service settings)
4. Check firewall rules between ShowNotes and services
5. Test API manually:
   ```bash
   curl -H "X-Api-Key: YOUR_API_KEY" http://localhost:8989/api/v3/system/status
   ```

### External Access Issues

**Problem:** Can't access from other devices on network.

**Solution:**
```bash
# Run with 0.0.0.0 to bind to all interfaces
python3 -c "from app import create_app; app = create_app(); app.run(debug=True, host='0.0.0.0', port=5001)"

# Update .env with your network IP
PLEX_APP_URL="http://YOUR_LOCAL_IP:5001"
```

---

## Next Steps

After successful setup:

1. **Configure Services:** Set up Sonarr, Radarr, and other integrations via admin panel
2. **Sync Libraries:** Import your TV shows and movies
3. **Set Up Plex Webhook:** Enable automatic watch tracking
4. **Explore Features:** Try character summaries, show searches, and AI chat
5. **Customize:** Adjust LLM prompts, notification settings, and preferences

For more information, see the main [README.md](README.md) for feature documentation.

---

## Getting Help

- **Issues:** Report bugs at https://github.com/scottwf/show_notes/issues
- **Documentation:** Check `docs/` folder for advanced topics
- **Community:** Join discussions on the GitHub repository

---

## Summary of Commands

```bash
# Complete setup from scratch
git clone https://github.com/scottwf/show_notes.git
cd show_notes
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your settings
python3 init_fresh_database.py
python3 run.py
```

**That's it!** ShowNotes should now be running at `http://localhost:5001`
