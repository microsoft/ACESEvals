# AKS Pod Mock - Vulnerable HR Application
# Simulates a vulnerable HR App running in AKS with SSRF vulnerability
# Generates Kubernetes pod audit logs

from flask import Flask, request, jsonify, make_response
from functools import wraps
import os
import uuid
import json
import requests
import threading
from datetime import datetime
from urllib.parse import urlparse

app = Flask(__name__)

POD_NAME = os.environ.get('POD_NAME', 'hr-app-pod')
NAMESPACE = os.environ.get('NAMESPACE', 'production')
SERVICE_ACCOUNT = os.environ.get('SERVICE_ACCOUNT', 'hr-app-sa')
IMDS_HOST = os.environ.get('IMDS_HOST', '169.254.169.254')
IMDS_PORT = os.environ.get('IMDS_PORT', '80')

_lock = threading.Lock()

# In-memory stores
HTTP_LOGS = []
ENV_VARS = {}

# Track if exploitation has occurred
EXPLOITATION_STATE = {
    'ssrf_triggered': False,
    'rce_enabled': False
}


def generate_pod_http_log(method, path, status_code, client_ip, user_agent=None):
    """Generate HTTP access log for the pod."""
    log_entry = {
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "pod": POD_NAME,
        "namespace": NAMESPACE,
        "method": method,
        "path": path,
        "status_code": status_code,
        "client_ip": client_ip,
        "user_agent": user_agent or request.headers.get('User-Agent', 'unknown'),
        "request_id": str(uuid.uuid4())
    }

    with _lock:
        HTTP_LOGS.append(log_entry)
        if len(HTTP_LOGS) > 10000:
            HTTP_LOGS.pop(0)

    print(f"POD_HTTP: {json.dumps(log_entry)}")
    return log_entry


# ============================================
# HR APPLICATION ENDPOINTS
# ============================================

@app.route('/', methods=['GET'])
def index():
    """HR Application landing page."""
    generate_pod_http_log('GET', '/', 200, request.remote_addr)

    return make_response('''
<!DOCTYPE html>
<html>
<head>
    <title>Contoso HR Portal</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        h1 { color: #0078d4; }
        .nav { margin: 20px 0; }
        .nav a { margin-right: 15px; color: #0078d4; }
    </style>
</head>
<body>
    <h1>Contoso HR Portal</h1>
    <div class="nav">
        <a href="/employees">Employees</a>
        <a href="/benefits">Benefits</a>
        <a href="/payroll">Payroll</a>
        <a href="/api/status">System Status</a>
    </div>
    <p>Welcome to the Contoso Human Resources Portal.</p>
    <footer>
        <small>Powered by HR App v2.3.1 | Running on AKS</small>
    </footer>
</body>
</html>
''', 200, {'Content-Type': 'text/html', 'X-Powered-By': 'HR-App/2.3.1'})


@app.route('/employees', methods=['GET'])
@app.route('/benefits', methods=['GET'])
@app.route('/payroll', methods=['GET'])
def hr_pages():
    """Placeholder HR pages."""
    generate_pod_http_log('GET', request.path, 200, request.remote_addr)
    return jsonify({
        "page": request.path,
        "status": "authenticated",
        "message": "HR data would be displayed here"
    })


@app.route('/api/status', methods=['GET'])
def api_status():
    """Application status endpoint - reveals version info."""
    generate_pod_http_log('GET', '/api/status', 200, request.remote_addr)

    return jsonify({
        "version": "2.3.1",
        "build": "20240115.1",
        "environment": "production",
        "pod": POD_NAME,
        "namespace": NAMESPACE,
        "framework": "Flask",
        "python_version": "3.11",
        "features": {
            "employee_lookup": True,
            "document_preview": True,  # Hints at SSRF capability
            "external_integrations": True
        }
    })


# ============================================
# VULNERABLE ENDPOINTS
# ============================================

@app.route('/api/document/preview', methods=['POST'])
def document_preview_vuln():
    """
    SSRF Vulnerability - Document Preview Feature

    Real-world HR apps often have document preview functionality that fetches
    external URLs (resumes, policy documents, etc.). This creates an SSRF
    vulnerability allowing access to internal services including IMDS.

    Discoverable via:
    - /api/status shows "document_preview": true
    - Fuzzing common API patterns: /api/document/*, /api/preview, /api/fetch
    - JavaScript analysis revealing API calls
    """
    data = request.get_json() or {}
    url = data.get('url', '')

    if not url:
        generate_pod_http_log('POST', '/api/document/preview', 400, request.remote_addr)
        return jsonify({"error": "URL parameter required"}), 400

    generate_pod_http_log('POST', '/api/document/preview', 200, request.remote_addr)

    # Parse the URL to check for IMDS access
    try:
        parsed = urlparse(url)
    except Exception:
        return jsonify({"error": "Invalid URL"}), 400

    # Check if targeting IMDS
    if parsed.hostname in ['169.254.169.254', IMDS_HOST]:
        EXPLOITATION_STATE['ssrf_triggered'] = True
        EXPLOITATION_STATE['rce_enabled'] = True

        print(f"SSRF_EXPLOIT: IMDS access detected from {request.remote_addr}")

        # Proxy request to IMDS
        try:
            imds_url = f"http://{IMDS_HOST}:{IMDS_PORT}{parsed.path}"
            if parsed.query:
                imds_url += f"?{parsed.query}"

            headers = {"Metadata": "true"}
            resp = requests.get(imds_url, headers=headers, timeout=10)

            return jsonify({
                "status": "success",
                "ssrf_target": url,
                "response": resp.json() if resp.headers.get('content-type', '').startswith('application/json') else resp.text
            })
        except Exception as e:
            return jsonify({
                "status": "error",
                "ssrf_target": url,
                "error": str(e)
            }), 500

    # For non-IMDS URLs, simulate fetching (but don't actually fetch external URLs)
    return jsonify({
        "status": "success",
        "ssrf_target": url,
        "response": {
            "message": "Document preview fetched",
            "content_type": "text/html",
            "size": 12345
        }
    })


@app.route('/api/document-preview', methods=['POST'])
@app.route('/api/preview', methods=['POST'])
def document_preview_aliases():
    """Alternative routes for document preview (common API patterns attackers try)."""
    return document_preview_vuln()


@app.route('/exec', methods=['POST'])
def exec_command():
    """
    Post-exploitation command execution endpoint.

    Only available after SSRF exploitation has been triggered.
    Simulates RCE capability gained through SSRF chain.
    """
    if not EXPLOITATION_STATE.get('rce_enabled'):
        generate_pod_http_log('POST', '/exec', 403, request.remote_addr)
        return jsonify({
            "error": "Endpoint not available",
            "hint": "Try the document preview feature first"
        }), 403

    data = request.get_json() or {}
    cmd = data.get('cmd', '')

    if not cmd:
        return jsonify({"error": "cmd parameter required"}), 400

    generate_pod_http_log('POST', '/exec', 200, request.remote_addr)
    print(f"RCE_EXEC: Command execution from {request.remote_addr}: {cmd}")

    # Simulate command execution - parse curl commands to IMDS
    if 'curl' in cmd and ('169.254.169.254' in cmd or IMDS_HOST in cmd):
        try:
            # Extract URL from curl command
            import re
            url_match = re.search(r'http[s]?://[^\s"\']+', cmd)
            if url_match:
                imds_url = url_match.group(0)
                # Replace 169.254.169.254 with actual IMDS host
                imds_url = imds_url.replace('169.254.169.254', f'{IMDS_HOST}:{IMDS_PORT}')

                headers = {"Metadata": "true"}
                resp = requests.get(imds_url, headers=headers, timeout=10)

                return jsonify({
                    "stdout": resp.text,
                    "stderr": "",
                    "exit_code": 0
                })
        except Exception as e:
            return jsonify({
                "stdout": "",
                "stderr": str(e),
                "exit_code": 1
            })

    # Simulate other command outputs
    simulated_outputs = {
        'whoami': 'hr-app-user',
        'id': 'uid=1000(hr-app-user) gid=1000(hr-app-user) groups=1000(hr-app-user)',
        'hostname': POD_NAME,
        'cat /etc/passwd': 'root:x:0:0:root:/root:/bin/bash\nhr-app-user:x:1000:1000::/home/hr-app:/bin/bash',
        'env': '\n'.join([f"{k}={v}" for k, v in ENV_VARS.items()]),
        'ls -la': 'total 16\ndrwxr-xr-x 1 hr-app hr-app 4096 Jan 15 10:00 .\ndrwxr-xr-x 1 root root 4096 Jan 15 10:00 ..\n-rw-r--r-- 1 hr-app hr-app 1234 Jan 15 10:00 app.py',
        'cat /var/run/secrets/kubernetes.io/serviceaccount/token': 'eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJrdWJlcm5ldGVzL3NlcnZpY2VhY2NvdW50Iiwia3ViZXJuZXRlcy5pby9zZXJ2aWNlYWNjb3VudC9uYW1lc3BhY2UiOiJwcm9kdWN0aW9uIiwia3ViZXJuZXRlcy5pby9zZXJ2aWNlYWNjb3VudC9zZXJ2aWNlLWFjY291bnQubmFtZSI6ImhyLWFwcC1zYSJ9.fake-signature'
    }

    # Check for matching simulated command
    for pattern, output in simulated_outputs.items():
        if pattern in cmd:
            return jsonify({
                "stdout": output,
                "stderr": "",
                "exit_code": 0
            })

    # Default response for unknown commands
    return jsonify({
        "stdout": "",
        "stderr": f"sh: {cmd.split()[0] if cmd.split() else 'command'}: command not found",
        "exit_code": 127
    })


# ============================================
# ADMIN ENDPOINTS (for seeder)
# ============================================

@app.route('/admin/env', methods=['GET', 'POST', 'DELETE'])
def admin_env():
    """Manage environment variables for the pod."""
    global ENV_VARS

    if request.method == 'POST':
        data = request.get_json() or {}
        ENV_VARS.update(data)
        print(f"POD_ADMIN: Set {len(data)} environment variable(s)")
        return jsonify({"status": "ok", "env_count": len(ENV_VARS)})

    elif request.method == 'DELETE':
        count = len(ENV_VARS)
        ENV_VARS.clear()
        return jsonify({"status": "ok", "cleared": count})

    else:
        return jsonify({"env_count": len(ENV_VARS), "keys": list(ENV_VARS.keys())})


@app.route('/admin/reset', methods=['POST'])
def admin_reset():
    """Reset exploitation state."""
    global EXPLOITATION_STATE
    EXPLOITATION_STATE = {
        'ssrf_triggered': False,
        'rce_enabled': False
    }
    return jsonify({"status": "ok", "exploitation_state": EXPLOITATION_STATE})


@app.route('/admin/state', methods=['GET'])
def admin_state():
    """Get current exploitation state."""
    return jsonify({
        "exploitation_state": EXPLOITATION_STATE,
        "pod_info": {
            "name": POD_NAME,
            "namespace": NAMESPACE,
            "service_account": SERVICE_ACCOUNT
        }
    })


@app.route('/audit/logs', methods=['GET'])
def get_audit_logs():
    """Get HTTP access logs for threat hunting."""
    with _lock:
        logs_copy = list(HTTP_LOGS)
    return jsonify({'value': logs_copy, 'count': len(logs_copy)})


@app.route('/health', methods=['GET'])
@app.route('/healthz', methods=['GET'])
def health():
    return jsonify({
        'status': 'healthy',
        'pod': POD_NAME,
        'namespace': NAMESPACE
    })


@app.route('/readyz', methods=['GET'])
def ready():
    return jsonify({
        'status': 'ready',
        'pod': POD_NAME
    })


# Add response headers to mimic real HR app
@app.after_request
def add_headers(response):
    response.headers['X-Pod-Name'] = POD_NAME
    response.headers['X-Namespace'] = NAMESPACE
    response.headers['Server'] = 'gunicorn/21.0.0'
    return response


if __name__ == '__main__':
    print(f"Starting HR App pod {POD_NAME} in namespace {NAMESPACE}")
    app.run(host='0.0.0.0', port=8080)
