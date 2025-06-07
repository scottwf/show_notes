## 🛠 Development Server with Auto-Restart and Tailwind Watcher

This project is configured to automatically start the Flask development server and Tailwind CSS watcher on system boot using a `systemd` service and a helper script.

### ✅ Features

- Flask runs in development mode (`debug=True`) on port `5001`
- Auto-restarts Flask when `.py` files change (via `watchmedo`)
- Tailwind CSS is compiled in watch mode
- Both processes are managed via a single `systemd` service and `tmux`

---

### 🧩 Systemd Service Setup

A `systemd` unit named `shownotes.service` is used to launch the app on boot.

#### `/etc/systemd/system/shownotes.service`:

```ini
[Unit]
Description=Flask App - ShowNotes with Watchdog Auto-Restart
After=network.target

[Service]
User=scott
WorkingDirectory=/home/scott/show_notes
ExecStart=/home/scott/restart-on-change.sh
Restart=always
Environment=FLASK_ENV=development

[Install]
WantedBy=multi-user.target
```

#### Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now shownotes.service
```

---

### 🔁 Flask + Tailwind Script: `restart-on-change.sh`

This script:

- Activates the Python virtual environment
- Starts Flask with `watchmedo` to reload on `.py` file changes
- Starts the Tailwind watcher in parallel using `tmux`

#### `~/restart-on-change.sh`:

```bash
#!/bin/bash

# Start a new tmux session named 'shownotes' only if it doesn't already exist
tmux has-session -t shownotes 2>/dev/null

if [ $? != 0 ]; then
  # Flask auto-reload
  tmux new-session -d -s shownotes "cd /home/scott/show_notes && source venv/bin/activate && ./venv/bin/watchmedo auto-restart --directory=./ --pattern='*.py' --recursive --signal SIGTERM -- python3 run.py"

  # Tailwind watcher
  tmux split-window -t shownotes -v "cd /home/scott/show_notes && ./watch_tailwind.sh"
fi
```

Make the script executable:

```bash
chmod +x ~/restart-on-change.sh
```

---

### 📺 Viewing Logs

To monitor live output of both Flask and Tailwind:

```bash
tmux attach -t shownotes
```

- Switch between panes: `Ctrl+b`, then arrow keys  
- Detach: `Ctrl+b`, then `d`  
- Kill and restart manually:

```bash
tmux kill-session -t shownotes
sudo systemctl restart shownotes.service
```
