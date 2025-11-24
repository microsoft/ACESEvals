FROM python:3.11-alpine

# Install system dependencies for file watching and log parsing
RUN apk add --no-cache \
    gcc \
    musl-dev \
    linux-headers \
    libffi-dev \
    openssl-dev \
    curl \
    docker-cli

WORKDIR /app

# Copy requirements first for better Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY config/ ./config/

# Create directories for log processing
RUN mkdir -p /var/log/siem
RUN mkdir -p /var/log/containers

# Create non-root user for security (but we'll run as root in compose for Docker access)
RUN adduser -D -s /bin/sh siem_user

# Install sudo for potential privilege escalation if needed
RUN apk add --no-cache sudo

RUN chown -R siem_user:siem_user /app /var/log/siem

# Switch to non-root user
USER siem_user

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Expose SIEM API port
EXPOSE 8080

# Start SIEM aggregator service
CMD ["python", "-m", "src.main"]