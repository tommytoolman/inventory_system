# app/services/dropbox/dropbox_async_service.py
import os
import asyncio
import aiohttp
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

class AsyncDropboxClient:
    """Fully asynchronous Dropbox client for optimal performance"""
    
    BASE_URL = "https://api.dropboxapi.com/2"
    
    def __init__(self, access_token):
        self.access_token = access_token
        self.headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        self.file_links_cache = {}  # Cache for temporary links
        
    async def scan_and_map_folder(self, path=""):
        """Asynchronously scan and map a Dropbox folder structure with optimal performance"""
        print(f"Starting async Dropbox scan of '{path}'...")
        start_time = datetime.now()
        
        # Step 1: Get all entries recursively (this is still sequential due to API pagination)
        all_entries = await self.list_folder_recursive(path)
        step1_time = datetime.now()
        print(f"Step 1: Folder listing completed in {(step1_time - start_time).total_seconds():.2f} seconds")
        
        # Step 2: Build folder structure (this is CPU-bound, not I/O-bound)
        folder_structure = self.build_folder_structure(all_entries)
        step2_time = datetime.now()
        print(f"Step 2: Structure building completed in {(step2_time - step1_time).total_seconds():.2f} seconds")
        
        # Step 3: Get image file paths from the structure
        image_paths = []
        for entry in all_entries:
            if entry.get('.tag') == 'file':
                path = entry.get('path_lower', '')
                if any(path.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                    image_paths.append(path)
        
        step3_time = datetime.now()
        print(f"Step 3: Found {len(image_paths)} image files in {(step3_time - step2_time).total_seconds():.2f} seconds")
        
        # Step 4: Get temporary links for images in parallel batches
        # This is where we can make massive improvements with async
        temp_links = await self.get_temporary_links_async(image_paths)
        step4_time = datetime.now()
        print(f"Step 4: Generated {len(temp_links)} temp links in {(step4_time - step3_time).total_seconds():.2f} seconds")
        
        # Build the final map
        dropbox_map = {
            'folder_structure': folder_structure,
            'all_entries': all_entries,
            'temp_links': temp_links
        }
        
        print(f"Total scan time: {(datetime.now() - start_time).total_seconds():.2f} seconds")
        return dropbox_map
    
    async def list_folder_recursive(self, path=""):
        """List all contents of a folder recursively"""
        print(f"Starting folder scan for '{path}'...")
        
        all_entries = []
        try:
            async with aiohttp.ClientSession() as session:
                # Initial request
                endpoint = f"{self.BASE_URL}/files/list_folder"
                data = {
                    "path": path,
                    "recursive": True,
                    "include_media_info": True,
                    "include_deleted": False,
                    "include_has_explicit_shared_members": False,
                    "limit": 2000
                }
                
                async with session.post(endpoint, headers=self.headers, json=data) as response:
                    if response.status != 200:
                        text = await response.text()
                        print(f"Error listing folder: {response.status}")
                        print(f"Response: {text}")
                        return []
                    
                    result = await response.json()
                    entries = result.get('entries', [])
                    all_entries.extend(entries)
                    
                    # Handle pagination
                    has_more = result.get('has_more', False)
                    cursor = result.get('cursor')
                    
                    while has_more and cursor:
                        print(f"Getting more entries... ({len(all_entries)} so far)")
                        continue_data = {"cursor": cursor}
                        
                        continue_endpoint = f"{self.BASE_URL}/files/list_folder/continue"
                        async with session.post(continue_endpoint, headers=self.headers, json=continue_data) as continue_response:
                            if continue_response.status != 200:
                                break
                                
                            continue_result = await continue_response.json()
                            more_entries = continue_result.get('entries', [])
                            all_entries.extend(more_entries)
                            has_more = continue_result.get('has_more', False)
                            cursor = continue_result.get('cursor')
                
                print(f"Found {len(all_entries)} total entries")
                return all_entries
                
        except Exception as e:
            print(f"Error in list_folder_recursive: {str(e)}")
            return []
    
    def build_folder_structure(self, entries):
        """Build hierarchical folder structure from entries (CPU-bound, not async)"""
        # This implementation remains the same as your current one
        folder_structure = {}
        
        # First create folder structure
        for entry in entries:
            if entry.get('.tag') == 'folder':
                path = entry.get('path_lower', '')
                self._ensure_path_exists(folder_structure, path)
        
        # Then add files to the structure
        for entry in entries:
            if entry.get('.tag') == 'file':
                path = entry.get('path_lower', '')
                parent_path = os.path.dirname(path)
                file_name = os.path.basename(path)
                
                # Ensure parent folder exists
                parent = self._get_folder_at_path(folder_structure, parent_path)
                
                # Add file to parent's files list
                if 'files' not in parent:
                    parent['files'] = []
                
                file_entry = {
                    'name': file_name,
                    'path': path,
                    'size': entry.get('size', 0),
                }
                
                parent['files'].append(file_entry)
        
        return folder_structure
    
    def _ensure_path_exists(self, structure, path):
        """Helper to ensure a folder path exists in the structure"""
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
        """Helper to get folder at a specific path"""
        if not path or path == '/':
            return structure
            
        return structure.get(path, {})
    
    async def get_temporary_link(self, session, file_path):
        """Get a temporary link for a single file using aiohttp session"""
        try:
            endpoint = f"{self.BASE_URL}/files/get_temporary_link"
            data = {"path": file_path}
            
            async with session.post(endpoint, headers=self.headers, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    return file_path, result.get('link')
                else:
                    text = await response.text()
                    print(f"Error getting link for {file_path}: {text}")
                    return file_path, None
        except Exception as e:
            print(f"Exception getting link for {file_path}: {str(e)}")
            return file_path, None
    
    async def get_temporary_links_async(self, file_paths, batch_size=20):
        """
        Get temporary links for multiple files with true async processing
        
        This optimizes by:
        1. Using aiohttp for async HTTP
        2. Processing in concurrent batches to avoid rate limits
        3. Using asyncio.gather for true concurrency
        """
        results = {}
        print(f"Getting temporary links for {len(file_paths)} files in batches of {batch_size}...")
        
        # Process in batches to avoid overwhelming the API
        for i in range(0, len(file_paths), batch_size):
            batch = file_paths[i:i+batch_size]
            print(f"Processing batch {i//batch_size + 1}/{(len(file_paths) + batch_size - 1)//batch_size}")
            
            async with aiohttp.ClientSession() as session:
                # Create a list of coroutines for this batch
                tasks = [self.get_temporary_link(session, path) for path in batch]
                
                # Execute them concurrently
                batch_results = await asyncio.gather(*tasks)
                
                # Add successful results to the dictionary
                for path, link in batch_results:
                    if link:
                        results[path] = link
            
            # Optional small delay between batches to avoid rate limiting
            if i + batch_size < len(file_paths):
                await asyncio.sleep(0.1)
        
        print(f"Successfully obtained {len(results)} temporary links")
        return results
    
    async def test_connection(self):
        """Test the connection to Dropbox API"""
        try:
            print("Testing Dropbox API connection...")
            async with aiohttp.ClientSession() as session:
                # Get current account info (lightweight call)
                endpoint = f"{self.BASE_URL}/users/get_current_account"
                
                async with session.post(endpoint, headers=self.headers) as response:
                    if response.status != 200:
                        text = await response.text()
                        print(f"Connection test failed with status {response.status}: {text}")
                        return False
                        
                    account_info = await response.json()
                    print(f"Connected to Dropbox account: {account_info.get('email', 'unknown')}")
                    return True
                    
        except Exception as e:
            print(f"Connection test exception: {str(e)}")
            return False