import os
import asyncio
import logging

from datetime import datetime
from typing import Optional, Any

from fastapi import (
    APIRouter,
    Depends,
    Request,
    BackgroundTasks,
    Query,
)

from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder

from app.core.config import Settings, get_settings

router = APIRouter()
logger = logging.getLogger(__name__)


async def get_dropbox_client(request: Request, settings: Settings = None) -> 'AsyncDropboxClient':
    """
    Get or create a shared Dropbox client with token persistence.

    This solves the token refresh issue where each request was creating a new client
    with a stale token, causing 401 errors on every request.

    The refreshed token is stored in app.state.dropbox_access_token so it persists
    across requests.
    """
    from app.services.dropbox.dropbox_async_service import AsyncDropboxClient

    if settings is None:
        settings = get_settings()

    # Check for refreshed token in app.state first (persists across requests)
    access_token = getattr(request.app.state, 'dropbox_access_token', None)

    # Fall back to settings/environment if no refreshed token
    if not access_token:
        access_token = getattr(settings, 'DROPBOX_ACCESS_TOKEN', None) or os.environ.get('DROPBOX_ACCESS_TOKEN')

    refresh_token = getattr(settings, 'DROPBOX_REFRESH_TOKEN', None) or os.environ.get('DROPBOX_REFRESH_TOKEN')
    app_key = getattr(settings, 'DROPBOX_APP_KEY', None) or os.environ.get('DROPBOX_APP_KEY')
    app_secret = getattr(settings, 'DROPBOX_APP_SECRET', None) or os.environ.get('DROPBOX_APP_SECRET')

    client = AsyncDropboxClient(
        access_token=access_token,
        refresh_token=refresh_token,
        app_key=app_key,
        app_secret=app_secret
    )

    # Test connection and refresh if needed
    if not await client.test_connection():
        # If test failed but we have refresh credentials, token may have been refreshed
        # Store the new token in app.state for future requests
        if client.access_token and client.access_token != access_token:
            request.app.state.dropbox_access_token = client.access_token
            logging.getLogger(__name__).info("Stored refreshed Dropbox token in app.state")
    else:
        # Connection succeeded, store token in case it was refreshed during test
        if client.access_token:
            request.app.state.dropbox_access_token = client.access_token

    return client


async def _upload_local_image_to_dropbox(
    local_url: str,
    sku: str,
    *args: Any,
    **kwargs: Any,
) -> Optional[str]:
    """Placeholder while Dropbox uploads are disabled.

    Uploading to Dropbox currently requires the `files.content.write` scope,
    which is not enabled on the connected app. Keep the helper in place so it
    can be reactivated quickly once the permissions are updated.
    """

    logger.debug(
        "Dropbox upload disabled; returning local URL for %s (SKU %s)",
        local_url,
        sku,
    )
    return None


@router.get("/api/dropbox/folders", response_class=JSONResponse)
async def get_dropbox_folders(
    request: Request,
    background_tasks: BackgroundTasks,
    path: str = "",
    settings: Settings = Depends(get_settings)
):
    """
    API endpoint to get Dropbox folders for navigation with token refresh support.

    This endpoint:
    1. Handles token refresh if needed
    2. Uses the cached folder structure when available
    3. Returns folder and file information for UI navigation
    4. Initializes a background scan if needed
    """
    try:
        # Check if scan is already in progress
        if hasattr(request.app.state, 'dropbox_scan_in_progress') and request.app.state.dropbox_scan_in_progress:
            progress = getattr(request.app.state, 'dropbox_scan_progress', {'status': 'scanning', 'progress': 0})
            return JSONResponse(
                status_code=202,  # Accepted but processing
                content={
                    "status": "processing",
                    "message": "Dropbox scan in progress",
                    "progress": progress
                }
            )

        # Get credentials
        access_token = getattr(settings, 'DROPBOX_ACCESS_TOKEN', None) or os.environ.get('DROPBOX_ACCESS_TOKEN')
        refresh_token = getattr(settings, 'DROPBOX_REFRESH_TOKEN', None) or os.environ.get('DROPBOX_REFRESH_TOKEN')
        app_key = getattr(settings, 'DROPBOX_APP_KEY', None) or os.environ.get('DROPBOX_APP_KEY')
        app_secret = getattr(settings, 'DROPBOX_APP_SECRET', None) or os.environ.get('DROPBOX_APP_SECRET')

        # Direct fallback to environment variables if not in settings
        if not access_token:
            access_token = os.environ.get('DROPBOX_ACCESS_TOKEN')
            print(f"Loading access token directly from environment: {bool(access_token)}")

        if not refresh_token:
            refresh_token = os.environ.get('DROPBOX_REFRESH_TOKEN')
            print(f"Loading refresh token directly from environment: {bool(refresh_token)}")

        if not app_key:
            app_key = os.environ.get('DROPBOX_APP_KEY')
            print(f"Loading app key directly from environment: {bool(app_key)}")

        if not app_secret:
            app_secret = os.environ.get('DROPBOX_APP_SECRET')
            print(f"Loading app secret directly from environment: {bool(app_secret)}")

        # Check if all credentials are available now
        if not access_token and not refresh_token:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "error",
                    "message": "Dropbox credentials not available. Please configure DROPBOX_ACCESS_TOKEN or DROPBOX_REFRESH_TOKEN in .env file."
                }
            )

        # Use shared client with token persistence to avoid 401 on every request
        client = await get_dropbox_client(request, settings)

        # Check if we need to initialize a scan
        if (not hasattr(request.app.state, 'dropbox_map') or
            request.app.state.dropbox_map is None):

            # Check if the service has cached folder structure
            logger.info(f"Checking client folder structure: {bool(client.folder_structure)}, entries: {len(client.folder_structure) if client.folder_structure else 0}")
            if client.folder_structure:
                logger.info("Found cached folder structure in service, using it")

                # Also update app state for consistency
                request.app.state.dropbox_map = {
                    'folder_structure': client.folder_structure,
                    'temp_links': {}
                }
                request.app.state.dropbox_last_updated = datetime.now()

                # Use the service's cached data
                folder_contents = await client.get_folder_contents(path)

                # For root path, extract top-level folders from the structure
                if not path:
                    folders = []
                    logger.info(f"Extracting folders from structure with {len(client.folder_structure)} entries")
                    for folder_path, folder_data in client.folder_structure.items():
                        logger.debug(f"Checking {folder_path}: is_dict={isinstance(folder_data, dict)}, starts_with_slash={folder_path.startswith('/')}, slash_count={folder_path.count('/')}")
                        if isinstance(folder_data, dict) and folder_path.startswith('/') and folder_path.count('/') == 1:
                            folder_entry = {
                                'name': folder_path.strip('/'),
                                'path': folder_path,
                                'is_folder': True
                            }
                            folders.append(folder_entry)
                            logger.debug(f"Added folder: {folder_entry}")

                    logger.info(f"Found {len(folders)} folders to return")
                    return JSONResponse(
                        content={
                            "folders": sorted(folders, key=lambda x: x['name'].lower()),
                            "files": [],
                            "current_path": path,
                            "cached": True
                        }
                    )
                else:
                    return JSONResponse(
                        content={
                            "folders": folder_contents.get("folders", []),
                            "files": folder_contents.get("images", []),
                            "current_path": path,
                            "cached": True
                        }
                    )

            # No cache available anywhere
            return JSONResponse(
                content={
                    "folders": [],
                    "files": [],
                    "current_path": path,
                    "message": "No Dropbox data cached. Please use the sync button to load data."
                }
            )

        # Get cached data
        dropbox_map = request.app.state.dropbox_map
        logger.info(f"App state dropbox_map exists: {dropbox_map is not None}, has structure: {'folder_structure' in dropbox_map if dropbox_map else False}")

        # If the token might be expired, verify it
        last_updated = getattr(request.app.state, 'dropbox_last_updated', None)
        token_age_hours = ((datetime.now() - last_updated).total_seconds() / 3600) if last_updated else None

        if token_age_hours and token_age_hours > 3:  # Check if token is older than 3 hours
            # Test connection and refresh if needed
            test_result = await client.test_connection()
            if not test_result:
                # Connection failed - token might be expired
                # This function handles refresh internally
                print("Token may be expired, getting fresh folder data")

                # Get specific folder contents
                if path:
                    folder_data = await client.get_folder_contents(path)
                    return folder_data
                else:
                    # For root, just list top-level folders
                    entries = await client.list_folder_recursive(path="", max_depth=1)
                    folders = []
                    for entry in entries:
                        if entry.get('.tag') == 'folder':
                            folder_path = entry.get('path_lower', '')
                            folder_name = os.path.basename(folder_path)
                            folders.append({
                                'name': folder_name,
                                'path': folder_path,
                                'is_folder': True
                            })
                    return {"folders": sorted(folders, key=lambda x: x['name'])}

        # If we get here, we can use the cached structure
        folder_structure = dropbox_map['folder_structure']

        # If first request, return top-level folders
        if not path:
            # Return top-level folders
            folders = []
            for folder_name, folder_data in folder_structure.items():
                if isinstance(folder_data, dict) and folder_name.startswith('/'):
                    folders.append({
                        'name': folder_name.strip('/'),
                        'path': folder_name,
                        'is_folder': True
                    })

            return {"folders": sorted(folders, key=lambda x: x['name'].lower())}
        else:
            # Navigate to the requested path
            current_level = folder_structure
            current_path = ""
            path_parts = path.strip('/').split('/')

            for part in path_parts:
                if part:
                    current_path = f"/{part}" if current_path == "" else f"{current_path}/{part}"
                    if current_path in current_level:
                        current_level = current_level[current_path]
                    else:
                        # Path not found
                        return {"items": [], "current_path": path, "error": f"Path {path} not found"}

            # Get folders and files at this level
            items = []

            # Process each key in the current level
            for key, value in current_level.items():
                # Skip non-string keys or special keys
                if not isinstance(key, str):
                    continue

                if key.startswith('/'):
                    # This is a subfolder
                    name = os.path.basename(key)
                    items.append({
                        'name': name,
                        'path': key,
                        'is_folder': True
                    })
                elif key == 'files' and isinstance(value, list):
                    # This is the files list
                    for file in value:
                        if not isinstance(file, dict) or 'path' not in file:
                            continue

                        # Only include image files
                        if any(file['path'].lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                            # Get temp link from the map if available
                            temp_link = None
                            if 'temp_links' in dropbox_map and file['path'] in dropbox_map['temp_links']:
                                temp_link = dropbox_map['temp_links'][file['path']]

                            items.append({
                                'name': file.get('name', os.path.basename(file['path'])),
                                'path': file['path'],
                                'is_folder': False,
                                'temp_link': temp_link
                            })

            # Sort items (folders first, then files)
            items.sort(key=lambda x: (not x['is_folder'], x['name'].lower()))

            return {"items": items, "current_path": path}

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"error": f"Error accessing Dropbox: {str(e)}"}
        )

@router.get("/api/dropbox/images", response_class=JSONResponse)
async def get_dropbox_images(
    request: Request,
    folder_path: str
):
    """
    API endpoint to get images from a Dropbox folder.

    This function uses two approaches to find images:
    1. First it directly searches for images in the temp_links cache with matching paths
    2. Then it tries to navigate the folder structure if no direct matches are found

    Args:
        request: The FastAPI request object
        folder_path: The Dropbox folder path to get images from

    Returns:
        JSON response with list of images and their temporary links
    """
    try:
        # Check for cached structure
        dropbox_map = getattr(request.app.state, 'dropbox_map', None)
        if not dropbox_map:
            return {"images": [], "error": "No Dropbox cache found. Please refresh the page."}

        # Normalize the folder path for consistent comparisons
        normalized_folder_path = folder_path.lower().rstrip('/')

        # APPROACH 1: First directly look in temp_links for images in this folder
        images = []
        temp_links = dropbox_map.get('temp_links', {})

        # Search for images directly in the requested folder
        for path, link_data in temp_links.items():
            path_lower = path.lower()

            # Match files directly in this folder (not in subfolders)
            folder_part = os.path.dirname(path_lower)

            if folder_part == normalized_folder_path:
                if any(path_lower.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                    # Handle new format with thumbnail and full URLs
                    if isinstance(link_data, dict):
                        images.append({
                            'name': os.path.basename(path),
                            'path': path,
                            'url': link_data.get('thumbnail', link_data.get('full')),  # Use thumbnail for display
                            'full_url': link_data.get('full'),  # Include full URL for when image is selected
                            'thumbnail_url': link_data.get('thumbnail')
                        })
                    else:
                        # Old format compatibility
                        images.append({
                            'name': os.path.basename(path),
                            'path': path,
                            'url': link_data,
                            'full_url': link_data,
                            'thumbnail_url': link_data
                        })

        # If images found directly, return them
        if images:
            print(f"Found {len(images)} images directly in folder {folder_path}")
            # Sort images by name for consistent ordering
            images.sort(key=lambda x: x.get('name', ''))
            return {"images": images}

        # APPROACH 2: If no images found directly, try navigating the folder structure
        folder_structure = dropbox_map.get('folder_structure', {})
        path_parts = folder_path.strip('/').split('/')
        current = folder_structure
        current_path = ""

        # Navigate to the folder
        for part in path_parts:
            if part:
                current_path = f"/{part}" if current_path == "" else f"{current_path}/{part}"
                if current_path in current:
                    current = current[current_path]
                else:
                    # Try a more flexible path search in temp_links as a fallback
                    fallback_images = []
                    search_prefix = f"{normalized_folder_path}/"

                    for path, link_data in temp_links.items():
                        if path.lower().startswith(search_prefix) and any(path.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                            # Handle new format with thumbnail and full URLs
                            if isinstance(link_data, dict):
                                fallback_images.append({
                                    'name': os.path.basename(path),
                                    'path': path,
                                    'url': link_data.get('thumbnail', link_data.get('full')),
                                    'full_url': link_data.get('full'),
                                    'thumbnail_url': link_data.get('thumbnail')
                                })
                            else:
                                # Old format compatibility
                                fallback_images.append({
                                    'name': os.path.basename(path),
                                    'path': path,
                                    'url': link_data,
                                    'full_url': link_data,
                                    'thumbnail_url': link_data
                                })

                    if fallback_images:
                        print(f"Found {len(fallback_images)} images using fallback search for {folder_path}")
                        fallback_images.sort(key=lambda x: x.get('name', ''))
                        return {"images": fallback_images}

                    # If no fallback images found either, return empty list
                    print(f"Folder {folder_path} not found in structure")
                    return {"images": [], "error": f"Folder {folder_path} not found"}

        # Extract images from specified folder using recursive helper function
        def extract_images_from_folder(folder_data, prefix=""):
            result = []

            # Check if folder contains files array
            if isinstance(folder_data, dict) and 'files' in folder_data and isinstance(folder_data['files'], list):
                for file in folder_data['files']:
                    if (file.get('path') and any(file['path'].lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif'])):
                        # Get temp link from the map
                        temp_link = None
                        if 'temp_links' in dropbox_map and file['path'] in dropbox_map['temp_links']:
                            temp_link = dropbox_map['temp_links'][file['path']]

                        if temp_link:
                            # Handle both old format (string URL) and new format (dict with thumbnail/full)
                            if isinstance(temp_link, dict):
                                result.append({
                                    'name': file.get('name', os.path.basename(file['path'])),
                                    'path': file['path'],
                                    'thumbnail_url': temp_link.get('thumbnail'),
                                    'url': temp_link.get('full') or temp_link.get('thumbnail'),  # Full may be None (lazy fetch)
                                })
                            else:
                                # Legacy string format
                                result.append({
                                    'name': file.get('name', os.path.basename(file['path'])),
                                    'path': file['path'],
                                    'thumbnail_url': temp_link,
                                    'url': temp_link
                                })

            # Look through subfolders with a priority for specific resolution folders
            resolution_folders = []
            other_folders = []

            for key, value in folder_data.items():
                if isinstance(key, str) and key.startswith('/') and isinstance(value, dict):
                    folder_name = os.path.basename(key.rstrip('/'))
                    # Prioritize resolution folders
                    if any(res in folder_name.lower() for res in ['1500px', 'hi-res', '640px']):
                        resolution_folders.append((key, value))
                    else:
                        other_folders.append((key, value))

            # Check resolution folders first
            for key, subfolder in resolution_folders:
                result.extend(extract_images_from_folder(subfolder, f"{prefix}{os.path.basename(key)}/"))

            # If no images found in resolution folders, check other folders
            if not result and other_folders:
                for key, subfolder in other_folders:
                    result.extend(extract_images_from_folder(subfolder, f"{prefix}{os.path.basename(key)}/"))

            return result

        # Extract images from the current folder and its subfolders
        images = extract_images_from_folder(current)

        # APPROACH 3: Final fallback - if still no images found, search entire temp_links
        if not images and 'temp_links' in dropbox_map:
            search_prefix = f"{normalized_folder_path}/"

            for path, link in dropbox_map['temp_links'].items():
                path_lower = path.lower()
                if path_lower.startswith(search_prefix) and any(path_lower.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                    # Handle both old format (string URL) and new format (dict with thumbnail/full)
                    if isinstance(link, dict):
                        images.append({
                            'name': os.path.basename(path),
                            'path': path,
                            'thumbnail_url': link.get('thumbnail'),
                            'url': link.get('full') or link.get('thumbnail'),
                        })
                    else:
                        images.append({
                            'name': os.path.basename(path),
                            'path': path,
                            'thumbnail_url': link,
                            'url': link
                        })

        # Sort images by name for consistent ordering
        images.sort(key=lambda x: x.get('name', ''))

        print(f"Found {len(images)} images in folder {folder_path}")
        return {"images": images}

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"error": f"Error getting Dropbox images: {str(e)}"}
        )

@router.get("/api/dropbox/init", response_class=JSONResponse)
async def init_dropbox_scan(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings)
):
    """Initialize Dropbox scan in the background and report progress"""

    # Check if already scanning
    if hasattr(request.app.state, 'dropbox_scan_in_progress') and request.app.state.dropbox_scan_in_progress:
        # Get progress if available
        progress = getattr(request.app.state, 'dropbox_scan_progress', {'status': 'scanning', 'progress': 0})
        return JSONResponse(content=progress)

    # Check if already scanned
    if hasattr(request.app.state, 'dropbox_map') and request.app.state.dropbox_map:
        return JSONResponse(content={
            'status': 'complete',
            'last_updated': request.app.state.dropbox_last_updated.isoformat()
        })

    # Start scan in background
    request.app.state.dropbox_scan_in_progress = True
    request.app.state.dropbox_scan_progress = {'status': 'starting', 'progress': 0}

    background_tasks.add_task(perform_dropbox_scan, request.app, settings.DROPBOX_ACCESS_TOKEN)

    return JSONResponse(content={
        'status': 'started',
        'message': 'Dropbox scan initiated in background'
    })

@router.get("/api/dropbox/debug-scan")
async def debug_dropbox_scan(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings)
):
    """Debug endpoint to trigger Dropbox scan"""
    # Reset scan state
    request.app.state.dropbox_scan_in_progress = False

    # Check token
    token = settings.DROPBOX_ACCESS_TOKEN
    if not token:
        return {"status": "error", "message": "No Dropbox access token configured"}

    # Start scan
    print(f"Manually starting Dropbox scan with token (length: {len(token)})")
    request.app.state.dropbox_scan_in_progress = True
    request.app.state.dropbox_scan_progress = {'status': 'starting', 'progress': 0}

    # Add to background tasks
    background_tasks.add_task(perform_dropbox_scan, request.app, token)

    return {
        "status": "started",
        "message": "Dropbox scan initiated in background",
        "token_available": bool(token)
    }

@router.get("/api/dropbox/debug-token")
async def debug_dropbox_token(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings)
):
    """Debug endpoint to check Dropbox tokens and refresh if needed"""
    try:
        # Get tokens from settings and environment
        access_token = getattr(settings, 'DROPBOX_ACCESS_TOKEN', None) or os.environ.get('DROPBOX_ACCESS_TOKEN')
        refresh_token = getattr(settings, 'DROPBOX_REFRESH_TOKEN', None) or os.environ.get('DROPBOX_REFRESH_TOKEN')
        app_key = getattr(settings, 'DROPBOX_APP_KEY', None) or os.environ.get('DROPBOX_APP_KEY')
        app_secret = getattr(settings, 'DROPBOX_APP_SECRET', None) or os.environ.get('DROPBOX_APP_SECRET')

        # Create detailed response with token info
        response = {
            "access_token": {
                "available": bool(access_token),
                "preview": f"{access_token[:5]}...{access_token[-5:]}" if access_token and len(access_token) > 10 else None,
                "length": len(access_token) if access_token else 0,
                "source": "settings" if hasattr(settings, 'DROPBOX_ACCESS_TOKEN') and settings.DROPBOX_ACCESS_TOKEN else "environment" if access_token else None
            },
            "refresh_token": {
                "available": bool(refresh_token),
                "preview": f"{refresh_token[:5]}...{refresh_token[-5:]}" if refresh_token and len(refresh_token) > 10 else None,
                "length": len(refresh_token) if refresh_token else 0,
                "source": "settings" if hasattr(settings, 'DROPBOX_REFRESH_TOKEN') and settings.DROPBOX_REFRESH_TOKEN else "environment" if refresh_token else None
            },
            "app_credentials": {
                "app_key_available": bool(app_key),
                "app_secret_available": bool(app_secret),
                "source": "settings" if hasattr(settings, 'DROPBOX_APP_KEY') and settings.DROPBOX_APP_KEY else "environment" if app_key else None
            }
        }

        # Test current access token if available
        if access_token:
            from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
            client = AsyncDropboxClient(access_token=access_token)
            test_result = await client.test_connection()
            response["token_status"] = "valid" if test_result else "invalid"
        else:
            response["token_status"] = "missing"

        # Try to refresh token if invalid and we have refresh credentials
        if (response["token_status"] in ["invalid", "missing"] and
            refresh_token and app_key and app_secret):

            print("Attempting to refresh token...")
            from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
            refresh_client = AsyncDropboxClient(
                refresh_token=refresh_token,
                app_key=app_key,
                app_secret=app_secret
            )

            refresh_success = await refresh_client.refresh_access_token()

            if refresh_success:
                # We got a new token
                new_token = refresh_client.access_token

                # Save it to use in future requests
                if hasattr(request.app.state, 'settings'):
                    request.app.state.settings.DROPBOX_ACCESS_TOKEN = new_token

                # Update environment variable
                os.environ["DROPBOX_ACCESS_TOKEN"] = new_token

                # Start background scan with new token
                request.app.state.dropbox_scan_in_progress = True
                request.app.state.dropbox_scan_progress = {'status': 'starting', 'progress': 0}
                background_tasks.add_task(perform_dropbox_scan, request.app, new_token)

                response["refresh_result"] = {
                    "success": True,
                    "new_token_preview": f"{new_token[:5]}...{new_token[-5:]}",
                    "new_token_length": len(new_token),
                    "scan_initiated": True
                }
            else:
                response["refresh_result"] = {
                    "success": False,
                    "error": "Failed to refresh token"
                }

        return response
    except Exception as e:
        import traceback
        print(f"Debug token error: {str(e)}")
        print(traceback.format_exc())
        return {
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__
        }

@router.get("/api/dropbox/direct-scan")
async def direct_dropbox_scan(
    request: Request,
    settings: Settings = Depends(get_settings)
):
    """
    Direct scan endpoint for debugging - attempts to scan a folder directly
    without using background tasks for immediate feedback
    """
    try:
        from app.services.dropbox.dropbox_async_service import AsyncDropboxClient

        # Get tokens from settings and environment
        access_token = getattr(settings, 'DROPBOX_ACCESS_TOKEN', None) or os.environ.get('DROPBOX_ACCESS_TOKEN')
        refresh_token = getattr(settings, 'DROPBOX_REFRESH_TOKEN', None) or os.environ.get('DROPBOX_REFRESH_TOKEN')
        app_key = getattr(settings, 'DROPBOX_APP_KEY', None) or os.environ.get('DROPBOX_APP_KEY')
        app_secret = getattr(settings, 'DROPBOX_APP_SECRET', None) or os.environ.get('DROPBOX_APP_SECRET')

        if not access_token and not refresh_token:
            return {
                "status": "error",
                "message": "No Dropbox access token or refresh token configured"
            }

        # Create the client with all credentials
        client = AsyncDropboxClient(
            access_token=access_token,
            refresh_token=refresh_token,
            app_key=app_key,
            app_secret=app_secret
        )

        # Try to refresh token if we have refresh credentials but no access token
        if refresh_token and app_key and app_secret and not access_token:
            print("Attempting to refresh token before direct scan...")
            refresh_success = await client.refresh_access_token()
            if refresh_success:
                # We got a new token
                access_token = client.access_token
                # Update in app state if settings exist
                if hasattr(request.app.state, 'settings'):
                    request.app.state.settings.DROPBOX_ACCESS_TOKEN = access_token
                # Update in environment
                os.environ['DROPBOX_ACCESS_TOKEN'] = access_token
                print("Successfully refreshed access token for direct scan")
            else:
                return {
                    "status": "error",
                    "message": "Failed to refresh access token"
                }

        # Test connection first
        test_result = await client.test_connection()
        if not test_result:
            return {
                "status": "error",
                "message": "Failed to connect to Dropbox API - invalid token"
            }

        # Start scan of top-level folders for quick test
        print("Starting direct scan of top-level folders...")

        # Just list top folders with max_depth=1 for quicker results
        entries = await client.list_folder_recursive(path="", max_depth=1)

        # Collect folder information
        folders = []
        files = []

        for entry in entries:
            entry_type = entry.get('.tag', '')
            path = entry.get('path_lower', '')
            name = os.path.basename(path)

            if entry_type == 'folder':
                folders.append({
                    "name": name,
                    "path": path
                })
            elif entry_type == 'file' and client._is_image_file(path):
                files.append({
                    "name": name,
                    "path": path,
                    "size": entry.get('size', 0),
                })

        # Get a sample of temp links for quick testing (max 5 files)
        sample_files = files[:5]
        temp_links = {}

        if sample_files:
            sample_paths = [f['path'] for f in sample_files]
            temp_links = await client.get_temporary_links_async(sample_paths)

        return {
            "status": "success",
            "message": f"Directly scanned {len(folders)} top-level folders and {len(files)} files",
            "folders": folders[:10],  # Limit to first 10
            "files": files[:10],      # Limit to first 10
            "temp_links_sample": len(temp_links),
            "token_refreshed": access_token != getattr(settings, 'DROPBOX_ACCESS_TOKEN', None)
        }

    except Exception as e:
        import traceback
        traceback_str = traceback.format_exc()
        print(f"Error in direct scan: {str(e)}")
        print(traceback_str)
        return {
            "status": "error",
            "message": f"Error in direct scan: {str(e)}",
            "traceback": traceback_str.split("\n")[-10:] if len(traceback_str) > 0 else []
        }

@router.get("/api/dropbox/sync-status")
async def get_dropbox_sync_status(request: Request):
    """Get current Dropbox sync status and statistics"""
    try:
        from app.services.dropbox.scheduled_sync import DropboxSyncScheduler

        if not hasattr(request.app.state, 'dropbox_scheduler'):
            request.app.state.dropbox_scheduler = DropboxSyncScheduler(request.app.state)

        scheduler = request.app.state.dropbox_scheduler
        return scheduler.get_sync_status()
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/api/dropbox/sync-now")
async def trigger_dropbox_sync(
    request: Request,
    force: bool = False,
    background_tasks: BackgroundTasks = None
):
    """Manually trigger a Dropbox sync"""
    try:
        from app.services.dropbox.scheduled_sync import DropboxSyncScheduler

        if not hasattr(request.app.state, 'dropbox_scheduler'):
            request.app.state.dropbox_scheduler = DropboxSyncScheduler(request.app.state)

        scheduler = request.app.state.dropbox_scheduler

        # Run sync in background
        if background_tasks:
            background_tasks.add_task(scheduler.full_sync, force=force)
            return {
                "status": "started",
                "message": "Sync started in background"
            }
        else:
            # Run sync directly
            result = await scheduler.full_sync(force=force)
            return result

    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/api/dropbox/refresh-token")
async def force_refresh_dropbox_token(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings)
):
    """Force refresh of the Dropbox access token using refresh token"""
    try:
        # Get refresh credentials
        refresh_token = getattr(settings, 'DROPBOX_REFRESH_TOKEN', None) or os.environ.get('DROPBOX_REFRESH_TOKEN')
        app_key = getattr(settings, 'DROPBOX_APP_KEY', None) or os.environ.get('DROPBOX_APP_KEY')
        app_secret = getattr(settings, 'DROPBOX_APP_SECRET', None) or os.environ.get('DROPBOX_APP_SECRET')

        if not refresh_token or not app_key or not app_secret:
            return {
                "status": "error",
                "message": "Missing required refresh credentials",
                "refresh_token_available": bool(refresh_token),
                "app_key_available": bool(app_key),
                "app_secret_available": bool(app_secret)
            }

        # Create client for token refresh
        from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
        client = AsyncDropboxClient(
            refresh_token=refresh_token,
            app_key=app_key,
            app_secret=app_secret
        )

        # Attempt to refresh the token
        print("Forcing Dropbox token refresh...")
        refresh_success = await client.refresh_access_token()

        if refresh_success:
            # We got a new token
            new_token = client.access_token

            # Update in app state if settings exist
            if hasattr(request.app.state, 'settings'):
                request.app.state.settings.DROPBOX_ACCESS_TOKEN = new_token

            # Update in environment
            os.environ['DROPBOX_ACCESS_TOKEN'] = new_token

            # Start background scan with new token if requested
            start_scan = request.query_params.get('start_scan', 'false').lower() == 'true'
            if start_scan:
                request.app.state.dropbox_scan_in_progress = True
                request.app.state.dropbox_scan_progress = {'status': 'starting', 'progress': 0}
                background_tasks.add_task(perform_dropbox_scan, request.app, new_token)

            return {
                "status": "success",
                "message": "Successfully refreshed access token",
                "new_token_preview": f"{new_token[:5]}...{new_token[-5:]}",
                "new_token_length": len(new_token),
                "scan_initiated": start_scan
            }
        else:
            return {
                "status": "error",
                "message": "Failed to refresh access token",
                "refresh_token_preview": f"{refresh_token[:5]}...{refresh_token[-5:]}" if len(refresh_token) > 10 else None
            }

    except Exception as e:
        import traceback
        print(f"Error in token refresh: {str(e)}")
        print(traceback.format_exc())
        return {
            "status": "error",
            "message": f"Exception during token refresh: {str(e)}",
            "error_type": type(e).__name__
        }

@router.get("/api/dropbox/test-credentials", response_class=JSONResponse)
async def test_dropbox_credentials(
    settings: Settings = Depends(get_settings)
):
    """Test that Dropbox credentials are being loaded correctly"""
    return {
        "app_key_available": bool(settings.DROPBOX_APP_KEY),
        "app_secret_available": bool(settings.DROPBOX_APP_SECRET),
        "refresh_token_available": bool(settings.DROPBOX_REFRESH_TOKEN),
        "access_token_available": bool(settings.DROPBOX_ACCESS_TOKEN),
        "app_key_preview": settings.DROPBOX_APP_KEY[:5] + "..." if settings.DROPBOX_APP_KEY else None,
        "refresh_token_preview": settings.DROPBOX_REFRESH_TOKEN[:5] + "..." if settings.DROPBOX_REFRESH_TOKEN else None
    }

@router.get("/api/dropbox/debug-cache")
async def debug_dropbox_cache(request: Request):
    """Debug endpoint to see what's in the Dropbox cache"""
    dropbox_map = getattr(request.app.state, 'dropbox_map', None)

    if not dropbox_map:
        return {"status": "no_cache", "message": "No Dropbox cache found"}

    # Count temporary links
    temp_links_count = len(dropbox_map.get('temp_links', {}))

    # Get some sample paths with temporary links
    sample_links = {}
    for i, (path, link) in enumerate(dropbox_map.get('temp_links', {}).items()):
        if i >= 5:  # Just get 5 samples
            break
        sample_links[path] = link[:50] + "..." if link else None

    return {
        "status": "ok",
        "last_updated": getattr(request.app.state, 'dropbox_last_updated', None),
        "has_folder_structure": "folder_structure" in dropbox_map,
        "temp_links_count": temp_links_count,
        "sample_links": sample_links,
        "sample_folder_paths": list(dropbox_map.get('folder_structure', {}).keys())[:5]
    }

@router.get("/api/dropbox/debug-credentials")
async def debug_dropbox_credentials(
    settings: Settings = Depends(get_settings)
):
    """Debug endpoint to check how credentials are loaded"""

    # Check settings first
    settings_creds = {
        "settings_access_token": bool(getattr(settings, 'DROPBOX_ACCESS_TOKEN', None)),
        "settings_refresh_token": bool(getattr(settings, 'DROPBOX_REFRESH_TOKEN', None)),
        "settings_app_key": bool(getattr(settings, 'DROPBOX_APP_KEY', None)),
        "settings_app_secret": bool(getattr(settings, 'DROPBOX_APP_SECRET', None))
    }

    # Check environment variables directly
    env_creds = {
        "env_access_token": bool(os.environ.get('DROPBOX_ACCESS_TOKEN')),
        "env_refresh_token": bool(os.environ.get('DROPBOX_REFRESH_TOKEN')),
        "env_app_key": bool(os.environ.get('DROPBOX_APP_KEY')),
        "env_app_secret": bool(os.environ.get('DROPBOX_APP_SECRET'))
    }

    # Sample values (first 5 chars only)
    samples = {
        "access_token_sample": os.environ.get('DROPBOX_ACCESS_TOKEN', '')[:5] + "..." if os.environ.get('DROPBOX_ACCESS_TOKEN') else None,
        "refresh_token_sample": os.environ.get('DROPBOX_REFRESH_TOKEN', '')[:5] + "..." if os.environ.get('DROPBOX_REFRESH_TOKEN') else None
    }

    return {
        "settings_loaded": settings_creds,
        "environment_loaded": env_creds,
        "samples": samples
    }

@router.get("/api/dropbox/debug-folder-images")
async def debug_folder_images(
    request: Request,
    folder_path: str
):
    """Debug endpoint to check what images exist for a specific folder"""
    dropbox_map = getattr(request.app.state, 'dropbox_map', None)

    if not dropbox_map:
        return {"status": "no_cache", "message": "No Dropbox cache found"}

    # Count all temporary links
    all_temp_links = dropbox_map.get('temp_links', {})

    # Find images in this folder from temp_links
    folder_images = []
    for path, link in all_temp_links.items():
        normalized_path = path.lower()
        normalized_folder = folder_path.lower()

        # Check if this path is in the requested folder
        if normalized_path.startswith(normalized_folder + '/') or normalized_path == normalized_folder:
            if any(path.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                folder_images.append({
                    'path': path,
                    'link': link[:50] + "..." if link else None
                })

    # Get folder structure info
    folder_structure = dropbox_map.get('folder_structure', {})
    current = folder_structure

    # Try to navigate to the folder (if it exists in structure)
    path_parts = folder_path.strip('/').split('/')
    current_path = ""
    for part in path_parts:
        if not part:
            continue
        current_path = f"/{part}" if current_path == "" else f"{current_path}/{part}"
        if current_path in current:
            current = current[current_path]
        else:
            current = None
            break

    return {
        "status": "ok",
        "folder_path": folder_path,
        "folder_exists_in_structure": current is not None,
        "folder_structure_details": current if isinstance(current, dict) and len(str(current)) < 1000 else "(too large to display)",
        "images_found_in_temp_links": len(folder_images),
        "sample_images": folder_images[:5]
    }

@router.get("/api/dropbox/generate-links", response_class=JSONResponse)
async def generate_folder_links(
    request: Request,
    folder_path: str,
    settings: Settings = Depends(get_settings)
):
    """
    Generate thumbnails for all images in a specific folder.

    Uses the Dropbox thumbnail API to fetch small base64 thumbnails (~12KB each)
    instead of full temporary links. This is MUCH faster and uses less bandwidth.
    Full-res links are fetched on-demand when user selects an image.
    """
    try:
        # Use shared client with token persistence
        client = await get_dropbox_client(request, settings)

        # Get the folder structure from cache if available
        dropbox_map = getattr(request.app.state, 'dropbox_map', None)
        if not dropbox_map:
            return {"status": "error", "message": "No Dropbox cache available"}

        # First, list the folder to get image paths
        import aiohttp
        async with aiohttp.ClientSession() as session:
            # List folder contents
            entries = await client.list_folder(folder_path)

            # Filter for images
            image_paths = []
            for entry in entries:
                if entry.get('.tag') == 'file':
                    path = entry.get('path_lower', '')
                    if any(path.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                        image_paths.append(path)

            print(f"Found {len(image_paths)} images in folder {folder_path}")

            if not image_paths:
                return {
                    "status": "success",
                    "message": "No images found in folder",
                    "images": []
                }

            # Get thumbnails for all images (FAST - ~12KB each vs ~600KB for full-res)
            # Run ALL thumbnail fetches in parallel for speed
            thumbnails = {}

            # Create all tasks at once
            tasks = [client.get_image_links_with_thumbnails(session, path) for path in image_paths]

            # Run all in parallel (Dropbox API can handle concurrent requests)
            print(f"Fetching {len(tasks)} thumbnails in parallel...")
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    continue  # Skip failed fetches
                path, links = result
                if links.get('thumbnail'):
                    thumbnails[path] = links

            print(f"Generated {len(thumbnails)} thumbnails for folder {folder_path}")

            # Update the cache with thumbnails
            if dropbox_map and 'temp_links' in dropbox_map:
                dropbox_map['temp_links'].update(thumbnails)
                print(f"Updated cache with {len(thumbnails)} thumbnails")

            # Return images with thumbnail data URLs for UI
            images = []
            for path, links in thumbnails.items():
                images.append({
                    'name': os.path.basename(path),
                    'path': path,
                    'url': links.get('thumbnail'),  # Base64 data URL for display
                    'thumbnail_url': links.get('thumbnail'),
                    'full_url': None  # Will be fetched on-demand
                })

            return {
                "status": "success",
                "message": f"Generated {len(thumbnails)} thumbnails",
                "images": images
            }

    except Exception as e:
        import traceback
        print(f"Error generating thumbnails: {str(e)}")
        print(traceback.format_exc())
        return {
            "status": "error",
            "message": f"Error generating thumbnails: {str(e)}"
        }


@router.get("/api/dropbox/full-res-link", response_class=JSONResponse)
async def get_dropbox_full_res_link(
    request: Request,
    file_path: str,
    settings: Settings = Depends(get_settings)
):
    """
    Get a full-resolution temporary link for a single image.
    Called on-demand when user selects/clicks an image.

    This is the "lazy fetch" approach - thumbnails are shown in browser,
    full-res is only fetched when actually needed.
    """
    try:
        # Use shared client with token persistence
        client = await get_dropbox_client(request, settings)

        # Get full-res link for this specific file
        full_link = await client.get_full_res_link(file_path)

        if full_link:
            return {
                "status": "success",
                "path": file_path,
                "url": full_link
            }
        else:
            return {
                "status": "error",
                "message": f"Could not get link for {file_path}"
            }

    except Exception as e:
        import traceback
        logger.error(f"Error getting full-res link: {str(e)}")
        logger.error(traceback.format_exc())
        return {
            "status": "error",
            "message": f"Error: {str(e)}"
        }


async def perform_dropbox_scan(app, access_token=None):
    """Background task to scan Dropbox with token refresh support"""
    try:
        print("Starting Dropbox scan background task...")

        # Mark scan as in progress
        app.state.dropbox_scan_in_progress = True
        app.state.dropbox_scan_progress = {'status': 'scanning', 'progress': 0}

        # Get tokens and credentials from settings
        settings = getattr(app.state, 'settings', None)

        # Fallback to environment variables if settings not available
        if settings:
            refresh_token = getattr(settings, 'DROPBOX_REFRESH_TOKEN', None)
            app_key = getattr(settings, 'DROPBOX_APP_KEY', None)
            app_secret = getattr(settings, 'DROPBOX_APP_SECRET', None)
        else:
            # Get from environment
            refresh_token = os.environ.get('DROPBOX_REFRESH_TOKEN')
            app_key = os.environ.get('DROPBOX_APP_KEY')
            app_secret = os.environ.get('DROPBOX_APP_SECRET')

        print(f"Access token available: {bool(access_token)}")
        print(f"Refresh token available: {bool(refresh_token)}{' (starts with: ' + refresh_token[:5] + '...)' if refresh_token else ''}")
        print(f"App key available: {bool(app_key)}{' (starts with: ' + app_key[:5] + '...)' if app_key else ''}")
        print(f"App secret available: {bool(app_secret)}{' (starts with: ' + app_secret[:5] + '...)' if app_secret else ''}")

        if not access_token and not refresh_token:
            print("ERROR: No access token or refresh token provided")
            app.state.dropbox_scan_progress = {'status': 'error', 'message': 'No token available', 'progress': 0}
            app.state.dropbox_scan_in_progress = False
            return

        # Create the async client
        print("Creating client instance...")

        # Initialize with all available credentials
        from app.services.dropbox.dropbox_async_service import AsyncDropboxClient
        client = AsyncDropboxClient(
            access_token=access_token,
            refresh_token=refresh_token,
            app_key=app_key,
            app_secret=app_secret
        )

        # Try to refresh token first if we have refresh credentials
        if refresh_token and app_key and app_secret:
            print("Attempting to refresh token before scan...")
            try:
                refresh_success = await client.refresh_access_token()
                if refresh_success:
                    print("Successfully refreshed access token")
                    # Save the new token
                    access_token = client.access_token
                    # Update in environment
                    os.environ['DROPBOX_ACCESS_TOKEN'] = access_token
                    # Update in app state if settings exist
                    if hasattr(app.state, 'settings'):
                        app.state.settings.DROPBOX_ACCESS_TOKEN = access_token
                else:
                    print("Failed to refresh access token")
                    app.state.dropbox_scan_progress = {
                        'status': 'error',
                        'message': 'Failed to refresh access token',
                        'progress': 0
                    }
                    app.state.dropbox_scan_in_progress = False
                    return
            except Exception as refresh_error:
                print(f"Error refreshing token: {str(refresh_error)}")
                app.state.dropbox_scan_progress = {
                    'status': 'error',
                    'message': f'Error refreshing token: {str(refresh_error)}',
                    'progress': 0
                }
                app.state.dropbox_scan_in_progress = False
                return

        # Try a simple operation first to test the token
        print("Testing connection...")
        test_result = await client.test_connection()
        if not test_result:
            print("ERROR: Could not connect to Dropbox API")
            app.state.dropbox_scan_progress = {
                'status': 'error',
                'message': 'Could not connect to Dropbox API',
                'progress': 0
            }
            app.state.dropbox_scan_in_progress = False
            return

        print("Connection successful, starting full scan...")
        app.state.dropbox_scan_progress = {'status': 'scanning', 'progress': 10}

        # Perform the scan with cache support
        dropbox_map = await client.scan_and_map_folder()

        # Store results
        print("Scan complete, saving results...")
        app.state.dropbox_map = dropbox_map
        app.state.dropbox_last_updated = datetime.now()
        app.state.dropbox_scan_progress = {'status': 'complete', 'progress': 100}

        # If we got a new token via refresh, store it
        if client.access_token != access_token:
            # Update in environment
            os.environ['DROPBOX_ACCESS_TOKEN'] = client.access_token
            # Update in app state if settings exist
            if hasattr(app.state, 'settings'):
                app.state.settings.DROPBOX_ACCESS_TOKEN = client.access_token
            print("Updated access token from refresh")

        print(f"Dropbox background scan completed successfully. Mapped {len(dropbox_map.get('all_entries', []))} entries and {len(dropbox_map.get('temp_links', {}))} temporary links.")
    except Exception as e:
        print(f"ERROR in Dropbox scan: {str(e)}")
        import traceback
        print(traceback.format_exc())
        app.state.dropbox_scan_progress = {'status': 'error', 'message': f"Error: {str(e)}", 'progress': 0}
    finally:
        app.state.dropbox_scan_in_progress = False
        print("Background scan task finished")
