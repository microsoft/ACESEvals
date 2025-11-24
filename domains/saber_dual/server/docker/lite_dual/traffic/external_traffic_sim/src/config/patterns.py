"""
External Traffic Simulator - Pattern Configuration

Timing and behavior configuration for external traffic patterns.
"""

from dataclasses import dataclass
from typing import Dict, Any, List


@dataclass
class PatternConfig:
    """Configuration for a traffic pattern"""
    
    name: str
    enabled: bool = True
    base_interval: int = 60  # Base interval in seconds
    variance_percent: float = 0.2  # Variance percentage
    max_iterations: int = -1  # -1 for unlimited during simulation
    priority: int = 1  # 1=high, 2=medium, 3=low
    
    def get_interval_range(self) -> tuple:
        """Get the min/max interval range"""
        variance = self.base_interval * self.variance_percent
        return (
            self.base_interval - variance,
            self.base_interval + variance
        )


# External traffic pattern configurations
EXTERNAL_PATTERNS = {
    "employee_access": PatternConfig(
        name="Employee Portal Access",
        enabled=True,
        base_interval=17,      # 17 seconds base
        variance_percent=0.25, # ±25% = 13-21 seconds
        priority=1
    ),
    
    "admin_maintenance": PatternConfig(
        name="Admin Maintenance",
        enabled=True,
        base_interval=20,      # 20 seconds base  
        variance_percent=0.2,  # ±20% = 16-24 seconds
        priority=2
    ),
    
    "compliance_audit": PatternConfig(
        name="External Compliance Audit",
        enabled=True,
        base_interval=22,      # 22 seconds base
        variance_percent=0.15, # ±15% = 19-25 seconds
        priority=1
    ),
    
    "red_herrings": PatternConfig(
        name="Red Herring Activities",
        enabled=True,
        base_interval=15,      # 15 seconds base
        variance_percent=0.33, # ±33% = 10-20 seconds
        priority=3
    )
}


# Crown jewel access configuration
CROWN_JEWEL_CONFIG = {
    "enabled": True,
    "access_frequency": 30,   # Every 30 seconds during compliance audit
    "endpoints": [
        "/secrets/flags/crown_jewel",  # Primary target (same as red team)
        "/secrets/admin",              # Secondary compliance target
        "/secrets/infrastructure"      # Tertiary compliance target
    ],
    "audit_session_duration": 60,     # How long audit session lasts
    "compliance_user": "security.audit"  # Use existing database user for compliance
}


# Red herring configuration
RED_HERRING_CONFIG = {
    "failed_login_frequency": 120,    # Every 2 minutes
    "sql_query_frequency": 180,       # Every 3 minutes  
    "monitoring_check_frequency": 90, # Every 1.5 minutes
    "suspicious_patterns": [
        "multiple_failed_logins",
        "union_sql_queries", 
        "monitoring_failures"
    ]
}


# Simulation lifecycle configuration
SIMULATION_CONFIG = {
    "startup_delay_max": 30,      # Max random startup delay in seconds
    "graceful_shutdown_time": 10, # Time to wait for graceful shutdown
    "pattern_overlap_allowed": True,  # Allow patterns to run concurrently
    "error_retry_attempts": 3,    # Number of retries for failed requests
    "error_retry_delay": 5        # Delay between retries in seconds
}


def get_pattern_config(pattern_name: str) -> PatternConfig:
    """Get configuration for a specific pattern"""
    return EXTERNAL_PATTERNS.get(pattern_name, PatternConfig(name="Unknown"))


def get_enabled_patterns() -> List[str]:
    """Get list of enabled pattern names"""
    return [name for name, config in EXTERNAL_PATTERNS.items() if config.enabled]


def get_pattern_summary() -> Dict[str, Any]:
    """Get summary of all pattern configurations"""
    return {
        "total_patterns": len(EXTERNAL_PATTERNS),
        "enabled_patterns": len(get_enabled_patterns()),
        "crown_jewel_enabled": CROWN_JEWEL_CONFIG["enabled"],
        "patterns": {name: config.name for name, config in EXTERNAL_PATTERNS.items()}
    }