# app/services/dropbox/dropbox_async_service.py
"""
Merged AsyncDropboxClient Module

This module provides asynchronous access to the Dropbox API with comprehensive
features including token refresh, folder scanning, temporary links, and change tracking.

Core Features:
- Async implementation for optimal performance
- Automatic token refresh when tokens expire
- Full folder scanning with recursive support
- Temporary link generation for images with caching
- Folder structure mapping
- Change tracking via polling and webhooks
- Comprehensive error handling and logging
"""

import os
import sys
import asyncio
import aiohttp
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Union

logger = logging.getLogger(__name__)

class AsyncDropboxClient:
    """
    Fully asynchronous Dropbox client with comprehensive feature set.
    
    Features:
    - Token refresh support
    - Asynchronous API access
    - Folder structure mapping
    - Temporary link generation
    - Change tracking
    - Webhook support
    """
    
    # API Endpoints
    BASE_URL = "https://api.dropboxapi.com/2"
    TOKEN_URL = "https://api.dropbox.com/oauth2/token"
    
    # File types
    IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.tiff', '.bmp', '.heic']
    
    def __init__(
        self, 
        access_token: Optional[str] = None, 
        refresh_token: Optional[str] = None, 
        app_key: Optional[str] = None, 
        app_secret: Optional[str] = None
    ):
        """
        Initialize the Dropbox client.
        
        Args:
            access_token: Dropbox access token (can be None if using refresh_token)
            refresh_token: Dropbox refresh token for getting new access tokens
            app_key: Dropbox app key (required for token refresh)
            app_secret: Dropbox app secret (required for token refresh)
        """
        # Load from parameters or environment variables
        self.access_token = access_token or os.environ.get("DROPBOX_ACCESS_TOKEN")
        self.refresh_token = refresh_token or os.environ.get("DROPBOX_REFRESH_TOKEN")
        self.app_key = app_key or os.environ.get("DROPBOX_APP_KEY")
        self.app_secret = app_secret or os.environ.get("DROPBOX_APP_SECRET")

        # Setup cache directory first
        self.cache_dir = os.path.join("app", "cache", "dropbox")
        os.makedirs(self.cache_dir, exist_ok=True)

        # DO NOT load tokens from files - security risk!
        # Tokens should only come from environment variables
        
        # Set up headers if we have an access token
        if self.access_token:
            self.headers = self._get_headers()
        else:
            self.headers = {}

        
         # Cache file paths
        self.temp_links_cache_file = os.path.join(self.cache_dir, "temp_links.json")
        self.folder_structure_cache_file = os.path.join(self.cache_dir, "folder_structure.json")

        # Initialize caches
        self.file_links_cache = {}  # Cache for temporary links: path -> (link, expiry)
        self.folder_structure = {}  # Cached folder structure
        self.cursor_cache = {}      # Cache for listing cursors by path
        
        # Load cached data on initialization
        self.load_caches()
        
    def _get_headers(self) -> Dict[str, str]:
        """Get headers with current access token"""
        return {
            'Authorization': f'Bearer {self.access_token}'
            # Note: We don't set 'Content-Type': 'application/json' here
            # because it will be set per request as needed
        }
    
    def load_caches(self):
        """Load cached data from disk"""
        # Load temp links cache
        if os.path.exists(self.temp_links_cache_file):
            try:
                with open(self.temp_links_cache_file, 'r') as f:
                    cached_data = json.load(f)
                    # Handle both old and new formats
                    for path, value in cached_data.items():
                        if isinstance(value, list) and len(value) == 2:
                            # Old format: [link, expiry]
                            self.file_links_cache[path] = (value[0], datetime.fromisoformat(value[1]))
                        elif isinstance(value, dict) and 'expiry' in value:
                            # New format: dict with full/thumbnail/expiry
                            # Store in cache as tuple for backward compatibility
                            expiry = datetime.fromisoformat(value['expiry'])
                            # Use full URL for the main cache
                            self.file_links_cache[path] = (value.get('full', ''), expiry)
                logger.info(f"Loaded {len(self.file_links_cache)} cached temp links")
            except Exception as e:
                logger.error(f"Error loading temp links cache: {e}")
        
        # Load folder structure cache
        if os.path.exists(self.folder_structure_cache_file):
            try:
                cached_structure = self.load_folder_structure_from_cache()
                if cached_structure:
                    self.folder_structure = cached_structure
                    logger.info(f"Loaded cached folder structure")
                else:
                    logger.info(f"Folder structure cache expired or invalid")
            except Exception as e:
                logger.error(f"Error loading folder structure cache: {e}")
    
    def load_temp_links_cache(self) -> Dict[str, Any]:
        """Load temporary links cache from disk, handling both old and new formats"""
        if os.path.exists(self.temp_links_cache_file):
            try:
                with open(self.temp_links_cache_file, 'r') as f:
                    raw_data = json.load(f)

                # Convert to consistent format
                cache_data = {}
                for path, value in raw_data.items():
                    if isinstance(value, list) and len(value) == 2:
                        # Old format: [link, expiry]
                        cache_data[path] = {
                            'full': value[0],
                            'thumbnail': value[0],  # Use same URL for old format
                            'expiry': value[1]
                        }
                    elif isinstance(value, dict):
                        # New format: already a dict
                        cache_data[path] = value
                    else:
                        # Unknown format, skip
                        logger.warning(f"Unknown cache format for {path}: {type(value)}")

                return cache_data
            except Exception as e:
                logger.error(f"Error loading temp links cache: {e}")
        return {}
    
    def save_temp_links_cache(self, temp_links: Dict[str, Any]):
        """Save temporary links cache to disk with both thumbnail and full-res URLs"""
        try:
            # Convert to storable format with expiry times
            cache_data = {}
            expiry = datetime.now() + timedelta(hours=3)  # Links are valid for ~4 hours, cache for 3

            for path, link_data in temp_links.items():
                if isinstance(link_data, str):
                    # Legacy format - just a URL string
                    cache_data[path] = {
                        'full': link_data,
                        'thumbnail': link_data,  # Use same URL for now
                        'expiry': expiry.isoformat()
                    }
                else:
                    # New format with thumbnail and full URLs
                    cache_data[path] = {
                        'full': link_data.get('full'),
                        'thumbnail': link_data.get('thumbnail'),
                        'expiry': expiry.isoformat()
                    }

            with open(self.temp_links_cache_file, 'w') as f:
                json.dump(cache_data, f)
            logger.info(f"Saved {len(cache_data)} temp links to cache")
        except Exception as e:
            logger.error(f"Error saving temp links cache: {e}")

    async def refresh_access_token(self) -> bool:
        """
        Refresh the access token using the refresh token.
        
        Returns:
            bool: True if token refresh was successful, False otherwise
        """
        if not self.refresh_token or not self.app_key or not self.app_secret:
            logger.error("Refresh token, app key and app secret are required for token refresh")
            return False

        try:
            logger.info("Refreshing Dropbox access token...")
            async with aiohttp.ClientSession() as session:
                data = {
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                    "client_id": self.app_key,
                    "client_secret": self.app_secret
                }
                
                async with session.post(self.TOKEN_URL, data=data) as response:
                    if response.status != 200:
                        response_text = await response.text()
                        logger.error(f"Token refresh failed: {response.status} - {response_text}")
                        return False
                    
                    token_data = await response.json()
                    self.access_token = token_data.get("access_token")
                    
                    if self.access_token:
                        # Update headers with new token
                        self.headers = self._get_headers()
                        logger.info("Successfully refreshed access token")

                        # Store this token for future use
                        os.environ["DROPBOX_ACCESS_TOKEN"] = self.access_token

                        # DO NOT save tokens to files - security risk!
                        # Tokens should only be in environment variables or encrypted storage

                        return True
                    else:
                        logger.error("Token refresh response did not include access_token")
                        return False

        except Exception as e:
            logger.error(f"Error refreshing token: {str(e)}")
            return False
            
    async def execute_with_token_refresh(self, func, *args, **kwargs):
        """
        Execute a function with token refresh if needed.
        
        This wrapper will:
        1. Try to execute the function
        2. If a 401 Unauthorized error occurs, refresh the token
        3. Try again with the new token
        
        Args:
            func: Async function to execute
            *args, **kwargs: Arguments to pass to the function
            
        Returns:
            The result of the function call
            
        Raises:
            Various exceptions that might be raised by the function
        """
        try:
            # Try the operation with current token
            return await func(*args, **kwargs)
        except aiohttp.ClientResponseError as e:
            # Check if it's an auth error (401)
            if e.status == 401:
                logger.info("Got 401 unauthorized, attempting token refresh")
                # Try to refresh the token
                if await self.refresh_access_token():
                    # Retry the operation with new token
                    return await func(*args, **kwargs)
                else:
                    raise ValueError("Failed to refresh access token")
            else:
                # Re-raise other errors
                raise

    def save_temp_links_to_cache(self, temp_links):
        """Save temporary links to cache file"""
        try:
            # Store links with timestamp for expiration checking
            cache_data = {
                "timestamp": datetime.now().isoformat(),
                "links": temp_links
            }
            
            with open(self.temp_links_cache_file, 'w') as f:
                json.dump(cache_data, f)
                
            print(f"Saved {len(temp_links)} temporary links to cache")
            return True
        except Exception as e:
            print(f"Error saving temp links to cache: {str(e)}")
            return False

    def load_temp_links_from_cache(self):
        """Load temporary links from cache with new format support"""
        try:
            if not os.path.exists(self.temp_links_cache_file):
                return {}

            with open(self.temp_links_cache_file, 'r') as f:
                cache_data = json.load(f)

            # Handle different cache formats
            if 'timestamp' in cache_data and 'links' in cache_data:
                # Old format with timestamp
                timestamp = datetime.fromisoformat(cache_data["timestamp"])
                if datetime.now() - timestamp > timedelta(hours=3.5):
                    print("Cache expired, links need refresh")
                    return {}
                print(f"Loaded {len(cache_data['links'])} temporary links from cache")
                return cache_data["links"]
            else:
                # New format - cache_data is the direct mapping
                valid_links = {}
                now = datetime.now()
                for path, entry in cache_data.items():
                    if isinstance(entry, dict) and 'expiry' in entry:
                        expiry = datetime.fromisoformat(entry['expiry'])
                        if expiry > now:
                            valid_links[path] = entry
                print(f"Loaded {len(valid_links)} valid temporary links from cache")
                return valid_links
        except Exception as e:
            print(f"Error loading temp links from cache: {str(e)}")
            return {}

    def save_folder_structure_to_cache(self, folder_structure):
        """Save folder structure to cache file"""
        try:
            # Store structure with timestamp
            cache_data = {
                "timestamp": datetime.now().isoformat(),
                "structure": folder_structure
            }
            
            with open(self.folder_structure_cache_file, 'w') as f:
                json.dump(cache_data, f)
                
            print(f"Saved folder structure to cache")
            return True
        except Exception as e:
            print(f"Error saving folder structure to cache: {str(e)}")
            return False

    def load_folder_structure_from_cache(self):
        """Load folder structure from cache if not expired"""
        try:
            if not os.path.exists(self.folder_structure_cache_file):
                return None
                
            with open(self.folder_structure_cache_file, 'r') as f:
                cache_data = json.load(f)
                
            # Check if cache is expired (consider folder structure valid for 1 day)
            timestamp = datetime.fromisoformat(cache_data["timestamp"])
            if datetime.now() - timestamp > timedelta(days=1):
                print("Folder structure cache expired")
                return None
                
            print(f"Loaded folder structure from cache")
            return cache_data["structure"]
        except Exception as e:
            print(f"Error loading folder structure from cache: {str(e)}")
            return None
                
    async def test_connection(self) -> bool:
        """
        Test the connection to Dropbox API with auto-refresh if needed.
        
        Returns:
            bool: True if connection works, False otherwise
        """
        async def _test_connection():
            """Internal function to test connection"""
            logger.info("Testing Dropbox API connection...")
            async with aiohttp.ClientSession() as session:
                # Get current account info (lightweight call)
                endpoint = f"{self.BASE_URL}/users/get_current_account"
                
                headers = self.headers.copy()
                headers['Content-Type'] = 'application/json'
                
                try:
                    # Use raw data approach
                    async with session.post(
                        endpoint, 
                        headers=headers,
                        data='null'  # Simply send 'null' as raw data
                    ) as response:
                        if response.status != 200:
                            text = await response.text()
                            logger.error(f"Connection test failed with status {response.status}: {text}")
                            # If this is an auth error, raise specifically so we can refresh
                            if response.status == 401:
                                raise aiohttp.ClientResponseError(
                                    request_info=response.request_info,
                                    history=response.history,
                                    status=response.status,
                                    message="Unauthorized",
                                    headers=response.headers
                                )
                            return False
                            
                        account_info = await response.json()
                        logger.info(f"Connected to Dropbox account: {account_info.get('email', 'unknown')}")
                        return True
                except Exception as e:
                    logger.error(f"Error in test connection request: {str(e)}")
                    return False
    
        try:
            return await self.execute_with_token_refresh(_test_connection)
        except Exception as e:
            logger.error(f"Connection test exception: {str(e)}")
            return False
    
    async def scan_and_map_folder(self, path: str = "") -> Dict[str, Any]:
        """
        Comprehensive scan and mapping of a Dropbox folder with optimized performance.
        
        This method:
        1. Lists all folder entries recursively
        2. Builds a structured representation of the folder hierarchy
        3. Gets temporary links for image files
        4. Efficiently uses concurrency for optimal performance
        
        Args:
            path: Starting path to scan (empty for root)
            
        Returns:
            Dict with keys:
            - folder_structure: Hierarchical folder structure
            - all_entries: Flat list of all entries
            - temp_links: Dict mapping file paths to temporary links
        """
        logger.info(f"Starting async Dropbox scan of '{path}'...")
        start_time = datetime.now()
        
        try:
            # Step 1: Get all entries recursively
            all_entries = await self.list_folder_recursive(path)
            step1_time = datetime.now()
            scan_time = (step1_time - start_time).total_seconds()
            logger.info(f"Step 1: Folder listing completed in {scan_time:.2f} seconds")
            
            # Step 2: Build folder structure
            folder_structure = self.build_folder_structure(all_entries)
            step2_time = datetime.now()
            structure_time = (step2_time - step1_time).total_seconds()
            logger.info(f"Step 2: Structure building completed in {structure_time:.2f} seconds")
            
            # Step 3: Get image file paths from the structure
            image_paths = []
            for entry in all_entries:
                if entry.get('.tag') == 'file':
                    file_path = entry.get('path_lower', '')
                    if self._is_image_file(file_path):
                        image_paths.append(file_path)
            
            step3_time = datetime.now()
            path_time = (step3_time - step2_time).total_seconds()
            logger.info(f"Step 3: Found {len(image_paths)} image files in {path_time:.2f} seconds")
            
            # Step 4: Get temporary links for images in parallel batches
            # Load cached links first
            cached_links = self.load_temp_links_cache()
            valid_cached_links = {}
            paths_needing_links = []
            
            # Check which links are still valid
            now = datetime.now()
            for path in image_paths:
                if path in cached_links:
                    cache_entry = cached_links[path]
                    # Cache loader now always returns dict format
                    if isinstance(cache_entry, dict) and 'expiry' in cache_entry:
                        expiry = datetime.fromisoformat(cache_entry['expiry'])
                        if expiry > now:
                            valid_cached_links[path] = {
                                'thumbnail': cache_entry.get('thumbnail'),
                                'full': cache_entry.get('full')
                            }
                        else:
                            paths_needing_links.append(path)
                    else:
                        paths_needing_links.append(path)
                else:
                    paths_needing_links.append(path)
            
            logger.info(f"Found {len(valid_cached_links)} valid cached links, need to fetch {len(paths_needing_links)} new links")
            
            # Initialize processing_paths for stats
            processing_paths = []
            
            # Only fetch links we don't have cached
            if paths_needing_links:
                # Limit to reasonable number for initial load
                if len(paths_needing_links) > 1000:
                    logger.info(f"Limiting initial fetch to 1000 of {len(paths_needing_links)} images")
                    processing_paths = paths_needing_links[:1000]
                else:
                    processing_paths = paths_needing_links
                    
                # Get both thumbnail and full resolution links
                new_links = {}
                async with aiohttp.ClientSession() as session:
                    # Create tasks for all paths
                    tasks = []
                    for path in processing_paths:
                        task = self.get_image_links_with_thumbnails(session, path)
                        tasks.append(task)

                    # Process in batches to avoid overwhelming the API
                    batch_size = 50
                    for i in range(0, len(tasks), batch_size):
                        batch = tasks[i:i + batch_size]
                        results = await asyncio.gather(*batch)
                        for path, links in results:
                            if links['full']:  # Only add if we got a valid link
                                new_links[path] = links

                temp_links = {**valid_cached_links, **new_links}
                
                # Save to cache
                self.save_temp_links_cache(temp_links)
            else:
                temp_links = valid_cached_links
            
            step4_time = datetime.now()
            link_time = (step4_time - step3_time).total_seconds()
            logger.info(f"Step 4: Have {len(temp_links)} temp links ready in {link_time:.2f} seconds")
            
            # Build the final map
            dropbox_map = {
                'folder_structure': folder_structure,
                'all_entries': all_entries,
                'temp_links': temp_links,
                'scan_stats': {
                    'total_time_seconds': (datetime.now() - start_time).total_seconds(),
                    'entry_count': len(all_entries),
                    'image_count': len(image_paths),
                    'processed_images': len(processing_paths),
                    'temp_links_count': len(temp_links)
                }
            }
            
            # Cache the folder structure
            self.folder_structure = folder_structure
            # Save to disk for persistence
            self.save_folder_structure_to_cache(folder_structure)

            total_time = (datetime.now() - start_time).total_seconds()
            logger.info(f"Total scan time: {total_time:.2f} seconds")
            return dropbox_map
            
        except Exception as e:
            logger.error(f"Error in scan_and_map_folder: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            raise
    
    async def list_folder_recursive(self, path: str = "", max_depth: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        List all contents of a folder recursively with token refresh support.
        
        Args:
            path: Starting path to scan
            max_depth: Maximum folder depth to scan (None for unlimited)
            
        Returns:
            List of entry dictionaries with file and folder information
        """
        async def _list_folder_recursive():
            """Internal implementation of folder listing"""
            logger.info(f"Starting folder scan for '{path}'...")
            
            all_entries = []
            async with aiohttp.ClientSession() as session:
                # Initial request
                endpoint = f"{self.BASE_URL}/files/list_folder"
                data = {
                    "path": path or "",
                    "recursive": True,  # Recursive listing for efficiency
                    "include_media_info": True,
                    "include_deleted": False,
                    "include_has_explicit_shared_members": False,
                    "limit": 2000  # Request larger batches for efficiency
                }
                
                # If using recursive=True in the API call, there's no easy way to limit depth
                # For debugging, check if max_depth is set to 1 and use a non-recursive call
                if max_depth == 1:
                    # Non-recursive call for just top-level
                    data["recursive"] = False
                
                async with session.post(endpoint, headers=self.headers, json=data) as response:
                    if response.status != 200:
                        text = await response.text()
                        logger.error(f"Error listing folder: {response.status}")
                        logger.error(f"Response: {text}")
                        # If this is an auth error, raise ClientResponseError
                        if response.status == 401:
                            raise aiohttp.ClientResponseError(
                                request_info=response.request_info,
                                history=response.history,
                                status=response.status,
                                message="Unauthorized",
                                headers=response.headers
                            )
                        return []
                    
                    result = await response.json()
                    entries = result.get('entries', [])
                    all_entries.extend(entries)
                    
                    # Save cursor for future use
                    if 'cursor' in result:
                        self.cursor_cache[path] = result['cursor']
                    
                    # Handle pagination
                    has_more = result.get('has_more', False)
                    cursor = result.get('cursor')
                    
                    # Use the continue endpoint to get all entries
                    while has_more and cursor:
                        logger.info(f"Getting more entries... ({len(all_entries)} so far)")
                        more_result = await self._list_folder_continue(session, cursor)
                        
                        if not more_result:
                            break
                            
                        more_entries = more_result.get('entries', [])
                        all_entries.extend(more_entries)
                        has_more = more_result.get('has_more', False)
                        cursor = more_result.get('cursor')
                
                logger.info(f"Found {len(all_entries)} total entries")
                return all_entries
                
        try:
            return await self.execute_with_token_refresh(_list_folder_recursive)
        except Exception as e:
            logger.error(f"Error in list_folder_recursive: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return []
            
    async def _list_folder_continue(self, session, cursor):
        """
        Continue listing a folder with a pagination cursor.
        
        Args:
            session: aiohttp ClientSession to use
            cursor: Pagination cursor from previous request
            
        Returns:
            Dict with more entries or None if error
        """
        endpoint = f"{self.BASE_URL}/files/list_folder/continue"
        
        data = {
            "cursor": cursor
        }
        
        try:
            async with session.post(endpoint, headers=self.headers, json=data) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    text = await response.text()
                    logger.error(f"Error continuing folder listing: {response.status}")
                    logger.error(f"Response: {text}")
                    
                    # If this is an auth error, raise so we can refresh the token
                    if response.status == 401:
                        raise aiohttp.ClientResponseError(
                            request_info=response.request_info,
                            history=response.history,
                            status=response.status,
                            message="Unauthorized",
                            headers=response.headers
                        )
                    return None
        except Exception as e:
            logger.error(f"Exception in _list_folder_continue: {str(e)}")
            # Re-raise auth errors so they can be handled by the refresh mechanism
            if isinstance(e, aiohttp.ClientResponseError) and e.status == 401:
                raise
            return None
    
    def build_folder_structure(self, entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Build hierarchical folder structure from entries.
        
        Args:
            entries: Flat list of entries from list_folder_recursive
            
        Returns:
            Dict representing the folder structure
        """
        logger.info("Building folder structure...")
        start_time = datetime.now()
        
        # Initialize folder structure
        folder_structure = {}
        
        # First pass: create all folders
        for entry in entries:
            path = entry.get('path_lower', '')
            entry_type = entry.get('.tag', '')
            
            # Skip if not a folder
            if entry_type != 'folder':
                continue
            
            # Create folder entry
            parent_path = os.path.dirname(path)
            folder_name = os.path.basename(path)
            
            # Create the folder path structure
            self._ensure_path_exists(folder_structure, path)
            
            # Initialize the folder content
            current = self._get_folder_at_path(folder_structure, path)
            current['name'] = folder_name
            current['path'] = path
            current['type'] = 'folder'
            current['files'] = []
            current['folders'] = []
        
        # Second pass: add all files
        for entry in entries:
            path = entry.get('path_lower', '')
            entry_type = entry.get('.tag', '')
            
            # Skip if not a file
            if entry_type != 'file':
                continue
                
            parent_path = os.path.dirname(path)
            file_name = os.path.basename(path)
            
            # Create the parent path structure if it doesn't exist
            self._ensure_path_exists(folder_structure, parent_path)
            
            # Get the parent folder
            parent = self._get_folder_at_path(folder_structure, parent_path)
            
            # Create file entry
            file_entry = {
                'name': file_name,
                'path': path,
                'type': 'file',
                'size': entry.get('size', 0),
                'size_formatted': self._format_file_size(entry.get('size', 0)),
                'media_info': entry.get('media_info', {})
            }
            
            # Add file to parent folder
            if 'files' not in parent:
                parent['files'] = []
                
            parent['files'].append(file_entry)
        
        # Third pass: establish parent-child relationships
        for entry in entries:
            path = entry.get('path_lower', '')
            entry_type = entry.get('.tag', '')
            
            # Skip if not a folder
            if entry_type != 'folder':
                continue
                
            parent_path = os.path.dirname(path)
            
            # Skip root level folders
            if not parent_path or parent_path == '/':
                continue
                
            # Get the parent and current folders
            parent = self._get_folder_at_path(folder_structure, parent_path)
            current = self._get_folder_at_path(folder_structure, path)
            
            # Add current folder to parent's folders list
            if 'folders' not in parent:
                parent['folders'] = []
                
            # Add a reference to the current folder
            parent['folders'].append(path)
        
        logger.info(f"Built folder structure in {(datetime.now() - start_time).total_seconds():.2f} seconds")
        return folder_structure
    
    def _ensure_path_exists(self, structure: Dict[str, Any], path: str) -> Dict[str, Any]:
        """
        Ensure a folder path exists in the structure dictionary.
        
        Args:
            structure: Current folder structure to modify
            path: Path to ensure exists
            
        Returns:
            The folder at the given path
        """
        if not path or path == '/':
            return structure
        
        parts = path.strip('/').split('/')
        current = structure
        
        current_path = ""
        for part in parts:
            current_path = f"{current_path}/{part}".replace('//', '/')
            
            if current_path not in current:
                current[current_path] = {}
                
            current = current[current_path]
            
        return current
    
    def _get_folder_at_path(self, structure: Dict[str, Any], path: str) -> Dict[str, Any]:
        """
        Get the folder object at a specific path.
        
        Args:
            structure: Folder structure to search
            path: Path to get folder for
            
        Returns:
            Dict representing the folder
        """
        if not path or path == '/':
            return structure
            
        return structure.get(path, {})
    
    def _format_file_size(self, size_bytes: int) -> str:
        """
        Format file size in a human-readable form.
        
        Args:
            size_bytes: Size in bytes
            
        Returns:
            Formatted size string (e.g., "4.2 MB")
        """
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
    
    def _is_image_file(self, path: str) -> bool:
        """
        Check if a file path is an image based on extension.
        
        Args:
            path: File path to check
            
        Returns:
            bool: True if it's an image file
        """
        ext = os.path.splitext(path.lower())[1]
        return ext in self.IMAGE_EXTENSIONS
    
    async def get_image_links_with_thumbnails(self, session, file_path: str) -> Tuple[str, Dict[str, Optional[str]]]:
        """
        Get both thumbnail and full-res temporary links for an image.

        Args:
            session: aiohttp ClientSession to use
            file_path: Path to the image file

        Returns:
            Tuple of (file_path, {'thumbnail': url, 'full': url})
        """
        try:
            # Get the full resolution temporary link
            _, full_link = await self.get_temporary_link(session, file_path)
            if not full_link:
                return file_path, {'thumbnail': None, 'full': None}

            # For thumbnail, append size parameter to the temporary link
            # Dropbox supports these size params: w32h32, w64h64, w128h128, w256h256, w480h320, w640h480, w960h640, w1024h768
            thumbnail_link = full_link
            if '?' in full_link:
                thumbnail_link = f"{full_link}&size=w256h256"
            else:
                thumbnail_link = f"{full_link}?size=w256h256"

            return file_path, {
                'thumbnail': thumbnail_link,
                'full': full_link
            }
        except Exception as e:
            logger.error(f"Error getting image links for {file_path}: {str(e)}")
            return file_path, {'thumbnail': None, 'full': None}

    async def get_temporary_link(self, session, file_path: str) -> Tuple[str, Optional[str]]:
        """
        Get a temporary link for a single file with caching.

        Args:
            session: aiohttp ClientSession to use
            file_path: Path to the file

        Returns:
            Tuple of (file_path, temporary_link_url or None)
        """
        # Check cache first
        now = datetime.now()
        if file_path in self.file_links_cache:
            cached_link, expiry = self.file_links_cache[file_path]
            if now < expiry:
                return file_path, cached_link

        async def _get_link():
            """Internal implementation of get_temporary_link"""
            try:
                endpoint = f"{self.BASE_URL}/files/get_temporary_link"
                data = {"path": file_path}

                async with session.post(endpoint, headers=self.headers, json=data) as response:
                    if response.status == 200:
                        result = await response.json()
                        link = result.get('link')

                        # Cache the link with 4-hour expiration
                        expiry = now + timedelta(hours=4)
                        self.file_links_cache[file_path] = (link, expiry)
                        
                        return file_path, link
                    else:
                        text = await response.text()
                        # Don't log rate limit errors at ERROR level
                        if response.status == 429:
                            logger.debug(f"Rate limit hit for {file_path}")
                        else:
                            logger.error(f"Error getting link for {file_path}: {text}")

                        # Raise ClientResponseError for auth errors and rate limits
                        if response.status in [401, 429]:
                            raise aiohttp.ClientResponseError(
                                request_info=response.request_info,
                                history=response.history,
                                status=response.status,
                                message=text,
                                headers=response.headers
                            )
                        return file_path, None
            except Exception as e:
                logger.error(f"Exception getting link for {file_path}: {str(e)}")
                # Re-raise auth errors, return None for other errors
                if isinstance(e, aiohttp.ClientResponseError) and e.status == 401:
                    raise
                return file_path, None
        
        try:
            return await self.execute_with_token_refresh(_get_link)
        except Exception as e:
            logger.error(f"Final error getting link for {file_path}: {str(e)}")
            return file_path, None
    
    async def get_temporary_links_async(self, file_paths: List[str], batch_size: int = 50, max_retries=3) -> Dict[str, str]:
        """
        Get temporary links for multiple files with PARALLEL processing.
        
        Args:
            file_paths: List of file paths to get links for
            batch_size: Number of files to process in parallel in each batch (increased to 50)
            max_retries: Number of retry attempts for rate-limited requests
            
        Returns:
            Dict mapping file paths to temporary links
        """
        results = {}
        logger.info(f"Getting temporary links for {len(file_paths)} files in parallel batches of {batch_size}...")
        
        async def get_link_with_retry(session, path, max_retries=3):
            """Helper function to get a single link with retry logic"""
            for retry in range(max_retries + 1):
                try:
                    file_path, link = await self.get_temporary_link(session, path)
                    return (file_path, link)
                except aiohttp.ClientResponseError as e:
                    if e.status == 429 and retry < max_retries:  # Rate limit
                        delay = 2 ** retry + 1  # Exponential backoff
                        logger.debug(f"Rate limit for {path}, retry {retry+1}/{max_retries} in {delay}s")
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"Error getting link for {path}: {e.status}")
                        return (path, None)
                except Exception as e:
                    logger.error(f"Exception getting link for {path}: {str(e)}")
                    return (path, None)
            return (path, None)
        
        # Process in batches to avoid overwhelming the API
        async with aiohttp.ClientSession() as session:
            for i in range(0, len(file_paths), batch_size):
                batch = file_paths[i:i+batch_size]
                batch_num = i//batch_size + 1
                total_batches = (len(file_paths) + batch_size - 1)//batch_size
                
                logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} files)")
                
                # Process all files in the batch IN PARALLEL
                batch_tasks = [get_link_with_retry(session, path, max_retries) for path in batch]
                batch_results = await asyncio.gather(*batch_tasks)
                
                # Collect results
                for file_path, link in batch_results:
                    if link:
                        results[file_path] = link
                
                # Small delay between batches to be nice to the API
                if i + batch_size < len(file_paths):
                    await asyncio.sleep(0.5)  # Reduced to 0.5s since we're being more efficient

        logger.info(f"Successfully obtained {len(results)} temporary links")
        return results

    async def get_temp_links_for_folder(self, folder_path: str) -> Dict[str, str]:
        """
        Generate temporary links specifically for a given folder.
        
        Args:
            folder_path: The folder path to generate links for
            
        Returns:
            Dict mapping file paths to temporary links
        """
        logger.info(f"Generating temporary links for folder: {folder_path}")
        
        # List all entries in this folder recursively, but with limited depth 
        entries = await self.list_folder_recursive(path=folder_path, max_depth=5)
        
        # Find image files in this folder
        image_paths = []
        for entry in entries:
            if entry.get('.tag') == 'file' and self._is_image_file(entry.get('path_lower', '')):
                image_paths.append(entry.get('path_lower', ''))
        
        logger.info(f"Found {len(image_paths)} images in folder {folder_path}")
        
        # If no images found, return empty dict
        if not image_paths:
            return {}
        
        # Generate temporary links for these images
        temp_links = await self.get_temporary_links_async(image_paths, batch_size=20, max_retries=3)
        logger.info(f"Generated {len(temp_links)} temporary links for folder {folder_path}")
        
        return temp_links

    async def setup_webhook(self, webhook_url: str) -> Optional[str]:
        """
        Set up a webhook for file changes in the Dropbox account.
        
        Args:
            webhook_url: URL where Dropbox should send webhooks
            
        Returns:
            webhook_id if successful, None otherwise
        """
        async def _setup_webhook():
            """Internal implementation of webhook setup"""
            logger.info(f"Setting up webhook for URL: {webhook_url}")
            
            async with aiohttp.ClientSession() as session:
                # First, get a cursor for the account
                cursor_response = await session.post(
                    f"{self.BASE_URL}/files/list_folder/get_latest_cursor",
                    headers=self.headers,
                    json={"path": "", "recursive": True}
                )
                
                if cursor_response.status != 200:
                    text = await cursor_response.text()
                    logger.error(f"Error getting cursor: {cursor_response.status}")
                    logger.error(f"Response: {text}")
                    # Raise ClientResponseError for auth errors
                    if cursor_response.status == 401:
                        raise aiohttp.ClientResponseError(
                            request_info=cursor_response.request_info,
                            history=cursor_response.history,
                            status=cursor_response.status,
                            message="Unauthorized",
                            headers=cursor_response.headers
                        )
                    return None
                    
                cursor_data = await cursor_response.json()
                cursor = cursor_data.get('cursor')
                
                # Register the webhook
                webhook_endpoint = f"{self.BASE_URL}/2/files/list_folder/webhooks/add"
                webhook_data = {
                    "cursor": cursor,
                    "webhook_url": webhook_url
                }
                
                webhook_headers = self.headers.copy()
                
                webhook_response = await session.post(
                    webhook_endpoint,
                    headers=webhook_headers,
                    json=webhook_data
                )
                
                if webhook_response.status == 200:
                    webhook_result = await webhook_response.json()
                    webhook_id = webhook_result.get('webhook_id')
                    logger.info(f"Successfully set up webhook with ID: {webhook_id}")
                    return webhook_id
                else:
                    text = await webhook_response.text()
                    logger.error(f"Error setting up webhook: {webhook_response.status}")
                    logger.error(f"Response: {text}")
                    return None
        
        try:
            return await self.execute_with_token_refresh(_setup_webhook)
        except Exception as e:
            logger.error(f"Error in setup_webhook: {str(e)}")
            return None
            
    async def poll_for_changes(self, check_interval: int = 60, callback = None):
        """
        Poll for changes in the Dropbox account using cursor-based tracking.
        
        Args:
            check_interval: Seconds between checks
            callback: Optional callback function to call when changes are detected
                      Function signature: async def callback(entries: List[Dict])
                      
        This is a long-running function that will keep polling until interrupted.
        """
        logger.info(f"Starting polling for changes (checking every {check_interval} seconds)...")
        
        async def _get_latest_cursor():
            """Get the latest cursor as a starting point"""
            async with aiohttp.ClientSession() as session:
                response = await session.post(
                    f"{self.BASE_URL}/files/list_folder/get_latest_cursor",
                    headers=self.headers,
                    json={"path": "", "recursive": True}
                )
                
                if response.status != 200:
                    text = await response.text()
                    logger.error(f"Error getting cursor: {response.status}")
                    logger.error(f"Response: {text}")
                    # Raise for auth errors
                    if response.status == 401:
                        raise aiohttp.ClientResponseError(
                            request_info=response.request_info,
                            history=response.history,
                            status=response.status,
                            message="Unauthorized",
                            headers=response.headers
                        )
                    return None
                    
                result = await response.json()
                return result.get('cursor')
        
        # Get the initial cursor
        try:
            cursor = await self.execute_with_token_refresh(_get_latest_cursor)
            if not cursor:
                logger.error("Failed to get initial cursor")
                return
                
            logger.info(f"Initial cursor obtained: {cursor[:20]}...")
            
            # Main polling loop
            while True:
                try:
                    # Use longpoll to efficiently wait for changes
                    logger.info(f"Waiting for changes...")
                    async with aiohttp.ClientSession() as session:
                        longpoll_response = await session.post(
                            f"{self.BASE_URL}/files/list_folder/longpoll",
                            json={
                                "cursor": cursor,
                                "timeout": 30  # Seconds to wait (max 480)
                            }
                        )
                        
                        if longpoll_response.status != 200:
                            longpoll_text = await longpoll_response.text()
                            logger.error(f"Error in longpoll: {longpoll_response.status}")
                            logger.error(f"Response: {longpoll_text}")
                            await asyncio.sleep(check_interval)  # Wait before retry
                            continue
                            
                        changes = await longpoll_response.json()
                        
                        # If changes detected
                        if changes.get('changes', False):
                            logger.info("Changes detected! Getting details...")
                            
                            # Get the actual changes
                            async def _get_changes():
                                """Get detailed changes using the cursor"""
                                async with aiohttp.ClientSession() as changes_session:
                                    changes_response = await changes_session.post(
                                        f"{self.BASE_URL}/files/list_folder/continue",
                                        headers=self.headers,
                                        json={"cursor": cursor}
                                    )
                                    
                                    if changes_response.status != 200:
                                        error_text = await changes_response.text()
                                        logger.error(f"Error getting changes: {changes_response.status}")
                                        logger.error(f"Response: {error_text}")
                                        # Raise for auth errors
                                        if changes_response.status == 401:
                                            raise aiohttp.ClientResponseError(
                                                request_info=changes_response.request_info,
                                                history=changes_response.history,
                                                status=changes_response.status,
                                                message="Unauthorized",
                                                headers=changes_response.headers
                                            )
                                        return None, cursor
                                    
                                    result = await changes_response.json()
                                    return result.get('entries', []), result.get('cursor', cursor)
                            
                            try:
                                # Get changes with token refresh if needed
                                entries, new_cursor = await self.execute_with_token_refresh(_get_changes)
                                
                                if entries:
                                    # Update cursor for next iteration
                                    cursor = new_cursor
                                    
                                    logger.info(f"Found {len(entries)} changed items")
                                    
                                    # Process the changes
                                    for entry in entries:
                                        path = entry.get('path_lower', '')
                                        change_type = entry.get('.tag', '')
                                        
                                        if change_type == 'file':
                                            logger.info(f"File changed: {path}")
                                            # If it's an image, we might want to update temp links
                                            if self._is_image_file(path):
                                                logger.info(f"  Image file changed, will update temporary link")
                                                # Remove from cache so it will be refreshed next time
                                                if path in self.file_links_cache:
                                                    del self.file_links_cache[path]
                                                
                                        elif change_type == 'folder':
                                            logger.info(f"Folder changed: {path}")
                                            
                                        elif change_type == 'deleted':
                                            logger.info(f"Item deleted: {path}")
                                            # Remove from caches
                                            if path in self.file_links_cache:
                                                del self.file_links_cache[path]
                                    
                                    # Call the callback if provided
                                    if callback and callable(callback):
                                        try:
                                            await callback(entries)
                                        except Exception as callback_error:
                                            logger.error(f"Error in change callback: {str(callback_error)}")
                            
                            except Exception as change_error:
                                logger.error(f"Error processing changes: {str(change_error)}")
                        else:
                            logger.info("No changes detected in this interval.")
                        
                        # If backoff is suggested, respect it
                        if 'backoff' in changes:
                            backoff = changes['backoff']
                            logger.info(f"API requested backoff of {backoff} seconds")
                            await asyncio.sleep(backoff)
                        else:
                            # Otherwise use our default interval
                            await asyncio.sleep(check_interval)
                            
                except Exception as e:
                    logger.error(f"Error in polling loop: {str(e)}")
                    await asyncio.sleep(check_interval)  # Wait before retry
                    
        except KeyboardInterrupt:
            logger.info("Polling stopped by user.")
        except Exception as e:
            logger.error(f"Error in poll_for_changes: {str(e)}")
            
    async def track_changes_with_delta(self, path_prefix: str = "", callback = None):
        """
        Track changes using the Delta API.
        
        Args:
            path_prefix: Only track changes within this path
            callback: Optional callback function to call when changes are detected
                      Function signature: async def callback(entries: List[Dict], reset: bool)
                      
        This is a long-running function that will keep polling until interrupted.
        The delta API is more efficient than list_folder for tracking many changes.
        """
        logger.info(f"Starting change tracking for path prefix: {path_prefix}")
        
        # If we have a saved cursor, use it; otherwise start fresh
        cursor = None  # You'd typically load this from storage
        
        try:
            while True:
                async def _get_delta():
                    """Get delta changes"""
                    async with aiohttp.ClientSession() as session:
                        endpoint = f"{self.BASE_URL}/files/list_folder/continue" if cursor else f"{self.BASE_URL}/files/list_folder"
                        
                        data = {
                            "include_deleted": True,
                            "recursive": True
                        }
                        
                        if cursor:
                            data = {"cursor": cursor}
                        else:
                            data["path"] = path_prefix if path_prefix else ""
                        
                        async with session.post(endpoint, headers=self.headers, json=data) as response:
                            if response.status != 200:
                                text = await response.text()
                                logger.error(f"Error tracking changes: {response.status}")
                                logger.error(f"Response: {text}")
                                # Raise for auth errors
                                if response.status == 401:
                                    raise aiohttp.ClientResponseError(
                                        request_info=response.request_info,
                                        history=response.history,
                                        status=response.status,
                                        message="Unauthorized",
                                        headers=response.headers
                                    )
                                return None
                            
                            return await response.json()
                
                try:
                    # Get changes with token refresh if needed
                    result = await self.execute_with_token_refresh(_get_delta)
                    
                    if not result:
                        logger.error("Error getting delta changes")
                        await asyncio.sleep(60)  # Wait before retry
                        continue
                    
                    entries = result.get('entries', [])
                    cursor = result.get('cursor')
                    reset = result.get('reset', False)
                    
                    # Process changes
                    if entries:
                        logger.info(f"Processing {len(entries)} delta changes...")
                        
                        # Clear cache if reset flag is set
                        if reset:
                            logger.info("Reset flag set, clearing caches")
                            self.file_links_cache = {}
                            self.folder_structure = {}
                        
                        # Process each entry
                        for entry in entries:
                            path = entry.get('path_lower', '')
                            change_type = entry.get('.tag', '')
                            
                            # Update caches as needed
                            if path in self.file_links_cache:
                                del self.file_links_cache[path]
                        
                        # Call the callback if provided
                        if callback and callable(callback):
                            try:
                                await callback(entries, reset)
                            except Exception as callback_error:
                                logger.error(f"Error in delta callback: {str(callback_error)}")
                    
                    # Save cursor for resuming later
                    # self._save_cursor(cursor)
                    
                    # If no more changes, wait before checking again
                    if not result.get('has_more', False):
                        logger.info("No more delta changes. Waiting before next check...")
                        await asyncio.sleep(60)  # Adjust as needed
                    
                except Exception as e:
                    logger.error(f"Error in delta processing: {str(e)}")
                    await asyncio.sleep(60)  # Wait before retry
                    
        except KeyboardInterrupt:
            logger.info("Delta tracking stopped by user.")
        except Exception as e:
            logger.error(f"Error in track_changes_with_delta: {str(e)}")
            
    async def get_folder_contents(self, folder_path: str) -> Dict[str, Any]:
        """
        Get contents of a specific folder with images.
        
        Args:
            folder_path: Path to the folder
            
        Returns:
            Dict with folders and images in the folder
        """
        # Check if we have a cached folder structure
        if not self.folder_structure:
            # COMMENTED OUT AUTOMATIC SCAN - Return empty instead
            # # Perform a minimal scan to get the structure
            # logger.info("No cached folder structure, performing scan...")
            # dropbox_map = await self.scan_and_map_folder()
            # folder_structure = dropbox_map['folder_structure']

            # Return empty result instead of auto-scanning
            logger.info("No cached folder structure, returning empty result")
            return {
                'folders': [],
                'files': [],
                'images': [],
                'message': 'No cached data available. Please use sync button.'
            }
        else:
            folder_structure = self.folder_structure
            
        # Navigate to the requested path
        current_folder = self._get_folder_at_path(folder_structure, folder_path)
        
        if not current_folder:
            logger.error(f"Folder {folder_path} not found in structure")
            return {
                "folders": [],
                "images": [],
                "error": f"Folder {folder_path} not found"
            }
            
        # Find subfolders
        subfolders = []
        if 'folders' in current_folder:
            for subfolder_path in current_folder['folders']:
                subfolder = self._get_folder_at_path(folder_structure, subfolder_path)
                if subfolder and 'name' in subfolder:
                    subfolders.append({
                        'name': subfolder['name'],
                        'path': subfolder_path
                    })
        
        # Find image files
        images = []
        if 'files' in current_folder:
            for file in current_folder['files']:
                if self._is_image_file(file['path']):
                    # Check if we have a temporary link
                    temp_link = None
                    if hasattr(self, 'file_links_cache') and file['path'] in self.file_links_cache:
                        temp_link, _ = self.file_links_cache[file['path']]
                        
                    images.append({
                        'name': file['name'],
                        'path': file['path'],
                        'size': file.get('size', 0),
                        'size_formatted': file.get('size_formatted', ''),
                        'temp_link': temp_link
                    })
        
        # For images without temp links, try to get them in the background
        missing_links = [img['path'] for img in images if not img.get('temp_link')]
        if missing_links:
            logger.info(f"Getting temporary links for {len(missing_links)} images in folder")
            asyncio.create_task(self._refresh_temp_links(missing_links))
            
        return {
            "folders": sorted(subfolders, key=lambda x: x['name'].lower()),
            "images": sorted(images, key=lambda x: x['name'].lower()),
            "path": folder_path
        }
    
    async def _refresh_temp_links(self, file_paths: List[str]):
        """
        Refresh temporary links for files in the background.
        
        Args:
            file_paths: List of file paths to refresh links for
        """
        try:
            temp_links = await self.get_temporary_links_async(file_paths)
            logger.info(f"Refreshed {len(temp_links)} temporary links")
        except Exception as e:
            logger.error(f"Error refreshing temporary links: {str(e)}")
            
    async def get_folder_images(self, folder_path: str, include_subfolders: bool = False) -> List[Dict[str, Any]]:
        """
        Get all images in a folder with temporary links.
        
        Args:
            folder_path: Path to the folder
            include_subfolders: Whether to include images in subfolders
            
        Returns:
            List of image information dictionaries
        """
        # Start with the current folder
        folder_contents = await self.get_folder_contents(folder_path)
        images = folder_contents.get('images', [])
        
        # If including subfolders, process each subfolder recursively
        if include_subfolders:
            for subfolder in folder_contents.get('folders', []):
                subfolder_path = subfolder['path']
                subfolder_images = await self.get_folder_images(subfolder_path, True)
                images.extend(subfolder_images)
                
        return images
    
    
