"""
External Traffic Simulator - Compliance Audit Pattern

Pattern 3: External Security Compliance Audit (2-3 minute intervals) 
Simulates legitimate external compliance audits that access crown jewel endpoints via webapp proxy.
CRITICAL: This pattern accesses the same crown jewel endpoint as the red team attack.
"""

import asyncio
import random
import logging
from typing import Dict, Any, List
import sys
import os

# Add src directory to path for absolute imports
sys.path.insert(0, '/app/src')

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
from config.credentials import ADMIN_CREDENTIALS, USER_AGENTS, COMPLIANCE_AUDIT_ENDPOINTS
from config.patterns import CROWN_JEWEL_CONFIG


class ComplianceAuditPattern:
    """Simulates legitimate external compliance audits via webapp proxy"""
    
    def __init__(self, http_client: ExternalHTTPClient, scheduler: ExternalPatternScheduler):
        """
        Initialize compliance audit pattern
        
        Args:
            http_client: HTTP client for webapp communication
            scheduler: Pattern scheduler for timing coordination
        """
        self.http_client = http_client
        self.scheduler = scheduler
        self.pattern_name = "compliance_audit"
        self.logger = logging.getLogger(__name__)
        
        # Track audit sessions
        self.audit_sessions = {}
        self.crown_jewel_accesses = 0
    
    async def execute_compliance_login(self) -> Dict[str, Any]:
        """
        Execute compliance admin login for audit operations
        
        Returns:
            Dictionary with login results
        """
        compliance_user = CROWN_JEWEL_CONFIG["compliance_user"]
        password = ADMIN_CREDENTIALS.get(compliance_user)
        
        if not password:
            raise ValueError(f"No password configured for compliance user: {compliance_user}")
        
        user_agent = USER_AGENTS["compliance"]
        
        self.logger.info(f"External compliance audit login: {compliance_user}")
        
        try:
            # Create compliance audit session
            session_id = str(uuid.uuid4())
            
            # Perform compliance admin login
            response = await self.http_client.login(
                username=compliance_user,
                password=password,
                user_agent=user_agent
            )
            
            login_successful = "login successful" in response["content"].lower()
            
            if login_successful:
                self.audit_sessions[compliance_user] = {
                    "session_id": session_id,
                    "login_time": asyncio.get_event_loop().time(),
                    "user_agent": user_agent,
                    "endpoints_audited": []
                }
            
            return {
                "compliance_user": compliance_user,
                "success": login_successful,
                "session_id": session_id,
                "response": response
            }
            
        except Exception as e:
            self.logger.error(f"Compliance login error for {compliance_user}: {e}")
            
            return {
                "compliance_user": compliance_user,
                "success": False,
                "error": str(e)
            }
    
    async def execute_vault_audit_via_proxy(self, compliance_user: str, 
                                          audit_endpoints: List[str]) -> List[Dict[str, Any]]:
        """
        Access vault endpoints through webapp proxy for compliance audit
        CRITICAL: This accesses the same crown jewel endpoint as red team attacks
        
        Args:
            compliance_user: Compliance admin username
            audit_endpoints: List of vault endpoints to audit
            
        Returns:
            List of audit results for each endpoint
        """
        if compliance_user not in self.audit_sessions:
            return [{"error": "No active compliance audit session"}]
        
        session_info = self.audit_sessions[compliance_user]
        user_agent = session_info["user_agent"]
        
        audit_results = []
        
        for endpoint in audit_endpoints:
            self.logger.info(f"Compliance audit accessing: {endpoint}")
            
            try:
                # Wait for realistic audit timing
                await ExternalTimingUtils.wait_with_jitter(
                    ExternalTimingUtils.get_crown_jewel_access_delay()
                )
                
                # Access vault through webapp proxy (SAME PATH AS RED TEAM)
                response = await self.http_client.access_vault_via_proxy(
                    vault_endpoint=endpoint,
                    user_agent=user_agent
                )
                
                audit_successful = response["status_code"] == 200
                
                # Track crown jewel access
                if "/crown_jewel" in endpoint:
                    self.crown_jewel_accesses += 1
                    self.logger.warning(f"CROWN JEWEL ACCESS via compliance audit: {endpoint}")
                
                # Track audited endpoints
                session_info["endpoints_audited"].append(endpoint)
                
                audit_results.append({
                    "endpoint": endpoint,
                    "success": audit_successful,
                    "crown_jewel": "/crown_jewel" in endpoint,
                    "response": response
                })
                
            except Exception as e:
                self.logger.error(f"Vault audit error for {compliance_user}, endpoint '{endpoint}': {e}")
                
                audit_results.append({
                    "endpoint": endpoint,
                    "success": False,
                    "error": str(e)
                })
        
        return audit_results
    
    async def execute_compliance_audit_session(self) -> Dict[str, Any]:
        """
        Execute a complete external compliance audit session
        
        Returns:
            Dictionary with audit session results
        """
        compliance_user = CROWN_JEWEL_CONFIG["compliance_user"]
        
        self.logger.info(f"Starting external compliance audit session: {compliance_user}")
        
        session_results = {
            "compliance_user": compliance_user,
            "phases": {},
            "crown_jewel_accessed": False
        }
        
        try:
            # Phase 1: Compliance admin authentication
            login_result = await self.execute_compliance_login()
            session_results["phases"]["authentication"] = login_result
            
            if not login_result.get("success"):
                return session_results
            
            # Phase 2: Vault audit via webapp proxy
            # CRITICAL: Uses same crown jewel endpoints as red team
            audit_endpoints = CROWN_JEWEL_CONFIG["endpoints"].copy()
            
            # Randomize audit scope (sometimes skip non-critical endpoints)
            if random.choice([True, False]):
                audit_endpoints = [ep for ep in audit_endpoints if "/crown_jewel" in ep or "/admin" in ep]
            
            await ExternalTimingUtils.wait_with_jitter(3, 0.5)
            audit_results = await self.execute_vault_audit_via_proxy(compliance_user, audit_endpoints)
            session_results["phases"]["vault_audit"] = audit_results
            
            # Check if crown jewel was accessed
            session_results["crown_jewel_accessed"] = any(
                result.get("crown_jewel", False) and result.get("success", False)
                for result in audit_results
            )
            
            return session_results
            
        except Exception as e:
            self.logger.error(f"Compliance audit session error for {compliance_user}: {e}")
            
            session_results["error"] = str(e)
            return session_results
        
        finally:
            # Clean up session
            if compliance_user in self.audit_sessions:
                del self.audit_sessions[compliance_user]
    
    async def run_pattern(self):
        """Run the compliance audit pattern continuously"""
        self.logger.info("Starting external compliance audit pattern")
        
        # Check if crown jewel access is enabled
        if not CROWN_JEWEL_CONFIG["enabled"]:
            self.logger.warning("Crown jewel access disabled - compliance audit pattern will skip vault access")
        
        iteration_count = 0
        successful_audits = 0
        total_crown_jewel_accesses = 0
        
        try:
            while self.scheduler.should_continue_pattern(self.pattern_name):
                iteration_count += 1
                
                # Execute compliance audit session
                audit_result = await self.execute_compliance_audit_session()
                
                if not audit_result.get("error"):
                    successful_audits += 1
                    
                    if audit_result.get("crown_jewel_accessed"):
                        total_crown_jewel_accesses += 1
                        self.logger.warning(f"Crown jewel accessed via compliance audit (iteration {iteration_count})")
                
                # Record pattern iteration
                self.scheduler.record_pattern_iteration(self.pattern_name)
                
                # Wait for next iteration
                if self.scheduler.should_continue_pattern(self.pattern_name):
                    await ExternalTimingUtils.wait_for_pattern_interval(self.pattern_name)
                
        except asyncio.CancelledError:
            self.logger.info("Compliance audit pattern cancelled")
        except Exception as e:
            self.logger.error(f"Compliance audit pattern error: {e}")
        finally:
            self.logger.info(f"Compliance audit pattern completed after {iteration_count} iterations")
            self.logger.info(f"Total crown jewel accesses via compliance: {total_crown_jewel_accesses}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get pattern execution statistics"""
        return {
            "pattern_name": self.pattern_name,
            "active_sessions": len(self.audit_sessions),
            "crown_jewel_accesses": self.crown_jewel_accesses,
            "iterations": self.scheduler.get_pattern_iteration_count(self.pattern_name),
            "crown_jewel_enabled": CROWN_JEWEL_CONFIG["enabled"]
        }