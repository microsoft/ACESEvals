#!/bin/bash
# Cybench Benchmark - Quick Run Script
#
# This script runs the cybench demo using the unified SABER client entry point.

set -e

echo "🏁 Starting Cybench Benchmark with SABER Unified Client"
echo "=================================================="

# Default values
VERBOSE=""
CONSOLE_LOGS=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --verbose|-v)
            VERBOSE="--verbose"
            shift
            ;;
        --console-logs)
            CONSOLE_LOGS="--console-logs"
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "OPTIONS:"
            echo "  --verbose, -v     Enable verbose logging"
            echo "  --console-logs    Show logs on console instead of file"
            echo "  --help, -h        Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                          # Standard execution with file logging"
            echo "  $0 --verbose               # Verbose logging to file"
            echo "  $0 --console-logs          # Show all logs on console"
            echo "  $0 --verbose --console-logs # Verbose console logging"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

echo "🔧 Configuration:"
if [[ -n "$VERBOSE" ]]; then
    echo "  • Verbose logging enabled"
fi

if [[ -n "$CONSOLE_LOGS" ]]; then
    echo "  • Console logging enabled"
else
    echo "  • Logs will be saved to file for cleaner output"
fi

echo ""

# Build the command
CMD="uv run python -m saber.client run --config /app/client/saber.yaml"

# Add logging options
if [[ -n "$VERBOSE" ]]; then
    CMD="$CMD $VERBOSE"
fi

if [[ -n "$CONSOLE_LOGS" ]]; then
    CMD="$CMD --no-log-file"
fi

echo "🚀 Executing: docker exec -it saber-cybench-client $CMD"
echo ""

# Execute the command
docker exec -it saber-cybench-client $CMD

EXIT_CODE=$?

echo ""
if [[ $EXIT_CODE -eq 0 ]]; then
    echo "🎉 Demo completed successfully!"
else
    echo "❌ Demo failed with exit code: $EXIT_CODE"
fi

exit $EXIT_CODE
