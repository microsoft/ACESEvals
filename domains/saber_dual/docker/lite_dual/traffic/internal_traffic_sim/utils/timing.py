"""
Internal Traffic Timing Utilities

Provides timing and scheduling utilities for internal service-to-service traffic patterns.
Handles pattern execution scheduling, jitter, and realistic timing distributions.
"""

import asyncio
import random
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional


class InternalTimingUtils:
    """Utility functions for internal traffic timing"""
    
    @staticmethod
    def get_startup_delay(min_delay: int = 5, max_delay: int = 15) -> float:
        """Get startup delay for internal traffic patterns
        
        Args:
            min_delay: Minimum delay in seconds
            max_delay: Maximum delay in seconds
            
        Returns:
            Delay in seconds
        """
        return random.uniform(min_delay, max_delay)
    
    @staticmethod
    def get_pattern_interval(min_interval: int, max_interval: int, jitter_factor: float = 0.1) -> float:
        """Get interval between pattern executions with jitter
        
        Args:
            min_interval: Minimum interval in seconds
            max_interval: Maximum interval in seconds
            jitter_factor: Jitter factor (0.0 to 1.0)
            
        Returns:
            Interval in seconds with jitter applied
        """
        base_interval = random.uniform(min_interval, max_interval)
        jitter = base_interval * jitter_factor * random.uniform(-1, 1)
        return max(1.0, base_interval + jitter)  # Minimum 1 second
    
    @staticmethod
    def should_execute_burst(burst_probability: float = 0.05) -> bool:
        """Determine if a burst execution should occur
        
        Args:
            burst_probability: Probability of burst execution (0.0 to 1.0)
            
        Returns:
            True if burst should execute
        """
        return random.random() < burst_probability
    
    @staticmethod
    def get_burst_interval(base_interval: float, burst_multiplier: float = 3.0) -> float:
        """Get interval for burst execution
        
        Args:
            base_interval: Base interval in seconds
            burst_multiplier: Multiplier for burst timing
            
        Returns:
            Burst interval in seconds
        """
        return base_interval / burst_multiplier
    
    @staticmethod
    def get_inter_request_delay(min_delay: float = 0.1, max_delay: float = 2.0) -> float:
        """Get delay between individual requests in a sequence
        
        Args:
            min_delay: Minimum delay in seconds
            max_delay: Maximum delay in seconds
            
        Returns:
            Delay in seconds
        """
        return random.uniform(min_delay, max_delay)
    
    @staticmethod
    def calculate_realistic_response_time(
        service_type: str,
        operation_type: str,
        base_latency: float = 0.1
    ) -> float:
        """Calculate realistic response time for internal service operations
        
        Args:
            service_type: Type of service (api_gateway, vault_service, database)
            operation_type: Type of operation (health_check, secret_access, etc.)
            base_latency: Base latency in seconds
            
        Returns:
            Simulated response time in seconds
        """
        # Base response times by service type
        service_latencies = {
            'api_gateway': 0.05,
            'vault_service': 0.1,
            'database': 0.15,
            'siem_aggregator': 0.08
        }
        
        # Operation complexity multipliers
        operation_multipliers = {
            'health_check': 0.5,
            'secret_access': 1.2,
            'token_operation': 0.8,
            'database_query': 1.5,
            'log_submission': 0.7,
            'performance_metrics': 1.0
        }
        
        base = service_latencies.get(service_type, base_latency)
        multiplier = operation_multipliers.get(operation_type, 1.0)
        
        # Add random variation
        variation = random.uniform(0.7, 1.3)
        
        return base * multiplier * variation


class InternalPatternScheduler:
    """Scheduler for internal traffic patterns"""
    
    def __init__(self, simulation_duration: int = 300):
        """Initialize the pattern scheduler
        
        Args:
            simulation_duration: Total simulation duration in seconds
        """
        self.simulation_duration = simulation_duration
        self.start_time = None
        self.running = False
        
        # Scheduling statistics
        self.stats = {
            'patterns_started': 0,
            'patterns_completed': 0,
            'total_executions': 0,
            'burst_executions': 0,
            'scheduling_errors': 0
        }
    
    def start(self):
        """Start the scheduler"""
        self.start_time = time.time()
        self.running = True
    
    def stop(self):
        """Stop the scheduler"""
        self.running = False
    
    def is_running(self) -> bool:
        """Check if scheduler is running and within simulation duration
        
        Returns:
            True if scheduler is active and within time limit (or running indefinitely)
        """
        if not self.running or self.start_time is None:
            return False
        
        # If simulation_duration is 0, run indefinitely
        if self.simulation_duration == 0:
            return True
        
        elapsed = time.time() - self.start_time
        return elapsed < self.simulation_duration
    
    def get_elapsed_time(self) -> float:
        """Get elapsed simulation time
        
        Returns:
            Elapsed time in seconds, or 0 if not started
        """
        if self.start_time is None:
            return 0.0
        return time.time() - self.start_time
    
    def get_remaining_time(self) -> float:
        """Get remaining simulation time
        
        Returns:
            Remaining time in seconds, or float('inf') for indefinite duration, or 0 if expired
        """
        if not self.is_running():
            return 0.0
        
        # If simulation_duration is 0, run indefinitely
        if self.simulation_duration == 0:
            return float('inf')
        
        elapsed = self.get_elapsed_time()
        return max(0.0, self.simulation_duration - elapsed)
    
    async def wait_for_next_execution(
        self,
        min_interval: int,
        max_interval: int,
        jitter_factor: float = 0.1
    ) -> bool:
        """Wait for next pattern execution
        
        Args:
            min_interval: Minimum interval in seconds
            max_interval: Maximum interval in seconds
            jitter_factor: Jitter factor for timing variation
            
        Returns:
            True if should continue execution, False if should stop
        """
        if not self.is_running():
            return False
        
        interval = InternalTimingUtils.get_pattern_interval(
            min_interval, max_interval, jitter_factor
        )
        
        # Don't wait longer than remaining time
        remaining = self.get_remaining_time()
        if remaining <= 0:
            return False
        
        wait_time = min(interval, remaining)
        
        try:
            await asyncio.sleep(wait_time)
            return self.is_running()
        except asyncio.CancelledError:
            return False
    
    def register_execution(self, is_burst: bool = False):
        """Register a pattern execution
        
        Args:
            is_burst: Whether this was a burst execution
        """
        self.stats['total_executions'] += 1
        if is_burst:
            self.stats['burst_executions'] += 1
    
    def register_pattern_start(self):
        """Register a pattern start"""
        self.stats['patterns_started'] += 1
    
    def register_pattern_completion(self):
        """Register a pattern completion"""
        self.stats['patterns_completed'] += 1
    
    def register_scheduling_error(self):
        """Register a scheduling error"""
        self.stats['scheduling_errors'] += 1
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get scheduler statistics
        
        Returns:
            Dictionary containing scheduler statistics
        """
        return {
            'simulation_duration': self.simulation_duration,
            'elapsed_time': self.get_elapsed_time(),
            'remaining_time': self.get_remaining_time(),
            'is_running': self.is_running(),
            'patterns_started': self.stats['patterns_started'],
            'patterns_completed': self.stats['patterns_completed'],
            'total_executions': self.stats['total_executions'],
            'burst_executions': self.stats['burst_executions'],
            'scheduling_errors': self.stats['scheduling_errors'],
            'execution_rate_per_minute': self._calculate_execution_rate()
        }
    
    def _calculate_execution_rate(self) -> float:
        """Calculate execution rate per minute"""
        elapsed = self.get_elapsed_time()
        if elapsed <= 0:
            return 0.0
        
        return (self.stats['total_executions'] / elapsed) * 60


class InternalBurstScheduler:
    """Specialized scheduler for burst executions in internal traffic"""
    
    def __init__(self, burst_probability: float = 0.05, burst_multiplier: float = 3.0):
        """Initialize burst scheduler
        
        Args:
            burst_probability: Probability of burst execution
            burst_multiplier: Timing multiplier for burst sequences
        """
        self.burst_probability = burst_probability
        self.burst_multiplier = burst_multiplier
        
        # Burst statistics
        self.burst_stats = {
            'total_bursts': 0,
            'burst_requests': 0,
            'last_burst_time': None
        }
    
    def should_execute_burst(self) -> bool:
        """Determine if burst should execute
        
        Returns:
            True if burst should execute
        """
        return InternalTimingUtils.should_execute_burst(self.burst_probability)
    
    async def execute_burst_sequence(
        self,
        burst_operations: list,
        base_interval: float = 1.0
    ) -> int:
        """Execute a sequence of burst operations
        
        Args:
            burst_operations: List of async operations to execute
            base_interval: Base interval between operations
            
        Returns:
            Number of operations executed
        """
        if not burst_operations:
            return 0
        
        self.burst_stats['total_bursts'] += 1
        self.burst_stats['last_burst_time'] = datetime.utcnow()
        
        executed = 0
        burst_interval = InternalTimingUtils.get_burst_interval(
            base_interval, self.burst_multiplier
        )
        
        for operation in burst_operations:
            try:
                await operation()
                executed += 1
                self.burst_stats['burst_requests'] += 1
                
                # Brief delay between burst operations
                if executed < len(burst_operations):
                    await asyncio.sleep(burst_interval)
                    
            except Exception as e:
                # Log error but continue with burst
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Burst operation failed: {e}")
        
        return executed
    
    def get_burst_statistics(self) -> Dict[str, Any]:
        """Get burst execution statistics
        
        Returns:
            Dictionary containing burst statistics
        """
        return {
            'total_bursts': self.burst_stats['total_bursts'],
            'burst_requests': self.burst_stats['burst_requests'],
            'last_burst_time': (
                self.burst_stats['last_burst_time'].isoformat()
                if self.burst_stats['last_burst_time'] else None
            ),
            'burst_probability': self.burst_probability,
            'burst_multiplier': self.burst_multiplier
        }