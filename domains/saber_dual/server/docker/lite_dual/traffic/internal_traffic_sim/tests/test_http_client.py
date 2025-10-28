"""
Unit tests for Int        test_endpoints = {
            'api_gateway': 'http://api-gateway:8080',
            'vault_service': 'http://vault-service:6379',
            'database': 'mysql://database:3306',
            'siem_aggregator': 'http://siem-aggregator:8080'
        }TTPClient.

Tests verify that the HTTP client can be configured for internal service
communication and handles credentials correctly.
"""

import unittest
import sys
import os

# Add paths for internal traffic simulator components
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from utils.http_client import InternalHTTPClient


class TestInternalHTTPClient(unittest.TestCase):
    """Test InternalHTTPClient functionality"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.test_endpoints = {
            'api_gateway': 'http://api_gateway:8080',
            'vault_service': 'http://vault_service:6379',
            'database': 'mysql://database:3306',
            'siem_aggregator': 'http://siem_aggregator:8080'
        }
        
        self.test_credentials = {
            'api_gateway': {
                'token': 'test_api_token',
                'service_id': 'internal_traffic_sim'
            },
            'vault_service': {
                'token': 'test_vault_token',
                'role': 'internal_service'
            },
            'database': {
                'username': 'test_user',
                'password': 'test_pass',
                'database': 'saber_dual'
            },
            'siem_aggregator': {
                'api_key': 'test_siem_key'
            }
        }
        
        
    def test_http_client_creation(self):
        """Test that HTTP client can be created with proper configuration"""
        client = InternalHTTPClient(
            service_endpoints=self.test_endpoints,
            credentials=self.test_credentials
        )
        
        self.assertEqual(client.service_endpoints, self.test_endpoints)
        self.assertEqual(client.credentials, self.test_credentials)
        self.assertFalse(hasattr(client, 'event_logger'))
        
    def test_default_headers_configuration(self):
        """Test that default headers are properly configured"""
        client = InternalHTTPClient(
            service_endpoints=self.test_endpoints,
            credentials=self.test_credentials
        )
        
        expected_headers = {
            'User-Agent': 'SABER-Internal-Traffic-Simulator/1.0',
            'Content-Type': 'application/json',
            'X-Internal-Service': 'traffic_simulator'
        }
        
        self.assertEqual(client.default_headers, expected_headers)
        
    def test_timeout_configuration(self):
        """Test that timeout is properly configured"""
        client = InternalHTTPClient(
            service_endpoints=self.test_endpoints,
            credentials=self.test_credentials
        )
        
        # The timeout should be configured for aiohttp
        self.assertIsNotNone(client.timeout)
        
    def test_service_endpoints_access(self):
        """Test access to service endpoints"""
        client = InternalHTTPClient(
            service_endpoints=self.test_endpoints,
            credentials=self.test_credentials
        )
        
        self.assertEqual(client.service_endpoints['api_gateway'], 'http://api-gateway:8080')
        self.assertEqual(client.service_endpoints['vault_service'], 'http://vault-service:6379')
        self.assertEqual(client.service_endpoints['database'], 'mysql://database:3306')
        self.assertEqual(client.service_endpoints['siem_aggregator'], 'http://siem-aggregator:8080')
        
    def test_credentials_access(self):
        """Test access to service credentials"""
        client = InternalHTTPClient(
            service_endpoints=self.test_endpoints,
            credentials=self.test_credentials
        )
        
        # Test API Gateway credentials
        api_creds = client.credentials['api_gateway']
        self.assertEqual(api_creds['token'], 'test_api_token')
        self.assertEqual(api_creds['service_id'], 'internal_traffic_sim')
        
        # Test Vault credentials
        vault_creds = client.credentials['vault_service']
        self.assertEqual(vault_creds['token'], 'test_vault_token')
        self.assertEqual(vault_creds['role'], 'internal_service')
        
        # Test Database credentials
        db_creds = client.credentials['database']
        self.assertEqual(db_creds['username'], 'test_user')
        self.assertEqual(db_creds['password'], 'test_pass')
        self.assertEqual(db_creds['database'], 'saber_dual')
        
        # Test SIEM credentials
        siem_creds = client.credentials['siem_aggregator']
        self.assertEqual(siem_creds['api_key'], 'test_siem_key')
        
    def test_session_initialization(self):
        """Test that session is initially None"""
        client = InternalHTTPClient(
            service_endpoints=self.test_endpoints,
            credentials=self.test_credentials
        )
        
        # Session should be None until context manager is used
        self.assertIsNone(client.session)


class TestInternalHTTPClientAsyncContext(unittest.TestCase):
    """Test InternalHTTPClient async context manager functionality"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.test_endpoints = {
            'api_gateway': 'http://api-gateway:8080'
        }
        self.test_credentials = {
            'api_gateway': {'token': 'test_token'}
        }
    # No event logger; nothing to set up beyond endpoints/creds
        
    def test_async_context_manager_interface(self):
        """Test that HTTP client implements async context manager interface"""
        client = InternalHTTPClient(service_endpoints=self.test_endpoints, credentials=self.test_credentials)
        
        # Should have async context manager methods
        self.assertTrue(hasattr(client, '__aenter__'))
        self.assertTrue(hasattr(client, '__aexit__'))
        
        # __aenter__ should be a coroutine function
        import inspect
        self.assertTrue(inspect.iscoroutinefunction(client.__aenter__))


if __name__ == '__main__':
    unittest.main()