#!/bin/bash
# Build script for Cybench Domain Docker images

set -e

# Parse command line arguments
FULL_BUILD=false
SPECIFIC_CHALLENGE=""

for arg in "$@"; do
    case $arg in
        --full-build)
            FULL_BUILD=true
            shift
            ;;
        --challenge=*)
            SPECIFIC_CHALLENGE="${arg#*=}"
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--full-build] [--challenge=CHALLENGE_NAME] [-h|--help]"
            echo ""
            echo "  --full-build               Force rebuild of base SABER images first"
            echo "  --challenge=CHALLENGE_NAME Build only a specific challenge"
            echo "  -h, --help                 Show this help"
            exit 0
            ;;
        *)
            echo "Unknown option: $arg"
            exit 1
            ;;
    esac
done

echo "🔨 Building Cybench Domain Images"
echo "=================================="

# Get the directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
cd "$SCRIPT_DIR"

# Ensure base images are built first
if [ "$FULL_BUILD" = true ]; then
    echo "🔄 Full build requested - rebuilding base SABER images..."
    cd ../../docker
    ./build-images.sh
    cd "$SCRIPT_DIR"
elif ! docker images | grep -q 'saber/server'; then
    echo "🔍 Checking for SABER base images..."
    echo "⚠️  Base images not found. Building base images first..."
    cd ../../docker
    ./build-images.sh
    cd "$SCRIPT_DIR"
else
    echo "✅ Base images found"
fi

# Build Cybench sandbox
echo "📦 Building Cybench sandbox..."
docker build -f Dockerfile.sandbox -t saber/cybench/sandbox:latest ../

echo ""
echo "🕵️ Scanning challenges directory for challenge-specific images..."

CHALLENGES_DIR="./challenges"
BUILT_IMAGES=()

if [ ! -d "$CHALLENGES_DIR" ]; then
    echo "⚠️  No challenges directory found at $CHALLENGES_DIR"
    exit 1
fi

# Function to build a specific challenge
build_challenge() {
    local challenge_name="$1"
    local challenge_dir="$CHALLENGES_DIR/$challenge_name"
    
    echo "📦 Building challenge: $challenge_name"
    
    # Look for Dockerfiles in the challenge directory
    local dockerfiles=($(find "$challenge_dir" -name "Dockerfile.*" -type f))
    
    if [ ${#dockerfiles[@]} -eq 0 ]; then
        echo "⚠️  No Dockerfiles found in $challenge_dir, skipping..."
        return
    fi
    
    for dockerfile in "${dockerfiles[@]}"; do
        # Extract the service type from Dockerfile name (e.g., Dockerfile.victim -> victim)
        local service_type=$(basename "$dockerfile" | sed 's/Dockerfile\.//')
        local image_name="saber/cybench/${challenge_name}-${service_type}:latest"
        
        echo "   🐳 Building $image_name from $dockerfile"
        
        # Build the image using the challenge directory as context
        if docker build -f "$dockerfile" -t "$image_name" "$challenge_dir"; then
            BUILT_IMAGES+=("$image_name")
            echo "   ✅ Successfully built $image_name"
        else
            echo "   ❌ Failed to build $image_name"
        fi
    done
}

# Build specific challenge or all challenges
if [ -n "$SPECIFIC_CHALLENGE" ]; then
    echo "🎯 Building specific challenge: $SPECIFIC_CHALLENGE"
    if [ -d "$CHALLENGES_DIR/$SPECIFIC_CHALLENGE" ]; then
        build_challenge "$SPECIFIC_CHALLENGE"
    else
        echo "❌ Challenge '$SPECIFIC_CHALLENGE' not found in $CHALLENGES_DIR"
        exit 1
    fi
else
    echo "🔍 Building all challenges found in $CHALLENGES_DIR"
    
    # Iterate through all subdirectories in challenges/
    for challenge_dir in "$CHALLENGES_DIR"/*/; do
        if [ -d "$challenge_dir" ]; then
            challenge_name=$(basename "$challenge_dir")
            build_challenge "$challenge_name"
        fi
    done
fi

# Verify images were built
if [ ${#BUILT_IMAGES[@]} -gt 0 ]; then
    echo ""
    echo "✅ Verifying built images..."
    docker images | grep 'saber/cybench'
    
    echo ""
    echo "🎉 SABER Cybench images built successfully!"
    echo ""
    echo "Built images:"
    echo "  • saber/cybench/sandbox:latest    - Sandbox execution environment"
    
    for image in "${BUILT_IMAGES[@]}"; do
        echo "  • $image"
    done
    
    echo ""
    echo "Next steps:"
    echo "  • Update compose files to use the new image tags"
    echo "  • Run: docker-compose up -d"
    echo ""
else
    echo ""
    echo "⚠️  No challenge images were built"
fi

echo "💡 Use --full-build flag to force rebuild of base SABER images"
echo "💡 Use --challenge=CHALLENGE_NAME to build only a specific challenge"