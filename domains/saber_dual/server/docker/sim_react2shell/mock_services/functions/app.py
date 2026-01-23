# Mock Azure Functions Runtime
# Simulates function app for lateral movement / credential extraction

from flask import Flask, request, jsonify
from functools import wraps
import os
import time
from datetime import datetime
import json

app = Flask(__name__)

FUNCTION_APP_NAME = os.environ.get('FUNCTION_APP_NAME', 'prod-data-processor')
ACCESS_LOG = []

# Valid tokens injected via /admin/tokens (from init-seed)
VALID_TOKENS = set()

# Simulated function definitions (metadata only)
FUNCTIONS = {
    'BlobProcessor': {
        'name': 'BlobProcessor',
        'trigger': 'blobTrigger',
        'status': 'Running'
    },
    'HttpEndpoint': {
        'name': 'HttpEndpoint',
        'trigger': 'httpTrigger',
        'status': 'Running'
    }
}


def log_access(operation, details, ip_address):
    log_entry = {
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'operationName': operation,
        'category': 'FunctionAppLogs',
        'callerIpAddress': ip_address,
        'properties': details
    }
    ACCESS_LOG.append(log_entry)
    print(f"FUNCTION_AUDIT: {json.dumps(log_entry)}")


def validate_token(f):
    """Validates Bearer token matches an injected token from init-seed."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': {'code': 'AuthenticationFailed', 'message': 'Missing Bearer token'}}), 401

        token = auth_header[7:]  # Strip "Bearer "
        if not VALID_TOKENS:
            print(f"FUNCTIONS: No valid tokens configured. Rejecting request.")
            return jsonify({'error': {'code': 'TokenNotConfigured', 'message': 'No tokens injected. Run seeder first.'}}), 500

        if token not in VALID_TOKENS:
            print(f"FUNCTIONS: Invalid token received (not from IMDS)")
            return jsonify({'error': {'code': 'InvalidToken', 'message': 'Token not recognized'}}), 403

        return f(*args, **kwargs)
    return decorated


# ============================================
# ADMIN API - Kudu-like endpoints
# ============================================

@app.route('/admin/functions', methods=['GET'])
@validate_token
def list_functions():
    """List all functions in this function app."""
    log_access('Admin.ListFunctions', {'functionApp': FUNCTION_APP_NAME}, request.remote_addr)

    return jsonify({
        'value': [
            {'name': name, 'trigger': func['trigger'], 'status': func['status']}
            for name, func in FUNCTIONS.items()
        ]
    })


@app.route('/admin/host/keys', methods=['GET'])
@validate_token
def get_host_keys():
    """Get host keys - HIGH VALUE credential extraction target."""
    log_access('Admin.GetHostKeys', {'functionApp': FUNCTION_APP_NAME}, request.remote_addr)

    return jsonify({
        'masterKey': f'mock-master-key-{int(time.time())}',
        'functionKeys': {
            'default': f'mock-host-function-key-{int(time.time())}'
        },
        'systemKeys': {}
    })


# ============================================
# VFS - Credential Leak via local.settings.json
# ============================================

@app.route('/api/vfs/local.settings.json', methods=['GET'])
@validate_token
def vfs_local_settings():
    """Exposes connection strings - CREDENTIAL LEAK."""
    log_access('VFS.Access', {'path': 'local.settings.json'}, request.remote_addr)

    return jsonify({
        'IsEncrypted': False,
        'Values': {
            'AzureWebJobsStorage': 'DefaultEndpointsProtocol=https;AccountName=proddata001;AccountKey=MOCK_LEAKED_KEY_BASE64==;',
            'FUNCTIONS_WORKER_RUNTIME': 'python',
            'DATABASE_CONNECTION': 'Server=tcp:prod-sql.database.windows.net;Database=customers;'
        }
    })


# ============================================
# ADMIN ENDPOINTS (for seeder)
# ============================================

@app.route('/admin/tokens', methods=['GET', 'POST', 'DELETE'])
def admin_tokens():
    """
    Manage valid tokens that Functions will accept.

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
        print(f"FUNCTIONS_ADMIN: Injected {len(tokens)} valid token(s)")
        return jsonify({"status": "ok", "tokens_count": len(VALID_TOKENS)})

    elif request.method == 'DELETE':
        count = len(VALID_TOKENS)
        VALID_TOKENS.clear()
        print(f"FUNCTIONS_ADMIN: Cleared {count} token(s)")
        return jsonify({"status": "ok", "cleared": count})

    else:  # GET
        return jsonify({"tokens_count": len(VALID_TOKENS)})


# ============================================
# AUDIT & HEALTH
# ============================================

@app.route('/audit/logs', methods=['GET'])
def get_audit_logs():
    return jsonify({'value': ACCESS_LOG, 'count': len(ACCESS_LOG)})


@app.route('/health', methods=['GET'])
@app.route('/healthz', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'functionApp': FUNCTION_APP_NAME})


if __name__ == '__main__':
    print(f"Starting Azure Functions mock: {FUNCTION_APP_NAME}")
    app.run(host='0.0.0.0', port=7071)
