"""

The Dropbox API does allow you to list and download files from a specific folder.Disappointed

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

import os
import dropbox
from dropbox.files import ListFolderResult, FileMetadata

def get_image_urls_and_download(access_token, folder_path, download_directory):
    # Initialize Dropbox client
    dbx = dropbox.Dropbox(access_token)
    
    # List all files in the specified folder
    try:
        # List folder contents
        result: ListFolderResult = dbx.files_list_folder(folder_path)
        
        # Filter for image files
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'}
        image_files = [
            entry for entry in result.entries 
            if isinstance(entry, FileMetadata) and 
               any(entry.name.lower().endswith(ext) for ext in image_extensions)
        ]
        
        # Prepare to store image URLs and download images
        image_urls = []
        
        for image in image_files:
            # Generate a shareable link for the image
            try:
                shared_link = dbx.sharing_create_shared_link_with_settings(image.path_lower)
                image_url = shared_link.url
                image_urls.append(image_url)
                
                # Download the image
                local_path = os.path.join(download_directory, image.name)
                with open(local_path, 'wb') as f:
                    metadata, response = dbx.files_download(image.path_lower)
                    f.write(response.content)
            
            except dropbox.exceptions.ApiError as e:
                print(f"Error processing {image.name}: {e}")
        
        return image_urls
    
    except dropbox.exceptions.ApiError as e:
        print(f"Error listing folder: {e}")
        return []

# Usage example
access_token = 'YOUR_DROPBOX_ACCESS_TOKEN'
folder_path = '/path/to/your/dropbox/folder'
download_directory = '/local/path/to/download/images'

image_urls = get_image_urls_and_download(access_token, folder_path, download_directory)
print("Image URLs:", image_urls)

class DropboxProductFolderNavigator:
    def __init__(self, access_token):
        """
        Initialize the Dropbox client with an access token
        
        Args:
            access_token (str): Dropbox API access token
        """
        self.dbx = dropbox.Dropbox(access_token)
    
    def list_top_level_product_folders(self, base_path='/Products'):
        """
        List all product folders in the base Products directory
        
        Args:
            base_path (str): Base directory containing product folders
        
        Returns:
            list: List of product folder names
        """
        try:
            # List folders in the base Products directory
            folders = []
            result = self.dbx.files_list_folder(base_path)
            
            for entry in result.entries:
                if entry.is_folder():
                    folders.append(entry.name)
            
            return folders
        
        except dropbox.exceptions.ApiError as e:
            print(f"Error listing product folders: {e}")
            return []
    
    def find_product_folder(self, product_identifier):
        """
        Find the exact folder path for a specific product
        
        Args:
            product_identifier (str): Unique identifier for the product
        
        Returns:
            str: Full path to the product folder, or None if not found
        """
        base_path = '/Products'
        try:
            # Search for folders matching the product identifier
            result = self.dbx.files_list_folder(base_path)
            
            for entry in result.entries:
                if entry.is_folder():
                    # Case-insensitive and partial match
                    if product_identifier.lower() in entry.name.lower():
                        return os.path.join(base_path, entry.name)
            
            return None
        
        except dropbox.exceptions.ApiError as e:
            print(f"Error finding product folder: {e}")
            return None
    
    def get_product_images(self, product_identifier):
        """
        Retrieve all images for a specific product
        
        Args:
            product_identifier (str): Unique identifier for the product
        
        Returns:
            list: List of image file paths
        """
        # Find the product folder
        product_folder = self.find_product_folder(product_identifier)
        
        if not product_folder:
            print(f"No folder found for product: {product_identifier}")
            return []
        
        try:
            # List image files in the product folder
            image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'}
            image_files = []
            
            result = self.dbx.files_list_folder(product_folder)
            
            for entry in result.entries:
                if entry.is_file():
                    # Check file extension
                    if any(entry.name.lower().endswith(ext) for ext in image_extensions):
                        image_files.append(os.path.join(product_folder, entry.name))
            
            return image_files
        
        except dropbox.exceptions.ApiError as e:
            print(f"Error listing images for product: {e}")
            return []

# Usage example
def main():
    # Replace with your actual Dropbox access token
    ACCESS_TOKEN = 'your_dropbox_access_token'
    
    # Initialize the navigator
    navigator = DropboxProductFolderNavigator(ACCESS_TOKEN)
    
    # List all product folders
    all_products = navigator.list_top_level_product_folders()
    print("Available Product Folders:", all_products)
    
    # Find images for a specific product
    product_id = 'summer-collection'
    product_images = navigator.get_product_images(product_id)
    
    print(f"Images for {product_id}:")
    for image in product_images:
        print(image)

if __name__ == '__main__':
    main()