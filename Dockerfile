FROM python:3.12-slim

# Install Node.js and system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Build Tailwind CSS
RUN npx tailwindcss -i ./app/static/input.css -o ./app/static/css/style.css --minify

# Create instance directory for database
RUN mkdir -p instance

# Expose port
EXPOSE 5001

# Set environment variables
ENV FLASK_APP=run.py
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5001/ || exit 1

# Initialize database and run application
CMD python3 init_fresh_database.py && python3 run.py
