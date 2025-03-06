import json

from app.services.dropbox import dropbox_service
from dropbox_service import DropboxClient

def main():
    # Replace with your access token
    
    # Create Dropbox client
    client = DropboxClient()
    # access_token = get_access_token(REFRESH_TOKEN, APP_KEY, APP_SECRET)
    
    # Verify connection by getting account info
    print("Verifying connection...")
    account_info = client.get_account_info()
    
    if account_info:
        print(f"Connected to Dropbox as {account_info.get('email')} ({account_info.get('name', {}).get('display_name')})")
        
        # Starting point - can be empty string for root or a specific folder path
        start_folder = "/feb25/07_red_marshall_100w"  # Change this to the folder you want to explore
        
        # Optional: Set up a webhook for notifications
        # webhook_url = "https://your-webhook-endpoint.com/dropbox-webhook"
        # webhook_id = client.setup_webhook(webhook_url)
        
        # Scan and map the folder structure
        print(f"\nScanning entire folder structure from: {start_folder}")
        result = client.scan_and_map_folder(start_folder)
        
        # Save results to a JSON file
        output_file = "dropbox_complete_mapping.json"
        with open(output_file, 'w') as f:
            json.dump(result['folder_structure'], f, indent=2)
        
        # Save temporary links to a separate file for easy access
        links_file = "dropbox_temporary_links.json"
        with open(links_file, 'w') as f:
            json.dump(result['temp_links'], f, indent=2)
        
        print(f"\nResults saved to {output_file} and {links_file}")
        
        # Print summary
        total_files = len(result['temp_links'])
        total_folders = sum(1 for entry in result['all_entries'] if entry.get('.tag') == 'folder')

        print(f"\nSummary:")
        print(f"- Total folders found: {total_folders}")
        print(f"- Total files found: {total_files}")
        print(f"- Temporary links generated: {len(result['temp_links'])}")

        # List some example files
        print("\nExample files with temporary links:")
        count = 0
        for path, link in list(result['temp_links'].items())[:5]:  # Show first 5 links
            print(f"- {path}: {link[:60]}...")
            count += 1

        if count < len(result['temp_links']):
            print(f"... and {len(result['temp_links']) - count} more files")
    else:
        print("Failed to connect to Dropbox. Please check your access token.")

if __name__ == "__main__":
    main()