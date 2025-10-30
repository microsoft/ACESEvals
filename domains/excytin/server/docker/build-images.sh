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
    cd ../../../../external/saber/docker
    ./build-images.sh
    cd "$SCRIPT_DIR"
elif ! docker images | grep -q 'saber/server'; then
    echo "🔍 Checking for SABER base images..."
    echo "⚠️  Base images not found. Building base images first..."
    cd ../../../../external/saber/docker
    ./build-images.sh
    cd "$SCRIPT_DIR"
else
    echo "✅ Base images found"
fi

echo ""
echo "📦 Building domain-specific images..."

# Build SABER server for excytin domain
echo "📦 Building SABER server for excytin domain..."
docker build -f Dockerfile.server -t saber/excytin/server:latest ../../..

# Build Excytin Demo client (needs repo root for external/ directory)
echo "📦 Building Excytin Demo client..."
docker build -f ./Dockerfile.client -t saber/excytin/client:latest ../../../../../

# Build Excytin Demo sandbox
echo "📦 Building Excytin Demo sandbox..."
docker build -f Dockerfile.sandbox -t saber/excytin/sandbox:latest ../../..

# Build custom MySQL images with SQL files for all incidents
echo ""
echo "📦 Building custom MySQL images with SQL data..."
echo "================================================"

# Array of incidents to build
INCIDENTS=(5 34 38 39 55 134 166 322)
INCIDENT_BUILD_FAILED=false

for incident in "${INCIDENTS[@]}"; do
    echo "  🗄️  Building incident-${incident} database..."
    if docker build -f db/Dockerfile.incident_${incident} -t saber/excytin/incident-${incident}:latest ../../..; then
        echo "     ✅ incident-${incident} built successfully"
    else
        echo "     ❌ incident-${incident} build failed"
        INCIDENT_BUILD_FAILED=true
    fi
done

if [ "$INCIDENT_BUILD_FAILED" = true ]; then
    echo ""
    echo "⚠️  Some incident database images failed to build"
    echo "   Check the errors above for details"
    exit 1
fi

echo ""
echo "✅ All incident database images built successfully!"

# Verify images were built
echo ""
echo "✅ Verifying built images..."
docker images | grep 'saber/excytin'

echo ""
echo "🎉 SABER Excytin images built successfully!"
echo ""
echo "Available images:"
echo "  • saber/excytin/server:latest       - SABER server for excytin domain"
echo "  • saber/excytin/client:latest       - Demo client for testing enhanced logging"
echo "  • saber/excytin/sandbox:latest      - Sandbox execution environment with mysql client"
echo "  • saber/excytin/incident-5:latest   - MySQL database for Incident 5 (port 3306)"
echo "  • saber/excytin/incident-34:latest  - MySQL database for Incident 34 (port 3307)"
echo "  • saber/excytin/incident-38:latest  - MySQL database for Incident 38 (port 3308)"
echo "  • saber/excytin/incident-39:latest  - MySQL database for Incident 39 (port 3309)"
echo "  • saber/excytin/incident-55:latest  - MySQL database for Incident 55 (port 3310)"
echo "  • saber/excytin/incident-134:latest - MySQL database for Incident 134 (port 3311)"
echo "  • saber/excytin/incident-166:latest - MySQL database for Incident 166 (port 3312)"
echo "  • saber/excytin/incident-322:latest - MySQL database for Incident 322 (port 3313)"
echo ""
echo "Next steps:"
echo "  • Run: docker-compose up -d"
echo "  • Test: docker exec -it saber-excytin-client uv run demo_client.py"
echo ""
echo "💡 Use --full-build flag to force rebuild of base SABER images"
