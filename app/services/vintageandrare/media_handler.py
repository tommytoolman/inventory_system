# tests/integration/media_handler.py
import os
import tempfile
import requests
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse
import shutil

class MediaHandler:
    """
    Handles downloading and managing temporary image files
    
    - Currently downloads an image from any provided URL (including a potential Dropbox URL) to a local temporary file. 
    - inspect_form.py then tells Selenium to upload that local temporary file.
    - Workflow should still function correctly even if the image URLs originate from Dropbox (added since this was written), 
        as long as the Dropbox URLs are direct links to the image data that requests.get can download. 
    - The primary change is the source of the image URLs (from central DB/Dropbox service), 
        not necessarily the mechanics within media_handler.py itself.
    """
    
    def __init__(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self._temp_files = []
    
    def download_image(self, url: str) -> Optional[Path]:
        """
        Download image from URL to temporary file
        Returns path to temporary file or None if download fails
        """
        try:
            # Validate URL
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError(f"Invalid URL: {url}")
            
            # Get file extension from URL or default to .jpg
            ext = os.path.splitext(parsed.path)[1]
            if not ext:
                ext = '.jpg'
            
            # Create temporary file
            temp_file = self.temp_dir / f"temp_{len(self._temp_files)}{ext}"
            
            # Download image
            response = requests.get(url, stream=True)
            response.raise_for_status()
            
            # Check if content is an image
            content_type = response.headers.get('content-type', '')
            if not content_type.startswith('image/'):
                raise ValueError(f"URL does not point to an image: {content_type}")
            
            # Save to temporary file
            with open(temp_file, 'wb') as f:
                shutil.copyfileobj(response.raw, f)
            
            self._temp_files.append(temp_file)
            return temp_file
            
        except Exception as e:
            print(f"Error downloading image from {url}: {str(e)}")
            return None
    
    def clean_up(self):
        """Remove all temporary files and directory"""
        try:
            shutil.rmtree(self.temp_dir)
        except Exception as e:
            print(f"Error cleaning up temporary files: {str(e)}")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.clean_up()