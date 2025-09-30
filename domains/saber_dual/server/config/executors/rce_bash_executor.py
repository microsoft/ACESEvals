"""
SABER_dual RCE Bash Executor

Custom executor for executing bash commands via simulated web shell.
This executor provides remote command execution simulation through the sandbox environment.
"""

import logging
from typing import Any, Dict, Optional

from saber.server.execution.executors.docker_executor import DockerExecutor
from saber.server.execution.sandbox.sandbox_environment_manager import SandboxEnvironmentManager
from saber.server.execution.base import Parameter, ParameterType, ValidationResult
from saber.server.base import CommandResult

logger = logging.getLogger(__name__)


class RceBashExecutor(DockerExecutor):
    """
    Executor for executing bash commands via web shell through WebApp proxy.
    
    This executor provides remote command execution capabilities by sending
    commands to an uploaded web shell endpoint and parsing the results.
    """
    
    _executor_metadata = {
        "name": "rce_bash",
        "description": "Execute bash commands via web shell RCE endpoint.",
    }

    @classmethod
    def get_default_config(cls) -> Dict[str, Any]:
        """
        Get default configuration for RCE bash executor.
        
        Returns:
            Dictionary containing RCE bash executor default configuration
        """
        return {
            "timeout": 30.0,
            "max_response_size": 20000,
            "max_command_length": 1000,
            "allowed_commands": [
                "whoami", "id", "pwd", "ls", "cat", "echo", "ps", "netstat", 
                "ifconfig", "ip", "find", "grep", "curl", "wget", "ping"
            ],
            "blocked_commands": [
                "rm -rf", "mkfs", "dd if=", "format", "del /f", "shutdown", "reboot"
            ],
        }

    @classmethod
    def create_with_config(
        cls,
        sandbox_manager: SandboxEnvironmentManager,
        config: Optional[Dict[str, Any]] = None,
        additional_params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> "RceBashExecutor":
        """
        Create RCE bash executor with standardized configuration interface.
        
        Args:
            sandbox_manager: Required sandbox manager for Docker execution
            config: RCE bash specific configuration dictionary
            additional_params: Additional parameters
            **kwargs: Additional keyword arguments
            
        Returns:
            Configured RCE bash executor instance
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
        Initialize RCE bash executor.
        
        Args:
            sandbox_manager: Required sandbox manager for Docker execution
            config: RCE bash specific configuration
            **kwargs: Additional arguments passed to parent
        """
        # Extract configuration
        config = config or {}
        self._max_response_size = config.get("max_response_size", 20000)
        self._max_command_length = config.get("max_command_length", 1000)
        self._allowed_commands = config.get("allowed_commands", [])
        self._blocked_commands = config.get("blocked_commands", ["rm -rf"])

        super().__init__(sandbox_manager=sandbox_manager, config=config, **kwargs)

    def setup_parameters(self, config: Dict[str, Any]) -> None:
        """Set up RCE bash executor parameters."""
        # RCE URL parameter
        self.add_parameter(
            Parameter(
                name="rce_url",
                type=ParameterType.STRING,
                description="URL of uploaded web shell endpoint",
                required=True,
            )
        )
        
        # Command to execute
        self.add_parameter(
            Parameter(
                name="command",
                type=ParameterType.STRING,
                description="Bash command to execute remotely",
                required=True,
            )
        )
        
        # Optional working directory
        self.add_parameter(
            Parameter(
                name="workdir",
                type=ParameterType.STRING,
                description="Working directory for command execution",
                required=False,
            )
        )

    def validate_parameters(self, parameters: Dict[str, Any]) -> ValidationResult:
        """
        Validate RCE bash specific parameters.
        
        Args:
            parameters: Parameters to validate
            
        Returns:
            ValidationResult with validation status
        """
        result = super().validate_parameters(parameters)
        
        # Validate rce_url
        rce_url = parameters.get("rce_url", "")
        if rce_url and not (rce_url.startswith("http://") or rce_url.startswith("https://")):
            result.add_error("rce_url must be a valid HTTP/HTTPS URL")
            
        # Validate command
        command = parameters.get("command", "").strip()
        if not command:
            result.add_error("Command cannot be empty")
        elif len(command) > self._max_command_length:
            result.add_error(f"Command too long (max {self._max_command_length} characters)")
        
        # Check for blocked commands
        command_lower = command.lower()
        for blocked in self._blocked_commands:
            if blocked.lower() in command_lower:
                result.add_error(f"Command contains blocked pattern: {blocked}")
        
        # Optional: Check allowed commands if configured strictly
        if self._allowed_commands and not any(allowed in command_lower for allowed in self._allowed_commands):
            # Only warn, don't block (for educational flexibility)
            result.add_warning(f"Command not in typical allowed list: {self._allowed_commands}")
                
        return result

    async def execute(self, parameters: Dict[str, Any], context: Dict[str, Any]) -> CommandResult:
        """
        Execute bash command via RCE web shell endpoint (NOT directly in sandbox).
        
        This executor sends a command through the established RCE web shell,
        allowing the compromised webapp container to execute commands in its context.
        
        Args:
            parameters: Validated parameters for RCE bash execution
            context: Execution context (episode_id, task_id, etc.)
            
        Returns:
            CommandResult with command execution results from the compromised container
        """
        episode_id = context.get("episode_id", "unknown")
        
        # Validate parameters first
        validation = self.validate_parameters(parameters)
        if not validation.valid:
            return CommandResult.error_result(
                error=f"rce_bash validation failed: {', '.join(validation.errors)}",
                metadata={"episode_id": episode_id}
            )
            
        # Ensure container is ready
        if not self.ensure_container_ready(episode_id):
            return CommandResult.error_result(
                error="Container not ready for execution",
                metadata={"episode_id": episode_id}
            )
            
        try:
            # Get episode environment
            environment = self.get_episode_environment(episode_id)
            
            # Extract parameters
            rce_url = parameters["rce_url"]  # Web shell endpoint URL
            command = parameters["command"]
            workdir = parameters.get("workdir")
            
            # Build final command with working directory if specified
            final_command = command
            if workdir:
                final_command = f"cd {workdir} && {command}"
            
            logger.info(f"Sending command via RCE web shell: {final_command}")
            
            # Execute command via RCE web shell endpoint (like tools.py does)
            import urllib.parse
            encoded_cmd = urllib.parse.quote(final_command)
            shell_request_url = f"{rce_url}?cmd={encoded_cmd}"
            
            # Use curl to make the request to the web shell endpoint
            http_cmd = [
                "curl", "-s", "-w", "\\nHTTP_CODE:%{http_code}",
                "--max-time", "30",
                shell_request_url
            ]
            
            # Execute HTTP request to RCE endpoint in sandbox
            result = await environment.execute_command(
                command=http_cmd,
                timeout=self._config.get("timeout", 30.0)
            )
            
            if result.success:
                output = result.stdout
                
                # Parse response for HTTP code
                http_code = "Unknown"
                response_body = output
                
                if "HTTP_CODE:" in output:
                    parts = output.rsplit("HTTP_CODE:", 1)
                    if len(parts) == 2:
                        response_body = parts[0]
                        http_code = parts[1].strip()
                
                # Try to parse JSON response from web shell
                command_stdout = ""
                command_stderr = ""
                command_exit_code = 0
                
                try:
                    import json
                    shell_response = json.loads(response_body)
                    command_stdout = shell_response.get("stdout", "")
                    command_stderr = shell_response.get("stderr", "")
                    command_exit_code = shell_response.get("exit_code", 0)
                    
                except json.JSONDecodeError:
                    # If not JSON, treat raw response as stdout
                    command_stdout = response_body
                
                # Limit response size for security
                if len(command_stdout) > self._max_response_size:
                    command_stdout = command_stdout[:self._max_response_size] + "\\n...(truncated for security)"
                
                # Format output to match expected RCE response format
                formatted_output = f"[+] RCE Command Execution Results:\\n"
                formatted_output += f"Command: {command}\\n"
                formatted_output += f"Exit Code: {command_exit_code}\\n"
                formatted_output += f"RCE URL: {rce_url}\\n"
                formatted_output += f"\\n--- STDOUT ---\\n{command_stdout}\\n"
                
                if command_stderr:
                    formatted_output += f"\\n--- STDERR ---\\n{command_stderr}\\n"
                
                return CommandResult.success_result(
                    data=formatted_output,
                    metadata={
                        "episode_id": episode_id,
                        "stdout": command_stdout,
                        "stderr": command_stderr,
                        "exit_code": command_exit_code,
                        "rce_url": rce_url,
                        "command": command,
                        "shell_http_code": http_code,
                        "web_shell_response": response_body
                    }
                )
            else:
                return CommandResult.error_result(
                    error=f"RCE web shell request failed with exit code {result.exit_code}: {result.stderr}",
                    metadata={
                        "episode_id": episode_id,
                        "rce_url": rce_url,
                        "command": command,
                        "exit_code": result.exit_code,
                        "stderr": result.stderr
                    }
                )
                
        except Exception as e:
            logger.error(f"RCE bash execution failed: {e}")
            return CommandResult.error_result(
                error=f"RCE bash execution failed: {str(e)}",
                metadata={"episode_id": episode_id}
            )


# Register this executor with the SABER registry
from saber.server.execution.executors.executor_registry import register_executor
register_executor("rce_bash", RceBashExecutor, "saber_dual")