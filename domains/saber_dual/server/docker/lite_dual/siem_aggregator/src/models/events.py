"""
SIEM Event Models

Pydantic models for standardized security events across all container sources.
Implements the event schema defined in the blue team refactor plan.
"""

from datetime import datetime
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from enum import Enum


class EventType(str, Enum):
    """Standardized event types for security analysis"""
    AUTH_ATTEMPT = "auth_attempt"
    AUTH_SUCCESS = "auth_success"
    AUTH_FAILURE = "auth_failure"
    SQL_QUERY = "sql_query"
    FILE_UPLOAD = "file_upload"
    JAVASCRIPT_EXECUTION = "javascript_execution"
    RCE_ENDPOINT_ACTIVATED = "rce_endpoint_activated"
    SHELL_ACCESS = "shell_access"
    SHELL_COMMAND_EXECUTION = "shell_command_execution"
    SECRET_ACCESS = "secret_access"
    FLAG_ACCESSED = "flag_accessed"  # Internal/authorized flag access (not malicious capture)
    NETWORK_CONNECTION = "network_connection"
    API_REQUEST = "api_request"
    DATABASE_QUERY = "database_query"
    VAULT_REQUEST = "vault_request"
    PAGE_ACCESS = "page_access"  # Added for webapp page access logging
    SQL_ERROR = "sql_error"      # Added for webapp SQL error logging
    SYSTEM_HEALTH = "system_health"  # Added for API gateway health checks


class EventSource(str, Enum):
    """Valid event sources visible to blue teams (no traffic simulators)"""
    WEBAPP = "webapp"
    API_GATEWAY = "api_gateway"
    VAULT = "vault"
    DATABASE = "database"


class EventStatus(str, Enum):
    """Event completion status"""
    SUCCESS = "success"
    FAILURE = "failure"
    ERROR = "error"
    IN_PROGRESS = "in_progress"
    UNKNOWN = "unknown"  # Added for unknown/unspecified status


class SecurityEvent(BaseModel):
    """
    Standardized security event model
    
    This is the core data structure that blue teams receive.
    All container logs are normalized to this schema.
    """
    timestamp: datetime = Field(..., description="Event occurrence time in ISO format")
    source: EventSource = Field(..., description="Container source (webapp|api_gateway|vault|database)")
    source_ip: str = Field(..., description="Source IP address")
    event_type: EventType = Field(..., description="Standardized event type")
    event_id: str = Field(..., description="Unique event identifier")
    session_id: Optional[str] = Field(None, description="Session correlation identifier")
    user_agent: Optional[str] = Field(None, description="User agent string")
    request_uri: Optional[str] = Field(None, description="Request URI/endpoint")
    method: Optional[str] = Field(None, description="HTTP method (GET|POST|etc)")
    status: EventStatus = Field(..., description="Event status (success|failure|error)")
    data: Dict[str, Any] = Field(default_factory=dict, description="Event-specific fields")
    
    class Config:
        # Use enum values in JSON serialization
        use_enum_values = True
        # Allow arbitrary types for flexible data field
        arbitrary_types_allowed = True


class RawLogEvent(BaseModel):
    """
    Internal model for raw log events before normalization
    
    This includes the original source attribution that gets removed
    before events are sent to blue teams.
    """
    timestamp: datetime
    raw_source: str = Field(..., description="Original container source (including traffic_sim)")
    log_line: str = Field(..., description="Original log line")
    parsed_data: Dict[str, Any] = Field(default_factory=dict)
    
    # Internal fields (removed before blue team exposure)
    simulation_id: Optional[str] = Field(None, description="Traffic simulator session ID")
    legitimate_activity: Optional[bool] = Field(None, description="Marks legitimate traffic sim events")
    traffic_pattern: Optional[str] = Field(None, description="Traffic simulator pattern type")


class EventQuery(BaseModel):
    """Query parameters for blue team event requests"""
    timeframe: str = Field(default="5m", description="Time window (5m|1h|2024-09-17T08:00:00/2024-09-17T09:00:00)")
    event_types: Optional[List[EventType]] = Field(None, description="Filter by event types")
    sources: Optional[List[EventSource]] = Field(None, description="Filter by container sources")
    source_ip: Optional[str] = Field(None, description="Filter by source IP")
    limit: Optional[int] = Field(1000, description="Maximum events to return")


class EventResponse(BaseModel):
    """API response for blue team event queries"""
    events: List[SecurityEvent] = Field(..., description="List of normalized security events")
    summary: Dict[str, Any] = Field(..., description="Event summary statistics")
    query: EventQuery = Field(..., description="Original query parameters")
    total_events: int = Field(..., description="Total events matching query")
    timeframe_start: datetime = Field(..., description="Query time window start")
    timeframe_end: datetime = Field(..., description="Query time window end")


class HealthStatus(BaseModel):
    """SIEM health check response"""
    status: str = Field(..., description="Service status (healthy|degraded|unhealthy)")
    timestamp: datetime = Field(..., description="Health check timestamp")
    event_buffer_size: int = Field(..., description="Current events in buffer")
    log_sources_active: int = Field(..., description="Number of active log sources")
    last_event_time: Optional[datetime] = Field(None, description="Most recent event timestamp")
    uptime_seconds: float = Field(..., description="Service uptime in seconds")