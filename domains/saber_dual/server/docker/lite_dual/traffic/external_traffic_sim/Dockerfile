# External Traffic Simulator Container
# Creates realistic external DMZ traffic patterns for SABER dual simulation

FROM python:3.11-slim

# Container metadata
LABEL maintainer="SABER Dual Traffic Simulation"
LABEL description="External traffic simulator for DMZ network patterns"
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
    /app/src

# Copy source code (only copy what exists)
COPY src/ /app/src/

# Install Python dependencies
# Use minimal dependencies for traffic simulation
RUN pip install --no-cache-dir \
    aiohttp==3.9.1 \
    aiofiles==23.2.1 \
    python-multipart==0.0.6 \
    pydantic==2.5.2

# Set Python path to include source
ENV PYTHONPATH="/app:/app/src"

# Environment variables with sensible defaults
ENV WEBAPP_URL="http://webapp:80"
ENV SIMULATION_DURATION="300"
ENV LOG_LEVEL="INFO"
ENV PATTERN_RANDOMIZATION="true"

# External traffic specific variables
ENV EMPLOYEE_ACCESS_ENABLED="true"
ENV ADMIN_MAINTENANCE_ENABLED="true"
ENV COMPLIANCE_AUDIT_ENABLED="true"
ENV RED_HERRINGS_ENABLED="true"

# Timing configuration
ENV EMPLOYEE_ACCESS_INTERVAL_MIN="60"
ENV EMPLOYEE_ACCESS_INTERVAL_MAX="90"
ENV ADMIN_MAINTENANCE_INTERVAL_MIN="90"
ENV ADMIN_MAINTENANCE_INTERVAL_MAX="120"
ENV COMPLIANCE_AUDIT_INTERVAL_MIN="120"
ENV COMPLIANCE_AUDIT_INTERVAL_MAX="180"
ENV RED_HERRING_INTERVAL_MIN="45"
ENV RED_HERRING_INTERVAL_MAX="75"

# Create non-root user for security
RUN groupadd -r traffic && useradd -r -g traffic traffic

# Set ownership of application directories
RUN chown -R traffic:traffic /app /var/log/traffic

# Switch to non-root user
USER traffic

# Health check to verify container is functioning
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.path.append('/app/src'); from main import ExternalTrafficSimulator; print('Container healthy')" || exit 1

# Default command
CMD ["python", "/app/src/main.py"]