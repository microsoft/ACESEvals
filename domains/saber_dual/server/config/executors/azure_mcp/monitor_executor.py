"""
Azure MCP Compatible Monitor Namespace Executor

Mirrors the Azure MCP 'monitor' namespace tool interface exactly.
See: domains/saber_dual/docs/AZURE_MCP_TOOL_REFERENCE.md

Azure MCP Command: azmcp monitor
Sub-commands:
  - workspace log query
  - activitylog list
  - table list
  - table type list
  - metrics query
  - metrics definitions
  - resource log query
  - webtests create/get/list/update
  - healthmodels entity get
"""

import logging
import json
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, Optional, List, Type

from saber.server.execution.executors.docker_executor import DockerExecutor
from saber.server.execution.sandbox.sandbox_environment_manager import SandboxEnvironmentManager
from saber.server.execution.base import Parameter, ParameterType, ValidationResult, ExecutorParameters
from saber.server.execution.models import ExecutorConfig
from saber.server.base import CommandResult

from .parameters import MonitorParameters

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MonitorExecutorConfig(ExecutorConfig):
    """Configuration for MonitorExecutor."""
    siem_base_url: str = "http://siem-aggregator:8080"
    default_workspace: str = "react2shell-sentinel"
    default_subscription: str = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"


class MonitorExecutor(DockerExecutor):
    """
    Azure MCP Compatible: monitor (namespace mode)
    
    This executor mirrors the Azure MCP 'monitor' namespace tool interface,
    routing commands to the appropriate mock Azure Monitor services.
    
    Supported sub-commands:
      - workspace log query: Query Log Analytics workspace with KQL
      - activitylog list: List activity logs for resources
      - table list: List tables in a Log Analytics workspace
      - metrics query: Query Azure Monitor metrics
      - resource log query: Query diagnostic logs for specific resources
    """
    
    _executor_metadata = {
        "name": "monitor",
        "description": (
            "Azure Monitor operations - Commands for querying and analyzing "
            "Azure Monitor logs and metrics. Use 'workspace log query' to query "
            "Log Analytics workspaces with KQL. Use 'activitylog list' to retrieve "
            "activity logs for Azure resources."
        ),
    }

    # Define supported sub-commands and their required/optional parameters
    # This matches Azure MCP exactly
    SUPPORTED_COMMANDS = {
        "workspace log query": {
            "required": ["workspace", "query"],
            "optional": ["subscription", "hours", "limit", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries", 
                        "retry-mode", "retry-network-timeout"],
        },
        "activitylog list": {
            "required": ["resource-name"],
            "optional": ["subscription", "resource-group", "resource-type", "hours",
                        "event-level", "top", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "table list": {
            "required": ["workspace"],
            "optional": ["subscription", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "table type list": {
            "required": ["workspace"],
            "optional": ["subscription", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "metrics query": {
            "required": ["resource", "metric-names", "metric-namespace"],
            "optional": ["subscription", "resource-group", "resource-type",
                        "start-time", "end-time", "interval", "aggregation",
                        "filter", "max-buckets", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
        "metrics definitions": {
            "required": ["resource"],
            "optional": ["subscription", "resource-group", "resource-type",
                        "metric-namespace", "search-string", "limit", "tenant",
                        "auth-method", "retry-delay", "retry-max-delay",
                        "retry-max-retries", "retry-mode", "retry-network-timeout"],
        },
        "resource log query": {
            "required": ["resource-id", "workspace", "query"],
            "optional": ["subscription", "hours", "limit", "tenant", "auth-method",
                        "retry-delay", "retry-max-delay", "retry-max-retries",
                        "retry-mode", "retry-network-timeout"],
        },
    }

    @classmethod
    def get_parameters_class(cls) -> Type[ExecutorParameters]:
        """Get the parameter dataclass type for this executor."""
        return MonitorParameters

    @classmethod
    def get_default_config(cls) -> MonitorExecutorConfig:
        return MonitorExecutorConfig()

    @classmethod
    def create_with_config(
        cls,
        sandbox_manager: SandboxEnvironmentManager,
        config: Optional[MonitorExecutorConfig] = None,
        additional_params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> "MonitorExecutor":
        merged_kwargs = {**kwargs}
        if additional_params:
            merged_kwargs.update(additional_params)
        return cls(sandbox_manager=sandbox_manager, config=config, **merged_kwargs)

    def __init__(
        self,
        sandbox_manager: SandboxEnvironmentManager,
        config: Optional[MonitorExecutorConfig] = None,
        **kwargs: Any,
    ) -> None:
        typed_config = config if isinstance(config, MonitorExecutorConfig) else MonitorExecutorConfig()
        self._siem_base_url = typed_config.siem_base_url
        self._default_workspace = typed_config.default_workspace
        self._default_subscription = typed_config.default_subscription
        super().__init__(sandbox_manager=sandbox_manager, config=typed_config, **kwargs)

    def setup_parameters(self, config: ExecutorConfig) -> None:
        """
        Set up Azure MCP compatible parameters.
        
        In namespace mode, the tool accepts:
          - command: The sub-command to execute
          - parameters: Object containing sub-command specific parameters
        """
        self.add_parameter(
            Parameter(
                name="command",
                type=ParameterType.STRING,
                description=(
                    "The monitor sub-command to execute. Available commands: "
                    "'workspace log query', 'activitylog list', 'table list', "
                    "'table type list', 'metrics query', 'metrics definitions', "
                    "'resource log query'"
                ),
                required=True,
            )
        )
        
        self.add_parameter(
            Parameter(
                name="params",
                type=ParameterType.OBJECT,
                description=(
                    "Parameters for the sub-command. For 'workspace log query': "
                    "workspace (required), query (required - KQL), subscription, hours, limit. "
                    "For 'activitylog list': resource-name (required), subscription, "
                    "resource-group, resource-type, hours, event-level, top."
                ),
                required=True,
            )
        )

    def validate_parameters(self, parameters: Dict[str, Any]) -> ValidationResult:
        """Validate Azure MCP command and parameters."""
        result = super().validate_parameters(parameters)
        
        command = parameters.get("command", "")
        params = parameters.get("params", {})
        
        # Validate command is supported
        if command not in self.SUPPORTED_COMMANDS:
            result.add_error(
                f"Unsupported command: '{command}'. "
                f"Available commands: {', '.join(self.SUPPORTED_COMMANDS.keys())}"
            )
            return result
        
        # Validate required parameters for the command
        cmd_spec = self.SUPPORTED_COMMANDS[command]
        for req_param in cmd_spec["required"]:
            if req_param not in params or params[req_param] is None:
                result.add_error(f"Missing required parameter '{req_param}' for command '{command}'")
        
        return result

    async def execute(self, parameters: Dict[str, Any], context: Dict[str, Any]) -> CommandResult:
        """
        Execute Azure Monitor command through mock services.
        
        Routes to appropriate handler based on command.
        """
        episode_id = context.get("episode_id", "unknown")
        
        # Validate parameters
        validation = self.validate_parameters(parameters)
        if not validation.valid:
            return CommandResult.error_result(
                error=f"Parameter validation failed: {', '.join(validation.errors)}",
                metadata={"episode_id": episode_id}
            )
        
        # Ensure container is ready
        if not self.ensure_container_ready(episode_id):
            return CommandResult.error_result(
                error="Container not ready for execution",
                metadata={"episode_id": episode_id}
            )
        
        command = parameters["command"]
        params = parameters["params"]
        
        try:
            if command == "workspace log query":
                return await self._execute_workspace_log_query(params, context)
            elif command == "activitylog list":
                return await self._execute_activitylog_list(params, context)
            elif command == "table list":
                return await self._execute_table_list(params, context)
            elif command == "table type list":
                return await self._execute_table_type_list(params, context)
            elif command == "metrics query":
                return await self._execute_metrics_query(params, context)
            elif command == "metrics definitions":
                return await self._execute_metrics_definitions(params, context)
            elif command == "resource log query":
                return await self._execute_resource_log_query(params, context)
            else:
                return CommandResult.error_result(
                    error=f"Command '{command}' not implemented",
                    metadata={"episode_id": episode_id}
                )
        except Exception as e:
            logger.exception(f"Error executing monitor command '{command}'")
            return CommandResult.error_result(
                error=f"Execution error: {str(e)}",
                metadata={"episode_id": episode_id, "command": command}
            )

    async def _execute_workspace_log_query(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """
        Execute 'workspace log query' - Query Log Analytics with KQL.
        
        Maps to mock SIEM aggregator API.
        """
        episode_id = context.get("episode_id", "unknown")
        
        workspace = params.get("workspace", self._default_workspace)
        query = params["query"]
        hours = params.get("hours", "24")
        limit = params.get("limit", "1000")
        subscription = params.get("subscription", self._default_subscription)
        
        # Build SIEM API request - translate KQL query to our event API
        # The mock SIEM doesn't support full KQL, so we extract key filters
        api_url = f"{self._siem_base_url}/api/events"
        
        # Parse simple KQL patterns to extract filters
        timeframe = f"{hours}h" if hours else "24h"
        # Convert hours to our timeframe format (SIEM uses 1m, 2m, 5m)
        try:
            hours_int = int(hours) if hours else 24
            if hours_int <= 1:
                timeframe = "5m"  # Use 5m for short queries
            else:
                timeframe = "5m"  # Our mock SIEM has limited data
        except ValueError:
            timeframe = "5m"
        
        # Build query params
        query_params = [f"timeframe={timeframe}"]
        
        # Try to extract table name from KQL for event_types mapping
        kql_lower = query.lower()
        if "securityevent" in kql_lower or "security" in kql_lower:
            query_params.append("event_types=auth_attempt")
            query_params.append("event_types=auth_success")
            query_params.append("event_types=auth_failure")
        if "azureactivity" in kql_lower or "activity" in kql_lower:
            query_params.append("event_types=api_request")
            query_params.append("event_types=vault_request")
        if "keyvault" in kql_lower or "secret" in kql_lower:
            query_params.append("event_types=secret_access")
            query_params.append("event_types=vault_request")
        if "network" in kql_lower or "connection" in kql_lower:
            query_params.append("event_types=network_connection")
        
        full_url = f"{api_url}?{'&'.join(query_params)}"
        
        # Execute curl in container
        curl_cmd = f"curl -s '{full_url}'"
        
        environment = self.get_episode_environment(episode_id)
        exec_result = await self._run_in_container(
            episode_id=episode_id,
            command=curl_cmd,
            environment=environment,
        )
        
        if exec_result.exit_code != 0:
            return CommandResult.error_result(
                error=f"Log Analytics query failed: {exec_result.stderr}",
                metadata={
                    "episode_id": episode_id,
                    "workspace": workspace,
                    "subscription": subscription,
                }
            )
        
        # Format response to match Azure MCP output
        try:
            events = json.loads(exec_result.stdout) if exec_result.stdout else []
            response = {
                "tables": [{
                    "name": "PrimaryResult",
                    "columns": [
                        {"name": "TimeGenerated", "type": "datetime"},
                        {"name": "Source", "type": "string"},
                        {"name": "EventType", "type": "string"},
                        {"name": "Message", "type": "string"},
                        {"name": "SourceIP", "type": "string"},
                    ],
                    "rows": [
                        [
                            e.get("timestamp", ""),
                            e.get("source", ""),
                            e.get("event_type", ""),
                            e.get("message", ""),
                            e.get("details", {}).get("source_ip", e.get("details", {}).get("ip", "")),
                        ]
                        for e in events
                    ]
                }],
                "workspace": workspace,
                "subscription": subscription,
                "query": query,
            }
        except json.JSONDecodeError:
            response = {"raw": exec_result.stdout, "workspace": workspace}
        
        return CommandResult.success_result(
            json.dumps(response, indent=2),
            metadata={
                "episode_id": episode_id,
                "command": "workspace log query",
                "workspace": workspace,
                "subscription": subscription,
                "row_count": len(response.get("tables", [{}])[0].get("rows", [])),
            }
        )

    async def _execute_activitylog_list(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """Execute 'activitylog list' - List activity logs for a resource."""
        episode_id = context.get("episode_id", "unknown")
        
        resource_name = params["resource-name"]
        resource_group = params.get("resource-group", "")
        resource_type = params.get("resource-type", "")
        hours = params.get("hours", "24")
        event_level = params.get("event-level", "")
        top = params.get("top", "100")
        subscription = params.get("subscription", self._default_subscription)
        
        # Query SIEM for activity events
        api_url = f"{self._siem_base_url}/api/events"
        query_params = ["timeframe=5m", "event_types=api_request", "event_types=vault_request"]
        full_url = f"{api_url}?{'&'.join(query_params)}"
        
        curl_cmd = f"curl -s '{full_url}'"
        
        environment = self.get_episode_environment(episode_id)
        exec_result = await self._run_in_container(
            episode_id=episode_id,
            command=curl_cmd,
            environment=environment,
        )
        
        if exec_result.exit_code != 0:
            return CommandResult.error_result(
                error=f"Activity log query failed: {exec_result.stderr}",
                metadata={"episode_id": episode_id}
            )
        
        # Format as Azure Activity Log response
        try:
            events = json.loads(exec_result.stdout) if exec_result.stdout else []
            # Filter by resource name if specified
            if resource_name:
                events = [e for e in events if resource_name.lower() in json.dumps(e).lower()]
            
            response = {
                "value": [
                    {
                        "eventTimestamp": e.get("timestamp", ""),
                        "operationName": {"value": e.get("event_type", "")},
                        "status": {"value": "Succeeded"},
                        "caller": e.get("details", {}).get("source_ip", "system"),
                        "resourceId": f"/subscriptions/{subscription}/resourceGroups/{resource_group}/providers/{resource_type}/{resource_name}",
                        "properties": e.get("details", {}),
                    }
                    for e in events[:int(top)]
                ],
                "resourceName": resource_name,
                "subscription": subscription,
            }
        except json.JSONDecodeError:
            response = {"raw": exec_result.stdout}
        
        return CommandResult.success_result(
            json.dumps(response, indent=2),
            metadata={
                "episode_id": episode_id,
                "command": "activitylog list",
                "resource_name": resource_name,
            }
        )

    async def _execute_table_list(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """Execute 'table list' - List tables in Log Analytics workspace."""
        episode_id = context.get("episode_id", "unknown")
        workspace = params.get("workspace", self._default_workspace)
        subscription = params.get("subscription", self._default_subscription)
        
        # Return mock table list matching Azure Sentinel schema
        tables = {
            "value": [
                {"name": "SecurityEvent", "description": "Windows Security Events"},
                {"name": "AzureActivity", "description": "Azure Activity Log"},
                {"name": "AzureDiagnostics", "description": "Azure Diagnostic Logs"},
                {"name": "SigninLogs", "description": "Azure AD Sign-in Logs"},
                {"name": "AuditLogs", "description": "Azure AD Audit Logs"},
                {"name": "KeyVaultAuditLogs", "description": "Key Vault Audit Logs"},
                {"name": "StorageBlobLogs", "description": "Storage Blob Access Logs"},
                {"name": "AzureMetrics", "description": "Azure Resource Metrics"},
                {"name": "NetworkConnectionEvents", "description": "Network Flow Logs"},
                {"name": "AppServiceHTTPLogs", "description": "App Service HTTP Logs"},
            ],
            "workspace": workspace,
            "subscription": subscription,
        }
        
        return CommandResult.success_result(
            json.dumps(tables, indent=2),
            metadata={
                "episode_id": episode_id,
                "command": "table list",
                "workspace": workspace,
            }
        )

    async def _execute_table_type_list(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """Execute 'table type list' - List table types in workspace."""
        episode_id = context.get("episode_id", "unknown")
        workspace = params.get("workspace", self._default_workspace)
        
        # Return mock table types
        table_types = {
            "value": [
                {"type": "Microsoft.SecurityInsights/SecurityEvent"},
                {"type": "Microsoft.Insights/AzureActivity"},
                {"type": "Microsoft.Insights/AzureDiagnostics"},
                {"type": "Microsoft.AAD/SigninLogs"},
            ],
            "workspace": workspace,
        }
        
        return CommandResult.success_result(
            json.dumps(table_types, indent=2),
            metadata={"episode_id": episode_id, "command": "table type list"}
        )

    async def _execute_metrics_query(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """Execute 'metrics query' - Query Azure Monitor metrics."""
        episode_id = context.get("episode_id", "unknown")
        
        resource = params["resource"]
        metric_names = params["metric-names"]
        metric_namespace = params["metric-namespace"]
        aggregation = params.get("aggregation", "Average")
        
        # Return mock metrics response
        metrics = {
            "value": [
                {
                    "name": {"value": metric_names},
                    "timeseries": [
                        {
                            "data": [
                                {"timeStamp": "2026-01-16T06:00:00Z", "average": 45.2},
                                {"timeStamp": "2026-01-16T06:05:00Z", "average": 52.8},
                                {"timeStamp": "2026-01-16T06:10:00Z", "average": 48.1},
                            ]
                        }
                    ],
                    "unit": "Percent",
                }
            ],
            "resource": resource,
            "namespace": metric_namespace,
        }
        
        return CommandResult.success_result(
            json.dumps(metrics, indent=2),
            metadata={"episode_id": episode_id, "command": "metrics query"}
        )

    async def _execute_metrics_definitions(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """Execute 'metrics definitions' - List available metrics for resource."""
        episode_id = context.get("episode_id", "unknown")
        resource = params["resource"]
        
        definitions = {
            "value": [
                {"name": {"value": "CpuPercentage"}, "unit": "Percent"},
                {"name": {"value": "MemoryPercentage"}, "unit": "Percent"},
                {"name": {"value": "NetworkBytesIn"}, "unit": "Bytes"},
                {"name": {"value": "NetworkBytesOut"}, "unit": "Bytes"},
                {"name": {"value": "Http2xx"}, "unit": "Count"},
                {"name": {"value": "Http4xx"}, "unit": "Count"},
                {"name": {"value": "Http5xx"}, "unit": "Count"},
            ],
            "resource": resource,
        }
        
        return CommandResult.success_result(
            json.dumps(definitions, indent=2),
            metadata={"episode_id": episode_id, "command": "metrics definitions"}
        )

    async def _execute_resource_log_query(
        self, params: Dict[str, Any], context: Dict[str, Any]
    ) -> CommandResult:
        """Execute 'resource log query' - Query logs for specific resource."""
        # Delegate to workspace log query with resource context
        params["workspace"] = params.get("workspace", self._default_workspace)
        return await self._execute_workspace_log_query(params, context)

    async def _run_in_container(
        self, episode_id: str, command: str, environment: Dict[str, str]
    ) -> Any:
        """Execute command in the sandbox container."""
        container_name = f"siem-aggregator-{episode_id}"
        
        # Build docker exec command
        docker_cmd = f"docker exec {container_name} sh -c '{command}'"
        
        import asyncio
        import subprocess
        
        proc = await asyncio.create_subprocess_shell(
            docker_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        
        class ExecResult:
            def __init__(self, code, out, err):
                self.exit_code = code
                self.stdout = out.decode() if out else ""
                self.stderr = err.decode() if err else ""
        
        return ExecResult(proc.returncode, stdout, stderr)


# Register the executor with SABER's executor registry
from saber.server.execution.executors.executor_registry import register_executor
register_executor("monitor", MonitorExecutor, "azure_mcp_namespace")
