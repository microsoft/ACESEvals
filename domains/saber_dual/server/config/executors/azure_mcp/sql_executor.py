"""
Azure MCP Compatible SQL Namespace Executor

Mirrors the Azure MCP 'sql' namespace tool interface exactly.
See: domains/saber_dual/docs/AZURE_MCP_TOOL_REFERENCE.md

Azure MCP Command: azmcp sql
Sub-commands:
  - server firewall-rule create
  - server firewall-rule delete
  - server firewall-rule list
  - server list
  - server show
  - server create
  - server delete
  - server entra-admin list
  - db list
  - db show
  - db create
  - db delete
  - db update
  - db rename
  - elastic-pool list
"""

import logging
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Type
from datetime import datetime

from saber.server.execution.executors.docker_executor import DockerExecutor
from saber.server.execution.sandbox.sandbox_environment_manager import SandboxEnvironmentManager
from saber.server.execution.base import Parameter, ParameterType, ValidationResult, ExecutorParameters
from saber.server.execution.models import ExecutorConfig
from saber.server.base import CommandResult

from .parameters import SqlParameters

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SqlExecutorConfig(ExecutorConfig):
    """Configuration for SqlExecutor."""
    siem_base_url: str = "http://siem-aggregator:8080"
    default_subscription: str = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    default_resource_group: str = "react2shell-rg"
    default_server: str = "react2shell-sql"


class SqlExecutor(DockerExecutor):
    """
    Azure MCP Compatible: sql (namespace mode)
    
    This executor mirrors the Azure MCP 'sql' namespace tool interface,
    enabling firewall rule management for SQL servers in the simulation.
    
    Primary use case for Blue Team: Block attacker IPs via firewall rules.
    
    Supported sub-commands:
      - server firewall-rule create: Create firewall rule (block/allow IP)
      - server firewall-rule delete: Delete firewall rule
      - server firewall-rule list: List existing firewall rules
      - server list: List SQL servers
      - server show: Show SQL server details
      - db list: List databases on a server
    """
    
    _executor_metadata = {
        "name": "sql",
        "description": (
            "Azure SQL operations - Commands for managing Azure SQL databases, "
            "servers, and elastic pools. Includes operations for listing databases, "
            "configuring server settings, managing firewall rules, Entra ID administrators, "
            "and elastic pool resources."
        ),
    }

    SUPPORTED_COMMANDS = {
        "server firewall-rule create": {
            "required": ["resource-group", "server", "rule-name", "start-ip", "end-ip"],
            "optional": ["subscription", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "server firewall-rule delete": {
            "required": ["resource-group", "server", "rule-name"],
            "optional": ["subscription", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "server firewall-rule list": {
            "required": ["resource-group", "server"],
            "optional": ["subscription", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "server list": {
            "required": [],
            "optional": ["subscription", "resource-group", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "server show": {
            "required": ["resource-group", "server"],
            "optional": ["subscription", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "server create": {
            "required": ["resource-group", "server", "admin-user", "admin-password"],
            "optional": ["subscription", "location", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "server delete": {
            "required": ["resource-group", "server"],
            "optional": ["subscription", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "server entra-admin list": {
            "required": ["resource-group", "server"],
            "optional": ["subscription", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "db list": {
            "required": ["resource-group", "server"],
            "optional": ["subscription", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "db show": {
            "required": ["resource-group", "server", "database"],
            "optional": ["subscription", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "db create": {
            "required": ["resource-group", "server", "database"],
            "optional": ["subscription", "sku", "max-size", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "db delete": {
            "required": ["resource-group", "server", "database"],
            "optional": ["subscription", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "db update": {
            "required": ["resource-group", "server", "database"],
            "optional": ["subscription", "sku", "max-size", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "db rename": {
            "required": ["resource-group", "server", "database", "new-name"],
            "optional": ["subscription", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "elastic-pool list": {
            "required": ["resource-group", "server"],
            "optional": ["subscription", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
    }

    @classmethod
    def get_parameters_class(cls) -> Type[ExecutorParameters]:
        """Get the parameter dataclass type for this executor."""
        return SqlParameters

    @classmethod
    def get_default_config(cls) -> SqlExecutorConfig:
        return SqlExecutorConfig()

    @classmethod
    def create_with_config(
        cls,
        sandbox_manager: SandboxEnvironmentManager,
        config: Optional[SqlExecutorConfig] = None,
        additional_params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> "SqlExecutor":
        merged_kwargs = {**kwargs}
        if additional_params:
            merged_kwargs.update(additional_params)
        return cls(sandbox_manager=sandbox_manager, config=config, **merged_kwargs)

    def __init__(
        self,
        sandbox_manager: SandboxEnvironmentManager,
        config: Optional[SqlExecutorConfig] = None,
        **kwargs: Any,
    ) -> None:
        typed_config = config if isinstance(config, SqlExecutorConfig) else SqlExecutorConfig()
        self._siem_base_url = typed_config.siem_base_url
        self._default_subscription = typed_config.default_subscription
        self._default_resource_group = typed_config.default_resource_group
        self._default_server = typed_config.default_server
        
        # In-memory firewall rules store (simulates Azure SQL firewall)
        self._firewall_rules: Dict[str, Dict[str, Any]] = {}
        
        super().__init__(sandbox_manager=sandbox_manager, config=typed_config, **kwargs)

    def setup_parameters(self, config: ExecutorConfig) -> None:
        """Set up Azure MCP compatible parameters."""
        self.add_parameter(
            Parameter(
                name="command",
                type=ParameterType.STRING,
                description=(
                    "The SQL sub-command to execute. Available commands: "
                    "'server firewall-rule create', 'server firewall-rule delete', "
                    "'server firewall-rule list', 'server list', 'server show', "
                    "'db list', 'db show'"
                ),
                required=True,
            )
        )
        
        self.add_parameter(
            Parameter(
                name="params",
                type=ParameterType.OBJECT,
                description=(
                    "Parameters for the sub-command. For 'server firewall-rule create': "
                    "resource-group (required), server (required), rule-name (required), "
                    "start-ip (required), end-ip (required), subscription. "
                    "For 'server firewall-rule delete': resource-group, server, rule-name. "
                    "For 'server firewall-rule list': resource-group, server."
                ),
                required=True,
            )
        )

    def validate_parameters(self, parameters: Dict[str, Any]) -> ValidationResult:
        """Validate Azure MCP command and parameters."""
        result = super().validate_parameters(parameters)
        
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
        
        # Validate IP addresses for firewall rules
        if command == "server firewall-rule create":
            for ip_param in ["start-ip", "end-ip"]:
                if ip_param in params:
                    if not self._is_valid_ip(params[ip_param]):
                        result.add_error(f"Invalid IP address format for '{ip_param}': {params[ip_param]}")
        
        return result

    def _is_valid_ip(self, ip: str) -> bool:
        """Validate IP address format."""
        pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
        if not re.match(pattern, ip):
            return False
        octets = ip.split('.')
        return all(0 <= int(o) <= 255 for o in octets)

    async def execute(self, parameters: Dict[str, Any], context: Dict[str, Any]) -> CommandResult:
        """Execute Azure SQL command."""
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
            if command == "server firewall-rule create":
                return await self._create_firewall_rule(params, context)
            elif command == "server firewall-rule delete":
                return await self._delete_firewall_rule(params, context)
            elif command == "server firewall-rule list":
                return await self._list_firewall_rules(params, context)
            elif command == "server list":
                return await self._list_servers(params, context)
            elif command == "server show":
                return await self._show_server(params, context)
            elif command == "db list":
                return await self._list_databases(params, context)
            elif command == "db show":
                return await self._show_database(params, context)
            else:
                return CommandResult.error_result(
                    error=f"Command '{command}' not implemented",
                    metadata={"episode_id": episode_id}
                )
        except Exception as e:
            logger.exception(f"Error executing SQL command '{command}'")
            return CommandResult.error_result(
                error=f"Execution error: {str(e)}",
                metadata={"episode_id": episode_id, "command": command}
            )

    async def _create_firewall_rule(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """
        Execute 'server firewall-rule create' - Create/update firewall rule.
        
        This is the primary defensive action for Blue Team to block attacker IPs.
        Also triggers the actual IP block via SIEM aggregator API.
        """
        episode_id = context.get("episode_id", "unknown")
        
        resource_group = params.get("resource-group", self._default_resource_group)
        server = params.get("server", self._default_server)
        rule_name = params["rule-name"]
        start_ip = params["start-ip"]
        end_ip = params["end-ip"]
        subscription = params.get("subscription", self._default_subscription)
        
        # Store the firewall rule
        rule_key = f"{server}/{rule_name}"
        rule = {
            "id": f"/subscriptions/{subscription}/resourceGroups/{resource_group}/providers/Microsoft.Sql/servers/{server}/firewallRules/{rule_name}",
            "name": rule_name,
            "type": "Microsoft.Sql/servers/firewallRules",
            "properties": {
                "startIpAddress": start_ip,
                "endIpAddress": end_ip,
            },
            "createdAt": datetime.utcnow().isoformat() + "Z",
        }
        self._firewall_rules[rule_key] = rule
        
        # ALSO trigger actual IP block via SIEM aggregator (for simulation effect)
        # This is the SABER-specific integration
        if start_ip == end_ip:
            # Single IP block
            await self._trigger_ip_block(episode_id, start_ip)
        
        logger.info(f"Created SQL firewall rule: {rule_name} ({start_ip} - {end_ip})")
        
        return CommandResult.success_result(
            json.dumps(rule, indent=2),
            metadata={
                "episode_id": episode_id,
                "command": "server firewall-rule create",
                "rule_name": rule_name,
                "start_ip": start_ip,
                "end_ip": end_ip,
                "action": "block_ip" if "block" in rule_name.lower() or "deny" in rule_name.lower() else "allow_ip",
            }
        )

    async def _trigger_ip_block(self, episode_id: str, ip: str) -> None:
        """Trigger actual IP block in the simulation via SIEM aggregator."""
        try:
            import asyncio
            import subprocess
            
            container_name = f"siem-aggregator-{episode_id}"
            # Call the block_ip endpoint on SIEM aggregator
            curl_cmd = f"curl -s -X POST '{self._siem_base_url}/api/block_ip' -H 'Content-Type: application/json' -d '{{\"ip_address\": \"{ip}\"}}'"
            docker_cmd = f"docker exec {container_name} sh -c \"{curl_cmd}\""
            
            proc = await asyncio.create_subprocess_shell(
                docker_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            await proc.communicate()
            logger.info(f"Triggered IP block for {ip} via SIEM aggregator")
        except Exception as e:
            logger.warning(f"Failed to trigger IP block: {e}")

    async def _delete_firewall_rule(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """Execute 'server firewall-rule delete' - Delete firewall rule."""
        episode_id = context.get("episode_id", "unknown")
        
        server = params.get("server", self._default_server)
        rule_name = params["rule-name"]
        
        rule_key = f"{server}/{rule_name}"
        
        if rule_key not in self._firewall_rules:
            return CommandResult.error_result(
                error=f"Firewall rule '{rule_name}' not found on server '{server}'",
                metadata={"episode_id": episode_id}
            )
        
        deleted_rule = self._firewall_rules.pop(rule_key)
        
        return CommandResult.success_result(
            json.dumps({"message": f"Firewall rule '{rule_name}' deleted successfully", "rule": deleted_rule}, indent=2),
            metadata={
                "episode_id": episode_id,
                "command": "server firewall-rule delete",
                "rule_name": rule_name,
            }
        )

    async def _list_firewall_rules(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """Execute 'server firewall-rule list' - List firewall rules."""
        episode_id = context.get("episode_id", "unknown")
        
        server = params.get("server", self._default_server)
        subscription = params.get("subscription", self._default_subscription)
        
        # Filter rules for this server
        rules = [
            rule for key, rule in self._firewall_rules.items()
            if key.startswith(f"{server}/")
        ]
        
        # Add default rules that always exist
        default_rules = [
            {
                "name": "AllowAllWindowsAzureIps",
                "properties": {"startIpAddress": "0.0.0.0", "endIpAddress": "0.0.0.0"},
            },
            {
                "name": "AllowInternalServices",
                "properties": {"startIpAddress": "10.0.0.0", "endIpAddress": "10.255.255.255"},
            },
        ]
        
        response = {
            "value": default_rules + rules,
            "server": server,
            "subscription": subscription,
        }
        
        return CommandResult.success_result(
            json.dumps(response, indent=2),
            metadata={
                "episode_id": episode_id,
                "command": "server firewall-rule list",
                "rule_count": len(response["value"]),
            }
        )

    async def _list_servers(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """Execute 'server list' - List SQL servers."""
        episode_id = context.get("episode_id", "unknown")
        subscription = params.get("subscription", self._default_subscription)
        
        servers = {
            "value": [
                {
                    "name": "react2shell-sql",
                    "location": "eastus",
                    "fullyQualifiedDomainName": "react2shell-sql.database.windows.net",
                    "administratorLogin": "sqladmin",
                    "version": "12.0",
                    "state": "Ready",
                },
            ],
            "subscription": subscription,
        }
        
        return CommandResult.success_result(
            json.dumps(servers, indent=2),
            metadata={"episode_id": episode_id, "command": "server list"}
        )

    async def _show_server(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """Execute 'server show' - Show SQL server details."""
        episode_id = context.get("episode_id", "unknown")
        server = params.get("server", self._default_server)
        resource_group = params.get("resource-group", self._default_resource_group)
        subscription = params.get("subscription", self._default_subscription)
        
        server_info = {
            "id": f"/subscriptions/{subscription}/resourceGroups/{resource_group}/providers/Microsoft.Sql/servers/{server}",
            "name": server,
            "type": "Microsoft.Sql/servers",
            "location": "eastus",
            "properties": {
                "fullyQualifiedDomainName": f"{server}.database.windows.net",
                "administratorLogin": "sqladmin",
                "version": "12.0",
                "state": "Ready",
                "publicNetworkAccess": "Enabled",
            },
        }
        
        return CommandResult.success_result(
            json.dumps(server_info, indent=2),
            metadata={"episode_id": episode_id, "command": "server show"}
        )

    async def _list_databases(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """Execute 'db list' - List databases on a server."""
        episode_id = context.get("episode_id", "unknown")
        server = params.get("server", self._default_server)
        
        databases = {
            "value": [
                {
                    "name": "react2shell-db",
                    "status": "Online",
                    "sku": {"name": "Standard", "tier": "Standard"},
                    "maxSizeBytes": 268435456000,
                },
                {
                    "name": "master",
                    "status": "Online",
                    "sku": {"name": "System", "tier": "System"},
                },
            ],
            "server": server,
        }
        
        return CommandResult.success_result(
            json.dumps(databases, indent=2),
            metadata={"episode_id": episode_id, "command": "db list"}
        )

    async def _show_database(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """Execute 'db show' - Show database details."""
        episode_id = context.get("episode_id", "unknown")
        database = params.get("database", "react2shell-db")
        
        db_info = {
            "name": database,
            "status": "Online",
            "creationDate": "2026-01-01T00:00:00Z",
            "maxSizeBytes": 268435456000,
            "sku": {"name": "Standard", "tier": "Standard", "capacity": 10},
        }
        
        return CommandResult.success_result(
            json.dumps(db_info, indent=2),
            metadata={"episode_id": episode_id, "command": "db show"}
        )


# Register the executor with SABER's executor registry
from saber.server.execution.executors.executor_registry import register_executor
register_executor("sql", SqlExecutor, "azure_mcp_namespace")
