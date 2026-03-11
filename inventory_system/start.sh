#!/bin/sh
# Start script for Railway deployment

# Use PORT from environment or default to 8000
PORT=${PORT:-8000}

echo "Starting application on port $PORT"
echo "Python version: $(python --version)"
echo "Current directory: $(pwd)"
echo "Checking imports..."
python -c "import app.main; print('✓ Main app imported successfully')"

echo "Starting Uvicorn..."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT --log-level info