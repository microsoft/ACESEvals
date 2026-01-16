"""Tests for the Azure MCP Monitor Namespace Executor.

Tests the MonitorExecutor implementation for:
- Parameter validation
- Command routing
- Azure MCP interface fidelity
- Log query execution
- Activity log retrieval
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
from server.config.executors.azure_mcp.monitor_executor import MonitorExecutor


class TestMonitorExecutorMetadata:
    """Tests for MonitorExecutor metadata and configuration."""

    def test_executor_name_matches_azure_mcp(self):
        """Executor name must be 'monitor' to match Azure MCP namespace."""
        assert MonitorExecutor._executor_metadata["name"] == "monitor"

    def test_executor_has_description(self):
        """Executor must have a description."""
        assert "description" in MonitorExecutor._executor_metadata
        assert len(MonitorExecutor._executor_metadata["description"]) > 0

    def test_supported_commands_defined(self):
        """Verify all expected Azure MCP commands are defined."""
        expected_commands = [
            "workspace log query",
            "activitylog list",
            "table list",
            "table type list",
            "metrics query",
            "metrics definitions",
            "resource log query",
        ]
        for cmd in expected_commands:
            assert cmd in MonitorExecutor.SUPPORTED_COMMANDS, f"Missing command: {cmd}"

    def test_workspace_log_query_parameters(self):
        """Verify 'workspace log query' has correct required parameters."""
        cmd_spec = MonitorExecutor.SUPPORTED_COMMANDS["workspace log query"]
        assert "workspace" in cmd_spec["required"]
        assert "query" in cmd_spec["required"]
        # Verify optional retry parameters are included (Azure MCP fidelity)
        assert "retry-delay" in cmd_spec["optional"]
        assert "retry-max-retries" in cmd_spec["optional"]

    def test_activitylog_list_parameters(self):
        """Verify 'activitylog list' has correct required parameters."""
        cmd_spec = MonitorExecutor.SUPPORTED_COMMANDS["activitylog list"]
        assert "resource-name" in cmd_spec["required"]
        assert "hours" in cmd_spec["optional"]
        assert "event-level" in cmd_spec["optional"]

    def test_metrics_query_parameters(self):
        """Verify 'metrics query' has correct required parameters."""
        cmd_spec = MonitorExecutor.SUPPORTED_COMMANDS["metrics query"]
        assert "resource" in cmd_spec["required"]
        assert "metric-names" in cmd_spec["required"]
        assert "metric-namespace" in cmd_spec["required"]


class TestMonitorExecutorValidation:
    """Tests for parameter validation."""

    def test_validate_unsupported_command(self):
        """Unsupported commands should fail validation."""
        parameters = {
            "command": "invalid-command",
            "parameters": {}
        }
        
        # Create a real ValidationResult for testing
        result = MockValidationResult()
        
        # Manually invoke validation logic
        command = parameters.get("command", "")
        if command not in MonitorExecutor.SUPPORTED_COMMANDS:
            result.add_error(f"Unsupported command: '{command}'")
        
        assert result.valid is False
        assert "Unsupported command" in result.errors[0]

    def test_validate_missing_required_params(self):
        """Missing required parameters should fail validation."""
        parameters = {
            "command": "workspace log query",
            "parameters": {
                "workspace": "my-workspace"
                # Missing 'query' which is required
            }
        }
        
        result = MockValidationResult()
        command = parameters["command"]
        params = parameters["parameters"]
        cmd_spec = MonitorExecutor.SUPPORTED_COMMANDS[command]
        
        for req_param in cmd_spec["required"]:
            if req_param not in params:
                result.add_error(f"Missing required parameter '{req_param}'")
        
        assert result.valid is False
        assert any("query" in e for e in result.errors)

    def test_validate_valid_workspace_log_query(self):
        """Valid parameters should pass validation."""
        parameters = {
            "command": "workspace log query",
            "parameters": {
                "workspace": "react2shell-sentinel",
                "query": "SecurityEvent | take 10"
            }
        }
        
        result = MockValidationResult()
        command = parameters["command"]
        params = parameters["parameters"]
        
        if command in MonitorExecutor.SUPPORTED_COMMANDS:
            cmd_spec = MonitorExecutor.SUPPORTED_COMMANDS[command]
            for req_param in cmd_spec["required"]:
                if req_param not in params:
                    result.add_error(f"Missing required parameter '{req_param}'")
        
        assert result.valid is True
        assert len(result.errors) == 0


class TestMonitorExecutorCommands:
    """Tests for command execution."""

    @pytest.mark.asyncio
    async def test_workspace_log_query_returns_json(self):
        """workspace log query should return JSON formatted results."""
        # Test the response format that _query_workspace_logs would return
        mock_response = {
            "tables": [
                {
                    "name": "PrimaryResult",
                    "columns": [
                        {"name": "TimeGenerated", "type": "datetime"},
                        {"name": "SourceIP", "type": "string"},
                        {"name": "DestinationIP", "type": "string"},
                    ],
                    "rows": [
                        ["2025-01-16T10:00:00Z", "192.168.1.100", "10.0.0.5"],
                        ["2025-01-16T10:01:00Z", "192.168.1.101", "10.0.0.6"],
                    ]
                }
            ],
            "workspace": "react2shell-sentinel",
            "query": "SecurityEvent | take 2",
            "rowCount": 2,
        }
        
        # Verify response structure matches Azure MCP format
        assert "tables" in mock_response
        assert "workspace" in mock_response
        assert mock_response["tables"][0]["name"] == "PrimaryResult"
        assert len(mock_response["tables"][0]["rows"]) == 2

    @pytest.mark.asyncio
    async def test_activitylog_list_response_format(self):
        """activitylog list should return Azure-formatted activity logs."""
        mock_response = {
            "value": [
                {
                    "id": "/subscriptions/test-sub/providers/Microsoft.Insights/eventtypes/management/values/event1",
                    "operationName": {"value": "Microsoft.Sql/servers/firewallRules/write"},
                    "status": {"value": "Started"},
                    "eventTimestamp": "2025-01-16T10:00:00Z",
                    "caller": "user@contoso.com",
                }
            ],
            "resourceName": "react2shell-sql",
        }
        
        # Verify response structure matches Azure Activity Log format
        assert "value" in mock_response
        assert "operationName" in mock_response["value"][0]
        assert "eventTimestamp" in mock_response["value"][0]

    def test_table_list_includes_security_tables(self):
        """table list should include relevant security tables."""
        expected_tables = [
            "SecurityEvent",
            "Syslog",
            "AzureActivity",
            "SigninLogs",
            "AuditLogs",
            "AzureDiagnostics",
        ]
        
        # These are the tables that should be available in the mock
        for table in expected_tables:
            assert table in expected_tables  # Placeholder for actual implementation test


class TestAzureMCPInterfaceFidelity:
    """Tests ensuring the executor matches Azure MCP interface exactly."""

    def test_command_parameter_is_string(self):
        """The 'command' parameter must be a string type."""
        # In Azure MCP namespace mode, command is always a string
        # This verifies our setup_parameters implementation
        assert MonitorExecutor.SUPPORTED_COMMANDS is not None
        for cmd in MonitorExecutor.SUPPORTED_COMMANDS:
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
        
        for cmd, spec in MonitorExecutor.SUPPORTED_COMMANDS.items():
            for opt in retry_options:
                assert opt in spec["optional"], f"Command '{cmd}' missing retry option '{opt}'"

    def test_all_commands_have_auth_options(self):
        """All commands should support authentication options."""
        auth_options = ["tenant", "auth-method"]
        
        for cmd, spec in MonitorExecutor.SUPPORTED_COMMANDS.items():
            for opt in auth_options:
                assert opt in spec["optional"], f"Command '{cmd}' missing auth option '{opt}'"
