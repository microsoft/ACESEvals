#!/bin/bash
# Build script for SABER_dual Docker images

set -e

# Parse command line arguments
FULL_BUILD=false
for arg in "$@"; do
    case $arg in
        --full-build)
            FULL_BUILD=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--full-build] [-h|--help]"
            echo ""
            echo "  --full-build    Force rebuild of base SABER images first"
            echo "  -h, --help      Show this help"
            exit 0
            ;;
        *)
            echo "Unknown option: $arg"
            exit 1
            ;;
    esac
done

echo "🔨 Building SABER_dual Images"
echo "============================="

# Get the directory of this script and go to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." &> /dev/null && pwd)"
cd "$PROJECT_ROOT"

# Ensure base SABER images are built first if needed
if [ "$FULL_BUILD" = true ]; then
    echo "🔄 Full build requested - rebuilding base SABER images..."
    cd external/saber/docker
    ./build-images.sh
    cd "$PROJECT_ROOT"
elif ! docker images | grep -q 'saber/server'; then
    echo "🔍 Checking for SABER base images..."
    echo "⚠️  Base images not found. Building base SABER images first..."
    cd external/saber/docker
    ./build-images.sh
    cd "$PROJECT_ROOT"
else
    echo "✅ Base SABER images found"
fi

echo ""
echo "📦 Building SABER_dual specific images..."

# Build SABER components for dual environment
echo "📦 Building SABER_dual server..."
docker build -f Dockerfile.server -t saber/saber_dual/server:latest ../

echo "📦 Building SABER_dual client..."  
docker build -f Dockerfile.client -t saber/saber_dual/client:latest ../

echo "📦 Building SABER_dual sandbox..."
docker build -f Dockerfile.sandbox -t saber/saber_dual/sandbox:latest ../

echo ""
echo "📦 Building cyber simulation environment images..."

# Build cyber simulation components
echo "📦 Building vulnerable webapp..."
docker build -f lite_dual/webapp/Dockerfile -t saber/saber_dual/webapp:latest lite_dual/webapp/

echo "📦 Building internal API gateway..."
docker build -f lite_dual/api_gateway/Dockerfile -t saber/saber_dual/api-gateway:latest lite_dual/api_gateway/

echo "📦 Building vault service..."
docker build -f lite_dual/vault/Dockerfile -t saber/saber_dual/vault:latest lite_dual/vault/

echo "📦 Building SIEM aggregator..."
docker build -f lite_dual/siem_aggregator/Dockerfile -t saber/saber_dual/siem:latest lite_dual/siem_aggregator/

echo "📦 Building database..."
docker build -f lite_dual/database/Dockerfile -t saber/saber_dual/database:latest lite_dual/database/

echo "📦 Building traffic simulation containers..."

echo "📦 Building external traffic simulator..."
docker build -f lite_dual/traffic/external_traffic_sim/Dockerfile -t saber/saber_dual/external-traffic:latest lite_dual/traffic/external_traffic_sim/

echo "📦 Building internal traffic simulator..."
docker build -f lite_dual/traffic/internal_traffic_sim/Dockerfile -t saber/saber_dual/internal-traffic:latest lite_dual/traffic/internal_traffic_sim/

# Verify images were built
echo ""
echo "✅ Verifying built images..."
docker images | grep 'saber/saber_dual'

echo ""
echo "🎉 SABER_dual images built successfully!"
echo ""
echo "Available images:"
echo "  📊 SABER Components:"
echo "    • saber/dual-server:latest     - SABER server for dual environment"
echo "    • saber/dual-client:latest     - SABER client for dual environment"
echo "    • saber/dual-sandbox:latest    - SABER sandbox with MySQL client"
echo ""
echo "  🎯 Cyber Simulation Environment:"
echo "    • saber/dual-webapp:latest     - Vulnerable web application (PHP/Apache)"
echo "    • saber/dual-api-gateway:latest - Internal API gateway (Node.js)"
echo "    • saber/dual-vault:latest      - Vault service with secrets (Node.js)"
echo "    • saber/dual-siem:latest       - SIEM aggregator for blue team analysis (Python/FastAPI)"
echo "    • saber/dual-database:latest   - MySQL with simulation data"
echo ""
echo "  🚦 Traffic Simulation:"
echo "    • saber/dual-external-traffic:latest - External traffic simulator (DMZ network)"
echo "    • saber/dual-internal-traffic:latest - Internal traffic simulator (service-to-service)"
echo ""
echo "Next steps:"
echo "  • Use these images in SABER domain configurations"
echo "  • Deploy via SABER server orchestration"
echo ""
echo "💡 Use --full-build flag to force rebuild of base SABER images"