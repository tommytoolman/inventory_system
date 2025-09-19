FROM python:3.12-slim

# Install basic system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for running Chrome
RUN useradd -m -u 1000 appuser

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=appuser:appuser . .

# Make scripts executable
RUN chmod +x /app/start.sh /app/start_app.py

# Create necessary directories with correct permissions
RUN mkdir -p /app/logs /app/cache /app/app/cache && \
    chown -R appuser:appuser /app

# Temporarily run as root for debugging
# USER appuser

# Set Python path
ENV PYTHONPATH=/app

# Railway expects port 8080
# Force rebuild with timestamp
ENV REBUILD_TIME="2025-09-19-09:40"
ENV PORT=8080
EXPOSE 8080

# Run on Railway's expected port
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]