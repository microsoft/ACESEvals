"""
External Traffic Simulator - Employee Access Pattern

Pattern 1: Employee Portal Access (60-90 second intervals)
Simulates legitimate employee logins to create auth events similar to red team.
"""

import asyncio
import random
import logging
from typing import Dict, Any
import sys
import os

# Add src directory to path for absolute imports
sys.path.insert(0, '/app/src')

from utils.http_client import ExternalHTTPClient
from utils.timing import ExternalTimingUtils, ExternalPatternScheduler
from config.credentials import EMPLOYEE_CREDENTIALS, USER_AGENTS


class EmployeeAccessPattern:
    """Simulates legitimate employee portal access"""
    
    def __init__(self, http_client: ExternalHTTPClient, scheduler: ExternalPatternScheduler):
        """
        Initialize employee access pattern
        
        Args:
            http_client: HTTP client for webapp communication
            scheduler: Pattern scheduler for timing coordination
        """
        self.http_client = http_client
        self.scheduler = scheduler
        self.pattern_name = "employee_access"
        self.logger = logging.getLogger(__name__)
        
        # Track employee login sessions
        self.active_sessions = {}
        self.login_rotation_index = 0
    
    async def execute_employee_login(self) -> Dict[str, Any]:
        """
        Execute a single employee login attempt
        
        Returns:
            Dictionary with login attempt results
        """
        # Rotate through employee credentials to simulate different users
        employee = EMPLOYEE_CREDENTIALS[self.login_rotation_index % len(EMPLOYEE_CREDENTIALS)]
        self.login_rotation_index += 1
        
        username = employee["username"]
        password = employee["password"]
        user_agent = USER_AGENTS["employee"]
        
        self.logger.info(f"Employee login attempt: {username}")
        
        try:
            # Create new session for this employee (just for tracking)
            import uuid
            session_id = str(uuid.uuid4())[:8]
            
            # Simulate realistic login delay
            await ExternalTimingUtils.wait_with_jitter(
                ExternalTimingUtils.get_employee_login_delay()
            )
            
            # Perform login request
            response = await self.http_client.login(
                username=username,
                password=password,
                user_agent=user_agent
            )
            
            # Determine login success
            login_successful = "login successful" in response["content"].lower()
            
            # Track active session if successful
            if login_successful:
                self.active_sessions[username] = {
                    "session_id": session_id,
                    "login_time": asyncio.get_event_loop().time(),
                    "user_agent": user_agent
                }
            
            self.logger.info(f"Employee login {'successful' if login_successful else 'failed'}: {username}")
            
            return {
                "username": username,
                "success": login_successful,
                "session_id": session_id,
                "response": response
            }
            
        except Exception as e:
            self.logger.error(f"Employee login error for {username}: {e}")
            
            return {
                "username": username,
                "success": False,
                "error": str(e)
            }
    
    async def execute_employee_browsing(self, username: str) -> Dict[str, Any]:
        """
        Execute employee browsing activity after login
        
        Args:
            username: Username of the logged-in employee
            
        Returns:
            Dictionary with browsing activity results
        """
        if username not in self.active_sessions:
            return {"error": "No active session for user"}
        
        session_info = self.active_sessions[username]
        user_agent = session_info["user_agent"]
        
        # Simulate employee browsing common pages
        browsing_pages = [
            "/dashboard.php",
            "/profile.php", 
            "/documents.php",
            "/help.php"
        ]
        
        browsed_pages = []
        
        for page in random.sample(browsing_pages, random.randint(1, 3)):
            try:
                await ExternalTimingUtils.wait_with_jitter(random.uniform(2, 5))
                
                response = await self.http_client.get_page(
                    endpoint=page,
                    user_agent=user_agent
                )
                
                browsed_pages.append({
                    "page": page,
                    "status": response["status_code"]
                })
                
                self.logger.debug(f"Employee {username} browsed {page}")
                
            except Exception as e:
                self.logger.warning(f"Employee browsing error for {username} on {page}: {e}")
        
        return {
            "username": username,
            "browsed_pages": browsed_pages,
            "session_id": session_info["session_id"]
        }
    
    async def run_pattern(self):
        """Run the employee access pattern continuously"""
        self.logger.info("Starting employee access pattern")
        
        iteration_count = 0
        
        try:
            while self.scheduler.should_continue_pattern(self.pattern_name):
                iteration_count += 1
                
                # Execute employee login
                login_result = await self.execute_employee_login()
                
                # If login successful, simulate some browsing
                if login_result.get("success"):
                    await self.execute_employee_browsing(login_result["username"])
                
                # Record pattern iteration
                self.scheduler.record_pattern_iteration(self.pattern_name)
                
                # Wait for next iteration
                if self.scheduler.should_continue_pattern(self.pattern_name):
                    await ExternalTimingUtils.wait_for_pattern_interval(self.pattern_name)
                
        except asyncio.CancelledError:
            self.logger.info("Employee access pattern cancelled")
        except Exception as e:
            self.logger.error(f"Employee access pattern error: {e}")
        finally:
            self.logger.info(f"Employee access pattern completed after {iteration_count} iterations")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get pattern execution statistics"""
        return {
            "pattern_name": self.pattern_name,
            "active_sessions": len(self.active_sessions),
            "total_employees": len(EMPLOYEE_CREDENTIALS),
            "current_rotation_index": self.login_rotation_index,
            "iterations": self.scheduler.get_pattern_iteration_count(self.pattern_name)
        }