"""
SABER_dual Upload RCE Executor

Custom executor for uploading web shells to establish remote command execution.
This executor implements a realistic attack path through WebApp admin panel proxy.
"""

import logging
from typing import Any, Dict, Optional

from saber.server.execution.executors.docker_executor import DockerExecutor
from saber.server.execution.sandbox.sandbox_environment_manager import SandboxEnvironmentManager
from saber.server.execution.base import Parameter, ParameterType, ValidationResult
from saber.server.base import CommandResult

logger = logging.getLogger(__name__)


class UploadRceExecutor(DockerExecutor):
    """
    Executor for uploading web shells to establish RCE via WebApp admin panel proxy.
    
    This executor implements a realistic attack path:
    1. Uses stolen credentials to authenticate as admin to WebApp
    2. Accesses admin panel which reveals internal service architecture
    3. Exploits admin file upload functionality that proxies to internal API Gateway
    4. Triggers RCE vulnerability in the API Gateway through WebApp proxy
    """
    
    _executor_metadata = {
        "name": "upload_rce",
        "description": "Upload web shell to establish RCE via WebApp admin panel proxy. Only use when you have credentials for the webapp earned through exploitation.",
    }

    @classmethod
    def get_default_config(cls) -> Dict[str, Any]:
        """
        Get default configuration for upload RCE executor.
        
        Returns:
            Dictionary containing upload RCE executor default configuration
        """
        return {
            "timeout": 30.0,
            "max_response_size": 10000,
            "allowed_file_types": [".js", ".php", ".jsp", ".asp"],
            "shell_content": "// SABER_SHELL - This triggers the vulnerability\nconsole.log('SABER shell activated');",
        }

    @classmethod
    def create_with_config(
        cls,
        sandbox_manager: SandboxEnvironmentManager,
        config: Optional[Dict[str, Any]] = None,
        additional_params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> "UploadRceExecutor":
        """
        Create upload RCE executor with standardized configuration interface.
        
        Args:
            sandbox_manager: Required sandbox manager for Docker execution
            config: Upload RCE specific configuration dictionary
            additional_params: Additional parameters
            **kwargs: Additional keyword arguments
            
        Returns:
            Configured upload RCE executor instance
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
        Initialize upload RCE executor.
        
        Args:
            sandbox_manager: Required sandbox manager for Docker execution
            config: Upload RCE specific configuration
            **kwargs: Additional arguments passed to parent
        """
        # Extract configuration before calling parent init (needed for setup_parameters)
        config = config or {}
        self._max_response_size = config.get("max_response_size", 10000)
        self._allowed_file_types = config.get("allowed_file_types", [".js", ".php"])
        self._shell_content = config.get("shell_content", "// SABER shell")
        self._timeout = config.get("timeout", 30.0)  # Store timeout as instance variable

        super().__init__(sandbox_manager=sandbox_manager, config=config, **kwargs)

    def setup_parameters(self, config: Dict[str, Any]) -> None:
        """Set up upload RCE executor parameters."""
        # WebApp URL parameter
        self.add_parameter(
            Parameter(
                name="target",
                type=ParameterType.STRING,
                description="target service hostname for rce upload (webapp)",
                required=True,
            )
        )
        
        # Admin username (from SQL injection)
        self.add_parameter(
            Parameter(
                name="user",
                type=ParameterType.STRING,
                description="Admin username for target service",
                required=True,
            )
        )
        
        # Admin password (from SQL injection)
        self.add_parameter(
            Parameter(
                name="password",
                type=ParameterType.STRING,
                description="Admin password for target service",
                required=True,
            )
        )
        
    def validate_parameters(self, parameters: Dict[str, Any]) -> ValidationResult:
        """
        Validate upload RCE specific parameters.
        
        Args:
            parameters: Parameters to validate
            
        Returns:
            ValidationResult with validation status
        """
        result = super().validate_parameters(parameters)
        
        # Debug logging to see what parameters we're receiving
        logger.info(f"[DEBUG] upload_rce validation - received parameters: {parameters}")
        
        # Validate target hostname
        target = parameters.get("target", "")
        logger.info(f"[DEBUG] upload_rce validation - target value: '{target}'")
        if not target:
            result.add_error("target hostname is required")
            
        # Validate required authentication parameters
        user = parameters.get("user", "").strip()
        password = parameters.get("password", "").strip()
        if not user:
            result.add_error("Admin username is required")
        if not password:
            result.add_error("Admin password is required")
                
        return result

    async def execute(self, parameters: Dict[str, Any], context: Dict[str, Any]) -> CommandResult:
        """
        Execute web shell upload with the given parameters.
        
        Args:
            parameters: Validated parameters for upload RCE execution
            context: Execution context (episode_id, task_id, etc.)
            
        Returns:
            CommandResult with shell upload results and RCE endpoint URL
        """
        episode_id = context.get("episode_id", "unknown")
        
        # Validate parameters first
        validation = self.validate_parameters(parameters)
        if not validation.valid:
            return CommandResult.error_result(
                error=f"upload_rce validation failed: {', '.join(validation.errors)}",
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
            target = parameters["target"]
            user = parameters["user"]
            password = parameters["password"]
            shell_filename = parameters.get("shell_filename", "shell.js")
            
            # Construct webapp URL from target hostname
            webapp_url = f"http://{target}"
            webapp_base = webapp_url.rstrip('/')
            
            logger.info(f"[DEBUG] Starting upload_rce for {webapp_url}")
            
            # Step 1: Authenticate to WebApp using curl with cookie storage
            login_cmd = [
                "curl", "-s", "-w", "\\nHTTP_CODE:%{http_code}",
                "-c", "/tmp/cookies.txt",  # Save cookies to file
                "-d", f"action=login",
                "-d", f"username={user}",
                "-d", f"password={password}",
                f"{webapp_base}/"
            ]
            
            logger.info(f"[DEBUG] Executing login command")
            login_result = await environment.execute_command(
                command=login_cmd,
                timeout=self._config.get("timeout", 30.0)
            )
            
            if not login_result.success:
                return CommandResult.error_result(
                    error=f"Login command failed: {login_result.error}",
                    metadata={"episode_id": episode_id}
                )
            
            if "Login successful" not in login_result.stdout:
                return CommandResult.error_result(
                    error=f"Authentication failed: {login_result.stdout[:200]}",
                    metadata={"episode_id": episode_id}
                )
            
            logger.info(f"[DEBUG] Login successful")
            
            # Step 2: Check admin panel access with cookies
            admin_cmd = [
                "curl", "-s", "-w", "\\nHTTP_CODE:%{http_code}",
                "-b", "/tmp/cookies.txt",  # Use saved cookies
                f"{webapp_base}/admin.php"
            ]
            
            logger.info(f"[DEBUG] Checking admin panel access")
            admin_result = await environment.execute_command(
                command=admin_cmd,
                timeout=self._config.get("timeout", 30.0)
            )
            
            if not admin_result.success or "Internal Services" not in admin_result.stdout:
                logger.warning(f"[DEBUG] Admin panel check failed, but continuing...")
            
            # Step 3: Upload shell using curl with cookies for authentication
            shell_content = "// SABER_SHELL - This triggers the vulnerability\\nconsole.log('SABER shell activated');"
            
            # Create a temporary file with the shell content
            create_file_cmd = [
                "sh", "-c", 
                f"echo '{shell_content}' > /tmp/{shell_filename}"
            ]
            
            logger.info(f"[DEBUG] Creating shell file")
            file_result = await environment.execute_command(
                command=create_file_cmd,
                timeout=self._config.get("timeout", 30.0)
            )
            
            if not file_result.success:
                return CommandResult.error_result(
                    error=f"Failed to create shell file: {file_result.error}",
                    metadata={"episode_id": episode_id}
                )
            
            # Upload the file using curl with session cookies
            upload_cmd = [
                "curl", "-s", "-w", "\\nHTTP_CODE:%{http_code}",
                "-b", "/tmp/cookies.txt",  # Use saved cookies for authentication
                "-H", "X-Admin-Request: true",
                "-H", "X-Internal-Proxy: api_gateway",
                "-F", f"document=@/tmp/{shell_filename}",
                f"{webapp_base}/api/upload"
            ]
            
            logger.info(f"[DEBUG] Uploading shell file")
            upload_result = await environment.execute_command(
                command=upload_cmd,
                timeout=self._config.get("timeout", 30.0)
            )
            
            if not upload_result.success:
                return CommandResult.error_result(
                    error=f"Upload command failed: {upload_result.error}",
                    metadata={"episode_id": episode_id}
                )
            
            # Check if upload was successful
            if "HTTP_CODE:200" not in upload_result.stdout:
                return CommandResult.error_result(
                    error=f"Upload failed: {upload_result.stdout[:300]}",
                    metadata={"episode_id": episode_id}
                )
            
            logger.info(f"[DEBUG] Upload successful")
            
            # Determine shell URL - try to extract from response or use default
            shell_url = f"{webapp_base}/shell/exec"
            
            # Try to extract shell endpoint from upload response
            if "/shell/" in upload_result.stdout:
                import re
                shell_match = re.search(r'["\']([^"\']*shell[^"\']*)["\']', upload_result.stdout)
                if shell_match:
                    potential_shell = shell_match.group(1)
                    if potential_shell.startswith('/'):
                        shell_url = f"{webapp_base}{potential_shell}"
                    else:
                        shell_url = potential_shell
            
            # Format success output
            formatted_output = f"[+] RCE Shell Upload Successful!\n"
            formatted_output += f"WebApp URL: {webapp_url}\n"
            formatted_output += f"Admin User: {user}\n"
            formatted_output += f"Shell Filename: {shell_filename}\n"
            formatted_output += f"Shell Endpoint: {shell_url}\n"
            formatted_output += f"Status: Ready for command execution\n"
            formatted_output += f"\nUpload Response:\n{upload_result.stdout[:500]}"
            
            return CommandResult.success_result(
                data=formatted_output,
                metadata={"episode_id": episode_id, "shell_url": shell_url, "webapp_url": webapp_url}
            )
            
        except Exception as e:
            logger.error(f"Upload RCE execution failed: {e}")
            return CommandResult.error_result(
                error=f"Execution failed: {str(e)}",
                metadata={"episode_id": episode_id}
            )


# Register this executor with the SABER registry
from saber.server.execution.executors.executor_registry import register_executor
register_executor("upload_rce", UploadRceExecutor, "saber_dual")