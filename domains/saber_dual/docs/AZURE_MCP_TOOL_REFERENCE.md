# Azure MCP Tool Reference for SABER Blue Team

This document captures the **definitive tool names and interfaces** from the official Azure MCP server (`@azure/mcp@2.0.0-beta.10`).

When creating SABER executors that mirror the Azure MCP interface, use these exact tool names and parameter schemas to ensure agent transferability between SABER simulation and real Azure MCP.

> **Generated:** 2026-01-16  
> **Source:** `npx -y @azure/mcp@latest tools list --name-only`

---

## ⚠️ CRITICAL: Azure MCP Server Modes

The Azure MCP server supports **three operating modes** that control how many tools are exposed to connected agents:

```bash
azmcp server start --mode <mode>
```

| Mode | Tools Exposed | Description |
|------|---------------|-------------|
| `single` | **1 tool** | One "azure" mega-tool that routes to all services internally |
| `namespace` | **~40 tools** | One tool per service namespace (storage, keyvault, monitor, etc.) |
| `all` | **202 tools** | Every individual tool exposed separately |

### Default Mode: `namespace`

**By default, Azure MCP runs in `namespace` mode**, exposing approximately 40 namespace-level tools rather than all 202 individual tools. Each namespace tool acts as a router that dispatches to the underlying individual operations.

### Server Start Options

```bash
# Default - namespace mode (~40 tools)
azmcp server start

# Expose only specific namespaces
azmcp server start --namespace storage --namespace monitor --namespace sql

# Expose specific individual tools only
azmcp server start --tool monitor_workspace_log_query --tool sql_server_firewall-rule_create

# Expose all 202 individual tools (floods agent context!)
azmcp server start --mode all

# Read-only mode (excludes write operations)
azmcp server start --read-only
```

### SABER Mock Strategy

**For SABER, we will mock the Azure MCP server in its default `namespace` mode.** This means:

1. Agents connect and receive ~40 namespace-level tools (not 202)
2. Each namespace tool (e.g., `monitor`, `sql`, `keyvault`) routes to underlying operations
3. Tool calls include a `command` parameter specifying the sub-operation

This mirrors the real-world Azure MCP experience and keeps agent context manageable.

---

## Namespace-Level Tools (Default Mode)

These are the tools exposed in the default `namespace` mode:

| Namespace Tool | Description | Key Sub-Commands |
|----------------|-------------|------------------|
| `monitor` | Azure Monitor logs and metrics | `workspace log query`, `activitylog list`, `metrics query` |
| `sql` | Azure SQL databases and servers | `server firewall-rule create/delete/list`, `db list` |
| `keyvault` | Key Vault secrets, keys, certs | `secret get/list`, `key get/list` |
| `storage` | Storage accounts and blobs | `account get`, `blob get/upload` |
| `resourcehealth` | Resource availability status | `availability-status get/list` |
| `kusto` | Azure Data Explorer queries | `query`, `table list` |
| `subscription` | Subscription management | `list` |
| `group` | Resource group management | `list` |

### Namespace Tool Call Format

When using namespace mode, tool calls include a `command` parameter:

```json
{
  "name": "monitor",
  "arguments": {
    "command": "workspace log query",
    "parameters": {
      "workspace": "my-workspace",
      "query": "SecurityEvent | take 10",
      "subscription": "my-sub-id"
    }
  }
}
```

---

## Individual Tool Names (`--mode all`)

The following section documents all 202 individual tool names available when running with `--mode all`. These are also the sub-commands available within each namespace tool.

---

## Complete Tool Name List

The Azure MCP server exposes tools with names following the pattern: `{service}_{resource}_{action}`

### All Available Tools (202 tools)

```
acr_registry_list
acr_registry_repository_list
aks_cluster_get
aks_nodepool_get
appconfig_account_list
appconfig_kv_delete
appconfig_kv_get
appconfig_kv_lock_set
appconfig_kv_set
applens_resource_diagnose
applicationinsights_recommendation_list
appservice_database_add
azureterraformbestpractices_get
bicepschema_get
cloudarchitect_design
communication_email_send
communication_sms_send
confidentialledger_entries_append
confidentialledger_entries_get
cosmos_account_list
cosmos_database_container_item_query
cosmos_database_container_list
cosmos_database_list
datadog_monitoredresources_list
deploy_app_logs_get
deploy_architecture_diagram_generate
deploy_iac_rules_get
deploy_pipeline_guidance_get
deploy_plan_get
eventgrid_events_publish
eventgrid_subscription_list
eventgrid_topic_list
eventhubs_eventhub_consumergroup_delete
eventhubs_eventhub_consumergroup_get
eventhubs_eventhub_consumergroup_update
eventhubs_eventhub_delete
eventhubs_eventhub_get
eventhubs_eventhub_update
eventhubs_namespace_delete
eventhubs_namespace_get
eventhubs_namespace_update
extension_azqr
extension_cli_generate
extension_cli_install
foundry_agents_connect
foundry_agents_create
foundry_agents_evaluate
foundry_agents_get-sdk-sample
foundry_agents_list
foundry_agents_query-and-evaluate
foundry_knowledge_index_list
foundry_knowledge_index_schema
foundry_models_deploy
foundry_models_deployments_list
foundry_models_list
foundry_openai_chat-completions-create
foundry_openai_create-completion
foundry_openai_embeddings-create
foundry_openai_models-list
foundry_resource_get
foundry_threads_create
foundry_threads_get-messages
foundry_threads_list
functionapp_get
get_bestpractices_ai_app
get_bestpractices_get
grafana_list
group_list
keyvault_admin_settings_get
keyvault_certificate_create
keyvault_certificate_get
keyvault_certificate_import
keyvault_certificate_list
keyvault_key_create
keyvault_key_get
keyvault_key_list
keyvault_secret_create
keyvault_secret_get
keyvault_secret_list
kusto_cluster_get
kusto_cluster_list
kusto_database_list
kusto_query
kusto_sample
kusto_table_list
kusto_table_schema
loadtesting_testresource_create
loadtesting_testresource_list
loadtesting_testrun_create
loadtesting_testrun_get
loadtesting_testrun_list
loadtesting_testrun_update
loadtesting_test_create
loadtesting_test_get
managedlustre_fs_blob_autoexport_cancel
managedlustre_fs_blob_autoexport_create
managedlustre_fs_blob_autoexport_delete
managedlustre_fs_blob_autoexport_get
managedlustre_fs_blob_autoimport_cancel
managedlustre_fs_blob_autoimport_create
managedlustre_fs_blob_autoimport_delete
managedlustre_fs_blob_autoimport_get
managedlustre_fs_create
managedlustre_fs_list
managedlustre_fs_sku_get
managedlustre_fs_subnetsize_ask
managedlustre_fs_subnetsize_validate
managedlustre_fs_update
marketplace_product_get
marketplace_product_list
monitor_activitylog_list
monitor_healthmodels_entity_get
monitor_metrics_definitions
monitor_metrics_query
monitor_resource_log_query
monitor_table_list
monitor_table_type_list
monitor_webtests_create
monitor_webtests_get
monitor_webtests_list
monitor_webtests_update
monitor_workspace_list
monitor_workspace_log_query
mysql_database_list
mysql_database_query
mysql_server_config_get
mysql_server_list
mysql_server_param_get
mysql_server_param_set
mysql_table_list
mysql_table_schema_get
postgres_database_list
postgres_database_query
postgres_server_config_get
postgres_server_list
postgres_server_param_get
postgres_server_param_set
postgres_table_list
postgres_table_schema_get
quota_region_availability_list
quota_usage_check
redis_create
redis_list
resourcehealth_availability-status_get
resourcehealth_availability-status_list
resourcehealth_health-events_list
role_assignment_list
search_index_get
search_index_query
search_knowledge_base_get
search_knowledge_base_retrieve
search_knowledge_source_get
search_service_list
servicebus_queue_details
servicebus_topic_details
servicebus_topic_subscription_details
signalr_runtime_get
speech_stt_recognize
speech_tts_synthesize
sql_db_create
sql_db_delete
sql_db_list
sql_db_rename
sql_db_show
sql_db_update
sql_elastic-pool_list
sql_server_create
sql_server_delete
sql_server_entra-admin_list
sql_server_firewall-rule_create
sql_server_firewall-rule_delete
sql_server_firewall-rule_list
sql_server_list
sql_server_show
storagesync_cloudendpoint_create
storagesync_cloudendpoint_delete
storagesync_cloudendpoint_get
storagesync_cloudendpoint_triggerchangedetection
storagesync_registeredserver_get
storagesync_registeredserver_unregister
storagesync_registeredserver_update
storagesync_serverendpoint_create
storagesync_serverendpoint_delete
storagesync_serverendpoint_get
storagesync_serverendpoint_update
storagesync_service_create
storagesync_service_delete
storagesync_service_get
storagesync_service_update
storagesync_syncgroup_create
storagesync_syncgroup_delete
storagesync_syncgroup_get
storage_account_create
storage_account_get
storage_blob_container_create
storage_blob_container_get
storage_blob_get
storage_blob_upload
storage_table_list
subscription_list
virtualdesktop_hostpool_host_list
virtualdesktop_hostpool_host_user-list
virtualdesktop_hostpool_list
workbooks_create
workbooks_delete
workbooks_list
workbooks_show
workbooks_update
```

---

## Blue Team Relevant Tools (Detailed)

These are the tools most relevant to the React2Shell blue team defensive scenario.

### SIEM / Log Analytics Tools

#### `monitor_workspace_log_query`
**Command:** `monitor workspace log query`  
**Description:** Query logs in an Azure Monitor Log Analytics workspace using Kusto Query Language (KQL).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `--subscription` | string | No | Azure subscription ID or display name |
| `--workspace` | string | **Yes** | Log Analytics workspace name |
| `--query` | string | **Yes** | KQL query to execute |
| `--hours` | string | No | Hours of data to query (default: 24) |
| `--limit` | string | No | Max rows to return |

**SABER Executor Name:** `monitor_workspace_log_query`

---

#### `monitor_activitylog_list`
**Command:** `monitor activitylog list`  
**Description:** Lists activity logs for the specified Azure resource over the given prior number of hours.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `--subscription` | string | No | Azure subscription ID or display name |
| `--resource-group` | string | No | Resource group name |
| `--resource-name` | string | **Yes** | The Azure resource name |
| `--resource-type` | string | No | Resource type (e.g., 'Microsoft.Storage/storageAccounts') |
| `--hours` | string | No | Hours prior to query |
| `--event-level` | string | No | Log level: Critical, Error, Informational, Warning |
| `--top` | string | No | Max logs to retrieve |

**SABER Executor Name:** `monitor_activitylog_list`

---

#### `monitor_table_list`
**Command:** `monitor table list`  
**Description:** List available tables in a Log Analytics workspace.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `--subscription` | string | No | Azure subscription ID |
| `--workspace` | string | **Yes** | Log Analytics workspace name |

**SABER Executor Name:** `monitor_table_list`

---

### SQL Server Tools (Firewall Management)

#### `sql_server_firewall-rule_create`
**Command:** `sql server firewall-rule create`  
**Description:** Create a firewall rule for an Azure SQL server.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `--subscription` | string | No | Azure subscription ID |
| `--resource-group` | string | **Yes** | Resource group name |
| `--server` | string | **Yes** | SQL server name |
| `--rule-name` | string | **Yes** | Firewall rule name |
| `--start-ip` | string | **Yes** | Start IP address |
| `--end-ip` | string | **Yes** | End IP address |

**SABER Executor Name:** `sql_server_firewall-rule_create`

---

#### `sql_server_firewall-rule_delete`
**Command:** `sql server firewall-rule delete`  
**Description:** Delete a firewall rule from an Azure SQL server.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `--subscription` | string | No | Azure subscription ID |
| `--resource-group` | string | **Yes** | Resource group name |
| `--server` | string | **Yes** | SQL server name |
| `--rule-name` | string | **Yes** | Firewall rule name to delete |

**SABER Executor Name:** `sql_server_firewall-rule_delete`

---

#### `sql_server_firewall-rule_list`
**Command:** `sql server firewall-rule list`  
**Description:** List firewall rules for an Azure SQL server.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `--subscription` | string | No | Azure subscription ID |
| `--resource-group` | string | **Yes** | Resource group name |
| `--server` | string | **Yes** | SQL server name |

**SABER Executor Name:** `sql_server_firewall-rule_list`

---

### Resource Health Tools

#### `resourcehealth_availability-status_get`
**Command:** `resourcehealth availability-status get`  
**Description:** Get the current availability status of a specific Azure resource.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `--subscription` | string | No | Azure subscription ID |
| `--resource-group` | string | **Yes** | Resource group name |
| `--resource-type` | string | **Yes** | Resource type |
| `--resource-name` | string | **Yes** | Resource name |

**SABER Executor Name:** `resourcehealth_availability-status_get`

---

#### `resourcehealth_availability-status_list`
**Command:** `resourcehealth availability-status list`  
**Description:** List availability statuses for resources in a subscription or resource group.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `--subscription` | string | No | Azure subscription ID |
| `--resource-group` | string | No | Filter by resource group |

**SABER Executor Name:** `resourcehealth_availability-status_list`

---

#### `resourcehealth_health-events_list`
**Command:** `resourcehealth health-events list`  
**Description:** List health events for a subscription or resource.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `--subscription` | string | No | Azure subscription ID |

**SABER Executor Name:** `resourcehealth_health-events_list`

---

### Key Vault Tools

#### `keyvault_secret_list`
**Command:** `keyvault secret list`  
**Description:** List/enumerate all secrets in a Key Vault.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `--subscription` | string | No | Azure subscription ID |
| `--vault` | string | **Yes** | Key Vault name |

**SABER Executor Name:** `keyvault_secret_list`

---

#### `keyvault_secret_get`
**Command:** `keyvault secret get`  
**Description:** Get/retrieve/show details for a single secret in an Azure Key Vault.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `--subscription` | string | No | Azure subscription ID |
| `--vault` | string | **Yes** | Key Vault name |
| `--secret` | string | **Yes** | Secret name |

**SABER Executor Name:** `keyvault_secret_get`

---

### Storage Tools

#### `storage_account_get`
**Command:** `storage account get`  
**Description:** Get details of a storage account.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `--subscription` | string | No | Azure subscription ID |
| `--resource-group` | string | **Yes** | Resource group name |
| `--account` | string | **Yes** | Storage account name |

**SABER Executor Name:** `storage_account_get`

---

#### `storage_blob_get`
**Command:** `storage blob get`  
**Description:** Get/download a blob from a storage container.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `--subscription` | string | No | Azure subscription ID |
| `--account` | string | **Yes** | Storage account name |
| `--container` | string | **Yes** | Container name |
| `--blob` | string | **Yes** | Blob name |

**SABER Executor Name:** `storage_blob_get`

---

### Subscription Tools

#### `subscription_list`
**Command:** `subscription list`  
**Description:** List Azure subscriptions available to the authenticated user.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `--tenant` | string | No | Entra ID tenant |

**SABER Executor Name:** `subscription_list`

---

#### `group_list`
**Command:** `group list`  
**Description:** List resource groups in a subscription.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `--subscription` | string | No | Azure subscription ID |

**SABER Executor Name:** `group_list`

---

### Kusto (Azure Data Explorer) Tools

#### `kusto_query`
**Command:** `kusto query`  
**Description:** Execute a KQL query against an Azure Data Explorer cluster.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `--subscription` | string | No | Azure subscription ID |
| `--cluster` | string | **Yes** | Kusto cluster name |
| `--database` | string | **Yes** | Database name |
| `--query` | string | **Yes** | KQL query |

**SABER Executor Name:** `kusto_query`

---

## Common Parameters

All Azure MCP tools support these common optional parameters:

| Parameter | Description |
|-----------|-------------|
| `--tenant` | Microsoft Entra ID tenant ID or name |
| `--auth-method` | Authentication method: 'credential', 'key', or 'connectionString' |
| `--subscription` | Azure subscription ID or display name |
| `--retry-delay` | Initial delay between retry attempts (seconds) |
| `--retry-max-delay` | Maximum delay between retries (seconds) |
| `--retry-max-retries` | Maximum retry attempts |
| `--retry-mode` | Retry strategy: 'fixed' or 'exponential' |
| `--retry-network-timeout` | Network operation timeout (seconds) |

---

## SABER Executor Strategy (Namespace Mode)

To mirror the default Azure MCP experience, SABER will expose **namespace-level executors** that route to underlying mock services.

### Namespace Executor Architecture

```
Agent sees:     monitor, sql, keyvault, storage, resourcehealth, subscription, group
                   │
                   ▼
SABER Executor: MonitorNamespaceExecutor
                   │
                   ├── command: "workspace log query" → Mock Sentinel API
                   ├── command: "activitylog list"   → Mock Activity Log API  
                   └── command: "table list"         → Mock Table List API
```

### Example Namespace Executor

```python
class MonitorNamespaceExecutor(BaseExecutor):
    """
    Azure MCP Compatible: monitor (namespace mode)
    Routes to: workspace log query, activitylog list, metrics query, etc.
    """
    
    _executor_metadata = {
        "name": "monitor",
        "description": "Azure Monitor operations - Commands for querying and analyzing Azure Monitor logs and metrics."
    }
    
    _parameters = {
        "command": {
            "type": "string",
            "description": "The monitor sub-command to execute (e.g., 'workspace log query')",
            "required": True
        },
        "parameters": {
            "type": "object",
            "description": "Parameters for the sub-command",
            "required": True
        }
    }
    
    async def execute(self, command: str, parameters: dict, **kwargs):
        if command == "workspace log query":
            return await self._query_logs(parameters)
        elif command == "activitylog list":
            return await self._list_activity_logs(parameters)
        # ... route to other sub-commands
```

### Blue Team Namespace Executors Needed

For the React2Shell scenario, implement these namespace executors:

| Executor | Mock Backend | Key Sub-Commands |
|----------|--------------|------------------|
| `monitor` | Mock Sentinel/Log Analytics | `workspace log query`, `activitylog list` |
| `sql` | Mock SQL Management API | `server firewall-rule create/delete/list` |
| `resourcehealth` | Mock Resource Health API | `availability-status get/list` |
| `keyvault` | Mock Key Vault API | `secret list/get` |
| `subscription` | Static config | `list` |
| `group` | Static config | `list` |

---

## Individual Tool Reference (`--mode all`)

The following sections document individual tool schemas for reference. These are the sub-commands available within each namespace.

---

## Blue Team Relevant Tools (Detailed)

These are the individual tools (sub-commands) most relevant to the React2Shell blue team defensive scenario.

### SIEM / Log Analytics Tools

#### `monitor workspace log query`
**Tool Name (--mode all):** `monitor_workspace_log_query`  
**Description:** Query logs in an Azure Monitor Log Analytics workspace using Kusto Query Language (KQL).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `subscription` | string | No | Azure subscription ID or display name |
| `workspace` | string | **Yes** | Log Analytics workspace name |
| `query` | string | **Yes** | KQL query to execute |
| `hours` | string | No | Hours of data to query (default: 24) |
| `limit` | string | No | Max rows to return |

---

#### `monitor activitylog list`
**Tool Name (--mode all):** `monitor_activitylog_list`  
**Description:** Lists activity logs for the specified Azure resource over the given prior number of hours.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `subscription` | string | No | Azure subscription ID or display name |
| `resource-group` | string | No | Resource group name |
| `resource-name` | string | **Yes** | The Azure resource name |
| `resource-type` | string | No | Resource type (e.g., 'Microsoft.Storage/storageAccounts') |
| `hours` | string | No | Hours prior to query |
| `event-level` | string | No | Log level: Critical, Error, Informational, Warning |
| `top` | string | No | Max logs to retrieve |

---

### SQL Server Tools (Firewall Management)

#### `sql server firewall-rule create`
**Tool Name (--mode all):** `sql_server_firewall-rule_create`  
**Description:** Create a firewall rule for an Azure SQL server.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `subscription` | string | No | Azure subscription ID |
| `resource-group` | string | **Yes** | Resource group name |
| `server` | string | **Yes** | SQL server name |
| `rule-name` | string | **Yes** | Firewall rule name |
| `start-ip` | string | **Yes** | Start IP address |
| `end-ip` | string | **Yes** | End IP address |

---

#### `sql server firewall-rule delete`
**Tool Name (--mode all):** `sql_server_firewall-rule_delete`  
**Description:** Delete a firewall rule from an Azure SQL server.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `subscription` | string | No | Azure subscription ID |
| `resource-group` | string | **Yes** | Resource group name |
| `server` | string | **Yes** | SQL server name |
| `rule-name` | string | **Yes** | Firewall rule name to delete |

---

#### `sql server firewall-rule list`
**Tool Name (--mode all):** `sql_server_firewall-rule_list`  
**Description:** List firewall rules for an Azure SQL server.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `subscription` | string | No | Azure subscription ID |
| `resource-group` | string | **Yes** | Resource group name |
| `server` | string | **Yes** | SQL server name |

---

### Resource Health Tools

#### `resourcehealth availability-status get`
**Tool Name (--mode all):** `resourcehealth_availability-status_get`  
**Description:** Get the current availability status of a specific Azure resource.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `subscription` | string | No | Azure subscription ID |
| `resource-group` | string | **Yes** | Resource group name |
| `resource-type` | string | **Yes** | Resource type |
| `resource-name` | string | **Yes** | Resource name |

---

#### `resourcehealth availability-status list`
**Tool Name (--mode all):** `resourcehealth_availability-status_list`  
**Description:** List availability statuses for resources in a subscription or resource group.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `subscription` | string | No | Azure subscription ID |
| `resource-group` | string | No | Filter by resource group |

---

### Key Vault Tools

#### `keyvault secret list`
**Tool Name (--mode all):** `keyvault_secret_list`  
**Description:** List/enumerate all secrets in a Key Vault.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `subscription` | string | No | Azure subscription ID |
| `vault` | string | **Yes** | Key Vault name |

---

#### `keyvault secret get`
**Tool Name (--mode all):** `keyvault_secret_get`  
**Description:** Get/retrieve/show details for a single secret in an Azure Key Vault.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `subscription` | string | No | Azure subscription ID |
| `vault` | string | **Yes** | Key Vault name |
| `secret` | string | **Yes** | Secret name |

---

### Infrastructure Tools

#### `subscription list`
**Tool Name (--mode all):** `subscription_list`  
**Description:** List Azure subscriptions available to the authenticated user.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `tenant` | string | No | Entra ID tenant |

---

#### `group list`
**Tool Name (--mode all):** `group_list`  
**Description:** List resource groups in a subscription.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `subscription` | string | No | Azure subscription ID |

---

## Common Parameters

All Azure MCP tools support these common optional parameters:

| Parameter | Description |
|-----------|-------------|
| `tenant` | Microsoft Entra ID tenant ID or name |
| `auth-method` | Authentication method: 'credential', 'key', or 'connectionString' |
| `subscription` | Azure subscription ID or display name |
| `retry-delay` | Initial delay between retry attempts (seconds) |
| `retry-max-delay` | Maximum delay between retries (seconds) |
| `retry-max-retries` | Maximum retry attempts |
| `retry-mode` | Retry strategy: 'fixed' or 'exponential' |
| `retry-network-timeout` | Network operation timeout (seconds) |

---

## Full JSON Reference

The complete Azure MCP tool definitions can be regenerated with:

```bash
npx -y @azure/mcp@latest tools list > azure_mcp_tools_full.json
npx -y @azure/mcp@latest tools list --name-only > azure_mcp_tool_names.json
```
