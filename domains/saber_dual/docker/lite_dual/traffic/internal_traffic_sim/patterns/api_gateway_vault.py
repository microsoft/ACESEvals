"""API Gateway → Vault Communication Pattern (Internal Traffic Simulator)

NOTE:
    • This pattern DOES NOT emit SecurityEvent objects or send anything directly to the SIEM.
    • It generates legitimate service-to-service HTTP requests whose handling by real
        infrastructure services (api_gateway, vault) will result in authoritative security
        events being emitted by those services themselves.
    • All logging here is local debug/telemetry only; removal of event schema dependencies
        reduces confusion about emitter responsibility.
"""

import asyncio
import logging
import random
from datetime import datetime
from typing import Dict, Any, List

# Add shared utilities to path
import sys
sys.path.append('/app/shared')

# Deliberately avoid importing SecurityEvent / event schema here: patterns stimulate behavior only.


class APIGatewayVaultPattern:
    """Simulates API Gateway → Vault service communication"""
    
    def __init__(self, http_client, scheduler):
        """Initialize the API Gateway-Vault pattern
        
        Args:
            http_client: InternalHTTPClient instance
            scheduler: InternalPatternScheduler instance
        """
        self.http_client = http_client
        self.scheduler = scheduler
        self.logger = logging.getLogger(__name__)
        
        # Pattern configuration
        self.pattern_name = 'api_gateway_vault'
        self.interval_min = 30
        self.interval_max = 60
        
        # Statistics tracking
        self.stats = {
            'requests_sent': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'secrets_accessed': 0,
            'token_operations': 0
        }
        
        # Common vault endpoints for API Gateway (updated for custom vault service)
        self.vault_endpoints = [
            '/health',
            '/secrets/status',
            '/secrets/list', 
            '/secrets/admin',
            '/secrets/flags/crown_jewel'
        ]
    
    async def run_pattern(self):
        """Main execution loop for API Gateway-Vault pattern"""
        self.logger.info(f"Starting {self.pattern_name} pattern")
        
        while self.scheduler.is_running():
            try:
                # Wait for next execution time
                await self._wait_for_next_execution()
                
                if not self.scheduler.is_running():
                    break
                
                # Execute vault request
                await self._execute_vault_request()
                
                # Occasionally do burst of related requests
                if random.random() < 0.15:  # 15% chance
                    await self._execute_burst_requests()
                
            except asyncio.CancelledError:
                self.logger.info(f"{self.pattern_name} pattern cancelled")
                break
            except Exception as e:
                self.logger.error(f"Error in {self.pattern_name} pattern: {e}")
                await asyncio.sleep(5)  # Brief pause on error
        
        self.logger.info(f"{self.pattern_name} pattern completed")
    
    async def _wait_for_next_execution(self):
        """Wait for the next pattern execution with jitter"""
        interval = random.uniform(self.interval_min, self.interval_max)
        
        # Add small jitter for realistic timing
        jitter = random.uniform(-2, 2)
        wait_time = max(5, interval + jitter)  # Minimum 5 second wait
        
        await asyncio.sleep(wait_time)
    
    async def _execute_vault_request(self):
        """Execute a single vault request from API Gateway"""
        endpoint = random.choice(self.vault_endpoints)
        
        self.logger.info(f"API Gateway requesting vault endpoint: {endpoint}")
        
        try:
            # Make vault request
            result = await self.http_client.vault_request(endpoint, method='GET')
            
            self.stats['requests_sent'] += 1
            
            if result.get('status_code', 500) < 400:
                self.stats['successful_requests'] += 1
                
                # Track specific types of operations
                if 'secret' in endpoint:
                    self.stats['secrets_accessed'] += 1
                elif 'token' in endpoint:
                    self.stats['token_operations'] += 1
                
                self.logger.debug(f"Vault request successful: {endpoint}")
                
            else:
                self.stats['failed_requests'] += 1
                self.logger.warning(f"Vault request failed: {endpoint} - {result.get('error', 'Unknown error')}")
            
                # Local debug record only (infrastructure will emit any real event)
                await self._log_vault_access_event(endpoint, result)
            
        except Exception as e:
            self.stats['failed_requests'] += 1
            self.logger.error(f"Vault request exception: {e}")
    
    async def _execute_burst_requests(self):
        """Execute a burst of related vault requests (simulating batch operations)"""
        self.logger.info("Executing vault request burst")
        
        # Burst operations: token lookup, config retrieval, secret access
        burst_sequence = [
            '/health',
            '/secrets/status',
            '/secrets/list'
        ]
        
        for endpoint in burst_sequence:
            try:
                result = await self.http_client.vault_request(endpoint, method='GET')
                
                self.stats['requests_sent'] += 1
                
                if result.get('status_code', 500) < 400:
                    self.stats['successful_requests'] += 1
                    
                    if 'secret' in endpoint:
                        self.stats['secrets_accessed'] += 1
                    elif 'token' in endpoint:
                        self.stats['token_operations'] += 1
                else:
                    self.stats['failed_requests'] += 1
                
                # Local debug record only
                await self._log_vault_access_event(endpoint, result, is_burst=True)
                
                # Brief delay between burst requests
                await asyncio.sleep(random.uniform(0.5, 1.5))
                
            except Exception as e:
                self.stats['failed_requests'] += 1
                self.logger.error(f"Burst vault request failed: {e}")
    
    async def _log_vault_access_event(self, endpoint: str, result: Dict[str, Any], is_burst: bool = False):
        """Local debug log for vault access (non-authoritative)."""
        status_code = result.get('status_code', 500)
        status_str = 'success' if status_code < 400 else 'failure'
        self.logger.debug(
            "vault_access", extra={
                'pattern': self.pattern_name,
                'endpoint': endpoint,
                'status_code': status_code,
                'status': status_str,
                'is_burst': is_burst,
                'operation_type': self._categorize_vault_operation(endpoint)
            }
        )
    
    def _categorize_vault_operation(self, endpoint: str) -> str:
        """Categorize the type of vault operation"""
        if 'token' in endpoint:
            if 'lookup' in endpoint:
                return 'token_verification'
            elif 'renew' in endpoint:
                return 'token_renewal'
            else:
                return 'token_operation'
        elif 'secret' in endpoint:
            if 'app_config' in endpoint:
                return 'configuration_retrieval'
            elif 'database' in endpoint:
                return 'database_credential_access'
            elif 'encryption' in endpoint:
                return 'encryption_key_access'
            else:
                return 'secret_access'
        else:
            return 'unknown_operation'
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get pattern execution statistics"""
        success_rate = 0
        if self.stats['requests_sent'] > 0:
            success_rate = (self.stats['successful_requests'] / self.stats['requests_sent']) * 100
        
        return {
            'pattern_name': self.pattern_name,
            'requests_sent': self.stats['requests_sent'],
            'successful_requests': self.stats['successful_requests'],
            'failed_requests': self.stats['failed_requests'],
            'success_rate_percent': round(success_rate, 2),
            'secrets_accessed': self.stats['secrets_accessed'],
            'token_operations': self.stats['token_operations']
        }