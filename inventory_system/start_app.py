#!/usr/bin/env python
"""Start the FastAPI application with proper port configuration for Railway."""
import os
import sys
import uvicorn

if __name__ == "__main__":
    # Get port from environment, default to 8000
    port = int(os.environ.get("PORT", 8000))

    print(f"Starting application on port {port}")

    # Run the app
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        log_level="info"
    )