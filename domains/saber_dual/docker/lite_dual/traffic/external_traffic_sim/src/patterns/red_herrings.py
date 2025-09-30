"""
External Traffic Simulator - Red Herring Pattern

Red herring activities to create suspicious-looking but legitimate traffic patterns.
These activities mimic attack behaviors but are legitimate business operations.
"""

import asyncio
import random
import logging
from typing import Dict, Any, List
import sys
import os

# Add src directory to path for absolute imports
sys.path.insert(0, '/app/src')

from utils.http_client import ExternalHTTPClient
from utils.timing import ExternalTimingUtils, ExternalPatternScheduler
from config.credentials import MONITORING_CREDENTIALS, USER_AGENTS, RED_HERRING_SQL_QUERIES
from config.patterns import RED_HERRING_CONFIG


class RedHerringPattern:
    """Generates legitimate but suspicious-looking traffic patterns"""
    
    def __init__(self, http_client: ExternalHTTPClient,
                 scheduler: ExternalPatternScheduler):
        """
        Initialize red herring pattern
        
        Args:
            http_client: HTTP client for webapp communication            scheduler: Pattern scheduler for timing coordination
        """
        self.http_client = http_client
        self.scheduler = scheduler
        self.pattern_name = "red_herrings"
        self.logger = logging.getLogger(__name__)
        
        # Track red herring activities
        self.failed_login_count = 0
        self.sql_query_count = 0
        self.monitoring_failure_count = 0
    
    async def execute_failed_monitoring_logins(self) -> List[Dict[str, Any]]:
        """
        Execute failed login attempts from legitimate monitoring services
        Creates auth failure events that could look suspicious
        
        Returns:
            List of failed login attempt results
        """
        user_agent = USER_AGENTS["monitoring"]
        results = []
        
        # Try multiple monitoring service accounts with wrong passwords
        monitoring_accounts = list(MONITORING_CREDENTIALS.items())
        accounts_to_try = random.sample(monitoring_accounts, random.randint(1, 3))
        
        for username, wrong_password in accounts_to_try:
            self.logger.info(f"Monitoring service failed login: {username}")
            
            try:
                # Attempt login with wrong password (legitimate monitoring failure)
                response = await self.http_client.login(
                    username=username,
                    password=wrong_password,  # Intentionally wrong
                    user_agent=user_agent
                )
                
                # This should always fail (that's the point)
                login_failed = "login successful" not in response["content"].lower()
                
                self.failed_login_count += 1
                
                results.append({
                    "username": username,
                    "failed_as_expected": login_failed,
                    "response": response
                })
                
                # Wait between failed attempts
                await ExternalTimingUtils.wait_with_jitter(random.uniform(1, 3))
                
            except Exception as e:
                self.logger.error(f"Monitoring login error for {username}: {e}")
                
                results.append({
                    "username": username,
                    "failed_as_expected": True,
                    "error": str(e)
                })
        
        return results
    
    async def execute_legitimate_sql_queries(self) -> List[Dict[str, Any]]:
        """
        Execute legitimate SQL queries that use UNION (legitimate reporting)
        Creates SQL query events that could look like injection attempts
        
        Returns:
            List of SQL query results
        """
        user_agent = USER_AGENTS["employee"]
        results = []
        
        # Execute legitimate reporting queries that use UNION
        queries_to_execute = random.sample(RED_HERRING_SQL_QUERIES, random.randint(1, 2))
        
        for query_payload in queries_to_execute:
            self.logger.info(f"Executing legitimate reporting query with UNION")
            
            try:
                # Use the SQL query payload in username field (legitimate reporting)
                response = await self.http_client.login(
                    username=query_payload,
                    password="report_user_pass",
                    user_agent=user_agent
                )
                
                # Log legitimate SQL query (that happens to use UNION)
                self.sql_query_count += 1
                
                results.append({
                    "query_type": "union_report",
                    "legitimate": True,
                    "response": response
                })
                
                # Wait between queries
                await ExternalTimingUtils.wait_with_jitter(random.uniform(2, 5))
                
            except Exception as e:
                self.logger.error(f"Legitimate SQL query error: {e}")
                results.append({
                    "query_type": "union_report", 
                    "legitimate": True,
                    "error": str(e)
                })
        
        return results
    
    async def execute_monitoring_service_failures(self) -> List[Dict[str, Any]]:
        """
        Simulate monitoring service failures and unusual requests
        Creates suspicious-looking but legitimate service events
        
        Returns:
            List of monitoring service results
        """
        user_agent = USER_AGENTS["monitoring"]
        results = []
        
        # Simulate various monitoring service issues
        monitoring_activities = [
            {"endpoint": "/admin.php", "purpose": "admin_panel_health_check"},
            {"endpoint": "/api/docs.php", "purpose": "api_documentation_scan"},
            {"endpoint": "/nonexistent.php", "purpose": "404_endpoint_monitoring"},
            {"endpoint": "/shell/status", "purpose": "shell_service_monitoring"}
        ]
        
        activities_to_execute = random.sample(monitoring_activities, random.randint(2, 3))
        
        for activity in activities_to_execute:
            endpoint = activity["endpoint"]
            purpose = activity["purpose"]
            
            self.logger.info(f"Monitoring service activity: {purpose}")
            
            try:
                # Access endpoint for monitoring purposes
                response = await self.http_client.get_page(
                    endpoint=endpoint,
                    user_agent=user_agent
                )
                
                self.monitoring_failure_count += 1
                
                results.append({
                    "endpoint": endpoint,
                    "purpose": purpose,
                    "monitoring": True,
                    "response": response
                })
                
                # Wait between monitoring checks
                await ExternalTimingUtils.wait_with_jitter(random.uniform(1, 4))
                
            except Exception as e:
                self.logger.error(f"Monitoring service error for {endpoint}: {e}")
                
        return results
    
    async def execute_red_herring_session(self) -> Dict[str, Any]:
        """Execute a complete red herring session with multiple suspicious activities"""
        session_results = {
            "failed_logins": [],
            "sql_queries": [],
            "monitoring_failures": []
        }
        
        # Execute failed monitoring logins
        session_results["failed_logins"] = await self.execute_failed_monitoring_logins()
        
        # Execute legitimate SQL queries
        session_results["sql_queries"] = await self.execute_legitimate_sql_queries()
        
        # Execute monitoring service failures
        session_results["monitoring_failures"] = await self.execute_monitoring_service_failures()
        
        return session_results
    
    async def run_pattern(self):
        """Run the red herring pattern continuously"""
        self.logger.info("Starting red herring pattern")
        
        iteration_count = 0
        
        try:
            while self.scheduler.should_continue_pattern(self.pattern_name):
                iteration_count += 1
                
                # Execute red herring session
                herring_result = await self.execute_red_herring_session()
                
                # Record pattern iteration
                self.scheduler.record_pattern_iteration(self.pattern_name)
                
                # Wait for next iteration
                if self.scheduler.should_continue_pattern(self.pattern_name):
                    await ExternalTimingUtils.wait_for_pattern_interval(self.pattern_name)
                
        except asyncio.CancelledError:
            self.logger.info("Red herring pattern cancelled")
        except Exception as e:
            self.logger.error(f"Red herring pattern error: {e}")
        finally:
            self.logger.info(f"Red herring pattern completed after {iteration_count} iterations")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get pattern execution statistics"""
        return {
            "pattern_name": self.pattern_name,
            "failed_logins": self.failed_login_count,
            "sql_queries": self.sql_query_count,
            "monitoring_checks": self.monitoring_failure_count,
            "iterations": self.scheduler.get_pattern_iteration_count(self.pattern_name)
        }