#!/bin/bash
# Build script for CTI Realm Domain Docker images

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

echo "🔨 Building CTI Realm Domain Images"
echo "===================================="

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

# Change to the domain root for building
cd ../../

# Build SABER server for CTI Realm domain
echo "📦 Building SABER server for CTI Realm domain..."
docker build -f server/docker/Dockerfile.server -t saber/cti_realm/server:latest .

# Build CTI Realm sandbox
echo "📦 Building CTI Realm sandbox..."
docker build -f server/docker/Dockerfile.sandbox -t saber/cti_realm/sandbox:latest .

# Verify images were built
echo "✅ Verifying built images..."
docker images | grep 'saber/cti_realm'

echo ""
echo "🎉 SABER CTI Realm images built successfully!"
echo ""
echo "Available images:"
echo "  • saber/cti_realm/server:latest        - SABER server for CTI Realm domain"
echo "  • saber/cti_realm/sandbox:latest       - Sandbox execution environment with CTI tools"
echo ""
echo "Services use public images:"
echo "  • mcr.microsoft.com/azuredataexplorer/kustainer-linux:latest - Kusto emulator"
echo "  • python:3.11-slim                     - MITRE service base"
echo ""
echo "Next steps:"
echo "  • Run: docker-compose -f ../config/environments/permanent/cti_realm_services.compose.yml up -d"
echo "  • Test: saber-domain test cti_realm"
echo ""
echo "💡 Use --full-build flag to force rebuild of base SABER images"
