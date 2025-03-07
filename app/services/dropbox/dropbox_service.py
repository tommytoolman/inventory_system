"""

The Dropbox API does allow you to list and download files from a specific folder.

Key points about this approach:
- Install the Dropbox Python SDK first with pip install dropbox
- You must generate an access token from the Dropbox Developer Console

The script does two things:
- Generates shareable URLs for images
- Downloads the images to a local directory

To get an access token:
- Go to the Dropbox Developer Console
- Create an app
- Generate an access token
- Keep it secret and never share it publicly

Caveats:
- Dropbox has rate limits on API calls
- For large folders, you might need to use pagination
- The shared link URL is typically different from the direct download URL

This implementation provides several key features:

Folder Navigation:
- Assumes a structured /Products/[Product Name] folder hierarchy
- Allows listing all product folders
- Supports fuzzy matching of product folders (case-insensitive, partial match)

Image Retrieval:
- Filters for common image file extensions
- Returns full file paths for product images

Flexibility:
- Can search for products by partial name
- Handles potential API errors gracefully

Practical Considerations:
- You'll need a consistent naming convention for product folders
- The base path /Products can be customized
- Error handling prevents the script from breaking if a folder is not found

Potential Enhancements:
- Add caching to reduce API calls
- Implement more sophisticated search algorithms
- Add logging for tracking searches

"""

import os, sys
import time
import json
import dropbox
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from dropbox import DropboxOAuth2FlowNoRedirect
from dropbox.exceptions import ApiError
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

# Use environment variables for credentials
APP_KEY = os.environ.get("DROPBOX_APP_KEY")
APP_SECRET = os.environ.get("DROPBOX_APP_SECRET")
REFRESH_TOKEN = os.environ.get("DROPBOX_REFRESH_TOKEN")
ACCESS_TOKEN = os.environ.get("DROPBOX_ACCESS_TOKEN")

# API endpoints
TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
LIST_FOLDER_URL = "https://api.dropboxapi.com/2/files/list_folder"
LIST_FOLDER_CONTINUE_URL = "https://api.dropboxapi.com/2/files/list_folder/continue"
GET_CURRENT_ACCOUNT_URL = "https://api.dropboxapi.com/2/users/get_current_account"


class DropboxClient:
    """Client for interacting with Dropbox API v2 with optimized folder scanning"""
    
    def __init__(self):
        
        def get_access_token(refresh_token, app_key, app_secret):
            """Get a new access token using the refresh token"""
            response = requests.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": app_key,
                    "client_secret": app_secret
                }
            )
    
            if response.status_code != 200:
                print(f"Error getting access token: {response.text}")
                return None
    
            data = response.json()
    
            return data.get('access_token')
        
        self.access_token = get_access_token(REFRESH_TOKEN, APP_KEY, APP_SECRET)
        self.base_url = "https://api.dropboxapi.com/2"
        self.headers = {
            'Authorization': f'Bearer {self.access_token}',
            # 'Content-Type': 'application/json'
        }
        self.file_links_cache = {}  # Cache for temporary links
        self.folder_structure = {}  # Complete folder structure
    
    def get_account_info(self):
        """Get information about the authenticated user's account"""
        endpoint = f"{self.base_url}/users/get_current_account"
        response = requests.post(endpoint, headers=self.headers)
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error getting account info: {response.status_code}")
            print(f"Response: {response.text}")
            return None
    
    async def list_folder_recursive(self, path="", max_depth=None):
        """
        List all contents of a folder recursively
        
        Args:
            path: Starting path
            max_depth: Maximum folder depth to scan (None for unlimited)
        """
        print(f"Starting folder scan for '{path}' (max_depth={max_depth})...")
        start_time = time.time()
        
        all_entries = []
        endpoint = f"{self.base_url}/files/list_folder"
        
        data = {
            "path": path,
            "recursive": True,  # This is key for efficient scanning
            "include_media_info": True,  # Get media info for images
            "include_deleted": False,
            "include_has_explicit_shared_members": False,
            "limit": 2000  # Request larger batches for efficiency
        }
        
        # If using recursive=True in the API call, there's no easy way to limit depth
        # So for debugging, you can check if max_depth is set to 1 and use a non-recursive call
        if max_depth == 1:
            # Non-recursive call for just top-level
            data["recursive"] = False
        
        response = requests.post(endpoint, headers=self.headers, json=data)
        
        if response.status_code != 200:
            print(f"Error listing folder: {response.status_code}")
            print(f"Response: {response.text}")
            return []
        
        result = response.json()
        entries = result.get('entries', [])
        all_entries.extend(entries)
        
        # Check if there are more entries
        has_more = result.get('has_more', False)
        cursor = result.get('cursor')
        
        # Use the continue endpoint to get all entries
        while has_more and cursor:
            print(f"Getting more entries... ({len(all_entries)} so far)")
            more_result = self._list_folder_continue(cursor)
            
            if not more_result:
                break
                
            more_entries = more_result.get('entries', [])
            all_entries.extend(more_entries)
            has_more = more_result.get('has_more', False)
            cursor = more_result.get('cursor')
        
        print(f"Completed folder scan in {time.time() - start_time:.2f} seconds")
        print(f"Found {len(all_entries)} total entries")
        return all_entries
    
    def _list_folder_continue(self, cursor):
        """Continue listing a folder with a cursor"""
        endpoint = f"{self.base_url}/files/list_folder/continue"
        
        data = {
            "cursor": cursor
        }
        
        response = requests.post(endpoint, headers=self.headers, json=data)
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error continuing folder listing: {response.status_code}")
            print(f"Response: {response.text}")
            return None
    
    def get_temporary_link(self, file_path):
        """Get a temporary link to a file"""
        # Check cache first
        now = datetime.now()
        if file_path in self.file_links_cache:
            cached_link, expiry = self.file_links_cache[file_path]
            if now < expiry:
                return cached_link
        
        endpoint = f"{self.base_url}/files/get_temporary_link"
        
        data = {
            "path": file_path
        }
        
        response = requests.post(endpoint, headers=self.headers, json=data)
        
        if response.status_code == 200:
            result = response.json()
            link = result.get('link')
            
            # Cache the link with 4-hour expiration
            expiry = now + timedelta(hours=4)
            self.file_links_cache[file_path] = (link, expiry)
            
            return link
        else:
            print(f"Error getting temporary link for {file_path}: {response.status_code}")
            return None
    
    def get_temporary_links_batch(self, file_paths, max_workers=10):
        """Get temporary links for multiple files using parallel requests"""
        # print(f"Getting temporary links for {len(file_paths)} files...")
        start_time = time.time()
        
        results = {}
        
        # Use ThreadPoolExecutor for parallel processing
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Create a map of futures to file paths
            future_to_path = {
                executor.submit(self.get_temporary_link, path): path
                for path in file_paths
            }
            
            # Process as they complete
            for i, future in enumerate(future_to_path):
                path = future_to_path[future]
                try:
                    link = future.result()
                    results[path] = link
                    
                    # Print progress every 100 items
                    if (i + 1) % 200 == 0:
                        print(f"Processed {i + 1}/{len(file_paths)} links...")
                        
                except Exception as e:
                    print(f"Error getting link for {path}: {str(e)}")
        
        print(f"Completed getting temporary links in {time.time() - start_time:.2f} seconds")
        return results
    
    def build_folder_structure(self, entries):
        """Build a hierarchical folder structure from flat entries list"""
        print("Building folder structure...")
        start_time = time.time()
        
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
            
            # Initialize the folder content (will be filled later)
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
        
        print(f"Built folder structure in {time.time() - start_time:.2f} seconds")
        return folder_structure
    
    def _ensure_path_exists(self, structure, path):
        """Ensure a folder path exists in the structure dictionary"""
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
    
    def _get_folder_at_path(self, structure, path):
        """Get the folder object at a specific path"""
        if not path or path == '/':
            return structure
            
        return structure.get(path, {})
    
    def _format_file_size(self, size_bytes):
        """Format file size in a human-readable form"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
    
    def setup_webhook(self, webhook_url):
        """Set up a webhook for file changes in the Dropbox account"""
        endpoint = f"{self.base_url}/files/list_folder/longpoll"
        
        # First, get a cursor for the account
        cursor_response = requests.post(
            f"{self.base_url}/files/list_folder/get_latest_cursor",
            headers=self.headers,
            json={"path": "", "recursive": True}
        )
        
        if cursor_response.status_code != 200:
            print(f"Error getting cursor: {cursor_response.status_code}")
            print(f"Response: {cursor_response.text}")
            return False
            
        cursor = cursor_response.json().get('cursor')
        
        # Register the webhook
        webhook_endpoint = f"{self.base_url}/2/files/list_folder/webhooks/add"
        webhook_data = {
            "cursor": cursor,
            "webhook_url": webhook_url
        }
        
        webhook_headers = self.headers.copy()
        
        webhook_response = requests.post(
            webhook_endpoint,
            headers=webhook_headers,
            json=webhook_data
        )
        
        if webhook_response.status_code == 200:
            webhook_id = webhook_response.json().get('webhook_id')
            print(f"Successfully set up webhook with ID: {webhook_id}")
            return webhook_id
        else:
            print(f"Error setting up webhook: {webhook_response.status_code}")
            print(f"Response: {webhook_response.text}")
            return None
    
    def scan_and_map_folder(self, start_path=""):
        """Complete process to scan and map a folder with temporary links"""
        # 1. Get all entries recursively
        all_entries = self.list_folder_recursive(start_path)
        
        # 2. Build folder structure
        folder_structure = self.build_folder_structure(all_entries)
        
        # 3. Get all file paths
        file_paths = []
        for entry in all_entries:
            if entry.get('.tag') == 'file':
                file_paths.append(entry.get('path_lower'))
        
        # 4. Get temporary links for all files
        print(f"Getting temporary links for {len(file_paths)} files...")
        temp_links = self.get_temporary_links_batch(file_paths)
        
        # 5. Add temporary links to the folder structure
        for path, link in temp_links.items():
            parent_path = os.path.dirname(path)
            filename = os.path.basename(path)
            
            parent = self._get_folder_at_path(folder_structure, parent_path)
            
            for file_entry in parent.get('files', []):
                if file_entry.get('path') == path:
                    file_entry['temporary_link'] = link
                    break
        
        return {
            'folder_structure': folder_structure,
            'all_entries': all_entries,
            'temp_links': temp_links
        }

    def poll_for_changes(self, check_interval=60):
        """
        Poll for changes in the Dropbox account using cursor-based tracking
        
        Args:
            check_interval: Seconds between checks
        """
        print(f"Starting polling for changes (checking every {check_interval} seconds)...")
        
        # Get the latest cursor as a starting point
        cursor_response = requests.post(
            f"{self.base_url}/files/list_folder/get_latest_cursor",
            headers=self.headers,
            json={"path": "", "recursive": True}
        )
        
        if cursor_response.status_code != 200:
            print(f"Error getting cursor: {cursor_response.status_code}")
            print(f"Response: {cursor_response.text}")
            return
            
        cursor = cursor_response.json().get('cursor')
        print(f"Initial cursor obtained: {cursor[:20]}...")
        
        try:
            while True:
                # Use longpoll to efficiently wait for changes
                print(f"Waiting for changes...")
                longpoll_response = requests.post(
                    f"{self.base_url}/files/list_folder/longpoll",
                    json={
                        "cursor": cursor,
                        "timeout": 30  # Seconds to wait (max 480)
                    }
                )
                
                if longpoll_response.status_code != 200:
                    print(f"Error in longpoll: {longpoll_response.status_code}")
                    print(f"Response: {longpoll_response.text}")
                    time.sleep(check_interval)  # Wait before retry
                    continue
                    
                changes = longpoll_response.json()
                
                # If changes detected
                if changes.get('changes', False):
                    print("Changes detected! Getting details...")
                    
                    # Get the actual changes
                    changes_response = requests.post(
                        f"{self.base_url}/files/list_folder/continue",
                        headers=self.headers,
                        json={"cursor": cursor}
                    )
                    
                    if changes_response.status_code != 200:
                        print(f"Error getting changes: {changes_response.status_code}")
                        time.sleep(check_interval)
                        continue
                    
                    # Process the changes
                    entries = changes_response.json().get('entries', [])
                    
                    # Record the new cursor for next iteration
                    cursor = changes_response.json().get('cursor')
                    
                    print(f"Found {len(entries)} changed items:")
                    for entry in entries:
                        path = entry.get('path_lower', '')
                        change_type = entry.get('.tag', '')
                        
                        if change_type == 'file':
                            print(f"- File changed: {path}")
                            # If it's a photo, process it
                            if self._is_photo(path):
                                print(f"  This is a photo, processing...")
                                # Get temp link, add to structure, etc.
                                
                        elif change_type == 'folder':
                            print(f"- Folder changed: {path}")
                            
                        elif change_type == 'deleted':
                            print(f"- Item deleted: {path}")
                else:
                    print("No changes detected in this interval.")
                
                # If backoff is suggested, respect it
                if 'backoff' in changes:
                    backoff = changes['backoff']
                    print(f"API requested backoff of {backoff} seconds")
                    time.sleep(backoff)
                else:
                    # Otherwise use our default interval
                    time.sleep(check_interval)
                    
        except KeyboardInterrupt:
            print("Polling stopped by user.")
        except Exception as e:
            print(f"Error in polling loop: {str(e)}")
    
    def _is_photo(self, path):
        """Check if a file is a photo based on extension"""
        photo_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.tiff', '.bmp', '.heic']
        ext = os.path.splitext(path.lower())[1]
        return ext in photo_extensions

    def track_changes_with_delta(self, path_prefix=""):
        """
        Track changes using the more efficient Delta API
        
        Args:
            path_prefix: Only track changes within this path
        """
        print(f"Starting change tracking for path prefix: {path_prefix}")
        
        # If we have a saved cursor, use it; otherwise start fresh
        cursor = None  # You'd typically load this from storage
        
        while True:
            try:
                endpoint = f"{self.base_url}/files/list_folder/continue" if cursor else f"{self.base_url}/files/list_folder"
                
                data = {
                    "include_deleted": True,
                    "recursive": True
                }
                
                if cursor:
                    data = {"cursor": cursor}
                else:
                    data["path"] = path_prefix if path_prefix else ""
                
                response = requests.post(endpoint, headers=self.headers, json=data)
                
                if response.status_code != 200:
                    print(f"Error tracking changes: {response.status_code}")
                    print(f"Response: {response.text}")
                    time.sleep(60)  # Wait before retry
                    continue
                
                result = response.json()
                entries = result.get('entries', [])
                cursor = result.get('cursor')
                
                # Process changes
                if entries:
                    print(f"Processing {len(entries)} changes...")
                    for entry in entries:
                        # Process each change...
                        pass
                
                # Save cursor for resuming later
                # self._save_cursor(cursor)
                
                # If no more changes, wait before checking again
                if not result.get('has_more', False):
                    print("No more changes. Waiting before next check...")
                    time.sleep(60)  # Adjust as needed
                    
            except Exception as e:
                print(f"Error in change tracking: {str(e)}")
                time.sleep(60)  # Wait before retry


