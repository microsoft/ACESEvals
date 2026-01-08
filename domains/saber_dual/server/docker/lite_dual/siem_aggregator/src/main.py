"""
SIEM Aggregator Main Server

FastAPI server providing REST API for blue team security event queries.
Implements the unified get_security_events() interface replacing scattered log methods.
"""

import asyncio
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional

import structlog
from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.responses import JSONResponse
import uvicorn

from .event_processor import EventProcessor
from .models import (
    SecurityEvent, EventType, EventSource, EventsRequest, EventQuery,
    EventResponse, EventSummary, HealthStatus, ErrorResponse
)

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO level
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# Global event processor instance
event_processor: Optional[EventProcessor] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan management - startup and shutdown
    """
    global event_processor
    
    # Startup
    logger.info("Starting SIEM Aggregator")
    
    # Initialize event processor with configurable retention
    retention_minutes = int(os.getenv('LOG_RETENTION_MINUTES', '5'))
    event_processor = EventProcessor(retention_minutes=retention_minutes)
    
    # Start event processing
    await event_processor.start()
    
    logger.info("SIEM Aggregator started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down SIEM Aggregator")
    if event_processor:
        await event_processor.stop()
    logger.info("SIEM Aggregator shutdown complete")


# Create FastAPI application
app = FastAPI(
    title="SABER SIEM Aggregator",
    description="Centralized security event collection and normalization for blue team analysis",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/health", response_model=HealthStatus)
async def health_check():
    """
    Health check endpoint for container monitoring
    """
    if not event_processor:
        raise HTTPException(status_code=503, detail="Event processor not initialized")
    
    health_data = event_processor.get_health_status()
    
    return HealthStatus(**health_data)


@app.get("/api/events", response_model=EventResponse)
async def get_security_events(
    timeframe: str = Query(default="5m", description="Time window (5m|1h|ISO range)"),
    event_types: Optional[List[EventType]] = Query(default=None, description="Filter by event types"),
    sources: Optional[List[EventSource]] = Query(default=None, description="Filter by container sources"),
    source_ip: Optional[str] = Query(default=None, description="Filter by source IP"),
    limit: int = Query(default=1000, le=10000, description="Maximum events to return")
):
    """
    Primary blue team interface - unified security event query
    
    This endpoint replaces the scattered get_network_logs() and get_service_logs() methods.
    Returns normalized events from all container sources with traffic simulator attribution removed.
    """
    if not event_processor:
        raise HTTPException(status_code=503, detail="Event processor not available")
    
    try:
        # Parse timeframe for response metadata
        start_time, end_time = event_processor._parse_timeframe(timeframe)
        
        # Query events from processor
        events = event_processor.get_events(
            timeframe=timeframe,
            event_types=event_types,
            sources=sources,
            source_ip=source_ip,
            limit=limit
        )
        
        # Generate summary statistics
        summary = generate_event_summary(events, start_time, end_time)
        
        logger.info("Security events query completed",
                   total_events=len(events),
                   timeframe=timeframe,
                   event_types=event_types,
                   sources=sources)
        
        return EventResponse(
            events=events,
            summary=summary,
            query=EventQuery(
                timeframe=timeframe,
                event_types=event_types,
                sources=sources,
                source_ip=source_ip,
                limit=limit
            ),
            total_events=len(events),
            timeframe_start=start_time,
            timeframe_end=end_time
        )
        
    except Exception as e:
        logger.error("Failed to query security events", error=str(e))
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")


@app.get("/api/events/summary", response_model=EventSummary)
async def get_events_summary(
    timeframe: str = Query(default="5m", description="Time window"),
    sources: Optional[List[EventSource]] = Query(default=None, description="Filter by sources")
):
    """
    Get event summary statistics without full event data
    """
    if not event_processor:
        raise HTTPException(status_code=503, detail="Event processor not available")
    
    try:
        events = event_processor.get_events(
            timeframe=timeframe,
            sources=sources,
            limit=10000  # High limit for accurate statistics
        )
        
        start_time, end_time = event_processor._parse_timeframe(timeframe)
        summary = generate_event_summary(events, start_time, end_time)
        
        return EventSummary(**summary)
        
    except Exception as e:
        logger.error("Failed to generate event summary", error=str(e))
        raise HTTPException(status_code=500, detail=f"Summary generation failed: {str(e)}")


@app.get("/api/sources", response_model=List[str])
async def get_active_sources():
    """Get list of active sources (post-masking)"""
    if not event_processor:
        raise HTTPException(status_code=503, detail="Event processor not available")
    return list(event_processor.active_sources)

@app.get("/api/meta/event_types", response_model=List[str])
async def meta_event_types():
    """List supported event types"""
    return [e.value for e in EventType]

@app.get("/api/meta/sources", response_model=List[str])
async def meta_sources():
    """List supported visible sources"""
    return [s.value for s in EventSource]

@app.get("/api/events/distribution")
async def events_distribution(timeframe: str = Query(default="5m")):
    """Lightweight distribution summary without returning full events."""
    if not event_processor:
        raise HTTPException(status_code=503, detail="Event processor not available")
    events = event_processor.get_events(timeframe=timeframe, limit=10000)
    start_time, end_time = event_processor._parse_timeframe(timeframe)
    summary = generate_event_summary(events, start_time, end_time)
    return {
        'timeframe': timeframe,
        'counts_by_type': summary['events_by_type'],
        'counts_by_source': summary['events_by_source'],
        'total_events': summary['total_events']
    }


@app.post("/api/events/ingest")
async def ingest_security_event(
    event: dict,
    x_source: Optional[str] = None,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
):
    """
    HTTP endpoint for services to submit security events directly
    
    Replaces file-based logging with direct HTTP submission for reliability.
    Services POST their events here for immediate ingestion and processing.
    """
    if not event_processor:
        raise HTTPException(status_code=503, detail="Event processor not available")
    
    # Basic API key validation (simple for simulation environment)
    expected_api_key = "siem_ingest_key_2024"
    if x_api_key != expected_api_key:
        logger.warning("Invalid API key for event ingestion", 
                      source=x_source, 
                      provided_key=x_api_key[:8] + "..." if x_api_key else None)
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    try:
        # Validate and normalize the event
        normalized_event = event_processor.normalize_http_event(event, x_source)
        
        # Add to event buffer immediately
        event_processor.add_event(normalized_event)
        
        logger.debug("Event ingested via HTTP", 
                    source=x_source,
                    event_type=event.get('event_type'),
                    event_id=event.get('event_id'))
        
        return {"status": "success", "event_id": event.get('event_id')}
        
    except Exception as e:
        logger.error("Failed to ingest HTTP event", 
                    source=x_source,
                    error=str(e),
                    event_preview=str(event)[:200])
        raise HTTPException(status_code=400, detail=f"Event ingestion failed: {str(e)}")


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """
    Global exception handler for unhandled errors
    """
    logger.error("Unhandled exception", 
                path=request.url.path,
                method=request.method,
                error=str(exc))
    
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="internal_server_error",
            message="An internal error occurred",
            details={"path": str(request.url.path)}
        ).model_dump()
    )


def generate_event_summary(events: List[SecurityEvent], start_time: datetime, end_time: datetime) -> dict:
    """
    Generate summary statistics for a list of events
    """
    # Count events by type
    events_by_type = {}
    for event in events:
        event_type = event.event_type.value if hasattr(event.event_type, 'value') else str(event.event_type)
        events_by_type[event_type] = events_by_type.get(event_type, 0) + 1
    
    # Count events by source
    events_by_source = {}
    for event in events:
        source = event.source.value if hasattr(event.source, 'value') else str(event.source)
        events_by_source[source] = events_by_source.get(source, 0) + 1
    
    # Count unique source IPs
    unique_ips = set(event.source_ip for event in events)
    
    return {
        'total_events': len(events),
        'events_by_type': events_by_type,
        'events_by_source': events_by_source,
        'unique_source_ips': len(unique_ips),
        'time_range': {
            'start': start_time.isoformat(),
            'end': end_time.isoformat()
        }
    }


def main():
    """
    Main entry point for the SIEM aggregator service
    """
    # Configuration from environment
    host = os.getenv('SIEM_HOST', '0.0.0.0')
    port = int(os.getenv('SIEM_PORT', '8080'))
    log_level = os.getenv('SIEM_LOG_LEVEL', 'info').lower()
    workers = int(os.getenv('SIEM_WORKERS', '1'))
    
    logger.info("Starting SIEM Aggregator server",
               host=host,
               port=port,
               log_level=log_level,
               workers=workers)
    
    # Run uvicorn server
    uvicorn.run(
        "src.main:app",
        host=host,
        port=port,
        log_level=log_level,
        workers=workers,
        access_log=True
    )


if __name__ == "__main__":
    main()