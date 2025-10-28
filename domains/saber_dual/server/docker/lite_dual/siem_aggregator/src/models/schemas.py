"""
SIEM API Schemas

Request and response schemas for the SIEM REST API.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from .events import EventType, EventSource


class EventsRequest(BaseModel):
    """Request schema for /api/events endpoint"""
    timeframe: str = Field(default="5m", description="Time window")
    event_types: Optional[List[EventType]] = None
    sources: Optional[List[EventSource]] = None
    source_ip: Optional[str] = None
    limit: Optional[int] = Field(default=1000, le=10000)


class EventSummary(BaseModel):
    """Event summary statistics"""
    total_events: int
    events_by_type: Dict[str, int]
    events_by_source: Dict[str, int]
    unique_source_ips: int
    time_range: Dict[str, str]


class ErrorResponse(BaseModel):
    """Error response schema"""
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Human-readable error message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error context")