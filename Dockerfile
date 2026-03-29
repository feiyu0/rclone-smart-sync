FROM python:3.11-slim

# Install rclone from official binary
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    ca-certificates \
    unzip \
    && wget -q https://downloads.rclone.org/rclone-current-linux-amd64.zip \
    && unzip rclone-current-linux-amd64.zip \
    && mv rclone-*-linux-amd64/rclone /usr/local/bin/ \
    && rm -rf rclone-current-linux-amd64.zip rclone-*-linux-amd64 \
    && apt-get remove -y wget unzip \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 -s /bin/bash appuser

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app/ ./app/

# Create necessary directories
RUN mkdir -p /data /config /logs && \
    chown -R appuser:appuser /app /data /config /logs

# Copy entrypoint script
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh && \
    chown appuser:appuser /docker-entrypoint.sh

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/api/status || exit 1

# Entrypoint
ENTRYPOINT ["/docker-entrypoint.sh"]

# Run application
CMD ["python", "-m", "app.main"]
