"""
Internal Traffic Simulator - Main Entry Point

Orchestrates all internal service-to-service traffic patterns within the internal network.
Handles API Gateway ↔ Vault, database queries, health monitoring, and log aggregation.
"""

import asyncio
import logging
import os
import signal
import sys
from typing import Dict, Any, List

# Add utilities to path
sys.path.append('/app')

from utils.http_client import InternalHTTPClient
from utils.timing import InternalTimingUtils, InternalPatternScheduler
from patterns.api_gateway_vault import APIGatewayVaultPattern
from patterns.database_queries import DatabaseQueryPattern
from patterns.health_monitoring import HealthMonitoringPattern
from patterns.log_aggregation import LogAggregationPattern
from patterns.internal_compliance_audit import InternalComplianceAuditPattern
from config.patterns import (
    get_internal_service_endpoints, get_internal_credentials,
    get_enabled_internal_patterns, get_internal_pattern_summary,
    get_internal_timing_config
)


class InternalTrafficSimulator:
    """Main orchestrator for internal service-to-service traffic simulation"""
    
    def __init__(self):
        """Initialize the internal traffic simulator"""
        # Environment configuration
        self.simulation_duration = int(os.getenv('SIMULATION_DURATION', '0'))  # 0 = run indefinitely
        self.log_level = os.getenv('LOG_LEVEL', 'INFO')
        self.pattern_randomization = os.getenv('PATTERN_RANDOMIZATION', 'true').lower() == 'true'
        
        # Service endpoints and credentials
        self.service_endpoints = get_internal_service_endpoints()
        self.credentials = get_internal_credentials()
        self.timing_config = get_internal_timing_config()
        
        # Setup logging
        self.logger = self._setup_logging()
        
        # Initialize components (event logger removed)
        self.scheduler = InternalPatternScheduler(self.simulation_duration)
        self.http_client = None
        
        # Pattern instances
        self.patterns = {}
        self.pattern_tasks = {}
        
        # Shutdown handling
        self.shutdown_event = asyncio.Event()
        self._setup_signal_handlers()
    
    def _setup_logging(self) -> logging.Logger:
        """Setup logging configuration for traffic simulation coordination only"""
        # Traffic simulators should NOT log security events - only console logging for debugging
        logger = logging.getLogger(__name__)
        logger.setLevel(getattr(logging, self.log_level.upper(), logging.INFO))
        
        # Console handler only - no file logging for traffic simulators
        if not logger.handlers:
            console_handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)
        
        return logger
    
    def _setup_signal_handlers(self):
        """Setup graceful shutdown signal handlers"""
        for sig in [signal.SIGINT, signal.SIGTERM]:
            signal.signal(sig, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info(f"Received signal {signum}, initiating graceful shutdown")
        asyncio.create_task(self.shutdown())
    
    async def initialize(self):
        """Initialize all components and patterns"""
        self.logger.info("Initializing internal traffic simulator")
        
        # Initialize HTTP client for internal service communication
        self.http_client = InternalHTTPClient(
            service_endpoints=self.service_endpoints,
            credentials=self.credentials
        )
        
        # Initialize traffic patterns
        self.patterns = {
            'api_gateway_vault': APIGatewayVaultPattern(
                self.http_client, self.scheduler
            ),
            'database_queries': DatabaseQueryPattern(
                self.http_client, self.scheduler
            ),
            'health_monitoring': HealthMonitoringPattern(
                self.http_client, self.scheduler
            ),
            'log_aggregation': LogAggregationPattern(
                self.http_client, self.scheduler
            ),
            'internal_compliance_audit': InternalComplianceAuditPattern(
                self.http_client, self.scheduler
            )
        }
        
        # Log initialization
        pattern_summary = get_internal_pattern_summary()
        self.logger.info(f"Initialized with pattern summary: {pattern_summary}")
        self.logger.info(f"Service endpoints: {list(self.service_endpoints.keys())}")
        
        # Apply startup delay to stagger container starts
        if self.pattern_randomization:
            startup_delay = InternalTimingUtils.get_startup_delay(
                self.timing_config['startup_delay_min'],
                self.timing_config['startup_delay_max']
            )
            self.logger.info(f"Applying startup delay: {startup_delay:.1f} seconds")
            await asyncio.sleep(startup_delay)
    
    async def start_patterns(self):
        """Start all enabled internal traffic patterns"""
        self.logger.info("Starting internal traffic patterns")
        
        enabled_patterns = get_enabled_internal_patterns()
        self.logger.info(f"Enabled patterns: {enabled_patterns}")
        
        # Start the scheduler
        self.scheduler.start()
        
        # Start HTTP client context
        await self.http_client.__aenter__()
        
        # Start each enabled pattern as a separate task
        for pattern_name in enabled_patterns:
            if pattern_name in self.patterns:
                pattern = self.patterns[pattern_name]
                
                self.logger.info(f"Starting pattern: {pattern_name}")
                
                # Create task for pattern execution
                task = asyncio.create_task(
                    pattern.run_pattern(),
                    name=f"internal_pattern_{pattern_name}"
                )
                
                self.pattern_tasks[pattern_name] = task
            else:
                self.logger.warning(f"Pattern not found: {pattern_name}")
        
        self.logger.info(f"Started {len(self.pattern_tasks)} internal traffic patterns")
    
    async def monitor_patterns(self):
        """Monitor pattern execution and log statistics"""
        self.logger.info("Starting internal pattern monitoring")
        
        monitoring_interval = 30  # Log stats every 30 seconds
        
        while not self.shutdown_event.is_set() and self.scheduler.is_running():
            try:
                await asyncio.wait_for(
                    self.shutdown_event.wait(),
                    timeout=monitoring_interval
                )
                # If we get here, shutdown was signaled
                break
                
            except asyncio.TimeoutError:
                # Normal monitoring cycle
                await self._log_pattern_statistics()
        
        self.logger.info("Internal pattern monitoring stopped")
    
    async def _log_pattern_statistics(self):
        """Log current pattern execution statistics"""
        stats = {
            "simulation": self.scheduler.get_statistics(),
            "internal_patterns": {},
            "service_connectivity": await self._check_service_connectivity()
        }
        
        for pattern_name, pattern in self.patterns.items():
            if hasattr(pattern, 'get_statistics'):
                stats["internal_patterns"][pattern_name] = pattern.get_statistics()
        
        self.logger.info(f"Internal pattern statistics: {stats}")
    
    async def _check_service_connectivity(self) -> Dict[str, str]:
        """Check connectivity to internal services"""
        connectivity = {}
        
        for service_name in self.service_endpoints.keys():
            try:
                result = await self.http_client.health_check(service_name)
                if result.get('status_code', 500) < 400:
                    connectivity[service_name] = 'healthy'
                else:
                    connectivity[service_name] = 'unhealthy'
            except Exception:
                connectivity[service_name] = 'unreachable'
        
        return connectivity
    
    async def wait_for_completion(self):
        """Wait for simulation completion or shutdown"""
        self.logger.info(f"Running internal simulation for {self.simulation_duration} seconds")
        
        try:
            # Wait for either shutdown signal or simulation completion
            while self.scheduler.is_running() and not self.shutdown_event.is_set():
                await asyncio.sleep(1)
            
            if self.scheduler.is_running():
                self.logger.info("Shutdown signal received")
            else:
                self.logger.info("Internal simulation duration completed")
                
        except Exception as e:
            self.logger.error(f"Error during internal simulation: {e}")
        
        # Stop the scheduler
        self.scheduler.stop()
    
    async def stop_patterns(self):
        """Stop all running patterns gracefully"""
        self.logger.info("Stopping internal traffic patterns")
        
        # Cancel all pattern tasks
        for pattern_name, task in self.pattern_tasks.items():
            if not task.done():
                self.logger.info(f"Cancelling internal pattern: {pattern_name}")
                task.cancel()
        
        # Wait for tasks to complete cancellation
        if self.pattern_tasks:
            await asyncio.gather(
                *self.pattern_tasks.values(),
                return_exceptions=True
            )
        
        # Close HTTP client
        if self.http_client:
            await self.http_client.__aexit__(None, None, None)
        
        self.logger.info("All internal traffic patterns stopped")
    
    async def shutdown(self):
        """Graceful shutdown of the simulator"""
        self.logger.info("Initiating internal traffic simulator graceful shutdown")
        self.shutdown_event.set()
    
    async def run(self):
        """Main execution method"""
        self.logger.info("Internal Traffic Simulator starting")
        
        try:
            # Initialize components
            await self.initialize()
            
            # Start all patterns
            await self.start_patterns()
            
            # Start monitoring task
            monitoring_task = asyncio.create_task(self.monitor_patterns())
            
            # Wait for completion or shutdown
            await self.wait_for_completion()
            
            # Cancel monitoring
            monitoring_task.cancel()
            
            # Stop all patterns
            await self.stop_patterns()
            
            # Final statistics
            await self._log_pattern_statistics()
            
            self.logger.info("Internal Traffic Simulator completed successfully")
            
        except Exception as e:
            self.logger.error(f"Internal Traffic Simulator error: {e}")
            raise
        finally:
            self.logger.info("Internal Traffic Simulator shutdown complete")


async def main():
    """Main entry point"""
    simulator = InternalTrafficSimulator()
    
    try:
        await simulator.run()
        return 0
    except KeyboardInterrupt:
        print("\nReceived interrupt signal")
        return 1
    except Exception as e:
        print(f"Internal simulator error: {e}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)