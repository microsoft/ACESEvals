"""Simple Python SIEM ingestion client for producers (traffic simulators).

Usage:
    from ingest_client import SIEMIngestClient, build_event
    client = SIEMIngestClient()
    client.emit(build_event(source="external_traffic_sim", destination_service="webapp", event_type="auth_attempt", data={"pattern":"employee_access"}))
"""
from __future__ import annotations
import os
import uuid
import requests
from datetime import datetime, timezone
from typing import Any, Dict, Optional

SIEM_DEFAULT_URL = os.getenv("SIEM_INGEST_URL", "http://siem_aggregator:8080/api/events/ingest")
SIEM_API_KEY = os.getenv("SIEM_INGEST_API_KEY", "siem_ingest_key_2024")

class SIEMIngestError(Exception):
    pass

class SIEMIngestClient:
    def __init__(self, ingest_url: str | None = None, api_key: str | None = None, timeout: int = 5):
        self.ingest_url = ingest_url or SIEM_DEFAULT_URL
        self.api_key = api_key or SIEM_API_KEY
        self.timeout = timeout

    def emit(self, event: Dict[str, Any]) -> str:
        headers = {
            "Content-Type": "application/json",
            "x_api_key": self.api_key,
            "x_source": event.get("source", "unknown")
        }
        resp = requests.post(self.ingest_url, json=event, headers=headers, timeout=self.timeout)
        if resp.status_code != 200:
            raise SIEMIngestError(f"Ingest failed {resp.status_code}: {resp.text[:200]}")
        return resp.json().get("event_id", "")

def build_event(*, source: str, event_type: str, destination_service: Optional[str] = None, source_ip: str = "127.0.0.1", status: str = "success", session_id: str | None = None, user_agent: str | None = None, request_uri: str | None = None, method: str | None = None, data: Optional[Dict[str, Any]] = None, event_id: str | None = None, timestamp: datetime | None = None) -> Dict[str, Any]:
    return {
        "timestamp": (timestamp or datetime.now(timezone.utc)).isoformat(),
        "source": source,
        "destination_service": destination_service,
        "source_ip": source_ip,
        "event_type": event_type,
        "event_id": event_id or str(uuid.uuid4()),
        "session_id": session_id,
        "user_agent": user_agent,
        "request_uri": request_uri,
        "method": method,
        "status": status,
        "data": data or {}
    }
