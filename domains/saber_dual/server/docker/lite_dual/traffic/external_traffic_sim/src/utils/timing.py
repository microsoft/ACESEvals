"""
External Traffic Simulator - Timing Utilities

Timing utilities specific to external traffic patterns.
"""

import random
import asyncio
import time
from typing import Optional

try:
    from ..config.patterns import EXTERNAL_PATTERNS
except ImportError:
    # Fallback for direct execution
    import sys
    import os
    sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
    from config.patterns import EXTERNAL_PATTERNS


class BaseTimingUtils:
    """Base timing utilities"""
    
    @staticmethod
    def randomize_interval(base_interval: float, variance_percent: float) -> float:
        """
        Randomize an interval with percentage variance
        
        Args:
            base_interval: Base interval in seconds
            variance_percent: Variance as a percentage (0.2 = 20%)
            
        Returns:
            Randomized interval
        """
        variance = base_interval * variance_percent
        return random.uniform(
            base_interval - variance,
            base_interval + variance
        )
    
    @staticmethod
    async def wait_with_jitter(interval: float) -> None:
        """Wait for an interval with small random jitter"""
        jitter = random.uniform(-0.1, 0.1)  # ±0.1 second jitter
        wait_time = max(0, interval + jitter)
        await asyncio.sleep(wait_time)


class PatternScheduler:
    """Basic pattern scheduler"""
    
    def __init__(self, simulation_duration: int):
        self.simulation_duration = simulation_duration
        self.start_time = None
        self.running = False
    
    def start(self):
        """Start the scheduler"""
        self.start_time = time.time()
        self.running = True
    
    def stop(self):
        """Stop the scheduler"""
        self.running = False
    
    def is_running(self) -> bool:
        """Check if scheduler is running (runs indefinitely until stopped)"""
        return self.running and self.start_time is not None
    
    def get_statistics(self) -> dict:
        """Get scheduler statistics"""
        if self.start_time is None:
            return {"status": "not_started"}
        
        elapsed = time.time() - self.start_time
        return {
            "status": "running" if self.is_running() else "stopped",
            "elapsed_seconds": elapsed,
            "remaining_seconds": max(0, self.simulation_duration - elapsed)
        }


class ExternalTimingUtils(BaseTimingUtils):
    """Extended timing utilities for external traffic patterns"""
    
    @staticmethod
    def get_pattern_interval(pattern_name: str) -> float:
        """
        Get randomized interval for a specific external pattern
        
        Args:
            pattern_name: Name of the pattern (from EXTERNAL_PATTERNS)
            
        Returns:
            Randomized interval in seconds
        """
        if pattern_name not in EXTERNAL_PATTERNS:
            return ExternalTimingUtils.randomize_interval(60, 0.2)  # Default
        
        config = EXTERNAL_PATTERNS[pattern_name]
        return ExternalTimingUtils.randomize_interval(
            config.base_interval, 
            config.variance_percent
        )
    
    @staticmethod
    def get_crown_jewel_access_delay() -> float:
        """Get delay before accessing crown jewel during compliance audit"""
        return random.uniform(5, 15)  # 5-15 seconds into audit session
    
    @staticmethod
    def get_maintenance_sequence_delay() -> float:
        """Get delay between maintenance operations"""
        return random.uniform(2, 8)  # 2-8 seconds between operations
    
    @staticmethod
    def get_employee_login_delay() -> float:
        """Get delay for employee login sequence"""
        return random.uniform(1, 3)  # 1-3 seconds for form submission
    
    @staticmethod
    def get_startup_delay() -> float:
        """Get randomized startup delay to stagger container starts"""
        import os
        min_delay = int(os.getenv('STARTUP_DELAY_MIN', '1'))
        max_delay = int(os.getenv('STARTUP_DELAY_MAX', '5'))
        return random.uniform(min_delay, max_delay)
    
    @staticmethod
    async def wait_for_pattern_interval(pattern_name: str):
        """Wait for the appropriate interval for a pattern"""
        interval = ExternalTimingUtils.get_pattern_interval(pattern_name)
        await asyncio.sleep(interval)
    
    @staticmethod
    async def wait_with_jitter(base_seconds: float, jitter_percent: float = 0.1):
        """Wait with small random jitter"""
        jitter = base_seconds * jitter_percent
        wait_time = base_seconds + random.uniform(-jitter, jitter)
        await asyncio.sleep(max(0, wait_time))


class ExternalPatternScheduler(PatternScheduler):
    """Specialized scheduler for external traffic patterns"""
    
    def __init__(self, simulation_duration: int = 300):
        super().__init__(simulation_duration)
        self.pattern_iterations = {}
    
    def record_pattern_iteration(self, pattern_name: str):
        """Record that a pattern completed an iteration"""
        if pattern_name not in self.pattern_iterations:
            self.pattern_iterations[pattern_name] = 0
        self.pattern_iterations[pattern_name] += 1
    
    def get_pattern_iteration_count(self, pattern_name: str) -> int:
        """Get the number of completed iterations for a pattern"""
        return self.pattern_iterations.get(pattern_name, 0)
    
    def should_continue_pattern(self, pattern_name: str) -> bool:
        """Check if a pattern should continue running"""
        if not self.is_running():
            return False
        
        config = EXTERNAL_PATTERNS.get(pattern_name)
        if not config or not config.enabled:
            return False
        
        # Check max iterations limit
        if config.max_iterations > 0:
            current_iterations = self.get_pattern_iteration_count(pattern_name)
            if current_iterations >= config.max_iterations:
                return False
        
        return True
    
    def get_elapsed_time(self) -> float:
        """Get elapsed time since simulation start"""
        if self.start_time is None:
            return 0
        return time.time() - self.start_time
    
    def get_remaining_time(self) -> float:
        """Get remaining time in simulation (returns large number for indefinite mode)"""
        return float('inf')  # Indefinite duration
    
    def get_statistics(self) -> dict:
        """Get simulation statistics"""
        return {
            "elapsed_time": self.get_elapsed_time(),
            "remaining_time": self.get_remaining_time(),
            "pattern_iterations": self.pattern_iterations.copy(),
            "total_iterations": sum(self.pattern_iterations.values()),
            "is_running": self.is_running()
        }