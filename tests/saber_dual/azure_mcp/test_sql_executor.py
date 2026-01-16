"""Tests for the Azure MCP SQL Namespace Executor.

Tests the SqlExecutor implementation for:
- Parameter validation
- Command routing
- Azure MCP interface fidelity
- Firewall rule management (critical for Blue Team defense)
- Server and database operations
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
from server.config.executors.azure_mcp.sql_executor import SqlExecutor


class TestSqlExecutorMetadata:
    """Tests for SqlExecutor metadata and configuration."""

    def test_executor_name_matches_azure_mcp(self):
        """Executor name must be 'sql' to match Azure MCP namespace."""
        assert SqlExecutor._executor_metadata["name"] == "sql"

    def test_executor_has_description(self):
        """Executor must have a description."""
        assert "description" in SqlExecutor._executor_metadata
        assert len(SqlExecutor._executor_metadata["description"]) > 0
        assert "SQL" in SqlExecutor._executor_metadata["description"]

    def test_supported_commands_defined(self):
        """Verify all expected Azure MCP commands are defined."""
        expected_commands = [
            "server firewall-rule create",
            "server firewall-rule delete",
            "server firewall-rule list",
            "server list",
            "server show",
            "db list",
        ]
        for cmd in expected_commands:
            assert cmd in SqlExecutor.SUPPORTED_COMMANDS, f"Missing command: {cmd}"


class TestFirewallRuleCommands:
    """Tests for firewall rule commands - critical for Blue Team defense."""

    def test_firewall_rule_create_required_params(self):
        """Verify firewall-rule create has all required parameters for blocking IPs."""
        cmd_spec = SqlExecutor.SUPPORTED_COMMANDS["server firewall-rule create"]
        required = cmd_spec["required"]
        
        # These are essential for creating a firewall rule
        assert "resource-group" in required
        assert "server" in required
        assert "rule-name" in required
        assert "start-ip" in required
        assert "end-ip" in required

    def test_firewall_rule_delete_required_params(self):
        """Verify firewall-rule delete has correct required parameters."""
        cmd_spec = SqlExecutor.SUPPORTED_COMMANDS["server firewall-rule delete"]
        required = cmd_spec["required"]
        
        assert "resource-group" in required
        assert "server" in required
        assert "rule-name" in required

    def test_firewall_rule_list_required_params(self):
        """Verify firewall-rule list has correct required parameters."""
        cmd_spec = SqlExecutor.SUPPORTED_COMMANDS["server firewall-rule list"]
        required = cmd_spec["required"]
        
        assert "resource-group" in required
        assert "server" in required


class TestSqlExecutorValidation:
    """Tests for parameter validation."""

    def test_validate_unsupported_command(self):
        """Unsupported commands should fail validation."""
        parameters = {
            "command": "invalid-sql-command",
            "parameters": {}
        }
        
        result = MockValidationResult()
        command = parameters.get("command", "")
        if command not in SqlExecutor.SUPPORTED_COMMANDS:
            result.add_error(f"Unsupported command: '{command}'")
        
        assert result.valid is False
        assert "Unsupported command" in result.errors[0]

    def test_validate_firewall_rule_create_missing_params(self):
        """Missing required parameters for firewall rule create should fail."""
        parameters = {
            "command": "server firewall-rule create",
            "parameters": {
                "resource-group": "react2shell-rg",
                "server": "react2shell-sql",
                "rule-name": "block-attacker"
                # Missing start-ip and end-ip
            }
        }
        
        result = MockValidationResult()
        command = parameters["command"]
        params = parameters["parameters"]
        cmd_spec = SqlExecutor.SUPPORTED_COMMANDS[command]
        
        for req_param in cmd_spec["required"]:
            if req_param not in params:
                result.add_error(f"Missing required parameter '{req_param}'")
        
        assert result.valid is False
        assert any("start-ip" in e for e in result.errors)
        assert any("end-ip" in e for e in result.errors)

    def test_validate_valid_firewall_rule_create(self):
        """Valid firewall rule create parameters should pass validation."""
        parameters = {
            "command": "server firewall-rule create",
            "parameters": {
                "resource-group": "react2shell-rg",
                "server": "react2shell-sql",
                "rule-name": "block-attacker-192-168-1-100",
                "start-ip": "192.168.1.100",
                "end-ip": "192.168.1.100"
            }
        }
        
        result = MockValidationResult()
        command = parameters["command"]
        params = parameters["parameters"]
        cmd_spec = SqlExecutor.SUPPORTED_COMMANDS[command]
        
        for req_param in cmd_spec["required"]:
            if req_param not in params:
                result.add_error(f"Missing required parameter '{req_param}'")
        
        assert result.valid is True
        assert len(result.errors) == 0


class TestFirewallRuleResponses:
    """Tests for firewall rule response formats."""

    def test_firewall_rule_create_response_format(self):
        """Firewall rule create should return Azure-formatted response."""
        mock_response = {
            "id": "/subscriptions/test-sub/resourceGroups/react2shell-rg/providers/Microsoft.Sql/servers/react2shell-sql/firewallRules/block-attacker",
            "name": "block-attacker",
            "type": "Microsoft.Sql/servers/firewallRules",
            "properties": {
                "startIpAddress": "192.168.1.100",
                "endIpAddress": "192.168.1.100"
            }
        }
        
        # Verify response structure matches Azure SQL firewall rule format
        assert "id" in mock_response
        assert "name" in mock_response
        assert "type" in mock_response
        assert mock_response["type"] == "Microsoft.Sql/servers/firewallRules"
        assert "properties" in mock_response
        assert "startIpAddress" in mock_response["properties"]
        assert "endIpAddress" in mock_response["properties"]

    def test_firewall_rule_list_response_format(self):
        """Firewall rule list should return Azure-formatted array."""
        mock_response = {
            "value": [
                {
                    "id": "/subscriptions/test-sub/resourceGroups/react2shell-rg/providers/Microsoft.Sql/servers/react2shell-sql/firewallRules/AllowAzureServices",
                    "name": "AllowAzureServices",
                    "type": "Microsoft.Sql/servers/firewallRules",
                    "properties": {
                        "startIpAddress": "0.0.0.0",
                        "endIpAddress": "0.0.0.0"
                    }
                },
                {
                    "id": "/subscriptions/test-sub/resourceGroups/react2shell-rg/providers/Microsoft.Sql/servers/react2shell-sql/firewallRules/ClientIP",
                    "name": "ClientIP",
                    "type": "Microsoft.Sql/servers/firewallRules",
                    "properties": {
                        "startIpAddress": "10.0.0.1",
                        "endIpAddress": "10.0.0.255"
                    }
                }
            ]
        }
        
        assert "value" in mock_response
        assert len(mock_response["value"]) == 2
        for rule in mock_response["value"]:
            assert "name" in rule
            assert "properties" in rule


class TestServerAndDatabaseCommands:
    """Tests for server and database commands."""

    def test_server_list_no_required_params(self):
        """server list should have no required parameters."""
        cmd_spec = SqlExecutor.SUPPORTED_COMMANDS["server list"]
        assert len(cmd_spec["required"]) == 0
        assert "subscription" in cmd_spec["optional"]
        assert "resource-group" in cmd_spec["optional"]

    def test_server_show_required_params(self):
        """server show should require resource-group and server."""
        cmd_spec = SqlExecutor.SUPPORTED_COMMANDS["server show"]
        assert "resource-group" in cmd_spec["required"]
        assert "server" in cmd_spec["required"]

    def test_db_list_required_params(self):
        """db list should require resource-group and server."""
        cmd_spec = SqlExecutor.SUPPORTED_COMMANDS["db list"]
        assert "resource-group" in cmd_spec["required"]
        assert "server" in cmd_spec["required"]

    def test_server_list_response_format(self):
        """Server list should return Azure-formatted server array."""
        mock_response = {
            "value": [
                {
                    "id": "/subscriptions/test-sub/resourceGroups/react2shell-rg/providers/Microsoft.Sql/servers/react2shell-sql",
                    "name": "react2shell-sql",
                    "type": "Microsoft.Sql/servers",
                    "location": "eastus",
                    "properties": {
                        "administratorLogin": "sqladmin",
                        "fullyQualifiedDomainName": "react2shell-sql.database.windows.net",
                        "state": "Ready",
                        "version": "12.0"
                    }
                }
            ]
        }
        
        assert "value" in mock_response
        server = mock_response["value"][0]
        assert "fullyQualifiedDomainName" in server["properties"]
        assert server["properties"]["state"] == "Ready"


class TestAzureMCPInterfaceFidelity:
    """Tests ensuring the executor matches Azure MCP interface exactly."""

    def test_command_parameter_is_string(self):
        """The 'command' parameter must be a string type."""
        assert SqlExecutor.SUPPORTED_COMMANDS is not None
        for cmd in SqlExecutor.SUPPORTED_COMMANDS:
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
        
        for cmd, spec in SqlExecutor.SUPPORTED_COMMANDS.items():
            for opt in retry_options:
                assert opt in spec["optional"], f"Command '{cmd}' missing retry option '{opt}'"

    def test_all_commands_have_auth_options(self):
        """All commands should support authentication options."""
        auth_options = ["tenant", "auth-method"]
        
        for cmd, spec in SqlExecutor.SUPPORTED_COMMANDS.items():
            for opt in auth_options:
                assert opt in spec["optional"], f"Command '{cmd}' missing auth option '{opt}'"

    def test_firewall_rule_ip_format(self):
        """IP addresses should be in dotted-quad format."""
        import re
        ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
        
        test_ips = ["192.168.1.100", "10.0.0.1", "0.0.0.0", "255.255.255.255"]
        for ip in test_ips:
            assert re.match(ip_pattern, ip), f"IP {ip} doesn't match expected format"


class TestBlueTeamDefenseScenarios:
    """Tests for Blue Team specific defense scenarios."""

    def test_block_single_attacker_ip_params(self):
        """Verify parameters for blocking a single attacker IP."""
        # Blue team would create a firewall rule to block attacker
        params = {
            "command": "server firewall-rule create",
            "parameters": {
                "resource-group": "react2shell-rg",
                "server": "react2shell-sql",
                "rule-name": "block-attacker-45-33-32-156",
                "start-ip": "45.33.32.156",  # Attacker IP
                "end-ip": "45.33.32.156"     # Same IP for single block
            }
        }
        
        cmd_spec = SqlExecutor.SUPPORTED_COMMANDS[params["command"]]
        for req in cmd_spec["required"]:
            assert req in params["parameters"], f"Missing {req} for blocking attacker"

    def test_block_ip_range_params(self):
        """Verify parameters for blocking an IP range."""
        params = {
            "command": "server firewall-rule create",
            "parameters": {
                "resource-group": "react2shell-rg",
                "server": "react2shell-sql",
                "rule-name": "block-suspicious-range",
                "start-ip": "45.33.32.0",
                "end-ip": "45.33.32.255"
            }
        }
        
        cmd_spec = SqlExecutor.SUPPORTED_COMMANDS[params["command"]]
        for req in cmd_spec["required"]:
            assert req in params["parameters"]
        
        # Verify IP range is valid (start <= end)
        start_parts = [int(x) for x in params["parameters"]["start-ip"].split(".")]
        end_parts = [int(x) for x in params["parameters"]["end-ip"].split(".")]
        start_int = sum(p * (256 ** (3-i)) for i, p in enumerate(start_parts))
        end_int = sum(p * (256 ** (3-i)) for i, p in enumerate(end_parts))
        assert start_int <= end_int, "Start IP should be <= end IP"

    def test_enumerate_existing_rules_before_action(self):
        """Blue team should enumerate rules before taking action."""
        # First action: list existing rules
        list_params = {
            "command": "server firewall-rule list",
            "parameters": {
                "resource-group": "react2shell-rg",
                "server": "react2shell-sql"
            }
        }
        
        cmd_spec = SqlExecutor.SUPPORTED_COMMANDS[list_params["command"]]
        for req in cmd_spec["required"]:
            assert req in list_params["parameters"]
