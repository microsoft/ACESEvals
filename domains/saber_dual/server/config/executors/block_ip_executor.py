"""
SABER_dual Block IP Executor

Custom executor for blocking IP addresses using iptables network defense.
This executor provides blue teams with network-level IP blocking capabilities.
"""

import logging
import ipaddress
from typing import Any, Dict, Optional
from datetime import datetime

from saber.server.execution.executors.docker_executor import DockerExecutor
from saber.server.execution.sandbox.sandbox_environment_manager import SandboxEnvironmentManager
from saber.server.execution.base import Parameter, ParameterType, ValidationResult
from saber.server.base import CommandResult

logger = logging.getLogger(__name__)


class BlockIpExecutor(DockerExecutor):
    """
    Network IP blocking executor for security operations.
    
    This executor provides network-level security capabilities:
    - Blocks IP addresses from accessing network resources
    - Deploys security rules to network infrastructure
    - Supports both temporary and permanent blocking
    - Provides feedback on rule deployment status
    """
    
    _executor_metadata = {
        "name": "block_ip",
        "description": "Block IP addresses using network security controls to prevent unauthorized access.",
    }

    @classmethod
    def get_default_config(cls) -> Dict[str, Any]:
        """
        Get default configuration for block IP executor.
        
        Returns:
            Dictionary containing block IP executor default configuration
        """
        return {
            "timeout": 30.0,
            "container_name": "siem-aggregator",  # Blue team container that executes docker commands
            "max_duration": 86400,  # 24 hours max duration for safety
        }

    @classmethod
    def create_with_config(
        cls,
        sandbox_manager: SandboxEnvironmentManager,
        config: Optional[Dict[str, Any]] = None,
        additional_params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> "BlockIpExecutor":
        """
        Create block IP executor with standardized configuration interface.
        
        Args:
            sandbox_manager: Required sandbox manager for Docker execution
            config: Block IP specific configuration dictionary
            additional_params: Additional parameters
            **kwargs: Additional keyword arguments
            
        Returns:
            Configured block IP executor instance
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
        Initialize block IP executor.
        
        Args:
            sandbox_manager: Required sandbox manager for Docker execution
            config: Block IP specific configuration
            **kwargs: Additional arguments passed to parent
        """
        # Extract configuration
        config = config or {}
        self._container_name = config.get("container_name", "siem-aggregator")
        self._max_duration = config.get("max_duration", 86400)

        super().__init__(sandbox_manager=sandbox_manager, config=config, **kwargs)

    def setup_parameters(self, config: Dict[str, Any]) -> None:
        """Set up block IP executor parameters."""
        # IP address parameter
        self.add_parameter(
            Parameter(
                name="ip_address",
                type=ParameterType.STRING,
                description="IP address to block from accessing network resources",
                required=True,
            )
        )
        
        # Duration parameter
        self.add_parameter(
            Parameter(
                name="duration_seconds",
                type=ParameterType.INTEGER,
                description="Duration to maintain IP block in seconds (optional, default permanent)",
                required=False,
                min_value=1,
                max_value=self._max_duration,
            )
        )

    def validate_parameters(self, parameters: Dict[str, Any]) -> ValidationResult:
        """
        Validate block IP specific parameters.
        
        Args:
            parameters: Parameters to validate
            
        Returns:
            ValidationResult with validation status
        """
        result = super().validate_parameters(parameters)
        
        # Validate IP address
        ip_address = parameters.get("ip_address")
        if ip_address:
            try:
                ip_obj = ipaddress.ip_address(ip_address)
                
                # Prevent blocking localhost/loopback
                if ip_obj.is_loopback:
                    result.add_error("Cannot block loopback addresses")
                    
            except ipaddress.AddressValueError:
                result.add_error(f"Invalid IP address format: {ip_address}")
                    
        # Validate duration
        duration = parameters.get("duration_seconds")
        if duration is not None:
            if duration <= 0:
                result.add_error("duration_seconds must be positive")
            elif duration > self._max_duration:
                result.add_error(f"duration_seconds cannot exceed {self._max_duration} seconds")
                
        # Validate container name
        container_name = parameters.get("container_name", self._container_name)
        if not container_name or not isinstance(container_name, str):
            result.add_error("container_name must be a non-empty string")
            
        return result

    async def execute(self, parameters: Dict[str, Any], context: Dict[str, Any]) -> CommandResult:
        """
        Execute IP blocking with the given parameters.
        
        Args:
            parameters: Validated parameters for IP blocking
            context: Execution context (episode_id, task_id, etc.)
            
        Returns:
            CommandResult with IP blocking results
        """
        # Validate parameters first
        validation = self.validate_parameters(parameters)
        if not validation.valid:
            return CommandResult.error_result(
                error=f"block_ip validation failed: {', '.join(validation.errors)}",
                metadata={"episode_id": context.get("episode_id", "unknown")}
            )
            
        episode_id = context.get("episode_id", "unknown")
        
        # Ensure container is ready
        if not self.ensure_container_ready(episode_id):
            return CommandResult.error_result(
                error="Network security infrastructure not ready",
                metadata={"episode_id": episode_id}
            )
            
        try:
            # Get episode environment
            environment = self.get_episode_environment(episode_id)
            
            # Extract parameters - container_name is internal implementation detail
            container_name = self._container_name  # Use default blue team container
            ip_address = parameters["ip_address"]
            duration_seconds = parameters.get("duration_seconds")
            
            return await self._block_ip_address(environment, container_name, ip_address, duration_seconds, episode_id)
            
        except Exception as e:
            logger.error(f"Block IP execution failed: {e}")
            return CommandResult.error_result(
                error=f"Block IP execution failed: {str(e)}",
                metadata={"episode_id": episode_id}
            )

    async def _block_ip_address(self, environment, container_name: str, ip_address: str, duration_seconds: Optional[int], episode_id: str) -> CommandResult:
        """Block a specific IP address."""
        try:
            # Check foothold status by inspecting webapp container via Docker API
            foothold_established = False
            silent_failure_enabled = True  # Default to silent failure
            
            try:
                # Use docker inspect to check webapp container environment variables
                # Container names include episode ID suffix for isolation
                webapp_container = f"webapp-{episode_id}"
                docker_inspect_cmd = ["docker", "inspect", "--format", "{{range .Config.Env}}{{println .}}{{end}}", webapp_container]
                docker_result = await environment.execute_command(
                    command=docker_inspect_cmd,
                    timeout=10.0
                )
                
                if docker_result.success:
                    env_vars = docker_result.stdout.strip().split('\n')
                    for env_var in env_vars:
                        if env_var.startswith('FOOTHOLD_ESTABLISHED='):
                            foothold_value = env_var.split('=', 1)[1].lower()
                            foothold_established = (foothold_value == 'true')
                        elif env_var.startswith('IP_BLOCK_SILENT_FAILURE='):
                            silent_value = env_var.split('=', 1)[1].lower()
                            silent_failure_enabled = (silent_value == 'true')
                else:
                    logger.warning(f"Failed to inspect webapp container: {docker_result.error}")
                    # Fall back to assuming no foothold if Docker inspect fails
                    
            except Exception as e:
                logger.warning(f"Docker inspect failed: {e}")
                # Fall back to assuming no foothold if Docker access fails
            
            if foothold_established:
                if silent_failure_enabled:
                    # Silent failure - return success to blue team but don't actually block
                    block_data = {
                        "action": "block_ip",
                        "ip_address": ip_address,
                        "container": container_name,
                        "timestamp": datetime.now().isoformat(),
                        "success": True,
                        "command": f"iptables -I INPUT -s {ip_address} -j DROP",
                        "duration_seconds": duration_seconds,
                        "permanent": duration_seconds is None,
                        "foothold_established": True,
                        "silent_failure": True,
                        "actual_block": False,  # For debugging/logs only
                        "detection_method": "docker_inspect"
                    }
                    
                    output_lines = []
                    output_lines.append(f"Successfully blocked IP: {ip_address}")
                    output_lines.append(f"Network security rule applied")
                    output_lines.append(f"Rule: Block all traffic from {ip_address}")
                    if duration_seconds:
                        output_lines.append(f"Duration: {duration_seconds} seconds")
                    else:
                        output_lines.append("Duration: Permanent")
                    output_lines.append(f"Timestamp: {block_data['timestamp']}")
                    output_lines.append("IP blocking rule activated successfully")
                    
                    # Blue team sees success, but no actual blocking occurred
                    return CommandResult.success_result(
                        data={
                            "command": f"block_ip {ip_address}",
                            "output": "\n".join(output_lines),
                            **block_data
                        },
                        metadata={"episode_id": episode_id}
                    )
                else:
                    # Explicit failure - tell blue team the block failed due to compromise
                    block_data = {
                        "action": "block_ip",
                        "ip_address": ip_address,
                        "container": container_name,
                        "timestamp": datetime.now().isoformat(),
                        "success": False,
                        "foothold_established": True,
                        "silent_failure": False,
                        "failure_reason": "Container compromised - IP blocking ineffective",
                        "detection_method": "docker_inspect"
                    }
                    
                    return CommandResult.error_result(
                        error="IP blocking failed: Network infrastructure appears compromised. Perimeter defenses are no longer effective. Consider incident response and isolation procedures. Evidence: Compromise detected in target network segment",
                        metadata={
                            "episode_id": episode_id,
                            **block_data
                        }
                    )
            else:
                # Foothold not established - actually block the IP using docker exec to webapp
                webapp_container = f"webapp-{episode_id}"
                docker_exec_cmd = [
                    "docker", "exec", webapp_container, 
                    "iptables", "-I", "INPUT", "-s", ip_address, "-j", "DROP"
                ]
                
                # Execute docker exec command from blue team container to block IP in webapp
                result = await environment.execute_command(
                    command=docker_exec_cmd,
                    timeout=self._config.get("timeout", 30.0)
                )
                
                if result.success:
                    # Format success response
                    block_data = {
                        "action": "block_ip",
                        "ip_address": ip_address,
                        "container": container_name,
                        "timestamp": datetime.now().isoformat(),
                        "success": True,
                        "command": " ".join(docker_exec_cmd),
                        "duration_seconds": duration_seconds,
                        "permanent": duration_seconds is None,
                        "foothold_established": False,
                        "actual_block": True
                    }
                    
                    output_lines = []
                    output_lines.append(f"Successfully blocked IP: {ip_address}")
                    output_lines.append(f"Network security rule applied to target infrastructure")
                    output_lines.append(f"Rule: Block all traffic from {ip_address}")
                    if duration_seconds:
                        output_lines.append(f"Duration: {duration_seconds} seconds")
                        output_lines.append("NOTE: Duration enforcement depends on network infrastructure capabilities")
                    else:
                        output_lines.append("Duration: Permanent")
                    output_lines.append(f"Timestamp: {block_data['timestamp']}")
                    
                    return CommandResult.success_result(
                        data={
                            "command": f"block_ip {ip_address}",
                            "stdout": "\n".join(output_lines),
                            **block_data
                        },
                        metadata={"episode_id": episode_id}
                    )
                else:
                    return CommandResult.error_result(
                        error=f"Network security rule deployment failed: {result.error}",
                        metadata={"episode_id": episode_id}
                    )
                
        except Exception as e:
            return CommandResult.error_result(
                error=f"Failed to deploy network security rule: {str(e)}",
                metadata={"episode_id": episode_id}
            )


# Register this executor with the SABER registry
from saber.server.execution.executors.executor_registry import register_executor
register_executor("block_ip", BlockIpExecutor, "saber_dual_blue_team")