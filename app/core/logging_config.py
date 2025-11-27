# app/core/logging_config.py
"""
Centralized logging configuration for the application.

This module configures logging levels to reduce noise from verbose libraries
while keeping important application logs visible.
"""

import logging
import os


def configure_logging():
    """
    Configure logging for the application.

    Sets appropriate log levels for different modules:
    - App code: INFO (or DEBUG if LOG_LEVEL=DEBUG)
    - HTTP clients (httpx, urllib3, requests): WARNING only
    - Selenium: WARNING only
    - Database: WARNING only
    - Other noisy libraries: WARNING only
    """

    # Get log level from environment, default to INFO
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )

    # Quiet noisy HTTP client loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)

    # Quiet Selenium loggers
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("selenium.webdriver").setLevel(logging.WARNING)
    logging.getLogger("selenium.webdriver.remote").setLevel(logging.WARNING)
    logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)

    # Quiet database loggers
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("asyncpg").setLevel(logging.WARNING)

    # Quiet other noisy libraries
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("chardet").setLevel(logging.WARNING)
    logging.getLogger("charset_normalizer").setLevel(logging.WARNING)
    logging.getLogger("undetected_chromedriver").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)

    # Keep app loggers at configured level
    logging.getLogger("app").setLevel(getattr(logging, log_level, logging.INFO))
    logging.getLogger("__main__").setLevel(getattr(logging, log_level, logging.INFO))

    # Log that we've configured logging
    logger = logging.getLogger(__name__)
    logger.info(f"Logging configured at level: {log_level}")


# Auto-configure when module is imported
configure_logging()
