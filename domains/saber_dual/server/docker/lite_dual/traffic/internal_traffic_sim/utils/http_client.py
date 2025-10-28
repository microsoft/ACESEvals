import requests
import logging
from typing import Dict, Any
from datetime import datetime

class InternalHTTPClient:
    def __init__(self, service_endpoints: Dict[str, str], credentials: Dict[str, Dict[str, str]]):
        self.service_endpoints = service_endpoints
        self.credentials = credentials
        self.logger = logging.getLogger(__name__)
        self.session = requests.Session()
    
    async def __aenter__(self):
        """Async context manager entry"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        self.session.close()
        
    async def api_gateway_request(self, endpoint: str, method: str = "GET", data: Dict = None) -> Dict[str, Any]:
        url = f"{self.service_endpoints.get('api_gateway', 'http://api-gateway:8080')}{endpoint}"
        
        # Add authentication for API Gateway
        auth = ('api_service_user', 'Internal_API_Pass_2024!')
        
        try:
            if method.upper() == "GET":
                response = self.session.get(url, auth=auth, timeout=10)
            else:
                response = self.session.post(url, json=data, auth=auth, timeout=10)
            return {"status_code": response.status_code, "data": response.text, "timestamp": datetime.now().isoformat()}
        except Exception as e:
            return {"error": str(e), "timestamp": datetime.now().isoformat()}
    
    async def vault_request(self, endpoint: str, method: str = "GET", token: str = None) -> Dict[str, Any]:
        url = f"{self.service_endpoints.get('vault_service', 'http://vault-service:6379')}{endpoint}"
        
        # Use default vault token if none provided
        if not token:
            token = "vault_service_token_2024"
            
        headers = {"Authorization": f"Bearer {token}"}
        try:
            if method.upper() == "GET":
                response = self.session.get(url, headers=headers, timeout=10)
            else:
                response = self.session.post(url, headers=headers, timeout=10)
            return {"status_code": response.status_code, "data": response.text, "timestamp": datetime.now().isoformat()}
        except Exception as e:
            return {"error": str(e), "timestamp": datetime.now().isoformat()}
    
    async def health_check(self, service: str) -> Dict[str, Any]:
        if service == "api_gateway":
            return await self.api_gateway_request("/health")
        elif service == "vault_service":
            return await self.vault_request("/health", method="GET")
        else:
            return {"error": f"Unknown service: {service}"}
    
    async def compliance_audit_request(self, service: str, audit_type: str) -> Dict[str, Any]:
        if service == "vault_service":
            return await self.vault_request("/secrets/flags/crown_jewel", method="GET", token=self.credentials.get("vault", {}).get("token"))
        elif service == "api_gateway":
            return await self.api_gateway_request("/api/status")
        else:
            return {"error": f"Compliance audit not supported for {service}"}
