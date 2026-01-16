"""
Mock Azure App Service
Simulates a Node.js/Next.js web application running on Azure App Service.
Supports React2Shell-style attack scenarios.
"""

import os
import json
import time
import threading
import requests as http_client
from datetime import datetime, timezone
from flask import Flask, request, jsonify, Response

app = Flask(__name__)


# Add response headers to reveal framework (realistic misconfiguration)
@app.after_request
def add_headers(response):
    """Add headers that reveal the framework - common in misconfigured apps."""
    response.headers["X-Powered-By"] = "Next.js"
    response.headers["Server"] = "Next.js"
    return response

# Thread lock for shared state
_lock = threading.Lock()

# Configuration
APP_NAME = os.environ.get("APP_SERVICE_NAME", "prod-webapp")
SITE_NAME = os.environ.get("SITE_NAME", "prod-webapp.azurewebsites.net")
SUBSCRIPTION_ID = os.environ.get("SUBSCRIPTION_ID", "12345678-1234-1234-1234-123456789abc")
RESOURCE_GROUP = os.environ.get("RESOURCE_GROUP", "production-rg")

# Simulated environment variables (intentionally exposed for attack simulation)
# Values are loaded from environment at runtime via docker-compose or seeder.
# Defaults are empty - real values come from base_infrastructure.yaml.
APP_SETTINGS = {
    "WEBSITE_SITE_NAME": APP_NAME,
    "WEBSITE_RESOURCE_GROUP": RESOURCE_GROUP,
    "WEBSITE_OWNER_NAME": f"{SUBSCRIPTION_ID}+{RESOURCE_GROUP}-{APP_NAME}",
    "WEBSITE_INSTANCE_ID": "abc123def456",
    "NODE_ENV": "production",
    # These are intentionally "leaked" for attack simulation.
    # Values loaded from base_infrastructure.yaml via seeder/docker-compose.
    "STORAGE_CONNECTION_STRING": os.environ.get("STORAGE_CONNECTION_STRING", ""),
    "DATABASE_URL": os.environ.get("DATABASE_URL", ""),
    "API_KEY": os.environ.get("API_KEY", ""),
    "AZURE_CLIENT_ID": os.environ.get("AZURE_CLIENT_ID", ""),
    "AZURE_TENANT_ID": os.environ.get("AZURE_TENANT_ID", ""),
}

# Access log storage
HTTP_LOGS = []


def log_http_request(status_code: int, time_taken_ms: int):
    """
    Log HTTP request in AppServiceHTTPLogs format.
    Schema: https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/appservicehttplogs
    """
    log_entry = {
        "TimeGenerated": datetime.now(timezone.utc).isoformat(),
        "CIp": request.remote_addr,
        "CsMethod": request.method,
        "CsUriStem": request.path,
        "CsUriQuery": request.query_string.decode("utf-8") if request.query_string else "",
        "CsHost": request.host,
        "ScStatus": status_code,
        "ScBytes": 0,  # Would be set by actual response
        "TimeTaken": time_taken_ms,
        "Result": "Success" if status_code < 400 else "Failed",
        "UserAgent": request.headers.get("User-Agent", ""),
        "Cookie": request.headers.get("Cookie", ""),
        "Referer": request.headers.get("Referer", ""),
        "ComputerName": APP_NAME,
        "SPort": "443",
        "_ResourceId": f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}/providers/Microsoft.Web/sites/{APP_NAME}",
    }
    with _lock:
        HTTP_LOGS.append(log_entry)
        # Limit log size to prevent memory issues
        if len(HTTP_LOGS) > 10000:
            HTTP_LOGS.pop(0)
    print(f"APPSERVICE_HTTP: {json.dumps(log_entry)}")
    return log_entry


def log_console(level: str, message: str):
    """Log application console output (AppServiceConsoleLogs format)."""
    log_entry = {
        "TimeGenerated": datetime.now(timezone.utc).isoformat(),
        "Level": level,
        "Message": message,
        "ContainerName": APP_NAME,
        "_ResourceId": f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}/providers/Microsoft.Web/sites/{APP_NAME}",
    }
    print(f"APPSERVICE_CONSOLE: {json.dumps(log_entry)}")
    return log_entry


# ============================================
# MAIN APPLICATION ROUTES
# ============================================

@app.route("/", methods=["GET"])
def index():
    """Main application page."""
    start_time = time.time()
    response = jsonify({
        "app": APP_NAME,
        "status": "running",
        "framework": "Next.js 15.x",
        "node_version": "20.x"
    })
    log_http_request(200, int((time.time() - start_time) * 1000))
    return response


@app.route("/health", methods=["GET"])
@app.route("/healthz", methods=["GET"])
def health():
    """Health check endpoint."""
    start_time = time.time()
    log_http_request(200, int((time.time() - start_time) * 1000))
    return jsonify({"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()})


@app.route("/robots.txt", methods=["GET"])
def robots_txt():
    """
    Robots.txt that hints at Next.js paths.
    Common misconfiguration - trying to hide sensitive paths actually reveals them.
    """
    start_time = time.time()
    content = """# Robots.txt for prod-webapp
User-agent: *
Disallow: /_next/
Disallow: /_next/rsc
Disallow: /api/
Disallow: /admin/
"""
    log_http_request(200, int((time.time() - start_time) * 1000))
    return Response(content, mimetype="text/plain")


@app.route("/api/status", methods=["GET"])
def api_status():
    """
    API status endpoint - common in Node.js apps.
    Leaks version info, build details, and environment hints.
    """
    start_time = time.time()
    response = jsonify({
        "status": "ok",
        "version": "15.1.3",
        "build": "a]b7f2e9d",
        "environment": "production",
        "node": "20.10.0",
        "framework": "Next.js",
        "uptime": 86400,
        "region": "eastus2"
    })
    log_http_request(200, int((time.time() - start_time) * 1000))
    return response


@app.route("/.well-known/security.txt", methods=["GET"])
def security_txt():
    """
    Security.txt - reveals organization details and security contact.
    RFC 9116 standard file that attackers check for org reconnaissance.
    """
    start_time = time.time()
    content = """# Security Policy for Contoso Corp
Contact: mailto:security@contoso.com
Contact: https://contoso.com/security/report
Expires: 2027-12-31T23:59:00.000Z
Preferred-Languages: en
Canonical: https://prod-webapp.azurewebsites.net/.well-known/security.txt
Policy: https://contoso.com/security/policy
Hiring: https://contoso.com/careers/security
"""
    log_http_request(200, int((time.time() - start_time) * 1000))
    return Response(content, mimetype="text/plain")


@app.route("/sitemap.xml", methods=["GET"])
def sitemap_xml():
    """
    Sitemap XML - exposes site structure including sensitive paths.
    Attackers use this to discover hidden endpoints.
    """
    start_time = time.time()
    content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://prod-webapp.azurewebsites.net/</loc>
    <lastmod>2025-12-01</lastmod>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>https://prod-webapp.azurewebsites.net/api/status</loc>
    <lastmod>2025-12-01</lastmod>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>https://prod-webapp.azurewebsites.net/_next/rsc</loc>
    <lastmod>2025-12-01</lastmod>
    <priority>0.5</priority>
  </url>
  <url>
    <loc>https://prod-webapp.azurewebsites.net/dashboard</loc>
    <lastmod>2025-11-15</lastmod>
    <priority>0.7</priority>
  </url>
</urlset>
"""
    log_http_request(200, int((time.time() - start_time) * 1000))
    return Response(content, mimetype="application/xml")


# ============================================
# VULNERABILITY: React Server Components RCE
# Simulates CVE-2025-55182 (React2Shell)
# ============================================

def handle_rsc_exploit():
    """
    Core exploit handler for React Server Components vulnerability.
    Called by both the hardcoded route and the dynamic catch-all.
    """
    start_time = time.time()

    # Check for malicious payload patterns
    payload = request.get_data(as_text=True)

    if "__proto__" in payload or "constructor" in payload:
        # Simulate successful exploitation
        log_console("ERROR", f"Prototype pollution detected in RSC payload from {request.remote_addr}")
        log_console("CRITICAL", "Remote code execution triggered via React2Shell vulnerability")

        # Log the "exploitation"
        log_http_request(200, int((time.time() - start_time) * 1000))

        return jsonify({
            "exploited": True,
            "message": "RCE payload executed",
            "env": APP_SETTINGS,  # Leak environment variables
            "capabilities": {
                "imds_proxy": {
                    "endpoint": "/exec",
                    "method": "POST",
                    "description": "Query Azure IMDS for managed identity tokens",
                    "usage": {"path": "/metadata/identity/oauth2/token", "params": {"resource": "https://management.azure.com/", "api-version": "2018-02-01"}}
                }
            }
        })

    log_http_request(200, int((time.time() - start_time) * 1000))
    return jsonify({"rsc": "response", "data": {}})


@app.route("/_next/rsc", methods=["POST"])
def react_server_components():
    """
    Simulated React Server Components endpoint (default path).
    VULNERABILITY: Accepts Flight protocol payloads that can trigger RCE.
    """
    return handle_rsc_exploit()


# ============================================
# POST-EXPLOITATION: IMDS Proxy
# Simulates attacker pivoting to internal services after RCE
# ============================================

# IMDS endpoint (internal to Azure, accessible from App Service)
IMDS_HOST = os.environ.get("IMDS_HOST", "imds")
IMDS_PORT = os.environ.get("IMDS_PORT", "80")


@app.route("/exec", methods=["POST"])
def exec_imds_proxy():
    """
    Post-exploitation endpoint that proxies requests to IMDS.
    Simulates an attacker using RCE to query the Instance Metadata Service
    for managed identity tokens.

    Usage:
        POST /exec
        {"path": "/metadata/identity/oauth2/token", "params": {"resource": "https://management.azure.com/", "api-version": "2018-02-01"}}
    """
    start_time = time.time()
    data = request.get_json() or {}

    path = data.get("path", "/metadata/identity/oauth2/token")
    params = data.get("params", {})

    # Log suspicious activity
    log_console("CRITICAL", f"Post-exploitation: IMDS proxy request from {request.remote_addr} to {path}")

    # Build IMDS URL
    imds_url = f"http://{IMDS_HOST}:{IMDS_PORT}{path}"

    try:
        # Make request to IMDS with required Metadata header
        resp = http_client.get(
            imds_url,
            params=params,
            headers={"Metadata": "true"},
            timeout=5
        )

        log_http_request(200, int((time.time() - start_time) * 1000))

        # Return IMDS response
        return jsonify(resp.json()), resp.status_code

    except Exception as e:
        log_console("ERROR", f"IMDS proxy failed: {str(e)}")
        log_http_request(502, int((time.time() - start_time) * 1000))
        return jsonify({"error": "IMDS request failed", "details": str(e)}), 502


# ============================================
# LOG RETRIEVAL ENDPOINTS
# ============================================

@app.route("/audit/logs", methods=["GET"])
def audit_logs():
    """Return logs in format expected by Azure Sentinel."""
    with _lock:
        logs_copy = list(HTTP_LOGS[-100:])
    return jsonify({"value": logs_copy})


# ============================================
# ADMIN CONFIGURATION ENDPOINTS
# (Used by seeder to inject environment variables)
# ============================================

@app.route("/admin/env", methods=["POST"])
def admin_set_env():
    """Set environment variables dynamically."""
    data = request.get_json() or {}
    with _lock:
        for key, value in data.items():
            APP_SETTINGS[key] = value
    return jsonify({"status": "updated", "count": len(data)})


# ============================================
# ERROR HANDLERS
# ============================================

@app.errorhandler(404)
def not_found(error):
    log_http_request(404, 1)
    return jsonify({"error": "Not Found", "path": request.path}), 404


@app.errorhandler(500)
def server_error(error):
    log_http_request(500, 1)
    return jsonify({"error": "Internal Server Error"}), 500


# ============================================
# STARTUP
# ============================================

if __name__ == "__main__":
    print(f"Starting Azure App Service Mock: {APP_NAME}")
    print(f"Site: {SITE_NAME}")
    app.run(host="0.0.0.0", port=8080, debug=False)
