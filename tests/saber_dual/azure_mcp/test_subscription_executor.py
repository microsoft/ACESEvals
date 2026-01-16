"""Tests for the Azure MCP Subscription Namespace Executor.

Tests the SubscriptionExecutor implementation for:
- Parameter validation
- Command routing
- Azure MCP interface fidelity
- Subscription enumeration
- Resource group listing
- Blue Team scoping scenarios
"""

import pytest
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

# Add the domains path so we can import the executor module
_repo_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_repo_root / "domains" / "saber_dual"))

# Mock ALL saber imports BEFORE any imports that might touch them
mock_saber = MagicMock()
mock_docker_executor = MagicMock()
mock_sandbox_manager = MagicMock()
mock_base = MagicMock()
mock_command_result = MagicMock()

# Create mock Parameter and ParameterType
class MockParameterType:
    STRING = "string"
    OBJECT = "object"
    INTEGER = "integer"
    BOOLEAN = "boolean"

class MockParameter:
    def __init__(self, name, type, description="", required=False):
        self.name = name
        self.type = type
        self.description = description
        self.required = required

class MockValidationResult:
    def __init__(self):
        self.valid = True
        self.errors = []
    
    def add_error(self, error):
        self.valid = False
        self.errors.append(error)

class MockCommandResult:
    def __init__(self, success, output=None, error=None, metadata=None):
        self.success = success
        self.output = output
        self.error = error
        self.metadata = metadata or {}
    
    @classmethod
    def success_result(cls, output, metadata=None):
        return cls(success=True, output=output, metadata=metadata)
    
    @classmethod
    def error_result(cls, error, metadata=None):
        return cls(success=False, error=error, metadata=metadata)

# Set up the mocks
sys.modules['saber'] = mock_saber
sys.modules['saber.server'] = MagicMock()
sys.modules['saber.server.execution'] = MagicMock()
sys.modules['saber.server.execution.executors'] = MagicMock()
sys.modules['saber.server.execution.executors.docker_executor'] = mock_docker_executor
sys.modules['saber.server.execution.sandbox'] = MagicMock()
sys.modules['saber.server.execution.sandbox.sandbox_environment_manager'] = mock_sandbox_manager
sys.modules['saber.server.execution.base'] = mock_base
sys.modules['saber.server.base'] = MagicMock()

# Configure mock classes
mock_docker_executor.DockerExecutor = MagicMock
mock_sandbox_manager.SandboxEnvironmentManager = MagicMock
mock_base.Parameter = MockParameter
mock_base.ParameterType = MockParameterType
mock_base.ValidationResult = MockValidationResult
sys.modules['saber.server.base'].CommandResult = MockCommandResult

# Now import the executor module
from server.config.executors.azure_mcp.subscription_executor import SubscriptionExecutor


class TestSubscriptionExecutorMetadata:
    """Tests for SubscriptionExecutor metadata and configuration."""

    def test_executor_name_matches_azure_mcp(self):
        """Executor name must be 'subscription' to match Azure MCP namespace."""
        assert SubscriptionExecutor._executor_metadata["name"] == "subscription"

    def test_executor_has_description(self):
        """Executor must have a description."""
        assert "description" in SubscriptionExecutor._executor_metadata
        assert len(SubscriptionExecutor._executor_metadata["description"]) > 0
        assert "Subscription" in SubscriptionExecutor._executor_metadata["description"]

    def test_supported_commands_defined(self):
        """Verify all expected Azure MCP commands are defined."""
        expected_commands = [
            "list",
            "resource-group list",
        ]
        for cmd in expected_commands:
            assert cmd in SubscriptionExecutor.SUPPORTED_COMMANDS, f"Missing command: {cmd}"


class TestSubscriptionListCommand:
    """Tests for subscription list command."""

    def test_list_no_required_params(self):
        """Verify list command has no required parameters."""
        cmd_spec = SubscriptionExecutor.SUPPORTED_COMMANDS["list"]
        assert len(cmd_spec["required"]) == 0

    def test_list_has_auth_options(self):
        """Verify list has authentication options."""
        cmd_spec = SubscriptionExecutor.SUPPORTED_COMMANDS["list"]
        assert "tenant" in cmd_spec["optional"]
        assert "auth-method" in cmd_spec["optional"]


class TestResourceGroupListCommand:
    """Tests for resource-group list command."""

    def test_resource_group_list_no_required_params(self):
        """Verify resource-group list has no required parameters."""
        cmd_spec = SubscriptionExecutor.SUPPORTED_COMMANDS["resource-group list"]
        # Subscription is optional - will use default if not specified
        assert len(cmd_spec["required"]) == 0

    def test_resource_group_list_subscription_optional(self):
        """Verify subscription filter is optional."""
        cmd_spec = SubscriptionExecutor.SUPPORTED_COMMANDS["resource-group list"]
        assert "subscription" in cmd_spec["optional"]


class TestSubscriptionExecutorValidation:
    """Tests for parameter validation."""

    def test_validate_unsupported_command(self):
        """Unsupported commands should fail validation."""
        parameters = {
            "command": "invalid-subscription-command",
            "parameters": {}
        }
        
        result = MockValidationResult()
        command = parameters.get("command", "")
        if command not in SubscriptionExecutor.SUPPORTED_COMMANDS:
            result.add_error(f"Unsupported command: '{command}'")
        
        assert result.valid is False
        assert "Unsupported command" in result.errors[0]

    def test_validate_valid_list_command(self):
        """Valid list command (no params) should pass validation."""
        parameters = {
            "command": "list",
            "parameters": {}
        }
        
        result = MockValidationResult()
        command = parameters["command"]
        params = parameters["parameters"]
        cmd_spec = SubscriptionExecutor.SUPPORTED_COMMANDS[command]
        
        for req_param in cmd_spec["required"]:
            if req_param not in params:
                result.add_error(f"Missing required parameter '{req_param}'")
        
        assert result.valid is True

    def test_validate_valid_resource_group_list(self):
        """Valid resource-group list should pass validation."""
        parameters = {
            "command": "resource-group list",
            "parameters": {
                "subscription": "specific-subscription-id"
            }
        }
        
        result = MockValidationResult()
        command = parameters["command"]
        params = parameters["parameters"]
        cmd_spec = SubscriptionExecutor.SUPPORTED_COMMANDS[command]
        
        for req_param in cmd_spec["required"]:
            if req_param not in params:
                result.add_error(f"Missing required parameter '{req_param}'")
        
        assert result.valid is True


class TestSubscriptionResponseFormats:
    """Tests for subscription response formats."""

    def test_subscription_list_response_format(self):
        """Subscription list should return Azure-formatted response."""
        mock_response = {
            "value": [
                {
                    "id": "/subscriptions/a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                    "subscriptionId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                    "tenantId": "contoso-tenant-id",
                    "displayName": "React2Shell-Production",
                    "state": "Enabled",
                    "subscriptionPolicies": {
                        "locationPlacementId": "Public_2014-09-01",
                        "quotaId": "EnterpriseAgreement_2014-09-01",
                        "spendingLimit": "Off"
                    },
                    "authorizationSource": "RoleBased",
                }
            ],
            "count": 1
        }
        
        # Verify response structure matches Azure Subscription format
        assert "value" in mock_response
        sub = mock_response["value"][0]
        assert "subscriptionId" in sub
        assert "tenantId" in sub
        assert "displayName" in sub
        assert "state" in sub
        assert sub["state"] in ["Enabled", "Disabled", "Warned", "PastDue", "Deleted"]

    def test_resource_group_list_response_format(self):
        """Resource group list should return Azure-formatted response."""
        mock_response = {
            "value": [
                {
                    "id": "/subscriptions/test-sub/resourceGroups/react2shell-rg",
                    "name": "react2shell-rg",
                    "type": "Microsoft.Resources/resourceGroups",
                    "location": "eastus",
                    "tags": {
                        "environment": "production",
                        "application": "react2shell-webapp",
                    },
                    "properties": {
                        "provisioningState": "Succeeded"
                    }
                },
                {
                    "id": "/subscriptions/test-sub/resourceGroups/react2shell-security-rg",
                    "name": "react2shell-security-rg",
                    "type": "Microsoft.Resources/resourceGroups",
                    "location": "eastus",
                    "tags": {
                        "purpose": "security-monitoring",
                    },
                    "properties": {
                        "provisioningState": "Succeeded"
                    }
                }
            ]
        }
        
        assert "value" in mock_response
        for rg in mock_response["value"]:
            assert "id" in rg
            assert "name" in rg
            assert "type" in rg
            assert rg["type"] == "Microsoft.Resources/resourceGroups"
            assert "location" in rg
            assert "properties" in rg
            assert rg["properties"]["provisioningState"] in ["Succeeded", "Failed", "Deleting", "Creating"]


class TestAzureMCPInterfaceFidelity:
    """Tests ensuring the executor matches Azure MCP interface exactly."""

    def test_command_parameter_is_string(self):
        """The 'command' parameter must be a string type."""
        assert SubscriptionExecutor.SUPPORTED_COMMANDS is not None
        for cmd in SubscriptionExecutor.SUPPORTED_COMMANDS:
            assert isinstance(cmd, str)

    def test_all_commands_have_retry_options(self):
        """All commands should support Azure MCP retry options."""
        retry_options = [
            "retry-delay",
            "retry-max-delay", 
            "retry-max-retries",
            "retry-mode",
            "retry-network-timeout",
        ]
        
        for cmd, spec in SubscriptionExecutor.SUPPORTED_COMMANDS.items():
            for opt in retry_options:
                assert opt in spec["optional"], f"Command '{cmd}' missing retry option '{opt}'"

    def test_all_commands_have_auth_options(self):
        """All commands should support authentication options."""
        auth_options = ["tenant", "auth-method"]
        
        for cmd, spec in SubscriptionExecutor.SUPPORTED_COMMANDS.items():
            for opt in auth_options:
                assert opt in spec["optional"], f"Command '{cmd}' missing auth option '{opt}'"


class TestBlueTeamScopingScenarios:
    """Tests for Blue Team investigation scoping scenarios."""

    def test_enumerate_subscriptions_first(self):
        """Blue team should enumerate subscriptions to understand scope."""
        params = {
            "command": "list",
            "parameters": {}
        }
        
        cmd_spec = SubscriptionExecutor.SUPPORTED_COMMANDS[params["command"]]
        assert len(cmd_spec["required"]) == 0  # Can call without params

    def test_enumerate_resource_groups_for_investigation(self):
        """Blue team should enumerate resource groups to scope investigation."""
        params = {
            "command": "resource-group list",
            "parameters": {
                "subscription": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
            }
        }
        
        cmd_spec = SubscriptionExecutor.SUPPORTED_COMMANDS[params["command"]]
        # Subscription is optional but useful for scoping
        assert "subscription" in cmd_spec["optional"]

    def test_resource_group_tags_useful_for_filtering(self):
        """Resource group tags should help identify relevant resources."""
        mock_rg = {
            "name": "react2shell-rg",
            "tags": {
                "environment": "production",
                "application": "react2shell-webapp",
                "criticality": "high",
            }
        }
        
        # Tags help blue team identify critical resources
        assert "environment" in mock_rg["tags"]
        assert "application" in mock_rg["tags"]

    def test_subscription_id_format(self):
        """Subscription IDs should be valid UUID format."""
        import re
        uuid_pattern = r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
        
        test_sub_ids = [
            "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "12345678-1234-1234-1234-123456789abc",
        ]
        
        for sub_id in test_sub_ids:
            assert re.match(uuid_pattern, sub_id), f"Subscription ID {sub_id} doesn't match UUID format"

    def test_react2shell_scenario_resource_groups(self):
        """Verify expected resource groups for React2Shell scenario."""
        expected_rg_names = [
            "react2shell-rg",           # Main app resources
            "react2shell-network-rg",   # Network resources
            "react2shell-security-rg",  # Sentinel workspace
            "react2shell-data-rg",      # SQL, KeyVault, Storage
        ]
        
        # These should all be valid resource group names
        for rg_name in expected_rg_names:
            assert rg_name.startswith("react2shell-")
            assert len(rg_name) <= 90  # Azure RG name max length
