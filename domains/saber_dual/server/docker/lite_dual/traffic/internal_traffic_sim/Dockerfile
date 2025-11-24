# Internal Traffic Simulator Container
# Creates realistic internal service-to-service traffic patterns for SABER dual simulation

FROM python:3.11-slim

# Container metadata
LABEL maintainer="SABER Dual Traffic Simulation"
LABEL description="Internal traffic simulator for service-to-service communication patterns"
LABEL version="1.0"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    dnsutils \
    net-tools \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Create required directories
RUN mkdir -p \
    /var/log/traffic \
    /app/src \
    /app/config \
    /app/patterns \
    /app/utils

# Copy source code
COPY src/ /app/src/
COPY config/ /app/config/
COPY patterns/ /app/patterns/
COPY utils/ /app/utils/

# Install Python dependencies
# Use minimal dependencies for internal traffic simulation
RUN pip install --no-cache-dir \
    requests==2.31.0 \
    pymysql==1.1.0

# Set Python path to include shared utilities
ENV PYTHONPATH="/app:/app/shared:/app/src"

# Environment variables with sensible defaults
ENV SIMULATION_DURATION="300"
ENV LOG_LEVEL="INFO"
ENV PATTERN_RANDOMIZATION="true"

# Internal service endpoints
ENV API_GATEWAY_URL="http://api_gateway:3000"
ENV VAULT_SERVICE_URL="http://vault_service:8200"
ENV DATABASE_URL="mysql://database:3306"
ENV SIEM_AGGREGATOR_URL="http://siem_aggregator:8000"

# Internal service credentials
ENV API_GATEWAY_TOKEN="internal_api_token_12345"
ENV VAULT_TOKEN="internal_vault_token_67890"
ENV DB_USER="internal_user"
ENV DB_PASSWORD="internal_pass_2024"
ENV SIEM_API_KEY="siem_internal_key_abc123"

# Pattern enablement
ENV API_VAULT_PATTERN_ENABLED="true"
ENV DB_QUERIES_PATTERN_ENABLED="true"
ENV HEALTH_MONITORING_PATTERN_ENABLED="true"
ENV LOG_AGGREGATION_PATTERN_ENABLED="true"

# Timing configuration for internal patterns
ENV API_VAULT_INTERVAL_MIN="30"
ENV API_VAULT_INTERVAL_MAX="60"
ENV DB_QUERIES_INTERVAL_MIN="15"
ENV DB_QUERIES_INTERVAL_MAX="45"
ENV HEALTH_MONITORING_INTERVAL_MIN="20"
ENV HEALTH_MONITORING_INTERVAL_MAX="40"
ENV LOG_AGGREGATION_INTERVAL_MIN="25"
ENV LOG_AGGREGATION_INTERVAL_MAX="50"

# Internal timing settings
ENV INTERNAL_STARTUP_DELAY_MIN="5"
ENV INTERNAL_STARTUP_DELAY_MAX="15"
ENV INTERNAL_JITTER_FACTOR="0.1"
ENV INTERNAL_BURST_PROBABILITY="0.05"
ENV INTERNAL_BURST_MULTIPLIER="3.0"

# Create non-root user for security
RUN groupadd -r traffic && useradd -r -g traffic traffic

# Set ownership of application directories
RUN chown -R traffic:traffic /app /var/log/traffic

# Switch to non-root user
USER traffic

# Health check to verify container is functioning
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.path.append('/app/src'); from main import InternalTrafficSimulator; print('Internal container healthy')" || exit 1

# Default command
CMD ["python", "/app/src/main.py"]