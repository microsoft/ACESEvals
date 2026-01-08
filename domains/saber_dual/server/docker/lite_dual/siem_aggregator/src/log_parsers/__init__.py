"""
Log Parser Factory and Base Classes

Factory pattern for creating appropriate log parsers for different container sources.
Each parser handles the specific log format of its container type.
"""

import re
import json
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
import structlog

from ..models.events import EventType, EventStatus

logger = structlog.get_logger(__name__)


class BaseLogParser(ABC):
    """
    Abstract base class for container log parsers
    """
    
    def __init__(self, source: str):
        self.source = source
    
    @abstractmethod
    async def parse_line(self, log_line: str, file_path: Path) -> Optional[Dict[str, Any]]:
        """
        Parse a single log line and extract structured data
        
        Returns:
            Dict with parsed fields or None if line should be ignored
        """
        pass
    
    def _extract_timestamp(self, log_line: str) -> Optional[datetime]:
        """
        Extract timestamp from log line (common patterns)
        """
        # Try common timestamp patterns
        patterns = [
            r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z?)',  # ISO format
            r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})',  # MySQL format
            r'\[(\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4})\]',  # Apache format
        ]
        
        for pattern in patterns:
            match = re.search(pattern, log_line)
            if match:
                try:
                    timestamp_str = match.group(1)
                    # Handle different formats
                    if 'T' in timestamp_str:
                        return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    elif '/' in timestamp_str:
                        return datetime.strptime(timestamp_str, '%d/%b/%Y:%H:%M:%S %z')
                    else:
                        return datetime.fromisoformat(timestamp_str)
                except (ValueError, TypeError):
                    continue
        
        # Default to current time if no timestamp found
        return datetime.now()
    
    def _extract_ip(self, log_line: str) -> str:
        """
        Extract IP address from log line
        """
        ip_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
        match = re.search(ip_pattern, log_line)
        return match.group(0) if match else '127.0.0.1'
    
    def _extract_user_agent(self, log_line: str) -> Optional[str]:
        """
        Extract User-Agent from log line
        """
        ua_pattern = r'"([^"]*(?:Mozilla|curl|wget|Python|Node|SABER)[^"]*)"'
        match = re.search(ua_pattern, log_line)
        return match.group(1) if match else None


class WebAppLogParser(BaseLogParser):
    """
    Parser for Apache/PHP webapp logs
    """
    
    async def parse_line(self, log_line: str, file_path: Path) -> Optional[Dict[str, Any]]:
        """
        Parse webapp log lines (Apache access logs and custom security logs)
        """
        try:
            # Check if this is a JSON security event
            if log_line.strip().startswith('{'):
                try:
                    data = json.loads(log_line)
                    return await self._parse_security_json(data)
                except json.JSONDecodeError:
                    pass
            
            # Parse Apache access log format
            apache_pattern = r'(\S+) \S+ \S+ \[(.*?)\] "(\S+) (\S+) \S+" (\d+) (\d+) "(.*?)" "(.*?)"'
            match = re.match(apache_pattern, log_line)
            
            if match:
                ip, timestamp_str, method, uri, status, size, referer, user_agent = match.groups()
                
                return {
                    'timestamp': self._extract_timestamp(log_line),
                    'source_ip': ip,
                    'method': method,
                    'request_uri': uri,
                    'status_code': int(status),
                    'user_agent': user_agent,
                    'event_type': self._classify_webapp_event(method, uri, status),
                    'status': EventStatus.SUCCESS if status.startswith('2') else EventStatus.FAILURE,
                    'data': {
                        'response_size': int(size) if size.isdigit() else 0,
                        'referer': referer
                    }
                }
            
            return None
            
        except Exception as e:
            logger.debug("Failed to parse webapp log line", 
                        line=log_line[:100], 
                        error=str(e))
            return None
    
    async def _parse_security_json(self, data: Dict) -> Dict[str, Any]:
        """
        Parse structured security events from webapp
        """
        return {
            'timestamp': datetime.fromisoformat(data.get('timestamp', datetime.now().isoformat())),
            'source_ip': data.get('source_ip', '127.0.0.1'),
            'event_type': EventType(data.get('event_type', 'api_request')),
            'status': EventStatus(data.get('status', 'success')),
            'session_id': data.get('session_id'),
            'user_agent': data.get('user_agent'),
            'request_uri': data.get('request_uri'),
            'method': data.get('method'),
            'data': data.get('data', {})
        }
    
    def _classify_webapp_event(self, method: str, uri: str, status: str) -> EventType:
        """
        Classify webapp events based on URI and method
        """
        if '/login' in uri or 'action=login' in uri:
            return EventType.AUTH_ATTEMPT
        elif '/upload' in uri or 'upload' in uri:
            return EventType.FILE_UPLOAD
        elif '/admin' in uri:
            return EventType.API_REQUEST
        else:
            return EventType.API_REQUEST


class APIGatewayLogParser(BaseLogParser):
    """
    Parser for Node.js API Gateway logs
    """
    
    async def parse_line(self, log_line: str, file_path: Path) -> Optional[Dict[str, Any]]:
        """
        Parse API Gateway log lines (structured JSON logs)
        """
        try:
            # API Gateway primarily logs structured JSON
            if log_line.strip().startswith('{'):
                data = json.loads(log_line)
                return await self._parse_api_json(data)
            
            # Fallback for unstructured logs
            return {
                'timestamp': self._extract_timestamp(log_line),
                'source_ip': self._extract_ip(log_line),
                'event_type': EventType.API_REQUEST,
                'status': EventStatus.SUCCESS,
                'data': {'raw_log': log_line[:200]}
            }
            
        except Exception as e:
            logger.debug("Failed to parse API Gateway log line",
                        line=log_line[:100],
                        error=str(e))
            return None
    
    async def _parse_api_json(self, data: Dict) -> Dict[str, Any]:
        """
        Parse structured JSON events from API Gateway
        """
        return {
            'timestamp': datetime.fromisoformat(data.get('timestamp', datetime.now().isoformat())),
            'source_ip': data.get('source_ip', '127.0.0.1'),
            'event_type': EventType(data.get('event_type', 'api_request')),
            'status': EventStatus(data.get('status', 'success')),
            'session_id': data.get('session_id'),
            'user_agent': data.get('user_agent'),
            'request_uri': data.get('endpoint', data.get('request_uri')),
            'method': data.get('method'),
            'data': {
                'username': data.get('username'),
                'file_size': data.get('file_size'),
                'file_type': data.get('file_type'),
                **data.get('data', {})
            }
        }


class VaultLogParser(BaseLogParser):
    """
    Parser for Vault service logs
    """
    
    async def parse_line(self, log_line: str, file_path: Path) -> Optional[Dict[str, Any]]:
        """
        Parse Vault service log lines
        """
        try:
            # Vault logs are typically JSON structured
            if log_line.strip().startswith('{'):
                data = json.loads(log_line)
                return await self._parse_vault_json(data)
            
            return None
            
        except Exception as e:
            logger.debug("Failed to parse Vault log line",
                        line=log_line[:100],
                        error=str(e))
            return None
    
    async def _parse_vault_json(self, data: Dict) -> Dict[str, Any]:
        """
        Parse structured vault events
        """
        event_type = EventType.SECRET_ACCESS
        if 'crown_jewel' in data.get('endpoint', ''):
            event_type = EventType.FLAG_ACCESSED
        
        return {
            'timestamp': datetime.fromisoformat(data.get('timestamp', datetime.now().isoformat())),
            'source_ip': data.get('source_ip', '127.0.0.1'),
            'event_type': event_type,
            'status': EventStatus(data.get('status', 'success')),
            'session_id': data.get('session_id'),
            'user_agent': data.get('user_agent'),
            'request_uri': data.get('endpoint'),
            'method': data.get('method', 'GET'),
            'data': {
                'secret_type': data.get('secret_type'),
                'access_token': data.get('access_token', '***'),
                **data.get('data', {})
            }
        }


class DatabaseLogParser(BaseLogParser):
    """
    Parser for MySQL database logs
    """
    
    async def parse_line(self, log_line: str, file_path: Path) -> Optional[Dict[str, Any]]:
        """
        Parse MySQL log lines
        """
        try:
            # Look for SQL queries
            if 'SELECT' in log_line.upper() or 'UNION' in log_line.upper():
                return {
                    'timestamp': self._extract_timestamp(log_line),
                    'source_ip': self._extract_ip(log_line),
                    'event_type': EventType.SQL_QUERY,
                    'status': EventStatus.SUCCESS,
                    'data': {
                        'query_type': 'SELECT' if 'SELECT' in log_line.upper() else 'OTHER',
                        'has_union': 'UNION' in log_line.upper(),
                        'query_snippet': log_line[:100]
                    }
                }
            
            return None
            
        except Exception as e:
            logger.debug("Failed to parse Database log line",
                        line=log_line[:100],
                        error=str(e))
            return None


class TrafficSimLogParser(BaseLogParser):
    """
    Parser for traffic simulator logs (includes attribution metadata)
    """
    
    async def parse_line(self, log_line: str, file_path: Path) -> Optional[Dict[str, Any]]:
        """
        Parse traffic simulator log lines with metadata preservation
        """
        try:
            if log_line.strip().startswith('{'):
                data = json.loads(log_line)
                return await self._parse_traffic_json(data)
            
            return None
            
        except Exception as e:
            logger.debug("Failed to parse Traffic Sim log line",
                        line=log_line[:100], 
                        error=str(e))
            return None
    
    async def _parse_traffic_json(self, data: Dict) -> Dict[str, Any]:
        """
        Parse traffic simulator events with metadata
        """
        parsed = {
            'timestamp': datetime.fromisoformat(data.get('timestamp', datetime.now().isoformat())),
            'source_ip': data.get('source_ip', '127.0.0.1'),
            'event_type': EventType(data.get('event_type', 'api_request')),
            'status': EventStatus(data.get('status', 'success')),
            'session_id': data.get('session_id'),
            'user_agent': data.get('user_agent'),
            'request_uri': data.get('endpoint', data.get('request_uri')),
            'method': data.get('method'),
            'target_url': data.get('target_url'),  # Used for source mapping
            
            # Traffic simulator metadata (removed before blue team exposure)
            'simulation_id': data.get('simulation_id'),
            'legitimate_activity': data.get('legitimate_activity', True),
            'traffic_pattern': data.get('traffic_pattern'),
            
            'data': data.get('data', {})
        }
        
        return parsed


class LogParserFactory:
    """
    Factory for creating appropriate log parsers
    """
    
    def __init__(self):
        self._parsers = {
            'webapp': WebAppLogParser('webapp'),
            'api_gateway': APIGatewayLogParser('api_gateway'),
            'vault': VaultLogParser('vault'),
            'database': DatabaseLogParser('database'),
            'external_traffic_sim': TrafficSimLogParser('external_traffic_sim'),
            'internal_traffic_sim': TrafficSimLogParser('internal_traffic_sim')
        }
    
    def get_parser(self, source: str) -> BaseLogParser:
        """
        Get appropriate parser for the given source
        """
        return self._parsers.get(source, self._parsers['webapp'])  # Default to webapp parser