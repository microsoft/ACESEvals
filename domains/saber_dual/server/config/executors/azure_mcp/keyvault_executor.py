"""
Azure MCP Compatible KeyVault Namespace Executor

Mirrors the Azure MCP 'keyvault' namespace tool interface exactly.
See: domains/saber_dual/docs/AZURE_MCP_TOOL_REFERENCE.md

Azure MCP Command: azmcp keyvault
Sub-commands:
  - secret list
  - secret get
  - secret create
  - key list
  - key get
  - key create
  - certificate list
  - certificate get
  - certificate create
  - certificate import
  - admin settings get
"""

import logging
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Type
from datetime import datetime, timedelta

from saber.server.execution.executors.docker_executor import DockerExecutor
from saber.server.execution.sandbox.sandbox_environment_manager import SandboxEnvironmentManager
from saber.server.execution.base import Parameter, ParameterType, ValidationResult, ExecutorParameters
from saber.server.execution.models import ExecutorConfig
from saber.server.base import CommandResult

from .parameters import KeyvaultParameters

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class KeyvaultExecutorConfig(ExecutorConfig):
    """Configuration for KeyvaultExecutor."""
    siem_base_url: str = "http://siem-aggregator:8080"
    default_subscription: str = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    default_vault: str = "react2shell-keyvault"


class KeyvaultExecutor(DockerExecutor):
    """
    Azure MCP Compatible: keyvault (namespace mode)
    
    This executor mirrors the Azure MCP 'keyvault' namespace tool interface,
    providing access to mock Key Vault secrets and audit capabilities.
    
    Primary use case for Blue Team: Monitor secret access patterns,
    detect credential theft attempts.
    
    Supported sub-commands:
      - secret list: List all secrets in a vault
      - secret get: Get a specific secret value
      - secret create: Create a new secret
      - key list: List all keys
      - key get: Get key details
      - certificate list: List certificates
      - certificate get: Get certificate details
      - admin settings get: Get vault admin settings
    """
    
    _executor_metadata = {
        "name": "keyvault",
        "description": (
            "Key Vault operations - Commands for managing and accessing Azure Key Vault "
            "resources. Includes operations for listing and retrieving secrets, keys, "
            "and certificates, as well as managing vault settings."
        ),
    }

    SUPPORTED_COMMANDS = {
        "secret list": {
            "required": ["vault"],
            "optional": ["subscription", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "secret get": {
            "required": ["vault", "secret"],
            "optional": ["subscription", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "secret create": {
            "required": ["vault", "secret", "value"],
            "optional": ["subscription", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "key list": {
            "required": ["vault"],
            "optional": ["subscription", "include-managed", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "key get": {
            "required": ["vault", "key"],
            "optional": ["subscription", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "key create": {
            "required": ["vault", "key", "key-type"],
            "optional": ["subscription", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "certificate list": {
            "required": ["vault"],
            "optional": ["subscription", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "certificate get": {
            "required": ["vault", "certificate"],
            "optional": ["subscription", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "certificate create": {
            "required": ["vault", "certificate"],
            "optional": ["subscription", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "certificate import": {
            "required": ["vault", "certificate", "certificate-data"],
            "optional": ["subscription", "password", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "admin settings get": {
            "required": ["vault"],
            "optional": ["subscription", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
    }

    @classmethod
    def get_parameters_class(cls) -> Type[ExecutorParameters]:
        """Get the parameter dataclass type for this executor."""
        return KeyvaultParameters

    @classmethod
    def get_default_config(cls) -> KeyvaultExecutorConfig:
        return KeyvaultExecutorConfig()

    @classmethod
    def create_with_config(
        cls,
        sandbox_manager: SandboxEnvironmentManager,
        config: Optional[KeyvaultExecutorConfig] = None,
        additional_params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> "KeyvaultExecutor":
        merged_kwargs = {**kwargs}
        if additional_params:
            merged_kwargs.update(additional_params)
        return cls(sandbox_manager=sandbox_manager, config=config, **merged_kwargs)

    def __init__(
        self,
        sandbox_manager: SandboxEnvironmentManager,
        config: Optional[KeyvaultExecutorConfig] = None,
        **kwargs: Any,
    ) -> None:
        typed_config = config if isinstance(config, KeyvaultExecutorConfig) else KeyvaultExecutorConfig()
        self._siem_base_url = typed_config.siem_base_url
        self._default_subscription = typed_config.default_subscription
        self._default_vault = typed_config.default_vault
        super().__init__(sandbox_manager=sandbox_manager, config=typed_config, **kwargs)

    def setup_parameters(self, config: ExecutorConfig) -> None:
        """Set up Azure MCP compatible parameters."""
        self.add_parameter(
            Parameter(
                name="command",
                type=ParameterType.STRING,
                description=(
                    "The keyvault sub-command to execute. Available commands: "
                    "'secret list', 'secret get', 'secret create', "
                    "'key list', 'key get', 'key create', "
                    "'certificate list', 'certificate get', 'admin settings get'"
                ),
                required=True,
            )
        )
        
        self.add_parameter(
            Parameter(
                name="params",
                type=ParameterType.OBJECT,
                description=(
                    "Parameters for the sub-command. For 'secret list': "
                    "vault (required), subscription. "
                    "For 'secret get': vault (required), secret (required), subscription. "
                    "For 'key list': vault (required), subscription, include-managed."
                ),
                required=True,
            )
        )

    def validate_parameters(self, parameters: Dict[str, Any]) -> ValidationResult:
        """Validate Azure MCP command and parameters."""
        result = super().validate_parameters(parameters)
        
        # Debug logging
        
        command = parameters.get("command", "")
        params = parameters.get("params", {})
        
        
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
        """Execute Azure Key Vault command."""
        episode_id = context.get("episode_id", "unknown")
        
        validation = self.validate_parameters(parameters)
        if not validation.valid:
            return CommandResult.error_result(
                error=f"Parameter validation failed: {', '.join(validation.errors)}",
                metadata={"episode_id": episode_id}
            )
        
        command = parameters["command"]
        params = parameters["params"]
        
        try:
            if command == "secret list":
                return await self._list_secrets(params, context)
            elif command == "secret get":
                return await self._get_secret(params, context)
            elif command == "secret create":
                return await self._create_secret(params, context)
            elif command == "key list":
                return await self._list_keys(params, context)
            elif command == "key get":
                return await self._get_key(params, context)
            elif command == "key create":
                return await self._create_key(params, context)
            elif command == "certificate list":
                return await self._list_certificates(params, context)
            elif command == "certificate get":
                return await self._get_certificate(params, context)
            elif command == "admin settings get":
                return await self._get_admin_settings(params, context)
            else:
                return CommandResult.error_result(
                    error=f"Command '{command}' not implemented",
                    metadata={"episode_id": episode_id}
                )
        except Exception as e:
            logger.exception(f"Error executing keyvault command '{command}'")
            return CommandResult.error_result(
                error=f"Execution error: {str(e)}",
                metadata={"episode_id": episode_id, "command": command}
            )

    async def _list_secrets(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """Execute 'secret list' - List all secrets in vault."""
        episode_id = context.get("episode_id", "unknown")
        vault = params.get("vault", self._default_vault)
        subscription = params.get("subscription", self._default_subscription)
        
        # Mock secrets that would exist in the React2Shell scenario
        secrets = {
            "value": [
                {
                    "id": f"https://{vault}.vault.azure.net/secrets/storage-sas-token",
                    "name": "storage-sas-token",
                    "enabled": True,
                    "created": "2026-01-01T00:00:00Z",
                    "updated": "2026-01-15T00:00:00Z",
                    "contentType": "text/plain",
                },
                {
                    "id": f"https://{vault}.vault.azure.net/secrets/sql-connection-string",
                    "name": "sql-connection-string",
                    "enabled": True,
                    "created": "2026-01-01T00:00:00Z",
                    "updated": "2026-01-10T00:00:00Z",
                    "contentType": "text/plain",
                },
                {
                    "id": f"https://{vault}.vault.azure.net/secrets/api-key",
                    "name": "api-key",
                    "enabled": True,
                    "created": "2026-01-01T00:00:00Z",
                    "updated": "2026-01-05T00:00:00Z",
                    "contentType": "text/plain",
                },
                {
                    "id": f"https://{vault}.vault.azure.net/secrets/managed-identity-token",
                    "name": "managed-identity-token",
                    "enabled": True,
                    "created": "2026-01-01T00:00:00Z",
                    "updated": "2026-01-16T06:00:00Z",
                    "contentType": "application/jwt",
                },
            ],
            "vault": vault,
            "subscription": subscription,
        }
        
        return CommandResult.success_result(
            json.dumps(secrets, indent=2),
            metadata={
                "episode_id": episode_id,
                "command": "secret list",
                "vault": vault,
                "secret_count": len(secrets["value"]),
            }
        )

    async def _get_secret(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """Execute 'secret get' - Get specific secret value."""
        episode_id = context.get("episode_id", "unknown")
        vault = params.get("vault", self._default_vault)
        secret_name = params["secret"]
        subscription = params.get("subscription", self._default_subscription)
        
        # Mock secret values
        secret_values = {
            "storage-sas-token": "sv=2021-06-08&ss=b&srt=sco&sp=rwdlacupiytfx&se=2026-12-31T23:59:59Z&st=2026-01-01T00:00:00Z&spr=https&sig=MOCK_SAS_SIGNATURE",
            "sql-connection-string": "Server=tcp:react2shell-sql.database.windows.net,1433;Database=react2shell-db;User ID=sqladmin;Password=REDACTED;",
            "api-key": "ak_live_MOCK_API_KEY_12345",
            "managed-identity-token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.MOCK_TOKEN_PAYLOAD.MOCK_SIGNATURE",
        }
        
        if secret_name not in secret_values:
            return CommandResult.error_result(
                error=f"Secret '{secret_name}' not found in vault '{vault}'",
                metadata={"episode_id": episode_id}
            )
        
        secret = {
            "id": f"https://{vault}.vault.azure.net/secrets/{secret_name}",
            "name": secret_name,
            "value": secret_values[secret_name],
            "contentType": "text/plain",
            "attributes": {
                "enabled": True,
                "created": "2026-01-01T00:00:00Z",
                "updated": datetime.utcnow().isoformat() + "Z",
            },
            "vault": vault,
            "subscription": subscription,
        }
        
        # Log secret access for Blue Team monitoring
        logger.info(f"Secret accessed: {secret_name} from vault {vault}")
        
        return CommandResult.success_result(
            json.dumps(secret, indent=2),
            metadata={
                "episode_id": episode_id,
                "command": "secret get",
                "vault": vault,
                "secret": secret_name,
            }
        )

    async def _create_secret(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """Execute 'secret create' - Create a new secret."""
        episode_id = context.get("episode_id", "unknown")
        vault = params.get("vault", self._default_vault)
        secret_name = params["secret"]
        value = params["value"]
        subscription = params.get("subscription", self._default_subscription)
        
        secret = {
            "id": f"https://{vault}.vault.azure.net/secrets/{secret_name}",
            "name": secret_name,
            "value": value,
            "attributes": {
                "enabled": True,
                "created": datetime.utcnow().isoformat() + "Z",
                "updated": datetime.utcnow().isoformat() + "Z",
            },
            "vault": vault,
        }
        
        return CommandResult.success_result(
            json.dumps(secret, indent=2),
            metadata={
                "episode_id": episode_id,
                "command": "secret create",
                "vault": vault,
                "secret": secret_name,
            }
        )

    async def _list_keys(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """Execute 'key list' - List all keys in vault."""
        episode_id = context.get("episode_id", "unknown")
        vault = params.get("vault", self._default_vault)
        
        keys = {
            "value": [
                {
                    "kid": f"https://{vault}.vault.azure.net/keys/encryption-key",
                    "name": "encryption-key",
                    "enabled": True,
                    "kty": "RSA",
                    "keySize": 2048,
                },
                {
                    "kid": f"https://{vault}.vault.azure.net/keys/signing-key",
                    "name": "signing-key",
                    "enabled": True,
                    "kty": "EC",
                    "crv": "P-256",
                },
            ],
            "vault": vault,
        }
        
        return CommandResult.success_result(
            json.dumps(keys, indent=2),
            metadata={"episode_id": episode_id, "command": "key list"}
        )

    async def _get_key(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """Execute 'key get' - Get key details."""
        episode_id = context.get("episode_id", "unknown")
        vault = params.get("vault", self._default_vault)
        key_name = params["key"]
        
        key = {
            "kid": f"https://{vault}.vault.azure.net/keys/{key_name}",
            "name": key_name,
            "kty": "RSA",
            "keySize": 2048,
            "keyOps": ["encrypt", "decrypt", "sign", "verify"],
            "attributes": {
                "enabled": True,
                "created": "2026-01-01T00:00:00Z",
            },
        }
        
        return CommandResult.success_result(
            json.dumps(key, indent=2),
            metadata={"episode_id": episode_id, "command": "key get"}
        )

    async def _create_key(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """Execute 'key create' - Create a new key."""
        episode_id = context.get("episode_id", "unknown")
        vault = params.get("vault", self._default_vault)
        key_name = params["key"]
        key_type = params["key-type"]
        
        key = {
            "kid": f"https://{vault}.vault.azure.net/keys/{key_name}",
            "name": key_name,
            "kty": key_type,
            "attributes": {
                "enabled": True,
                "created": datetime.utcnow().isoformat() + "Z",
            },
        }
        
        return CommandResult.success_result(
            json.dumps(key, indent=2),
            metadata={"episode_id": episode_id, "command": "key create"}
        )

    async def _list_certificates(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """Execute 'certificate list' - List certificates."""
        episode_id = context.get("episode_id", "unknown")
        vault = params.get("vault", self._default_vault)
        
        certs = {
            "value": [
                {
                    "id": f"https://{vault}.vault.azure.net/certificates/ssl-cert",
                    "name": "ssl-cert",
                    "enabled": True,
                    "subject": "CN=react2shell.azurewebsites.net",
                },
            ],
            "vault": vault,
        }
        
        return CommandResult.success_result(
            json.dumps(certs, indent=2),
            metadata={"episode_id": episode_id, "command": "certificate list"}
        )

    async def _get_certificate(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """Execute 'certificate get' - Get certificate details."""
        episode_id = context.get("episode_id", "unknown")
        vault = params.get("vault", self._default_vault)
        cert_name = params["certificate"]
        
        cert = {
            "id": f"https://{vault}.vault.azure.net/certificates/{cert_name}",
            "name": cert_name,
            "subject": f"CN={cert_name}.azurewebsites.net",
            "issuer": "Self",
            "attributes": {
                "enabled": True,
                "notBefore": "2026-01-01T00:00:00Z",
                "expires": "2027-01-01T00:00:00Z",
            },
        }
        
        return CommandResult.success_result(
            json.dumps(cert, indent=2),
            metadata={"episode_id": episode_id, "command": "certificate get"}
        )

    async def _get_admin_settings(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """Execute 'admin settings get' - Get vault admin settings."""
        episode_id = context.get("episode_id", "unknown")
        vault = params.get("vault", self._default_vault)
        
        settings = {
            "vaultName": vault,
            "settings": {
                "softDeleteEnabled": True,
                "softDeleteRetentionDays": 90,
                "purgeProtectionEnabled": True,
                "enableRbacAuthorization": True,
                "publicNetworkAccess": "Enabled",
            },
        }
        
        return CommandResult.success_result(
            json.dumps(settings, indent=2),
            metadata={"episode_id": episode_id, "command": "admin settings get"}
        )


# Register the executor with SABER's executor registry
from saber.server.execution.executors.executor_registry import register_executor
register_executor("keyvault", KeyvaultExecutor, "azure_mcp_namespace")
