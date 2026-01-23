"""
Mock Azure Front Door with Web Application Firewall (WAF)
Simulates Azure Front Door Premium with WAF policy for attack detection/prevention.

Generates two log types:
- FrontDoorAccessLog: All HTTP requests
- FrontDoorWebApplicationFirewallLog: WAF rule matches
"""

import os
import re
import json
import time
import uuid
import yaml
import threading
from datetime import datetime, timezone
from flask import Flask, request, jsonify, Response
import requests as http_requests

app = Flask(__name__)

# Thread lock for shared state
_lock = threading.Lock()

# Configuration from environment
BACKEND_URL = os.environ.get("BACKEND_URL", "http://172.30.20.10:8080")
WAF_MODE = os.environ.get("WAF_MODE", "Detection").lower()  # detection or prevention
SUBSCRIPTION_ID = os.environ.get("SUBSCRIPTION_ID", "12345678-1234-1234-1234-123456789abc")
RESOURCE_GROUP = os.environ.get("RESOURCE_GROUP", "production-rg")
PROFILE_NAME = os.environ.get("PROFILE_NAME", "prod-frontdoor")
ENDPOINT_NAME = os.environ.get("ENDPOINT_NAME", "prod-webapp.azurefd.net")
WAF_POLICY_NAME = os.environ.get("WAF_POLICY_NAME", "React2ShellWAFPolicy")
POP_LOCATION = os.environ.get("POP_LOCATION", "EUS")  # East US

# Log storage
ACCESS_LOGS = []
WAF_LOGS = []
MAX_LOGS = 10000

# WAF Rules loaded from YAML
WAF_RULES = []


def load_waf_rules():
    """Load WAF rules from YAML file."""
    global WAF_RULES
    rules_path = "/app/waf_rules.yaml"
    try:
        if os.path.exists(rules_path):
            with open(rules_path, "r") as f:
                config = yaml.safe_load(f)
                WAF_RULES = config.get("rules", [])
                print(f"[FRONT_DOOR] Loaded {len(WAF_RULES)} WAF rules")
        else:
            # Default rules if file not found
            WAF_RULES = get_default_rules()
            print(f"[FRONT_DOOR] Using {len(WAF_RULES)} default WAF rules")
    except Exception as e:
        print(f"[FRONT_DOOR] Error loading WAF rules: {e}")
        WAF_RULES = get_default_rules()


def get_default_rules():
    """Return default WAF rules."""
    return [
        {
            "id": "CUSTOM-001",
            "name": "Prototype Pollution Attempt",
            "pattern": r"__proto__|constructor\.prototype",
            "action": "Block",
            "category": "CUSTOM",
        },
        {
            "id": "942100",
            "name": "SQL Injection Attack Detected",
            "pattern": r"(?i)(union.*select|select.*from|insert.*into|delete.*from|drop\s+table)",
            "action": "Block",
            "category": "SQLI",
        },
        {
            "id": "941100",
            "name": "XSS Attack Detected",
            "pattern": r"<script|javascript:|onerror\s*=|onload\s*=",
            "action": "Block",
            "category": "XSS",
        },
        {
            "id": "920350",
            "name": "Suspicious User-Agent Detected",
            "pattern": r"(curl|wget|python-requests|nikto|sqlmap|nmap)",
            "action": "Log",
            "category": "SCANNER",
        },
    ]


def generate_tracking_reference():
    """Generate a unique tracking reference like Azure Front Door."""
    return f"0{uuid.uuid4().hex[:20].upper()}"


def generate_resource_id():
    """Generate Azure resource ID for Front Door profile."""
    return f"/SUBSCRIPTIONS/{SUBSCRIPTION_ID}/RESOURCEGROUPS/{RESOURCE_GROUP}/PROVIDERS/MICROSOFT.CDN/PROFILES/{PROFILE_NAME}"


def log_access(
    tracking_ref: str,
    method: str,
    uri: str,
    host: str,
    status_code: int,
    request_bytes: int,
    response_bytes: int,
    time_taken: float,
    time_to_first_byte: float,
    client_ip: str,
    client_port: int,
    user_agent: str,
    referrer: str,
    origin_url: str,
    origin_ip: str,
    error_info: str = "NoError",
):
    """Generate FrontDoorAccessLog entry."""
    log_entry = {
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "resourceId": generate_resource_id(),
        "category": "FrontDoorAccessLog",
        "operationName": "Microsoft.Cdn/Profiles/FrontDoorAccessLog/Write",
        "properties": {
            "trackingReference": tracking_ref,
            "httpMethod": method,
            "httpVersion": "HTTP/1.1",
            "requestUri": uri,
            "hostName": host,
            "requestBytes": request_bytes,
            "responseBytes": response_bytes,
            "userAgent": user_agent,
            "referrer": referrer or "",
            "clientIp": client_ip,
            "socketIp": client_ip,
            "clientPort": client_port,
            "timeTaken": round(time_taken, 3),
            "timeToFirstByte": round(time_to_first_byte, 3),
            "requestProtocol": "HTTP",
            "securityProtocol": None,
            "securityCipher": None,
            "sni": None,
            "endpoint": ENDPOINT_NAME,
            "httpStatusCode": status_code,
            "pop": POP_LOCATION,
            "cacheStatus": "MISS",
            "routeName": "default-route",
            "matchedRulesSetName": "",
            "originUrl": origin_url,
            "originIp": origin_ip,
            "originName": "app-service-origin",
            "errorInfo": error_info,
            "result": "",
        },
    }

    with _lock:
        ACCESS_LOGS.append(log_entry)
        if len(ACCESS_LOGS) > MAX_LOGS:
            ACCESS_LOGS.pop(0)

    print(f"FRONTDOOR_ACCESS: {json.dumps(log_entry)}")
    return log_entry


def log_waf_match(
    tracking_ref: str,
    client_ip: str,
    client_port: int,
    request_uri: str,
    host: str,
    rule_id: str,
    rule_name: str,
    action: str,
    match_variable_name: str,
    match_variable_value: str,
):
    """Generate FrontDoorWebApplicationFirewallLog entry."""
    log_entry = {
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "resourceId": generate_resource_id(),
        "category": "FrontDoorWebApplicationFirewallLog",
        "operationName": "Microsoft.Network/FrontDoorWebApplicationFirewallLog/Write",
        "properties": {
            "trackingReference": tracking_ref,
            "clientIP": client_ip,
            "clientPort": str(client_port),
            "socketIP": client_ip,
            "requestUri": request_uri,
            "ruleName": f"{rule_name}-{rule_id}",
            "policy": WAF_POLICY_NAME,
            "policyMode": WAF_MODE,
            "action": action,
            "host": host,
            "details": {
                "matches": [
                    {
                        "matchVariableName": match_variable_name,
                        "matchVariableValue": match_variable_value[:100],  # Max 100 chars
                    }
                ]
            },
        },
    }

    with _lock:
        WAF_LOGS.append(log_entry)
        if len(WAF_LOGS) > MAX_LOGS:
            WAF_LOGS.pop(0)

    print(f"FRONTDOOR_WAF: {json.dumps(log_entry)}")
    return log_entry


def check_waf_rules(request_data: str, headers: dict, uri: str) -> list:
    """Check request against WAF rules and return matches."""
    matches = []

    # Combine all request data for checking
    check_targets = {
        "RequestBody": request_data,
        "RequestUri": uri,
        "QueryString": request.query_string.decode("utf-8") if request.query_string else "",
        "RequestHeaders": json.dumps(dict(headers)),
        "UserAgent": headers.get("User-Agent", ""),
    }

    for rule in WAF_RULES:
        pattern = rule.get("pattern", "")
        if not pattern:
            continue

        try:
            regex = re.compile(pattern, re.IGNORECASE)

            for target_name, target_value in check_targets.items():
                if target_value and regex.search(target_value):
                    match = regex.search(target_value)
                    matches.append({
                        "rule": rule,
                        "match_variable_name": target_name,
                        "match_variable_value": match.group(0) if match else target_value[:50],
                    })
                    break  # One match per rule is enough
        except re.error as e:
            print(f"[FRONT_DOOR] Invalid regex in rule {rule.get('id')}: {e}")

    return matches


def proxy_request(tracking_ref: str):
    """Proxy the request to the backend App Service."""
    start_time = time.time()

    # Build backend URL
    backend_path = request.path
    if request.query_string:
        backend_path += "?" + request.query_string.decode("utf-8")

    backend_full_url = f"{BACKEND_URL}{backend_path}"

    try:
        # Forward the request
        resp = http_requests.request(
            method=request.method,
            url=backend_full_url,
            headers={k: v for k, v in request.headers if k.lower() not in ["host"]},
            data=request.get_data(),
            timeout=30,
            allow_redirects=False,
        )

        time_taken = time.time() - start_time

        return resp, backend_full_url, time_taken
    except Exception as e:
        print(f"[FRONT_DOOR] Backend error: {e}")
        return None, backend_full_url, time.time() - start_time


# ============================================
# HEALTH AND ADMIN ENDPOINTS
# ============================================

@app.route("/health", methods=["GET"])
@app.route("/healthz", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "azure-front-door",
        "waf_mode": WAF_MODE,
        "backend": BACKEND_URL,
        "rules_loaded": len(WAF_RULES),
    })


@app.route("/audit/logs", methods=["GET"])
def audit_logs():
    """Return logs for Azure Sentinel polling."""
    with _lock:
        # Combine access and WAF logs
        all_logs = list(ACCESS_LOGS[-100:]) + list(WAF_LOGS[-100:])
    return jsonify(all_logs)


@app.route("/waf/rules", methods=["GET"])
def get_waf_rules():
    """Return loaded WAF rules."""
    return jsonify({"rules": WAF_RULES, "mode": WAF_MODE})


@app.route("/waf/mode", methods=["POST"])
def set_waf_mode():
    """Change WAF mode at runtime."""
    global WAF_MODE
    data = request.get_json() or {}
    new_mode = data.get("mode", "detection").lower()
    if new_mode in ["detection", "prevention"]:
        WAF_MODE = new_mode
        return jsonify({"status": "updated", "mode": WAF_MODE})
    return jsonify({"error": "Invalid mode. Use 'detection' or 'prevention'"}), 400


@app.route("/logs/clear", methods=["POST"])
def clear_logs():
    """Clear all logs."""
    with _lock:
        ACCESS_LOGS.clear()
        WAF_LOGS.clear()
    return jsonify({"status": "cleared"})


# ============================================
# WAF PROXY - ALL OTHER REQUESTS
# ============================================

@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
@app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
def waf_proxy(path):
    """Main WAF proxy handler for all requests."""
    start_time = time.time()
    tracking_ref = generate_tracking_reference()

    # Get request details
    client_ip = request.remote_addr
    client_port = request.environ.get("REMOTE_PORT", 0)
    user_agent = request.headers.get("User-Agent", "")
    referrer = request.headers.get("Referer", "")
    request_data = request.get_data(as_text=True)
    request_uri = f"http://{ENDPOINT_NAME}{request.path}"
    if request.query_string:
        request_uri += "?" + request.query_string.decode("utf-8")

    # Check WAF rules
    waf_matches = check_waf_rules(request_data, dict(request.headers), request.path)

    # Log WAF matches
    should_block = False
    for match in waf_matches:
        rule = match["rule"]
        action = rule.get("action", "Log")

        log_waf_match(
            tracking_ref=tracking_ref,
            client_ip=client_ip,
            client_port=client_port,
            request_uri=request_uri,
            host=ENDPOINT_NAME,
            rule_id=rule.get("id", "UNKNOWN"),
            rule_name=rule.get("name", "Unknown Rule"),
            action=action if WAF_MODE == "prevention" else "Log",
            match_variable_name=match["match_variable_name"],
            match_variable_value=match["match_variable_value"],
        )

        if action == "Block" and WAF_MODE == "prevention":
            should_block = True

    # Block request if in prevention mode and rule says to block
    if should_block:
        time_taken = time.time() - start_time

        log_access(
            tracking_ref=tracking_ref,
            method=request.method,
            uri=request_uri,
            host=ENDPOINT_NAME,
            status_code=403,
            request_bytes=len(request_data),
            response_bytes=0,
            time_taken=time_taken,
            time_to_first_byte=time_taken,
            client_ip=client_ip,
            client_port=client_port,
            user_agent=user_agent,
            referrer=referrer,
            origin_url="N/A",
            origin_ip="N/A",
            error_info="NoError",
        )

        return jsonify({
            "error": "Request blocked by WAF",
            "trackingReference": tracking_ref,
        }), 403

    # Proxy to backend
    backend_resp, origin_url, proxy_time = proxy_request(tracking_ref)

    if backend_resp is None:
        time_taken = time.time() - start_time

        log_access(
            tracking_ref=tracking_ref,
            method=request.method,
            uri=request_uri,
            host=ENDPOINT_NAME,
            status_code=502,
            request_bytes=len(request_data),
            response_bytes=0,
            time_taken=time_taken,
            time_to_first_byte=time_taken,
            client_ip=client_ip,
            client_port=client_port,
            user_agent=user_agent,
            referrer=referrer,
            origin_url=origin_url,
            origin_ip=BACKEND_URL.split("//")[1].split(":")[0],
            error_info="OriginConnectionError",
        )

        return jsonify({
            "error": "Backend unavailable",
            "trackingReference": tracking_ref,
        }), 502

    time_taken = time.time() - start_time
    response_content = backend_resp.content

    # Log access
    log_access(
        tracking_ref=tracking_ref,
        method=request.method,
        uri=request_uri,
        host=ENDPOINT_NAME,
        status_code=backend_resp.status_code,
        request_bytes=len(request_data),
        response_bytes=len(response_content),
        time_taken=time_taken,
        time_to_first_byte=proxy_time,
        client_ip=client_ip,
        client_port=client_port,
        user_agent=user_agent,
        referrer=referrer,
        origin_url=origin_url,
        origin_ip=BACKEND_URL.split("//")[1].split(":")[0],
        error_info="NoError",
    )

    # Build response with X-Azure-Ref header
    excluded_headers = ["content-encoding", "content-length", "transfer-encoding", "connection"]
    headers = [(k, v) for k, v in backend_resp.raw.headers.items() if k.lower() not in excluded_headers]
    headers.append(("X-Azure-Ref", tracking_ref))

    return Response(response_content, status=backend_resp.status_code, headers=headers)


# ============================================
# STARTUP
# ============================================

if __name__ == "__main__":
    load_waf_rules()
    print(f"[FRONT_DOOR] Starting Azure Front Door Mock")
    print(f"[FRONT_DOOR] WAF Mode: {WAF_MODE}")
    print(f"[FRONT_DOOR] Backend: {BACKEND_URL}")
    print(f"[FRONT_DOOR] Endpoint: {ENDPOINT_NAME}")
    app.run(host="0.0.0.0", port=8080, debug=False)
