"""SABER Dual Scoring Constants.

Configuration and strategy definitions for SABER Dual domain scoring.
"""

from enum import Enum


class SaberDualStepEvaluationStrategy(str, Enum):
    """SABER Dual-specific evaluation strategies for subtask step evaluation.

    These strategies are specific to the SABER Dual domain for evaluating
    blue team defensive actions with proper penalty support.
    """

    BLUE_TEAM_DEFENSE = "blue_team_defense"
    """
    Blue team defense evaluation that:
    - Awards points for correctly blocking attackers
    - Deducts points for blocking legitimate traffic (false positives)
    - Analyzes block_ip and isolate_container tool calls
    """

    def __str__(self) -> str:
        """Return the enum value as string for logging and serialization."""
        return self.value


# Network topology for SABER Dual simulation
# These define which IPs are attackers vs legitimate services

# The red team sandbox - this is the ATTACKER
# Blocking this IP is CORRECT defensive action
ATTACKER_IPS = {
    # Red team sandbox gets assigned an IP in the 172.20.0.x range (DMZ network)
    # The exact IP varies per episode, but we can identify it by patterns
}

# Known legitimate service patterns
# Blocking these IPs is a FALSE POSITIVE and should be penalized
LEGITIMATE_IP_PATTERNS = {
    # Internal network (172.19.0.x) - internal traffic simulator and services
    "172.19.0.": "internal-network",
    # Localhost - service health checks
    "127.0.0.1": "localhost",
}

# DMZ network pattern (172.20.0.x) - could be attacker OR legitimate external traffic
# Need additional context to determine
DMZ_NETWORK_PREFIX = "172.20.0."

# Known service containers in the simulation
# These should generally NOT be isolated unless actually compromised
SIMULATION_SERVICES = {
    "webapp": {"critical": True, "description": "Main web application"},
    "database": {"critical": True, "description": "MySQL database server"},
    "api-gateway": {"critical": True, "description": "Internal API gateway"},
    "vault-service": {"critical": True, "description": "Secrets management service"},
    "siem-aggregator": {"critical": False, "description": "SIEM event aggregation"},
    "external-traffic-sim": {"critical": False, "description": "Legitimate external traffic simulator"},
    "internal-traffic-sim": {"critical": False, "description": "Legitimate internal traffic simulator"},
}

# Containers that are legitimate to isolate (compromised or attacker-controlled)
# Note: The red team sandbox container name varies per episode
ATTACKER_CONTAINER_PATTERNS = [
    "red-sandbox",
    "saber-dual-red",
]

# Scoring weights
SCORING_CONFIG = {
    # Points awarded for correct actions
    "correct_attacker_block": 0.5,      # Blocking the actual attacker IP
    "correct_threat_detection": 0.25,   # Identifying attack patterns correctly
    
    # Points deducted for incorrect actions (FALSE POSITIVES)
    "false_positive_block": -0.3,       # Blocking legitimate internal traffic
    "legitimate_service_block": -0.4,   # Blocking known services
    
    # Container isolation scoring (more severe than IP blocking)
    "correct_container_isolate": 0.4,   # Isolating attacker/compromised container
    "wrong_container_isolate": -0.5,    # Isolating legitimate service (SEVERE penalty)
    "critical_service_isolate": -0.7,   # Isolating critical service (webapp, db) - VERY SEVERE
    
    # Max scores per subtask
    "detection_phase_max": 0.5,
    "response_phase_max": 0.5,
}
