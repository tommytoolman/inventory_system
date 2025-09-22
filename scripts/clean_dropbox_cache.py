#!/usr/bin/env python3
"""
Clean up Dropbox cache files.

This script helps manage Dropbox cache size by:
1. Removing expired temporary links
2. Converting old cache format to new format
3. Optionally clearing all cache
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add the app directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings


def clean_temp_links_cache():
    """Clean up expired links from the cache"""
    cache_file = os.path.join(settings.cache_dir, 'dropbox', 'temp_links.json')

    if not os.path.exists(cache_file):
        print("No cache file found")
        return

    # Load cache
    with open(cache_file, 'r') as f:
        cache_data = json.load(f)

    original_size = len(cache_data)
    now = datetime.now()
    valid_entries = {}

    # Check each entry
    for path, value in cache_data.items():
        try:
            # Handle different formats
            if isinstance(value, list) and len(value) == 2:
                # Old format: [link, expiry]
                expiry = datetime.fromisoformat(value[1])
                if expiry > now:
                    # Convert to new format
                    valid_entries[path] = {
                        'full': value[0],
                        'thumbnail': value[0],
                        'expiry': value[1]
                    }
            elif isinstance(value, dict) and 'expiry' in value:
                # New format
                expiry = datetime.fromisoformat(value['expiry'])
                if expiry > now:
                    valid_entries[path] = value
        except Exception as e:
            print(f"Error processing {path}: {e}")

    # Calculate savings
    removed = original_size - len(valid_entries)

    if removed > 0:
        # Save cleaned cache
        with open(cache_file, 'w') as f:
            json.dump(valid_entries, f, indent=2)

        # Get file sizes
        old_size = os.path.getsize(cache_file) / 1024  # KB
        print(f"Cleaned cache: removed {removed} expired entries")
        print(f"Remaining entries: {len(valid_entries)}")
        print(f"Cache file size: {old_size:.1f} KB")
    else:
        print(f"No expired entries found. Total entries: {original_size}")


def clear_all_cache():
    """Clear all Dropbox cache files"""
    cache_dir = os.path.join(settings.cache_dir, 'dropbox')

    if not os.path.exists(cache_dir):
        print("No cache directory found")
        return

    files_removed = []
    for file in os.listdir(cache_dir):
        file_path = os.path.join(cache_dir, file)
        if os.path.isfile(file_path):
            size = os.path.getsize(file_path) / 1024  # KB
            os.remove(file_path)
            files_removed.append((file, size))

    if files_removed:
        print("Removed cache files:")
        total_size = 0
        for file, size in files_removed:
            print(f"  - {file}: {size:.1f} KB")
            total_size += size
        print(f"Total space freed: {total_size:.1f} KB")
    else:
        print("No cache files found")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Clean Dropbox cache")
    parser.add_argument('--clear-all', action='store_true',
                        help="Clear all cache files (default: clean expired only)")

    args = parser.parse_args()

    if args.clear_all:
        response = input("This will delete ALL Dropbox cache. Continue? (y/N): ")
        if response.lower() == 'y':
            clear_all_cache()
        else:
            print("Cancelled")
    else:
        clean_temp_links_cache()


if __name__ == "__main__":
    main()