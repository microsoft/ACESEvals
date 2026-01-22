"""
Get Table Schema Executor - Get schema for a specific Kusto table.

Logging category: LogCategory.DOCKER
"""

from typing import Any, Dict, List, Optional

from saber.logging_config import LogCategory, get_saber_logger
from saber.server.base import CommandResult
from saber.server.execution.base import Parameter, ParameterType
from saber.server.execution.executors.docker_executor import DockerExecutor
from saber.server.execution.sandbox.sandbox_environment_manager import SandboxEnvironmentManager

logger = get_saber_logger(LogCategory.DOCKER, __name__)


class GetTableSchemaExecutor(DockerExecutor):
    """Executor for get_table_schema tool."""

    _tool_name = "get_table_schema"
    _executor_metadata = {
        "name": "get_table_schema",
        "description": "Get the schema (columns and data types) for a specific table.",
    }

    @classmethod
    def get_default_config(cls) -> Dict[str, Any]:
        return {"timeout": 120.0}

    @classmethod
    def create_with_config(
        cls,
        sandbox_manager: SandboxEnvironmentManager,
        config: Optional[Dict[str, Any]] = None,
        additional_params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> "GetTableSchemaExecutor":
        merged_kwargs = {**kwargs}
        if additional_params:
            merged_kwargs.update(additional_params)
        return cls(sandbox_manager=sandbox_manager, config=config, **merged_kwargs)

    def __init__(
        self, sandbox_manager: SandboxEnvironmentManager, config: Optional[Dict[str, Any]] = None, **kwargs: Any
    ) -> None:
        super().__init__(sandbox_manager=sandbox_manager, config=config, **kwargs)

    def setup_parameters(self, config: Dict[str, Any]) -> None:
        """Set up parameters."""
        self.add_parameter(
            Parameter(
                name="table",
                type=ParameterType.STRING,
                description="Name of the table to examine",
                required=True,
            )
        )

    def build_command(self, parameters: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
        """Build command with direct HTTP call to Kusto using curl."""
        import json

        table = parameters.get("table", "")
        payload = json.dumps({"db": "NetDefaultDB", "csl": f"{table} | getschema"})

        return [
            "curl",
            "-s",
            "-X", "POST",
            "http://saber-cti-kusto-emulator:8080/v1/rest/query",
            "-H", "Content-Type: application/json",
            "-d", payload,
        ]

    async def execute(self, parameters: Dict[str, Any], context: Dict[str, Any]) -> CommandResult:
        try:
            episode_id = context.get("episode_id")
            if not episode_id:
                from saber.server.execution.exceptions import SandboxExecutionError

                raise SandboxExecutionError("episode_id required in context for Docker execution")
            environment = self.get_episode_environment(episode_id)
            timeout = int(self.get_timeout())
            command = self.build_command(parameters, context)
            result = await environment.execute_command(command=command, timeout=timeout)
            tool_result = self.parse_output(result.stdout, result.stderr, result.exit_code)
            container = environment.get_execution_container()
            container_id = container.id[:12] if container else "unknown"
            tool_result.metadata.update(
                {
                    "container_id": container_id,
                    "episode_id": episode_id,
                    "execution_time": result.execution_time,
                    "tool": self._tool_name,
                }
            )
            return tool_result
        except Exception as e:
            logger.error(
                f"{self._tool_name} execution error: {e}",
                extra={
                    "event": "cti_tool_execution_error",
                    "episode_id": context.get("episode_id"),
                    "tool": self._tool_name,
                    "error": str(e),
                },
            )
            return CommandResult.error_result(f"{self._tool_name} execution failed: {str(e)}")

    def parse_output(self, stdout: str, stderr: str, return_code: int) -> CommandResult:
        success = return_code == 0
        result_data = {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": return_code,
            "success": success,
            "output": stdout if success else stderr,
        }
        metadata = {"command_type": self._tool_name, "exit_code": return_code}
        if success:
            return CommandResult.success_result(data=result_data, metadata=metadata)
        else:
            error_msg = f"Command failed with exit code {return_code}"
            if stderr.strip():
                error_msg += f": {stderr.strip()}"
            return CommandResult.error_result(error=error_msg, metadata={**metadata, "raw_data": result_data})


# Register this executor
from saber.server.execution.executors.executor_registry import register_executor

register_executor("get_table_schema", GetTableSchemaExecutor, "domain:cti_realm")
