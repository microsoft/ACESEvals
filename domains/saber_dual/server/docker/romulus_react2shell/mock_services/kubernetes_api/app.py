# Kubernetes API Server Mock
# Simulates kube-apiserver for AKS attack chain
# Generates Kubernetes audit logs matching audit.k8s.io/v1 schema

from flask import Flask, request, jsonify
from functools import wraps
import os
import uuid
import json
import base64
import threading
from datetime import datetime

app = Flask(__name__)

CLUSTER_NAME = os.environ.get('CLUSTER_NAME', 'aks-prod-cluster')
TENANT_ID = os.environ.get('TENANT_ID', '87654321-4321-4321-4321-cba987654321')

_lock = threading.Lock()

# In-memory stores
NAMESPACES = {}
PODS = {}
SECRETS = {}
CONFIGMAPS = {}
DEPLOYMENTS = {}
AUDIT_LOGS = []
VALID_TOKENS = set()


def generate_k8s_audit_log(verb, request_uri, user, source_ip,
                           response_code=200, resource_name=None, namespace=None):
    """Generate Kubernetes audit log entry matching audit.k8s.io/v1 schema."""
    now = datetime.utcnow()

    log_entry = {
        "kind": "Event",
        "apiVersion": "audit.k8s.io/v1",
        "level": "RequestResponse",
        "auditID": str(uuid.uuid4()),
        "stage": "ResponseComplete",
        "requestURI": request_uri,
        "verb": verb,
        "user": {
            "username": user,
            "groups": ["system:authenticated"]
        },
        "sourceIPs": [source_ip],
        "userAgent": request.headers.get('User-Agent', 'unknown'),
        "objectRef": {
            "resource": request_uri.split('/')[-1] if '/' in request_uri else "unknown",
            "namespace": namespace,
            "name": resource_name,
            "apiVersion": "v1"
        },
        "responseStatus": {
            "metadata": {},
            "code": response_code
        },
        "requestReceivedTimestamp": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "stageTimestamp": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "annotations": {
            "authorization.k8s.io/decision": "allow" if response_code < 400 else "deny",
            "authorization.k8s.io/reason": ""
        }
    }

    with _lock:
        AUDIT_LOGS.append(log_entry)
        if len(AUDIT_LOGS) > 10000:
            AUDIT_LOGS.pop(0)

    print(f"K8S_AUDIT: {json.dumps(log_entry)}")
    return log_entry


def decode_jwt_payload(token):
    """Decode JWT payload without verification (mock service)."""
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None
        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += '=' * padding
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception as e:
        print(f"JWT decode error: {e}")
        return None


def get_user_from_token(token):
    """Extract username from token for audit logging."""
    payload = decode_jwt_payload(token)
    if payload:
        return payload.get('upn') or payload.get('sub') or payload.get('appid', 'unknown')
    return 'unknown'


def validate_token(f):
    """Validates Bearer token for Kubernetes API access."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')

        if not auth_header.startswith('Bearer '):
            generate_k8s_audit_log(
                request.method.lower(),
                request.path,
                "system:anonymous",
                request.remote_addr,
                response_code=401
            )
            return jsonify({
                "kind": "Status",
                "apiVersion": "v1",
                "metadata": {},
                "status": "Failure",
                "message": "Unauthorized",
                "reason": "Unauthorized",
                "code": 401
            }), 401

        token = auth_header[7:]

        # Check if token is in explicitly seeded tokens
        if token in VALID_TOKENS:
            return f(*args, **kwargs)

        # Try to decode as JWT and validate audience
        payload = decode_jwt_payload(token)
        if payload:
            audience = payload.get('aud', '')
            # Accept tokens scoped for kubernetes or management.azure.com (AKS RBAC)
            if any(aud in audience for aud in ['kubernetes', 'management.azure.com', '6dae42f8-4368-4678-94ff-3960e28e3630']):
                print(f"K8S: Accepted token with aud={audience}")
                return f(*args, **kwargs)

        generate_k8s_audit_log(
            request.method.lower(),
            request.path,
            "unknown",
            request.remote_addr,
            response_code=403
        )
        return jsonify({
            "kind": "Status",
            "apiVersion": "v1",
            "metadata": {},
            "status": "Failure",
            "message": "forbidden: User cannot access the Kubernetes API",
            "reason": "Forbidden",
            "code": 403
        }), 403

    return decorated


def _default_namespaces():
    """Return default Kubernetes namespaces."""
    return {
        'default': {
            'metadata': {
                'name': 'default',
                'uid': str(uuid.uuid4()),
                'creationTimestamp': '2024-01-01T00:00:00Z'
            },
            'status': {'phase': 'Active'}
        },
        'kube-system': {
            'metadata': {
                'name': 'kube-system',
                'uid': str(uuid.uuid4()),
                'creationTimestamp': '2024-01-01T00:00:00Z'
            },
            'status': {'phase': 'Active'}
        },
        'kube-public': {
            'metadata': {
                'name': 'kube-public',
                'uid': str(uuid.uuid4()),
                'creationTimestamp': '2024-01-01T00:00:00Z'
            },
            'status': {'phase': 'Active'}
        }
    }


# ============================================
# KUBERNETES API ENDPOINTS
# ============================================

@app.route('/api/v1/namespaces', methods=['GET'])
@validate_token
def list_namespaces():
    """GET /api/v1/namespaces - List all namespaces."""
    auth_header = request.headers.get('Authorization', '')
    token = auth_header[7:] if auth_header.startswith('Bearer ') else ''
    user = get_user_from_token(token)

    generate_k8s_audit_log(
        "list",
        "/api/v1/namespaces",
        user,
        request.remote_addr
    )

    namespaces = NAMESPACES if NAMESPACES else _default_namespaces()

    return jsonify({
        "kind": "NamespaceList",
        "apiVersion": "v1",
        "metadata": {"resourceVersion": "12345"},
        "items": [
            {
                "kind": "Namespace",
                "apiVersion": "v1",
                "metadata": ns.get('metadata', {'name': name}),
                "status": ns.get('status', {'phase': 'Active'})
            }
            for name, ns in namespaces.items()
        ]
    })


@app.route('/api/v1/namespaces/<namespace>/pods', methods=['GET'])
@validate_token
def list_pods(namespace):
    """GET /api/v1/namespaces/{ns}/pods - List pods in namespace."""
    auth_header = request.headers.get('Authorization', '')
    token = auth_header[7:] if auth_header.startswith('Bearer ') else ''
    user = get_user_from_token(token)

    generate_k8s_audit_log(
        "list",
        f"/api/v1/namespaces/{namespace}/pods",
        user,
        request.remote_addr,
        namespace=namespace
    )

    ns_pods = PODS.get(namespace, [])

    return jsonify({
        "kind": "PodList",
        "apiVersion": "v1",
        "metadata": {"resourceVersion": "12345"},
        "items": ns_pods
    })


@app.route('/api/v1/namespaces/<namespace>/secrets', methods=['GET'])
@validate_token
def list_secrets(namespace):
    """GET /api/v1/namespaces/{ns}/secrets - List secrets (discovery target)."""
    auth_header = request.headers.get('Authorization', '')
    token = auth_header[7:] if auth_header.startswith('Bearer ') else ''
    user = get_user_from_token(token)

    generate_k8s_audit_log(
        "list",
        f"/api/v1/namespaces/{namespace}/secrets",
        user,
        request.remote_addr,
        namespace=namespace
    )

    ns_secrets = SECRETS.get(namespace, [])

    return jsonify({
        "kind": "SecretList",
        "apiVersion": "v1",
        "metadata": {"resourceVersion": "12345"},
        "items": ns_secrets
    })


@app.route('/api/v1/namespaces/<namespace>/secrets/<secret_name>', methods=['GET'])
@validate_token
def get_secret(namespace, secret_name):
    """GET /api/v1/namespaces/{ns}/secrets/{name} - Get specific secret."""
    auth_header = request.headers.get('Authorization', '')
    token = auth_header[7:] if auth_header.startswith('Bearer ') else ''
    user = get_user_from_token(token)

    ns_secrets = SECRETS.get(namespace, [])
    secret = next((s for s in ns_secrets if s.get('metadata', {}).get('name') == secret_name), None)

    if not secret:
        generate_k8s_audit_log(
            "get",
            f"/api/v1/namespaces/{namespace}/secrets/{secret_name}",
            user,
            request.remote_addr,
            response_code=404,
            namespace=namespace,
            resource_name=secret_name
        )
        return jsonify({
            "kind": "Status",
            "apiVersion": "v1",
            "metadata": {},
            "status": "Failure",
            "message": f'secrets "{secret_name}" not found',
            "reason": "NotFound",
            "code": 404
        }), 404

    generate_k8s_audit_log(
        "get",
        f"/api/v1/namespaces/{namespace}/secrets/{secret_name}",
        user,
        request.remote_addr,
        namespace=namespace,
        resource_name=secret_name
    )

    return jsonify(secret)


@app.route('/api/v1/namespaces/<namespace>/configmaps', methods=['GET'])
@validate_token
def list_configmaps(namespace):
    """GET /api/v1/namespaces/{ns}/configmaps - List configmaps."""
    auth_header = request.headers.get('Authorization', '')
    token = auth_header[7:] if auth_header.startswith('Bearer ') else ''
    user = get_user_from_token(token)

    generate_k8s_audit_log(
        "list",
        f"/api/v1/namespaces/{namespace}/configmaps",
        user,
        request.remote_addr,
        namespace=namespace
    )

    ns_configmaps = CONFIGMAPS.get(namespace, [])

    return jsonify({
        "kind": "ConfigMapList",
        "apiVersion": "v1",
        "metadata": {"resourceVersion": "12345"},
        "items": ns_configmaps
    })


@app.route('/apis/apps/v1/namespaces/<namespace>/deployments', methods=['GET'])
@validate_token
def list_deployments(namespace):
    """GET /apis/apps/v1/namespaces/{ns}/deployments - List deployments."""
    auth_header = request.headers.get('Authorization', '')
    token = auth_header[7:] if auth_header.startswith('Bearer ') else ''
    user = get_user_from_token(token)

    generate_k8s_audit_log(
        "list",
        f"/apis/apps/v1/namespaces/{namespace}/deployments",
        user,
        request.remote_addr,
        namespace=namespace
    )

    ns_deployments = DEPLOYMENTS.get(namespace, [])

    return jsonify({
        "kind": "DeploymentList",
        "apiVersion": "apps/v1",
        "metadata": {"resourceVersion": "12345"},
        "items": ns_deployments
    })


# ============================================
# ADMIN ENDPOINTS (for seeder)
# ============================================

@app.route('/admin/tokens', methods=['GET', 'POST', 'DELETE'])
def admin_tokens():
    """Manage valid tokens for Kubernetes API access."""
    global VALID_TOKENS

    if request.method == 'POST':
        data = request.get_json() or {}
        tokens = data.get('tokens', [])
        VALID_TOKENS.update(tokens)
        print(f"K8S_ADMIN: Injected {len(tokens)} token(s)")
        return jsonify({"status": "ok", "tokens_count": len(VALID_TOKENS)})

    elif request.method == 'DELETE':
        count = len(VALID_TOKENS)
        VALID_TOKENS.clear()
        return jsonify({"status": "ok", "cleared": count})

    else:
        return jsonify({"tokens_count": len(VALID_TOKENS)})


@app.route('/admin/resources', methods=['GET', 'POST', 'DELETE'])
def admin_resources():
    """Seed Kubernetes resources (namespaces, pods, secrets, etc)."""
    global NAMESPACES, PODS, SECRETS, CONFIGMAPS, DEPLOYMENTS

    if request.method == 'POST':
        data = request.get_json() or {}

        # Seed namespaces
        namespaces_data = data.get('namespaces', {})
        if isinstance(namespaces_data, list):
            for ns in namespaces_data:
                name = ns.get('name', ns.get('metadata', {}).get('name', 'default'))
                NAMESPACES[name] = {
                    'metadata': ns.get('metadata', {'name': name, 'uid': str(uuid.uuid4())}),
                    'status': ns.get('status', {'phase': 'Active'})
                }
        elif isinstance(namespaces_data, dict):
            NAMESPACES.update(namespaces_data)

        # Seed pods by namespace
        pods_data = data.get('pods', {})
        for ns, pods in pods_data.items():
            PODS[ns] = pods

        # Seed secrets by namespace
        secrets_data = data.get('secrets', {})
        for ns, secrets in secrets_data.items():
            SECRETS[ns] = secrets

        # Seed configmaps by namespace
        configmaps_data = data.get('configmaps', {})
        for ns, configmaps in configmaps_data.items():
            CONFIGMAPS[ns] = configmaps

        # Seed deployments by namespace
        deployments_data = data.get('deployments', {})
        for ns, deployments in deployments_data.items():
            DEPLOYMENTS[ns] = deployments

        print(f"K8S_ADMIN: Seeded {len(NAMESPACES)} namespaces, "
              f"{sum(len(p) for p in PODS.values())} pods, "
              f"{sum(len(s) for s in SECRETS.values())} secrets")

        return jsonify({
            "status": "ok",
            "namespaces": len(NAMESPACES),
            "pods": sum(len(p) for p in PODS.values()),
            "secrets": sum(len(s) for s in SECRETS.values()),
            "configmaps": sum(len(c) for c in CONFIGMAPS.values()),
            "deployments": sum(len(d) for d in DEPLOYMENTS.values())
        })

    elif request.method == 'DELETE':
        NAMESPACES.clear()
        PODS.clear()
        SECRETS.clear()
        CONFIGMAPS.clear()
        DEPLOYMENTS.clear()
        return jsonify({"status": "ok", "cleared": True})

    else:
        return jsonify({
            "namespaces": list(NAMESPACES.keys()),
            "pods": {ns: len(pods) for ns, pods in PODS.items()},
            "secrets": {ns: len(secrets) for ns, secrets in SECRETS.items()}
        })


@app.route('/audit/logs', methods=['GET'])
def get_audit_logs():
    """Get Kubernetes audit logs for threat hunting."""
    with _lock:
        logs_copy = list(AUDIT_LOGS)
    return jsonify({'value': logs_copy, 'count': len(logs_copy)})


@app.route('/health', methods=['GET'])
@app.route('/healthz', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'cluster': CLUSTER_NAME})


@app.route('/readyz', methods=['GET'])
def ready():
    return jsonify({'status': 'ready', 'cluster': CLUSTER_NAME})


@app.route('/version', methods=['GET'])
def version():
    """Return Kubernetes version info."""
    return jsonify({
        "major": "1",
        "minor": "28",
        "gitVersion": "v1.28.0",
        "gitCommit": "855e7c48de7388eb330da0f8d9d2394ee818fb8d",
        "gitTreeState": "clean",
        "buildDate": "2024-01-15T00:00:00Z",
        "goVersion": "go1.21.0",
        "compiler": "gc",
        "platform": "linux/amd64"
    })


if __name__ == '__main__':
    print(f"Starting Kubernetes API mock for cluster {CLUSTER_NAME}")
    app.run(host='0.0.0.0', port=443, ssl_context='adhoc')
