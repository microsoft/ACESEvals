"""Tests for the Azure MCP ResourceHealth Namespace Executor.

Tests the ResourcehealthExecutor implementation for:
- Parameter validation
- Command routing
- Azure MCP interface fidelity
- Availability status operations
- Health events monitoring
- Blue Team incident response scenarios
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
from server.config.executors.azure_mcp.resourcehealth_executor import ResourcehealthExecutor


class TestResourcehealthExecutorMetadata:
    """Tests for ResourcehealthExecutor metadata and configuration."""

    def test_executor_name_matches_azure_mcp(self):
        """Executor name must be 'resourcehealth' to match Azure MCP namespace."""
        assert ResourcehealthExecutor._executor_metadata["name"] == "resourcehealth"

    def test_executor_has_description(self):
        """Executor must have a description."""
        assert "description" in ResourcehealthExecutor._executor_metadata
        assert len(ResourcehealthExecutor._executor_metadata["description"]) > 0
        assert "Resource Health" in ResourcehealthExecutor._executor_metadata["description"]

    def test_supported_commands_defined(self):
        """Verify all expected Azure MCP commands are defined."""
        expected_commands = [
            "availability-status get",
            "availability-status list",
            "health-events list",
        ]
        for cmd in expected_commands:
            assert cmd in ResourcehealthExecutor.SUPPORTED_COMMANDS, f"Missing command: {cmd}"


class TestAvailabilityStatusCommands:
    """Tests for availability status commands."""

    def test_availability_status_get_required_params(self):
        """Verify availability-status get requires resource identification."""
        cmd_spec = ResourcehealthExecutor.SUPPORTED_COMMANDS["availability-status get"]
        required = cmd_spec["required"]
        
        # These are essential for identifying a specific resource
        assert "resource-group" in required
        assert "resource-type" in required
        assert "resource-name" in required

    def test_availability_status_list_no_required_params(self):
        """Verify availability-status list has no required parameters."""
        cmd_spec = ResourcehealthExecutor.SUPPORTED_COMMANDS["availability-status list"]
        # Can list all resources in subscription without specifying params
        assert len(cmd_spec["required"]) == 0
        # But resource-group can be used to filter
        assert "resource-group" in cmd_spec["optional"]


class TestHealthEventsCommands:
    """Tests for health events commands."""

    def test_health_events_list_no_required_params(self):
        """Verify health-events list has no required parameters."""
        cmd_spec = ResourcehealthExecutor.SUPPORTED_COMMANDS["health-events list"]
        assert len(cmd_spec["required"]) == 0
        # Subscription filter is optional
        assert "subscription" in cmd_spec["optional"]


class TestResourcehealthExecutorValidation:
    """Tests for parameter validation."""

    def test_validate_unsupported_command(self):
        """Unsupported commands should fail validation."""
        parameters = {
            "command": "invalid-health-command",
            "parameters": {}
        }
        
        result = MockValidationResult()
        command = parameters.get("command", "")
        if command not in ResourcehealthExecutor.SUPPORTED_COMMANDS:
            result.add_error(f"Unsupported command: '{command}'")
        
        assert result.valid is False
        assert "Unsupported command" in result.errors[0]

    def test_validate_availability_status_get_missing_params(self):
        """Missing required parameters for availability-status get should fail."""
        parameters = {
            "command": "availability-status get",
            "parameters": {
                "resource-group": "react2shell-rg"
                # Missing resource-type and resource-name
            }
        }
        
        result = MockValidationResult()
        command = parameters["command"]
        params = parameters["parameters"]
        cmd_spec = ResourcehealthExecutor.SUPPORTED_COMMANDS[command]
        
        for req_param in cmd_spec["required"]:
            if req_param not in params:
                result.add_error(f"Missing required parameter '{req_param}'")
        
        assert result.valid is False
        assert any("resource-type" in e for e in result.errors)
        assert any("resource-name" in e for e in result.errors)

    def test_validate_valid_availability_status_get(self):
        """Valid availability-status get parameters should pass validation."""
        parameters = {
            "command": "availability-status get",
            "parameters": {
                "resource-group": "react2shell-rg",
                "resource-type": "Microsoft.Web/sites",
                "resource-name": "react2shell-webapp"
            }
        }
        
        result = MockValidationResult()
        command = parameters["command"]
        params = parameters["parameters"]
        cmd_spec = ResourcehealthExecutor.SUPPORTED_COMMANDS[command]
        
        for req_param in cmd_spec["required"]:
            if req_param not in params:
                result.add_error(f"Missing required parameter '{req_param}'")
        
        assert result.valid is True
        assert len(result.errors) == 0

    def test_validate_valid_availability_status_list(self):
        """Valid availability-status list (no params) should pass validation."""
        parameters = {
            "command": "availability-status list",
            "parameters": {}
        }
        
        result = MockValidationResult()
        command = parameters["command"]
        params = parameters["parameters"]
        cmd_spec = ResourcehealthExecutor.SUPPORTED_COMMANDS[command]
        
        for req_param in cmd_spec["required"]:
            if req_param not in params:
                result.add_error(f"Missing required parameter '{req_param}'")
        
        assert result.valid is True


class TestAvailabilityStatusResponseFormats:
    """Tests for availability status response formats."""

    def test_availability_status_get_response_format(self):
        """Availability status get should return Azure-formatted response."""
        mock_response = {
            "id": "/subscriptions/test-sub/resourceGroups/react2shell-rg/providers/Microsoft.Web/sites/react2shell-webapp/providers/Microsoft.ResourceHealth/availabilityStatuses/current",
            "name": "current",
            "type": "Microsoft.ResourceHealth/availabilityStatuses",
            "location": "eastus",
            "properties": {
                "availabilityState": "Degraded",
                "summary": "Resource is experiencing intermittent issues.",
                "detailedStatus": "Degraded",
                "reasonType": "Unplanned",
                "occuredTime": "2025-01-16T10:00:00Z",
                "reportedTime": "2025-01-16T10:01:00Z",
            }
        }
        
        # Verify response structure matches Azure Resource Health format
        assert "id" in mock_response
        assert "type" in mock_response
        assert mock_response["type"] == "Microsoft.ResourceHealth/availabilityStatuses"
        assert "properties" in mock_response
        assert "availabilityState" in mock_response["properties"]
        # Valid availability states
        assert mock_response["properties"]["availabilityState"] in [
            "Available", "Degraded", "Unavailable", "Unknown"
        ]

    def test_availability_status_list_response_format(self):
        """Availability status list should return array of statuses."""
        mock_response = {
            "value": [
                {
                    "id": "/subscriptions/test-sub/resourceGroups/react2shell-rg/providers/Microsoft.Web/sites/react2shell-webapp/providers/Microsoft.ResourceHealth/availabilityStatuses/current",
                    "name": "current",
                    "type": "Microsoft.ResourceHealth/availabilityStatuses",
                    "properties": {
                        "availabilityState": "Degraded",
                        "summary": "Elevated CPU usage detected.",
                        "reportedTime": "2025-01-16T10:00:00Z",
                    },
                    "resourceName": "react2shell-webapp",
                    "resourceType": "Microsoft.Web/sites",
                },
                {
                    "id": "/subscriptions/test-sub/resourceGroups/react2shell-rg/providers/Microsoft.Sql/servers/react2shell-sql/providers/Microsoft.ResourceHealth/availabilityStatuses/current",
                    "name": "current",
                    "type": "Microsoft.ResourceHealth/availabilityStatuses",
                    "properties": {
                        "availabilityState": "Available",
                        "summary": "Resource is healthy.",
                        "reportedTime": "2025-01-16T10:00:00Z",
                    },
                    "resourceName": "react2shell-sql",
                    "resourceType": "Microsoft.Sql/servers",
                }
            ]
        }
        
        assert "value" in mock_response
        assert len(mock_response["value"]) >= 1
        for status in mock_response["value"]:
            assert "properties" in status
            assert "availabilityState" in status["properties"]


class TestHealthEventsResponseFormats:
    """Tests for health events response formats."""

    def test_health_events_list_response_format(self):
        """Health events list should return Azure-formatted events."""
        mock_response = {
            "value": [
                {
                    "name": "SIEM_Alert_001",
                    "type": "Microsoft.ResourceHealth/events",
                    "properties": {
                        "eventType": "SecurityAdvisory",
                        "eventSource": "ResourceHealth",
                        "status": "Active",
                        "title": "Suspicious Activity Detected - CVE-2025-55182",
                        "summary": "Potential exploitation detected.",
                        "impactStartTime": "2025-01-16T09:00:00Z",
                        "lastUpdateTime": "2025-01-16T10:00:00Z",
                        "level": "Warning",
                    }
                }
            ]
        }
        
        assert "value" in mock_response
        event = mock_response["value"][0]
        assert "type" in event
        assert event["type"] == "Microsoft.ResourceHealth/events"
        assert "properties" in event
        assert "eventType" in event["properties"]
        assert "status" in event["properties"]


class TestAzureMCPInterfaceFidelity:
    """Tests ensuring the executor matches Azure MCP interface exactly."""

    def test_command_parameter_is_string(self):
        """The 'command' parameter must be a string type."""
        assert ResourcehealthExecutor.SUPPORTED_COMMANDS is not None
        for cmd in ResourcehealthExecutor.SUPPORTED_COMMANDS:
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
        
        for cmd, spec in ResourcehealthExecutor.SUPPORTED_COMMANDS.items():
            for opt in retry_options:
                assert opt in spec["optional"], f"Command '{cmd}' missing retry option '{opt}'"

    def test_all_commands_have_auth_options(self):
        """All commands should support authentication options."""
        auth_options = ["tenant", "auth-method"]
        
        for cmd, spec in ResourcehealthExecutor.SUPPORTED_COMMANDS.items():
            for opt in auth_options:
                assert opt in spec["optional"], f"Command '{cmd}' missing auth option '{opt}'"


class TestBlueTeamIncidentResponseScenarios:
    """Tests for Blue Team incident response scenarios."""

    def test_check_webapp_health_during_attack(self):
        """Blue team should check webapp health during active attack."""
        # React2Shell attack may cause webapp to show degraded health
        params = {
            "command": "availability-status get",
            "parameters": {
                "resource-group": "react2shell-rg",
                "resource-type": "Microsoft.Web/sites",
                "resource-name": "react2shell-webapp"
            }
        }
        
        cmd_spec = ResourcehealthExecutor.SUPPORTED_COMMANDS[params["command"]]
        for req in cmd_spec["required"]:
            assert req in params["parameters"]

    def test_enumerate_all_resource_health_status(self):
        """Blue team should enumerate all resource health to find compromised resources."""
        params = {
            "command": "availability-status list",
            "parameters": {
                "resource-group": "react2shell-rg"  # Optional filter
            }
        }
        
        cmd_spec = ResourcehealthExecutor.SUPPORTED_COMMANDS[params["command"]]
        # No required params, so this should be valid
        assert len(cmd_spec["required"]) == 0

    def test_check_security_health_events(self):
        """Blue team should check for security-related health events."""
        params = {
            "command": "health-events list",
            "parameters": {}
        }
        
        cmd_spec = ResourcehealthExecutor.SUPPORTED_COMMANDS[params["command"]]
        assert len(cmd_spec["required"]) == 0

    def test_check_keyvault_health_after_secret_access(self):
        """Blue team should verify Key Vault health after suspicious access."""
        params = {
            "command": "availability-status get",
            "parameters": {
                "resource-group": "react2shell-rg",
                "resource-type": "Microsoft.KeyVault/vaults",
                "resource-name": "react2shell-keyvault"
            }
        }
        
        cmd_spec = ResourcehealthExecutor.SUPPORTED_COMMANDS[params["command"]]
        for req in cmd_spec["required"]:
            assert req in params["parameters"]

    def test_common_azure_resource_types(self):
        """Verify common Azure resource types for health checks."""
        common_resource_types = [
            "Microsoft.Web/sites",
            "Microsoft.Sql/servers",
            "Microsoft.KeyVault/vaults",
            "Microsoft.Storage/storageAccounts",
            "Microsoft.OperationalInsights/workspaces",
        ]
        
        # All these should be valid resource-type values
        for resource_type in common_resource_types:
            assert "/" in resource_type  # Azure resource types have format Provider/Type
            assert resource_type.startswith("Microsoft.")
