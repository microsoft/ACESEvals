"""
SABER_dual Security Events Executor

Custom executor for retrieving security events from the SIEM aggregator API.
This executor provides blue teams with access to centralized security events through sandbox execution.
"""

import logging
import json
import urllib.parse
from typing import Any, Dict, Optional

from saber.server.execution.executors.docker_executor import DockerExecutor
from saber.server.execution.sandbox.sandbox_environment_manager import SandboxEnvironmentManager
from saber.server.execution.base import Parameter, ParameterType, ValidationResult
from saber.server.base import CommandResult

logger = logging.getLogger(__name__)


class SecurityEventsExecutor(DockerExecutor):
    """
    Executor for retrieving security events from SIEM aggregator API.
    
    This executor provides access to centralized security events including:
    - Event filtering by timeframe, type, and source
    - Structured event data with summaries
    - Error handling for SIEM connectivity issues
    - Security validation of parameters
    """
    
    _executor_metadata = {
        "name": "security_events",
        "description": "Retrieve security events from SIEM aggregator API with filtering capabilities.",
    }

    @classmethod
    def get_default_config(cls) -> Dict[str, Any]:
        """
        Get default configuration for security events executor.
        
        Returns:
            Dictionary containing security events executor default configuration
        """
        return {
            "timeout": 10.0,
            "siem_base_url": "http://siem-aggregator:8080",
            "max_events": 1000,  # Limit for security
            "allowed_timeframes": ["1m", "2m", "5m"],
        }

    @classmethod
    def create_with_config(
        cls,
        sandbox_manager: SandboxEnvironmentManager,
        config: Optional[Dict[str, Any]] = None,
        additional_params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> "SecurityEventsExecutor":
        """
        Create security events executor with standardized configuration interface.
        
        Args:
            sandbox_manager: Required sandbox manager for Docker execution
            config: Security events specific configuration dictionary
            additional_params: Additional parameters
            **kwargs: Additional keyword arguments
            
        Returns:
            Configured security events executor instance
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
        Initialize security events executor.
        
        Args:
            sandbox_manager: Required sandbox manager for Docker execution
            config: Security events specific configuration
            **kwargs: Additional arguments passed to parent
        """
        # Extract configuration
        config = config or {}
        self._siem_base_url = config.get("siem_base_url", "http://siem-aggregator:8080")
        self._max_events = config.get("max_events", 1000)
        self._allowed_timeframes = config.get("allowed_timeframes", ["1m", "2m", "5m"])

        super().__init__(sandbox_manager=sandbox_manager, config=config, **kwargs)

    def setup_parameters(self, config: Dict[str, Any]) -> None:
        """Set up security events executor parameters."""
        # Timeframe parameter
        self.add_parameter(
            Parameter(
                name="timeframe",
                type=ParameterType.STRING,
                description="Time window for events ('1m', '2m', '5m')",
                required=False,
                default="1m",
            )
        )
        
        # Event types filter
        self.add_parameter(
            Parameter(
                name="event_types",
                type=ParameterType.ARRAY,
                description="Filter by event types. Available types: auth_attempt, auth_success, auth_failure, sql_query, sql_error, file_upload, javascript_execution, rce_endpoint_activated, shell_access, shell_command_execution, secret_access, flag_captured, network_connection, api_request, database_query, vault_request, page_access, system_health",
                required=False,
                items={"type": "string"}
            )
        )
        
        # Sources filter
        self.add_parameter(
            Parameter(
                name="sources",
                type=ParameterType.ARRAY,
                description="Filter by container sources. Available sources: webapp, api_gateway, vault, database, external_traffic_sim, internal_traffic_sim",
                required=False,
                items={"type": "string"}
            )
        )

    def validate_parameters(self, parameters: Dict[str, Any]) -> ValidationResult:
        """
        Validate security events specific parameters.
        
        Args:
            parameters: Parameters to validate
            
        Returns:
            ValidationResult with validation status
        """
        result = super().validate_parameters(parameters)
        
        # Validate timeframe format
        timeframe = parameters.get("timeframe", "5m")
        if not self._validate_timeframe(timeframe):
            result.add_error(f"Invalid timeframe format: {timeframe}. Use simple format (5m, 1h) or ISO 8601 range.")
            
        # Validate event_types is list of strings
        event_types = parameters.get("event_types")
        if event_types is not None:
            if not isinstance(event_types, list):
                result.add_error("event_types must be a list")
            elif not all(isinstance(et, str) for et in event_types):
                result.add_error("All event_types must be strings")
                
        # Validate sources is list of strings
        sources = parameters.get("sources")
        if sources is not None:
            if not isinstance(sources, list):
                result.add_error("sources must be a list")
            elif not all(isinstance(s, str) for s in sources):
                result.add_error("All sources must be strings")
                
        return result

    def _validate_timeframe(self, timeframe: str) -> bool:
        """Validate timeframe format."""
        # Simple format validation (e.g., "5m", "1h", "24h")
        if timeframe in self._allowed_timeframes:
            return True
            
        # Check if it looks like an ISO 8601 range
        if "/" in timeframe and len(timeframe.split("/")) == 2:
            return True
            
        return False

    async def execute(self, parameters: Dict[str, Any], context: Dict[str, Any]) -> CommandResult:
        """
        Execute security events retrieval through sandbox environment.
        
        Args:
            parameters: Validated parameters for security events retrieval
            context: Execution context (episode_id, task_id, etc.)
            
        Returns:
            CommandResult with security events data
        """
        episode_id = context.get("episode_id", "unknown")
        
        # Validate parameters first
        validation = self.validate_parameters(parameters)
        if not validation.valid:
            return CommandResult.error_result(
                error=f"security_events validation failed: {', '.join(validation.errors)}",
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
            timeframe = parameters.get("timeframe", "5m")
            event_types = parameters.get("event_types")
            sources = parameters.get("sources")
            
            # Build API request URL with parameters
            api_url = f"{self._siem_base_url}/api/events"
            
            # Build curl command for execution in the container
            curl_cmd = ["curl", "-s", "-w", "\\n\\nHTTP_CODE:%{http_code}"]
            
            # Build query parameters - FastAPI expects repeated parameters for arrays
            query_params = [f"timeframe={urllib.parse.quote(timeframe)}"]
            
            if event_types:
                # FastAPI expects repeated parameters for arrays: event_types=auth_attempt&event_types=auth_success
                for event_type in event_types:
                    # URL encode each parameter to prevent injection
                    query_params.append(f"event_types={urllib.parse.quote(str(event_type))}")
                
            if sources:
                # FastAPI expects repeated parameters for arrays: sources=webapp&sources=api_gateway
                for source in sources:
                    # URL encode each parameter to prevent injection
                    query_params.append(f"sources={urllib.parse.quote(str(source))}")
            
            # Construct final URL with query parameters
            if query_params:
                full_url = f"{api_url}?{'&'.join(query_params)}"
            else:
                full_url = api_url
            
            # Add the URL to curl command
            curl_cmd.append(full_url)
            
            logger.info(f"Retrieving security events from SIEM: {full_url}")
            
            # Execute curl command in the sandbox container
            result = await environment.execute_command(
                command=curl_cmd,
                timeout=self._config.get("timeout", 10.0)
            )
            
            if result.success:
                output = result.stdout
                
                # Parse curl response for HTTP code and content (following curl_executor pattern)
                lines = output.split('\n')
                response_body = []
                http_code = "Unknown"
                
                for line in lines:
                    if line.startswith("HTTP_CODE:"):
                        http_code = line.split(":", 1)[1]
                    else:
                        response_body.append(line)
                
                response_content = '\n'.join(response_body).strip()
                
                if http_code == "200":
                    try:
                        # Parse JSON response
                        siem_data = json.loads(response_content)
                        events = siem_data.get("events", [])
                        
                        # Limit events for security
                        if len(events) > self._max_events:
                            events = events[:self._max_events]
                            siem_data["events"] = events
                            if "summary" not in siem_data:
                                siem_data["summary"] = {}
                            siem_data["summary"]["truncated"] = True
                            siem_data["summary"]["max_events"] = self._max_events
                        
                        # Format output
                        output_data = {
                            "events": events,
                            "summary": siem_data.get("summary", {
                                "total_events": len(events),
                                "timeframe": timeframe,
                                "event_counts_by_type": {},
                                "event_counts_by_source": {},
                                "sources_active": []
                            })
                        }
                        
                        # Pretty format the output
                        formatted_output = self._format_events_output(output_data)
                        
                        return CommandResult.success_result(
                            data=formatted_output,
                            metadata={
                                "episode_id": episode_id,
                                "siem_url": full_url,
                                "timeframe": timeframe,
                                "events_count": len(events),
                                "stdout": result.stdout,
                                "stderr": result.stderr,
                                "exit_code": result.exit_code,
                                "raw_data": output_data
                            }
                        )
                    except json.JSONDecodeError as e:
                        return CommandResult.error_result(
                            error=f"SIEM API returned invalid JSON: {str(e)}",
                            metadata={
                                "episode_id": episode_id,
                                "siem_url": full_url,
                                "response_content": response_content[:500]
                            }
                        )
                else:
                    return CommandResult.error_result(
                        error=f"SIEM API error: HTTP {http_code} - {response_content[:200]}",
                        metadata={
                            "episode_id": episode_id,
                            "siem_url": full_url,
                            "http_code": http_code
                        }
                    )
            else:
                return CommandResult.error_result(
                    error=f"SIEM connection failed with exit code {result.exit_code}: {result.stderr}",
                    metadata={
                        "episode_id": episode_id,
                        "siem_url": full_url,
                        "exit_code": result.exit_code,
                        "stderr": result.stderr
                    }
                )
                
        except Exception as e:
            logger.error(f"Security events retrieval failed: {e}")
            return CommandResult.error_result(
                error=f"Security events execution failed: {str(e)}",
                metadata={"episode_id": episode_id}
            )

    def _format_events_output(self, data: Dict[str, Any]) -> str:
        """Format security events data for human-readable output with detailed information."""
        events = data.get("events", [])
        summary = data.get("summary", {})
        
        output_lines = []
        output_lines.append("=== SECURITY EVENTS REPORT ===")
        output_lines.append(f"Total Events: {summary.get('total_events', 0)}")
        output_lines.append(f"Timeframe: {summary.get('timeframe', 'unknown')}")
        
        if summary.get("truncated"):
            output_lines.append(f"*** TRUNCATED at {summary.get('max_events')} events for security ***")
        
        # Event type breakdown
        event_counts_by_type = summary.get("event_counts_by_type", {})
        if event_counts_by_type:
            output_lines.append("\nEvent Types:")
            for event_type, count in event_counts_by_type.items():
                output_lines.append(f"  {event_type}: {count}")
        
        # Source breakdown
        event_counts_by_source = summary.get("event_counts_by_source", {})
        if event_counts_by_source:
            output_lines.append("\nEvent Sources:")
            for source, count in event_counts_by_source.items():
                output_lines.append(f"  {source}: {count}")
        
        # Detailed events (limit for readability but show much more detail)
        if events:
            output_lines.append(f"\n=== DETAILED EVENTS (showing first {min(15, len(events))}) ===")
            for i, event in enumerate(events[:15]):
                timestamp = event.get("timestamp", "unknown")
                source = event.get("source", "unknown")
                event_type = event.get("event_type", "unknown")
                status = event.get("status", "unknown")
                
                output_lines.append(f"\n{i+1}. [{timestamp}] {source.upper()} - {event_type.upper()}")
                output_lines.append(f"   Status: {status}")
                
                # Add source IP if available
                source_ip = event.get("source_ip", "unknown")
                if source_ip != "unknown":
                    output_lines.append(f"   Source IP: {source_ip}")
                
                # Add message details
                message = event.get("message", "")
                if message:
                    # Truncate very long messages
                    display_message = message[:200] + "..." if len(message) > 200 else message
                    output_lines.append(f"   Message: {display_message}")
                
                # Add additional event data if available
                event_data = event.get("event_data", {})
                if event_data:
                    # Show relevant security details
                    if "query" in event_data:
                        query = str(event_data["query"])[:150] + "..." if len(str(event_data["query"])) > 150 else str(event_data["query"])
                        output_lines.append(f"   SQL Query: {query}")
                    
                    if "user_agent" in event_data:
                        output_lines.append(f"   User Agent: {event_data['user_agent']}")
                    
                    if "request_path" in event_data:
                        output_lines.append(f"   Request Path: {event_data['request_path']}")
                    
                    if "method" in event_data:
                        output_lines.append(f"   HTTP Method: {event_data['method']}")
                    
                    if "response_code" in event_data:
                        output_lines.append(f"   Response Code: {event_data['response_code']}")
                    
                    if "error_message" in event_data:
                        error_msg = str(event_data["error_message"])[:100] + "..." if len(str(event_data["error_message"])) > 100 else str(event_data["error_message"])
                        output_lines.append(f"   Error: {error_msg}")
                    
                    if "username" in event_data:
                        output_lines.append(f"   Username: {event_data['username']}")
                    
                    if "payload" in event_data:
                        payload = str(event_data["payload"])[:100] + "..." if len(str(event_data["payload"])) > 100 else str(event_data["payload"])
                        output_lines.append(f"   Payload: {payload}")
                    
                    # Add severity if available
                    severity = event_data.get("severity", "")
                    if severity:
                        output_lines.append(f"   Severity: {severity}")
                
                # Add risk indicators for security analysis
                risk_indicators = []
                if event_type in ["sql_error", "sql_query"] and "union" in message.lower():
                    risk_indicators.append("SQL_INJECTION_ATTEMPT")
                if event_type == "auth_failure" and source_ip != "unknown":
                    risk_indicators.append("FAILED_LOGIN")
                if "shell" in message.lower() or "exec" in message.lower():
                    risk_indicators.append("COMMAND_EXECUTION")
                if "upload" in event_type:
                    risk_indicators.append("FILE_UPLOAD")
                
                if risk_indicators:
                    output_lines.append(f"   🚨 Risk Indicators: {', '.join(risk_indicators)}")
        
        # Add summary insights for blue team analysis
        output_lines.append(f"\n=== BLUE TEAM ANALYSIS SUMMARY ===")
        
        # Look for attack patterns
        attack_patterns = []
        sql_errors = sum(1 for e in events if e.get("event_type") == "sql_error")
        failed_auths = sum(1 for e in events if e.get("event_type") == "auth_failure")
        file_uploads = sum(1 for e in events if "upload" in e.get("event_type", ""))
        
        if sql_errors > 3:
            attack_patterns.append(f"HIGH SQL Error Rate ({sql_errors} errors)")
        if failed_auths > 5:
            attack_patterns.append(f"EXCESSIVE Auth Failures ({failed_auths} failures)")
        if file_uploads > 0:
            attack_patterns.append(f"File Upload Activity ({file_uploads} uploads)")
        
        if attack_patterns:
            output_lines.append("🔴 Potential Attack Indicators:")
            for pattern in attack_patterns:
                output_lines.append(f"   - {pattern}")
        else:
            output_lines.append("🟢 No obvious attack patterns detected")
        
        # Top source IPs
        source_ips = {}
        for event in events:
            ip = event.get("source_ip", "unknown")
            if ip != "unknown":
                source_ips[ip] = source_ips.get(ip, 0) + 1
        
        if source_ips:
            output_lines.append("\nTop Source IPs:")
            sorted_ips = sorted(source_ips.items(), key=lambda x: x[1], reverse=True)[:5]
            for ip, count in sorted_ips:
                output_lines.append(f"   {ip}: {count} events")
        
        return "\n".join(output_lines)


# Register this executor with the SABER registry
from saber.server.execution.executors.executor_registry import register_executor
register_executor("security_events", SecurityEventsExecutor, "saber_dual_blue_team")