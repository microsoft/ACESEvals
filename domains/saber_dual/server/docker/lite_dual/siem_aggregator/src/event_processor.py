"""
SIEM Event Processor (HTTP-only Ingestion)

Refactored to remove file-based log watching in favor of direct HTTP ingestion from
all producers (services + traffic simulators). Simplifies deployment, eliminates
file race conditions, and enforces a single normalized pipeline.

Key Features:
    • In-memory ring buffer with retention-based cleanup
    • Event rate tracking (1m / 5m / total)
    • Source attribution masking via destination_service override
    • Schema normalization & simulator field scrubbing
"""

import asyncio
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Deque, Set
import structlog

from .models.events import SecurityEvent, EventSource, EventType, EventStatus

logger = structlog.get_logger(__name__)


class EventProcessor:
    """
    Core SIEM event processor with real-time log monitoring
    """
    
    def __init__(self, retention_minutes: int = 5):
        self.retention_minutes = retention_minutes
        self.event_buffer: Deque[SecurityEvent] = deque(maxlen=10000)
        self.start_time = time.time()
        self.last_event_time: Optional[datetime] = None
        self.active_sources: Set[str] = set()

        # Rate tracking (timestamps of events)
        self.event_timestamps: Deque[float] = deque(maxlen=20000)

        logger.info(
            "EventProcessor initialized (HTTP-only mode)",
            retention_minutes=retention_minutes,
            max_buffer_size=10000
        )
    
    async def start(self):
        """Start the event processor (HTTP-only mode)"""
        logger.info("Starting SIEM EventProcessor (HTTP-only)")
        asyncio.create_task(self._cleanup_old_events())
        logger.info("EventProcessor started successfully", active_sources=len(self.active_sources))
    
    async def stop(self):
        """
        Stop the event processor and cleanup resources
        """
        logger.info("Stopping SIEM EventProcessor (HTTP-only)")
        logger.info("EventProcessor stopped successfully")
    
    # Removed file watching & raw log line parsing – HTTP-only ingestion path now
    
    # Legacy normalization removed; producers must submit already-normalized events.
    
    def _map_simulator_source(self, raw_source: str, destination_service: Optional[str]) -> Optional[EventSource]:
        """Explicit mapping for traffic simulator submissions using destination_service field."""
        if raw_source in ['external_traffic_sim', 'internal_traffic_sim']:
            if destination_service in ['webapp', 'api_gateway', 'vault', 'database']:
                return EventSource(destination_service)
            # Default bias: external -> webapp, internal -> api_gateway
            return EventSource.WEBAPP if raw_source == 'external_traffic_sim' else EventSource.API_GATEWAY
        return None
    
    def _sanitize_event_data(self, data: Dict) -> Dict:
        sanitized = dict(data) if data else {}
        for k in ['simulation_id','legitimate_activity','traffic_pattern','simulator_session','automation_flag','destination_service']:
            sanitized.pop(k, None)
        return sanitized
    
    async def _cleanup_old_events(self):
        """
        Background task to remove events older than retention period
        """
        while True:
            try:
                from datetime import timezone
                cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=self.retention_minutes)
                
                # Remove old events from buffer
                while (self.event_buffer and self.event_buffer[0].timestamp < cutoff_time):
                    self.event_buffer.popleft()
                # Prune event timestamps (rate tracking)
                now = time.time()
                one_hour_ago = now - 3600
                while self.event_timestamps and self.event_timestamps[0] < one_hour_ago:
                    self.event_timestamps.popleft()
                
                # Sleep for 30 seconds before next cleanup
                await asyncio.sleep(30)
                
            except Exception as e:
                logger.error("Error in cleanup task", error=str(e))
                await asyncio.sleep(30)
    
    def get_events(self, 
                   timeframe: str = "5m",
                   event_types: Optional[List[EventType]] = None,
                   sources: Optional[List[EventSource]] = None,
                   source_ip: Optional[str] = None,
                   limit: int = 1000) -> List[SecurityEvent]:
        """
        Query events from the buffer with filtering
        """
        try:
            # Parse timeframe
            start_time, end_time = self._parse_timeframe(timeframe)
            
            # Filter events
            filtered_events = []
            
            for event in reversed(self.event_buffer):  # Most recent first
                # Time filter
                if event.timestamp < start_time or event.timestamp > end_time:
                    continue
                
                # Type filter
                if event_types and event.event_type not in event_types:
                    continue
                
                # Source filter  
                if sources and event.source not in sources:
                    continue
                
                # IP filter
                if source_ip and event.source_ip != source_ip:
                    continue
                
                filtered_events.append(event)
                
                # Limit results
                if len(filtered_events) >= limit:
                    break
            
            return filtered_events
            
        except Exception as e:
            logger.error("Failed to query events", error=str(e))
            return []
    
    def _parse_timeframe(self, timeframe: str) -> tuple[datetime, datetime]:
        """
        Parse timeframe string to start/end datetime
        """
        from datetime import timezone
        end_time = datetime.now(timezone.utc)  # Make timezone-aware
        
        if timeframe.endswith('m'):
            minutes = int(timeframe[:-1])
            start_time = end_time - timedelta(minutes=minutes)
        elif timeframe.endswith('h'):
            hours = int(timeframe[:-1])
            start_time = end_time - timedelta(hours=hours)
        elif '/' in timeframe:
            # ISO format: 2024-09-17T08:00:00/2024-09-17T09:00:00
            start_str, end_str = timeframe.split('/')
            start_time = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
            end_time = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
        else:
            # Default to 5 minutes
            start_time = end_time - timedelta(minutes=5)
        
        return start_time, end_time
    
    def normalize_http_event(self, event_data: dict, source_hint: str = None) -> SecurityEvent:
        from datetime import datetime
        import uuid

        raw_source = source_hint or event_data.get('source') or 'unknown'
        destination_service = event_data.get('destination_service')

        # Determine final visible source
        if raw_source in ['external_traffic_sim', 'internal_traffic_sim']:
            mapped = self._map_simulator_source(raw_source, destination_service)
            if not mapped:
                raise ValueError(f"Unmappable traffic simulator source '{raw_source}' (destination_service={destination_service!r})")
            source = mapped
        else:
            if raw_source not in [e.value for e in EventSource]:
                raise ValueError(f"Unknown source '{raw_source}' (must be one of {[e.value for e in EventSource]})")
            source = EventSource(raw_source)

        ts = event_data.get('timestamp')
        if isinstance(ts, str):
            timestamp = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        else:
            from datetime import timezone
            timestamp = ts or datetime.now(timezone.utc)  # Make timezone-aware

        if 'event_type' not in event_data:
            raise ValueError("Missing required field 'event_type'")
        event_type_raw = event_data.get('event_type')
        try:
            event_type = EventType(event_type_raw)
        except ValueError:
            raise ValueError(f"Unknown event_type '{event_type_raw}' (allowed: {[e.value for e in EventType]})")

        if 'status' not in event_data:
            raise ValueError("Missing required field 'status'")
        status_raw = event_data.get('status')
        try:
            status = EventStatus(status_raw)
        except ValueError:
            raise ValueError(f"Unknown status '{status_raw}' (allowed: {[s.value for s in EventStatus]})")

        event_id = event_data.get('event_id') or str(uuid.uuid4())

        security_event = SecurityEvent(
            timestamp=timestamp,
            source=source,
            source_ip=event_data.get('source_ip', '127.0.0.1'),
            event_type=event_type,
            event_id=event_id,
            session_id=event_data.get('session_id'),
            user_agent=event_data.get('user_agent'),
            request_uri=event_data.get('request_uri'),
            method=event_data.get('method'),
            status=status,
            data=self._sanitize_event_data(event_data.get('data'))
        )
        logger.debug(
            "Normalized HTTP event",
            source=source,
            event_type=security_event.event_type,
            event_id=event_id
        )
        return security_event
    
    def add_event(self, security_event: SecurityEvent):
        """
        Add a security event directly to the buffer
        
        Used for HTTP-submitted events that bypass file processing.
        """
        self.event_buffer.append(security_event)
        self.last_event_time = security_event.timestamp
        self.active_sources.add(security_event.source.value if hasattr(security_event.source, 'value') else security_event.source)
        self.event_timestamps.append(time.time())
        logger.debug(
            "Added event to buffer",
            source=security_event.source,
            event_type=security_event.event_type,
            buffer_size=len(self.event_buffer)
        )
    
    def get_health_status(self) -> Dict:
        """
        Get processor health status for monitoring
        """
        now = time.time()
        one_minute = now - 60
        five_minutes = now - 300
        events_last_min = sum(1 for t in self.event_timestamps if t >= one_minute)
        events_last_5m = sum(1 for t in self.event_timestamps if t >= five_minutes)
        return {
            'status': 'healthy' if self.active_sources else 'degraded',
            'timestamp': datetime.now(),
            'event_buffer_size': len(self.event_buffer),
            'log_sources_active': len(self.active_sources),
            'last_event_time': self.last_event_time,
            'uptime_seconds': time.time() - self.start_time,
            'events_last_minute': events_last_min,
            'events_last_5m': events_last_5m,
            'events_total': len(self.event_timestamps)
        }