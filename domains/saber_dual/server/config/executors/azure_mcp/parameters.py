"""
Shared parameter dataclasses for Azure MCP executors.

These implement the ExecutorParameters protocol required by SABER.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True, slots=True)
class AzureMCPParameters:
    """Base parameters for Azure MCP namespace-style executors."""
    
    command: str
    parameters: Dict[str, Any]
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AzureMCPParameters":
        """Create from dictionary with validation."""
        command = data.get("command")
        if not command:
            raise ValueError("command is required")
        parameters = data.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ValueError("parameters must be a dictionary")
        return cls(command=command, parameters=parameters)


# Alias for each executor type - they all use the same parameter structure
MonitorParameters = AzureMCPParameters
SqlParameters = AzureMCPParameters
KeyvaultParameters = AzureMCPParameters  
ResourcehealthParameters = AzureMCPParameters
SubscriptionParameters = AzureMCPParameters
