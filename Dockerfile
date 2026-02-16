FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user matching host UID/GID
RUN groupadd -g 1000 shownotes && \
    useradd -u 1000 -g 1000 -m -s /bin/bash shownotes

# Copy dependency manifests
COPY requirements.txt .
COPY package.json .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt gunicorn
RUN npm install --no-audit --no-fund

# Copy application code
COPY . .

# Build Tailwind CSS once at image build time
RUN npm run build:css

# Create instance directory and set ownership
RUN mkdir -p instance logs && \
    chown -R shownotes:shownotes /app

# Switch to non-root user
USER shownotes

# Expose port
EXPOSE 5003

# Set environment variables
ENV FLASK_APP=run.py
ENV PYTHONUNBUFFERED=1

# Rebuild Tailwind CSS at startup to avoid stale styles, then run Gunicorn
CMD ["sh", "-c", "npm run build:css && exec gunicorn --bind 0.0.0.0:5003 --workers 4 --timeout 120 run:app"]
