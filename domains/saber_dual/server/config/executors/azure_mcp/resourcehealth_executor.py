"""
Azure MCP Compatible ResourceHealth Namespace Executor

Mirrors the Azure MCP 'resourcehealth' namespace tool interface exactly.
See: domains/saber_dual/docs/AZURE_MCP_TOOL_REFERENCE.md

Azure MCP Command: azmcp resourcehealth
Sub-commands:
  - availability-status get
  - availability-status list
  - health-events list
"""

import logging
import json
from typing import Any, Dict, Optional
from datetime import datetime, timedelta

from saber.server.execution.executors.docker_executor import DockerExecutor
from saber.server.execution.sandbox.sandbox_environment_manager import SandboxEnvironmentManager
from saber.server.execution.base import Parameter, ParameterType, ValidationResult
from saber.server.base import CommandResult

logger = logging.getLogger(__name__)


class ResourcehealthExecutor(DockerExecutor):
    """
    Azure MCP Compatible: resourcehealth (namespace mode)
    
    This executor mirrors the Azure MCP 'resourcehealth' namespace tool interface,
    providing resource health status monitoring capabilities.
    
    Primary use case for Blue Team: Monitor resource availability during incident,
    detect compromised resources showing degraded health.
    
    Supported sub-commands:
      - availability-status get: Get availability status for specific resource
      - availability-status list: List availability statuses for subscription/resource group
      - health-events list: List health events for subscription
    """
    
    _executor_metadata = {
        "name": "resourcehealth",
        "description": (
            "Resource Health operations - Commands for monitoring and diagnosing "
            "Azure resource health status. Use this tool to check the current "
            "availability status of Azure resources and identify potential issues. "
            "This tool provides access to Azure Resource Health data including "
            "availability state, detailed status, historical health information, "
            "and service health events for troubleshooting and monitoring purposes."
        ),
    }

    SUPPORTED_COMMANDS = {
        "availability-status get": {
            "required": ["resource-group", "resource-type", "resource-name"],
            "optional": ["subscription", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "availability-status list": {
            "required": [],
            "optional": ["subscription", "resource-group", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "health-events list": {
            "required": [],
            "optional": ["subscription", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
    }

    @classmethod
    def get_default_config(cls) -> Dict[str, Any]:
        return {
            "timeout": 30.0,
            "siem_base_url": "http://siem-aggregator:8080",
            "default_subscription": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "default_resource_group": "react2shell-rg",
        }

    @classmethod
    def create_with_config(
        cls,
        sandbox_manager: SandboxEnvironmentManager,
        config: Optional[Dict[str, Any]] = None,
        additional_params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> "ResourcehealthExecutor":
        merged_kwargs = {**kwargs}
        if additional_params:
            merged_kwargs.update(additional_params)
        return cls(sandbox_manager=sandbox_manager, config=config, **merged_kwargs)

    def __init__(
        self,
        sandbox_manager: SandboxEnvironmentManager,
        config: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        config = config or {}
        self._siem_base_url = config.get("siem_base_url", "http://siem-aggregator:8080")
        self._default_subscription = config.get("default_subscription", "a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        self._default_resource_group = config.get("default_resource_group", "react2shell-rg")
        super().__init__(sandbox_manager=sandbox_manager, config=config, **kwargs)

    def setup_parameters(self, config: Dict[str, Any]) -> None:
        """Set up Azure MCP compatible parameters."""
        self.add_parameter(
            Parameter(
                name="command",
                type=ParameterType.STRING,
                description=(
                    "The resourcehealth sub-command to execute. Available commands: "
                    "'availability-status get', 'availability-status list', 'health-events list'"
                ),
                required=True,
            )
        )
        
        self.add_parameter(
            Parameter(
                name="parameters",
                type=ParameterType.OBJECT,
                description=(
                    "Parameters for the sub-command. For 'availability-status get': "
                    "resource-group (required), resource-type (required), resource-name (required), "
                    "subscription. For 'availability-status list': subscription, resource-group. "
                    "For 'health-events list': subscription."
                ),
                required=True,
            )
        )

    def validate_parameters(self, parameters: Dict[str, Any]) -> ValidationResult:
        """Validate Azure MCP command and parameters."""
        result = super().validate_parameters(parameters)
        
        command = parameters.get("command", "")
        params = parameters.get("parameters", {})
        
        if command not in self.SUPPORTED_COMMANDS:
            result.add_error(
                f"Unsupported command: '{command}'. "
                f"Available commands: {', '.join(self.SUPPORTED_COMMANDS.keys())}"
            )
            return result
        
        cmd_spec = self.SUPPORTED_COMMANDS[command]
        for req_param in cmd_spec["required"]:
            if req_param not in params or params[req_param] is None:
                result.add_error(f"Missing required parameter '{req_param}' for command '{command}'")
        
        return result

    async def execute(self, parameters: Dict[str, Any], context: Dict[str, Any]) -> CommandResult:
        """Execute Azure Resource Health command."""
        episode_id = context.get("episode_id", "unknown")
        
        validation = self.validate_parameters(parameters)
        if not validation.valid:
            return CommandResult.error_result(
                error=f"Parameter validation failed: {', '.join(validation.errors)}",
                metadata={"episode_id": episode_id}
            )
        
        command = parameters["command"]
        params = parameters["parameters"]
        
        try:
            if command == "availability-status get":
                return await self._get_availability_status(params, context)
            elif command == "availability-status list":
                return await self._list_availability_status(params, context)
            elif command == "health-events list":
                return await self._list_health_events(params, context)
            else:
                return CommandResult.error_result(
                    error=f"Command '{command}' not implemented",
                    metadata={"episode_id": episode_id}
                )
        except Exception as e:
            logger.exception(f"Error executing resourcehealth command '{command}'")
            return CommandResult.error_result(
                error=f"Execution error: {str(e)}",
                metadata={"episode_id": episode_id, "command": command}
            )

    async def _get_availability_status(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """
        Execute 'availability-status get' - Get health status for specific resource.
        
        Returns availability state and details for a specific Azure resource.
        """
        episode_id = context.get("episode_id", "unknown")
        
        resource_group = params.get("resource-group", self._default_resource_group)
        resource_type = params["resource-type"]
        resource_name = params["resource-name"]
        subscription = params.get("subscription", self._default_subscription)
        
        # Determine health status based on resource type and name
        # In the React2Shell scenario, compromised resources may show degraded health
        availability_state = "Available"
        summary = "Resource is healthy and operating normally."
        
        # Check for known attack indicators
        if "webapp" in resource_name.lower() or "app" in resource_name.lower():
            # Web app might be compromised
            availability_state = "Degraded"
            summary = "Resource is experiencing intermittent issues. Elevated CPU and memory usage detected."
        
        resource_id = f"/subscriptions/{subscription}/resourceGroups/{resource_group}/providers/{resource_type}/{resource_name}"
        
        status = {
            "id": f"{resource_id}/providers/Microsoft.ResourceHealth/availabilityStatuses/current",
            "name": "current",
            "type": "Microsoft.ResourceHealth/availabilityStatuses",
            "location": "eastus",
            "properties": {
                "availabilityState": availability_state,
                "summary": summary,
                "detailedStatus": availability_state,
                "reasonType": "Unplanned" if availability_state != "Available" else "",
                "occuredTime": datetime.utcnow().isoformat() + "Z",
                "reportedTime": datetime.utcnow().isoformat() + "Z",
                "resourceId": resource_id,
            },
            "subscription": subscription,
            "resourceGroup": resource_group,
            "resourceName": resource_name,
        }
        
        return CommandResult.success_result(
            output=json.dumps(status, indent=2),
            metadata={
                "episode_id": episode_id,
                "command": "availability-status get",
                "resource_name": resource_name,
                "availability_state": availability_state,
            }
        )

    async def _list_availability_status(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """
        Execute 'availability-status list' - List availability statuses.
        
        Returns availability statuses for all resources in scope.
        """
        episode_id = context.get("episode_id", "unknown")
        
        subscription = params.get("subscription", self._default_subscription)
        resource_group = params.get("resource-group", "")
        
        # Mock resources in the React2Shell scenario
        resources = [
            {
                "name": "react2shell-webapp",
                "type": "Microsoft.Web/sites",
                "availabilityState": "Degraded",
                "summary": "Elevated CPU usage and suspicious outbound connections detected.",
            },
            {
                "name": "react2shell-sql",
                "type": "Microsoft.Sql/servers",
                "availabilityState": "Available",
                "summary": "Resource is healthy.",
            },
            {
                "name": "react2shell-keyvault",
                "type": "Microsoft.KeyVault/vaults",
                "availabilityState": "Available",
                "summary": "Resource is healthy. Recent access from new principals detected.",
            },
            {
                "name": "react2shell-storage",
                "type": "Microsoft.Storage/storageAccounts",
                "availabilityState": "Available",
                "summary": "Resource is healthy. Elevated read operations in last hour.",
            },
            {
                "name": "react2shell-sentinel",
                "type": "Microsoft.OperationalInsights/workspaces",
                "availabilityState": "Available",
                "summary": "Resource is healthy.",
            },
        ]
        
        response = {
            "value": [
                {
                    "id": f"/subscriptions/{subscription}/resourceGroups/{self._default_resource_group}/providers/{r['type']}/{r['name']}/providers/Microsoft.ResourceHealth/availabilityStatuses/current",
                    "name": "current",
                    "type": "Microsoft.ResourceHealth/availabilityStatuses",
                    "properties": {
                        "availabilityState": r["availabilityState"],
                        "summary": r["summary"],
                        "reportedTime": datetime.utcnow().isoformat() + "Z",
                    },
                    "resourceName": r["name"],
                    "resourceType": r["type"],
                }
                for r in resources
            ],
            "subscription": subscription,
        }
        
        return CommandResult.success_result(
            output=json.dumps(response, indent=2),
            metadata={
                "episode_id": episode_id,
                "command": "availability-status list",
                "resource_count": len(resources),
            }
        )

    async def _list_health_events(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """
        Execute 'health-events list' - List health events.
        
        Returns service health events affecting the subscription.
        """
        episode_id = context.get("episode_id", "unknown")
        subscription = params.get("subscription", self._default_subscription)
        
        now = datetime.utcnow()
        
        # Mock health events relevant to the scenario
        events = {
            "value": [
                {
                    "name": "SIEM_Alert_001",
                    "type": "Microsoft.ResourceHealth/events",
                    "properties": {
                        "eventType": "SecurityAdvisory",
                        "eventSource": "ResourceHealth",
                        "status": "Active",
                        "title": "Suspicious Activity Detected - CVE-2025-55182",
                        "summary": "Potential exploitation of React Server Components vulnerability detected. Monitor App Service resources for unusual IMDS access patterns.",
                        "header": "Security Advisory",
                        "impactStartTime": (now - timedelta(hours=1)).isoformat() + "Z",
                        "lastUpdateTime": now.isoformat() + "Z",
                        "level": "Warning",
                        "impactedServices": [
                            {"serviceName": "App Service"},
                            {"serviceName": "Key Vault"},
                        ],
                    },
                },
                {
                    "name": "Network_Event_002",
                    "type": "Microsoft.ResourceHealth/events",
                    "properties": {
                        "eventType": "ServiceIssue",
                        "eventSource": "ResourceHealth",
                        "status": "Resolved",
                        "title": "Network Latency Increase - East US",
                        "summary": "Temporary increase in network latency resolved.",
                        "impactStartTime": (now - timedelta(hours=4)).isoformat() + "Z",
                        "impactEndTime": (now - timedelta(hours=3)).isoformat() + "Z",
                        "lastUpdateTime": (now - timedelta(hours=3)).isoformat() + "Z",
                        "level": "Informational",
                    },
                },
            ],
            "subscription": subscription,
        }
        
        return CommandResult.success_result(
            output=json.dumps(events, indent=2),
            metadata={
                "episode_id": episode_id,
                "command": "health-events list",
                "event_count": len(events["value"]),
            }
        )
