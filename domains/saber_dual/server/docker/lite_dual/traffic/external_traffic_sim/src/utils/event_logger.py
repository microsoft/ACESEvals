"""
External Traffic Simulator - Local Debug Event Logger

IMPORTANT: This logger NEVER emits security events to the SIEM. The design
relies on indirect event generation: the simulator performs realistic HTTP
interactions against the webapp (DMZ) which in turn causes the infrastructure
containers (webapp, api_gateway, vault, database) to emit authoritative
SecurityEvent records.

This module is strictly for:
    * Local timing/debug visibility
    * Pattern execution tracing
    * Session correlation during development

It MUST NOT be extended to push SecurityEvent objects directly to the SIEM.
Remove or reject any future code that attempts direct ingestion from traffic
containers.
"""

import os
import logging
from typing import Dict, Any, Optional
import uuid
from datetime import datetime


class ExternalTrafficEventLogger:
    """Local event logger for external traffic simulation debugging"""
    
    def __init__(self, log_dir: str = "/var/log/traffic"):
        """
        Initialize external traffic event logger for local debugging only
        
        Args:
            log_dir: Directory to write local log files
        """
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        
        # Set up local Python logging (not SIEM)
        self.logger = logging.getLogger("external_traffic_sim")
        if not self.logger.handlers:
            handler = logging.FileHandler(os.path.join(log_dir, "traffic_debug.log"))
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
        
        self.session_counter = 0
    
    def create_new_session(self) -> str:
        """Create a new session ID for traffic correlation"""
        self.session_counter += 1
        return f"external_traffic_session_{self.session_counter}_{uuid.uuid4().hex[:8]}"
    
    def log_employee_access(self, username: str, success: bool, user_agent: str = None, 
                          data: Optional[Dict[str, Any]] = None):
        """Log employee portal access event locally (for debugging)"""
        self.logger.info(f"Employee access: {username} {'success' if success else 'failed'}")
    
    def log_admin_maintenance(self, admin_user: str, maintenance_type: str, 
                            success: bool, data: Optional[Dict[str, Any]] = None):
        """Log admin maintenance activity locally (for debugging)"""
        self.logger.info(f"Admin maintenance: {admin_user} - {maintenance_type} {'success' if success else 'failed'}")
    
    def log_compliance_audit(self, audit_endpoint: str, compliance_user: str, success: bool,
                           data: Optional[Dict[str, Any]] = None):
        """Log compliance audit activity locally (for debugging)"""
        self.logger.info(f"Compliance audit: {compliance_user} -> {audit_endpoint} {'success' if success else 'failed'}")
    
    def log_red_herring(self, herring_type: str, data: Optional[Dict[str, Any]] = None):
        """Log red herring activity locally (for debugging)"""
        self.logger.info(f"Red herring: {herring_type}")
    
    def log_pattern_execution(self, pattern_name: str, status: str, data: Optional[Dict[str, Any]] = None):
        """Log pattern execution status locally (for debugging)"""
        self.logger.info(f"Pattern {pattern_name}: {status}")
    
    def log_simulation_event(self, event_type: str, message: str, data: Optional[Dict[str, Any]] = None):
        """Log general simulation events locally (for debugging)"""
        self.logger.info(f"{event_type}: {message}")
    
    def get_session_id(self) -> str:
        """Get current session ID"""
        return f"external_traffic_session_{self.session_counter}"