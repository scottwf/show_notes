# ShowNotes - Quick Start Guide

Get ShowNotes running in under 5 minutes!

## Option 1: Standard Installation (Recommended for First-Time Users)

```bash
# Clone the repository
git clone https://github.com/scottwf/show_notes.git
cd show_notes

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and set PLEX_CLIENT_ID and PLEX_APP_URL

# Initialize database
python3 init_fresh_database.py

# Run the application
python3 run.py
```

**Access:** Open http://localhost:5001 in your browser

---

## Option 2: Docker (Easiest Setup)

```bash
# Clone the repository
git clone https://github.com/scottwf/show_notes.git
cd show_notes

# Copy environment file
cp .env.example .env
# Edit .env with your Plex settings

# Build and run with Docker Compose
docker-compose up -d

# View logs
docker-compose logs -f shownotes
```

**Access:** Open http://localhost:5001 in your browser

### Stop the container:
```bash
docker-compose down
```

### Update the container:
```bash
docker-compose pull
docker-compose up -d
```

---

## Option 3: Docker Run (One-Line Command)

```bash
docker run -d \
  --name shownotes \
  -p 5001:5001 \
  -v shownotes-data:/app/instance \
  -e PLEX_CLIENT_ID=shownotes-instance \
  -e PLEX_APP_URL=http://localhost:5001 \
  scottwf/shownotes:latest
```

**Note:** Replace `http://localhost:5001` with your server's accessible URL if accessing remotely.

---

## Initial Configuration

After starting ShowNotes for the first time:

1. **Open the admin panel:** http://localhost:5001/admin/settings

2. **Configure Plex:**
   - Enter your Plex server URL
   - Click "Authenticate with Plex"

3. **Configure services** (optional but recommended):
   - Sonarr (TV shows)
   - Radarr (Movies)
   - Bazarr (Subtitles)
   - Ollama or OpenAI (AI summaries)

4. **Sync your libraries:**
   - Go to http://localhost:5001/admin/tasks
   - Click "Sync Sonarr Library"
   - Click "Sync Radarr Library"

5. **Set up Plex webhook** (for automatic watch tracking):
   - In Plex: Settings → Webhooks
   - Add webhook: `http://YOUR_SERVER_IP:5001/webhook/plex`

---

## What's Next?

- ✅ Browse your TV show library
- ✅ Get spoiler-aware character summaries
- ✅ Find actor overlap between shows
- ✅ Chat with characters using AI
- ✅ Track your watch history
- ✅ Get episode summaries and recommendations

---

## Need Help?

- **Detailed setup:** See [SETUP.md](SETUP.md) for comprehensive instructions
- **Features:** See [README.md](README.md) for full feature documentation
- **Issues:** Report bugs at https://github.com/scottwf/show_notes/issues
- **Troubleshooting:** Check [SETUP.md](SETUP.md#troubleshooting) for common issues

---

## System Requirements

### Minimum:
- Python 3.8+ **OR** Docker
- 1 GB RAM
- 500 MB disk space

### Recommended:
- Python 3.12+ **OR** Docker
- 2 GB RAM
- 2 GB disk space (for cached images)
- Plex Media Server (for watch tracking)
- Sonarr/Radarr (for metadata)

---

## Quick Reference

| Task | Command |
|------|---------|
| Start app (standard) | `source venv/bin/activate && python3 run.py` |
| Start app (Docker) | `docker-compose up -d` |
| Stop app (Docker) | `docker-compose down` |
| View logs (Docker) | `docker-compose logs -f shownotes` |
| Reset database | `rm instance/shownotes.sqlite3 && python3 init_fresh_database.py` |
| Update dependencies | `pip install -r requirements.txt --upgrade` |
| Rebuild Tailwind CSS | `npx tailwindcss -i ./app/static/input.css -o ./app/static/css/style.css --minify` |

---

**Happy watching! 🎬**
