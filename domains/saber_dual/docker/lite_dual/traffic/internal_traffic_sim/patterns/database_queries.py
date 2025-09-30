"""Database Query Pattern (Internal Traffic Simulator)

Generates realistic maintenance / monitoring / security-oriented query traffic by
calling API Gateway endpoints that proxy database-related functionality.

IMPORTANT:
    • This pattern does NOT emit SecurityEvent objects.
    • It only stimulates infrastructure services which will perform any real logging.
    • SecurityEvent imports removed intentionally to reduce role confusion.
"""

import asyncio
import logging
import random
from datetime import datetime
from typing import Dict, Any, List

# Add shared utilities to path
import sys
sys.path.append('/app/shared')

# No SecurityEvent / schema imports: infrastructure remains sole event emitter.


class DatabaseQueryPattern:
    """Simulates internal database maintenance and monitoring queries"""
    
    def __init__(self, http_client, scheduler):
        """Initialize the database query pattern
        
        Args:
            http_client: InternalHTTPClient instance
            (event logger removed)
            scheduler: InternalPatternScheduler instance
        """
        self.http_client = http_client
        self.scheduler = scheduler
        self.logger = logging.getLogger(__name__)
        
        # Pattern configuration
        self.pattern_name = 'database_queries'
        self.interval_min = 15
        self.interval_max = 45
        
        # Statistics tracking
        self.stats = {
            'queries_executed': 0,
            'successful_queries': 0,
            'failed_queries': 0,
            'maintenance_queries': 0,
            'monitoring_queries': 0,
            'security_queries': 0
        }
        
        # Common internal database queries
        self.maintenance_queries = [
            "SELECT COUNT(*) FROM users WHERE last_login > NOW() - INTERVAL 1 HOUR",
            "SELECT * FROM system_health WHERE check_time > NOW() - INTERVAL 5 MINUTE ORDER BY check_time DESC LIMIT 5",
            "SELECT session_id, user_id, created_at FROM active_sessions ORDER BY created_at DESC LIMIT 10",
            "SELECT COUNT(*) FROM failed_logins WHERE attempt_time > NOW() - INTERVAL 1 HOUR",
            "UPDATE system_metrics SET last_updated = NOW() WHERE metric_name = 'database_health'",
            "SELECT table_name, table_rows FROM information_schema.tables WHERE table_schema = 'saber_dual'"
        ]
        
        self.monitoring_queries = [
            "SELECT COUNT(*) FROM security_events WHERE severity >= 3 AND created_at > NOW() - INTERVAL 1 HOUR",
            "SELECT event_type, COUNT(*) as count FROM security_events WHERE created_at > NOW() - INTERVAL 15 MINUTE GROUP BY event_type",
            "SELECT user_id, COUNT(*) as login_count FROM user_sessions WHERE created_at > NOW() - INTERVAL 2 HOUR GROUP BY user_id HAVING login_count > 5",
            "SELECT ip_address, COUNT(*) as request_count FROM access_logs WHERE timestamp > NOW() - INTERVAL 30 MINUTE GROUP BY ip_address ORDER BY request_count DESC LIMIT 10",
            "SELECT AVG(response_time) as avg_response FROM performance_metrics WHERE recorded_at > NOW() - INTERVAL 10 MINUTE"
        ]
        
        self.security_queries = [
            "SELECT * FROM security_events WHERE event_type = 'failed_login' AND created_at > NOW() - INTERVAL 30 MINUTE ORDER BY created_at DESC",
            "SELECT user_id, ip_address, COUNT(*) as attempts FROM failed_logins WHERE attempt_time > NOW() - INTERVAL 1 HOUR GROUP BY user_id, ip_address HAVING attempts >= 3",
            "SELECT * FROM audit_logs WHERE action IN ('secret_access', 'privilege_escalation') AND timestamp > NOW() - INTERVAL 2 HOUR",
            "SELECT endpoint, COUNT(*) as access_count FROM api_access_logs WHERE timestamp > NOW() - INTERVAL 15 MINUTE AND endpoint LIKE '%/secrets/%' GROUP BY endpoint"
        ]
    
    async def run_pattern(self):
        """Main execution loop for database query pattern"""
        self.logger.info(f"Starting {self.pattern_name} pattern")
        
        while self.scheduler.is_running():
            try:
                # Wait for next execution time
                await self._wait_for_next_execution()
                
                if not self.scheduler.is_running():
                    break
                
                # Execute database query
                await self._execute_database_query()
                
                # Occasionally execute monitoring burst
                if random.random() < 0.1:  # 10% chance
                    await self._execute_monitoring_burst()
                
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
        jitter = random.uniform(-1, 1)
        wait_time = max(3, interval + jitter)  # Minimum 3 second wait
        
        await asyncio.sleep(wait_time)
    
    async def _execute_database_query(self):
        """Execute a single database query"""
        # Choose query type based on realistic distribution
        query_type = random.choices(
            ['maintenance', 'monitoring', 'security'],
            weights=[0.5, 0.3, 0.2]  # 50% maintenance, 30% monitoring, 20% security
        )[0]
        
        if query_type == 'maintenance':
            query = random.choice(self.maintenance_queries)
            self.stats['maintenance_queries'] += 1
        elif query_type == 'monitoring':
            query = random.choice(self.monitoring_queries)
            self.stats['monitoring_queries'] += 1
        else:
            query = random.choice(self.security_queries)
            self.stats['security_queries'] += 1
        
        self.logger.info(f"Executing {query_type} database query")
        
        try:
            # Simulate database query via API Gateway using available endpoints
            # Use /api/services endpoint since it requires auth (simulates internal database operations)
            result = await self.http_client.api_gateway_request(
                '/api/services',
                method='GET'
            )
            
            self.stats['queries_executed'] += 1
            
            if result.get('status_code', 500) < 400:
                self.stats['successful_queries'] += 1
                self.logger.debug(f"Database query successful: {query_type}")
            else:
                self.stats['failed_queries'] += 1
                self.logger.warning(f"Database query failed: {query_type} - {result.get('error', 'Unknown error')}")
            
            # Local debug trace only
            await self._log_database_query_event(query_type, query, result)
            
        except Exception as e:
            self.stats['failed_queries'] += 1
            self.logger.error(f"Database query exception: {e}")
    
    async def _execute_monitoring_burst(self):
        """Execute a burst of monitoring queries (simulating health check cycle)"""
        self.logger.info("Executing database monitoring burst")
        
        # Monitoring burst sequence
        monitoring_sequence = [
            "SELECT COUNT(*) FROM security_events WHERE created_at > NOW() - INTERVAL 5 MINUTE",
            "SELECT AVG(response_time) as avg_response FROM performance_metrics WHERE recorded_at > NOW() - INTERVAL 5 MINUTE",
            "SELECT COUNT(*) FROM active_sessions",
            "SELECT event_type, COUNT(*) as count FROM security_events WHERE created_at > NOW() - INTERVAL 10 MINUTE GROUP BY event_type"
        ]
        
        for query in monitoring_sequence:
            try:
                result = await self.http_client.api_gateway_request(
                    '/api/services',
                    method='GET'
                )
                
                self.stats['queries_executed'] += 1
                self.stats['monitoring_queries'] += 1
                
                if result.get('status_code', 500) < 400:
                    self.stats['successful_queries'] += 1
                else:
                    self.stats['failed_queries'] += 1
                
                # Local debug trace only
                await self._log_database_query_event('monitoring', query, result, is_burst=True)
                
                # Brief delay between burst queries
                await asyncio.sleep(random.uniform(0.3, 0.8))
                
            except Exception as e:
                self.stats['failed_queries'] += 1
                self.logger.error(f"Burst database query failed: {e}")
    
    async def _log_database_query_event(self, query_type: str, query: str, result: Dict[str, Any], is_burst: bool = False):
        """Local debug log summarizing query activity (non-authoritative)."""
        status_code = result.get('status_code', 500)
        status_str = 'success' if status_code < 400 else 'failure'
        truncated = query[:100] + ('...' if len(query) > 100 else '')
        self.logger.debug(
            "database_query",
            extra={
                'pattern': self.pattern_name,
                'query_type': query_type,
                'query': truncated,
                'status_code': status_code,
                'status': status_str,
                'is_burst': is_burst,
                'target_service': 'database'
            }
        )
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get pattern execution statistics"""
        success_rate = 0
        if self.stats['queries_executed'] > 0:
            success_rate = (self.stats['successful_queries'] / self.stats['queries_executed']) * 100
        
        return {
            'pattern_name': self.pattern_name,
            'queries_executed': self.stats['queries_executed'],
            'successful_queries': self.stats['successful_queries'],
            'failed_queries': self.stats['failed_queries'],
            'success_rate_percent': round(success_rate, 2),
            'maintenance_queries': self.stats['maintenance_queries'],
            'monitoring_queries': self.stats['monitoring_queries'],
            'security_queries': self.stats['security_queries']
        }