"""
Azure MCP Executors Registration Module

This module imports all Azure MCP executors to trigger their registration
with SABER's executor registry when the executors directory is scanned.

The executors themselves contain the register_executor() calls at module level.
"""

import sys
from pathlib import Path

# Add the executors directory to path to allow importing from azure_mcp subdirectory
_executors_dir = Path(__file__).parent
if str(_executors_dir) not in sys.path:
    sys.path.insert(0, str(_executors_dir))

# Import all Azure MCP executors to trigger their registration
from azure_mcp.monitor_executor import MonitorExecutor
from azure_mcp.sql_executor import SqlExecutor
from azure_mcp.keyvault_executor import KeyvaultExecutor
from azure_mcp.resourcehealth_executor import ResourcehealthExecutor
from azure_mcp.subscription_executor import SubscriptionExecutor

__all__ = [
    "MonitorExecutor",
    "SqlExecutor",
    "KeyvaultExecutor",
    "ResourcehealthExecutor",
    "SubscriptionExecutor",
]
