"""
External Traffic Simulator - HTTP Client

HTTP client that generates legitimate traffic to infrastructure services.
Infrastructure services will log these requests to SIEM - traffic simulator does not log directly.
"""

import aiohttp
import asyncio
import random
import logging
from typing import Dict, Any, Optional
from urllib.parse import urljoin


class ExternalHTTPClient:
    """HTTP client for external traffic simulation - generates HTTP requests only"""
    
    def __init__(self, webapp_url: str, timeout: int = 30, max_retries: int = 3):
        """Initialize HTTP client"""
        self.webapp_url = webapp_url.rstrip('/')
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.max_retries = max_retries
        self.session = None
        self.logger = logging.getLogger(__name__)
    
    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession(timeout=self.timeout)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()
    
    async def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make HTTP request with retry logic"""
        url = urljoin(self.webapp_url, endpoint)
        
        for attempt in range(self.max_retries + 1):
            try:
                async with self.session.request(method, url, **kwargs) as response:
                    content = await response.text()
                    
                    self.logger.debug(f"{method} {endpoint} -> {response.status}")
                    
                    return {
                        "status_code": response.status,
                        "content": content,
                        "headers": dict(response.headers),
                        "url": str(response.url),
                        "attempt": attempt + 1
                    }
                    
            except Exception as e:
                if attempt == self.max_retries:
                    self.logger.error(f"Request failed after {self.max_retries + 1} attempts: {e}")
                    return {
                        "status_code": 0,
                        "content": "",
                        "headers": {},
                        "url": url,
                        "error": str(e),
                        "attempt": attempt + 1
                    }
                
                await asyncio.sleep(random.uniform(1, 3))
    
    async def login(self, username: str, password: str, user_agent: str = None) -> Dict[str, Any]:
        """Perform login to webapp - webapp will log this to SIEM"""
        headers = {}
        if user_agent:
            headers['User-Agent'] = user_agent
        
        data = {
            'action': 'login',
            'username': username,
            'password': password
        }
        
        self.logger.info(f"Making login request for {username}")
        return await self._make_request('POST', '/', data=data, headers=headers)
    
    async def upload_file(self, filename: str, content: str, user_agent: str = None) -> Dict[str, Any]:
        """Upload file via webapp - webapp will log this to SIEM"""
        headers = {}
        if user_agent:
            headers['User-Agent'] = user_agent
        
        data = aiohttp.FormData()
        data.add_field('document', content, filename=filename)
        
        self.logger.info(f"Uploading file: {filename}")
        return await self._make_request('POST', '/api/upload', data=data, headers=headers)
    
    async def execute_shell_command(self, command: str, user_agent: str = None) -> Dict[str, Any]:
        """Execute shell command via webapp - webapp will log this to SIEM"""
        headers = {}
        if user_agent:
            headers['User-Agent'] = user_agent
        
        params = {'cmd': command}
        
        self.logger.info(f"Executing shell command: {command}")
        return await self._make_request('GET', '/shell/exec', params=params, headers=headers)
    
    async def access_vault_via_proxy(self, vault_endpoint: str, user_agent: str = None) -> Dict[str, Any]:
        """Access vault via webapp proxy - webapp will log this to SIEM"""
        headers = {}
        if user_agent:
            headers['User-Agent'] = user_agent
        
        proxy_endpoint = f'/proxy/vault{vault_endpoint}'
        
        self.logger.info(f"Accessing vault via proxy: {vault_endpoint}")
        return await self._make_request('GET', proxy_endpoint, headers=headers)
    
    async def get_admin_panel(self, user_agent: str = None) -> Dict[str, Any]:
        """Access admin panel - webapp will log this to SIEM"""
        headers = {}
        if user_agent:
            headers['User-Agent'] = user_agent
        
        self.logger.info("Accessing admin panel")
        return await self._make_request('GET', '/admin.php', headers=headers)
    
    async def get_page(self, endpoint: str, user_agent: str = None) -> Dict[str, Any]:
        """Generic page access method - webapp will log this to SIEM"""
        headers = {}
        if user_agent:
            headers['User-Agent'] = user_agent
        
        self.logger.info(f"Accessing page: {endpoint}")
        return await self._make_request('GET', endpoint, headers=headers)