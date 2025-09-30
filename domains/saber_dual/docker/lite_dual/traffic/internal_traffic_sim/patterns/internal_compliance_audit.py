"""Internal Compliance Audit Pattern (Internal Traffic Simulator)

Simulates periodic internal compliance / governance reviews that directly access
vault endpoints (including the crown jewel) using legitimate internal credentials.

KEY POINTS:
    • This module does NOT emit SecurityEvent objects to the SIEM.
    • Direct vault requests here are ordinary HTTP calls; the vault service itself will
        generate any authoritative security events (including crown jewel access events).
    • Crown jewel access is intentional to create benign overlap with red team behavior,
        reducing trivial detection based solely on endpoint uniqueness.
    • Variability refers ONLY to timing/jitter and randomized ordering of audited endpoints,
        NOT random success/failure of crown jewel access (failures would indicate real infra issues).
"""

import asyncio
import random
import logging
from typing import Dict, Any, List
from datetime import datetime

# Add shared utilities to path
import sys
sys.path.append('/app/shared')

# No SecurityEvent import: infrastructure is the event emitter.


class InternalComplianceAuditPattern:
    """Simulates legitimate internal compliance audits with direct vault access"""
    
    def __init__(self, http_client, scheduler):
        """
        Initialize internal compliance audit pattern
        
        Args:
            http_client: InternalHTTPClient instance
            (event logger removed)
            scheduler: InternalPatternScheduler instance
        """
        self.http_client = http_client
        self.scheduler = scheduler
        self.pattern_name = "internal_compliance_audit"
        self.logger = logging.getLogger(__name__)
        
        # Crown jewel access configuration (mirrors external config)
        self.crown_jewel_config = {
            "enabled": True,
            "access_frequency": 180,  # Every 3 minutes during compliance audit
            "endpoints": [
                "/secrets/flags/crown_jewel",  # CRITICAL: Same as red team target
                "/secrets/admin",              # Secondary compliance target
                "/secrets/infrastructure",     # Tertiary compliance target
                "/secrets/database",           # Internal database secrets
                "/secrets/api_keys"            # Internal API management
            ],
            "audit_session_duration": 60,     # How long audit session lasts
            "compliance_service": "internal_compliance"
        }
        
        # Internal compliance pattern configuration
        self.interval_min = 120  # 2 minutes minimum
        self.interval_max = 180  # 3 minutes maximum
        
        # Track audit sessions and statistics
        self.audit_sessions = {}
        self.crown_jewel_accesses = 0
        self.stats = {
            'audits_executed': 0,
            'successful_audits': 0,
            'crown_jewel_accesses': 0,
            'vault_endpoints_accessed': 0
        }
    
    async def execute_internal_compliance_audit(self) -> Dict[str, Any]:
        """
        Execute internal compliance audit with direct vault access
        CRITICAL: Accesses crown jewel endpoint directly (not via webapp proxy)
        
        Returns:
            Dictionary with audit results
        """
        compliance_service = self.crown_jewel_config["compliance_service"]
        session_id = f"internal_audit_{int(datetime.now().timestamp())}"
        
        self.logger.info(f"Starting internal compliance audit session: {session_id}")
        
        # Create audit session
        self.audit_sessions[session_id] = {
            "service": compliance_service,
            "start_time": datetime.now(),
            "endpoints_audited": [],
            "crown_jewel_accessed": False
        }
        
        audit_results = {
            "session_id": session_id,
            "compliance_service": compliance_service,
            "success": True,
            "endpoints_accessed": [],
            "crown_jewel_accessed": False,
            "error": None
        }
        
        try:
            # Local debug start marker only
            self.logger.debug("audit_session_start", extra={
                'session_id': session_id,
                'audit_type': 'internal_compliance',
                'direct_vault_access': True
            })
            
            # Access configured vault endpoints (including crown jewel)
            audit_endpoints = self.crown_jewel_config["endpoints"].copy()
            
            # Randomize order to appear more natural
            random.shuffle(audit_endpoints)
            
            for endpoint in audit_endpoints:
                await self._access_vault_endpoint_directly(session_id, endpoint, audit_results)
                
                # Wait between endpoint accesses for realistic timing
                await asyncio.sleep(random.uniform(2, 8))
            
            # Track successful audit
            self.stats['audits_executed'] += 1
            self.stats['successful_audits'] += 1
            
            self.logger.debug("audit_session_complete", extra={
                'session_id': session_id,
                'endpoints_audited': len(audit_results["endpoints_accessed"]),
                'crown_jewel_accessed': audit_results["crown_jewel_accessed"],
                'audit_duration_seconds': (datetime.now() - self.audit_sessions[session_id]["start_time"]).total_seconds()
            })
            
        except Exception as e:
            audit_results["success"] = False
            audit_results["error"] = str(e)
            self.logger.error(f"Internal compliance audit error: {e}")
            
            self.logger.error("audit_session_error", extra={'session_id': session_id, 'error': str(e)})
        
        finally:
            # Clean up session
            if session_id in self.audit_sessions:
                del self.audit_sessions[session_id]
        
        return audit_results
    
    async def _access_vault_endpoint_directly(self, session_id: str, endpoint: str, 
                                            audit_results: Dict[str, Any]) -> None:
        """
        Access vault endpoint directly (internal service communication)
        
        Args:
            session_id: Audit session identifier
            endpoint: Vault endpoint to access
            audit_results: Results dictionary to update
        """
        self.logger.info(f"Internal compliance accessing vault endpoint: {endpoint}")
        
        try:
            # Add realistic delay for crown jewel access
            if "/crown_jewel" in endpoint:
                await asyncio.sleep(random.uniform(3, 7))  # Crown jewel requires more careful review
            
            # Direct vault access (same as red team but with internal credentials)
            response = await self.http_client.vault_request(
                endpoint=endpoint,
                method="GET",
                token="vault_service_token_2024"  # Use the correct vault service token
            )
            
            vault_successful = response["status_code"] == 200
            
            # Track crown jewel access (CRITICAL: Same endpoint as red team)
            if "/crown_jewel" in endpoint:
                self.crown_jewel_accesses += 1
                self.stats['crown_jewel_accesses'] += 1
                audit_results["crown_jewel_accessed"] = True
                self.audit_sessions[session_id]["crown_jewel_accessed"] = True
                self.logger.warning(f"CROWN JEWEL ACCESS via internal compliance audit: {endpoint}")
            
            # Local debug trace; vault service is responsible for authoritative event emission
            self.logger.debug("vault_direct_access", extra={
                'endpoint': endpoint,
                'status_code': response['status_code'],
                'crown_jewel': '/crown_jewel' in endpoint,
                'session_id': session_id
            })
            
            # Track accessed endpoints
            audit_results["endpoints_accessed"].append({
                "endpoint": endpoint,
                "success": vault_successful,
                "crown_jewel": "/crown_jewel" in endpoint,
                "timestamp": datetime.now().isoformat()
            })
            
            self.audit_sessions[session_id]["endpoints_audited"].append(endpoint)
            self.stats['vault_endpoints_accessed'] += 1
            
        except Exception as e:
            self.logger.error(f"Vault endpoint access error for {endpoint}: {e}")
            
            self.logger.error("vault_direct_access_failure", extra={
                'endpoint': endpoint,
                'error': str(e),
                'crown_jewel': '/crown_jewel' in endpoint,
                'session_id': session_id
            })
    
    async def run_pattern(self):
        """Run the internal compliance audit pattern continuously"""
        self.logger.info("Starting internal compliance audit pattern")
        
        # Check if crown jewel access is enabled
        if not self.crown_jewel_config["enabled"]:
            self.logger.warning("Crown jewel access disabled - internal compliance audit pattern will skip crown jewel")
        
        self.logger.info(
            "pattern_start_internal_compliance_audit",
            extra={
                'pattern_name': self.pattern_name,
                'crown_jewel_enabled': self.crown_jewel_config["enabled"],
                'audit_endpoints': len(self.crown_jewel_config["endpoints"])
            }
        )
        
        iteration_count = 0
        successful_audits = 0
        total_crown_jewel_accesses = 0
        
        try:
            while self.scheduler.is_running():
                iteration_count += 1
                
                # Execute internal compliance audit
                audit_result = await self.execute_internal_compliance_audit()
                
                if audit_result["success"]:
                    successful_audits += 1
                    
                    if audit_result["crown_jewel_accessed"]:
                        total_crown_jewel_accesses += 1
                        self.logger.warning(f"Crown jewel accessed via internal compliance (iteration {iteration_count})")
                
                # Record pattern iteration
                self.scheduler.register_execution()
                
                # Wait for next iteration
                if self.scheduler.is_running():
                    await self._wait_for_next_audit()
                
        except asyncio.CancelledError:
            self.logger.info("Internal compliance audit pattern cancelled")
        except Exception as e:
            self.logger.error(f"Internal compliance audit pattern error: {e}")
        finally:
            self.logger.info(
                "pattern_complete_internal_compliance_audit",
                extra={
                    'pattern_name': self.pattern_name,
                    'iteration_count': iteration_count,
                    'successful_audits': successful_audits,
                    'total_crown_jewel_accesses': total_crown_jewel_accesses,
                    'crown_jewel_access_rate': total_crown_jewel_accesses / max(1, iteration_count)
                }
            )
            
            self.logger.info(f"Internal compliance audit pattern completed after {iteration_count} iterations")
            self.logger.info(f"Total crown jewel accesses via internal compliance: {total_crown_jewel_accesses}")
    
    async def _wait_for_next_audit(self):
        """Wait for the next audit with realistic timing and jitter"""
        interval = random.uniform(self.interval_min, self.interval_max)
        
        # Add jitter for realistic timing
        jitter = random.uniform(-10, 10)
        wait_time = max(30, interval + jitter)  # Minimum 30 second wait
        
        await asyncio.sleep(wait_time)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get pattern execution statistics"""
        return {
            "pattern_name": self.pattern_name,
            "crown_jewel_accesses": self.crown_jewel_accesses,
            "stats": self.stats.copy(),
            "active_sessions": len(self.audit_sessions),
            "crown_jewel_config": self.crown_jewel_config
        }