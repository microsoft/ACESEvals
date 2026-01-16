# Azure Resource Manager (ARM) Mock API
# Simulates https://management.azure.com/
# Generates AzureActivity logs matching real Azure Activity Log schema

from flask import Flask, request, jsonify
from functools import wraps
import yaml
import os
import uuid
from datetime import datetime

app = Flask(__name__)

SUBSCRIPTION_ID = os.environ.get('SUBSCRIPTION_ID', '12345678-1234-1234-1234-123456789abc')
TENANT_ID = os.environ.get('TENANT_ID', '87654321-4321-4321-4321-cba987654321')
CONFIG_PATH = os.environ.get('CONFIG_PATH', '/app/config.yaml')

ACTIVITY_LOG = []
CONFIG = {}

# Valid tokens injected via /admin/tokens (from init-seed)
VALID_TOKENS = set()


def load_config():
    global CONFIG
    try:
        with open(CONFIG_PATH, 'r') as f:
            CONFIG = yaml.safe_load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        CONFIG = {}


def generate_azure_activity_log(operation_name, resource_id, caller_ip, success=True, http_method='GET'):
    """
    Generate an Azure Activity Log entry matching the real AzureActivity schema.
    Reference: https://learn.microsoft.com/en-us/azure/azure-monitor/essentials/activity-log-schema
    """
    now = datetime.utcnow()
    correlation_id = str(uuid.uuid4())

    log_entry = {
        'time': now.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
        'resourceId': resource_id.upper(),
        'operationName': operation_name,
        'category': 'Administrative',
        'resultType': 'Success' if success else 'Failure',
        'callerIpAddress': caller_ip,
        'correlationId': correlation_id,
        'level': 'Informational' if success else 'Warning',
        'properties': {
            'statusCode': 'OK' if success else 'Forbidden',
            'httpMethod': http_method
        },
        'tenantId': TENANT_ID
    }

    ACTIVITY_LOG.append(log_entry)
    print(f"ARM_ACTIVITY: {log_entry}")
    return log_entry


def validate_token(f):
    """Validates Bearer token matches an injected token from init-seed."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': {'code': 'AuthenticationFailed', 'message': 'Missing Bearer token'}}), 401

        token = auth_header[7:]  # Strip "Bearer "
        if not VALID_TOKENS:
            # No tokens injected yet - reject all
            print(f"ARM: No valid tokens configured. Rejecting request.")
            return jsonify({'error': {'code': 'TokenNotConfigured', 'message': 'No tokens injected. Run seeder first.'}}), 500

        if token not in VALID_TOKENS:
            print(f"ARM: Invalid token received (not from IMDS)")
            return jsonify({'error': {'code': 'InvalidToken', 'message': 'Token not recognized'}}), 403

        return f(*args, **kwargs)
    return decorated


# ============================================
# SUBSCRIPTION ENDPOINTS
# ============================================

@app.route('/subscriptions', methods=['GET'])
@validate_token
def list_subscriptions():
    generate_azure_activity_log(
        'Microsoft.Resources/subscriptions/read',
        '/subscriptions',
        request.remote_addr
    )

    sub = CONFIG.get('subscription', {})
    sub_id = sub.get('id', SUBSCRIPTION_ID)
    tenant_id = sub.get('tenant_id', TENANT_ID)
    display_name = sub.get('name', 'Production Subscription')

    return jsonify({
        'value': [{
            'id': f'/subscriptions/{sub_id}',
            'subscriptionId': sub_id,
            'tenantId': tenant_id,
            'displayName': display_name,
            'state': 'Enabled'
        }]
    })


@app.route('/subscriptions/<subscription_id>/resourcegroups', methods=['GET'])
@validate_token
def list_resource_groups(subscription_id):
    generate_azure_activity_log(
        'Microsoft.Resources/resourceGroups/read',
        f'/subscriptions/{subscription_id}',
        request.remote_addr
    )

    rgs = CONFIG.get('resource_groups', [])
    return jsonify({
        'value': [
            {
                'id': f'/subscriptions/{subscription_id}/resourceGroups/{rg["name"]}',
                'name': rg['name'],
                'location': rg['location'],
                'properties': {'provisioningState': 'Succeeded'}
            }
            for rg in rgs
        ]
    })


# ============================================
# STORAGE ACCOUNT ENDPOINTS
# ============================================

@app.route('/subscriptions/<subscription_id>/providers/Microsoft.Storage/storageAccounts', methods=['GET'])
@validate_token
def list_storage_accounts(subscription_id):
    generate_azure_activity_log(
        'Microsoft.Storage/storageAccounts/read',
        f'/subscriptions/{subscription_id}',
        request.remote_addr
    )

    storage_accounts = CONFIG.get('storage_accounts', [])
    return jsonify({
        'value': [
            {
                'id': f'/subscriptions/{subscription_id}/resourceGroups/{sa["resource_group"]}/providers/Microsoft.Storage/storageAccounts/{sa["name"]}',
                'name': sa['name'],
                'type': 'Microsoft.Storage/storageAccounts',
                'location': sa['location'],
                'properties': {
                    'primaryEndpoints': {
                        'blob': f"https://{sa['name']}.blob.core.windows.net/"
                    }
                }
            }
            for sa in storage_accounts
        ]
    })


# ============================================
# KEY VAULT ENDPOINTS
# ============================================

@app.route('/subscriptions/<subscription_id>/providers/Microsoft.KeyVault/vaults', methods=['GET'])
@validate_token
def list_key_vaults(subscription_id):
    generate_azure_activity_log(
        'Microsoft.KeyVault/vaults/read',
        f'/subscriptions/{subscription_id}',
        request.remote_addr
    )

    vaults = CONFIG.get('key_vaults', [])
    return jsonify({
        'value': [
            {
                'id': f'/subscriptions/{subscription_id}/resourceGroups/{vault["resource_group"]}/providers/Microsoft.KeyVault/vaults/{vault["name"]}',
                'name': vault['name'],
                'type': 'Microsoft.KeyVault/vaults',
                'location': vault['location'],
                'properties': {
                    'vaultUri': f"https://{vault['name']}.vault.azure.net/"
                }
            }
            for vault in vaults
        ]
    })


# ============================================
# WEB APPS / FUNCTION APPS
# ============================================

@app.route('/subscriptions/<subscription_id>/providers/Microsoft.Web/sites', methods=['GET'])
@validate_token
def list_web_sites(subscription_id):
    """List all web apps and function apps in subscription."""
    generate_azure_activity_log(
        'Microsoft.Web/sites/read',
        f'/subscriptions/{subscription_id}',
        request.remote_addr
    )

    function_apps = CONFIG.get('function_apps', [])
    app_services = CONFIG.get('app_services', [])

    sites = []
    for app in function_apps:
        sites.append({
            'id': f'/subscriptions/{subscription_id}/resourceGroups/{app["resource_group"]}/providers/Microsoft.Web/sites/{app["name"]}',
            'name': app['name'],
            'type': 'Microsoft.Web/sites',
            'kind': 'functionapp',
            'properties': {
                'defaultHostName': f"{app['name']}.azurewebsites.net"
            }
        })

    for app in app_services:
        sites.append({
            'id': f'/subscriptions/{subscription_id}/resourceGroups/{app["resource_group"]}/providers/Microsoft.Web/sites/{app["name"]}',
            'name': app['name'],
            'type': 'Microsoft.Web/sites',
            'kind': 'app',
            'properties': {
                'defaultHostName': f"{app['name']}.azurewebsites.net"
            }
        })

    return jsonify({'value': sites})


# ============================================
# ADMIN ENDPOINTS
# ============================================

@app.route('/admin/config', methods=['GET', 'POST'])
def admin_config():
    """
    Inject infrastructure configuration (called by init-seed).

    POST: Set infrastructure data ARM will return for discovery
      Body: {
        "subscription": {...},
        "resource_groups": [...],
        "storage_accounts": [...],
        "key_vaults": [...],
        "function_apps": [...],
        "app_services": [...]
      }

    GET: Return current config summary
    """
    global CONFIG

    if request.method == 'POST':
        data = request.get_json() or {}
        CONFIG.update(data)
        print(f"ARM_ADMIN: Config updated - {len(CONFIG.get('storage_accounts', []))} storage, "
              f"{len(CONFIG.get('key_vaults', []))} vaults, {len(CONFIG.get('app_services', []))} apps")
        return jsonify({
            "status": "ok",
            "storage_accounts": len(CONFIG.get('storage_accounts', [])),
            "key_vaults": len(CONFIG.get('key_vaults', [])),
            "app_services": len(CONFIG.get('app_services', [])),
            "function_apps": len(CONFIG.get('function_apps', []))
        })

    else:  # GET
        return jsonify({
            "storage_accounts": len(CONFIG.get('storage_accounts', [])),
            "key_vaults": len(CONFIG.get('key_vaults', [])),
            "resource_groups": len(CONFIG.get('resource_groups', []))
        })


@app.route('/admin/tokens', methods=['GET', 'POST', 'DELETE'])
def admin_tokens():
    """
    Manage valid tokens that ARM will accept.

    POST: Inject valid tokens (called by init-seed)
      Body: {"tokens": ["token1", "token2"]}

    GET: List count of valid tokens

    DELETE: Clear all valid tokens
    """
    global VALID_TOKENS

    if request.method == 'POST':
        data = request.get_json() or {}
        tokens = data.get('tokens', [])
        VALID_TOKENS.update(tokens)
        print(f"ARM_ADMIN: Injected {len(tokens)} valid token(s)")
        return jsonify({"status": "ok", "tokens_count": len(VALID_TOKENS)})

    elif request.method == 'DELETE':
        count = len(VALID_TOKENS)
        VALID_TOKENS.clear()
        print(f"ARM_ADMIN: Cleared {count} token(s)")
        return jsonify({"status": "ok", "cleared": count})

    else:  # GET
        return jsonify({"tokens_count": len(VALID_TOKENS)})


# ============================================
# AUDIT & HEALTH
# ============================================

@app.route('/audit/logs', methods=['GET'])
def get_audit_logs():
    """Get ARM Activity Logs for threat hunting."""
    return jsonify({'value': ACTIVITY_LOG, 'count': len(ACTIVITY_LOG)})


@app.route('/health', methods=['GET'])
@app.route('/healthz', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'subscription': SUBSCRIPTION_ID})


if __name__ == '__main__':
    load_config()
    print(f"Starting Azure ARM mock for subscription {SUBSCRIPTION_ID}")
    app.run(host='0.0.0.0', port=443, ssl_context='adhoc')
