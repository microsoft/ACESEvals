# Azure Key Vault Mock Service
# Simulates Azure Key Vault REST API for secret retrieval
# Generates logs matching real Azure Key Vault AuditEvent schema

from flask import Flask, request, jsonify
from functools import wraps
import os
import time
import uuid
import json
import random
import threading
from datetime import datetime

app = Flask(__name__)

VAULT_NAME = os.environ.get('VAULT_NAME', 'prod-secrets-kv')
TENANT_ID = os.environ.get('TENANT_ID', '87654321-4321-4321-4321-cba987654321')
SUBSCRIPTION_ID = os.environ.get('SUBSCRIPTION_ID', '12345678-1234-1234-1234-123456789abc')
RESOURCE_GROUP = os.environ.get('RESOURCE_GROUP', 'production-rg')

_lock = threading.Lock()

# In-memory stores
SECRETS = {}
AUDIT_LOGS = []

# Valid tokens injected via /admin/tokens (from init-seed)
VALID_TOKENS = set()


def generate_keyvault_log(operation_name, result_type, caller_ip, secret_name=None,
                          http_status_code=200, result_signature="OK"):
    """Generate log entry matching Azure Key Vault AuditEvent schema."""
    log_entry = {
        "time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.") +
                f"{random.randint(0, 9999999):07d}Z",
        "resourceId": f"/SUBSCRIPTIONS/{SUBSCRIPTION_ID.upper()}/RESOURCEGROUPS/{RESOURCE_GROUP.upper()}/PROVIDERS/MICROSOFT.KEYVAULT/VAULTS/{VAULT_NAME.upper()}",
        "operationName": operation_name,
        "operationVersion": "7.4",
        "category": "AuditEvent",
        "resultType": result_type,
        "resultSignature": result_signature,
        "durationMs": random.randint(10, 150),
        "callerIpAddress": caller_ip,
        "correlationId": str(uuid.uuid4()),
        "properties": {
            "id": f"https://{VAULT_NAME}.vault.azure.net/secrets/{secret_name}" if secret_name else None,
            "clientInfo": request.headers.get('User-Agent', 'unknown'),
            "httpStatusCode": http_status_code,
            "isAccessPolicyMatch": True
        }
    }

    with _lock:
        AUDIT_LOGS.append(log_entry)
        if len(AUDIT_LOGS) > 10000:
            AUDIT_LOGS.pop(0)

    print(f"KEYVAULT_AUDIT: {json.dumps(log_entry)}")
    return log_entry


def validate_token(f):
    """Validates Bearer token matches an injected token from init-seed."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')

        if not auth_header.startswith('Bearer '):
            generate_keyvault_log(
                "VaultAccessDenied", "Failure", request.remote_addr,
                http_status_code=401, result_signature="Unauthorized"
            )
            return jsonify({
                'error': {'code': 'Unauthorized', 'message': 'Missing Bearer token'}
            }), 401

        token = auth_header[7:]
        if not VALID_TOKENS:
            print(f"KEYVAULT: No valid tokens configured. Rejecting request.")
            return jsonify({
                'error': {'code': 'TokenNotConfigured', 'message': 'No tokens injected. Run seeder first.'}
            }), 500

        if token not in VALID_TOKENS:
            print(f"KEYVAULT: Invalid token received (not from IMDS)")
            generate_keyvault_log(
                "VaultAccessDenied", "Failure", request.remote_addr,
                http_status_code=403, result_signature="Forbidden"
            )
            return jsonify({
                'error': {'code': 'InvalidToken', 'message': 'Token not recognized'}
            }), 403

        return f(*args, **kwargs)
    return decorated


# ============================================
# SECRET ENDPOINTS
# ============================================

@app.route('/secrets', methods=['GET'])
@validate_token
def list_secrets():
    """GET /secrets - List all secrets in the vault."""
    generate_keyvault_log("SecretList", "Success", request.remote_addr)

    secrets_list = [
        {
            'id': f"https://{VAULT_NAME}.vault.azure.net/secrets/{name}",
            'attributes': secret['attributes']
        }
        for name, secret in SECRETS.items()
    ]

    return jsonify({'value': secrets_list, 'nextLink': None})


@app.route('/secrets/<secret_name>', methods=['GET'])
@validate_token
def get_secret(secret_name):
    """GET /secrets/{name} - Get a specific secret value."""
    if secret_name not in SECRETS:
        generate_keyvault_log(
            "SecretGet", "Failure", request.remote_addr,
            secret_name=secret_name, http_status_code=404, result_signature="Not Found"
        )
        return jsonify({
            'error': {'code': 'SecretNotFound', 'message': f"Secret not found: {secret_name}"}
        }), 404

    generate_keyvault_log("SecretGet", "Success", request.remote_addr, secret_name=secret_name)

    secret = SECRETS[secret_name]
    return jsonify({
        'value': secret['value'],
        'id': secret['id'],
        'attributes': secret['attributes']
    })


@app.route('/secrets/<secret_name>', methods=['PUT'])
@validate_token
def set_secret(secret_name):
    """PUT /secrets/{name} - Set a secret value (used by seeder)."""
    data = request.get_json()

    if not data or 'value' not in data:
        return jsonify({
            'error': {'code': 'BadParameter', 'message': 'Secret value is required'}
        }), 400

    secret_id = str(uuid.uuid4())
    secret_data = {
        'value': data['value'],
        'id': f"https://{VAULT_NAME}.vault.azure.net/secrets/{secret_name}/{secret_id}",
        'attributes': {
            'enabled': True,
            'created': int(time.time()),
            'updated': int(time.time())
        }
    }

    with _lock:
        SECRETS[secret_name] = secret_data

    generate_keyvault_log("SecretSet", "Success", request.remote_addr, secret_name=secret_name)

    return jsonify({
        'value': data['value'],
        'id': secret_data['id'],
        'attributes': secret_data['attributes']
    })


# ============================================
# ADMIN ENDPOINTS (for seeder)
# ============================================

@app.route('/admin/tokens', methods=['GET', 'POST', 'DELETE'])
def admin_tokens():
    """
    Manage valid tokens that KeyVault will accept.

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
        print(f"KEYVAULT_ADMIN: Injected {len(tokens)} valid token(s)")
        return jsonify({"status": "ok", "tokens_count": len(VALID_TOKENS)})

    elif request.method == 'DELETE':
        count = len(VALID_TOKENS)
        VALID_TOKENS.clear()
        print(f"KEYVAULT_ADMIN: Cleared {count} token(s)")
        return jsonify({"status": "ok", "cleared": count})

    else:  # GET
        return jsonify({"tokens_count": len(VALID_TOKENS)})


# ============================================
# AUDIT & HEALTH
# ============================================

@app.route('/audit/logs', methods=['GET'])
def get_audit_logs():
    """Get audit logs in Azure Key Vault AuditEvent format."""
    with _lock:
        logs_copy = list(AUDIT_LOGS)
    return jsonify({'value': logs_copy, 'count': len(logs_copy)})


@app.route('/health', methods=['GET'])
@app.route('/healthz', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'vault': VAULT_NAME})


if __name__ == '__main__':
    print(f"Starting Azure Key Vault mock for {VAULT_NAME}")
    app.run(host='0.0.0.0', port=443, ssl_context='adhoc')
