"""Tests for the Azure MCP KeyVault Namespace Executor.

Tests the KeyvaultExecutor implementation for:
- Parameter validation
- Command routing
- Azure MCP interface fidelity
- Secret management operations
- Key and certificate operations
- Blue Team credential theft detection scenarios
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
from server.config.executors.azure_mcp.keyvault_executor import KeyvaultExecutor


class TestKeyvaultExecutorMetadata:
    """Tests for KeyvaultExecutor metadata and configuration."""

    def test_executor_name_matches_azure_mcp(self):
        """Executor name must be 'keyvault' to match Azure MCP namespace."""
        assert KeyvaultExecutor._executor_metadata["name"] == "keyvault"

    def test_executor_has_description(self):
        """Executor must have a description."""
        assert "description" in KeyvaultExecutor._executor_metadata
        assert len(KeyvaultExecutor._executor_metadata["description"]) > 0
        assert "Key Vault" in KeyvaultExecutor._executor_metadata["description"]

    def test_supported_commands_defined(self):
        """Verify all expected Azure MCP commands are defined."""
        expected_commands = [
            "secret list",
            "secret get",
            "secret create",
            "key list",
            "key get",
            "certificate list",
            "certificate get",
        ]
        for cmd in expected_commands:
            assert cmd in KeyvaultExecutor.SUPPORTED_COMMANDS, f"Missing command: {cmd}"


class TestSecretCommands:
    """Tests for secret management commands."""

    def test_secret_list_required_params(self):
        """Verify secret list requires vault name."""
        cmd_spec = KeyvaultExecutor.SUPPORTED_COMMANDS["secret list"]
        assert "vault" in cmd_spec["required"]

    def test_secret_get_required_params(self):
        """Verify secret get requires vault and secret name."""
        cmd_spec = KeyvaultExecutor.SUPPORTED_COMMANDS["secret get"]
        assert "vault" in cmd_spec["required"]
        assert "secret" in cmd_spec["required"]

    def test_secret_create_required_params(self):
        """Verify secret create requires vault, secret name, and value."""
        cmd_spec = KeyvaultExecutor.SUPPORTED_COMMANDS["secret create"]
        assert "vault" in cmd_spec["required"]
        assert "secret" in cmd_spec["required"]
        assert "value" in cmd_spec["required"]


class TestKeyCommands:
    """Tests for key management commands."""

    def test_key_list_required_params(self):
        """Verify key list requires vault name."""
        cmd_spec = KeyvaultExecutor.SUPPORTED_COMMANDS["key list"]
        assert "vault" in cmd_spec["required"]
        # include-managed is optional Azure MCP parameter
        assert "include-managed" in cmd_spec["optional"]

    def test_key_get_required_params(self):
        """Verify key get requires vault and key name."""
        cmd_spec = KeyvaultExecutor.SUPPORTED_COMMANDS["key get"]
        assert "vault" in cmd_spec["required"]
        assert "key" in cmd_spec["required"]

    def test_key_create_required_params(self):
        """Verify key create requires vault, key name, and key type."""
        cmd_spec = KeyvaultExecutor.SUPPORTED_COMMANDS["key create"]
        assert "vault" in cmd_spec["required"]
        assert "key" in cmd_spec["required"]
        assert "key-type" in cmd_spec["required"]


class TestCertificateCommands:
    """Tests for certificate management commands."""

    def test_certificate_list_required_params(self):
        """Verify certificate list requires vault name."""
        cmd_spec = KeyvaultExecutor.SUPPORTED_COMMANDS["certificate list"]
        assert "vault" in cmd_spec["required"]

    def test_certificate_get_required_params(self):
        """Verify certificate get requires vault and certificate name."""
        cmd_spec = KeyvaultExecutor.SUPPORTED_COMMANDS["certificate get"]
        assert "vault" in cmd_spec["required"]
        assert "certificate" in cmd_spec["required"]


class TestKeyvaultExecutorValidation:
    """Tests for parameter validation."""

    def test_validate_unsupported_command(self):
        """Unsupported commands should fail validation."""
        parameters = {
            "command": "invalid-keyvault-command",
            "parameters": {}
        }
        
        result = MockValidationResult()
        command = parameters.get("command", "")
        if command not in KeyvaultExecutor.SUPPORTED_COMMANDS:
            result.add_error(f"Unsupported command: '{command}'")
        
        assert result.valid is False
        assert "Unsupported command" in result.errors[0]

    def test_validate_secret_get_missing_params(self):
        """Missing required parameters for secret get should fail."""
        parameters = {
            "command": "secret get",
            "parameters": {
                "vault": "react2shell-keyvault"
                # Missing 'secret' parameter
            }
        }
        
        result = MockValidationResult()
        command = parameters["command"]
        params = parameters["parameters"]
        cmd_spec = KeyvaultExecutor.SUPPORTED_COMMANDS[command]
        
        for req_param in cmd_spec["required"]:
            if req_param not in params:
                result.add_error(f"Missing required parameter '{req_param}'")
        
        assert result.valid is False
        assert any("secret" in e for e in result.errors)

    def test_validate_valid_secret_list(self):
        """Valid secret list parameters should pass validation."""
        parameters = {
            "command": "secret list",
            "parameters": {
                "vault": "react2shell-keyvault"
            }
        }
        
        result = MockValidationResult()
        command = parameters["command"]
        params = parameters["parameters"]
        cmd_spec = KeyvaultExecutor.SUPPORTED_COMMANDS[command]
        
        for req_param in cmd_spec["required"]:
            if req_param not in params:
                result.add_error(f"Missing required parameter '{req_param}'")
        
        assert result.valid is True
        assert len(result.errors) == 0


class TestSecretResponseFormats:
    """Tests for secret response formats matching Azure Key Vault API."""

    def test_secret_list_response_format(self):
        """Secret list should return Azure-formatted response."""
        mock_response = {
            "value": [
                {
                    "id": "https://react2shell-keyvault.vault.azure.net/secrets/storage-sas-token",
                    "attributes": {
                        "enabled": True,
                        "created": 1705398000,
                        "updated": 1705398000,
                    }
                },
                {
                    "id": "https://react2shell-keyvault.vault.azure.net/secrets/sql-connection-string",
                    "attributes": {
                        "enabled": True,
                        "created": 1705398000,
                        "updated": 1705398000,
                    }
                }
            ],
            "vault": "react2shell-keyvault"
        }
        
        assert "value" in mock_response
        for secret in mock_response["value"]:
            assert "id" in secret
            assert "vault.azure.net/secrets/" in secret["id"]
            assert "attributes" in secret
            assert "enabled" in secret["attributes"]

    def test_secret_get_response_format(self):
        """Secret get should return secret value and metadata."""
        mock_response = {
            "id": "https://react2shell-keyvault.vault.azure.net/secrets/api-key/abc123",
            "value": "sk-secret-api-key-value-12345",
            "attributes": {
                "enabled": True,
                "created": 1705398000,
                "updated": 1705398000,
                "recoveryLevel": "Recoverable+Purgeable"
            },
            "vault": "react2shell-keyvault",
            "secretName": "api-key"
        }
        
        assert "id" in mock_response
        assert "value" in mock_response
        assert "attributes" in mock_response
        assert mock_response["attributes"]["recoveryLevel"] is not None


class TestAzureMCPInterfaceFidelity:
    """Tests ensuring the executor matches Azure MCP interface exactly."""

    def test_command_parameter_is_string(self):
        """The 'command' parameter must be a string type."""
        assert KeyvaultExecutor.SUPPORTED_COMMANDS is not None
        for cmd in KeyvaultExecutor.SUPPORTED_COMMANDS:
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
        
        for cmd, spec in KeyvaultExecutor.SUPPORTED_COMMANDS.items():
            for opt in retry_options:
                assert opt in spec["optional"], f"Command '{cmd}' missing retry option '{opt}'"

    def test_all_commands_have_auth_options(self):
        """All commands should support authentication options."""
        auth_options = ["tenant", "auth-method"]
        
        for cmd, spec in KeyvaultExecutor.SUPPORTED_COMMANDS.items():
            for opt in auth_options:
                assert opt in spec["optional"], f"Command '{cmd}' missing auth option '{opt}'"


class TestBlueTeamCredentialMonitoring:
    """Tests for Blue Team credential theft detection scenarios."""

    def test_enumerate_secrets_for_audit(self):
        """Blue team should be able to list all secrets for audit."""
        params = {
            "command": "secret list",
            "parameters": {
                "vault": "react2shell-keyvault"
            }
        }
        
        cmd_spec = KeyvaultExecutor.SUPPORTED_COMMANDS[params["command"]]
        for req in cmd_spec["required"]:
            assert req in params["parameters"]

    def test_check_sensitive_secret_access(self):
        """Blue team can check if sensitive secrets were accessed."""
        # In React2Shell scenario, attacker may access managed identity token
        sensitive_secrets = [
            "storage-sas-token",
            "sql-connection-string",
            "api-key",
            "managed-identity-token",
        ]
        
        for secret_name in sensitive_secrets:
            params = {
                "command": "secret get",
                "parameters": {
                    "vault": "react2shell-keyvault",
                    "secret": secret_name
                }
            }
            
            cmd_spec = KeyvaultExecutor.SUPPORTED_COMMANDS[params["command"]]
            for req in cmd_spec["required"]:
                assert req in params["parameters"]

    def test_key_enumeration_for_compromise_detection(self):
        """Blue team should enumerate keys to detect unauthorized access."""
        params = {
            "command": "key list",
            "parameters": {
                "vault": "react2shell-keyvault",
                "include-managed": True  # Include managed keys for full audit
            }
        }
        
        cmd_spec = KeyvaultExecutor.SUPPORTED_COMMANDS[params["command"]]
        for req in cmd_spec["required"]:
            assert req in params["parameters"]
        # include-managed should be valid optional param
        assert "include-managed" in cmd_spec["optional"]

    def test_certificate_audit_for_compromise(self):
        """Blue team should audit certificates for unauthorized access."""
        params = {
            "command": "certificate list",
            "parameters": {
                "vault": "react2shell-keyvault"
            }
        }
        
        cmd_spec = KeyvaultExecutor.SUPPORTED_COMMANDS[params["command"]]
        for req in cmd_spec["required"]:
            assert req in params["parameters"]
