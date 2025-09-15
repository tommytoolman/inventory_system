"""
Scheduled Dropbox synchronization service.

Provides scheduled and on-demand synchronization of Dropbox content
with intelligent caching and incremental updates.
"""

import asyncio
import logging
import json
import os
from datetime import datetime, timedelta, time
from typing import Optional, Dict, Any
from pathlib import Path

from app.services.dropbox.dropbox_async_service import AsyncDropboxClient

logger = logging.getLogger(__name__)


class DropboxSyncScheduler:
    """Manages scheduled and on-demand Dropbox synchronization."""
    
    def __init__(self, app_state):
        """
        Initialize the scheduler.
        
        Args:
            app_state: FastAPI app.state object for storing shared data
        """
        self.app_state = app_state
        self.sync_state_file = Path("app/cache/dropbox/sync_state.json")
        self.sync_state_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Load last sync state
        self.load_sync_state()
        
        # Schedule configuration
        self.daily_sync_time = time(3, 0)  # 3:00 AM
        self.min_sync_interval = timedelta(minutes=5)  # Don't sync more than every 5 minutes
        
    def load_sync_state(self):
        """Load the last sync state from disk."""
        if self.sync_state_file.exists():
            try:
                with open(self.sync_state_file, 'r') as f:
                    state = json.load(f)
                    self.last_sync_time = datetime.fromisoformat(state.get('last_sync_time', '2000-01-01'))
                    self.last_cursor = state.get('last_cursor')
                    self.total_files = state.get('total_files', 0)
                    self.total_images = state.get('total_images', 0)
                    logger.info(f"Loaded sync state: Last sync at {self.last_sync_time}")
            except Exception as e:
                logger.error(f"Error loading sync state: {e}")
                self.reset_sync_state()
        else:
            self.reset_sync_state()
    
    def reset_sync_state(self):
        """Reset sync state to defaults."""
        self.last_sync_time = datetime(2000, 1, 1)
        self.last_cursor = None
        self.total_files = 0
        self.total_images = 0
    
    def save_sync_state(self):
        """Save current sync state to disk."""
        try:
            state = {
                'last_sync_time': self.last_sync_time.isoformat(),
                'last_cursor': self.last_cursor,
                'total_files': self.total_files,
                'total_images': self.total_images,
                'last_updated': datetime.now().isoformat()
            }
            with open(self.sync_state_file, 'w') as f:
                json.dump(state, f, indent=2)
            logger.info("Saved sync state")
        except Exception as e:
            logger.error(f"Error saving sync state: {e}")
    
    async def full_sync(self, force: bool = False) -> Dict[str, Any]:
        """
        Perform a full synchronization of Dropbox content.
        
        Args:
            force: Force sync even if recently synced
            
        Returns:
            Dict with sync results
        """
        # Check if we're already syncing
        if hasattr(self.app_state, 'dropbox_sync_in_progress') and self.app_state.dropbox_sync_in_progress:
            return {
                'status': 'already_running',
                'message': 'Sync already in progress'
            }
        
        # Check minimum interval
        time_since_last = datetime.now() - self.last_sync_time
        if not force and time_since_last < self.min_sync_interval:
            return {
                'status': 'too_soon',
                'message': f'Last sync was {time_since_last.total_seconds():.0f} seconds ago',
                'next_allowed': (self.last_sync_time + self.min_sync_interval).isoformat()
            }
        
        try:
            logger.info("Starting full Dropbox sync...")
            self.app_state.dropbox_sync_in_progress = True
            self.app_state.dropbox_sync_progress = {
                'status': 'syncing',
                'progress': 0,
                'message': 'Initializing...'
            }
            
            # Initialize client
            client = AsyncDropboxClient()
            
            # Test connection first
            if not await client.test_connection():
                # Try to refresh token
                if await client.refresh_access_token():
                    logger.info("Refreshed access token successfully")
                else:
                    raise Exception("Failed to connect to Dropbox")
            
            # Perform the scan
            self.app_state.dropbox_sync_progress['message'] = 'Scanning folders...'
            dropbox_map = await client.scan_and_map_folder()
            
            # Update state
            self.app_state.dropbox_map = dropbox_map
            self.app_state.dropbox_last_updated = datetime.now()
            
            # Update sync state
            self.last_sync_time = datetime.now()
            self.total_files = len(dropbox_map.get('all_entries', []))
            self.total_images = len(dropbox_map.get('temp_links', {}))
            
            # Get cursor for next incremental sync
            # This would need to be implemented in the client
            # self.last_cursor = dropbox_map.get('cursor')
            
            self.save_sync_state()
            
            result = {
                'status': 'success',
                'sync_time': self.last_sync_time.isoformat(),
                'total_files': self.total_files,
                'total_images': self.total_images,
                'duration_seconds': (datetime.now() - self.last_sync_time).total_seconds()
            }
            
            logger.info(f"Full sync completed: {self.total_files} files, {self.total_images} images")
            return result
            
        except Exception as e:
            logger.error(f"Error during full sync: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }
        finally:
            self.app_state.dropbox_sync_in_progress = False
            self.app_state.dropbox_sync_progress = {
                'status': 'idle',
                'progress': 100
            }
    
    async def incremental_sync(self) -> Dict[str, Any]:
        """
        Perform incremental sync using Dropbox cursor.
        Only gets changes since last sync.
        
        Returns:
            Dict with sync results
        """
        if not self.last_cursor:
            logger.info("No cursor available, performing full sync")
            return await self.full_sync()
        
        try:
            logger.info("Starting incremental Dropbox sync...")
            self.app_state.dropbox_sync_in_progress = True
            
            # Initialize client
            client = AsyncDropboxClient()
            
            # Get changes since last cursor
            # This would need to be implemented in the client
            # changes = await client.get_changes_since_cursor(self.last_cursor)
            
            # For now, just do a quick scan
            return await self.full_sync()
            
        except Exception as e:
            logger.error(f"Error during incremental sync: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }
        finally:
            self.app_state.dropbox_sync_in_progress = False
    
    async def run_scheduled_sync(self):
        """
        Background task that runs scheduled synchronization.
        Runs daily at configured time.
        """
        logger.info(f"Starting scheduled sync service (daily at {self.daily_sync_time})")
        
        while True:
            try:
                now = datetime.now()
                
                # Calculate next sync time
                next_sync = datetime.combine(now.date(), self.daily_sync_time)
                if next_sync <= now:
                    # If we've passed today's sync time, schedule for tomorrow
                    next_sync += timedelta(days=1)
                
                # Calculate seconds until next sync
                seconds_until_sync = (next_sync - now).total_seconds()
                
                logger.info(f"Next scheduled sync at {next_sync} ({seconds_until_sync/3600:.1f} hours)")
                
                # Wait until sync time
                await asyncio.sleep(seconds_until_sync)
                
                # Perform the sync
                logger.info("Running scheduled daily sync")
                result = await self.full_sync(force=True)
                logger.info(f"Scheduled sync result: {result}")
                
                # Wait a minute before checking again to avoid double-runs
                await asyncio.sleep(60)
                
            except asyncio.CancelledError:
                logger.info("Scheduled sync service cancelled")
                break
            except Exception as e:
                logger.error(f"Error in scheduled sync loop: {e}")
                # Wait 5 minutes before retrying
                await asyncio.sleep(300)
    
    def get_sync_status(self) -> Dict[str, Any]:
        """
        Get current sync status and statistics.
        
        Returns:
            Dict with sync status information
        """
        time_since_sync = datetime.now() - self.last_sync_time
        
        status = {
            'last_sync': self.last_sync_time.isoformat(),
            'time_since_sync': str(time_since_sync),
            'time_since_sync_seconds': time_since_sync.total_seconds(),
            'total_files': self.total_files,
            'total_images': self.total_images,
            'sync_in_progress': getattr(self.app_state, 'dropbox_sync_in_progress', False),
            'has_cursor': self.last_cursor is not None,
            'next_scheduled_sync': self._get_next_scheduled_time().isoformat()
        }
        
        # Add progress if syncing
        if status['sync_in_progress']:
            status['progress'] = getattr(self.app_state, 'dropbox_sync_progress', {})
        
        return status
    
    def _get_next_scheduled_time(self) -> datetime:
        """Calculate the next scheduled sync time."""
        now = datetime.now()
        next_sync = datetime.combine(now.date(), self.daily_sync_time)
        if next_sync <= now:
            next_sync += timedelta(days=1)
        return next_sync