"""
Azure MCP Compatible Executors for SABER Blue Team

These executors mirror the Azure MCP server's default namespace mode interface,
enabling agent transferability between SABER simulation and real Azure MCP.

See: domains/saber_dual/docs/AZURE_MCP_TOOL_REFERENCE.md
"""

from .monitor_executor import MonitorExecutor
from .sql_executor import SqlExecutor
from .keyvault_executor import KeyvaultExecutor
from .resourcehealth_executor import ResourcehealthExecutor
from .subscription_executor import SubscriptionExecutor

__all__ = [
    "MonitorExecutor",
    "SqlExecutor", 
    "KeyvaultExecutor",
    "ResourcehealthExecutor",
    "SubscriptionExecutor",
]
