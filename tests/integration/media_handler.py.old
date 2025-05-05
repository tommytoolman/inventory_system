# tests/integration/media_handler.py
import os
import tempfile
import requests
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse
import shutil

class MediaHandler:
    """Handles downloading and managing temporary image files"""
    
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