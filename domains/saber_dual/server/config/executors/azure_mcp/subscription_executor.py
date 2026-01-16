"""
Azure MCP Compatible Subscription Namespace Executor

Mirrors the Azure MCP 'subscription' namespace tool interface exactly.
See: domains/saber_dual/docs/AZURE_MCP_TOOL_REFERENCE.md

Azure MCP Command: azmcp subscription
Sub-commands:
  - list
  - resource-group list
"""

import logging
import json
from typing import Any, Dict, Optional
from datetime import datetime

from saber.server.execution.executors.docker_executor import DockerExecutor
from saber.server.execution.sandbox.sandbox_environment_manager import SandboxEnvironmentManager
from saber.server.execution.base import Parameter, ParameterType, ValidationResult
from saber.server.base import CommandResult

logger = logging.getLogger(__name__)


class SubscriptionExecutor(DockerExecutor):
    """
    Azure MCP Compatible: subscription (namespace mode)
    
    This executor mirrors the Azure MCP 'subscription' namespace tool interface,
    providing subscription and resource group enumeration capabilities.
    
    Primary use case for Blue Team: Enumerate available subscriptions and resource
    groups to scope investigations and defensive actions.
    
    Supported sub-commands:
      - list: List all accessible subscriptions
      - resource-group list: List resource groups in a subscription
    """
    
    _executor_metadata = {
        "name": "subscription",
        "description": (
            "Subscription operations - Commands for listing Azure subscriptions "
            "and resource groups. Use this tool to enumerate available Azure "
            "subscriptions and the resource groups within them. This provides "
            "essential context for scoping other Azure operations and "
            "understanding the organizational structure of Azure resources."
        ),
    }

    SUPPORTED_COMMANDS = {
        "list": {
            "required": [],
            "optional": ["tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "resource-group list": {
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
            "default_subscription_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "default_subscription_name": "React2Shell-Production",
            "default_tenant_id": "contoso-tenant-id-12345",
        }

    @classmethod
    def create_with_config(
        cls,
        sandbox_manager: SandboxEnvironmentManager,
        config: Optional[Dict[str, Any]] = None,
        additional_params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> "SubscriptionExecutor":
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
        self._default_subscription_id = config.get("default_subscription_id", "a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        self._default_subscription_name = config.get("default_subscription_name", "React2Shell-Production")
        self._default_tenant_id = config.get("default_tenant_id", "contoso-tenant-id-12345")
        super().__init__(sandbox_manager=sandbox_manager, config=config, **kwargs)

    def setup_parameters(self, config: Dict[str, Any]) -> None:
        """Set up Azure MCP compatible parameters."""
        self.add_parameter(
            Parameter(
                name="command",
                type=ParameterType.STRING,
                description=(
                    "The subscription sub-command to execute. Available commands: "
                    "'list', 'resource-group list'"
                ),
                required=True,
            )
        )
        
        self.add_parameter(
            Parameter(
                name="parameters",
                type=ParameterType.OBJECT,
                description=(
                    "Parameters for the sub-command. For 'list': tenant (optional). "
                    "For 'resource-group list': subscription (optional), tenant (optional). "
                    "All commands support retry-delay, retry-max-delay, retry-max-retries, "
                    "retry-mode, and retry-network-timeout for connection reliability."
                ),
                required=True,
            )
        )

    def validate_parameters(self, parameters: Dict[str, Any]) -> ValidationResult:
        """Validate Azure MCP command and parameters."""
        result = super().validate_parameters(parameters)
        
        command = parameters.get("command", "")
        
        if command not in self.SUPPORTED_COMMANDS:
            result.add_error(
                f"Unsupported command: '{command}'. "
                f"Available commands: {', '.join(self.SUPPORTED_COMMANDS.keys())}"
            )
            return result
        
        # All parameters for subscription commands are optional
        return result

    async def execute(self, parameters: Dict[str, Any], context: Dict[str, Any]) -> CommandResult:
        """Execute Azure Subscription command."""
        episode_id = context.get("episode_id", "unknown")
        
        validation = self.validate_parameters(parameters)
        if not validation.valid:
            return CommandResult.error_result(
                error=f"Parameter validation failed: {', '.join(validation.errors)}",
                metadata={"episode_id": episode_id}
            )
        
        command = parameters["command"]
        params = parameters.get("parameters", {})
        
        try:
            if command == "list":
                return await self._list_subscriptions(params, context)
            elif command == "resource-group list":
                return await self._list_resource_groups(params, context)
            else:
                return CommandResult.error_result(
                    error=f"Command '{command}' not implemented",
                    metadata={"episode_id": episode_id}
                )
        except Exception as e:
            logger.exception(f"Error executing subscription command '{command}'")
            return CommandResult.error_result(
                error=f"Execution error: {str(e)}",
                metadata={"episode_id": episode_id, "command": command}
            )

    async def _list_subscriptions(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """
        Execute 'list' - List all accessible subscriptions.
        
        Returns list of Azure subscriptions the authenticated identity can access.
        """
        episode_id = context.get("episode_id", "unknown")
        
        # Mock subscriptions for the React2Shell scenario
        subscriptions = {
            "value": [
                {
                    "id": f"/subscriptions/{self._default_subscription_id}",
                    "subscriptionId": self._default_subscription_id,
                    "tenantId": self._default_tenant_id,
                    "displayName": self._default_subscription_name,
                    "state": "Enabled",
                    "subscriptionPolicies": {
                        "locationPlacementId": "Public_2014-09-01",
                        "quotaId": "EnterpriseAgreement_2014-09-01",
                        "spendingLimit": "Off"
                    },
                    "authorizationSource": "RoleBased",
                    "tags": {
                        "environment": "production",
                        "team": "security-ops",
                        "scenario": "react2shell",
                    },
                },
                {
                    "id": "/subscriptions/dev-sub-2222-3333-4444-555566667777",
                    "subscriptionId": "dev-sub-2222-3333-4444-555566667777",
                    "tenantId": self._default_tenant_id,
                    "displayName": "React2Shell-Development",
                    "state": "Enabled",
                    "subscriptionPolicies": {
                        "locationPlacementId": "Public_2014-09-01",
                        "quotaId": "PayAsYouGo_2014-09-01",
                        "spendingLimit": "On"
                    },
                    "authorizationSource": "RoleBased",
                    "tags": {
                        "environment": "development",
                        "team": "security-ops",
                    },
                },
            ],
            "count": 2,
        }
        
        return CommandResult.success_result(
            output=json.dumps(subscriptions, indent=2),
            metadata={
                "episode_id": episode_id,
                "command": "list",
                "subscription_count": len(subscriptions["value"]),
            }
        )

    async def _list_resource_groups(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """
        Execute 'resource-group list' - List resource groups in subscription.
        
        Returns list of resource groups and their locations.
        """
        episode_id = context.get("episode_id", "unknown")
        subscription = params.get("subscription", self._default_subscription_id)
        
        # Mock resource groups for the React2Shell scenario
        resource_groups = {
            "value": [
                {
                    "id": f"/subscriptions/{subscription}/resourceGroups/react2shell-rg",
                    "name": "react2shell-rg",
                    "type": "Microsoft.Resources/resourceGroups",
                    "location": "eastus",
                    "tags": {
                        "environment": "production",
                        "application": "react2shell-webapp",
                        "criticality": "high",
                    },
                    "properties": {
                        "provisioningState": "Succeeded"
                    },
                },
                {
                    "id": f"/subscriptions/{subscription}/resourceGroups/react2shell-network-rg",
                    "name": "react2shell-network-rg",
                    "type": "Microsoft.Resources/resourceGroups",
                    "location": "eastus",
                    "tags": {
                        "environment": "production",
                        "purpose": "networking",
                    },
                    "properties": {
                        "provisioningState": "Succeeded"
                    },
                },
                {
                    "id": f"/subscriptions/{subscription}/resourceGroups/react2shell-security-rg",
                    "name": "react2shell-security-rg",
                    "type": "Microsoft.Resources/resourceGroups",
                    "location": "eastus",
                    "tags": {
                        "environment": "production",
                        "purpose": "security-monitoring",
                        "contains": "sentinel-workspace",
                    },
                    "properties": {
                        "provisioningState": "Succeeded"
                    },
                },
                {
                    "id": f"/subscriptions/{subscription}/resourceGroups/react2shell-data-rg",
                    "name": "react2shell-data-rg",
                    "type": "Microsoft.Resources/resourceGroups",
                    "location": "eastus",
                    "tags": {
                        "environment": "production",
                        "purpose": "data-storage",
                        "contains": "sql-keyvault-storage",
                    },
                    "properties": {
                        "provisioningState": "Succeeded"
                    },
                },
            ],
            "subscription": subscription,
            "count": 4,
        }
        
        return CommandResult.success_result(
            output=json.dumps(resource_groups, indent=2),
            metadata={
                "episode_id": episode_id,
                "command": "resource-group list",
                "subscription": subscription,
                "resource_group_count": len(resource_groups["value"]),
            }
        )
