"""
Test Source Attribution Removal

Tests for the traffic simulator source hiding functionality.
"""

import pytest
from datetime import datetime
from src.event_processor import EventProcessor
from src.models.events import RawLogEvent, EventSource


class TestSourceAttribution:
    """Test source attribution removal functionality"""
    
    def setup_method(self):
        """Setup test fixtures"""
        self.processor = EventProcessor(retention_minutes=5)
    
    def test_traffic_sim_source_mapping(self):
        """Test mapping of traffic simulator sources to infrastructure"""
        # External traffic sim accessing webapp
        result = self.processor._map_source(
            "external_traffic_sim", 
            {"target_url": "http://webapp:80/login"}
        )
        assert result == EventSource.WEBAPP
        
        # Internal traffic sim accessing vault
        result = self.processor._map_source(
            "internal_traffic_sim",
            {"target_url": "http://vault_service:6379/secrets"}
        )
        assert result == EventSource.VAULT
        
        # Direct infrastructure source
        result = self.processor._map_source(
            "api_gateway",
            {"target_url": "http://localhost:8080"}
        )
        assert result == EventSource.API_GATEWAY
    
    def test_data_sanitization(self):
        """Test removal of traffic simulator metadata"""
        original_data = {
            "event_type": "auth_attempt",
            "source_ip": "192.168.1.100",
            "simulation_id": "sim_001",
            "legitimate_activity": True,
            "traffic_pattern": "employee_login",
            "user_agent": "Mozilla/5.0"
        }
        
        sanitized = self.processor._sanitize_event_data(original_data, "external_traffic_sim")
        
        # Should preserve legitimate fields
        assert sanitized["event_type"] == "auth_attempt"
        assert sanitized["source_ip"] == "192.168.1.100"
        assert sanitized["user_agent"] == "Mozilla/5.0"
        
        # Should remove simulator-specific fields
        assert "simulation_id" not in sanitized
        assert "legitimate_activity" not in sanitized
        assert "traffic_pattern" not in sanitized
    
    def test_unknown_source_handling(self):
        """Test handling of unknown/invalid sources"""
        result = self.processor._map_source("unknown_container", {})
        assert result is None
        
        result = self.processor._map_source("", {"target_url": ""})
        assert result is None
    
    def test_crown_jewel_access_masking(self):
        """Test that crown jewel access from different sources looks identical"""
        # Traffic simulator crown jewel access
        traffic_sim_data = {
            "target_url": "http://vault_service:6379/secrets/flags/crown_jewel",
            "simulation_id": "audit_001",
            "legitimate_activity": True
        }
        
        mapped_source = self.processor._map_source("internal_traffic_sim", traffic_sim_data)
        sanitized_data = self.processor._sanitize_event_data(traffic_sim_data, "internal_traffic_sim")
        
        # Should map to vault source
        assert mapped_source == EventSource.VAULT
        
        # Should remove simulation metadata
        assert "simulation_id" not in sanitized_data
        assert "legitimate_activity" not in sanitized_data
        
        # Target URL should remain for blue team analysis
        assert sanitized_data["target_url"] == "http://vault_service:6379/secrets/flags/crown_jewel"


if __name__ == "__main__":
    pytest.main([__file__])