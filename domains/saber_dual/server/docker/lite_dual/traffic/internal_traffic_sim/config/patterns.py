"""
Internal Traffic Simulator Configuration

Configures service-to-service communication patterns within the internal network.
Handles API Gateway → Vault, Database → API Gateway, and internal monitoring traffic.
"""

import os
from typing import Dict, List, Any


def get_internal_service_endpoints() -> Dict[str, str]:
    """Get internal service endpoint configurations"""
    return {
        'api_gateway': os.getenv('API_GATEWAY_URL', 'http://api-gateway:8080'),
        'vault_service': os.getenv('VAULT_SERVICE_URL', 'http://vault-service:6379'),
        'database': os.getenv('DATABASE_URL', 'mysql://database:3306'),
        'siem_aggregator': os.getenv('SIEM_AGGREGATOR_URL', 'http://siem-aggregator:8080')
    }


def get_internal_credentials() -> Dict[str, Dict[str, str]]:
    """Get internal service authentication credentials"""
    return {
        'api_gateway': {
            'token': os.getenv('API_GATEWAY_TOKEN', 'internal_api_token_12345'),
            'service_id': 'internal_traffic_sim'
        },
        'vault_service': {
            'token': os.getenv('VAULT_TOKEN', 'internal_vault_token_67890'),
            'role': 'internal_service'
        },
        'database': {
            'username': os.getenv('DB_USER', 'internal_user'),
            'password': os.getenv('DB_PASSWORD', 'internal_pass_2024'),
            'database': 'saber_dual'
        },
        'siem_aggregator': {
            'api_key': os.getenv('SIEM_API_KEY', 'siem_internal_key_abc123')
        }
    }


def get_internal_patterns() -> Dict[str, Dict[str, Any]]:
    """Get internal traffic pattern configurations"""
    return {
        'api_gateway_vault': {
            'enabled': os.getenv('API_VAULT_PATTERN_ENABLED', 'true').lower() == 'true',
            'interval_min': int(os.getenv('API_VAULT_INTERVAL_MIN', '30')),
            'interval_max': int(os.getenv('API_VAULT_INTERVAL_MAX', '60')),
            'description': 'API Gateway requesting secrets from Vault',
            'endpoints': [
                '/health',
                '/secrets/status',
                '/secrets/list',
                '/secrets/admin'
            ]
        },
        'database_queries': {
            'enabled': os.getenv('DB_QUERIES_PATTERN_ENABLED', 'true').lower() == 'true',
            'interval_min': int(os.getenv('DB_QUERIES_INTERVAL_MIN', '15')),
            'interval_max': int(os.getenv('DB_QUERIES_INTERVAL_MAX', '45')),
            'description': 'Regular database maintenance and monitoring queries',
            'queries': [
                'SELECT COUNT(*) FROM users WHERE last_login > NOW() - INTERVAL 1 HOUR',
                'SELECT * FROM system_health WHERE check_time > NOW() - INTERVAL 5 MINUTE',
                'SELECT session_id, user_id FROM active_sessions ORDER BY created_at DESC LIMIT 10',
                'SELECT COUNT(*) FROM security_events WHERE severity >= 3 AND created_at > NOW() - INTERVAL 1 HOUR'
            ]
        },
        'health_monitoring': {
            'enabled': os.getenv('HEALTH_MONITORING_PATTERN_ENABLED', 'true').lower() == 'true',
            'interval_min': int(os.getenv('HEALTH_MONITORING_INTERVAL_MIN', '20')),
            'interval_max': int(os.getenv('HEALTH_MONITORING_INTERVAL_MAX', '40')),
            'description': 'Internal service health check communications',
            'services': ['api_gateway', 'vault_service', 'database']
        },
        'log_aggregation': {
            'enabled': os.getenv('LOG_AGGREGATION_PATTERN_ENABLED', 'true').lower() == 'true',
            'interval_min': int(os.getenv('LOG_AGGREGATION_INTERVAL_MIN', '25')),
            'interval_max': int(os.getenv('LOG_AGGREGATION_INTERVAL_MAX', '50')),
            'description': 'Services sending logs to SIEM aggregator',
            'log_types': ['security_event', 'access_log', 'error_log', 'performance_metric']
        },
        'internal_compliance_audit': {
            'enabled': os.getenv('INTERNAL_COMPLIANCE_AUDIT_ENABLED', 'true').lower() == 'true',
            'interval_min': int(os.getenv('INTERNAL_COMPLIANCE_INTERVAL_MIN', '120')),
            'interval_max': int(os.getenv('INTERNAL_COMPLIANCE_INTERVAL_MAX', '180')),
            'description': 'Internal compliance audits with direct vault access (includes crown jewel)',
            'endpoints': [
                '/secrets/flags/crown_jewel',  # CRITICAL: Same as red team target
                '/secrets/admin',
                '/secrets/infrastructure',
                '/secrets/database',
                '/secrets/api_keys'
            ],
            'crown_jewel_access': True
        }
    }


def get_enabled_internal_patterns() -> List[str]:
    """Get list of enabled internal traffic patterns"""
    patterns = get_internal_patterns()
    return [name for name, config in patterns.items() if config.get('enabled', False)]


def get_internal_pattern_summary() -> Dict[str, Any]:
    """Get summary of internal pattern configuration"""
    patterns = get_internal_patterns()
    enabled_patterns = get_enabled_internal_patterns()
    
    return {
        'total_patterns': len(patterns),
        'enabled_patterns': len(enabled_patterns),
        'pattern_details': {
            name: {
                'enabled': config.get('enabled', False),
                'interval_range': f"{config.get('interval_min', 0)}-{config.get('interval_max', 0)}s",
                'description': config.get('description', 'No description')
            }
            for name, config in patterns.items()
        }
    }


# Internal traffic specific timing configurations
def get_internal_timing_config() -> Dict[str, Any]:
    """Get internal traffic timing configurations"""
    return {
        'startup_delay_min': int(os.getenv('INTERNAL_STARTUP_DELAY_MIN', '5')),
        'startup_delay_max': int(os.getenv('INTERNAL_STARTUP_DELAY_MAX', '15')),
        'jitter_factor': float(os.getenv('INTERNAL_JITTER_FACTOR', '0.1')),
        'burst_probability': float(os.getenv('INTERNAL_BURST_PROBABILITY', '0.05')),
        'burst_multiplier': float(os.getenv('INTERNAL_BURST_MULTIPLIER', '3.0'))
    }