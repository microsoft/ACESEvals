"""
Test SIEM Event Normalization

Tests for the event normalization engine to ensure proper event schema standardization.
"""

import pytest
from datetime import datetime
from src.models.events import SecurityEvent, RawLogEvent, EventType, EventSource, EventStatus


class TestEventNormalization:
    """Test event normalization functionality"""
    
    def test_security_event_creation(self):
        """Test creation of normalized security events"""
        event = SecurityEvent(
            timestamp=datetime.now(),
            source=EventSource.WEBAPP,
            source_ip="192.168.1.100",
            event_type=EventType.AUTH_ATTEMPT,
            event_id="test_001",
            session_id="session_123",
            user_agent="Mozilla/5.0",
            request_uri="/login",
            method="POST",
            status=EventStatus.SUCCESS,
            data={"username": "test_user"}
        )
        
        assert event.source == EventSource.WEBAPP
        assert event.event_type == EventType.AUTH_ATTEMPT
        assert event.status == EventStatus.SUCCESS
        assert event.data["username"] == "test_user"
    
    def test_raw_log_event_creation(self):
        """Test creation of raw log events with metadata"""
        raw_event = RawLogEvent(
            timestamp=datetime.now(),
            raw_source="external_traffic_sim",
            log_line='{"event_type": "auth_attempt", "legitimate_activity": true}',
            parsed_data={"event_type": "auth_attempt"},
            simulation_id="sim_001",
            legitimate_activity=True,
            traffic_pattern="employee_login"
        )
        
        assert raw_event.raw_source == "external_traffic_sim"
        assert raw_event.legitimate_activity is True
        assert raw_event.simulation_id == "sim_001"
    
    def test_event_type_enum(self):
        """Test event type enumeration"""
        assert EventType.AUTH_ATTEMPT == "auth_attempt"
        assert EventType.FLAG_ACCESSED == "flag_accessed"
        assert EventType.SECRET_ACCESS == "secret_access"
    
    def test_event_source_enum(self):
        """Test event source enumeration (no traffic sim sources)"""
        sources = list(EventSource)
        source_values = [s.value for s in sources]
        
        assert "webapp" in source_values
        assert "api_gateway" in source_values
        assert "vault" in source_values
        assert "database" in source_values
        
        # Traffic simulator sources should NOT be in EventSource enum
        assert "external_traffic_sim" not in source_values
        assert "internal_traffic_sim" not in source_values


if __name__ == "__main__":
    pytest.main([__file__])