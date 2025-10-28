"""Health Monitoring Pattern (Internal Traffic Simulator)

Performs periodic health/status/metrics/dependency checks across internal services.

NOTE:
    • No SecurityEvent objects are emitted here.
    • These calls stimulate infrastructure services which generate authoritative events.
    • Local debug logging only for observability of simulation behavior.
"""

import asyncio
import logging
import random
from datetime import datetime
from typing import Dict, Any, List

# Intentionally no SecurityEvent import: this component is not an emitter.


class HealthMonitoringPattern:
    """Simulates internal service health check communications"""
    
    def __init__(self, http_client, scheduler):
        """Initialize the health monitoring pattern
        
        Args:
            http_client: InternalHTTPClient instance
            (event logger removed)
            scheduler: InternalPatternScheduler instance
        """
        self.http_client = http_client
        self.scheduler = scheduler
        self.logger = logging.getLogger(__name__)
        
        # Pattern configuration
        self.pattern_name = 'health_monitoring'
        self.interval_min = 20
        self.interval_max = 40
        
        # Statistics tracking
        self.stats = {
            'health_checks_performed': 0,
            'successful_checks': 0,
            'failed_checks': 0,
            'service_status_requests': 0,
            'performance_metric_requests': 0
        }
        
        # Services to monitor
        self.monitored_services = ['api_gateway', 'vault_service', 'database']
        
        # Health check types
        self.health_check_types = [
            'basic_health',
            'service_status', 
            'performance_metrics',
            'dependency_check'
        ]
    
    async def run_pattern(self):
        """Main execution loop for health monitoring pattern"""
        self.logger.info(f"Starting {self.pattern_name} pattern")
        
        while self.scheduler.is_running():
            try:
                # Wait for next execution time
                await self._wait_for_next_execution()
                
                if not self.scheduler.is_running():
                    break
                
                # Execute health check
                await self._execute_health_check()
                
                # Occasionally do comprehensive health check cycle
                if random.random() < 0.08:  # 8% chance
                    await self._execute_comprehensive_health_cycle()
                
            except asyncio.CancelledError:
                self.logger.info(f"{self.pattern_name} pattern cancelled")
                break
            except Exception as e:
                self.logger.error(f"Error in {self.pattern_name} pattern: {e}")
                await asyncio.sleep(3)  # Brief pause on error
        
        self.logger.info(f"{self.pattern_name} pattern completed")
    
    async def _wait_for_next_execution(self):
        """Wait for the next pattern execution with jitter"""
        interval = random.uniform(self.interval_min, self.interval_max)
        
        # Add small jitter for realistic timing
        jitter = random.uniform(-1.5, 1.5)
        wait_time = max(5, interval + jitter)  # Minimum 5 second wait
        
        await asyncio.sleep(wait_time)
    
    async def _execute_health_check(self):
        """Execute a single health check on a random service"""
        service = random.choice(self.monitored_services)
        check_type = random.choice(self.health_check_types)
        
        self.logger.info(f"Performing {check_type} health check on {service}")
        
        try:
            if check_type == 'basic_health':
                result = await self._basic_health_check(service)
            elif check_type == 'service_status':
                result = await self._service_status_check(service)
            elif check_type == 'performance_metrics':
                result = await self._performance_metrics_check(service)
            else:  # dependency_check
                result = await self._dependency_check(service)
            
            self.stats['health_checks_performed'] += 1
            
            if result.get('status_code', 500) < 400:
                self.stats['successful_checks'] += 1
                self.logger.debug(f"Health check successful: {service} - {check_type}")
            else:
                self.stats['failed_checks'] += 1
                self.logger.warning(f"Health check failed: {service} - {check_type}")
            
            # Local debug trace only
            await self._log_health_check_event(service, check_type, result)
            
        except Exception as e:
            self.stats['failed_checks'] += 1
            self.logger.error(f"Health check exception: {e}")
    
    async def _basic_health_check(self, service: str) -> Dict[str, Any]:
        """Perform basic health check"""
        return await self.http_client.health_check(service)
    
    async def _service_status_check(self, service: str) -> Dict[str, Any]:
        """Perform detailed service status check"""
        self.stats['service_status_requests'] += 1
        
        if service == 'api_gateway':
            return await self.http_client.api_gateway_request('/health', method='GET')
        elif service == 'vault_service':
            return await self.http_client.vault_request('/health', method='GET')
        else:  # database
            return await self.http_client.api_gateway_request('/api/services', method='GET')
    
    async def _performance_metrics_check(self, service: str) -> Dict[str, Any]:
        """Perform performance metrics check"""
        self.stats['performance_metric_requests'] += 1
        
        if service == 'api_gateway':
            return await self.http_client.api_gateway_request('/health', method='GET')
        elif service == 'vault_service':
            return await self.http_client.vault_request('/health', method='GET')
        else:  # database
            return await self.http_client.api_gateway_request('/api/services', method='GET')
    
    async def _dependency_check(self, service: str) -> Dict[str, Any]:
        """Check service dependencies"""
        if service == 'api_gateway':
            # API Gateway depends on vault and database
            return await self.http_client.api_gateway_request('/health', method='GET')
        elif service == 'vault_service':
            # Vault has minimal dependencies
            return await self.http_client.vault_request('/health', method='GET')
        else:  # database
            # Database dependency check via API Gateway
            return await self.http_client.api_gateway_request('/api/services', method='GET')
    
    async def _execute_comprehensive_health_cycle(self):
        """Execute comprehensive health check cycle across all services"""
        self.logger.info("Executing comprehensive health check cycle")
        
        for service in self.monitored_services:
            try:
                # Basic health check
                basic_result = await self._basic_health_check(service)
                await self._log_health_check_event(service, 'basic_health', basic_result, is_comprehensive=True)
                
                # Service status check
                status_result = await self._service_status_check(service)
                await self._log_health_check_event(service, 'service_status', status_result, is_comprehensive=True)
                
                # Update statistics
                self.stats['health_checks_performed'] += 2
                
                if basic_result.get('status_code', 500) < 400:
                    self.stats['successful_checks'] += 1
                else:
                    self.stats['failed_checks'] += 1
                
                if status_result.get('status_code', 500) < 400:
                    self.stats['successful_checks'] += 1
                else:
                    self.stats['failed_checks'] += 1
                
                # Brief delay between service checks
                await asyncio.sleep(random.uniform(0.5, 1.0))
                
            except Exception as e:
                self.stats['failed_checks'] += 2
                self.logger.error(f"Comprehensive health check failed for {service}: {e}")
    
    async def _log_health_check_event(self, service: str, check_type: str, result: Dict[str, Any], is_comprehensive: bool = False):
        """Local debug log for health check (non-authoritative)."""
        status_code = result.get('status_code', 500)
        status_str = 'success' if status_code < 400 else 'failure'
        self.logger.debug(
            "health_check",
            extra={
                'pattern': self.pattern_name,
                'service': service,
                'check_type': check_type,
                'status_code': status_code,
                'status': status_str,
                'is_comprehensive': is_comprehensive,
                'monitoring_type': self._categorize_monitoring_type(check_type)
            }
        )
    
    def _categorize_monitoring_type(self, check_type: str) -> str:
        """Categorize the type of monitoring operation"""
        if check_type == 'basic_health':
            return 'basic_health_check'
        elif check_type == 'service_status':
            return 'detailed_status_check'
        elif check_type == 'performance_metrics':
            return 'performance_monitoring'
        elif check_type == 'dependency_check':
            return 'dependency_validation'
        else:
            return 'unknown_monitoring'
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get pattern execution statistics"""
        success_rate = 0
        if self.stats['health_checks_performed'] > 0:
            success_rate = (self.stats['successful_checks'] / self.stats['health_checks_performed']) * 100
        
        return {
            'pattern_name': self.pattern_name,
            'health_checks_performed': self.stats['health_checks_performed'],
            'successful_checks': self.stats['successful_checks'],
            'failed_checks': self.stats['failed_checks'],
            'success_rate_percent': round(success_rate, 2),
            'service_status_requests': self.stats['service_status_requests'],
            'performance_metric_requests': self.stats['performance_metric_requests']
        }