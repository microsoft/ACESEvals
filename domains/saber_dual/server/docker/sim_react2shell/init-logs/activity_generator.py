"""
ActivityGenerator - Generate realistic benign Azure activity logs.

Inspired by CMU-SEI GHOSTS patterns:
- Jittered timing to avoid machine-like patterns
- Probability-weighted action selection
- Working hours windows for human activity
- Session clustering for related operations
- Persona-based activity profiles

Can run as:
1. Historical generation: generate_historical_logs(output_dir, hours=48)
2. Real-time background process: start_realtime_generator(output_dir)
3. Standalone: python -m src.activity_generator --output ./logs --hours 48
"""

import json
import os
import random
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from faker import Faker

fake = Faker()

# PID file for real-time generator
PID_FILE = Path("/tmp/saber-sim-activity-generator.pid")

# Log schema names (matching log_streamer.py)
LOG_SCHEMAS = {
    "imds": "AzureIMDSAccessLogs",
    "keyvault": "AzureKeyVaultAuditLogs",
    "azure_ad": "AADSignInLogs",
    "app_service": "AppServiceHTTPLogs",
    "functions": "AzureFunctionLogs",
    "gateway": "AzureNetworkSecurityGroupLogs",
    "sql": "SQLSecurityAuditEvents",
    "windows": "WindowsSecurityEvents",
    "sysmon": "SysmonEvents",
    "eventgrid": "EventGridPublishLogs",
    "arm": "AzureActivityLogs",
    "blob_storage": "StorageBlobLogs",
}

# =============================================================================
# Core Utilities (GHOSTS-inspired)
# =============================================================================


def jitter(base_value: int, jitter_percent: int = 30) -> int:
    """Apply randomization to a value. E.g., 100 with 30% jitter = 70-130."""
    if jitter_percent <= 0:
        return base_value
    min_val = int(base_value * (100 - jitter_percent) / 100)
    max_val = int(base_value * (100 + jitter_percent) / 100)
    return random.randint(min_val, max_val)


def weighted_choice(options: dict[str, int]) -> str:
    """Select from options based on probability weights."""
    items = list(options.keys())
    weights = list(options.values())
    return random.choices(items, weights=weights, k=1)[0]


def is_working_hours(dt: datetime, time_on: str = "08:00", time_off: str = "18:00") -> bool:
    """Check if datetime falls within working hours."""
    start = datetime.strptime(time_on, "%H:%M").time()
    end = datetime.strptime(time_off, "%H:%M").time()
    return start <= dt.time() <= end


# =============================================================================
# Persona Definitions
# =============================================================================

PERSONAS = {
    # Engineering personas
    "senior_developer": {
        "services": ["keyvault", "imds", "app_service", "functions", "sql", "blob_storage"],
        "frequency_per_hour": 40,
        "working_hours": ("08:00", "20:00"),
        "jitter_percent": 35,
        "operations": {
            "keyvault": {"GetSecret": 50, "ListSecrets": 35, "SetSecret": 15},
            "imds": {"GetToken": 70, "GetMetadata": 30},
            "app_service": {"GET": 45, "POST": 35, "PUT": 15, "DELETE": 5},
            "sql": {"Login": 5, "Select": 60, "Insert": 15, "Update": 15, "Delete": 5},
            "blob_storage": {"GetBlob": 50, "PutBlob": 30, "ListBlobs": 20},
        },
    },
    "backend_developer": {
        "services": ["keyvault", "imds", "functions", "sql", "blob_storage", "eventgrid"],
        "frequency_per_hour": 35,
        "working_hours": ("09:00", "19:00"),
        "jitter_percent": 40,
        "operations": {
            "keyvault": {"GetSecret": 60, "ListSecrets": 30, "SetSecret": 10},
            "imds": {"GetToken": 80, "GetMetadata": 20},
            "functions": {"HttpTrigger": 70, "TimerTrigger": 30},
            "sql": {"Login": 5, "Select": 65, "Insert": 15, "Update": 10, "Delete": 5},
            "blob_storage": {"GetBlob": 55, "PutBlob": 25, "ListBlobs": 20},
            "eventgrid": {"PublishEvent": 80, "ListSubscriptions": 20},
        },
    },
    "frontend_developer": {
        "services": ["app_service", "keyvault", "blob_storage"],
        "frequency_per_hour": 25,
        "working_hours": ("09:00", "18:00"),
        "jitter_percent": 45,
        "operations": {
            "app_service": {"GET": 60, "POST": 25, "PUT": 10, "DELETE": 5},
            "keyvault": {"GetSecret": 70, "ListSecrets": 30},
            "blob_storage": {"GetBlob": 75, "ListBlobs": 25},
        },
    },
    "tech_lead": {
        "services": ["keyvault", "azure_ad", "app_service", "gateway", "arm"],
        "frequency_per_hour": 20,
        "working_hours": ("08:00", "19:00"),
        "jitter_percent": 50,
        "operations": {
            "keyvault": {"GetSecret": 40, "ListSecrets": 50, "SetSecret": 10},
            "azure_ad": {"SignIn": 60, "TokenRefresh": 40},
            "app_service": {"GET": 70, "POST": 20, "PUT": 10},
            "arm": {"ResourceRead": 75, "RoleAssignment": 25},
        },
    },
    # DevOps/SRE personas
    "sre": {
        "services": ["keyvault", "imds", "gateway", "functions", "azure_ad", "arm", "windows"],
        "frequency_per_hour": 50,
        "working_hours": ("07:00", "22:00"),  # On-call hours
        "jitter_percent": 30,
        "operations": {
            "keyvault": {"GetSecret": 50, "ListSecrets": 40, "SetSecret": 10},
            "imds": {"GetToken": 60, "GetMetadata": 40},
            "gateway": {"Allow": 85, "Deny": 15},
            "arm": {"ResourceRead": 60, "ListKeys": 5, "ResourceWrite": 20, "RoleAssignment": 15},
            "windows": {"Logon": 50, "KerberosTGT": 30, "KerberosService": 20},
        },
    },
    "devops_engineer": {
        "services": ["keyvault", "imds", "functions", "eventgrid", "arm", "blob_storage"],
        "frequency_per_hour": 45,
        "working_hours": ("08:00", "20:00"),
        "jitter_percent": 35,
        "operations": {
            "keyvault": {"GetSecret": 55, "ListSecrets": 30, "SetSecret": 15},
            "imds": {"GetToken": 75, "GetMetadata": 25},
            "functions": {"HttpTrigger": 50, "TimerTrigger": 50},
            "eventgrid": {"PublishEvent": 70, "ListSubscriptions": 20, "CreateSubscription": 10},
            "arm": {"ResourceRead": 40, "ResourceWrite": 30, "Deployment": 20, "ListKeys": 10},
            "blob_storage": {"GetBlob": 40, "PutBlob": 35, "ListBlobs": 25},
        },
    },
    "platform_engineer": {
        "services": ["keyvault", "gateway", "imds", "arm"],
        "frequency_per_hour": 40,
        "working_hours": ("08:00", "19:00"),
        "jitter_percent": 30,
        "operations": {
            "keyvault": {"GetSecret": 45, "ListSecrets": 45, "SetSecret": 10},
            "gateway": {"Allow": 90, "Deny": 10},
            "imds": {"GetToken": 65, "GetMetadata": 35},
            "arm": {"ResourceRead": 50, "ResourceWrite": 30, "RoleAssignment": 20},
        },
    },
    # Security personas
    "security_engineer": {
        "services": ["keyvault", "azure_ad", "gateway", "arm", "windows"],
        "frequency_per_hour": 30,
        "working_hours": ("08:00", "18:00"),
        "jitter_percent": 40,
        "operations": {
            "keyvault": {"GetSecret": 30, "ListSecrets": 60, "SetSecret": 10},
            "azure_ad": {"SignIn": 50, "TokenRefresh": 50},
            "gateway": {"Allow": 70, "Deny": 30},
            "arm": {"ResourceRead": 70, "RoleAssignment": 30},
            "windows": {"Logon": 40, "KerberosTGT": 30, "KerberosService": 20, "AccountCreated": 10},
        },
    },
    "soc_analyst": {
        "services": ["azure_ad", "gateway", "keyvault", "sql", "windows", "arm"],
        "frequency_per_hour": 25,
        "working_hours": ("00:00", "23:59"),  # 24/7 SOC coverage
        "jitter_percent": 45,
        "operations": {
            "azure_ad": {"SignIn": 40, "TokenRefresh": 60},
            "gateway": {"Allow": 60, "Deny": 40},
            "keyvault": {"GetSecret": 20, "ListSecrets": 80},
            "sql": {"Login": 10, "Select": 90},
            "windows": {"Logon": 45, "KerberosTGT": 35, "KerberosService": 20},
            "arm": {"ResourceRead": 85, "RoleAssignment": 15},
        },
    },
    # Data Team personas
    "data_engineer": {
        "services": ["keyvault", "functions", "app_service", "sql", "blob_storage", "eventgrid"],
        "frequency_per_hour": 35,
        "working_hours": ("08:00", "19:00"),
        "jitter_percent": 40,
        "operations": {
            "keyvault": {"GetSecret": 70, "ListSecrets": 25, "SetSecret": 5},
            "functions": {"HttpTrigger": 40, "TimerTrigger": 60},
            "app_service": {"GET": 50, "POST": 40, "PUT": 10},
            "sql": {"Login": 5, "Select": 50, "Insert": 25, "Update": 15, "Delete": 5},
            "blob_storage": {"GetBlob": 40, "PutBlob": 30, "ListBlobs": 25, "DeleteBlob": 5},
            "eventgrid": {"PublishEvent": 80, "ListSubscriptions": 20},
        },
    },
    "data_scientist": {
        "services": ["keyvault", "app_service", "sql", "blob_storage"],
        "frequency_per_hour": 20,
        "working_hours": ("09:00", "18:00"),
        "jitter_percent": 55,
        "operations": {
            "keyvault": {"GetSecret": 80, "ListSecrets": 20},
            "app_service": {"GET": 60, "POST": 35, "PUT": 5},
            "sql": {"Login": 5, "Select": 85, "Insert": 5, "Update": 5},
            "blob_storage": {"GetBlob": 70, "ListBlobs": 30},
        },
    },
    "bi_analyst": {
        "services": ["app_service", "keyvault", "sql"],
        "frequency_per_hour": 15,
        "working_hours": ("09:00", "17:00"),
        "jitter_percent": 50,
        "operations": {
            "app_service": {"GET": 85, "POST": 10, "PUT": 5},
            "keyvault": {"GetSecret": 60, "ListSecrets": 40},
            "sql": {"Login": 5, "Select": 95},
        },
    },
    # IT Operations personas
    "it_admin": {
        "services": ["keyvault", "azure_ad", "gateway", "windows", "arm"],
        "frequency_per_hour": 20,
        "working_hours": ("07:00", "19:00"),
        "jitter_percent": 35,
        "operations": {
            "keyvault": {"GetSecret": 35, "ListSecrets": 45, "SetSecret": 20},
            "azure_ad": {"SignIn": 70, "TokenRefresh": 30},
            "gateway": {"Allow": 80, "Deny": 20},
            "windows": {"Logon": 40, "KerberosTGT": 30, "KerberosService": 20, "GroupMemberAdded": 10},
            "arm": {"ResourceRead": 65, "ResourceWrite": 25, "RoleAssignment": 10},
        },
    },
    "systems_admin": {
        "services": ["keyvault", "imds", "gateway", "windows", "arm"],
        "frequency_per_hour": 25,
        "working_hours": ("06:00", "20:00"),
        "jitter_percent": 30,
        "operations": {
            "keyvault": {"GetSecret": 50, "ListSecrets": 40, "SetSecret": 10},
            "imds": {"GetToken": 55, "GetMetadata": 45},
            "gateway": {"Allow": 85, "Deny": 15},
            "windows": {"Logon": 45, "KerberosTGT": 35, "KerberosService": 20},
            "arm": {"ResourceRead": 70, "ResourceWrite": 20, "Deployment": 10},
        },
    },
    # Service accounts (automated - 24/7)
    "cicd_pipeline": {
        "services": ["imds", "keyvault", "functions", "eventgrid", "arm", "blob_storage"],
        "frequency_per_hour": 80,
        "working_hours": ("00:00", "23:59"),
        "jitter_percent": 10,
        "operations": {
            "imds": {"GetToken": 95, "GetMetadata": 5},
            "keyvault": {"GetSecret": 90, "ListSecrets": 10},
            "functions": {"HttpTrigger": 60, "TimerTrigger": 40},
            "eventgrid": {"PublishEvent": 85, "CreateSubscription": 15},
            "arm": {"Deployment": 60, "ResourceWrite": 30, "ResourceRead": 10},
            "blob_storage": {"PutBlob": 60, "GetBlob": 30, "ListBlobs": 10},
        },
    },
    "monitoring_agent": {
        "services": ["imds", "keyvault", "app_service", "arm", "sql", "windows", "blob_storage"],
        "frequency_per_hour": 120,
        "working_hours": ("00:00", "23:59"),
        "jitter_percent": 5,
        "operations": {
            "imds": {"GetToken": 80, "GetMetadata": 20},
            "keyvault": {"GetSecret": 70, "ListSecrets": 30},
            "app_service": {"GET": 95, "POST": 5},
            "arm": {"ResourceRead": 100},
            "sql": {"Login": 10, "Select": 90},
            "windows": {"Logon": 60, "NetworkConnection": 40},
            "blob_storage": {"ListBlobs": 60, "GetBlob": 40},
        },
    },
    "backup_service": {
        "services": ["keyvault", "imds", "sql", "windows", "blob_storage"],
        "frequency_per_hour": 30,
        "working_hours": ("00:00", "23:59"),
        "jitter_percent": 8,
        "operations": {
            "keyvault": {"GetSecret": 85, "ListSecrets": 15},
            "imds": {"GetToken": 90, "GetMetadata": 10},
            "sql": {"Login": 10, "Select": 90},
            "windows": {"Logon": 70, "ProcessCreate": 30},
            "blob_storage": {"GetBlob": 70, "PutBlob": 20, "ListBlobs": 10},
        },
    },
    "data_pipeline": {
        "services": ["keyvault", "functions", "sql", "blob_storage", "eventgrid"],
        "frequency_per_hour": 100,
        "working_hours": ("00:00", "23:59"),
        "jitter_percent": 12,
        "operations": {
            "keyvault": {"GetSecret": 92, "ListSecrets": 8},
            "functions": {"TimerTrigger": 80, "HttpTrigger": 20},
            "sql": {"Login": 5, "Select": 40, "Insert": 40, "Update": 10, "Delete": 5},
            "blob_storage": {"PutBlob": 50, "GetBlob": 30, "DeleteBlob": 20},
            "eventgrid": {"PublishEvent": 100},
        },
    },
    "security_scanner": {
        "services": ["keyvault", "gateway", "azure_ad", "arm", "blob_storage", "windows"],
        "frequency_per_hour": 40,
        "working_hours": ("00:00", "23:59"),
        "jitter_percent": 15,
        "operations": {
            "keyvault": {"GetSecret": 20, "ListSecrets": 80},
            "gateway": {"Allow": 50, "Deny": 50},
            "azure_ad": {"SignIn": 30, "TokenRefresh": 70},
            "arm": {"ResourceRead": 80, "RoleAssignment": 20},
            "blob_storage": {"ListBlobs": 60, "GetBlob": 30, "ListContainers": 10},
            "windows": {"ProcessCreate": 60, "NetworkConnection": 40},
        },
    },
}

# Service principals mapped to personas (for log identity)
SERVICE_PRINCIPAL_PERSONAS = {
    "cicd_pipeline": [
        {"name": "github-actions-deploy", "app_id": "bbbbbbbb-1111-2222-3333-444444444444"},
        {"name": "azure-devops-pipeline", "app_id": "bbbbbbbb-2222-3333-4444-555555555555"},
        {"name": "terraform-automation", "app_id": "bbbbbbbb-3333-4444-5555-666666666666"},
        {"name": "argocd-deployer", "app_id": "bbbbbbbb-4444-5555-6666-777777777777"},
    ],
    "monitoring_agent": [
        {"name": "app-insights-collector", "app_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"},
        {"name": "prometheus-scraper", "app_id": "aaaaaaaa-1111-2222-3333-444444444444"},
        {"name": "datadog-agent", "app_id": "aaaaaaaa-2222-3333-4444-555555555555"},
        {"name": "log-analytics-shipper", "app_id": "cccccccc-dddd-eeee-ffff-111111111111"},
    ],
    "backup_service": [
        {"name": "backup-agent", "app_id": "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"},
        {"name": "disaster-recovery-sync", "app_id": "cccccccc-1111-2222-3333-444444444444"},
    ],
    "security_scanner": [
        {"name": "defender-scanner", "app_id": "dddddddd-1111-2222-3333-444444444444"},
        {"name": "sentinel-connector", "app_id": "dddddddd-2222-3333-4444-555555555555"},
        {"name": "vault-sync", "app_id": "dddddddd-3333-4444-5555-666666666666"},
    ],
    "data_pipeline": [
        {"name": "databricks-connector", "app_id": "eeeeeeee-1111-2222-3333-444444444444"},
        {"name": "synapse-worker", "app_id": "eeeeeeee-2222-3333-4444-555555555555"},
        {"name": "adf-pipeline", "app_id": "eeeeeeee-3333-4444-5555-666666666666"},
    ],
}

# Human personas that need dynamically generated users
HUMAN_PERSONA_CONFIG = {
    "senior_developer": {"count": 2, "department": "Engineering"},
    "backend_developer": {"count": 3, "department": "Engineering"},
    "frontend_developer": {"count": 2, "department": "Engineering"},
    "tech_lead": {"count": 2, "department": "Engineering"},
    "sre": {"count": 2, "department": "DevOps"},
    "devops_engineer": {"count": 3, "department": "DevOps"},
    "platform_engineer": {"count": 2, "department": "DevOps"},
    "security_engineer": {"count": 2, "department": "Security"},
    "soc_analyst": {"count": 3, "department": "Security"},
    "data_engineer": {"count": 2, "department": "Data"},
    "data_scientist": {"count": 2, "department": "Data"},
    "bi_analyst": {"count": 2, "department": "Data"},
    "it_admin": {"count": 2, "department": "IT"},
    "systems_admin": {"count": 2, "department": "IT"},
}


def _generate_user() -> dict:
    """Generate a random user using Faker."""
    first_name = fake.first_name()
    last_name = fake.last_name()
    name = f"{first_name} {last_name}"
    # Create email-safe username
    upn = f"{first_name.lower()}.{last_name.lower()}@contoso.com"
    user_id = fake.uuid4()
    return {"name": name, "upn": upn, "user_id": user_id}


def _initialize_human_users() -> dict:
    """Generate all human users for each persona at module load time."""
    users = {}
    for persona_name, config in HUMAN_PERSONA_CONFIG.items():
        users[persona_name] = [_generate_user() for _ in range(config["count"])]
    return users


# Generate users once at module load - consistent within a run
HUMAN_USER_PERSONAS = _initialize_human_users()


def get_identity_for_persona(persona_name: str) -> dict:
    """Get a random identity (service principal or user) for a persona."""
    # Check if it's a service account persona
    if persona_name in SERVICE_PRINCIPAL_PERSONAS:
        sp = random.choice(SERVICE_PRINCIPAL_PERSONAS[persona_name])
        return {"type": "service_principal", "name": sp["name"], "app_id": sp["app_id"], "user_id": sp["app_id"]}

    # Check if it's a human persona
    if persona_name in HUMAN_USER_PERSONAS:
        user = random.choice(HUMAN_USER_PERSONAS[persona_name])
        return {"type": "user", "name": user["name"], "upn": user["upn"], "user_id": user["user_id"]}

    # Fallback to generic identity
    return {"type": "service_principal", "name": "unknown-service", "app_id": fake.uuid4(), "user_id": fake.uuid4()}


# Benign IP ranges (internal network)
BENIGN_IPS = ["10.0.0.", "10.0.1.", "172.16.0.", "192.168.1."]

# Benign user agents
BENIGN_USER_AGENTS = [
    "python-requests/2.31.0",
    "azsdk-python-identity/1.14.0 Python/3.11.0",
    "Azure-SDK-For-Python",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "curl/8.1.2",
]


def get_benign_ip() -> str:
    """Generate a realistic internal IP address."""
    prefix = random.choice(BENIGN_IPS)
    return f"{prefix}{random.randint(2, 254)}"


def get_benign_user_agent() -> str:
    """Get a realistic user agent string."""
    return random.choice(BENIGN_USER_AGENTS)


# =============================================================================
# Log Generators (per service)
# =============================================================================


def generate_imds_log(dt: datetime, operation: str, identity: dict = None) -> dict:
    """Generate an IMDS access log entry matching azure_log_schemas.yaml."""
    ops_map = {
        "GetToken": ("IMDS.GetToken", "InstanceMetadata"),
        "GetMetadata": ("IMDS.GetInstanceMetadata", "InstanceMetadata"),
    }
    op_name, category = ops_map.get(operation, ("IMDS.GetInstanceMetadata", "InstanceMetadata"))

    # Use identity if provided
    client_id = (
        identity.get("app_id", identity.get("user_id", "11111111-2222-3333-4444-555555555555"))
        if identity
        else "11111111-2222-3333-4444-555555555555"
    )

    return {
        "time": dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{random.randint(0, 9999999):07d}Z",
        "resourceId": "/SUBSCRIPTIONS/12345678-1234-1234-1234-123456789ABC/RESOURCEGROUPS/PRODUCTION-RG/PROVIDERS/MICROSOFT.COMPUTE/VIRTUALMACHINES/WEBAPP-VM-001",
        "operationName": op_name,
        "category": category,
        "resultType": "Success",
        "callerIpAddress": get_benign_ip(),
        "correlationId": fake.uuid4(),
        "properties": {
            "endpoint": "/metadata/identity/oauth2/token" if operation == "GetToken" else "/metadata/instance",
            "resource": "https://vault.azure.net" if operation == "GetToken" else None,
            "vmName": "webapp-vm-001",
            "clientId": client_id,
            "userAgent": get_benign_user_agent(),
        },
        "_source": "imds",
    }


def generate_keyvault_log(dt: datetime, operation: str, identity: dict = None) -> dict:
    """Generate a KeyVault audit log entry matching azure_log_schemas.yaml."""
    secrets = [
        "app-insights-instrumentation-key",
        "redis-connection-dev",
        "sendgrid-api-key-sandbox",
        "feature-flags-config",
    ]
    secret_name = random.choice(secrets)

    ops_map = {
        "GetSecret": "SecretGet",
        "ListSecrets": "SecretList",
        "SetSecret": "SecretSet",
    }
    op_name = ops_map.get(operation, "SecretGet")

    # Use identity if provided, otherwise pick random
    if identity:
        app_id = identity.get("app_id", identity.get("user_id", fake.uuid4()))
        object_id = identity.get("user_id", fake.uuid4())
    else:
        app_id = random.choice(list({sp["app_id"] for sps in SERVICE_PRINCIPAL_PERSONAS.values() for sp in sps}))
        object_id = fake.uuid4()

    return {
        "time": dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{random.randint(0, 9999999):07d}Z",
        "resourceId": "/SUBSCRIPTIONS/12345678-1234-1234-1234-123456789ABC/RESOURCEGROUPS/PRODUCTION-RG/PROVIDERS/MICROSOFT.KEYVAULT/VAULTS/PROD-SECRETS-KV",
        "operationName": op_name,
        "operationVersion": "7.4",
        "category": "AuditEvent",
        "resultType": "Success",
        "resultSignature": "OK",
        "resultDescription": "",
        "durationMs": jitter(80, 50),
        "callerIpAddress": get_benign_ip(),
        "correlationId": fake.uuid4(),
        "identity": {
            "claim": {
                "http://schemas.microsoft.com/identity/claims/objectidentifier": object_id,
                "appid": app_id,
            }
        },
        "properties": {
            "clientInfo": get_benign_user_agent(),
            "requestUri": f"https://prod-secrets-kv.vault.azure.net/secrets/{secret_name}?api-version=7.4",
            "id": f"https://prod-secrets-kv.vault.azure.net/secrets/{secret_name}",
            "httpStatusCode": 200,
            "isAccessPolicyMatch": True,
        },
        "_source": "keyvault",
    }


def generate_azure_ad_log(dt: datetime, operation: str, identity: dict = None) -> dict:
    """Generate an Azure AD sign-in log entry matching azure_log_schemas.yaml."""
    ip = get_benign_ip()

    # Use identity if provided
    if identity:
        if identity.get("type") == "user":
            display_name = identity["name"]
            upn = identity["upn"]
            user_id = identity["user_id"]
            app_id = "00000003-0000-0000-c000-000000000000"  # Microsoft Graph
            app_name = "Azure Portal"
            user_type = "Member"
            is_interactive = True
            client_app = "Browser"
            os_name = random.choice(["Windows", "macOS", "Linux"])
            browser = random.choice(["Chrome", "Edge", "Firefox", "Safari"])
        else:
            display_name = identity["name"]
            upn = f"{identity['name'].replace(' ', '-').lower()}@contoso.onmicrosoft.com"
            user_id = identity.get("user_id", identity.get("app_id", fake.uuid4()))
            app_id = identity.get("app_id", fake.uuid4())
            app_name = identity["name"]
            user_type = "Application"
            is_interactive = False
            client_app = "Mobile Apps and Desktop clients"
            os_name = "Linux"
            browser = "Other"
    else:
        # Pick random service principal
        all_sps = [sp for sps in SERVICE_PRINCIPAL_PERSONAS.values() for sp in sps]
        sp = random.choice(all_sps)
        display_name = sp["name"]
        upn = f"{sp['name']}@contoso.onmicrosoft.com"
        user_id = sp["app_id"]
        app_id = sp["app_id"]
        app_name = sp["name"]
        user_type = "Application"
        is_interactive = False
        client_app = "Mobile Apps and Desktop clients"
        os_name = "Linux"
        browser = "Other"

    return {
        "TimeGenerated": dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{random.randint(0, 9999999):07d}Z",
        "OperationName": "Sign-in activity",
        "Category": "SignInLogs",
        "ResultType": "0",  # Success
        "ResultDescription": "Success",
        "CorrelationId": fake.uuid4(),
        "Id": fake.uuid4(),
        "UserDisplayName": display_name,
        "UserPrincipalName": upn,
        "UserId": user_id,
        "AppDisplayName": app_name,
        "AppId": app_id,
        "IPAddress": ip,
        "Location": "US",
        "LocationDetails": {
            "city": random.choice(["Seattle", "San Francisco", "New York", "Austin", "Denver"]),
            "state": random.choice(["Washington", "California", "New York", "Texas", "Colorado"]),
            "countryOrRegion": "US",
        },
        "ClientAppUsed": client_app,
        "DeviceDetail": {
            "operatingSystem": os_name,
            "browser": browser,
        },
        "ConditionalAccessStatus": "success",
        "IsInteractive": is_interactive,
        "RiskLevelAggregated": "none",
        "RiskLevelDuringSignIn": "none",
        "RiskState": "none",
        "Status": {"errorCode": 0},
        "AuthenticationRequirement": "singleFactorAuthentication"
        if not is_interactive
        else "multiFactorAuthentication",
        "TokenIssuerType": "AzureAD",
        "ResourceDisplayName": random.choice(["Azure Key Vault", "Azure Storage", "Microsoft Graph", "Azure Portal"]),
        "ResourceId": random.choice(
            ["https://vault.azure.net", "https://storage.azure.com", "https://graph.microsoft.com"]
        ),
        "HomeTenantId": "87654321-4321-4321-4321-cba987654321",
        "UserType": user_type,
        "_source": "azure_ad",
    }


def generate_app_service_log(dt: datetime, operation: str, identity: dict = None) -> dict:
    """Generate an App Service HTTP log entry matching azure_log_schemas.yaml."""
    endpoints = [
        "/",
        "/health",
        "/api/status",
        "/api/data",
        "/api/users",
        "/api/reports",
        "/static/app.js",
        "/static/styles.css",
        "/favicon.ico",
        "/dashboard",
    ]
    endpoint = random.choice(endpoints)

    status_codes = {"GET": [200, 200, 200, 304], "POST": [200, 201], "PUT": [200, 204], "DELETE": [200, 204]}
    status = random.choice(status_codes.get(operation, [200]))

    # User agent varies by identity type
    if identity and identity.get("type") == "user":
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        ]
        user_agent = random.choice(user_agents)
    else:
        user_agent = get_benign_user_agent()

    return {
        "time": dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{random.randint(0, 9999999):07d}Z",
        "resourceId": "/SUBSCRIPTIONS/12345678-1234-1234-1234-123456789ABC/RESOURCEGROUPS/PRODUCTION-RG/PROVIDERS/MICROSOFT.WEB/SITES/PROD-WEBAPP",
        "category": "AppServiceHTTPLogs",
        "operationName": "Microsoft.Web/sites/log",
        "properties": {
            "CIp": get_benign_ip(),
            "CsMethod": operation,
            "CsUriStem": endpoint,
            "CsUriQuery": "",
            "CsHost": "prod-webapp.azurewebsites.net",
            "ScStatus": status,
            "ScBytes": random.randint(200, 5000),
            "CsBytes": random.randint(100, 1000),
            "TimeTaken": jitter(150, 50),
            "Result": "Success",
            "Cookie": "-",
            "Referer": "-",
            "UserAgent": user_agent,
            "Protocol": "HTTP/1.1",
            "ComputerName": f"RD00155D{random.randint(100000, 999999)}",
        },
        "_source": "app_service",
    }


def generate_functions_log(dt: datetime, operation: str, identity: dict = None) -> dict:
    """Generate an Azure Functions log entry matching azure_log_schemas.yaml."""
    function_names = [
        "ProcessData",
        "CleanupTimer",
        "HealthCheck",
        "SyncRecords",
        "ExportReports",
        "NotificationSender",
        "DataValidator",
        "BackupHandler",
    ]
    func_name = random.choice(function_names)

    trigger_map = {"TimerTrigger": "timerTrigger", "HttpTrigger": "httpTrigger"}
    trigger_type = trigger_map.get(operation, "timerTrigger")

    # Add caller info for HTTP triggers if identity provided
    caller_ip = None
    if operation == "HttpTrigger":
        caller_ip = get_benign_ip()

    return {
        "time": dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{random.randint(0, 9999999):07d}Z",
        "resourceId": "/SUBSCRIPTIONS/12345678-1234-1234-1234-123456789ABC/RESOURCEGROUPS/PRODUCTION-RG/PROVIDERS/MICROSOFT.WEB/SITES/PROD-DATA-PROCESSOR",
        "operationName": "Microsoft.Web/sites/functions/invoke/action",
        "category": "FunctionAppLogs",
        "resultType": "Success",
        "durationMs": jitter(125, 60),
        "callerIpAddress": caller_ip,
        "correlationId": fake.uuid4(),
        "properties": {
            "functionName": func_name,
            "invocationId": f"inv-{fake.uuid4()[:8]}",
            "triggerType": trigger_type,
            "functionInvocationId": fake.uuid4(),
            "executionStage": "Succeeded",
            "hostInstanceId": f"host-{fake.uuid4()[:8]}",
        },
        "_source": "functions",
    }


def generate_gateway_log(dt: datetime, operation: str = None, identity: dict = None) -> dict:
    """Generate a Network Security Group flow log entry."""
    protocols = ["TCP", "TCP", "TCP", "UDP"]
    ports = [443, 443, 80, 22, 3306, 5432, 6379, 8080]

    # Decide allow/deny based on operation hint
    decision = "A" if operation != "Deny" else "D"
    rule = "AllowVnetInBound" if decision == "A" else "DenyAllInBound"

    return {
        "time": dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{random.randint(0, 9999999):07d}Z",
        "resourceId": "/SUBSCRIPTIONS/12345678-1234-1234-1234-123456789ABC/RESOURCEGROUPS/PRODUCTION-RG/PROVIDERS/MICROSOFT.NETWORK/NETWORKSECURITYGROUPS/PROD-NSG",
        "operationName": "NetworkSecurityGroupFlowEvents",
        "category": "NetworkSecurityGroupFlowEvent",
        "properties": {
            "rule": rule,
            "flows": [
                {
                    "sourceAddress": get_benign_ip(),
                    "destinationAddress": f"10.0.0.{random.randint(2, 10)}",
                    "sourcePort": random.randint(49152, 65535),
                    "destinationPort": random.choice(ports),
                    "protocol": random.choice(protocols),
                    "direction": "I",
                    "decision": decision,
                }
            ],
        },
        "_source": "gateway",
    }


def generate_sql_log(dt: datetime, operation: str, identity: dict = None) -> dict:
    """Generate SQL Security Audit Event matching azure_log_schemas.yaml."""
    tables = ["Customers", "Orders", "Products", "Users", "Transactions", "AuditLog", "Sessions"]
    schemas = ["dbo", "sales", "admin", "analytics"]

    ops_map = {
        "Login": ("AUDIT_LOGIN", "LGIS", "Success", ""),
        "LoginFailed": ("AUDIT_LOGIN_FAILED", "LGIF", "Failure", "Password incorrect"),
        "Select": ("AUDIT_SELECT", "SL", "Success", f"SELECT * FROM {random.choice(tables)} WHERE id = @id"),
        "Insert": ("AUDIT_INSERT", "IN", "Success", f"INSERT INTO {random.choice(tables)} VALUES (...)"),
        "Update": (
            "AUDIT_UPDATE",
            "UP",
            "Success",
            f"UPDATE {random.choice(tables)} SET status = @status WHERE id = @id",
        ),
        "Delete": ("AUDIT_DELETE", "DL", "Success", f"DELETE FROM {random.choice(tables)} WHERE id = @id"),
    }

    op_name, action_id, result, statement = ops_map.get(operation, ops_map["Select"])

    return {
        "time": dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{random.randint(0, 9999999):07d}Z",
        "resourceId": "/SUBSCRIPTIONS/12345678-1234-1234-1234-123456789ABC/RESOURCEGROUPS/PRODUCTION-RG/PROVIDERS/MICROSOFT.SQL/SERVERS/PROD-SQL-SERVER/DATABASES/CUSTOMERDB",
        "operationName": op_name,
        "category": "SQLSecurityAuditEvents",
        "resultType": result,
        "properties": {
            "event_time": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "sequence_number": random.randint(10000, 99999),
            "action_id": action_id,
            "succeeded": result == "Success",
            "session_id": random.randint(50, 200),
            "server_principal_name": identity.get("name", "app_user") if identity else "app_user",
            "database_name": "CustomerDB",
            "schema_name": random.choice(schemas),
            "object_name": random.choice(tables),
            "statement": statement,
            "object_type": "TABLE",
            "client_ip": get_benign_ip(),
            "application_name": random.choice(["Azure Functions", "ASP.NET", "JDBC Driver", "SQLAlchemy"]),
            "duration_milliseconds": jitter(50, 30),
        },
        "_source": "sql",
    }


def generate_windows_security_log(dt: datetime, operation: str, identity: dict = None) -> dict:
    """Generate Windows Security Event matching SecurityEvent schema."""
    computers = ["DC.CORP.LOCAL", "WEB01.CORP.LOCAL", "APP01.CORP.LOCAL", "SQL01.CORP.LOCAL"]

    ops_map = {
        "Logon": (4624, "An account was successfully logged on", "0x0", 3),
        "LogonFailed": (4625, "An account failed to log on", "0xc000006d", 3),
        "KerberosTGT": (4768, "A Kerberos authentication ticket (TGT) was requested", "0x0", None),
        "KerberosService": (4769, "A Kerberos service ticket was requested", "0x0", None),
        "CredentialValidation": (4776, "The domain controller attempted to validate the credentials", "0x0", None),
        "SpecialPrivileges": (4672, "Special privileges assigned to new logon", "0x0", None),
        "AccountCreated": (4720, "A user account was created", "0x0", None),
        "AccountEnabled": (4722, "A user account was enabled", "0x0", None),
        "PasswordReset": (4724, "An attempt was made to reset an account's password", "0x0", None),
        "GroupMemberAdded": (4732, "A member was added to a security-enabled local group", "0x0", None),
        "AccountLocked": (4740, "A user account was locked out", "0xc0000234", None),
    }

    event_id, description, status, logon_type = ops_map.get(operation, ops_map["Logon"])

    username = identity.get("name", "user") if identity else "user"

    return {
        "time": dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{random.randint(0, 9999999):07d}Z",
        "category": "SecurityEvent",
        "operationName": f"SecurityEvent_{event_id}",
        "resultType": "Success" if status == "0x0" else "Failure",
        "properties": {
            "EventID": event_id,
            "Computer": random.choice(computers),
            "Channel": "Security",
            "Level": "Information" if status == "0x0" else "FailureAudit",
            "Description": description,
            "EventData": {
                "SubjectUserName": username,
                "TargetUserName": username,
                "Status": status,
                "LogonType": logon_type if logon_type else "",
                "IpAddress": get_benign_ip(),
                "WorkstationName": f"WKS-{random.randint(100, 999)}",
                "FailureReason": "" if status == "0x0" else "Bad password",
            },
        },
        "_source": "windows",
    }


def generate_sysmon_log(dt: datetime, operation: str, identity: dict = None) -> dict:
    """Generate Sysmon event matching SysmonEvent schema."""
    computers = ["DC.CORP.LOCAL", "WEB01.CORP.LOCAL", "APP01.CORP.LOCAL"]

    ops_map = {
        "ProcessCreate": (1, "Process Create"),
        "NetworkConnection": (3, "Network Connection"),
        "FileCreate": (11, "File Create"),
        "RegistryEvent": (13, "Registry Event"),
    }

    event_id, description = ops_map.get(operation, ops_map["ProcessCreate"])

    if event_id == 1:  # Process Create
        processes = [
            ("C:\\Windows\\System32\\cmd.exe", "/c dir", "C:\\Windows\\System32\\svchost.exe"),
            ("C:\\Windows\\System32\\powershell.exe", "Get-Process", "C:\\Windows\\explorer.exe"),
            ("C:\\Program Files\\Microsoft SQL Server\\sqlservr.exe", "", "C:\\Windows\\System32\\services.exe"),
        ]
        image, cmdline, parent = random.choice(processes)

        event_data = {
            "Image": image,
            "CommandLine": cmdline if cmdline else image,
            "ParentImage": parent,
            "User": f"CORP\\{identity.get('name', 'user')}" if identity else "CORP\\user",
            "ProcessGuid": f"{{{fake.uuid4()}}}",
            "ProcessId": random.randint(1000, 9999),
            "Hashes": f"SHA256={fake.sha256()}",
            "IntegrityLevel": random.choice(["High", "Medium", "Low"]),
            "CurrentDirectory": "C:\\Windows\\System32\\",
        }
    elif event_id == 3:  # Network Connection
        ports = [80, 443, 445, 3389, 1433, 5432]
        event_data = {
            "SourceIp": get_benign_ip(),
            "SourcePort": random.randint(49152, 65535),
            "DestinationIp": f"10.0.0.{random.randint(2, 50)}",
            "DestinationPort": random.choice(ports),
            "Protocol": "tcp",
            "Initiated": "true",
            "Image": "C:\\Windows\\System32\\svchost.exe",
        }
    else:
        event_data = {}

    return {
        "time": dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{random.randint(0, 9999999):07d}Z",
        "category": "SysmonEvent",
        "operationName": f"Sysmon_{event_id}",
        "resultType": "Success",
        "properties": {
            "EventID": event_id,
            "Computer": random.choice(computers),
            "Channel": "Microsoft-Windows-Sysmon/Operational",
            "Provider": "Microsoft-Windows-Sysmon",
            "Description": description,
            "EventData": event_data,
        },
        "_source": "sysmon",
    }


def generate_eventgrid_log(dt: datetime, operation: str, identity: dict = None) -> dict:
    """Generate Event Grid publish log matching EventGridPublishLogs schema."""
    event_types = [
        "Microsoft.Storage.BlobCreated",
        "Microsoft.Storage.BlobDeleted",
        "Microsoft.Resources.ResourceWriteSuccess",
        "CustomApp.OrderProcessed",
        "CustomApp.PaymentReceived",
        "CustomApp.UserRegistered",
    ]

    topics = ["storage-events", "app-events", "infrastructure-events", "data-pipeline-events"]

    return {
        "time": dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{random.randint(0, 9999999):07d}Z",
        "resourceId": f"/SUBSCRIPTIONS/12345678-1234-1234-1234-123456789ABC/RESOURCEGROUPS/PRODUCTION-RG/PROVIDERS/MICROSOFT.EVENTGRID/TOPICS/{random.choice(topics).upper()}",
        "operationName": "Microsoft.EventGrid/events/send",
        "category": "PublishEvents",
        "resultType": "Succeeded",
        "durationMs": jitter(25, 15),
        "callerIpAddress": get_benign_ip(),
        "properties": {
            "eventType": random.choice(event_types),
            "subject": f"/subscriptions/12345678-1234-1234-1234-123456789ABC/resourceGroups/production-rg/providers/Microsoft.Storage/storageAccounts/prodstorage/blobServices/default/containers/data/blobs/file-{random.randint(1000, 9999)}.json",
            "eventCount": random.randint(1, 5),
            "topicName": random.choice(topics),
        },
        "_source": "eventgrid",
    }


def generate_arm_log(dt: datetime, operation: str, identity: dict = None) -> dict:
    """Generate Azure Activity log matching AzureActivity schema."""
    resource_types = [
        "Microsoft.Storage/storageAccounts",
        "Microsoft.KeyVault/vaults",
        "Microsoft.Web/sites",
        "Microsoft.Compute/virtualMachines",
        "Microsoft.EventGrid/topics",
        "Microsoft.Network/networkSecurityGroups",
    ]

    ops_map = {
        "ResourceRead": ("read", "Succeeded", "OK", 200),
        "ListKeys": ("listKeys/action", "Succeeded", "OK", 200),
        "ResourceWrite": ("write", "Succeeded", "Created", 201),
        "RoleAssignment": ("Microsoft.Authorization/roleAssignments/read", "Succeeded", "OK", 200),
        "Deployment": ("Microsoft.Resources/deployments/write", "Succeeded", "Accepted", 202),
    }

    action, result_type, result_sig, status_code = ops_map.get(operation, ops_map["ResourceRead"])

    resource_type = random.choice(resource_types)
    f"prod-{resource_type.split('/')[-1].lower()}-{random.randint(100, 999)}"

    return {
        "time": dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{random.randint(0, 9999999):07d}Z",
        "operationName": f"{resource_type}/{action}",
        "category": "Administrative",
        "resultType": result_type,
        "resultSignature": result_sig,
        "durationMs": jitter(200, 100),
        "callerIpAddress": get_benign_ip(),
        "correlationId": fake.uuid4(),
        "identity": {
            "authorization": {
                "scope": "/subscriptions/12345678-1234-1234-1234-123456789ABC/resourceGroups/production-rg",
                "action": f"{resource_type}/{action}",
                "evidence": {
                    "role": random.choice(["Owner", "Contributor", "Reader"]),
                    "principalId": identity.get("user_id") if identity else fake.uuid4(),
                    "principalType": "User" if identity and identity.get("type") == "user" else "ServicePrincipal",
                },
            }
        },
        "properties": {
            "statusCode": status_code,
            "serviceRequestId": fake.uuid4(),
            "statusMessage": f"Operation '{action}' completed successfully",
        },
        "_source": "arm",
    }


def generate_blob_storage_log(dt: datetime, operation: str, identity: dict = None) -> dict:
    """Generate Storage Blob log matching StorageBlobLogs schema."""
    containers = ["uploads", "backups", "public-assets", "customer-data", "analytics", "logs"]

    ops_map = {
        "GetBlob": ("GetBlob", "StorageRead", 200, "Success"),
        "PutBlob": ("PutBlob", "StorageWrite", 201, "Success"),
        "DeleteBlob": ("DeleteBlob", "StorageDelete", 202, "Success"),
        "ListBlobs": ("ListBlobs", "StorageRead", 200, "Success"),
        "GetContainerProperties": ("GetContainerProperties", "StorageRead", 200, "Success"),
        "ListContainers": ("ListContainers", "StorageRead", 200, "Success"),
    }

    op_name, category, status_code, status_text = ops_map.get(operation, ops_map["GetBlob"])

    container = random.choice(containers)
    blob_name = f"data-{fake.date()}-{random.randint(1000, 9999)}.json"

    auth_type = random.choice(["OAuth", "SAS", "AccountKey"])

    return {
        "time": dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{random.randint(0, 9999999):07d}Z",
        "operationName": op_name,
        "category": category,
        "statusCode": status_code,
        "statusText": status_text,
        "durationMs": jitter(80, 40),
        "callerIpAddress": get_benign_ip(),
        "uri": f"https://prodstorage.blob.core.windows.net/{container}/{blob_name}",
        "identity": {
            "type": auth_type,
            "tokenHash": fake.sha256()[:16] if auth_type == "OAuth" else "",
        },
        "properties": {
            "accountName": "prodstorage",
            "requestUrl": f"https://prodstorage.blob.core.windows.net/{container}/{blob_name}?comp=metadata",
            "userAgentHeader": random.choice(["azcopy/10.16.0", "Azure-Storage/8.6.0", "python-requests/2.28.0"]),
            "clientRequestId": fake.uuid4(),
            "etag": f'"{fake.md5()}"',
            "serverLatencyMs": jitter(30, 20),
            "tlsVersion": random.choice(["TLS 1.2", "TLS 1.3"]),
            "objectKey": f"/{container}/{blob_name}",
        },
        "_source": "blob_storage",
    }


# Map services to their log generators
LOG_GENERATORS = {
    "imds": generate_imds_log,
    "keyvault": generate_keyvault_log,
    "azure_ad": generate_azure_ad_log,
    "app_service": generate_app_service_log,
    "functions": generate_functions_log,
    "gateway": generate_gateway_log,
    "sql": generate_sql_log,
    "windows": generate_windows_security_log,
    "sysmon": generate_sysmon_log,
    "eventgrid": generate_eventgrid_log,
    "arm": generate_arm_log,
    "blob_storage": generate_blob_storage_log,
}


# =============================================================================
# Historical Log Generation
# =============================================================================


def generate_historical_logs(output_dir: Path, hours: int = 48) -> dict:
    """
    Generate historical benign activity logs.

    Args:
        output_dir: Directory to write log files
        hours: How many hours of historical data to generate

    Returns:
        Dict with counts per log type
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.utcnow()
    start_time = now - timedelta(hours=hours)

    # Collect all events first, then sort by time
    all_events: list[tuple[datetime, str, dict]] = []

    print(f"\n📝 Generating {hours}h of historical benign activity...")

    for persona_name, persona in PERSONAS.items():
        work_start, work_end = persona["working_hours"]
        events_per_hour = persona["frequency_per_hour"]
        jitter_pct = persona["jitter_percent"]

        # Generate events for each hour
        current = start_time
        while current < now:
            # Check working hours for this persona
            if is_working_hours(current, work_start, work_end):
                # Generate events for this hour
                num_events = jitter(events_per_hour, jitter_pct)

                for _ in range(num_events):
                    # Random time within this hour
                    event_time = current + timedelta(minutes=random.randint(0, 59), seconds=random.randint(0, 59))

                    if event_time >= now:
                        continue

                    # Pick a service this persona uses
                    service = random.choice(persona["services"])

                    # Pick an operation based on weights
                    if service in persona.get("operations", {}):
                        operation = weighted_choice(persona["operations"][service])
                    else:
                        operation = None

                    # Get identity for this persona
                    identity = get_identity_for_persona(persona_name)

                    # Special handling for Windows logs - route Sysmon events separately
                    actual_service = service
                    if service == "windows":
                        sysmon_ops = ["ProcessCreate", "NetworkConnection", "FileCreate", "RegistryEvent"]
                        if operation in sysmon_ops:
                            actual_service = "sysmon"

                    # Generate the log with identity
                    generator = LOG_GENERATORS.get(actual_service)
                    if generator:
                        log_entry = generator(event_time, operation, identity)
                        all_events.append((event_time, actual_service, log_entry))

            current += timedelta(hours=1)

    # Also add some network traffic (not persona-based)
    current = start_time
    while current < now:
        num_flows = jitter(20, 40)  # ~20 flows per hour
        for _ in range(num_flows):
            event_time = current + timedelta(minutes=random.randint(0, 59), seconds=random.randint(0, 59))
            if event_time < now:
                log_entry = generate_gateway_log(event_time, operation=None, identity=None)
                all_events.append((event_time, "gateway", log_entry))
        current += timedelta(hours=1)

    # Sort by timestamp
    all_events.sort(key=lambda x: x[0])

    # Write to files
    counts = {}
    file_handles = {}

    try:
        for event_time, service, log_entry in all_events:
            schema = LOG_SCHEMAS.get(service, "UnknownLogs")

            if schema not in file_handles:
                file_path = output_dir / f"{schema}.jsonl"
                file_handles[schema] = open(file_path, "a")
                counts[schema] = 0

            file_handles[schema].write(json.dumps(log_entry) + "\n")
            counts[schema] = counts.get(schema, 0) + 1
    finally:
        for fh in file_handles.values():
            fh.close()

    # Print summary
    total = sum(counts.values())
    print(f"   Generated {total} benign log entries:")
    for schema, count in sorted(counts.items()):
        print(f"      • {schema}: {count}")

    return counts


# =============================================================================
# Real-time Generator (Background Process)
# =============================================================================


class RealtimeGenerator:
    """Continuously generates benign activity in the background."""

    def __init__(self, output_dir: Path, interval_seconds: int = 15):
        self.output_dir = Path(output_dir)
        self.interval = interval_seconds
        self._running = False

    def run(self):
        """Main loop - generates activity periodically."""
        self._running = True
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        print(f"[ActivityGenerator] Started, writing to {self.output_dir}")

        while self._running:
            try:
                self._generate_batch()
                sleep_time = jitter(self.interval * 1000, 40) / 1000  # Convert back to seconds
                time.sleep(sleep_time)
            except Exception as e:
                print(f"[ActivityGenerator] Error: {e}")
                time.sleep(5)

        print("[ActivityGenerator] Stopped")

    def _generate_batch(self):
        """Generate a small batch of benign activity."""
        now = datetime.utcnow()

        # Pick 1-3 random personas that are "active" now
        active_personas = [
            (name, p)
            for name, p in PERSONAS.items()
            if is_working_hours(now, p["working_hours"][0], p["working_hours"][1])
        ]

        if not active_personas:
            return

        # Generate 1-5 events
        num_events = random.randint(1, 5)

        for _ in range(num_events):
            persona_name, persona = random.choice(active_personas)
            service = random.choice(persona["services"])

            if service in persona.get("operations", {}):
                operation = weighted_choice(persona["operations"][service])
            else:
                operation = None

            # Get identity for this persona
            identity = get_identity_for_persona(persona_name)

            # Special handling for Windows logs - route Sysmon events separately
            actual_service = service
            if service == "windows":
                sysmon_ops = ["ProcessCreate", "NetworkConnection", "FileCreate", "RegistryEvent"]
                if operation in sysmon_ops:
                    actual_service = "sysmon"

            generator = LOG_GENERATORS.get(actual_service)
            if generator:
                # Slight time variation
                event_time = now - timedelta(seconds=random.randint(0, 10))
                log_entry = generator(event_time, operation, identity)

                schema = LOG_SCHEMAS.get(actual_service, "UnknownLogs")
                file_path = self.output_dir / f"{schema}.jsonl"

                with open(file_path, "a") as f:
                    f.write(json.dumps(log_entry) + "\n")

    def _handle_signal(self, signum, frame):
        self._running = False


def start_realtime_generator(output_dir: Path) -> dict:
    """Start the real-time generator as a background subprocess."""
    if PID_FILE.exists():
        pid = int(PID_FILE.read_text().strip())
        try:
            os.kill(pid, 0)
            return {"status": "already_running", "pid": pid}
        except OSError:
            PID_FILE.unlink()

    # Start subprocess
    cmd = [sys.executable, "-m", "src.activity_generator", "--realtime", "--output", str(output_dir)]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    PID_FILE.write_text(str(proc.pid))
    return {"status": "started", "pid": proc.pid}


def stop_realtime_generator() -> dict:
    """Stop the real-time generator background process."""
    if not PID_FILE.exists():
        return {"status": "not_running"}

    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(0.5)
        PID_FILE.unlink()
        return {"status": "stopped", "pid": pid}
    except OSError:
        PID_FILE.unlink()
        return {"status": "not_running"}


# =============================================================================
# CLI Entry Point
# =============================================================================


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate benign Azure activity logs")
    parser.add_argument("--output", "-o", required=True, help="Output directory for logs")
    parser.add_argument("--hours", type=int, default=48, help="Hours of historical data (default: 48)")
    parser.add_argument("--realtime", action="store_true", help="Run as real-time generator (internal use)")
    args = parser.parse_args()

    output_dir = Path(args.output)

    if args.realtime:
        # Run as real-time generator (called by subprocess)
        generator = RealtimeGenerator(output_dir)
        generator.run()
    else:
        # Generate historical data
        generate_historical_logs(output_dir, args.hours)


if __name__ == "__main__":
    main()
