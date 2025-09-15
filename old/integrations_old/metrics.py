"""
Purpose: Provides tools for monitoring the performance and reliability of platform interactions.
Contents:
Data structures (MetricPoint, PlatformMetrics) to hold metric data (like update times, error counts) per platform.
MetricsCollector: A central class to record metrics (update duration, queue length, errors, sync success/failure) 
and calculate statistics (averages, P95, success rates) over a defined time window. Uses asyncio.Lock for safe concurrent updates.
MetricsContext: An async context manager (async with ...) to easily measure the duration of operations and record success/failure, 
simplifying metric collection within the update logic.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta, timezone
from typing import Dict, List, Optional
from collections import defaultdict

import statistics
import asyncio
import time

@dataclass
class MetricPoint:
    """A single measurement at a point in time"""
    timestamp: datetime
    value: float

@dataclass
class PlatformMetrics:
    """Tracks metrics for a specific platform"""
    update_times: List[MetricPoint] = field(default_factory=list)
    error_count: int = 0
    successful_updates: int = 0
    failed_updates: int = 0
    last_sync_time: Optional[datetime] = None


class MetricsCollector:
    def __init__(self, window_size: timedelta = timedelta(hours=24)):
        """Initialize the metrics collector with a specified time window"""
        self.window_size = window_size
        self.platform_metrics: Dict[str, PlatformMetrics] = defaultdict(PlatformMetrics)
        self.queue_length_history: List[MetricPoint] = []
        self._lock = asyncio.Lock()
    
    async def record_update_time(self, platform: str, duration: float):
        """Record the duration of an update operation for a platform"""
        async with self._lock:
            metric = MetricPoint(timestamp=datetime.now(), value=duration)
            self.platform_metrics[platform].update_times.append(metric)
            self._cleanup_old_metrics(platform)
    
    async def record_queue_length(self, length: int):
        """Record the current queue length"""
        async with self._lock:
            metric = MetricPoint(timestamp=datetime.now(), value=length)
            self.queue_length_history.append(metric)
            self._cleanup_old_queue_metrics()
    
    async def record_error(self, platform: str):
        """Record an error occurrence for a platform"""
        async with self._lock:
            self.platform_metrics[platform].error_count += 1
    
    async def record_sync_status(self, platform: str, success: bool):
        """Record the success/failure status of a sync operation"""
        async with self._lock:
            metrics = self.platform_metrics[platform]
            metrics.last_sync_time = datetime.now()
            if success:
                metrics.successful_updates += 1
            else:
                metrics.failed_updates += 1
    
    def _cleanup_old_metrics(self, platform: str):
        """Remove metrics older than the window size for a platform"""
        cutoff = datetime.now() - self.window_size
        metrics = self.platform_metrics[platform]
        metrics.update_times = [
            m for m in metrics.update_times 
            if m.timestamp > cutoff
        ]
    
    def _cleanup_old_queue_metrics(self):
        """Remove queue metrics older than the window size"""
        cutoff = datetime.now() - self.window_size
        self.queue_length_history = [
            m for m in self.queue_length_history 
            if m.timestamp > cutoff
        ]
    
    def get_platform_stats(self, platform: str) -> dict:
        """Get statistics for a specific platform"""
        metrics = self.platform_metrics[platform]
        recent_times = [m.value for m in metrics.update_times]
        
        if not recent_times:
            return {
                "avg_update_time": None,
                "max_update_time": None,
                "p95_update_time": None,
                "error_rate": 0,
                "total_updates": 0,
                "success_rate": 0,
                "last_sync": metrics.last_sync_time
            }
        
        sorted_times = sorted(recent_times)
        p95_index = int(len(sorted_times) * 0.95)
        
        total_updates = metrics.successful_updates + metrics.failed_updates
        success_rate = (metrics.successful_updates / total_updates * 100) if total_updates > 0 else 0
        
        return {
            "avg_update_time": statistics.mean(recent_times),
            "max_update_time": max(recent_times),
            "p95_update_time": sorted_times[p95_index],
            "error_rate": metrics.error_count / len(recent_times) if recent_times else 0,
            "total_updates": total_updates,
            "success_rate": success_rate,
            "last_sync": metrics.last_sync_time
        }
    
    def get_queue_stats(self) -> dict:
        """Get statistics about the queue"""
        if not self.queue_length_history:
            return {
                "avg_length": 0,
                "max_length": 0,
                "current_length": 0
            }
        
        recent_lengths = [m.value for m in self.queue_length_history]
        return {
            "avg_length": statistics.mean(recent_lengths),
            "max_length": max(recent_lengths),
            "current_length": recent_lengths[-1] if recent_lengths else 0
        }

class MetricsContext:
    """Context manager for measuring update operations"""
    def __init__(self, metrics: MetricsCollector, platform: str):
        self.metrics = metrics
        self.platform = platform
        self.start_time = None
    
    async def __aenter__(self):
        self.start_time = time.monotonic()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        duration = time.monotonic() - self.start_time
        await self.metrics.record_update_time(self.platform, duration)
        
        if exc_type is not None:
            await self.metrics.record_error(self.platform)
            await self.metrics.record_sync_status(self.platform, False)
        else:
            await self.metrics.record_sync_status(self.platform, True)