"""
Search Sigma Rules Executor - Search Sigma detection rules.

Logging category: LogCategory.DOCKER
"""

from typing import Any, Dict, List, Optional

from saber.logging_config import LogCategory, get_saber_logger
from saber.server.base import CommandResult
from saber.server.execution.base import Parameter, ParameterType
from saber.server.execution.executors.docker_executor import DockerExecutor
from saber.server.execution.sandbox.sandbox_environment_manager import SandboxEnvironmentManager

logger = get_saber_logger(LogCategory.DOCKER, __name__)


class SearchSigmaRulesExecutor(DockerExecutor):
    """Executor for search_sigma_rules tool."""

    _tool_name = "search_sigma_rules"
    _executor_metadata = {
        "name": "search_sigma_rules",
        "description": "Search Sigma detection rules by keyword, technique ID, or platform.",
    }

    @classmethod
    def get_default_config(cls) -> Dict[str, Any]:
        """Get default configuration."""
        return {"timeout": 120.0}

    @classmethod
    def create_with_config(
        cls,
        sandbox_manager: SandboxEnvironmentManager,
        config: Optional[Dict[str, Any]] = None,
        additional_params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> "SearchSigmaRulesExecutor":
        """Create executor with configuration."""
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
        """Initialize executor."""
        super().__init__(sandbox_manager=sandbox_manager, config=config, **kwargs)

    def setup_parameters(self, config: Dict[str, Any]) -> None:
        """Set up parameters."""
        self.add_parameter(
            Parameter(
                name="keyword",
                type=ParameterType.STRING,
                description="Search keyword",
                required=False,
            )
        )
        self.add_parameter(
            Parameter(
                name="technique_id",
                type=ParameterType.STRING,
                description="MITRE technique ID",
                required=False,
            )
        )
        self.add_parameter(
            Parameter(
                name="platform",
                type=ParameterType.STRING,
                description="Platform filter",
                required=False,
            )
        )
        self.add_parameter(
            Parameter(
                name="limit",
                type=ParameterType.INTEGER,
                description="Maximum number of results to return (default: 5)",
                required=False,
            )
        )

    def build_command(self, parameters: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
        """Build command to search Sigma rules from local data."""
        keyword = parameters.get("keyword", "")
        technique_id = parameters.get("technique_id", "")
        platform = parameters.get("platform", "")
        limit = parameters.get("limit", 5)

        keyword_escaped = keyword.replace("'", "'\\''").lower()
        technique_escaped = technique_id.replace("'", "'\\''").upper()
        platform_escaped = platform.replace("'", "'\\''").lower()

        script = f"""
import json
from pathlib import Path

sigma_file = Path("/workspace/data/sigma_rules.json")
if not sigma_file.exists():
    print(json.dumps({{"error": "Sigma rules index not found"}}))
else:
    with open(sigma_file) as f:
        rules = json.load(f)

    results = []
    keyword = "{keyword_escaped}"
    technique = "{technique_escaped}"
    plat = "{platform_escaped}"
    limit = {limit}

    for rule in rules:
        if keyword and keyword not in rule["title"].lower() and keyword not in rule["description"].lower():
            continue
        if technique and technique not in rule["techniques"]:
            continue
        if plat and plat not in rule["platform"].lower():
            continue
        results.append(rule)
        if len(results) >= limit:
            break

    print(json.dumps({{"count": len(results), "rules": results}}))
"""
        return ["/bin/sh", "-c", f"python3 -c '{script}'"]

    async def execute(self, parameters: Dict[str, Any], context: Dict[str, Any]) -> CommandResult:
        """Execute the CTI tool command in Docker container."""
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
        """Parse command output."""
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

register_executor("search_sigma_rules", SearchSigmaRulesExecutor, "domain:cti_realm")
