FROM python:3.11-slim

WORKDIR /app

# Install runtime tools for health checks and create an unprivileged user
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /usr/sbin/nologin appuser

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app/ ./app/

# Create data directory for persistent storage
RUN mkdir -p /data \
    && chown -R appuser:appuser /app /data

# Set environment variables
ENV DATA_DIR=/data
ENV PYTHONUNBUFFERED=1

USER appuser

# Expose port
EXPOSE 8000

# Volume for persistent data (bookmarks database and encryption key)
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl --fail http://127.0.0.1:8000/api/status || exit 1

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
