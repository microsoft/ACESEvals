"""
External Traffic Simulator - Admin Maintenance Pattern

Pattern 2: Admin Maintenance via WebApp Proxy (90-120 second intervals)
Simulates legitimate admin maintenance operations that use the same endpoints as red team attacks.
"""

import asyncio
import random
import logging
import uuid
from typing import Dict, Any, List
import sys
import os

# Add src directory to path for absolute imports
sys.path.insert(0, '/app/src')

from utils.http_client import ExternalHTTPClient
from utils.timing import ExternalTimingUtils, ExternalPatternScheduler
from config.credentials import ADMIN_CREDENTIALS, USER_AGENTS, MAINTENANCE_SCRIPTS, MAINTENANCE_COMMANDS


class AdminMaintenancePattern:
    """Simulates legitimate admin maintenance operations"""
    
    def __init__(self, http_client: ExternalHTTPClient, scheduler: ExternalPatternScheduler):
        """
        Initialize admin maintenance pattern
        
        Args:
            http_client: HTTP client for webapp communication
            scheduler: Pattern scheduler for timing coordination
        """
        self.http_client = http_client
        self.scheduler = scheduler
        self.pattern_name = "admin_maintenance"
        self.logger = logging.getLogger(__name__)
        
        # Track maintenance sessions
        self.maintenance_sessions = {}
        self.script_rotation_index = 0
        self.command_rotation_index = 0
    
    async def execute_admin_login(self, admin_user: str) -> Dict[str, Any]:
        """
        Execute admin login for maintenance operations
        
        Args:
            admin_user: Admin username
            
        Returns:
            Dictionary with login results
        """
        password = ADMIN_CREDENTIALS.get(admin_user)
        if not password:
            raise ValueError(f"No password configured for admin user: {admin_user}")
        
        user_agent = USER_AGENTS["admin"]
        
        self.logger.info(f"Admin maintenance login: {admin_user}")
        
        try:
            # Create maintenance session
            session_id = str(uuid.uuid4())
            
            # Perform admin login (same as red team Phase 1-2)
            response = await self.http_client.login(
                username=admin_user,
                password=password,
                user_agent=user_agent
            )
            
            login_successful = "login successful" in response["content"].lower()
            
            if login_successful:
                self.maintenance_sessions[admin_user] = {
                    "session_id": session_id,
                    "login_time": asyncio.get_event_loop().time(),
                    "user_agent": user_agent
                }
            
            return {
                "admin_user": admin_user,
                "success": login_successful,
                "session_id": session_id,
                "response": response
            }
            
        except Exception as e:
            self.logger.error(f"Admin login error for {admin_user}: {e}")
            
            return {
                "admin_user": admin_user,
                "success": False,
                "error": str(e)
            }
    
    async def execute_script_upload(self, admin_user: str) -> Dict[str, Any]:
        """
        Upload legitimate maintenance script (same endpoint as red team Phase 3)
        
        Args:
            admin_user: Admin username
            
        Returns:
            Dictionary with upload results
        """
        if admin_user not in self.maintenance_sessions:
            return {"error": "No active maintenance session"}
        
        session_info = self.maintenance_sessions[admin_user]
        user_agent = session_info["user_agent"]
        
        # Rotate through maintenance scripts
        script = MAINTENANCE_SCRIPTS[self.script_rotation_index % len(MAINTENANCE_SCRIPTS)]
        self.script_rotation_index += 1
        
        self.logger.info(f"Admin uploading maintenance script: {script['filename']}")
        
        try:
            # Upload legitimate maintenance script (same as red team Phase 3)
            response = await self.http_client.upload_file(
                filename=script["filename"],
                content=script["content"],
                user_agent=user_agent
            )
            
            upload_successful = response["status_code"] == 200
            
            return {
                "admin_user": admin_user,
                "script_filename": script["filename"],
                "success": upload_successful,
                "response": response
            }
            
        except Exception as e:
            self.logger.error(f"Script upload error for {admin_user}: {e}")
            
            return {
                "admin_user": admin_user,
                "script_filename": script["filename"],
                "success": False,
                "error": str(e)
            }
    
    async def execute_maintenance_commands(self, admin_user: str, num_commands: int = None) -> List[Dict[str, Any]]:
        """
        Execute maintenance shell commands (same endpoint as red team RCE)
        
        Args:
            admin_user: Admin username
            num_commands: Number of commands to execute (random if None)
            
        Returns:
            List of command execution results
        """
        if admin_user not in self.maintenance_sessions:
            return [{"error": "No active maintenance session"}]
        
        session_info = self.maintenance_sessions[admin_user]
        user_agent = session_info["user_agent"]
        
        # Select random maintenance commands
        if num_commands is None:
            num_commands = random.randint(2, 4)
        
        commands_to_execute = random.sample(MAINTENANCE_COMMANDS, 
                                          min(num_commands, len(MAINTENANCE_COMMANDS)))
        
        results = []
        
        for command in commands_to_execute:
            self.logger.info(f"Admin executing maintenance command: {command}")
            
            try:
                # Wait between commands for realistic timing
                await ExternalTimingUtils.wait_with_jitter(
                    ExternalTimingUtils.get_maintenance_sequence_delay()
                )
                
                # Execute maintenance command (same endpoint as red team RCE)
                response = await self.http_client.execute_shell_command(
                    command=command,
                    user_agent=user_agent
                )
                
                command_successful = response["status_code"] == 200
                
                results.append({
                    "command": command,
                    "success": command_successful,
                    "response": response
                })
                
            except Exception as e:
                self.logger.error(f"Command execution error for {admin_user}, command '{command}': {e}")
                
                results.append({
                    "command": command,
                    "success": False,
                    "error": str(e)
                })
        
        return results
    
    async def execute_maintenance_session(self) -> Dict[str, Any]:
        """
        Execute a complete admin maintenance session
        
        Returns:
            Dictionary with maintenance session results
        """
        # Rotate through admin users
        admin_users = list(ADMIN_CREDENTIALS.keys())
        admin_user = random.choice(admin_users)
        
        self.logger.info(f"Starting admin maintenance session: {admin_user}")
        
        session_results = {
            "admin_user": admin_user,
            "phases": {}
        }
        
        try:
            # Phase 1: Admin login (same as red team Phase 1-2)
            login_result = await self.execute_admin_login(admin_user)
            session_results["phases"]["login"] = login_result
            
            if not login_result.get("success"):
                return session_results
            
            # Phase 2: Upload maintenance script (same as red team Phase 3)  
            await ExternalTimingUtils.wait_with_jitter(2, 0.5)
            upload_result = await self.execute_script_upload(admin_user)
            session_results["phases"]["script_upload"] = upload_result
            
            # Phase 3: Execute maintenance commands (same endpoint as red team RCE)
            await ExternalTimingUtils.wait_with_jitter(3, 0.5)
            command_results = await self.execute_maintenance_commands(admin_user)
            session_results["phases"]["shell_commands"] = command_results
            
            return session_results
            
        except Exception as e:
            self.logger.error(f"Admin maintenance session error for {admin_user}: {e}")
            
            session_results["error"] = str(e)
            return session_results
        
        finally:
            # Clean up session
            if admin_user in self.maintenance_sessions:
                del self.maintenance_sessions[admin_user]
    
    async def run_pattern(self):
        """Run the admin maintenance pattern continuously"""
        self.logger.info("Starting admin maintenance pattern")
        
        iteration_count = 0
        successful_sessions = 0
        
        try:
            while self.scheduler.should_continue_pattern(self.pattern_name):
                iteration_count += 1
                
                # Execute admin maintenance session
                session_result = await self.execute_maintenance_session()
                
                if not session_result.get("error"):
                    successful_sessions += 1
                
                # Record pattern iteration
                self.scheduler.record_pattern_iteration(self.pattern_name)
                
                # Wait for next iteration
                if self.scheduler.should_continue_pattern(self.pattern_name):
                    await ExternalTimingUtils.wait_for_pattern_interval(self.pattern_name)
                
        except asyncio.CancelledError:
            self.logger.info("Admin maintenance pattern cancelled")
        except Exception as e:
            self.logger.error(f"Admin maintenance pattern error: {e}")
        finally:
            self.logger.info(f"Admin maintenance pattern completed after {iteration_count} iterations")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get pattern execution statistics"""
        return {
            "pattern_name": self.pattern_name,
            "active_sessions": len(self.maintenance_sessions),
            "scripts_uploaded": self.script_rotation_index,
            "commands_executed": self.command_rotation_index,
            "iterations": self.scheduler.get_pattern_iteration_count(self.pattern_name)
        }