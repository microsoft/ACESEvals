"""
External Traffic Simulator - Main Entry Point

Orchestrates all external traffic patterns for realistic DMZ network simulation.
Runs employee access, admin maintenance, compliance audits, and red herring activities.
"""

import asyncio
import logging
import os
import signal
import sys
from typing import Dict, Any, List

# Add current directory to path for absolute imports
sys.path.insert(0, '/app/src')

from utils.http_client import ExternalHTTPClient
from utils.timing import ExternalTimingUtils, ExternalPatternScheduler
from patterns.employee_access import EmployeeAccessPattern
from patterns.admin_maintenance import AdminMaintenancePattern  
from patterns.compliance_audit import ComplianceAuditPattern
from patterns.red_herrings import RedHerringPattern
from config.patterns import get_enabled_patterns, get_pattern_summary


class ExternalTrafficSimulator:
    """Main orchestrator for external traffic simulation"""
    
    def __init__(self):
        """Initialize the external traffic simulator"""
        # Environment configuration
        self.webapp_url = os.getenv('WEBAPP_URL', 'http://webapp:80')
        self.simulation_duration = int(os.getenv('SIMULATION_DURATION', '0'))  # 0 = run indefinitely
        self.log_level = os.getenv('LOG_LEVEL', 'INFO')
        self.pattern_randomization = os.getenv('PATTERN_RANDOMIZATION', 'true').lower() == 'true'
        
        # Setup logging
        self.logger = self._setup_logging()
        
        # Initialize components
        self.scheduler = ExternalPatternScheduler(self.simulation_duration)
        self.http_client = None
        
        # Pattern instances
        self.patterns = {}
        self.pattern_tasks = {}
        
        # Shutdown handling
        self.shutdown_event = asyncio.Event()
        self._setup_signal_handlers()
    
    def _setup_logging(self) -> logging.Logger:
        """Setup logging configuration"""
        logger = logging.getLogger(__name__)
        
        # Set log level
        level = getattr(logging, self.log_level.upper(), logging.INFO)
        logger.setLevel(level)
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # File handler (if possible)
        try:
            os.makedirs('/var/log/traffic', exist_ok=True)
            file_handler = logging.FileHandler('/var/log/traffic/external_simulator.log')
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception:
            # If we can't write to file, just use console
            pass
        
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
        self.logger.info("Initializing external traffic simulator")
        
        # Initialize HTTP client
        self.http_client = ExternalHTTPClient(
            webapp_url=self.webapp_url
        )
        
        # Initialize traffic patterns
        self.patterns = {
            'employee_access': EmployeeAccessPattern(
                self.http_client, self.scheduler
            ),
            'admin_maintenance': AdminMaintenancePattern(
                self.http_client, self.scheduler
            ),
            'compliance_audit': ComplianceAuditPattern(
                self.http_client, self.scheduler
            ),
            'red_herrings': RedHerringPattern(
                self.http_client, self.scheduler
            )
        }
        
        # Log initialization
        pattern_summary = get_pattern_summary()
        self.logger.info(f"Initialized with pattern summary: {pattern_summary}")
        
        # Apply startup delay to stagger container starts
        if self.pattern_randomization:
            startup_delay = ExternalTimingUtils.get_startup_delay()
            self.logger.info(f"Applying startup delay: {startup_delay:.1f} seconds")
            await asyncio.sleep(startup_delay)
    
    async def start_patterns(self):
        """Start all enabled traffic patterns"""
        self.logger.info("Starting external traffic patterns")
        
        enabled_patterns = get_enabled_patterns()
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
                    name=f"pattern_{pattern_name}"
                )
                
                self.pattern_tasks[pattern_name] = task
            else:
                self.logger.warning(f"Pattern not found: {pattern_name}")
        
        self.logger.info(f"Started {len(self.pattern_tasks)} traffic patterns")
    
    async def monitor_patterns(self):
        """Monitor pattern execution and log statistics"""
        self.logger.info("Starting pattern monitoring")
        
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
        
        self.logger.info("Pattern monitoring stopped")
    
    async def _log_pattern_statistics(self):
        """Log current pattern execution statistics"""
        stats = {
            "simulation": self.scheduler.get_statistics(),
            "patterns": {}
        }
        
        for pattern_name, pattern in self.patterns.items():
            if hasattr(pattern, 'get_statistics'):
                stats["patterns"][pattern_name] = pattern.get_statistics()
        
        self.logger.info(f"Pattern statistics: {stats}")
    
    async def wait_for_completion(self):
        """Wait for shutdown signal (runs indefinitely until stopped)"""
        self.logger.info("Running external traffic simulation (indefinite duration)")
        
        try:
            # Wait for shutdown signal only
            while not self.shutdown_event.is_set():
                await asyncio.sleep(1)
            
            self.logger.info("Shutdown signal received")
                
        except Exception as e:
            self.logger.error(f"Error during simulation: {e}")
        
        # Stop the scheduler
        self.scheduler.stop()
    
    async def stop_patterns(self):
        """Stop all running patterns gracefully"""
        self.logger.info("Stopping traffic patterns")
        
        # Cancel all pattern tasks
        for pattern_name, task in self.pattern_tasks.items():
            if not task.done():
                self.logger.info(f"Cancelling pattern: {pattern_name}")
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
        
        self.logger.info("All traffic patterns stopped")
    
    async def shutdown(self):
        """Graceful shutdown of the simulator"""
        self.logger.info("Initiating graceful shutdown")
        self.shutdown_event.set()
    
    async def run(self):
        """Main execution method"""
        self.logger.info("External Traffic Simulator starting")
        
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
            
            self.logger.info("External Traffic Simulator completed successfully")
            
        except Exception as e:
            self.logger.error(f"External Traffic Simulator error: {e}")
            raise
        finally:
            self.logger.info("External Traffic Simulator shutdown complete")


async def main():
    """Main entry point"""
    simulator = ExternalTrafficSimulator()
    
    try:
        await simulator.run()
        return 0
    except KeyboardInterrupt:
        print("\nReceived interrupt signal")
        return 1
    except Exception as e:
        print(f"Simulator error: {e}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)