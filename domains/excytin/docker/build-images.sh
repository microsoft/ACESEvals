#!/bin/bash
# Build script for Excytin Demo Domain Docker images

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

echo "🔨 Building Excytin Demo Domain Images"
echo "======================================"

# Get the directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
cd "$SCRIPT_DIR"

# Ensure base images are built first
if [ "$FULL_BUILD" = true ]; then
    echo "🔄 Full build requested - rebuilding base SABER images..."
    cd ../../../docker
    ./build-images.sh
    cd "$SCRIPT_DIR"
elif ! docker images | grep -q 'saber/server'; then
    echo "🔍 Checking for SABER base images..."
    echo "⚠️  Base images not found. Building base images first..."
    cd ../../../docker
    ./build-images.sh
    cd "$SCRIPT_DIR"
else
    echo "✅ Base images found"
fi

echo ""
echo "📦 Building domain-specific images..."

# Build SABER server for excytin domain
echo "📦 Building SABER server for excytin domain..."
docker build -f Dockerfile.server -t saber/excytin/server:latest ../

# Build Excytin Demo client (needs repo root for external/ directory)
echo "📦 Building Excytin Demo client..."
docker build -f ./Dockerfile.client -t saber/excytin/client:latest ../../../

# Build Excytin Demo sandbox
echo "📦 Building Excytin Demo sandbox..."
docker build -f Dockerfile.sandbox -t saber/excytin/sandbox:latest ../

# Build custom MySQL images with SQL files for all incidents
echo "📦 Building custom MySQL images with SQL data..."
for dockerfile in db/Dockerfile.incident_*; do
    if [ -f "$dockerfile" ]; then
        incident_num=$(basename "$dockerfile" | sed 's/Dockerfile.incident_//')
        echo "  🗄️  Building incident-${incident_num} database..."
        docker build -f "$dockerfile" -t "saber/excytin/incident-${incident_num}:latest" ../
    fi
done

# Verify images were built
echo "✅ Verifying built images..."
docker images | grep 'saber/excytin'

echo ""
echo "🎉 SABER Excytin Demo images built successfully!"
echo ""
echo "Available images:"
echo "  • saber/excytin/server:latest     - SABER server for excytin domain"
echo "  • saber/excytin/client:latest     - Demo client for testing enhanced logging"
echo "  • saber/excytin/sandbox:latest    - Sandbox execution environment with mysql client"
echo "  • saber/excytin/incident-*:latest - Custom MySQL images with SQL data for all incidents"
echo ""
echo "Next steps:"
echo "  • Run: docker-compose up -d"
echo "  • Test: docker exec -it saber-excytin-client uv run demo_client.py"
echo ""
echo "💡 Use --full-build flag to force rebuild of base SABER images"
