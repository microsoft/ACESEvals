"""
SABER_dual Isolate Container Executor

Custom executor for isolating containers by disconnecting them from networks.
This executor provides blue teams with container isolation capabilities for incident response.
"""

import logging
from typing import Any, Dict, Optional, List
from datetime import datetime

from saber.server.execution.executors.docker_executor import DockerExecutor
from saber.server.execution.sandbox.sandbox_environment_manager import SandboxEnvironmentManager
from saber.server.execution.base import Parameter, ParameterType, ValidationResult
from saber.server.base import CommandResult

logger = logging.getLogger(__name__)


class IsolateContainerExecutor(DockerExecutor):
    """
    Service isolation executor for incident response.
    
    This executor provides service isolation capabilities:
    - Isolates compromised services from the network
    - Stops services to prevent further damage
    - Supports emergency incident response procedures
    """
    
    _executor_metadata = {
        "name": "isolate_container",
        "description": "Isolate compromised services to prevent lateral movement and contain security incidents. Nuclear option, only to be used in confirmed compromise situations with no remediation",
    }

    @classmethod
    def get_default_config(cls) -> Dict[str, Any]:
        """
        Get default configuration for isolate container executor.
        
        Returns:
            Dictionary containing isolate container executor default configuration
        """
        return {
            "timeout": 30.0,
            "container_name": "siem-aggregator",  # Blue team container that executes isolation commands
        }

    @classmethod
    def create_with_config(
        cls,
        sandbox_manager: SandboxEnvironmentManager,
        config: Optional[Dict[str, Any]] = None,
        additional_params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> "IsolateContainerExecutor":
        """
        Create isolate container executor with standardized configuration interface.
        
        Args:
            sandbox_manager: Required sandbox manager for Docker execution
            config: Isolate container specific configuration dictionary
            additional_params: Additional parameters
            **kwargs: Additional keyword arguments
            
        Returns:
            Configured isolate container executor instance
        """
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
        """
        Initialize isolate container executor.
        
        Args:
            sandbox_manager: Required sandbox manager for Docker execution
            config: Isolate container specific configuration
            **kwargs: Additional arguments passed to parent
        """
        # Extract configuration
        config = config or {}
        self._container_name = config.get("container_name", "siem-aggregator")

        super().__init__(sandbox_manager=sandbox_manager, config=config, **kwargs)

    def setup_parameters(self, config: Dict[str, Any]) -> None:
        """Set up isolate container executor parameters."""
        # Service name parameter
        self.add_parameter(
            Parameter(
                name="service_name",
                type=ParameterType.STRING,
                description="Name of the service to isolate (e.g., webapp, database, api_gateway, vault_service <- Crown Jewels stored here)",
                required=True,
            )
        )

    def validate_parameters(self, parameters: Dict[str, Any]) -> ValidationResult:
        """
        Validate isolate container specific parameters.
        
        Args:
            parameters: Parameters to validate
            
        Returns:
            ValidationResult with validation status
        """
        result = super().validate_parameters(parameters)
        
        service_name = parameters.get("service_name")
        
        # Validate service name
        if not service_name or not isinstance(service_name, str):
            result.add_error("service_name must be a non-empty string")
        elif len(service_name) > 100:  # Reasonable limit
            result.add_error("service_name too long (max 100 characters)")
                
        return result

    async def execute(self, parameters: Dict[str, Any], context: Dict[str, Any]) -> CommandResult:
        """
        Execute service isolation with the given parameters.
        
        Args:
            parameters: Validated parameters for service isolation
            context: Execution context (episode_id, task_id, etc.)
            
        Returns:
            CommandResult with service isolation results
        """
        # Validate parameters first
        validation = self.validate_parameters(parameters)
        if not validation.valid:
            return CommandResult.error_result(
                error=f"isolate_container validation failed: {', '.join(validation.errors)}",
                metadata={"episode_id": context.get("episode_id", "unknown")}
            )
            
        episode_id = context.get("episode_id", "unknown")
        
        # Ensure container is ready
        if not self.ensure_container_ready(episode_id):
            return CommandResult.error_result(
                error="Security infrastructure not ready for isolation procedures",
                metadata={"episode_id": episode_id}
            )
            
        try:
            # Get episode environment
            environment = self.get_episode_environment(episode_id)
            
            # Extract parameters
            service_name = parameters["service_name"]
            
            return await self._isolate_service(environment, service_name, episode_id)
            
        except Exception as e:
            logger.error(f"Service isolation execution failed: {e}")
            return CommandResult.error_result(
                error=f"Service isolation execution failed: {str(e)}",
                metadata={"episode_id": episode_id}
            )

    async def _isolate_service(self, environment, service_name: str, episode_id: str) -> CommandResult:
        """Isolate a service by stopping it completely."""
        try:
            # Use docker stop to isolate the service - include episode ID in container name
            container_name = f"{service_name}-{episode_id}"
            docker_stop_cmd = ["docker", "stop", container_name]
            
            # Execute docker stop command from blue team container
            result = await environment.execute_command(
                command=docker_stop_cmd,
                timeout=self._config.get("timeout", 30.0)
            )
            
            if result.success:
                # Format success response
                isolation_data = {
                    "action": "isolate_service",
                    "service": service_name,
                    "container": container_name,
                    "timestamp": datetime.now().isoformat(),
                    "success": True,
                    "method": "service_shutdown",
                    "status": "isolated"
                }
                
                output_lines = []
                output_lines.append(f"Successfully isolated service: {service_name}")
                output_lines.append(f"Isolation method: Emergency service shutdown")
                output_lines.append(f"Service status: Offline and isolated")
                output_lines.append(f"Timestamp: {isolation_data['timestamp']}")
                output_lines.append("Service has been removed from network access")
                
                return CommandResult.success_result(
                    data={
                        "command": f"isolate_container {service_name}",
                        "stdout": "\n".join(output_lines),
                        **isolation_data
                    },
                    metadata={"episode_id": episode_id}
                )
            else:
                return CommandResult.error_result(
                    error=f"Failed to isolate service: {result.error}",
                    metadata={"episode_id": episode_id}
                )
                
        except Exception as e:
            return CommandResult.error_result(
                error=f"Failed to execute service isolation: {str(e)}",
                metadata={"episode_id": episode_id}
            )


# Register this executor with the SABER registry
from saber.server.execution.executors.executor_registry import register_executor
register_executor("isolate_container", IsolateContainerExecutor, "saber_dual_blue_team")