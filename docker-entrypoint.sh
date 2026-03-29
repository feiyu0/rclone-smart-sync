#!/bin/bash
set -e

echo "Starting Rclone Sync Service..."

# Create necessary directories
mkdir -p /data /config /logs

# Set proper permissions
chown -R appuser:appuser /data /config /logs 2>/dev/null || true

# Initialize database if needed
if [ ! -f /data/sync.db ]; then
    echo "Initializing database..."
    python -c "from app.database import db; db.init_tables()" 2>/dev/null || true
fi

# Create default config if not exists
if [ ! -f /config/config.json ]; then
    echo "Creating default configuration..."
    cp /app/config/config.example.json /config/config.json 2>/dev/null || \
    python -c "from app.config_manager import config_manager; config_manager.save_config()" 2>/dev/null || true
fi

# Start application
echo "Starting Flask application..."
exec python -m app.main
