# ShowNotes Setup Guide

Detailed setup instructions for ShowNotes. For a quick start, see [QUICKSTART.md](QUICKSTART.md).

## Prerequisites

- **Python 3.8+** (tested with Python 3.12)
- **Node.js v18+** and **npm v9+** (for Tailwind CSS)
- **Git**

Optional services for full functionality:
- Plex Media Server, Sonarr, Radarr, Bazarr, Tautulli, Ollama/OpenAI

## Installation

### 1. Clone and Setup Environment

```bash
git clone https://github.com/scottwf/show_notes.git
cd show_notes
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env - minimum required:
# PLEX_CLIENT_ID="shownotes-your-instance"
# PLEX_APP_URL="http://localhost:5001"
```

### 3. Initialize Database

```bash
python3 init_fresh_database.py
```

### 4. Run

```bash
python3 run.py
```

Access at `http://localhost:5001`

## Post-Installation Configuration

### Admin Panel Setup

1. Navigate to `http://localhost:5001/admin/settings`
2. Configure Plex authentication
3. Add optional services (Sonarr, Radarr, etc.) with API keys
4. Test connections with "Test" buttons
5. Go to `/admin/tasks` and sync your libraries

### Plex Webhook

For automatic watch tracking:
1. In Plex: Settings → Webhooks
2. Add: `http://YOUR_SERVER:5001/webhook/plex`

### Sonarr/Radarr Webhooks

For automatic library updates:
1. In service: Settings → Connect → Add Webhook
2. URL: `http://YOUR_SERVER:5001/sonarr/webhook` or `/radarr/webhook`
3. Enable events: Series/Movie Add, Download, Delete

## Production Deployment

### Systemd Service

```bash
sudo cp shownotes.service /etc/systemd/system/
# Edit service file with your paths
sudo systemctl daemon-reload
sudo systemctl enable shownotes
sudo systemctl start shownotes
```

### Docker (Recommended)

```bash
cp .env.example .env
# Edit .env with your settings
docker-compose up -d
```

## Troubleshooting

### Port Conflicts
```bash
# Check what's using port 5001
sudo lsof -i :5001
# Use different port
python3 run.py --port 5002
```

### Database Issues
```bash
# Reset database (WARNING: deletes all data)
rm instance/shownotes.sqlite3
python3 init_fresh_database.py
```

### Module Not Found
```bash
# Activate virtual environment
source venv/bin/activate
pip install -r requirements.txt
```

### Service Connection Failures
1. Verify service is running
2. Check URL format (no trailing slash): `http://localhost:8989`
3. Verify API key from service settings
4. Test manually: `curl -H "X-Api-Key: KEY" http://localhost:8989/api/v3/system/status`

### External Access
```bash
# Bind to all interfaces
python3 -c "from app import create_app; app = create_app(); app.run(debug=True, host='0.0.0.0', port=5001)"
# Update .env with your network IP
```

## Development

### Tailwind CSS

```bash
# Watch mode for development
npx tailwindcss -i ./app/static/input.css -o ./app/static/css/style.css --watch
# Or use included script
bash watch_tailwind.sh
```

### Advanced Dev Setup

See [docs/dev-server-watchdog.md](docs/dev-server-watchdog.md) for auto-restart configuration with systemd and tmux.

## Getting Help

- **Quick Start:** [QUICKSTART.md](QUICKSTART.md)
- **Features:** [README.md](README.md)
- **Issues:** https://github.com/scottwf/show_notes/issues
