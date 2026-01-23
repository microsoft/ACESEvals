# Azure Sentinel SIEM Service with Kusto Emulator
# Full-featured SIEM using real Azure Data Explorer (Kusto) engine
# Aggregates audit logs from all Azure mock services

from flask import Flask, request, jsonify
import os
import json
import time
from datetime import datetime, timedelta
from threading import Thread, Lock
import requests
import uuid
import yaml

app = Flask(__name__)

# Schema configuration
SCHEMA_PATH = os.environ.get('SCHEMA_PATH', '/app/schemas/azure_log_schemas.yaml')

# Data stores (kept for backwards compatibility and analytics rules)
ANALYTICS_RULES = []
RULES_LOCK = Lock()
INCIDENTS = []
INCIDENTS_LOCK = Lock()
QUERY_LOGS = []
QUERY_LOCK = Lock()

# Kusto configuration
KUSTO_URL = os.environ.get('KUSTO_URL', 'http://kusto-emulator:8080')
KUSTO_DATABASE = 'NetDefaultDB'  # Use Kusto Emulator's default database

# Services to poll for logs
SERVICES = {
    'keyvault': os.environ.get('KEYVAULT_URL', 'https://keyvault:443'),
    'azure_ad': os.environ.get('AZURE_AD_URL', 'http://azure-ad:8080'),
    'imds': os.environ.get('IMDS_URL', 'http://imds:80'),
    'arm': os.environ.get('ARM_URL', 'https://arm-api:443'),
    'functions': os.environ.get('FUNCTIONS_URL', 'http://azure-functions:7071'),
    'eventgrid': os.environ.get('EVENTGRID_URL', 'http://eventgrid:4000'),
    'gateway': os.environ.get('GATEWAY_URL', 'http://gateway:8080'),
    'sql_wrapper': os.environ.get('SQL_WRAPPER_URL', 'http://azure-sql-wrapper:8083'),
    'domain_controller': os.environ.get('DOMAIN_CONTROLLER_URL', 'http://domain-controller:8080'),
    'front_door': os.environ.get('FRONT_DOOR_URL', 'http://front-door:8080'),
    # AKS Attack Chain services
    'aks_pod': os.environ.get('AKS_POD_URL', 'http://aks-pod:8080'),
    'kubernetes_api': os.environ.get('KUBERNETES_API_URL', 'https://kubernetes-api:443'),
    'exchange_online': os.environ.get('EXCHANGE_URL', 'https://exchange-online:443'),
}

OUTPUT_FORMAT = os.environ.get('OUTPUT_FORMAT', 'azure_monitor')

# ============================================
# KUSTO CLIENT
# ============================================

class KustoClient:
    """Client for Kusto Emulator REST API"""

    def __init__(self, endpoint, database):
        self.endpoint = endpoint.rstrip('/')
        self.database = database
        self.mgmt_url = f"{self.endpoint}/v1/rest/mgmt"
        self.query_url = f"{self.endpoint}/v1/rest/query"

    def execute_mgmt_command(self, command):
        """Execute a Kusto management command"""
        payload = {
            "db": self.database,
            "csl": command
        }
        try:
            resp = requests.post(self.mgmt_url, json=payload, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"[KUSTO] Management command error: {e}", flush=True)
            raise

    def execute_query(self, query):
        """Execute a KQL query"""
        payload = {
            "db": self.database,
            "csl": query
        }
        try:
            resp = requests.post(self.query_url, json=payload, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"[KUSTO] Query error: {e}", flush=True)
            raise

    def ingest_json(self, table_name, records):
        """Ingest JSON records into a table using .ingest inline"""
        if not records:
            return

        # Format records as JSON lines (one JSON object per line)
        json_data = '\n'.join(json.dumps(r) for r in records)

        # Use .ingest inline command with multijson format for proper JSON parsing
        command = f".ingest inline into table {table_name} with (format='multijson') <|\n{json_data}"

        try:
            self.execute_mgmt_command(command)
        except Exception as e:
            print(f"[KUSTO] Ingest error for {table_name}: {e}", flush=True)


# Global Kusto client
kusto = KustoClient(KUSTO_URL, KUSTO_DATABASE)

# ============================================
# KUSTO INITIALIZATION
# ============================================

# Schema key to Kusto table name mapping
SCHEMA_TO_TABLE = {
    'key_vault_audit_event': 'AzureKeyVaultAuditLogs',
    'storage_blob_log': 'StorageBlobLogs',
    'sign_in_log': 'AADSignInLogs',
    'activity_log': 'AzureActivity',
    'imds_access_log': 'InstanceMetadata',
    'function_app_log': 'FunctionAppLogs',
    'event_grid_log': 'EventGridPublishLogs',
    'app_service_http_logs': 'AppServiceHTTPLogs',
    'la_query_logs': 'LAQueryLogs',
    'front_door_access_log': 'FrontDoorAccessLog',
    'front_door_waf_log': 'FrontDoorWebApplicationFirewallLog',
    # AKS Attack Chain tables
    'kube_audit_log': 'KubeAuditLogs',
    'aks_pod_http_log': 'ContainerLogs',
    'exchange_audit_log': 'OfficeActivity',
}

# Kusto reserved keywords that need escaping with brackets
KUSTO_RESERVED = {'time', 'timestamp', 'level', 'type', 'source'}


def load_schemas():
    """Load Azure log schemas from YAML file."""
    try:
        with open(SCHEMA_PATH, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"[KUSTO] Warning: Could not load schemas from {SCHEMA_PATH}: {e}", flush=True)
        return {}


def map_field_type(field_type):
    """Map schema field type to Kusto type.

    Note: Kusto Emulator has limited type support, using string for datetime.
    """
    type_map = {
        'datetime': 'string',  # Kusto Emulator doesn't support datetime
        'string': 'string',
        'integer': 'long',
        'int': 'long',
        'guid': 'string',
        'object': 'dynamic',
        'array': 'dynamic',
        'float': 'real',
        'boolean': 'bool',
    }
    return type_map.get(field_type, 'string')


def generate_table_command(table_name, schema):
    """Generate Kusto CREATE TABLE command from schema definition."""
    fields = schema.get('fields', [])
    if not fields:
        # Fallback to generic schema
        return f'.create table {table_name} (["time"]: string, category: string, operationName: string, resultType: string, properties: dynamic, source: string, collectedAt: string)'

    columns = []
    seen_columns = set()

    for field in fields:
        name = field.get('name', '')
        field_type = field.get('type', 'string')

        # Skip nested fields (e.g., identity.claim, properties.clientInfo)
        # These will be captured in their parent dynamic column
        if '.' in name:
            parent = name.split('.')[0]
            if parent not in seen_columns:
                col_name = f'["{parent}"]' if parent in KUSTO_RESERVED else parent
                columns.append(f'{col_name}: dynamic')
                seen_columns.add(parent)
            continue

        # Escape reserved keywords
        col_name = f'["{name}"]' if name in KUSTO_RESERVED else name
        kusto_type = map_field_type(field_type)

        if name not in seen_columns:
            columns.append(f'{col_name}: {kusto_type}')
            seen_columns.add(name)

    # Always add source and collectedAt for sentinel metadata
    if 'source' not in seen_columns:
        columns.append('source: string')
    if 'collectedAt' not in seen_columns:
        columns.append('collectedAt: string')

    return f'.create table {table_name} ({", ".join(columns)})'


def initialize_kusto():
    """Initialize Kusto database and tables from schema definitions."""
    print("[KUSTO] Initializing Kusto Emulator", flush=True)

    # Wait for Kusto to be ready
    max_retries = 30
    for i in range(max_retries):
        try:
            requests.get(f"{KUSTO_URL}/v1/rest/mgmt", timeout=5)
            print("[KUSTO] Kusto Emulator is ready", flush=True)
            break
        except Exception:
            if i == max_retries - 1:
                print("[KUSTO] ERROR: Kusto Emulator not available after 30 retries", flush=True)
                return False
            time.sleep(1)

    # Load schemas from YAML
    schemas = load_schemas()
    tables_to_create = {}

    # Generate table commands from schemas
    for schema_key, table_name in SCHEMA_TO_TABLE.items():
        if schema_key in schemas:
            tables_to_create[table_name] = generate_table_command(table_name, schemas[schema_key])
            print(f"[KUSTO] Generated schema for {table_name} from {schema_key}", flush=True)
        else:
            # Fallback to generic schema
            tables_to_create[table_name] = f'.create table {table_name} (["time"]: string, category: string, operationName: string, resultType: string, properties: dynamic, source: string, collectedAt: string)'

    # Add tables not in schema file (generic schema)
    extra_tables = ['SecurityEvent', 'SysmonEvent', 'SQLSecurityAuditEvents',
                    'NetworkSecurityGroupFlowEvent', 'ManagedIdentityToken', 'AllLogs',
                    # AKS Attack Chain tables
                    'KubeAuditLogs', 'ContainerLogs', 'OfficeActivity']
    for table_name in extra_tables:
        if table_name not in tables_to_create:
            tables_to_create[table_name] = f'.create table {table_name} (["time"]: string, category: string, operationName: string, resultType: string, properties: dynamic, source: string, collectedAt: string)'

    tables_created = 0

    for table_name, create_command in tables_to_create.items():
        try:
            print(f"[KUSTO] Creating {table_name}: {create_command[:80]}...", flush=True)
            kusto.execute_mgmt_command(create_command)
            print(f"[KUSTO] {table_name} table created successfully", flush=True)
            tables_created += 1
        except Exception as e:
            # Table might already exist
            if "already exists" in str(e) or "400" in str(e):
                print(f"[KUSTO] {table_name} table may already exist, continuing", flush=True)
                tables_created += 1
            else:
                print(f"[KUSTO] Error creating {table_name} table: {e}", flush=True)

        time.sleep(0.2)

    if tables_created >= 1:
        print(f"[KUSTO] Kusto initialization complete ({tables_created}/{len(tables_to_create)} tables ready)", flush=True)
        return True
    else:
        print("[KUSTO] ERROR: Failed to create any tables", flush=True)
        return False

# ============================================
# LOG COLLECTION
# ============================================

def get_table_name_for_category(category: str) -> str:
    """Map log category to Kusto table name"""
    # Direct mapping for known categories
    category_to_table = {
        'SecurityEvent': 'SecurityEvent',
        'SysmonEvent': 'SysmonEvent',
        'SQLSecurityAuditEvents': 'SQLSecurityAuditEvents',
        'NetworkSecurityGroupFlowEvent': 'NetworkSecurityGroupFlowEvent',
        'FunctionAppLogs': 'FunctionAppLogs',
        'InstanceMetadata': 'InstanceMetadata',
        'ManagedIdentityToken': 'ManagedIdentityToken',
        'AADSignInLogs': 'AADSignInLogs',
        'SignInLogs': 'AADSignInLogs',  # Alias
        'AzureKeyVaultAuditLogs': 'AzureKeyVaultAuditLogs',
        'KeyVaultAudit': 'AzureKeyVaultAuditLogs',  # Alias
        'StorageBlobLogs': 'StorageBlobLogs',
        'BlobStorage': 'StorageBlobLogs',  # Alias
        'AzureActivity': 'AzureActivity',
        'Administrative': 'AzureActivity',  # Alias
        'EventGridPublishLogs': 'EventGridPublishLogs',
        'EventGrid': 'EventGridPublishLogs',  # Alias
        'AppServiceHTTPLogs': 'AppServiceHTTPLogs',
        'AppServiceLogs': 'AppServiceHTTPLogs',  # Alias
        'FrontDoorAccessLog': 'FrontDoorAccessLog',
        'FrontDoorWebApplicationFirewallLog': 'FrontDoorWebApplicationFirewallLog',
        'FrontDoorWAF': 'FrontDoorWebApplicationFirewallLog',  # Alias
        'LAQueryLogs': 'LAQueryLogs',
        # AKS Attack Chain categories
        'KubeAuditLogs': 'KubeAuditLogs',
        'KubernetesAudit': 'KubeAuditLogs',  # Alias
        'ContainerLogs': 'ContainerLogs',
        'AKSPodLogs': 'ContainerLogs',  # Alias
        'OfficeActivity': 'OfficeActivity',
        'ExchangeAudit': 'OfficeActivity',  # Alias
        'MailItemsAccessed': 'OfficeActivity',  # Alias
    }

    return category_to_table.get(category, 'AllLogs')  # Default to AllLogs for unknown

def poll_service_logs():
    """Background thread to poll all services for logs"""
    try:
        print("[SENTINEL] Starting log collection thread", flush=True)
        while True:
            batch = []

            for service_name, service_url in SERVICES.items():
                try:
                    response = requests.get(
                        f"{service_url}/audit/logs",
                        timeout=5,
                        verify=False  # For self-signed certs on ARM
                    )
                    if response.status_code == 200:
                        data = response.json()
                        # Handle both list format (gateway) and {'value': [...]} format (other services)
                        if isinstance(data, list):
                            new_logs = data
                        else:
                            new_logs = data.get('value', [])

                        for log in new_logs:
                            # Add source metadata
                            log['source'] = service_name
                            log['collectedAt'] = datetime.utcnow().isoformat() + 'Z'

                            # Ensure time field exists
                            if 'time' not in log and 'timestamp' in log:
                                log['time'] = log['timestamp']

                            batch.append(log)

                except Exception as e:
                    print(f"[SENTINEL] Error polling {service_name}: {e}", flush=True)

            # Categorize logs by table and ingest
            if batch:
                # Group logs by target table
                categorized_logs = {}
                for log in batch:
                    category = log.get('category', 'Unknown')
                    table_name = get_table_name_for_category(category)

                    if table_name not in categorized_logs:
                        categorized_logs[table_name] = []
                    categorized_logs[table_name].append(log)

                # Ingest into separate tables
                for table_name, logs in categorized_logs.items():
                    try:
                        kusto.ingest_json(table_name, logs)
                        print(f"[SENTINEL] Ingested {len(logs)} logs into {table_name}", flush=True)
                    except Exception as e:
                        print(f"[SENTINEL] Error ingesting into {table_name}: {e}", flush=True)

                # Also ingest ALL logs into AllLogs for backwards compatibility
                try:
                    kusto.ingest_json('AllLogs', batch)
                except Exception as e:
                    print(f"[SENTINEL] Error ingesting into AllLogs: {e}", flush=True)

            time.sleep(5)  # Poll every 5 seconds

    except Exception as e:
        print(f"[SENTINEL] FATAL ERROR in collection thread: {e}", flush=True)
        import traceback
        traceback.print_exc()

# ============================================
# QUERY ENDPOINT
# ============================================

@app.route('/query', methods=['POST'])
def query_workspace():
    """KQL Query endpoint (Azure Sentinel compatible)"""
    data = request.get_json() or {}
    query_text = data.get('query', '')
    timespan = data.get('timespan', 'PT24H')

    start_time = datetime.utcnow()

    try:
        # Execute query against Kusto
        result = kusto.execute_query(query_text)

        # Extract primary result table
        tables = result.get('Tables', [])
        if tables:
            primary_table = tables[0]
            columns = [{'name': c['ColumnName'], 'type': c['DataType']}
                      for c in primary_table.get('Columns', [])]
            rows = primary_table.get('Rows', [])
        else:
            columns = []
            rows = []

        status = 'Success'
        error = None

    except Exception as e:
        columns = []
        rows = []
        status = 'Failed'
        error = str(e)

    # Log query execution
    query_log = {
        'time': start_time.isoformat() + 'Z',
        'category': 'LAQueryLogs',
        'operationName': 'Query',
        'resultType': status,
        'properties': {
            'queryText': query_text,
            'timespan': timespan,
            'resultCount': len(rows),
            'durationMs': int((datetime.utcnow() - start_time).total_seconds() * 1000),
            'errorMessage': error
        }
    }

    with QUERY_LOCK:
        QUERY_LOGS.append(query_log)

    # Also ingest query log into Kusto
    try:
        kusto.ingest_json('LAQueryLogs', [query_log])
    except Exception:
        pass

    return jsonify({
        'tables': [
            {
                'name': 'PrimaryResult',
                'columns': columns,
                'rows': rows
            }
        ],
        'status': status
    })

@app.route('/workspace/tables', methods=['GET'])
def get_workspace_tables():
    """List available workspace tables"""
    # Get tables from Kusto
    try:
        result = kusto.execute_query(".show tables")
        tables = result.get('Tables', [{}])[0].get('Rows', [])
        table_names = [row[0] for row in tables]
    except Exception:
        table_names = ['AllLogs', 'LAQueryLogs']

    return jsonify({'value': table_names})

# ============================================
# LOGS ENDPOINT (for backwards compatibility)
# ============================================

@app.route('/logs', methods=['GET'])
def get_all_logs():
    """Get all collected logs (queries Kusto)"""
    limit = request.args.get('limit', 1000, type=int)

    try:
        # Query recent logs from Kusto
        query = f"AllLogs | take {limit}"
        result = kusto.execute_query(query)

        tables = result.get('Tables', [])
        if tables:
            rows = tables[0].get('Rows', [])
            columns = tables[0].get('Columns', [])

            # Convert rows to dict format
            logs = []
            for row in rows:
                log = {}
                for i, col in enumerate(columns):
                    log[col['ColumnName']] = row[i]
                logs.append(log)
        else:
            logs = []

    except Exception as e:
        print(f"[LOGS] Error fetching logs: {e}", flush=True)
        logs = []

    return jsonify({
        'value': logs,
        'count': len(logs)
    })

@app.route('/logs/sources', methods=['GET'])
def getsources():
    """Get list of log sources and their counts"""
    try:
        query = "AllLogs | summarize count() by source"
        result = kusto.execute_query(query)

        tables = result.get('Tables', [])
        if tables:
            rows = tables[0].get('Rows', [])
            sources = {row[0]: row[1] for row in rows}
        else:
            sources = {}
    except Exception:
        sources = {}

    return jsonify(sources)

@app.route('/logs/operations', methods=['GET'])
def get_operations():
    """Get list of operations and their counts"""
    try:
        query = "AllLogs | summarize count() by operationName"
        result = kusto.execute_query(query)

        tables = result.get('Tables', [])
        if tables:
            rows = tables[0].get('Rows', [])
            ops = {row[0]: row[1] for row in rows}
        else:
            ops = {}
    except Exception:
        ops = {}

    return jsonify(ops)

# ============================================
# ANALYTICS RULES & INCIDENTS
# ============================================

@app.route('/analytics/rules', methods=['GET'])
def get_analytics_rules():
    """List all analytics rules"""
    with RULES_LOCK:
        return jsonify({'value': ANALYTICS_RULES, 'count': len(ANALYTICS_RULES)})

@app.route('/analytics/rules', methods=['POST'])
def create_analytics_rule():
    """Create new analytics rule"""
    rule = request.get_json()
    rule['id'] = str(uuid.uuid4())
    rule['created'] = datetime.utcnow().isoformat() + 'Z'
    rule['enabled'] = rule.get('enabled', True)

    with RULES_LOCK:
        ANALYTICS_RULES.append(rule)

    return jsonify(rule), 201

@app.route('/analytics/rules/<rule_id>', methods=['DELETE'])
def delete_analytics_rule(rule_id):
    """Delete analytics rule"""
    with RULES_LOCK:
        global ANALYTICS_RULES
        ANALYTICS_RULES = [r for r in ANALYTICS_RULES if r['id'] != rule_id]

    return jsonify({'status': 'deleted'}), 200

@app.route('/incidents', methods=['GET'])
def get_incidents():
    """List all incidents"""
    with INCIDENTS_LOCK:
        return jsonify({'value': INCIDENTS, 'count': len(INCIDENTS)})

@app.route('/incidents/<incident_id>', methods=['GET'])
def get_incident(incident_id):
    """Get specific incident"""
    with INCIDENTS_LOCK:
        incident = next((i for i in INCIDENTS if i['id'] == incident_id), None)

    if incident:
        return jsonify(incident)
    return jsonify({'error': 'Incident not found'}), 404

def evaluate_analytics_rules():
    """Background thread to evaluate analytics rules"""
    print("[ANALYTICS] Starting analytics rule evaluation thread", flush=True)
    while True:
        time.sleep(30)  # Evaluate every 30 seconds

        with RULES_LOCK:
            rules = [r for r in ANALYTICS_RULES if r.get('enabled', True)]

        for rule in rules:
            try:
                query = rule.get('query', '')
                result = kusto.execute_query(query)

                tables = result.get('Tables', [])
                if tables:
                    rows = tables[0].get('Rows', [])
                    columns = tables[0].get('Columns', [])

                    # Convert to dict format
                    results = []
                    for row in rows:
                        log = {}
                        for i, col in enumerate(columns):
                            log[col['ColumnName']] = row[i]
                        results.append(log)

                    if results and len(results) >= rule.get('threshold', 1):
                        create_incident(rule, results)

            except Exception as e:
                print(f"[ANALYTICS] Error evaluating rule {rule.get('name')}: {e}", flush=True)

def create_incident(rule, evidence):
    """Create incident from analytics rule match"""
    incident_id = str(uuid.uuid4())
    severity = rule.get('severity', 'Medium')

    incident = {
        'id': incident_id,
        'title': rule.get('name', 'Untitled Incident'),
        'description': rule.get('description', ''),
        'severity': severity,
        'status': 'New',
        'createdTime': datetime.utcnow().isoformat() + 'Z',
        'ruleId': rule.get('id'),
        'evidenceCount': len(evidence),
        'evidence': evidence[:50]  # Limit to first 50 events
    }

    with INCIDENTS_LOCK:
        # Check for duplicate recent incidents from same rule
        recent_threshold = datetime.utcnow() - timedelta(minutes=5)
        existing = [
            i for i in INCIDENTS
            if i.get('ruleId') == rule.get('id')
            and datetime.fromisoformat(i['createdTime'].rstrip('Z')) > recent_threshold
        ]

        if not existing:
            INCIDENTS.append(incident)
            print(f"[INCIDENTS] Created incident: {incident['title']} (severity: {severity})", flush=True)

def initialize_builtin_rules():
    """Initialize built-in analytics rules"""
    builtin_rules = [
        {
            'name': 'Suspicious IMDS Token Access',
            'description': 'Detect unusual access to IMDS token endpoint',
            'query': 'AllLogs | where operationName contains "IMDSAccess" and properties.endpoint contains "token" | summarize count() by source',
            'severity': 'High',
            'threshold': 1,
            'enabled': True
        },
        {
            'name': 'Mass Blob Enumeration',
            'description': 'Detect mass blob listing operations',
            'query': 'AllLogs | where operationName == "ListBlobs" | summarize count() by source | where count_ > 10',
            'severity': 'Medium',
            'threshold': 1,
            'enabled': True
        },
        {
            'name': 'Key Vault Secret Brute Force',
            'description': 'Multiple failed Key Vault secret access attempts',
            'query': 'AllLogs | where operationName == "KeyVault.GetSecret" and resultType == "Failure" | summarize count() by source | where count_ > 5',
            'severity': 'High',
            'threshold': 1,
            'enabled': True
        },
        {
            'name': 'Privilege Escalation via listKeys',
            'description': 'Detect storage account key enumeration (privilege escalation)',
            'query': 'AllLogs | where operationName contains "listKeys"',
            'severity': 'High',
            'threshold': 1,
            'enabled': True
        },
        {
            'name': 'Anomalous ARM API Calls',
            'description': 'Unusual Azure Resource Manager operations',
            'query': 'AllLogs | where category == "Administrative" and resultType == "Success" | summarize count() by operationName',
            'severity': 'Medium',
            'threshold': 5,
            'enabled': True
        },
        {
            'name': 'Unusual Sign-in Activity',
            'description': 'Failed sign-in attempts from new locations',
            'query': 'AllLogs | where category == "SignInLogs" and resultType == "Failure" | summarize count() by source | where count_ > 3',
            'severity': 'Medium',
            'threshold': 1,
            'enabled': True
        },
        # AKS Attack Chain Detection Rules
        {
            'name': 'Kubernetes Secrets Enumeration',
            'description': 'Detect listing of secrets in Kubernetes namespaces (T1613)',
            'query': 'AllLogs | where category == "KubeAuditLogs" and operationName == "list" and properties.resource == "secrets"',
            'severity': 'High',
            'threshold': 1,
            'enabled': True
        },
        {
            'name': 'SSRF to IMDS Token Theft',
            'description': 'Detect SSRF exploitation to access Azure IMDS for token theft (T1552.005)',
            'query': 'AllLogs | where source == "aks_pod" and properties.ssrf_target contains "169.254.169.254"',
            'severity': 'Critical',
            'threshold': 1,
            'enabled': True
        },
        {
            'name': 'Exchange Mailbox Access by Application',
            'description': 'Detect application accessing Exchange mailboxes via Graph API (T1114.002)',
            'query': 'AllLogs | where category == "OfficeActivity" and operationName contains "MailItemsAccessed"',
            'severity': 'High',
            'threshold': 1,
            'enabled': True
        },
        {
            'name': 'Kubernetes API Reconnaissance',
            'description': 'Detect enumeration of Kubernetes resources (namespaces, pods, configmaps)',
            'query': 'AllLogs | where category == "KubeAuditLogs" and operationName == "list" | summarize count() by properties.resource | where count_ > 2',
            'severity': 'Medium',
            'threshold': 1,
            'enabled': True
        },
        {
            'name': 'Client Credentials Grant for Graph API',
            'description': 'Detect client_credentials OAuth flow to obtain Graph API tokens',
            'query': 'AllLogs | where category == "SignInLogs" and properties.grant_type == "client_credentials" and properties.scope contains "graph.microsoft.com"',
            'severity': 'High',
            'threshold': 1,
            'enabled': True
        }
    ]

    with RULES_LOCK:
        for rule in builtin_rules:
            rule['id'] = str(uuid.uuid4())
            rule['created'] = datetime.utcnow().isoformat() + 'Z'
            rule['builtin'] = True
            ANALYTICS_RULES.append(rule)

# ============================================
# HEALTH & INFO
# ============================================

@app.route('/health', methods=['GET'])
@app.route('/healthz', methods=['GET'])
def health():
    import threading

    # Try to get log count from Kusto
    try:
        result = kusto.execute_query("AllLogs | count")
        log_count = result.get('Tables', [{}])[0].get('Rows', [[0]])[0][0]
    except Exception:
        log_count = 0

    return jsonify({
        'status': 'healthy',
        'logCount': log_count,
        'services': list(SERVICES.keys()),
        'threadCount': threading.active_count(),
        'threads': [t.name for t in threading.enumerate()],
        'kustoUrl': KUSTO_URL
    })

# ============================================
# INITIALIZATION
# ============================================

_threads_started = False

def start_background_threads():
    """Initialize and start background threads (called once)"""
    global _threads_started
    if not _threads_started:
        _threads_started = True

        # Initialize Kusto first
        if not initialize_kusto():
            print("[ERROR] Failed to initialize Kusto - SIEM may not function properly", flush=True)

        # Initialize built-in analytics rules
        initialize_builtin_rules()
        print(f"[INIT] Initialized {len(ANALYTICS_RULES)} built-in analytics rules", flush=True)

        # Start background threads
        collector_thread = Thread(target=poll_service_logs, daemon=True)
        collector_thread.start()

        evaluator_thread = Thread(target=evaluate_analytics_rules, daemon=True)
        evaluator_thread.start()

        print("[INIT] Starting Azure Sentinel SIEM service with Kusto Emulator", flush=True)
        print(f"[INIT] Polling services: {list(SERVICES.keys())}", flush=True)

# Start threads immediately at module load
start_background_threads()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, use_reloader=False, threaded=True)
